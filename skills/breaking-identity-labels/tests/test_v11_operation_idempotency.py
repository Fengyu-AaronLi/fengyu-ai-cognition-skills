#!/usr/bin/env python3
"""V11 exactly-once contracts for retried state mutations."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
TEXT = (ROOT / "examples" / "real-run" / "demo-input.txt").read_text(encoding="utf-8").strip()
ANALYSIS = ROOT / "examples" / "real-run" / "analysis.json"


def run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


class V11OperationIdempotency(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v11-operation-")
        self.case_dir = Path(self.temporary.name) / "case"
        self.confirmation_file = Path(self.temporary.name) / "confirmation.txt"
        self.confirmation_file.write_text("我确认按当前小实验开始。\n", encoding="utf-8")
        commands = (
            ("init", "--text", TEXT, "--case-dir", str(self.case_dir), "--clock", "2026-08-06T10:00:00Z"),
            (
                "plan", "--case-dir", str(self.case_dir), "--analysis", str(ANALYSIS),
                "--clock", "2026-08-06T10:01:00Z",
            ),
            (
                "start", "--case-dir", str(self.case_dir),
                "--confirmation-file", str(self.confirmation_file),
                "--clock", "2026-08-06T10:02:00Z",
            ),
        )
        for command in commands:
            result = run(*command)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def record(self, operation_id: str, fact: str, clock: str) -> subprocess.CompletedProcess[str]:
        return run(
            "record",
            "--case-dir", str(self.case_dir),
            "--kind", "experiment_result",
            "--source-text", f"结果：{fact}。",
            "--fact", fact,
            "--context", "团队分工任务",
            "--timeframe", "实验第一天",
            "--operation-id", operation_id,
            "--clock", clock,
        )

    def test_same_operation_id_and_payload_is_exactly_once(self) -> None:
        first = self.record("record-demo-001", "当天提出了一份分工初版", "2026-08-07T10:02:00Z")
        retry = self.record("record-demo-001", "当天提出了一份分工初版", "2026-08-07T10:03:00Z")
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        self.assertEqual(0, retry.returncode, retry.stdout + retry.stderr)
        self.assertTrue(payload(retry)["idempotent_replay"])
        self.assertEqual(payload(first)["case"]["revision"], payload(retry)["case"]["revision"])
        replay = payload(run("replay", "--case-dir", str(self.case_dir)))
        self.assertTrue(replay["valid"])
        self.assertEqual(4, replay["event_count"])

    def test_same_operation_id_with_different_payload_is_rejected_without_write(self) -> None:
        first = self.record("record-demo-002", "当天提出了一份分工初版", "2026-08-07T10:02:00Z")
        before = (self.case_dir / "events.jsonl").read_bytes()
        conflict = self.record("record-demo-002", "当天取消了分工任务", "2026-08-07T10:03:00Z")
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        self.assertNotEqual(0, conflict.returncode)
        self.assertIn("operation_id_conflict", {item["code"] for item in payload(conflict)["errors"]})
        self.assertEqual(before, (self.case_dir / "events.jsonl").read_bytes())

    def test_distinct_operation_ids_allow_distinct_observations(self) -> None:
        first = self.record("record-demo-003", "当天提出了一份分工初版", "2026-08-07T10:02:00Z")
        second = self.record("record-demo-004", "当天提出了一份分工初版", "2026-08-08T10:02:00Z")
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)
        self.assertEqual(4, payload(second)["case"]["revision"])
        self.assertEqual(5, payload(run("replay", "--case-dir", str(self.case_dir)))["event_count"])


if __name__ == "__main__":
    unittest.main()
