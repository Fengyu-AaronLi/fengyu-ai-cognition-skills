#!/usr/bin/env python3
"""Additional integrity checks for exactly-once record operations."""

from __future__ import annotations

import hashlib
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


def digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class V11OperationIntegrity(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v11-operation-integrity-")
        self.case_dir = Path(self.temporary.name) / "case"
        self.confirmation_file = Path(self.temporary.name) / "confirmation.txt"
        self.confirmation_file.write_text("我确认按当前小实验开始。\n", encoding="utf-8")
        commands = (
            ("init", "--text", TEXT, "--case-dir", str(self.case_dir), "--clock", "2026-08-06T10:00:00Z"),
            ("plan", "--case-dir", str(self.case_dir), "--analysis", str(ANALYSIS), "--clock", "2026-08-06T10:01:00Z"),
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

    def record(
        self,
        operation_id: str,
        fact: str,
        clock: str,
        *extra: str,
    ) -> subprocess.CompletedProcess[str]:
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
            *extra,
        )

    def test_retry_precedes_stale_revision_and_clock_checks(self) -> None:
        first = self.record("retry-before-preconditions", "当天提出了一份分工初版", "2026-08-07T10:02:00Z")
        retry = self.record(
            "retry-before-preconditions",
            "当天提出了一份分工初版",
            "2026-08-06T10:02:30Z",
            "--expected-revision", "0",
        )
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        self.assertEqual(0, retry.returncode, retry.stdout + retry.stderr)
        self.assertTrue(payload(retry)["idempotent_replay"])
        self.assertEqual(4, payload(run("replay", "--case-dir", str(self.case_dir)))["event_count"])

    def test_invalid_operation_id_is_zero_write(self) -> None:
        before = (self.case_dir / "events.jsonl").read_bytes()
        result = self.record("../escape", "当天提出了一份分工初版", "2026-08-07T10:02:00Z")
        self.assertNotEqual(0, result.returncode)
        self.assertIn("operation_id_invalid", {item["code"] for item in payload(result)["errors"]})
        self.assertEqual(before, (self.case_dir / "events.jsonl").read_bytes())

    def test_replay_rejects_a_rehashed_duplicate_operation_id(self) -> None:
        first = self.record("duplicate-a", "当天提出了一份分工初版", "2026-08-07T10:02:00Z")
        second = self.record("duplicate-b", "第二天提出了另一份分工初版", "2026-08-08T10:02:00Z")
        self.assertEqual(0, first.returncode, first.stdout + first.stderr)
        self.assertEqual(0, second.returncode, second.stdout + second.stderr)

        events_path = self.case_dir / "events.jsonl"
        events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
        events[-1]["operation_id"] = events[-2]["operation_id"]
        events[-1]["event_sha256"] = digest(
            {key: value for key, value in events[-1].items() if key != "event_sha256"}
        )
        events_path.write_text(
            "\n".join(json.dumps(event, ensure_ascii=False, sort_keys=True) for event in events) + "\n",
            encoding="utf-8",
        )
        head_path = self.case_dir / "events.head.json"
        head = json.loads(head_path.read_text(encoding="utf-8"))
        head["latest_event_sha256"] = events[-1]["event_sha256"]
        head_path.write_text(json.dumps(head, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        replay = run("replay", "--case-dir", str(self.case_dir))
        self.assertNotEqual(0, replay.returncode)
        self.assertIn("duplicate_operation_id", {item["code"] for item in payload(replay)["errors"]})


if __name__ == "__main__":
    unittest.main()
