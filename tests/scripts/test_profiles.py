import copy
import json
import sys
import unittest
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SKILL = REPO / "skills" / "creating-aws-projects"
sys.path.insert(0, str(SKILL / "scripts"))

import profiles  # noqa: E402

TODAY = date(2026, 11, 8)
PROFILE_ID = "apigw-lambda.python3.13-arm64-zip"


def shipped_profile():
    return json.loads((SKILL / "profiles" / f"{PROFILE_ID}.json").read_text(encoding="utf-8"))


class ShippedProfileTest(unittest.TestCase):
    def test_shipped_profile_passes_today(self):
        result = profiles.check_profile(shipped_profile(), TODAY)

        self.assertEqual("PASS", result.status, result.reasons)

    def test_shipped_profile_is_not_advertised_as_supported_without_sandbox_evidence(self):
        profile = shipped_profile()

        if profile["status"] == "supported":
            self.assertTrue(profile["evidence"].get("sandbox"), "supported needs sandbox evidence")

    def test_profile_file_name_matches_its_id(self):
        for path in (SKILL / "profiles").glob("*.json"):
            self.assertEqual(path.stem, json.loads(path.read_text(encoding="utf-8"))["id"])


class LifecycleTest(unittest.TestCase):
    def test_preview_runtime_fails(self):
        profile = shipped_profile()
        profile["runtime"]["preview"] = True

        result = profiles.check_profile(profile, TODAY)

        self.assertEqual("FAIL", result.status)
        self.assertIn("preview", " ".join(result.reasons))

    def test_deprecated_runtime_fails(self):
        result = profiles.check_profile(shipped_profile(), date(2029, 7, 1))

        self.assertEqual("FAIL", result.status)
        self.assertIn("deprecat", " ".join(result.reasons))

    def test_runtime_inside_runway_fails(self):
        result = profiles.check_profile(shipped_profile(), date(2028, 12, 1))

        self.assertEqual("FAIL", result.status)
        self.assertIn("runway", " ".join(result.reasons))

    def test_stale_source_check_is_unverified(self):
        result = profiles.check_profile(shipped_profile(), date(2027, 8, 1))

        self.assertEqual("UNVERIFIED", result.status)
        self.assertIn("recheck", " ".join(result.reasons))

    def test_unscheduled_deprecation_is_unverified_not_pass(self):
        profile = shipped_profile()
        profile["runtime"]["lifecycle"]["deprecation"] = None

        result = profiles.check_profile(profile, TODAY)

        self.assertEqual("UNVERIFIED", result.status)

    def test_managed_service_with_no_runtime_lifecycle_passes_with_a_reason(self):
        profile = shipped_profile()
        profile["architecture"] = "managed"
        profile["runtime"]["lifecycle"] = {"deprecation": "none", "reason": "Step Functions has no runtime versions"}

        result = profiles.check_profile(profile, TODAY)

        self.assertEqual("PASS", result.status, result.reasons)

    def test_versioned_runtime_cannot_claim_no_lifecycle(self):
        profile = shipped_profile()
        profile["runtime"]["lifecycle"] = {"deprecation": "none", "reason": "we will keep it updated"}

        result = profiles.check_profile(profile, date(2030, 1, 1))

        self.assertEqual("FAIL", result.status)
        self.assertIn("managed", " ".join(result.reasons))

    def test_no_lifecycle_without_a_reason_fails(self):
        profile = shipped_profile()
        profile["architecture"] = "managed"
        profile["runtime"]["lifecycle"] = {"deprecation": "none", "reason": " "}

        result = profiles.check_profile(profile, TODAY)

        self.assertEqual("FAIL", result.status)
        self.assertIn("reason", " ".join(result.reasons))


