#!/usr/bin/env python3
"""Verify a deployed application against this checkout, with evidence.

Usage:
    python verify_deployment.py verify <project> --expect-account ID --expect-region REGION
           [--profile NAME] [--root infra] [--json] [--log-wait 120] [--trace-wait 60]
    python verify_deployment.py residue --project-tag NAME --environment ENV
           --expect-account ID --expect-region REGION [--profile NAME]
    python verify_deployment.py source-hash <project>

`verify` order: target (account and region from STS and Terraform outputs must equal the
expected values, or nothing else runs) -> artifact (the deployed CodeSha256 equals the local
package, and the package equals app/) -> probes from .verify/probes.json (the only requests
that change anything) -> logs by request ID -> trace -> alarms -> alerting.

For an ECS service (the ecs_service_name output) the artifact check is different: every
running task runs the image_digest output, the rollout is complete and running equals
desired. A health check then needs every registered target healthy, and a probe with
expect_source_hash needs the response's source_sha256 to equal `source-hash` of app/.
Logs are found by correlation ID, because the load balancer returns no request ID.

For an Auto Scaling group (the asg_name output) the artifact check needs every instance
InService and Healthy, as many as desired, on launch_template_version and ami_id, with no
instance refresh running. The health check then reads target_group_arn.

For a workflow (the state_machine_arn output) the artifact check needs the deployed
definition to equal workflow/definition.asl.json and the state machine to be ACTIVE.

A probe may name alarms it trips (trips_alarm); those alarms in ALARM do not fail the
alarms check.

Probe types: HTTP (the default; needs the api_url output) and, for a queue worker,
sqs-processed (one message is logged "order processed"), sqs-processed-once (the same
order sent twice is logged "order processed" once) and sqs-dead-letter (a message that
always fails reaches the dead-letter queue within (max_receive_count + 1) x visibility
timeout + 60 s; the verifier then deletes it).

Results are PASS, FAIL or UNVERIFIED per check. Missing data is UNVERIFIED, never PASS.
Traces are sampled, alarms lag and a confirmed subscriber is not a delivered message, so
trace, alarms and alerting are reported but do not decide the exit code.

`residue` lists resources still tagged Project/Environment after a destroy.

`source-hash` prints the SHA-256 of app/ without tests and bytecode. The image build passes
it in, and the service returns it, so a response proves which source it came from.

Exit codes: 0 required checks PASS; 1 a required FAIL; 2 a required UNVERIFIED; 3 wrong target.
Needs boto3 (`uv run --with boto3 ...`).
"""

import argparse
import base64
import hashlib
import json
import re
import subprocess
import sys
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path

REQUIRED = ("target", "artifact", "health", "probe", "auth-rejection", "logs", "dead-letter")
APP_SKIP = {"tests", "__pycache__"}


@dataclass
class Target:
    account: str
    region: str


@dataclass
class Waits:
    logs: float = 120
    traces: float = 60
    interval: float = 5


@dataclass
class HttpResponse:
    status: int
    headers: dict
    body: str


@dataclass
class Result:
    id: str
    status: str
    detail: str = ""
    required: bool = True
    evidence: dict = field(default_factory=dict)


def exit_code(results):
    if any(r.id == "target" and r.status != "PASS" for r in results):
        return 3
    required = [r for r in results if r.required]
    if any(r.status == "FAIL" for r in required):
        return 1
    if any(r.status == "UNVERIFIED" for r in required) or not required:
        return 2
    return 0


def b64_sha256(data: bytes) -> str:
    return base64.b64encode(hashlib.sha256(data).digest()).decode()


def app_files(app: Path):
    return {p.relative_to(app).as_posix(): p for p in app.rglob("*")
            if p.is_file() and not APP_SKIP & set(p.relative_to(app).parts)}


