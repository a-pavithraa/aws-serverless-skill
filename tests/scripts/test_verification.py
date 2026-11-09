"""Unit tests for verify_deployment.py with in-memory AWS and HTTP fakes.
The real-sandbox evidence is in docs/evidence/task-6-sandbox/."""

import base64
import contextlib
import hashlib
import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "skills" / "aws-iac-team-harness" / "scripts"))

import verify_deployment as vd  # noqa: E402

ACCOUNT, REGION = "111111111111", "us-east-1"
REQUEST_ID = "11111111-2222-3333-4444-555555555555"
TRACE_HEADER = "Root=1-6750a1b2-0123456789abcdef01234567;Parent=1a2b3c4d5e6f7a8b;Sampled=1"


class FakeClients:
    def __init__(self, project, *, account=ACCOUNT, code_sha=None, log_hits_after=0, trace_found=True,
                 alarms=None, subscriptions=None, residue=None, key_state="PendingDeletion",
                 live_mappings=()):
        self.project = project
        self.account = account
        self.code_sha = code_sha
        self.log_hits_after = log_hits_after
        self.log_calls = 0
        self.trace_found = trace_found
        self.alarms = alarms or {"svc-dev-lambda-errors": "OK"}
        self.subscriptions = subscriptions if subscriptions is not None else []
        self.residue = residue or []
        self.key_state = key_state
        self.live_mappings = set(live_mappings)
        self.calls = []

    def client(self, name):
        self.calls.append(name)
        return getattr(self, f"_{name.replace('-', '_')}")()

    def _sts(self):
        fake = self

        class Sts:
            def get_caller_identity(self):
                return {"Account": fake.account, "Arn": f"arn:aws:iam::{fake.account}:user/dev"}
        return Sts()

    def _lambda(self):
        fake = self

        class NotFound(Exception):
            pass

        class Lambda:
            exceptions = type("Exceptions", (), {"ResourceNotFoundException": NotFound})

            def get_function(self, FunctionName, Qualifier):
                return {"Configuration": {"CodeSha256": fake.code_sha, "Version": "3", "State": "Active",
                                          "LastUpdateStatus": "Successful"}}

            def get_event_source_mapping(self, UUID):
                if UUID not in fake.live_mappings:
                    raise NotFound(UUID)
                return {"UUID": UUID, "State": "Enabled"}
        return Lambda()

    def _logs(self):
        fake = self

        class Logs:
            def filter_log_events(self, **kwargs):
                fake.log_calls += 1
                if fake.log_calls <= fake.log_hits_after:
                    return {"events": []}
                sent = fake.http.requests[0]["headers"]["x-correlation-id"]
                return {"events": [{"message": json.dumps({"requestId": REQUEST_ID, "correlation_id": sent,
                                                           "message": "request handled"})}]}
        return Logs()

    def _xray(self):
        fake = self

        class XRay:
            def batch_get_traces(self, TraceIds):
                return {"Traces": [{"Id": TraceIds[0]}] if fake.trace_found else [], "UnprocessedTraceIds": []}
        return XRay()

    def _cloudwatch(self):
        fake = self

        class CloudWatch:
            def describe_alarms(self, AlarmNames):
                return {"MetricAlarms": [{"AlarmName": n, "StateValue": s} for n, s in fake.alarms.items()]}
        return CloudWatch()

    def _sns(self):
        fake = self

        class Sns:
            def list_subscriptions_by_topic(self, TopicArn):
                return {"Subscriptions": fake.subscriptions}
        return Sns()

    def _kms(self):
        fake = self

        class Kms:
            def describe_key(self, KeyId):
                return {"KeyMetadata": {"KeyState": fake.key_state, "DeletionDate": "2026-11-15T23:25:41+05:30"}}
        return Kms()

    def _resourcegroupstaggingapi(self):
        fake = self

        class Tagging:
            def get_resources(self, **kwargs):
                return {"ResourceTagMappingList": [{"ResourceARN": arn} for arn in fake.residue],
                        "PaginationToken": ""}
        return Tagging()


class FakeHttp:
    def __init__(self, status=200, unsigned_status=403, error=None, echo_correlation=True):
        self.status, self.unsigned_status, self.error, self.echo = status, unsigned_status, error, echo_correlation
        self.requests = []

    def __call__(self, method, url, headers, sign, body=None):
        self.requests.append({"url": url, "signed": sign, "headers": headers, "method": method, "body": body})
        if self.error:
            raise self.error
        if not sign and self.unsigned_status:
            return vd.HttpResponse(self.unsigned_status, {}, '{"message":"Forbidden"}')
        response_headers = {"x-lambda-request-id": REQUEST_ID, "x-trace-id": TRACE_HEADER,
                            "x-correlation-id": headers["x-correlation-id"] if self.echo else "other"}
        body = json.dumps({"message": "hello", "requestId": REQUEST_ID}) if self.status == 200 else '{"message":"Internal Server Error"}'
        return vd.HttpResponse(self.status, response_headers, body)


