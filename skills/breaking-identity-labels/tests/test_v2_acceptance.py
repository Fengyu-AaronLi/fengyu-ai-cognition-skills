#!/usr/bin/env python3
"""Package-level acceptance tests for the executable V2 Skill."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEST_TMP = ROOT / "tests" / ".tmp"
EVAL_RUNNER = ROOT / "evals" / "run_v2_evals.py"
PACKAGE_VALIDATOR = ROOT / "evals" / "validate.py"
DEMO_BUILDER = ROOT / "scripts" / "build_demo.py"


def run_python(path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(path), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class EvaluationContractTests(unittest.TestCase):
    def test_heldout_set_is_large_and_not_a_copy_of_original_cases(self) -> None:
        heldout = json.loads((ROOT / "evals" / "heldout-cases.json").read_text(encoding="utf-8"))["cases"]
        original = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]
        upgrade = json.loads((ROOT / "evals" / "upgrade-cases.json").read_text(encoding="utf-8"))["cases"]
        self.assertGreaterEqual(len(heldout), 30)
        heldout_text = {case["text"] for case in heldout}
        frozen_text = {case["input"] for case in original + upgrade}
        self.assertTrue(heldout_text.isdisjoint(frozen_text))

    def test_router_eval_meets_registered_thresholds(self) -> None:
        result = run_python(EVAL_RUNNER)
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])
        self.assertGreaterEqual(payload["heldout"]["count"], 30)
        self.assertGreaterEqual(payload["heldout"]["trigger_macro_f1"], 0.90)
        self.assertGreaterEqual(payload["heldout"]["mode_accuracy"], 0.90)
        self.assertEqual(payload["boundary"]["count"], payload["boundary"]["passed"])
        self.assertGreaterEqual(payload["boundary"]["count"], 12)
        self.assertEqual(payload["regression"]["count"], payload["regression"]["passed"])
        self.assertEqual(payload["policy"]["critical_injections"], payload["policy"]["blocked"])
        self.assertGreaterEqual(payload["policy"]["critical_injections"], 12)

    def test_package_validator_checks_v2_runtime(self) -> None:
        result = run_python(PACKAGE_VALIDATOR)
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertIn("V2 runtime", result.stdout)


class DemoAndOrchestrationTests(unittest.TestCase):
    def setUp(self) -> None:
        TEST_TMP.mkdir(parents=True, exist_ok=True)
        self.output_dir = TEST_TMP / "generated-demo"
        if self.output_dir.exists():
            for path in sorted(self.output_dir.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            self.output_dir.rmdir()

    def tearDown(self) -> None:
        if self.output_dir.exists():
            for path in sorted(self.output_dir.rglob("*"), reverse=True):
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    path.rmdir()
            self.output_dir.rmdir()

    def test_demo_rebuilds_machine_readable_artifacts(self) -> None:
        result = run_python(
            DEMO_BUILDER,
            "--output-dir",
            str(self.output_dir),
            "--clock",
            "2026-08-05T10:00:00Z",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        required = ["case.json", "events.jsonl", "report.md", "run-manifest.json"]
        self.assertEqual([], [name for name in required if not (self.output_dir / name).is_file()])
        manifest = json.loads((self.output_dir / "run-manifest.json").read_text(encoding="utf-8"))
        self.assertTrue(manifest["validation"]["valid"])
        self.assertTrue(manifest["replay"]["valid"])
        self.assertEqual("reviewed", manifest["final_status"])
        self.assertEqual(5, manifest["replay"]["event_count"])
        self.assertEqual(4, manifest["replay"]["latest_revision"])
        self.assertTrue(manifest["idempotency"]["retry_returned_original"])
        self.assertEqual(3, manifest["idempotency"]["retry_revision"])
        events = [
            json.loads(line)
            for line in (self.output_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
        ]
        operation_events = [event for event in events if event.get("operation_id") == "demo-record-001"]
        self.assertEqual(1, len(operation_events))
        actions = [command[0] for command in manifest["commands"]]
        for action in ("init", "plan", "start", "record", "review", "validate", "replay", "render"):
            self.assertIn(action, actions)
        clocks = [
            command[command.index("--clock") + 1]
            for command in manifest["commands"]
            if "--clock" in command
        ]
        self.assertEqual(len(clocks), len(set(clocks)))
        report = (self.output_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("## 实验复核", report)
        self.assertIn("分类：weakens", report)

    def test_demo_force_preserves_unrelated_files_in_a_nonempty_output_directory(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        sentinel = self.output_dir / "user-note.txt"
        sentinel.write_text("preserve me\n", encoding="utf-8")
        result = run_python(
            DEMO_BUILDER,
            "--output-dir",
            str(self.output_dir),
            "--clock",
            "2026-08-05T10:00:00Z",
            "--force",
        )
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual("preserve me\n", sentinel.read_text(encoding="utf-8"))
        self.assertTrue((self.output_dir / "events.head.json").is_file())

    def test_skill_orchestrates_commands_instead_of_repeating_runtime(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        for command in (
            "identity_label_case.py scaffold",
            "identity_label_case.py init",
            "identity_label_case.py plan",
            "identity_label_case.py validate",
            "identity_label_case.py record",
            "identity_label_case.py replay",
            "identity_label_case.py render",
        ):
            self.assertIn(command, skill)
        self.assertLess(len(skill.splitlines()), 220)
        self.assertIn("portable fallback", skill.lower())


if __name__ == "__main__":
    unittest.main()
