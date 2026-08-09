#!/usr/bin/env python3
"""R66 red contracts for mixed preferences and missing-lock state integrity."""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-07T02:00:00Z"
PLAN_CLOCK = "2026-08-07T02:01:00Z"
STATE_FILES = ("case.json", "events.jsonl", "events.head.json")
LOCK_FILE = ".case.lock"
MIXED_PREFERENCE_TEXT = (
    "我喜欢安静房间工作，不喜欢大型聚会，所以我不适合带团队，也不可能做好公开表达。"
)


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    return json.loads(result.stdout)


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def tree_snapshot(case_dir: Path) -> dict[str, bytes | str]:
    snapshot: dict[str, bytes | str] = {}
    for item in sorted(case_dir.rglob("*")):
        relative = str(item.relative_to(case_dir))
        if item.is_symlink():
            snapshot[relative] = f"symlink:{item.readlink()}"
        elif item.is_file():
            snapshot[relative] = item.read_bytes()
        elif item.is_dir():
            snapshot[relative] = "directory"
    return snapshot


class MixedStablePreferenceContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v66-preference-")
        self.root = Path(self.temporary.name)
        scaffold_result = run_cli(
            "scaffold",
            "--text",
            MIXED_PREFERENCE_TEXT,
            "--case-id",
            "v66-mixed-preference",
            "--clock",
            CLOCK,
        )
        self.assertEqual(0, scaffold_result.returncode, scaffold_result.stdout + scaffold_result.stderr)
        self.scaffold = payload(scaffold_result)
        self.assertEqual("deconstruct", self.scaffold["route"]["mode"])
        self.scaffold_path = self.root / "scaffold.json"
        write_json(self.scaffold_path, self.scaffold)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def planned_analysis(self, *, primary_variable: str, action: str) -> dict:
        analysis = copy.deepcopy(self.scaffold["analysis"])
        judgment = analysis["judgments"][0]
        source = judgment["source"]
        judgment_id = f"J-{source['evidence_id']}-{source['start']}-{source['end']}"
        analysis["candidate_variables"] = [
            {
                "name": primary_variable,
                "status": "hypothesis",
                "reason": "仅用于检验带团队能力判决，不授权纠正稳定偏好",
            }
        ]
        analysis["experiment"] = {
            "status": "planned",
            "target_claim": "在一次具体任务中，我是否仍不适合带团队",
            "target_judgment_ids": [judgment_id],
            "primary_variable": primary_variable,
            "duration": {"value": 7, "unit": "days"},
            "action": action,
            "kept_constant": ["团队更新主题", "任务时长"],
            "measures": ["是否完成三分钟团队更新"],
            "support_if": ["在约定条件下未完成三分钟团队更新"],
            "weaken_if": ["在约定条件下完成三分钟团队更新"],
            "reversible": True,
            "reversibility_note": "实验结束后恢复原工作与社交安排",
        }
        return analysis

    def assert_compile_rejects_preference_correction(
        self,
        *,
        name: str,
        primary_variable: str,
        action: str,
    ) -> None:
        analysis_path = self.root / f"{name}-analysis.json"
        output_path = self.root / f"{name}-case.json"
        write_json(
            analysis_path,
            self.planned_analysis(primary_variable=primary_variable, action=action),
        )
        result = run_cli(
            "compile",
            "--scaffold",
            str(self.scaffold_path),
            "--analysis",
            str(analysis_path),
            "--out",
            str(output_path),
            "--clock",
            PLAN_CLOCK,
        )
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertFalse(output_path.exists(), "rejected preference correction must write no case")
        self.assertIn(
            "preference_correction",
            {item["code"] for item in payload(result)["errors"]},
        )

    def test_mixed_deconstruct_cannot_use_the_stable_preference_as_primary_variable(self) -> None:
        self.assert_compile_rejects_preference_correction(
            name="preference-variable",
            primary_variable="是否参加大型聚会",
            action="在一次大型聚会中完成三分钟团队更新",
        )

    def test_mixed_deconstruct_cannot_force_large_gatherings_to_correct_the_preference(self) -> None:
        self.assert_compile_rejects_preference_correction(
            name="coercive-action",
            primary_variable="准备时间",
            action="参加一次大型聚会，并在那里完成三分钟团队更新",
        )


class MissingLockStateContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v66-missing-lock-")
        self.root = Path(self.temporary.name)
        self.source = self.root / "source"
        result = run_cli(
            "init",
            "--text",
            "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。",
            "--case-dir",
            str(self.source),
            "--case-id",
            "v66-valid-source",
            "--clock",
            CLOCK,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertTrue((self.source / LOCK_FILE).is_file())
        replay = run_cli("replay", "--case-dir", str(self.source))
        self.assertEqual(0, replay.returncode, replay.stdout + replay.stderr)
        self.assertTrue(payload(replay)["valid"])

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def clone_state_without_lock(self, name: str) -> Path:
        clone = self.root / name
        clone.mkdir()
        for state_file in STATE_FILES:
            (clone / state_file).write_bytes((self.source / state_file).read_bytes())
        self.assertFalse((clone / LOCK_FILE).exists())
        return clone

    def command_args(self, command: str, case_dir: Path) -> tuple[str, ...]:
        args = [command, "--case-dir", str(case_dir)]
        if command == "next":
            args.extend(["--clock", PLAN_CLOCK])
        return tuple(args)

    def test_missing_lock_is_never_created_or_repaired_by_case_commands(self) -> None:
        for command in ("doctor", "status", "replay", "next", "recover"):
            with self.subTest(command=command):
                case_dir = self.clone_state_without_lock(command)
                before = tree_snapshot(case_dir)
                first = run_cli(*self.command_args(command, case_dir))
                middle = tree_snapshot(case_dir)
                second = run_cli(*self.command_args(command, case_dir))
                after = tree_snapshot(case_dir)

                self.assertNotEqual(0, first.returncode, first.stdout + first.stderr)
                self.assertNotEqual(0, second.returncode, second.stdout + second.stderr)
                self.assertEqual(first.stdout, second.stdout, "failure output must be stable")
                self.assertEqual(before, middle, f"{command} must not mutate a missing-lock case")
                self.assertEqual(before, after, f"{command} must remain read-only on retry")
                self.assertFalse((case_dir / LOCK_FILE).exists())
                report = payload(first)
                self.assertFalse(report.get("valid", False))
                self.assertIn("case_lock_missing", {item["code"] for item in report["errors"]})
                if command == "recover":
                    self.assertIs(report.get("valid"), False)
                    self.assertFalse(report.get("recovered", False))


if __name__ == "__main__":
    unittest.main()