def zip_sha(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


class Project:
    def __init__(self, auth_mode="iam"):
        self.root = Path(tempfile.mkdtemp(prefix="verify-"))
        (self.root / "app").mkdir()
        (self.root / "app" / "handler.py").write_bytes(b"def handler(e, c):\n    return {}\n")
        (self.root / "infra" / "build").mkdir(parents=True)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            z.writestr("handler.py", "def handler(e, c):\n    return {}\n")
        self.zip_bytes = buffer.getvalue()
        (self.root / "infra" / "build" / "lambda.zip").write_bytes(self.zip_bytes)
        (self.root / ".verify").mkdir()
        (self.root / ".verify" / "probes.json").write_text(json.dumps({"probes": [{
            "name": "hello", "method": "GET", "path": "/hello", "expect_status": 200,
            "expect_json_keys": ["message", "requestId"], "unauthenticated_expect_status_when_iam": 403}]}),
            encoding="utf-8")
        self.outputs = {
            "account_id": ACCOUNT, "region": REGION, "api_url": "https://abc.execute-api.us-east-1.amazonaws.com/",
            "auth_mode": auth_mode, "function_name": "svc-dev", "function_alias": "live", "function_version": "3",
            "lambda_log_group": "/aws/lambda/svc-dev", "alarm_names": ["svc-dev-lambda-errors"],
            "alarm_topic_arn": f"arn:aws:sns:{REGION}:{ACCOUNT}:svc-dev-alarms",
            "artifact_path": "./build/lambda.zip",
        }

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class VerifierCase(unittest.TestCase):
    def verify(self, clients=None, http=None, outputs=None, **kwargs):
        clients = clients or FakeClients(self.project, code_sha=zip_sha(self.project.zip_bytes))
        self.http = http or FakeHttp()
        clients.http = self.http
        target = vd.Target(account=kwargs.pop("account", ACCOUNT), region=kwargs.pop("region", REGION))
        verifier = vd.Verifier(self.project.root, "infra", outputs or self.project.outputs, clients, self.http,
                               target, waits=vd.Waits(logs=3, traces=2, interval=1), sleep=lambda s: None)
        return verifier.run()

    def status(self, report, check_id):
        return next(c["status"] for c in report["checks"] if c["id"] == check_id)


class VerifyTest(VerifierCase):
    def setUp(self):
        self.project = Project()
        self.addCleanup(self.project.cleanup)

    def test_healthy_deployment_passes(self):
        report = self.verify()

        self.assertEqual(0, report["exit_code"], report)
        for check_id in ("target", "artifact", "probe:hello", "auth-rejection:hello", "logs:hello"):
            self.assertEqual("PASS", self.status(report, check_id), check_id)
        self.assertEqual([True, False], [r["signed"] for r in self.http.requests])

    def test_wrong_account_stops_before_any_probe(self):
        report = self.verify(account="222222222222")

        self.assertEqual(3, report["exit_code"])
        self.assertEqual("FAIL", self.status(report, "target"))
        self.assertEqual([], self.http.requests)

    def test_wrong_region_stops_before_any_probe(self):
        report = self.verify(region="eu-west-1")

        self.assertEqual(3, report["exit_code"])
        self.assertEqual([], self.http.requests)

    def test_outputs_from_another_account_stop_before_any_probe(self):
        report = self.verify(outputs={**self.project.outputs, "account_id": "333333333333"})

        self.assertEqual(3, report["exit_code"])
        self.assertEqual([], self.http.requests)

    def test_deployed_code_that_is_not_this_package_fails(self):
        report = self.verify(clients=FakeClients(self.project, code_sha=zip_sha(b"something else")))

        self.assertEqual(1, report["exit_code"])
        self.assertEqual("FAIL", self.status(report, "artifact"))

    def test_package_that_differs_from_app_source_fails(self):
        (self.project.root / "app" / "handler.py").write_text("changed\n", encoding="utf-8")

        report = self.verify()

        self.assertEqual("FAIL", self.status(report, "artifact"))
        self.assertIn("handler.py", json.dumps(report))

    def test_missing_local_package_is_unverified(self):
        (self.project.root / "infra" / "build" / "lambda.zip").unlink()

        report = self.verify()

        self.assertEqual("UNVERIFIED", self.status(report, "artifact"))
        self.assertEqual(2, report["exit_code"])

    def test_server_error_fails(self):
        report = self.verify(http=FakeHttp(status=502))

        self.assertEqual(1, report["exit_code"])
        self.assertEqual("FAIL", self.status(report, "probe:hello"))

    def test_unsigned_request_that_succeeds_fails(self):
        report = self.verify(http=FakeHttp(unsigned_status=None))

        self.assertEqual("FAIL", self.status(report, "auth-rejection:hello"))

    def test_public_api_is_not_probed_for_rejection(self):
        project = Project(auth_mode="none")
        self.addCleanup(project.cleanup)
        self.project = project

        report = self.verify()

        self.assertNotIn("auth-rejection:hello", [c["id"] for c in report["checks"]])
        self.assertTrue(all(not r["signed"] for r in self.http.requests))

    def test_network_timeout_is_unverified(self):
        report = self.verify(http=FakeHttp(error=TimeoutError("timed out")))

        self.assertEqual("UNVERIFIED", self.status(report, "probe:hello"))
        self.assertEqual(2, report["exit_code"])

    def test_logs_that_arrive_late_within_budget_pass(self):
        clients = FakeClients(self.project, code_sha=zip_sha(self.project.zip_bytes), log_hits_after=2)

        report = self.verify(clients=clients)

        self.assertEqual("PASS", self.status(report, "logs:hello"))

    def test_logs_missing_after_budget_are_unverified_not_pass(self):
        clients = FakeClients(self.project, code_sha=zip_sha(self.project.zip_bytes), log_hits_after=99)

        report = self.verify(clients=clients)

        self.assertEqual("UNVERIFIED", self.status(report, "logs:hello"))
        self.assertEqual(2, report["exit_code"])

    def test_unsampled_trace_is_reported_but_does_not_fail_the_deployment(self):
        clients = FakeClients(self.project, code_sha=zip_sha(self.project.zip_bytes), trace_found=False)

        report = self.verify(clients=clients)

        self.assertEqual("UNVERIFIED", self.status(report, "trace:hello"))
        self.assertEqual(0, report["exit_code"])

    def test_alerting_without_confirmed_subscription_is_reported(self):
        clients = FakeClients(self.project, code_sha=zip_sha(self.project.zip_bytes),
                              subscriptions=[{"Protocol": "email", "SubscriptionArn": "PendingConfirmation"}])

        report = self.verify(clients=clients)

        self.assertEqual("UNVERIFIED", self.status(report, "alerting"))

    def test_alarm_in_alarm_state_is_reported(self):
        clients = FakeClients(self.project, code_sha=zip_sha(self.project.zip_bytes),
                              alarms={"svc-dev-lambda-errors": "ALARM"})

        report = self.verify(clients=clients)

        self.assertEqual("FAIL", self.status(report, "alarms"))

    def test_summary_line_names_counts(self):
        report = self.verify()

        self.assertRegex(report["summary"], r"^verify-deployment: PASS \(pass \d+, fail 0, unverified \d+\)")


LOG_FILTER = re.compile(r'\$\.order_id = "([^"]+)" && \$\.message = "([^"]+)"')


class FakeSqsClients(FakeClients):
    """A worker that logs each delivery, processes each order once (unless idempotency is broken),
    and sends poison orders to the dead-letter queue after `dead_letter_after` receive calls."""

    def __init__(self, project, *, idempotent=True, processes=True, dead_letter_after=2, **kwargs):
        super().__init__(project, **kwargs)
        self.idempotent, self.processes, self.dead_letter_after = idempotent, processes, dead_letter_after
        self.sent, self.receive_calls, self.deleted = [], 0, []

    def _sqs(self):
        fake = self

        class Sqs:
            def send_message(self, QueueUrl, MessageBody):
                fake.sent.append({"queue": QueueUrl, "body": json.loads(MessageBody)})
                return {"MessageId": f"m-{len(fake.sent)}"}

            def receive_message(self, QueueUrl, **kwargs):
                fake.receive_calls += 1
                poison = [s["body"] for s in fake.sent if s["body"].get("action") == "fail"]
                if not poison or fake.dead_letter_after is None or fake.receive_calls < fake.dead_letter_after:
                    return {"Messages": []}
                return {"Messages": [{"Body": "not json", "ReceiptHandle": "other"},
                                     {"Body": json.dumps(poison[0]), "ReceiptHandle": "rh-1",
                                      "Attributes": {"ApproximateReceiveCount": "4"}}]}

            def delete_message(self, QueueUrl, ReceiptHandle):
                fake.deleted.append((QueueUrl, ReceiptHandle))
        return Sqs()

    def _logs(self):
        fake = self

        class Logs:
            def filter_log_events(self, filterPattern, **kwargs):
                order_id, text = LOG_FILTER.search(filterPattern).groups()
                bodies = [s["body"] for s in fake.sent if s["body"]["id"] == order_id]
                if text == "message received":
                    count = len(bodies)
                elif not fake.processes or any(b.get("action") == "fail" for b in bodies):
                    count = 0
                else:
                    count = min(len(bodies), 1) if fake.idempotent else len(bodies)
                return {"events": [{"message": json.dumps({"order_id": order_id, "message": text})}] * count}
        return Logs()


class SqsProject(Project):
    def __init__(self):
        super().__init__()
        (self.root / ".verify" / "probes.json").write_text(json.dumps({"probes": [
            {"name": "processed", "type": "sqs-processed", "message": {"action": "process"}},
            {"name": "processed-once", "type": "sqs-processed-once", "message": {"action": "process"}},
            {"name": "dead-letter", "type": "sqs-dead-letter", "message": {"action": "fail"},
             "trips_alarm": ["dlq-messages", "lambda-errors"]},
        ]}), encoding="utf-8")
        self.outputs = {
            "account_id": ACCOUNT, "region": REGION, "function_name": "svc-dev", "function_alias": "live",
            "function_version": "3", "lambda_log_group": "/aws/lambda/svc-dev",
            "queue_url": "https://sqs.us-east-1.amazonaws.com/111111111111/svc-dev-orders",
            "dead_letter_queue_url": "https://sqs.us-east-1.amazonaws.com/111111111111/svc-dev-dlq",
            "max_receive_count": 3, "visibility_timeout_seconds": 60,
            "alarm_names": ["svc-dev-lambda-errors", "svc-dev-dlq-messages", "svc-dev-oldest-message-age"],
            "alarm_topic_arn": f"arn:aws:sns:{REGION}:{ACCOUNT}:svc-dev-alarms",
            "artifact_path": "./build/lambda.zip",
        }


class SqsVerifyTest(VerifierCase):
    def setUp(self):
        self.project = SqsProject()
        self.addCleanup(self.project.cleanup)

    def clients(self, **kwargs):
        return FakeSqsClients(self.project, code_sha=zip_sha(self.project.zip_bytes), **kwargs)

    def test_healthy_worker_passes(self):
        clients = self.clients()

        report = self.verify(clients=clients)

        self.assertEqual(0, report["exit_code"], report)
        for check_id in ("probe:processed", "logs:processed", "probe:processed-once", "logs:processed-once",
                         "dead-letter:dead-letter"):
            self.assertEqual("PASS", self.status(report, check_id), check_id)
        self.assertEqual([], self.http.requests)

    def test_processed_once_sends_the_same_order_twice(self):
        clients = self.clients()

        self.verify(clients=clients)

        ids = [s["body"]["id"] for s in clients.sent if s["body"]["action"] == "process"]
        self.assertEqual(3, len(ids))
        self.assertEqual(2, len(set(ids)))
        self.assertTrue(all(s["queue"].endswith("-orders") for s in clients.sent))

    def test_order_processed_twice_fails(self):
        report = self.verify(clients=self.clients(idempotent=False))

        self.assertEqual("FAIL", self.status(report, "logs:processed-once"))
        self.assertEqual(1, report["exit_code"])

    def test_order_never_processed_is_unverified(self):
        report = self.verify(clients=self.clients(processes=False))

        self.assertEqual("UNVERIFIED", self.status(report, "logs:processed"))
        self.assertEqual(2, report["exit_code"])

    def test_dead_letter_message_is_deleted_after_it_is_found(self):
        clients = self.clients()

        self.verify(clients=clients)

        self.assertEqual([(self.project.outputs["dead_letter_queue_url"], "rh-1")], clients.deleted)

    def test_poison_message_missing_from_dead_letter_queue_is_unverified_after_the_redrive_budget(self):
        clients = self.clients(dead_letter_after=None)

        report = self.verify(clients=clients)

        self.assertEqual("UNVERIFIED", self.status(report, "dead-letter:dead-letter"))
        self.assertEqual(2, report["exit_code"])
        # (max_receive_count + 1) x visibility timeout + 60 s, polled every second, plus the first attempt
        self.assertEqual((3 + 1) * 60 + 60 + 1, clients.receive_calls)

    def test_alarm_the_dead_letter_probe_trips_is_expected(self):
        clients = self.clients(alarms={"svc-dev-lambda-errors": "OK", "svc-dev-dlq-messages": "ALARM",
                                       "svc-dev-oldest-message-age": "OK"})

        report = self.verify(clients=clients)

        self.assertEqual("PASS", self.status(report, "alarms"))
        self.assertIn("expected", next(c["detail"] for c in report["checks"] if c["id"] == "alarms"))

    def test_lambda_errors_from_the_poison_message_are_expected(self):
        # A batch whose every record fails raises BatchProcessingError, which Lambda counts as an error.
        clients = self.clients(alarms={"svc-dev-lambda-errors": "ALARM", "svc-dev-dlq-messages": "ALARM",
                                       "svc-dev-oldest-message-age": "OK"})

        report = self.verify(clients=clients)

        self.assertEqual("PASS", self.status(report, "alarms"))

    def test_other_alarm_firing_still_fails(self):
        clients = self.clients(alarms={"svc-dev-lambda-errors": "OK", "svc-dev-dlq-messages": "OK",
                                       "svc-dev-oldest-message-age": "ALARM"})

        report = self.verify(clients=clients)

        self.assertEqual("FAIL", self.status(report, "alarms"))


DIGEST = "sha256:" + "a" * 64
CLUSTER, SERVICE = "svc-dev", "svc-dev-web"
TG = f"arn:aws:elasticloadbalancing:{REGION}:{ACCOUNT}:targetgroup/ecs-gateway-tg/0123456789abcdef"


class FakeEcsClients(FakeClients):
    def __init__(self, project, *, task_digests=(DIGEST,), deployments=None, running=1, desired=1,
                 target_states=("healthy",), express=False, page_size=None, describe_failures=(), **kwargs):
        super().__init__(project, **kwargs)
        self.express = express
        self.page_size, self.describe_failures = page_size, list(describe_failures)
        self.task_digests = list(task_digests)
        self.deployments = deployments or [{"status": "PRIMARY", "rolloutState": "COMPLETED"}]
        self.running, self.desired = running, desired
        self.target_states = list(target_states)
        self.log_filters = []

    def _ecs(self):
        fake = self

        class Ecs:
            def describe_services(self, cluster, services):
                balancers = [] if fake.express else [{"targetGroupArn": TG, "containerPort": 8080}]
                return {"services": [{"serviceName": services[0], "status": "ACTIVE",
                                      "runningCount": fake.running, "desiredCount": fake.desired,
                                      "deployments": fake.deployments, "loadBalancers": balancers,
                                      "currentServiceRevisions": [{"arn": "rev-1"}]}]}

            def describe_service_revisions(self, serviceRevisionArns):
                return {"serviceRevisions": [{"serviceRevisionArn": serviceRevisionArns[0], "loadBalancers": [
                    {"targetGroupArn": TG + "-blue", "advancedConfiguration": {"alternateTargetGroupArn": TG}}]}]}

            def list_tasks(self, cluster, serviceName, desiredStatus, nextToken=None):
                arns = [f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/{cluster}/t{i}" for i in range(len(fake.task_digests))]
                start = int(nextToken or 0)
                end = len(arns) if fake.page_size is None else start + fake.page_size
                page = {"taskArns": arns[start:end]}
                if end < len(arns):
                    page["nextToken"] = str(end)
                return page

            def describe_tasks(self, cluster, tasks):
                digests = {f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/{cluster}/t{i}": d
                           for i, d in enumerate(fake.task_digests)}
                return {"tasks": [{"taskArn": arn, "containers": [{"name": "main", "imageDigest": digests[arn]}]}
                                  for arn in tasks if arn not in fake.describe_failures],
                        "failures": [{"arn": arn, "reason": "MISSING"} for arn in tasks if arn in fake.describe_failures]}
        return Ecs()

    def _elbv2(self):
        fake = self

        class Elbv2:
            def describe_target_health(self, TargetGroupArn):
                if TargetGroupArn.endswith("-blue"):
                    return {"TargetHealthDescriptions": []}
                return {"TargetHealthDescriptions": [
                    {"Target": {"Id": f"10.0.0.{i}", "Port": 8080}, "TargetHealth": {"State": state}}
                    for i, state in enumerate(fake.target_states)]}
        return Elbv2()

    def _logs(self):
        fake = self

        class Logs:
            def filter_log_events(self, filterPattern, **kwargs):
                fake.log_filters.append(filterPattern)
                sent = fake.http.requests[0]["headers"]["x-correlation-id"]
                return {"events": [{"message": json.dumps({"correlation_id": sent, "message": "request handled",
                                                           "status": 200})}]}
        return Logs()


class FakeEcsHttp(FakeHttp):
    def __init__(self, source_sha256, extra=None, **kwargs):
        super().__init__(unsigned_status=None, **kwargs)
        self.source_sha256, self.extra = source_sha256, extra or {}

    def __call__(self, method, url, headers, sign, body=None):
        self.requests.append({"url": url, "signed": sign, "headers": headers})
        body = json.dumps({"message": "hello", "source_sha256": self.source_sha256, **self.extra})
        return vd.HttpResponse(self.status, {"x-correlation-id": headers["x-correlation-id"]}, body)


class EcsProject:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="verify-ecs-"))
        (self.root / "app" / "tests").mkdir(parents=True)
        (self.root / "app" / "server.py").write_text("print('serve')\n", encoding="utf-8")
        (self.root / "app" / "tests" / "test_server.py").write_text("# not shipped\n", encoding="utf-8")
        (self.root / "infra").mkdir()
        (self.root / ".verify").mkdir()
        (self.root / ".verify" / "probes.json").write_text(json.dumps({"probes": [{
            "name": "hello", "method": "GET", "path": "/hello", "expect_status": 200,
            "expect_json_keys": ["message", "source_sha256"], "expect_source_hash": True}]}), encoding="utf-8")
        self.outputs = {
            "account_id": ACCOUNT, "region": REGION, "service_url": "https://svc-dev-web.ecs.us-east-1.on.aws/",
            "ecs_cluster_name": CLUSTER, "ecs_service_name": SERVICE, "image_digest": DIGEST,
            "log_group": "/ecs/svc-dev", "alarm_names": ["svc-dev-http-5xx"],
            "alarm_topic_arn": f"arn:aws:sns:{REGION}:{ACCOUNT}:svc-dev-alarms",
        }

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class EcsVerifyTest(VerifierCase):
    def setUp(self):
        self.project = EcsProject()
        self.addCleanup(self.project.cleanup)
        self.source = vd.source_hash(self.project.root / "app")

    def run_ecs(self, http=None, **kwargs):
        clients = FakeEcsClients(self.project, **kwargs)
        return clients, self.verify(clients=clients, http=http or FakeEcsHttp(self.source))

    def test_healthy_service_passes(self):
        clients, report = self.run_ecs()

        self.assertEqual(0, report["exit_code"], report)
        for check_id in ("target", "artifact", "health", "probe:hello", "logs:hello"):
            self.assertEqual("PASS", self.status(report, check_id), check_id)
        self.assertNotIn("auth-rejection:hello", [c["id"] for c in report["checks"]])
        self.assertEqual([False], [r["signed"] for r in self.http.requests])
        sent = self.http.requests[0]["headers"]["x-correlation-id"]
        self.assertTrue(all(sent in f for f in clients.log_filters), clients.log_filters)

    def expect_secrets(self, names):
        probes = self.project.root / ".verify" / "probes.json"
        config = json.loads(probes.read_text(encoding="utf-8"))
        config["probes"][0]["expect_json"] = {"secrets_loaded": names}
        probes.write_text(json.dumps(config), encoding="utf-8")

    def test_expected_json_values_pass(self):
        self.expect_secrets(["DB_PASSWORD"])

        _, report = self.run_ecs(http=FakeEcsHttp(self.source, extra={"secrets_loaded": ["DB_PASSWORD"]}))

        self.assertEqual("PASS", self.status(report, "probe:hello"), report)

    def test_missing_secret_in_the_response_fails_the_probe(self):
        self.expect_secrets(["DB_PASSWORD"])

        _, report = self.run_ecs(http=FakeEcsHttp(self.source, extra={"secrets_loaded": []}))

        self.assertEqual("FAIL", self.status(report, "probe:hello"))
        self.assertIn("secrets_loaded", json.dumps(report))

    def test_task_running_another_image_fails(self):
        _, report = self.run_ecs(task_digests=(DIGEST, "sha256:" + "b" * 64))

        self.assertEqual(1, report["exit_code"])
        self.assertEqual("FAIL", self.status(report, "artifact"))
        self.assertIn("b" * 64, json.dumps(report))

    def test_service_counting_a_task_that_list_tasks_does_not_return_fails(self):
        _, report = self.run_ecs(task_digests=(), running=1, desired=1)

        self.assertEqual(1, report["exit_code"], report)
        self.assertEqual("FAIL", self.status(report, "artifact"))

    def test_task_on_a_later_list_tasks_page_is_checked(self):
        _, report = self.run_ecs(task_digests=(DIGEST, "sha256:" + "b" * 64), running=2, desired=2, page_size=1)

        self.assertEqual("FAIL", self.status(report, "artifact"))
        self.assertIn("b" * 64, json.dumps(report))

    def test_task_that_describe_tasks_cannot_find_fails(self):
        arn = f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/{CLUSTER}/t0"
        _, report = self.run_ecs(describe_failures=(arn,))

        self.assertEqual("FAIL", self.status(report, "artifact"))
        self.assertIn("MISSING", json.dumps(report))

    def test_rollout_in_progress_fails(self):
        _, report = self.run_ecs(deployments=[{"status": "PRIMARY", "rolloutState": "IN_PROGRESS"},
                                              {"status": "ACTIVE", "rolloutState": "COMPLETED"}])

        self.assertEqual("FAIL", self.status(report, "artifact"))

    def test_fewer_running_tasks_than_desired_fails(self):
        _, report = self.run_ecs(running=0, desired=1, task_digests=())

        self.assertEqual("FAIL", self.status(report, "artifact"))

    def test_express_service_targets_are_read_from_its_revision(self):
        _, report = self.run_ecs(express=True)

        self.assertEqual("PASS", self.status(report, "health"), report)

    def test_express_service_with_an_unhealthy_target_fails(self):
        _, report = self.run_ecs(express=True, target_states=("healthy", "unhealthy"))

        self.assertEqual("FAIL", self.status(report, "health"))

    def test_unhealthy_target_fails(self):
        _, report = self.run_ecs(target_states=("healthy", "unhealthy"))

        self.assertEqual(1, report["exit_code"])
        self.assertEqual("FAIL", self.status(report, "health"))

    def test_no_registered_target_fails(self):
        _, report = self.run_ecs(target_states=())

        self.assertEqual("FAIL", self.status(report, "health"))

    def test_response_built_from_other_source_fails(self):
        _, report = self.run_ecs(http=FakeEcsHttp("0" * 64))

        self.assertEqual("FAIL", self.status(report, "probe:hello"))
        self.assertIn("source", next(c["detail"] for c in report["checks"] if c["id"] == "probe:hello"))


