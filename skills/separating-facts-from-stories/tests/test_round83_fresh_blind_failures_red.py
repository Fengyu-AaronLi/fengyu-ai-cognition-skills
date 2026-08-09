from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
FIXTURE_PATH = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "round83_fresh_blind_failures.json"
)
WORKFLOW_SCRIPT = SCRIPTS_DIR / "workflow.py"
sys.path.insert(0, str(SCRIPTS_DIR))

import casefile  # noqa: E402


FIXTURE = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
FROZEN_CASES_SHA256 = "861589dc2b7be75fa49210c2314201fcf6223d398b1ac9d35377f0567db54299"
FROZEN_SOURCE_SHA256 = {
    "manifest": "c28c8498843ff03a6c42c17f7d4c69c8272a973d08d052765be0c2504eff2b04",
    "report": "5c960b94d051abfa5ef94993505d40caf9d1cf666331332824a68474a4c7640d",
    "failures": "f08e75cb82f65a82396a1482fa9877c3d52436e45996e0d1bae341ac7fe6b2d7",
    "results_cases": "843ffc0d33a4ac225e0c2f0c8f5e13ddcf4a4acebcbe4698a545da9bd0fa47e8",
    "results_invocations": "0a8b3c8e6da4bda22f7b7002f82912bc81efe0f9b27a72f24b0bff51eb8924b6",
}


def workflow_auto_route(prompt: str, case_id: str) -> str:
    with tempfile.TemporaryDirectory(prefix="round83-fresh-red-") as temp_dir:
        root = Path(temp_dir)
        input_path = root / "input.txt"
        input_path.write_text(prompt, encoding="utf-8")
        completed = subprocess.run(
            [
                sys.executable,
                str(WORKFLOW_SCRIPT),
                "start",
                "--input",
                str(input_path),
                "--workspace",
                str(root / "workspace"),
                "--case-id",
                case_id,
                "--mode",
                "auto",
            ],
            cwd=SKILL_DIR,
            text=True,
            capture_output=True,
            check=False,
        )
        if completed.returncode != 0:
            raise AssertionError(
                f"workflow start failed for {case_id}: {completed.stderr}"
            )
        return json.loads(completed.stdout)["mode"]


class Round83FreshBlindFixtureIntegrityTests(unittest.TestCase):
    def test_fixture_identity_and_case_count_are_frozen(self) -> None:
        self.assertIs(FIXTURE["frozen"], True)
        self.assertEqual("round83-fresh-blind-real-failures", FIXTURE["fixture_id"])
        self.assertEqual(52, FIXTURE["case_count"])
        self.assertEqual(52, len(FIXTURE["cases"]))
        self.assertEqual(52, len({case["id"] for case in FIXTURE["cases"]}))

    def test_case_payload_sha_is_frozen(self) -> None:
        payload = json.dumps(
            FIXTURE["cases"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        actual = hashlib.sha256(payload).hexdigest()
        self.assertEqual(FROZEN_CASES_SHA256, FIXTURE["cases_sha256"])
        self.assertEqual(FROZEN_CASES_SHA256, actual)

    def test_source_artifact_and_environment_metadata_are_frozen(self) -> None:
        observed = {
            name: record["sha256"]
            for name, record in FIXTURE["source_artifacts"].items()
        }
        self.assertEqual(FROZEN_SOURCE_SHA256, observed)
        environment = FIXTURE["generation_environment"]
        self.assertEqual(["replayC", "replayD"], environment["valid_environments"])
        self.assertEqual(480, environment["invocation_count"])
        self.assertEqual(0, environment["environment_divergence_cases"])
        self.assertEqual(3, environment["entry_divergence_cases"])


class Round83FreshBlindRouteRedTests(unittest.TestCase):
    """One immutable RED test per real fresh-blind failure."""


def make_route_test(case: dict[str, object]):
    def test(self: Round83FreshBlindRouteRedTests) -> None:
        case_id = str(case["id"])
        prompt = str(case["prompt"])
        expected = str(case["expected_route"])
        casefile_route = casefile.make_draft(prompt, case_id, "auto")["mode"]
        workflow_route = workflow_auto_route(prompt, case_id)

        with self.subTest(case_id=case_id, entry="casefile"):
            self.assertEqual(expected, casefile_route)
        with self.subTest(case_id=case_id, entry="workflow"):
            self.assertEqual(expected, workflow_route)
        with self.subTest(case_id=case_id, check="entry_consistency"):
            self.assertEqual(casefile_route, workflow_route)

    return test


for frozen_case in FIXTURE["cases"]:
    method_name = "test_" + str(frozen_case["id"]).lower().replace("-", "_")
    setattr(Round83FreshBlindRouteRedTests, method_name, make_route_test(frozen_case))


if __name__ == "__main__":
    unittest.main()
