#!/usr/bin/env python3
"""V10 red contracts for state transaction and concurrent-writer integrity."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
ANALYSIS = ROOT / "tests" / "fixtures" / "analysis-c01.json"
STATE_FILES = ("case.json", "events.jsonl", "events.head.json")
TEXT = "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def state_hashes(case_dir: Path) -> dict[str, str | None]:
    return {
        name: hashlib.sha256((case_dir / name).read_bytes()).hexdigest()
        if (case_dir / name).is_file()
        else None
        for name in STATE_FILES
    }


def init_case(case_dir: Path, clock: str = "2026-08-06T22:10:00Z") -> None:
    result = run_cli("init", "--text", TEXT, "--case-dir", str(case_dir), "--clock", clock)
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)


def plan_case(case_dir: Path, clock: str) -> subprocess.CompletedProcess[str]:
    return run_cli(
        "plan",
        "--case-dir",
        str(case_dir),
        "--analysis",
        str(ANALYSIS),
        "--clock",
        clock,
    )


class V10StateTransactionRegressions(unittest.TestCase):
    def assert_failed_plan_preserves_triplet(self, obstacle: str) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v10-atomic-") as tmp:
            case_dir = Path(tmp) / "case"
            init_case(case_dir)
            before = state_hashes(case_dir)
            (case_dir / obstacle).mkdir()
            result = plan_case(case_dir, "2026-08-06T22:11:00Z")
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, state_hashes(case_dir))
            replay = run_cli("replay", "--case-dir", str(case_dir))
            self.assertEqual(0, replay.returncode, replay.stdout + replay.stderr)
            self.assertTrue(json.loads(replay.stdout)["valid"])

    def test_case_stage_failure_is_zero_write(self) -> None:
        self.assert_failed_plan_preserves_triplet(".case.json.tmp")

    def test_head_stage_failure_is_zero_write(self) -> None:
        self.assert_failed_plan_preserves_triplet(".events.head.json.tmp")

    @unittest.skipUnless(sys.platform == "darwin", "immutable flag regression is macOS-specific")
    def test_case_replace_failure_rolls_back_the_event_log(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v10-case-replace-") as tmp:
            case_dir = Path(tmp) / "case"
            init_case(case_dir)
            before = state_hashes(case_dir)
            target = case_dir / "case.json"
            os.chflags(target, os.stat(target).st_flags | 0x00000002)
            try:
                result = plan_case(case_dir, "2026-08-06T22:12:00Z")
            finally:
                os.chflags(target, os.stat(target).st_flags & ~0x00000002)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, state_hashes(case_dir))
            replay = run_cli("replay", "--case-dir", str(case_dir))
            self.assertEqual(0, replay.returncode, replay.stdout + replay.stderr)

    @unittest.skipUnless(sys.platform == "darwin", "immutable flag regression is macOS-specific")
    def test_head_replace_failure_rolls_back_case_and_event_log(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v10-head-replace-") as tmp:
            case_dir = Path(tmp) / "case"
            init_case(case_dir)
            before = state_hashes(case_dir)
            target = case_dir / "events.head.json"
            os.chflags(target, os.stat(target).st_flags | 0x00000002)
            try:
                result = plan_case(case_dir, "2026-08-06T22:13:00Z")
            finally:
                os.chflags(target, os.stat(target).st_flags & ~0x00000002)
            self.assertNotEqual(0, result.returncode)
            self.assertEqual(before, state_hashes(case_dir))
            replay = run_cli("replay", "--case-dir", str(case_dir))
            self.assertEqual(0, replay.returncode, replay.stdout + replay.stderr)

    def test_eight_concurrent_record_writers_have_one_winner_and_valid_replay(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v10-concurrent-") as tmp:
            case_dir = Path(tmp) / "case"
            init_case(case_dir, "2026-08-06T22:20:00Z")
            planned = plan_case(case_dir, "2026-08-06T22:21:00Z")
            self.assertEqual(0, planned.returncode, planned.stdout + planned.stderr)
            confirmation_file = Path(tmp) / "confirmation.txt"
            confirmation_file.write_text("我确认按当前小实验开始。\n", encoding="utf-8")
            started = run_cli(
                "start", "--case-dir", str(case_dir),
                "--confirmation-file", str(confirmation_file),
                "--clock", "2026-08-06T22:22:00Z",
            )
            self.assertEqual(0, started.returncode, started.stdout + started.stderr)

            barrier = __import__("threading").Barrier(8)

            def writer(index: int) -> subprocess.CompletedProcess[str]:
                barrier.wait()
                fact = f"完成更新{index}"
                return run_cli(
                    "record",
                    "--case-dir",
                    str(case_dir),
                    "--kind",
                    "experiment_result",
                    "--source-text",
                    f"并发结果{index}：{fact}。",
                    "--fact",
                    fact,
                    "--context",
                    f"并发分支{index}",
                    "--timeframe",
                    "同时",
                    "--expected-revision",
                    "2",
                    "--clock",
                    "2026-08-06T22:23:00Z",
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
                results = list(executor.map(writer, range(8)))
            self.assertEqual(1, sum(result.returncode == 0 for result in results))

            replay = run_cli("replay", "--case-dir", str(case_dir))
            self.assertEqual(0, replay.returncode, replay.stdout + replay.stderr)
            payload = json.loads(replay.stdout)
            self.assertTrue(payload["valid"])
            self.assertEqual(4, payload["event_count"])
            self.assertEqual(3, payload["latest_revision"])

    def test_transaction_and_lock_primitives_are_part_of_the_runtime(self) -> None:
        source = CLI.read_text(encoding="utf-8")
        for marker in (
            "def case_lock(",
            "def commit_state_bundle(",
            "def recover_pending_transaction(",
            "transaction_recovery_required",
        ):
            self.assertIn(marker, source)


if __name__ == "__main__":
    unittest.main()