class CompletenessTest(unittest.TestCase):
    def test_missing_required_field_fails(self):
        for dotted in ["runtime.identifier", "runtime.lifecycle", "runtime.source", "architecture", "packaging", "tools"]:
            with self.subTest(field=dotted):
                profile = copy.deepcopy(shipped_profile())
                parent = profile
                *path, leaf = dotted.split(".")
                for key in path:
                    parent = parent[key]
                del parent[leaf]

                result = profiles.check_profile(profile, TODAY)

                self.assertEqual("FAIL", result.status)
                self.assertIn(dotted, " ".join(result.reasons))

    def test_supported_without_sandbox_evidence_fails(self):
        profile = shipped_profile()
        profile["status"] = "supported"
        profile["evidence"]["sandbox"] = None

        result = profiles.check_profile(profile, TODAY)

        self.assertEqual("FAIL", result.status)
        self.assertIn("sandbox", " ".join(result.reasons))


class ResolveTest(unittest.TestCase):
    def test_known_combination_resolves_to_shipped_profile(self):
        result = profiles.resolve(SKILL / "profiles", "apigw-lambda", "python3.13", "arm64", "zip", TODAY, region="us-east-1")

        self.assertEqual("PASS", result.status, result.reasons)
        self.assertEqual(PROFILE_ID, result.profile_id)

    def test_sqs_worker_profile_resolves(self):
        result = profiles.resolve(SKILL / "profiles", "sqs-lambda-worker", "python3.13", "arm64", "zip", TODAY, region="us-east-1")

        self.assertEqual("PASS", result.status, result.reasons)
        self.assertEqual("sqs-lambda-worker.python3.13-arm64-zip", result.profile_id)

    def test_ecs_web_profile_resolves(self):
        result = profiles.resolve(SKILL / "profiles", "ecs-web", "python3.13", "arm64", "container", TODAY, region="us-east-1")

        self.assertEqual("PASS", result.status, result.reasons)
        self.assertEqual("ecs-web.python3.13-arm64-container", result.profile_id)

    def test_step_functions_profile_resolves(self):
        result = profiles.resolve(SKILL / "profiles", "apigw-step-functions", "asl-jsonpath", "managed", "definition",
                                  TODAY, region="us-east-1")

        self.assertEqual("PASS", result.status, result.reasons)
        self.assertEqual("apigw-step-functions.asl-jsonpath-managed-definition", result.profile_id)

    def test_alb_ec2_profile_resolves(self):
        result = profiles.resolve(SKILL / "profiles", "alb-ec2", "python3.13", "arm64", "ami", TODAY, region="us-east-1")

        self.assertEqual("PASS", result.status, result.reasons)
        self.assertEqual("alb-ec2.python3.13-arm64-ami", result.profile_id)

    def test_network_profile_resolves(self):
        result = profiles.resolve(SKILL / "profiles", "network", "none", "managed", "module", TODAY, region="us-east-1")

        self.assertEqual("PASS", result.status, result.reasons)
        self.assertEqual("network.none-managed-module", result.profile_id)

    def test_every_template_has_a_packaging_entry(self):
        for template in (SKILL / "templates").iterdir():
            self.assertIn(template.name, profiles.TEMPLATE_PACKAGING)

    def test_region_outside_the_profile_is_unverified(self):
        result = profiles.resolve(SKILL / "profiles", "apigw-lambda", "python3.13", "arm64", "zip", TODAY,
                                  region="eu-west-1")

        self.assertEqual("UNVERIFIED", result.status)
        self.assertIn("eu-west-1", " ".join(result.reasons))

    def test_unknown_combination_is_unverified(self):
        for runtime, arch in [("python3.13", "x86_64"), ("python3.14", "arm64"), ("nodejs22.x", "arm64")]:
            with self.subTest(runtime=runtime, arch=arch):
                result = profiles.resolve(SKILL / "profiles", "apigw-lambda", runtime, arch, "zip", TODAY, region="us-east-1")

                self.assertEqual("UNVERIFIED", result.status)
                self.assertIsNone(result.profile_id)


if __name__ == "__main__":
    unittest.main()
