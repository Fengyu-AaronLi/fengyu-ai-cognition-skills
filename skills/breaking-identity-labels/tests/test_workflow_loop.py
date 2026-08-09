#!/usr/bin/env python3
"""Red-to-green contract for the read-only workflow convergence loop."""

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
ANALYSIS = ROOT / "tests" / "fixtures" / "analysis-c01.json"
CLOCK = "2026-08-06T00:00:00Z"
INPUT = "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    if not result.stdout.strip():
        raise AssertionError(f"no JSON output: {result.stderr}")
    return json.loads(result.stdout)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WorkflowLoopTests(unittest.TestCase):
    def test_next_is_read_only_and_routes_every_lifecycle_state(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-loop-") as tmp:
            case_dir = Path(tmp) / "case"
            initialized = run_cli(
                "init", "--text", INPUT, "--case-dir", str(case_dir), "--clock", CLOCK
            )
            self.assertEqual(0, initialized.returncode, initialized.stderr)

            before = sha256(case_dir / "case.json")
            drafted = run_cli("next", "--case-dir", str(case_dir))
            self.assertEqual(0, drafted.returncode, drafted.stderr)
            self.assertEqual(before, sha256(case_dir / "case.json"))
            drafted_payload = payload(drafted)
            self.assertFalse(drafted_payload["complete"])
            self.assertEqual("analysis", drafted_payload["stage"])
            self.assertEqual("plan", drafted_payload["next_steps"][0]["action"])
            self.assertNotIn("command", drafted_payload["next_steps"][0])

            planned = run_cli(
                "plan",
                "--case-dir",
                str(case_dir),
                "--analysis",
                str(ANALYSIS),
                "--clock",
                "2026-08-06T00:01:00Z",
            )
            self.assertEqual(0, planned.returncode, planned.stderr)
            ready = payload(run_cli("next", "--case-dir", str(case_dir)))
            self.assertEqual("experiment_ready", ready["stage"])
            self.assertEqual("start", ready["next_steps"][0]["action"])

            confirmation = Path(tmp) / "user-confirmation.txt"
            confirmation.write_text("我愿意开始这个现实实验。", encoding="utf-8")
            started = run_cli(
                "start",
                "--case-dir",
                str(case_dir),
                "--confirmation-file",
                str(confirmation),
                "--clock",
                "2026-08-06T00:02:00Z",
            )
            self.assertEqual(0, started.returncode, started.stderr)
            observing = payload(
                run_cli(
                    "next",
                    "--case-dir",
                    str(case_dir),
                    "--clock",
                    "2026-08-06T00:02:00Z",
                )
            )
            self.assertEqual("observation", observing["stage"])
            self.assertEqual("record", observing["next_steps"][0]["action"])

            recorded = run_cli(
                "record",
                "--case-dir",
                str(case_dir),
                "--kind",
                "experiment_result",
                "--source-text",
                "完成了三分钟团队更新。",
                "--fact",
                "完成了三分钟团队更新",
                "--context",
                "团队周会",
                "--timeframe",
                "今天",
                "--clock",
                "2026-08-20T00:03:00Z",
            )
            self.assertEqual(0, recorded.returncode, recorded.stderr)
            reviewable = payload(
                run_cli(
                    "next",
                    "--case-dir",
                    str(case_dir),
                    "--clock",
                    "2026-08-20T00:03:00Z",
                )
            )
            self.assertEqual("review", reviewable["stage"])
            self.assertEqual("review", reviewable["next_steps"][0]["action"])

            reviewed = run_cli(
                "review",
                "--case-dir",
                str(case_dir),
                "--classification",
                "weakens",
                "--rationale",
                "本次完成只能削弱预先登记的窄命题。",
                "--clock",
                "2026-08-20T00:04:00Z",
            )
            self.assertEqual(0, reviewed.returncode, reviewed.stderr)
            complete = payload(run_cli("next", "--case-dir", str(case_dir)))
            self.assertTrue(complete["complete"])
            self.assertEqual("complete", complete["stage"])
            self.assertEqual([], complete["next_steps"])

    def test_next_blocks_when_event_chain_and_materialized_state_disagree(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-loop-") as tmp:
            case_dir = Path(tmp) / "case"
            result = run_cli("init", "--text", INPUT, "--case-dir", str(case_dir), "--clock", CLOCK)
            self.assertEqual(0, result.returncode, result.stderr)
            case = json.loads((case_dir / "case.json").read_text(encoding="utf-8"))
            case["case_id"] = "silently-changed"
            (case_dir / "case.json").write_text(
                json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )

            blocked = run_cli("next", "--case-dir", str(case_dir))
            self.assertNotEqual(0, blocked.returncode)
            blocked_payload = payload(blocked)
            self.assertEqual("integrity_failure", blocked_payload["stage"])
            self.assertFalse(blocked_payload["complete"])
            self.assertEqual([], blocked_payload["next_steps"])
            self.assertIn(
                "materialized_state_mismatch",
                {item["code"] for item in blocked_payload["errors"]},
            )

    def test_next_can_route_nonpersistent_preference_and_safety_cases(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-loop-") as tmp:
            preference_path = Path(tmp) / "preference.json"
            preference = run_cli(
                "scaffold",
                "--text",
                "我喜欢小型讨论，不喜欢大型酒会。",
                "--clock",
                CLOCK,
            )
            preference_path.write_text(preference.stdout, encoding="utf-8")
            preference_next = payload(run_cli("next", "--case", str(preference_path)))
            self.assertTrue(preference_next["complete"])
            self.assertEqual("preference_acknowledgement", preference_next["stage"])
            self.assertEqual([], preference_next["next_steps"])

            safety_path = Path(tmp) / "safety.json"
            safety = run_cli(
                "scaffold",
                "--text",
                "AI 说我是废物，我今晚想伤害自己。",
                "--clock",
                CLOCK,
            )
            safety_path.write_text(safety.stdout, encoding="utf-8")
            safety_next = payload(run_cli("next", "--case", str(safety_path)))
            self.assertFalse(safety_next["complete"])
            self.assertEqual("safety_support", safety_next["stage"])
            actions = [item["action"] for item in safety_next["next_steps"]]
            self.assertEqual(["seek_immediate_real_world_support"], actions)
            self.assertNotIn("plan", actions)

    def test_next_never_turns_untrusted_user_text_into_a_shell_command(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-loop-") as tmp:
            sentinel = Path(tmp) / "should-not-exist"
            text = f"AI 说我是低能量型，所以 $(touch {sentinel})，我不适合工作。"
            case_dir = Path(tmp) / "case"
            initialized = run_cli(
                "init", "--text", text, "--case-dir", str(case_dir), "--clock", CLOCK
            )
            self.assertEqual(0, initialized.returncode, initialized.stderr)
            result = run_cli("next", "--case-dir", str(case_dir))
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertNotIn("command", result.stdout)
            self.assertFalse(sentinel.exists())


if __name__ == "__main__":
    unittest.main()
