#!/usr/bin/env python3
"""V28 red contract: a record observation must cite that record's new evidence."""

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


def digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class RecordEventBindingTests(unittest.TestCase):
    def test_replay_rejects_observation_bound_to_old_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v28-record-binding-") as temporary:
            case_dir = Path(temporary) / "case"
            confirmation = Path(temporary) / "user-confirmation.txt"
            confirmation.write_text("我愿意开始这个现实实验。", encoding="utf-8")
            commands = (
                ("init", "--text", TEXT, "--case-dir", str(case_dir), "--clock", "2026-08-06T10:00:00Z"),
                ("plan", "--case-dir", str(case_dir), "--analysis", str(ANALYSIS), "--clock", "2026-08-06T10:01:00Z"),
                (
                    "start", "--case-dir", str(case_dir),
                    "--confirmation-file", str(confirmation),
                    "--clock", "2026-08-06T10:02:00Z",
                ),
                (
                    "record", "--case-dir", str(case_dir), "--kind", "experiment_result",
                    "--source-text", "结果：当天提出了一份可修改的分工初版。",
                    "--fact", "当天提出了一份可修改的分工初版",
                    "--context", "团队分工任务", "--timeframe", "实验第一天",
                    "--clock", "2026-08-07T10:02:00Z",
                ),
            )
            for command in commands:
                result = run(*command)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

            events_path = case_dir / "events.jsonl"
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            record = events[-1]
            label = record["snapshot"]["analysis"]["labels"][0]
            observation = record["snapshot"]["analysis"]["observations"][-1]
            observation["text"] = label["text"]
            observation["source"] = dict(label["source"])
            record["snapshot_sha256"] = digest(record["snapshot"])
            record["event_sha256"] = digest(
                {key: value for key, value in record.items() if key != "event_sha256"}
            )
            events_path.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in events) + "\n",
                encoding="utf-8",
            )

            head_path = case_dir / "events.head.json"
            head = json.loads(head_path.read_text(encoding="utf-8"))
            head["latest_event_sha256"] = record["event_sha256"]
            head["latest_snapshot_sha256"] = record["snapshot_sha256"]
            head_path.write_text(json.dumps(head, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            replay = run("replay", "--case-dir", str(case_dir))
            self.assertNotEqual(0, replay.returncode)
            payload = json.loads(replay.stdout)
            self.assertIn(
                "event_record_binding_mismatch",
                {item["code"] for item in payload["errors"]},
                payload,
            )


if __name__ == "__main__":
    unittest.main()