class SourceHashTest(unittest.TestCase):
    def setUp(self):
        self.project = EcsProject()
        self.addCleanup(self.project.cleanup)
        self.app = self.project.root / "app"

    def test_tests_and_bytecode_do_not_change_the_hash(self):
        before = vd.source_hash(self.app)
        (self.app / "tests" / "test_server.py").write_text("# edited\n", encoding="utf-8")
        (self.app / "__pycache__").mkdir()
        (self.app / "__pycache__" / "server.cpython-313.pyc").write_bytes(b"\x00")

        self.assertEqual(before, vd.source_hash(self.app))

    def test_source_edit_changes_the_hash(self):
        before = vd.source_hash(self.app)
        (self.app / "server.py").write_text("print('changed')\n", encoding="utf-8")

        self.assertNotEqual(before, vd.source_hash(self.app))

    def test_command_prints_the_hash_without_aws(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = vd.main(["source-hash", str(self.project.root)])

        self.assertEqual(0, code)
        self.assertEqual(vd.source_hash(self.app), out.getvalue().strip())


DEFINITION = {"StartAt": "Process", "TimeoutSeconds": 10,
              "States": {"Process": {"Type": "Pass", "End": True}}}
SM_ARN = f"arn:aws:states:{REGION}:{ACCOUNT}:stateMachine:svc-dev"


class FakeSfnClients(FakeClients):
    def __init__(self, project, *, deployed=None, status="ACTIVE", **kwargs):
        super().__init__(project, **kwargs)
        self.deployed = DEFINITION if deployed is None else deployed
        self.sm_status = status

    def _stepfunctions(self):
        fake = self

        class StepFunctions:
            def describe_state_machine(self, stateMachineArn):
                return {"stateMachineArn": stateMachineArn, "status": fake.sm_status, "type": "EXPRESS",
                        "definition": json.dumps(fake.deployed, indent=4)}
        return StepFunctions()


class SfnProject:
    def __init__(self):
        self.root = Path(tempfile.mkdtemp(prefix="verify-sfn-"))
        (self.root / "workflow").mkdir()
        (self.root / "workflow" / "definition.asl.json").write_text(json.dumps(DEFINITION), encoding="utf-8")
        (self.root / "infra").mkdir()
        (self.root / ".verify").mkdir()
        (self.root / ".verify" / "probes.json").write_text(json.dumps({"probes": [
            {"name": "hello", "method": "GET", "path": "/hello", "expect_status": 200,
             "expect_json_keys": ["message"]},
            {"name": "timeout", "method": "GET", "path": "/hello", "expect_status": 200,
             "trips_alarm": ["api-5xx", "executions-timed-out"]}]}), encoding="utf-8")
        self.outputs = {
            "account_id": ACCOUNT, "region": REGION, "api_url": "https://abc.execute-api.us-east-1.amazonaws.com/dev",
            "auth_mode": "iam", "state_machine_arn": SM_ARN, "log_group": "/aws/vendedlogs/states/svc-dev",
            "alarm_names": ["svc-dev-api-5xx", "svc-dev-executions-timed-out"],
            "alarm_topic_arn": f"arn:aws:sns:{REGION}:{ACCOUNT}:svc-dev-alarms",
        }

    def cleanup(self):
        shutil.rmtree(self.root, ignore_errors=True)


class SfnVerifyTest(VerifierCase):
    def setUp(self):
        self.project = SfnProject()
        self.addCleanup(self.project.cleanup)

    def test_deployed_definition_equal_to_the_local_file_passes(self):
        report = self.verify(clients=FakeSfnClients(self.project))

        self.assertEqual("PASS", self.status(report, "artifact"), report)

    def test_deployed_definition_that_differs_from_the_local_file_fails(self):
        changed = {**DEFINITION, "TimeoutSeconds": 20}

        report = self.verify(clients=FakeSfnClients(self.project, deployed=changed))

        self.assertEqual(1, report["exit_code"])
        self.assertEqual("FAIL", self.status(report, "artifact"))

    def test_state_machine_being_deleted_fails(self):
        report = self.verify(clients=FakeSfnClients(self.project, status="DELETING"))

        self.assertEqual("FAIL", self.status(report, "artifact"))

    def test_probe_body_is_sent_as_json(self):
        probes = json.loads((self.project.root / ".verify" / "probes.json").read_text(encoding="utf-8"))
        probes["probes"][0].update(method="POST", body={"order_id": "o-1"})
        (self.project.root / ".verify" / "probes.json").write_text(json.dumps(probes), encoding="utf-8")

        self.verify(clients=FakeSfnClients(self.project))

        sent = self.http.requests[0]
        self.assertEqual(("POST", {"order_id": "o-1"}), (sent["method"], json.loads(sent["body"])))
        self.assertEqual("application/json", sent["headers"]["content-type"])

    def test_alarm_an_http_probe_trips_is_expected(self):
        clients = FakeSfnClients(self.project, alarms={"svc-dev-api-5xx": "ALARM",
                                                        "svc-dev-executions-timed-out": "ALARM"})

        report = self.verify(clients=clients)

        self.assertEqual("PASS", self.status(report, "alarms"), report)


AMI, ASG = "ami-0123456789abcdef0", "svc-dev-web"


class FakeAsgClients(FakeEcsClients):
    def __init__(self, project, *, instances=None, desired=2, refresh_status="Successful", images=None, **kwargs):
        super().__init__(project, **kwargs)
        self.instances = instances if instances is not None else [
            {"InstanceId": f"i-{n}", "LifecycleState": "InService", "HealthStatus": "Healthy",
             "LaunchTemplate": {"LaunchTemplateId": "lt-1", "Version": "4"}} for n in range(2)]
        self.asg_desired = desired
        self.refresh_status = refresh_status
        self.images = images or {}

    def _autoscaling(self):
        fake = self

        class AutoScaling:
            def describe_auto_scaling_groups(self, AutoScalingGroupNames):
                return {"AutoScalingGroups": [{"AutoScalingGroupName": AutoScalingGroupNames[0],
                                               "DesiredCapacity": fake.asg_desired, "Instances": fake.instances}]}

            def describe_instance_refreshes(self, AutoScalingGroupName, MaxRecords):
                refreshes = [{"InstanceRefreshId": "r-1", "Status": fake.refresh_status}] if fake.refresh_status else []
                return {"InstanceRefreshes": refreshes}
        return AutoScaling()

    def _ec2(self):
        fake = self

        class Ec2:
            def describe_instances(self, InstanceIds):
                return {"Reservations": [{"Instances": [
                    {"InstanceId": i, "ImageId": fake.images.get(i, AMI)} for i in InstanceIds]}]}
        return Ec2()


class AsgProject(EcsProject):
    def __init__(self):
        super().__init__()
        self.outputs = {
            "account_id": ACCOUNT, "region": REGION, "service_url": "http://svc-dev-123.us-east-1.elb.amazonaws.com",
            "asg_name": ASG, "ami_id": AMI, "launch_template_version": 4, "target_group_arn": TG,
            "log_group": "/ec2/svc-dev", "alarm_names": ["svc-dev-target-5xx"],
            "alarm_topic_arn": f"arn:aws:sns:{REGION}:{ACCOUNT}:svc-dev-alarms",
        }


class AsgVerifyTest(VerifierCase):
    def setUp(self):
        self.project = AsgProject()
        self.addCleanup(self.project.cleanup)
        self.source = vd.source_hash(self.project.root / "app")

    def run_asg(self, **kwargs):
        clients = FakeAsgClients(self.project, **kwargs)
        return self.verify(clients=clients, http=FakeEcsHttp(self.source))

    def instance(self, n, version="4", state="InService", health="Healthy"):
        return {"InstanceId": f"i-{n}", "LifecycleState": state, "HealthStatus": health,
                "LaunchTemplate": {"LaunchTemplateId": "lt-1", "Version": version}}

    def test_healthy_fleet_passes(self):
        report = self.run_asg(target_states=("healthy", "healthy"))

        self.assertEqual(0, report["exit_code"], report)
        for check_id in ("target", "artifact", "health", "probe:hello", "logs:hello"):
            self.assertEqual("PASS", self.status(report, check_id), check_id)

    def test_instance_on_an_older_launch_template_fails(self):
        report = self.run_asg(instances=[self.instance(0), self.instance(1, version="3")])

        self.assertEqual("FAIL", self.status(report, "artifact"))
        self.assertIn("i-1", json.dumps(report))

    def test_instance_from_another_image_fails(self):
        report = self.run_asg(images={"i-1": "ami-0fffffffffffffff0"})

        self.assertEqual("FAIL", self.status(report, "artifact"))

    def test_refresh_in_progress_fails(self):
        report = self.run_asg(refresh_status="InProgress")

        self.assertEqual("FAIL", self.status(report, "artifact"))

    def test_fewer_in_service_than_desired_fails(self):
        report = self.run_asg(instances=[self.instance(0), self.instance(1, state="Pending")])

        self.assertEqual("FAIL", self.status(report, "artifact"))

    def test_unhealthy_target_fails(self):
        report = self.run_asg(target_states=("healthy", "unhealthy"))

        self.assertEqual("FAIL", self.status(report, "health"))


class AwsError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.response = {"Error": {"Code": code}}


class FakeResidueClients(FakeClients):
    def __init__(self, residue, *, cluster="INACTIVE", service="INACTIVE", task_definition="ACTIVE",
                 rule_exists=False, task="STOPPED", instance="terminated", volume_exists=False, group_exists=False,
                 flow_log_exists=False, secret_deleted=True):
        super().__init__(None, residue=residue)
        self.task, self.instance, self.volume_exists = task, instance, volume_exists
        self.group_exists, self.flow_log_exists = group_exists, flow_log_exists
        self.secret_deleted = secret_deleted
        self.cluster, self.service, self.task_definition, self.rule_exists = (
            cluster, service, task_definition, rule_exists)

    def _secretsmanager(self):
        fake = self

        class SecretsManager:
            def describe_secret(self, SecretId):
                secret = {"ARN": SecretId, "Name": "svc-dev/app"}
                if fake.secret_deleted:
                    secret["DeletedDate"] = "2026-11-09T10:00:00+00:00"
                return secret
        return SecretsManager()

    def _ecs(self):
        fake = self

        class Ecs:
            def describe_clusters(self, clusters):
                return {"clusters": [{"clusterArn": clusters[0], "status": fake.cluster}]}

            def describe_services(self, cluster, services):
                return {"services": [{"serviceArn": services[0], "status": fake.service}], "failures": []}

            def describe_tasks(self, cluster, tasks):
                if fake.task is None:
                    return {"tasks": [], "failures": [{"arn": tasks[0], "reason": "MISSING"}]}
                return {"tasks": [{"taskArn": tasks[0], "lastStatus": fake.task}], "failures": []}

            def describe_task_definition(self, taskDefinition):
                return {"taskDefinition": {"taskDefinitionArn": taskDefinition, "status": fake.task_definition}}
        return Ecs()

    def _ec2(self):
        fake = self

        class Ec2:
            def describe_security_group_rules(self, SecurityGroupRuleIds):
                if not fake.rule_exists:
                    raise AwsError("InvalidSecurityGroupRuleId.NotFound")
                return {"SecurityGroupRules": [{"SecurityGroupRuleId": SecurityGroupRuleIds[0]}]}

            def describe_instances(self, InstanceIds):
                if fake.instance is None:
                    raise AwsError("InvalidInstanceID.NotFound")
                if fake.instance == "purged":
                    return {"Reservations": []}
                return {"Reservations": [{"Instances": [{"InstanceId": InstanceIds[0],
                                                         "State": {"Name": fake.instance}}]}]}

            def describe_volumes(self, VolumeIds):
                if not fake.volume_exists:
                    raise AwsError("InvalidVolume.NotFound")
                return {"Volumes": [{"VolumeId": VolumeIds[0], "State": "available"}]}

            def describe_security_groups(self, GroupIds):
                if not fake.group_exists:
                    raise AwsError("InvalidGroup.NotFound")
                return {"SecurityGroups": [{"GroupId": GroupIds[0]}]}

            def describe_flow_logs(self, FlowLogIds):
                return {"FlowLogs": [{"FlowLogId": FlowLogIds[0]}] if fake.flow_log_exists else []}
        return Ec2()


CLUSTER_ARN = f"arn:aws:ecs:{REGION}:{ACCOUNT}:cluster/svc-dev"
SERVICE_ARN = f"arn:aws:ecs:{REGION}:{ACCOUNT}:service/svc-dev/svc-dev-web"
TASKDEF_ARN = f"arn:aws:ecs:{REGION}:{ACCOUNT}:task-definition/svc-dev-web:1"
TASK_ARN = f"arn:aws:ecs:{REGION}:{ACCOUNT}:task/svc-dev/f20d853da4d5411b8fe964cfe78a0d25"
RULE_ARN = f"arn:aws:ec2:{REGION}:{ACCOUNT}:security-group-rule/sgr-0123456789abcdef0"
INSTANCE_ARN = f"arn:aws:ec2:{REGION}:{ACCOUNT}:instance/i-0123456789abcdef0"
VOLUME_ARN = f"arn:aws:ec2:{REGION}:{ACCOUNT}:volume/vol-0123456789abcdef0"
GROUP_ARN = f"arn:aws:ec2:{REGION}:{ACCOUNT}:security-group/sg-0123456789abcdef0"
FLOW_LOG_ARN = f"arn:aws:ec2:{REGION}:{ACCOUNT}:vpc-flow-log/fl-0123456789abcdef0"
SECRET_ARN = f"arn:aws:secretsmanager:{REGION}:{ACCOUNT}:secret:svc-dev/app-AbCdEf"


class ResidueTest(unittest.TestCase):
    def test_credentials_for_another_account_stop_before_the_search(self):
        clients = FakeClients(None, residue=[], account="999999999999")

        result = vd.residue(clients, "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual(("target", "FAIL"), (result.id, result.status))
        self.assertIn("999999999999", result.detail)

    def test_residue_command_exits_3_for_another_account(self):
        fake = FakeClients(None, residue=[], account="999999999999")
        with mock.patch("boto3.Session", return_value=fake):
            code = vd.main(["residue", "--project-tag", "svc", "--environment", "dev",
                            "--expect-account", ACCOUNT, "--expect-region", REGION])

        self.assertEqual(3, code)

    def test_no_tagged_resources_left_passes(self):
        result = vd.residue(FakeClients(None, residue=[]), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("PASS", result.status)

    def test_tagged_resources_left_after_destroy_fail_and_are_listed(self):
        arn = f"arn:aws:logs:{REGION}:{ACCOUNT}:log-group:/aws/lambda/svc-dev"

        result = vd.residue(FakeClients(None, residue=[arn]), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("FAIL", result.status)
        self.assertIn(arn, result.detail)

    def test_key_pending_deletion_is_reported_not_failed(self):
        arn = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/abc"

        result = vd.residue(FakeClients(None, residue=[arn]), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("PASS", result.status)
        self.assertIn("scheduled for deletion on 2026-11-15", result.detail)

    def test_deleted_mapping_still_in_the_tag_index_is_reported_not_failed(self):
        arn = f"arn:aws:lambda:{REGION}:{ACCOUNT}:event-source-mapping:33e72fd4"

        result = vd.residue(FakeClients(None, residue=[arn]), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("PASS", result.status)
        self.assertIn(f"{arn} deleted; the tag index has not caught up", result.detail)

    def test_live_mapping_left_after_destroy_fails(self):
        arn = f"arn:aws:lambda:{REGION}:{ACCOUNT}:event-source-mapping:33e72fd4"

        result = vd.residue(FakeClients(None, residue=[arn], live_mappings=["33e72fd4"]), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("FAIL", result.status)

    def test_deleted_ecs_cluster_service_and_rule_in_the_tag_index_are_reported_not_failed(self):
        result = vd.residue(FakeResidueClients([CLUSTER_ARN, SERVICE_ARN, RULE_ARN]), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("PASS", result.status, result.detail)
        self.assertEqual(3, result.detail.count("deleted; the tag index has not caught up"))

    def test_stopped_or_missing_ecs_task_is_reported_not_failed(self):
        for state in ("STOPPED", None):
            with self.subTest(state=state):
                result = vd.residue(FakeResidueClients([TASK_ARN], task=state), "svc", "dev", expect_account=ACCOUNT)

                self.assertEqual("PASS", result.status, result.detail)

    def test_running_ecs_task_fails(self):
        result = vd.residue(FakeResidueClients([TASK_ARN], task="RUNNING"), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("FAIL", result.status)

    def test_live_ecs_service_fails(self):
        result = vd.residue(FakeResidueClients([SERVICE_ARN], service="ACTIVE"), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("FAIL", result.status)

    def test_live_security_group_rule_fails(self):
        result = vd.residue(FakeResidueClients([RULE_ARN], rule_exists=True), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("FAIL", result.status)

    def test_terminated_or_missing_instance_is_reported_not_failed(self):
        for state in ("terminated", "shutting-down", None, "purged"):
            with self.subTest(state=state):
                result = vd.residue(FakeResidueClients([INSTANCE_ARN], instance=state), "svc", "dev", expect_account=ACCOUNT)

                self.assertEqual("PASS", result.status, result.detail)

    def test_running_or_stopped_instance_fails(self):
        for state in ("running", "stopped"):
            with self.subTest(state=state):
                result = vd.residue(FakeResidueClients([INSTANCE_ARN], instance=state), "svc", "dev", expect_account=ACCOUNT)

                self.assertEqual("FAIL", result.status)

    def test_deleted_volume_is_reported_not_failed(self):
        result = vd.residue(FakeResidueClients([VOLUME_ARN]), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("PASS", result.status, result.detail)

    def test_existing_volume_fails(self):
        result = vd.residue(FakeResidueClients([VOLUME_ARN], volume_exists=True), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("FAIL", result.status)

    def test_deleted_security_group_and_flow_log_are_reported_not_failed(self):
        result = vd.residue(FakeResidueClients([GROUP_ARN, FLOW_LOG_ARN]), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("PASS", result.status, result.detail)
        self.assertEqual(2, result.detail.count("deleted; the tag index has not caught up"))

    def test_live_security_group_fails(self):
        result = vd.residue(FakeResidueClients([GROUP_ARN], group_exists=True), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("FAIL", result.status)

    def test_secret_scheduled_for_deletion_is_reported_not_failed(self):
        result = vd.residue(FakeResidueClients([SECRET_ARN]), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("PASS", result.status, result.detail)
        self.assertIn("deletion", result.detail)

    def test_live_secret_fails(self):
        result = vd.residue(FakeResidueClients([SECRET_ARN], secret_deleted=False), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("FAIL", result.status)

    def test_live_flow_log_fails(self):
        result = vd.residue(FakeResidueClients([FLOW_LOG_ARN], flow_log_exists=True), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("FAIL", result.status)

    def test_active_task_definition_left_by_express_mode_fails(self):
        result = vd.residue(FakeResidueClients([TASKDEF_ARN]), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("FAIL", result.status)
        self.assertIn(TASKDEF_ARN, result.detail)

    def test_deregistered_task_definition_is_reported_not_failed(self):
        result = vd.residue(FakeResidueClients([TASKDEF_ARN], task_definition="INACTIVE"), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("PASS", result.status)

    def test_enabled_key_left_after_destroy_fails(self):
        arn = f"arn:aws:kms:{REGION}:{ACCOUNT}:key/abc"

        result = vd.residue(FakeClients(None, residue=[arn], key_state="Enabled"), "svc", "dev", expect_account=ACCOUNT)

        self.assertEqual("FAIL", result.status)


if __name__ == "__main__":
    unittest.main()