def source_hash(app: Path) -> str:
    digest = hashlib.sha256()
    for name, path in sorted(app_files(app).items()):
        digest.update(name.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


class Verifier:
    def __init__(self, project: Path, root: str, outputs: dict, clients, http, target: Target,
                 waits: Waits = Waits(), sleep=time.sleep, clock=time.time):
        self.project, self.root, self.outputs = project, project / root, outputs
        self.clients, self.http, self.target, self.waits = clients, http, target, waits
        self.sleep, self.clock = sleep, clock
        self.results = []
        self.expected_alarms = set()

    def add(self, check_id, status, detail="", required=None, **evidence):
        if required is None:
            required = check_id.split(":")[0] in REQUIRED
        self.results.append(Result(check_id, status, detail, required, evidence))

    def check_target(self):
        identity = self.clients.client("sts").get_caller_identity()
        problems = []
        if identity["Account"] != self.target.account:
            problems.append(f"credentials are for account {identity['Account']}, expected {self.target.account}")
        if str(self.outputs.get("account_id")) != self.target.account:
            problems.append(f"Terraform outputs are for account {self.outputs.get('account_id')}")
        if self.outputs.get("region") != self.target.region:
            problems.append(f"Terraform outputs are for region {self.outputs.get('region')}, "
                            f"expected {self.target.region}")
        if problems:
            self.add("target", "FAIL", "; ".join(problems))
            return False
        self.add("target", "PASS", f"{self.target.account} {self.target.region}", caller=identity["Arn"])
        return True

    def check_artifact(self):
        if "ecs_service_name" in self.outputs:
            self.check_service()
            return
        if "state_machine_arn" in self.outputs:
            self.check_workflow()
            return
        if "asg_name" in self.outputs:
            self.check_fleet()
            return
        package = (self.root / self.outputs["artifact_path"]).resolve()
        if not package.is_file():
            self.add("artifact", "UNVERIFIED", f"no local package at {package}; run terraform plan to build it")
            return
        problems = self.package_vs_source(package)
        config = self.clients.client("lambda").get_function(
            FunctionName=self.outputs["function_name"], Qualifier=self.outputs["function_alias"])["Configuration"]
        local = b64_sha256(package.read_bytes())
        if config["CodeSha256"] != local:
            problems.append(f"deployed CodeSha256 {config['CodeSha256']} is not the local package {local}")
        if str(config.get("Version")) != str(self.outputs["function_version"]):
            problems.append(f"alias points at version {config.get('Version')}, "
                            f"outputs say {self.outputs['function_version']}")
        if config.get("State") != "Active" or config.get("LastUpdateStatus") != "Successful":
            problems.append(f"function state {config.get('State')}/{config.get('LastUpdateStatus')}")
        if problems:
            self.add("artifact", "FAIL", "; ".join(problems))
        else:
            self.add("artifact", "PASS", f"version {config['Version']}, CodeSha256 {local}",
                     code_sha256=local, version=config["Version"])

    def check_workflow(self):
        local_path = self.project / "workflow" / "definition.asl.json"
        machine = self.clients.client("stepfunctions").describe_state_machine(
            stateMachineArn=self.outputs["state_machine_arn"])
        problems = []
        if machine["status"] != "ACTIVE":
            problems.append(f"state machine is {machine['status']}")
        if json.loads(machine["definition"]) != json.loads(local_path.read_text(encoding="utf-8")):
            problems.append(f"deployed definition is not {local_path.relative_to(self.project).as_posix()}")
        if problems:
            self.add("artifact", "FAIL", "; ".join(problems))
        else:
            self.add("artifact", "PASS", f"{machine.get('type', '')} state machine runs the local definition",
                     state_machine_arn=machine["stateMachineArn"])

    def check_fleet(self):
        autoscaling, name = self.clients.client("autoscaling"), self.outputs["asg_name"]
        group = autoscaling.describe_auto_scaling_groups(AutoScalingGroupNames=[name])["AutoScalingGroups"][0]
        version, ami = str(self.outputs["launch_template_version"]), self.outputs["ami_id"]
        problems = []
        serving = [i for i in group["Instances"]
                   if i["LifecycleState"] == "InService" and i["HealthStatus"] == "Healthy"]
        if len(serving) != group["DesiredCapacity"]:
            problems.append(f"{len(serving)} of {group['DesiredCapacity']} desired instances InService and Healthy")
        old = [i["InstanceId"] for i in group["Instances"] if str(i.get("LaunchTemplate", {}).get("Version")) != version]
        if old:
            problems.append(f"not on launch template version {version}: {', '.join(old)}")
        refreshes = autoscaling.describe_instance_refreshes(AutoScalingGroupName=name, MaxRecords=1)["InstanceRefreshes"]
        if refreshes and refreshes[0]["Status"] in ("Pending", "InProgress", "Cancelling", "RollbackInProgress"):
            problems.append(f"instance refresh {refreshes[0]['Status']}")
        ids = [i["InstanceId"] for i in group["Instances"]]
        found = self.clients.client("ec2").describe_instances(InstanceIds=ids)["Reservations"] if ids else []
        other = sorted(f"{i['InstanceId']} runs {i['ImageId']}" for r in found for i in r["Instances"]
                       if i["ImageId"] != ami)
        if other:
            problems.append(f"not on {ami}: {', '.join(other)}")
        if problems:
            self.add("artifact", "FAIL", "; ".join(problems))
        else:
            self.add("artifact", "PASS", f"{len(serving)} instance(s) run {ami}, launch template version {version}",
                     ami_id=ami, launch_template_version=version)
        self.check_health([self.outputs["target_group_arn"]])

    def expect_alarms(self, probe):
        trips = probe.get("trips_alarm", [])
        self.expected_alarms.update([trips] if isinstance(trips, str) else trips)

    def ecs_service(self):
        return self.clients.client("ecs").describe_services(
            cluster=self.outputs["ecs_cluster_name"], services=[self.outputs["ecs_service_name"]])["services"][0]

    def check_service(self):
        ecs, cluster = self.clients.client("ecs"), self.outputs["ecs_cluster_name"]
        service, expected = self.ecs_service(), self.outputs["image_digest"]
        problems = []
        rollouts = [f"{d['status']}={d.get('rolloutState')}" for d in service["deployments"]]
        if len(rollouts) != 1 or service["deployments"][0].get("rolloutState") != "COMPLETED":
            problems.append(f"rollout not complete: {', '.join(rollouts)}")
        if service["desiredCount"] < 1 or service["runningCount"] != service["desiredCount"]:
            problems.append(f"running {service['runningCount']} of desired {service['desiredCount']}")
        arns, token = [], None
        while True:
            page = ecs.list_tasks(cluster=cluster, serviceName=self.outputs["ecs_service_name"],
                                  desiredStatus="RUNNING", **({"nextToken": token} if token else {}))
            arns += page["taskArns"]
            token = page.get("nextToken")
            if not token:
                break
        tasks, failures = [], []
        for start in range(0, len(arns), 100):
            described = ecs.describe_tasks(cluster=cluster, tasks=arns[start:start + 100])
            tasks += described["tasks"]
            failures += described.get("failures", [])
        if failures:
            problems.append("tasks not described: " + ", ".join(f"{f.get('arn')} ({f.get('reason')})" for f in failures))
        if len(tasks) != service["runningCount"]:
            problems.append(f"service counts {service['runningCount']} running task(s), {len(tasks)} described")
        digests = sorted({c.get("imageDigest") for task in tasks for c in task["containers"]})
        other = [d for d in digests if d != expected]
        if other:
            problems.append(f"tasks run {', '.join(map(str, other))}, not {expected}")
        if problems:
            self.add("artifact", "FAIL", "; ".join(problems))
        else:
            self.add("artifact", "PASS", f"{len(tasks)} task(s) run {expected}", image_digest=expected)
        self.check_health(self.service_target_groups(service))

    def service_target_groups(self, service):
        groups = [lb["targetGroupArn"] for lb in service.get("loadBalancers") or []]
        if groups:
            return groups
        # Express Mode and other blue/green services list their target groups on the service
        # revision: the production one and the alternate a rollout shifts traffic to.
        arns = [r["arn"] for r in service.get("currentServiceRevisions", [])]
        if not arns:
            return []
        revisions = self.clients.client("ecs").describe_service_revisions(serviceRevisionArns=arns)["serviceRevisions"]
        return sorted({arn for r in revisions for lb in r.get("loadBalancers", [])
                       for arn in (lb.get("targetGroupArn"), lb.get("advancedConfiguration", {}).get("alternateTargetGroupArn"))
                       if arn})

    def check_health(self, target_groups):
        elbv2 = self.clients.client("elbv2")
        states = [d["TargetHealth"]["State"] for arn in target_groups
                  for d in elbv2.describe_target_health(TargetGroupArn=arn)["TargetHealthDescriptions"]]
        unhealthy = [s for s in states if s not in ("healthy", "draining")]
        if not states.count("healthy"):
            self.add("health", "FAIL", "no healthy target behind the load balancer")
        elif unhealthy:
            self.add("health", "FAIL", f"targets not healthy: {', '.join(unhealthy)}")
        else:
            self.add("health", "PASS", f"{states.count('healthy')} healthy target(s)")

    def package_vs_source(self, package: Path):
        app = self.project / "app"
        sources = {name: path.read_bytes() for name, path in app_files(app).items()}
        with zipfile.ZipFile(package) as z:
            packaged = {name: z.read(name) for name in z.namelist() if not name.endswith("/")}
        problems = [f"{name} differs between app/ and the package" for name in sorted(sources)
                    if name in packaged and packaged[name] != sources[name]]
        problems += [f"{name} is in app/ but not in the package" for name in sorted(set(sources) - set(packaged))]
        problems += [f"{name} is in the package but not in app/" for name in sorted(set(packaged) - set(sources))]
        return problems

    def probes(self):
        path = self.project / ".verify" / "probes.json"
        if not path.is_file():
            self.add("probe", "UNVERIFIED", "no .verify/probes.json")
            return []
        return json.loads(path.read_text(encoding="utf-8"))["probes"]

    def request(self, probe, sign):
        correlation_id = str(uuid.uuid4())
        url = (self.outputs.get("api_url") or self.outputs["service_url"]).rstrip("/") + probe["path"]
        headers, body = {"x-correlation-id": correlation_id}, None
        if "body" in probe:
            headers["content-type"], body = "application/json", json.dumps(probe["body"])
        response = self.http(probe["method"], url, headers, sign, body)
        return correlation_id, response

    def check_probe(self, probe):
        name = probe["name"]
        iam = self.outputs.get("auth_mode") == "iam"
        self.expect_alarms(probe)
        started = self.clock()
        try:
            correlation_id, response = self.request(probe, sign=iam)
        except (OSError, TimeoutError) as error:
            self.add(f"probe:{name}", "UNVERIFIED", f"request failed: {error}")
            return None
        problems = []
        if response.status != probe["expect_status"]:
            problems.append(f"status {response.status}, expected {probe['expect_status']}: {response.body[:200]}")
        else:
            try:
                body = json.loads(response.body)
                missing = [k for k in probe.get("expect_json_keys", []) if k not in body]
                if missing:
                    problems.append(f"response lacks {', '.join(missing)}")
                for key, value in probe.get("expect_json", {}).items():
                    if body.get(key) != value:
                        problems.append(f"response {key} is {json.dumps(body.get(key))}, expected {json.dumps(value)}")
                local = source_hash(self.project / "app")
                if probe.get("expect_source_hash") and body.get("source_sha256") != local:
                    problems.append(f"response source_sha256 {body.get('source_sha256')} is not app/ ({local})")
            except json.JSONDecodeError:
                problems.append("response is not JSON")
            if response.headers.get("x-correlation-id") != correlation_id:
                problems.append("correlation ID not echoed")
        request_id = response.headers.get("x-lambda-request-id", "")
        if problems:
            self.add(f"probe:{name}", "FAIL", "; ".join(problems), request_id=request_id)
            return None
        self.add(f"probe:{name}", "PASS", f"{response.status}", request_id=request_id, correlation_id=correlation_id)
        if iam:
            self.check_rejection(probe)
        return {"name": name, "request_id": request_id, "correlation_id": correlation_id,
                "trace_header": response.headers.get("x-trace-id", ""), "started": started}

    def check_rejection(self, probe):
        expected = probe.get("unauthenticated_expect_status_when_iam", 403)
        try:
            _, response = self.request(probe, sign=False)
        except (OSError, TimeoutError) as error:
            self.add(f"auth-rejection:{probe['name']}", "UNVERIFIED", f"request failed: {error}")
            return
        status = "PASS" if response.status == expected else "FAIL"
        self.add(f"auth-rejection:{probe['name']}", status, f"unsigned request got {response.status}, expected {expected}")

    def send_sqs(self, probe):
        name, kind = probe["name"], probe["type"]
        order_id = f"verify-{uuid.uuid4()}"
        body = json.dumps({**probe.get("message", {}), "id": order_id})
        copies = 2 if kind == "sqs-processed-once" else 1
        started = self.clock()
        sqs = self.clients.client("sqs")
        message_ids = [sqs.send_message(QueueUrl=self.outputs["queue_url"], MessageBody=body)["MessageId"]
                       for _ in range(copies)]
        self.add(f"probe:{name}", "PASS", f"sent order {order_id} {copies} time(s)",
                 order_id=order_id, message_ids=message_ids)
        self.expect_alarms(probe)
        return {"name": name, "type": kind, "order_id": order_id, "copies": copies, "started": started}

    def check_processed(self, sent):
        logs = self.clients.client("logs")
        order_id = sent["order_id"]

        def events(text):
            return logs.filter_log_events(
                logGroupName=self.outputs["lambda_log_group"],
                filterPattern='{ $.order_id = "%s" && $.message = "%s" }' % (order_id, text),
                startTime=int((sent["started"] - 60) * 1000))["events"]

        def attempt():
            received, processed = events("message received"), events("order processed")
            return (received, processed) if len(received) >= sent["copies"] and processed else None

        found = self.poll(self.waits.logs, attempt)
        check_id = f"logs:{sent['name']}"
        if not found:
            self.add(check_id, "UNVERIFIED", f"order {order_id} not logged as received {sent['copies']} "
                                             f"time(s) and processed within {self.waits.logs:g}s")
            return
        received, processed = found
        if len(processed) > 1:
            self.add(check_id, "FAIL", f"order {order_id} processed {len(processed)} times from "
                                       f"{len(received)} deliveries; expected once")
        else:
            self.add(check_id, "PASS", f"order {order_id}: {len(received)} delivery(ies), processed once")

    def check_dead_letter(self, sent):
        queue = self.outputs["dead_letter_queue_url"]
        budget = (int(self.outputs["max_receive_count"]) + 1) * int(self.outputs["visibility_timeout_seconds"]) + 60
        sqs = self.clients.client("sqs")

        def order_id(message):
            try:
                body = json.loads(message["Body"])
            except json.JSONDecodeError:
                return None
            return body.get("id") if isinstance(body, dict) else None

        def attempt():
            messages = sqs.receive_message(QueueUrl=queue, MaxNumberOfMessages=10, VisibilityTimeout=30,
                                           AttributeNames=["ApproximateReceiveCount"]).get("Messages", [])
            return next((m for m in messages if order_id(m) == sent["order_id"]), None)

        found = self.poll(budget, attempt)
        check_id = f"dead-letter:{sent['name']}"
        if not found:
            self.add(check_id, "UNVERIFIED", f"order {sent['order_id']} not in the dead-letter queue within {budget}s")
            return
        sqs.delete_message(QueueUrl=queue, ReceiptHandle=found["ReceiptHandle"])
        receives = found.get("Attributes", {}).get("ApproximateReceiveCount", "?")
        self.add(check_id, "PASS", f"order {sent['order_id']} reached the dead-letter queue "
                                   f"(receive count {receives}); probe message deleted")

    def poll(self, budget, attempt):
        attempts = int(budget // self.waits.interval) + 1
        for remaining in range(attempts - 1, -1, -1):
            found = attempt()
            if found or remaining == 0:
                return found
            self.sleep(self.waits.interval)

    def check_logs(self, probe):
        logs = self.clients.client("logs")
        key = probe["request_id"] or probe["correlation_id"]

        def attempt():
            return logs.filter_log_events(
                logGroupName=self.outputs.get("lambda_log_group") or self.outputs["log_group"],
                filterPattern=f'"{key}"', startTime=int((probe["started"] - 60) * 1000))["events"]

        events = self.poll(self.waits.logs, attempt)
        check_id = f"logs:{probe['name']}"
        if not events:
            self.add(check_id, "UNVERIFIED", f"no log event for request {key} within {self.waits.logs:g}s")
        elif not any(probe["correlation_id"] in e["message"] for e in events):
            self.add(check_id, "FAIL", f"log events for {key} lack correlation ID")
        else:
            self.add(check_id, "PASS", f"{len(events)} event(s) for request {key}")

    def check_trace(self, probe):
        match = re.search(r"Root=([0-9a-f-]+)", probe["trace_header"])
        check_id = f"trace:{probe['name']}"
        if not match:
            self.add(check_id, "UNVERIFIED", "response carried no trace ID", required=False)
            return
        xray = self.clients.client("xray")
        trace_id = match.group(1)
        found = self.poll(self.waits.traces, lambda: xray.batch_get_traces(TraceIds=[trace_id])["Traces"])
        if found:
            self.add(check_id, "PASS", trace_id, required=False)
        else:
            self.add(check_id, "UNVERIFIED", f"trace {trace_id} not found within {self.waits.traces:g}s "
                                             "(sampled out or not yet indexed)", required=False)

    def check_alarms(self):
        names = self.outputs.get("alarm_names") or []
        if not names:
            self.add("alarms", "UNVERIFIED", "no alarm_names output", required=False)
            return
        alarms = self.clients.client("cloudwatch").describe_alarms(AlarmNames=names)["MetricAlarms"]
        states = {a["AlarmName"]: a["StateValue"] for a in alarms}
        in_alarm = sorted(n for n, s in states.items() if s == "ALARM")
        expected = [n for n in in_alarm if any(n.endswith(f"-{suffix}") for suffix in self.expected_alarms)]
        firing = [n for n in in_alarm if n not in expected]
        missing = sorted(set(names) - set(states))
        if firing:
            self.add("alarms", "FAIL", f"in ALARM: {', '.join(firing)}", required=False, states=states)
        elif missing:
            self.add("alarms", "UNVERIFIED", f"not found: {', '.join(missing)}", required=False)
        else:
            detail = ", ".join(f"{n}={s}" for n, s in sorted(states.items()))
            if expected:
                detail += f" ({', '.join(expected)} expected: a probe trips it)"
            self.add("alarms", "PASS", detail, required=False)

    def check_alerting(self):
        topic = self.outputs.get("alarm_topic_arn")
        if not topic:
            self.add("alerting", "UNVERIFIED", "no alarm_topic_arn output", required=False)
            return
        subs = self.clients.client("sns").list_subscriptions_by_topic(TopicArn=topic)["Subscriptions"]
        confirmed = [s for s in subs if s.get("SubscriptionArn", "").startswith("arn:")]
        if confirmed:
            self.add("alerting", "PASS", f"{len(confirmed)} confirmed subscriber(s); delivery not exercised by "
                                         "this tool", required=False)
        else:
            self.add("alerting", "UNVERIFIED", "no confirmed subscriber on the alarm topic: alarms notify no one",
                     required=False)

    def run(self):
        if self.check_target():
            self.check_artifact()
            probes = self.probes()
            queued = [p for p in probes if p.get("type", "http").startswith("sqs-")]
            done = [p for p in (self.check_probe(p) for p in probes if p not in queued) if p]
            sent = sorted((self.send_sqs(p) for p in queued), key=lambda s: s["type"] == "sqs-dead-letter")
            for probe in done:
                self.check_logs(probe)
                self.check_trace(probe)
            for message in sent:
                if message["type"] == "sqs-dead-letter":
                    self.check_dead_letter(message)
                else:
                    self.check_processed(message)
            self.check_alarms()
            self.check_alerting()
        code = exit_code(self.results)
        status = {0: "PASS", 1: "FAIL", 2: "UNVERIFIED", 3: "WRONG-TARGET"}[code]
        counts = {s: sum(r.status == s for r in self.results) for s in ("PASS", "FAIL", "UNVERIFIED")}
        return {
            "status": status,
            "exit_code": code,
            "summary": f"verify-deployment: {status} (pass {counts['PASS']}, fail {counts['FAIL']}, "
                       f"unverified {counts['UNVERIFIED']})",
            "checks": [asdict(r) for r in self.results],
        }


LAGGING = "deleted; the tag index has not caught up"


def aws_error_code(error):
    return getattr(error, "response", {}).get("Error", {}).get("Code", "")


def gone_note(clients, arn):
    """Why an ARN the tag index still lists is not a live resource, or None when it is live.

    The tagging index lists some deleted resources for minutes to hours after the owning
    service removes them, so each kind is asked of its own service.
    """
    if ":kms:" in arn and ":key/" in arn:
        key = clients.client("kms").describe_key(KeyId=arn)["KeyMetadata"]
        if key["KeyState"] == "PendingDeletion":
            return f"scheduled for deletion on {str(key['DeletionDate'])[:10]}"
        return None
    if ":event-source-mapping:" in arn:
        lam = clients.client("lambda")
        try:
            lam.get_event_source_mapping(UUID=arn.rsplit(":", 1)[1])
        except lam.exceptions.ResourceNotFoundException:
            return LAGGING
        return None
    if ":ecs:" in arn and ":cluster/" in arn:
        found = clients.client("ecs").describe_clusters(clusters=[arn])["clusters"]
        return LAGGING if not found or found[0]["status"] == "INACTIVE" else None
    if ":ecs:" in arn and ":service/" in arn:
        cluster = arn.split(":service/", 1)[1].split("/")[0]
        found = clients.client("ecs").describe_services(cluster=cluster, services=[arn])["services"]
        return LAGGING if not found or found[0]["status"] == "INACTIVE" else None
    if ":ecs:" in arn and ":task/" in arn:
        cluster = arn.split(":task/", 1)[1].split("/")[0]
        found = clients.client("ecs").describe_tasks(cluster=cluster, tasks=[arn])["tasks"]
        return LAGGING if not found or found[0]["lastStatus"] == "STOPPED" else None
    if ":ecs:" in arn and ":task-definition/" in arn:
        status = clients.client("ecs").describe_task_definition(taskDefinition=arn)["taskDefinition"]["status"]
        return f"deregistered ({status})" if status != "ACTIVE" else None
    if ":security-group-rule/" in arn:
        try:
            clients.client("ec2").describe_security_group_rules(SecurityGroupRuleIds=[arn.rsplit("/", 1)[1]])
        except Exception as error:
            if aws_error_code(error) != "InvalidSecurityGroupRuleId.NotFound":
                raise
            return LAGGING
        return None
    if ":ec2:" in arn and ":instance/" in arn:
        try:
            reservations = clients.client("ec2").describe_instances(
                InstanceIds=[arn.rsplit("/", 1)[1]])["Reservations"]
        except Exception as error:
            if aws_error_code(error) != "InvalidInstanceID.NotFound":
                raise
            return LAGGING
        states = {i["State"]["Name"] for r in reservations for i in r["Instances"]}
        if not states:
            return LAGGING
        return f"instance {states.pop()}" if states <= {"shutting-down", "terminated"} else None
    if ":ec2:" in arn and ":volume/" in arn:
        try:
            clients.client("ec2").describe_volumes(VolumeIds=[arn.rsplit("/", 1)[1]])
        except Exception as error:
            if aws_error_code(error) != "InvalidVolume.NotFound":
                raise
            return LAGGING
        return None
    if ":ec2:" in arn and ":security-group/" in arn:
        try:
            clients.client("ec2").describe_security_groups(GroupIds=[arn.rsplit("/", 1)[1]])
        except Exception as error:
            if aws_error_code(error) != "InvalidGroup.NotFound":
                raise
            return LAGGING
        return None
    if ":secretsmanager:" in arn and ":secret:" in arn:
        secret = clients.client("secretsmanager").describe_secret(SecretId=arn)
        return f"deletion requested on {str(secret['DeletedDate'])[:10]}" if secret.get("DeletedDate") else None
    if ":ec2:" in arn and ":vpc-flow-log/" in arn:
        found = clients.client("ec2").describe_flow_logs(FlowLogIds=[arn.rsplit("/", 1)[1]])["FlowLogs"]
        return None if found else LAGGING
    return None


def residue(clients, project_tag, environment, *, expect_account):
    account = clients.client("sts").get_caller_identity()["Account"]
    if account != expect_account:
        return Result("target", "FAIL", f"credentials are for account {account}, expected {expect_account}")
    tagging = clients.client("resourcegroupstaggingapi")
    arns, token = [], ""
    while True:
        page = tagging.get_resources(TagFilters=[{"Key": "Project", "Values": [project_tag]},
                                                 {"Key": "Environment", "Values": [environment]}],
                                     PaginationToken=token)
        arns += [m["ResourceARN"] for m in page["ResourceTagMappingList"]]
        token = page.get("PaginationToken") or ""
        if not token:
            break
    left, scheduled = [], []
    for arn in sorted(arns):
        note = gone_note(clients, arn)
        if note:
            scheduled.append(f"{arn} {note}")
        else:
            left.append(arn)
    if left:
        return Result("residue", "FAIL", "still tagged after destroy:\n" + "\n".join(left + scheduled))
    detail = f"no live resources tagged Project={project_tag}, Environment={environment}"
    return Result("residue", "PASS", "\n".join([detail] + scheduled))


def terraform_outputs(root: Path):
    completed = subprocess.run(["terraform", f"-chdir={root}", "output", "-json"],
                               capture_output=True, text=True)
    if completed.returncode != 0:
        return None, completed.stderr.strip()
    outputs = {k: v["value"] for k, v in json.loads(completed.stdout or "{}").items()}
    return (outputs or None), "no outputs: has this root been applied?"


def signed_http(session, region):
    import urllib.error
    import urllib.request

    from botocore.auth import SigV4Auth
    from botocore.awsrequest import AWSRequest

    def http(method, url, headers, sign, body=None):
        data = body.encode() if body is not None else None
        if sign:
            request = AWSRequest(method=method, url=url, headers=headers, data=data)
            SigV4Auth(session.get_credentials().get_frozen_credentials(), "execute-api", region).add_auth(request)
            headers = dict(request.headers.items())
        req = urllib.request.Request(url, method=method, headers=headers, data=data)
        try:
            # Longer than API Gateway's 29 s integration timeout, so a slow workflow returns its own 504.
            with urllib.request.urlopen(req, timeout=35) as response:
                return HttpResponse(response.status, {k.lower(): v for k, v in response.headers.items()},
                                    response.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as error:
            return HttpResponse(error.code, {k.lower(): v for k, v in error.headers.items()},
                                error.read().decode("utf-8", "replace"))
    return http


def print_report(report, as_json):
    if as_json:
        print(json.dumps(report, indent=2))
        return
    for c in report["checks"]:
        marker = "" if c["required"] else " (reported)"
        print(f"{c['status']:<10} {c['id']:<24} {c['detail']}{marker}")
    print(report["summary"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("verify")
    v.add_argument("project", type=Path)
    v.add_argument("--root", default="infra")
    v.add_argument("--log-wait", type=float, default=120)
    v.add_argument("--trace-wait", type=float, default=60)
    h = sub.add_parser("source-hash")
    h.add_argument("project", type=Path)
    r = sub.add_parser("residue")
    r.add_argument("--project-tag", required=True)
    r.add_argument("--environment", required=True)
    for p in (v, r):
        p.add_argument("--profile")
        p.add_argument("--expect-account", required=True)
        p.add_argument("--expect-region", required=True)
        p.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "source-hash":
        print(source_hash(args.project.resolve() / "app"))
        return 0

    import boto3

    session = boto3.Session(profile_name=args.profile, region_name=args.expect_region)
    if args.command == "residue":
        result = residue(session, args.project_tag, args.environment, expect_account=args.expect_account)
        report = {"status": result.status, "exit_code": exit_code([result]) if result.id == "target" else
                  0 if result.status == "PASS" else 1,
                  "summary": f"residue: {result.status}", "checks": [asdict(result)]}
        print_report(report, args.json)
        return report["exit_code"]

    project = args.project.resolve()
    outputs, error = terraform_outputs(project / args.root)
    if outputs is None:
        report = {"status": "UNVERIFIED", "exit_code": 2, "summary": "verify-deployment: UNVERIFIED (no outputs)",
                  "checks": [asdict(Result("target", "UNVERIFIED", error))]}
        print_report(report, args.json)
        return 2
    verifier = Verifier(project, args.root, outputs, session, signed_http(session, args.expect_region),
                        Target(args.expect_account, args.expect_region),
                        Waits(logs=args.log_wait, traces=args.trace_wait))
    report = verifier.run()
    print_report(report, args.json)
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
