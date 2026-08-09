#!/usr/bin/env python3
"""V58 contracts: untrusted prose never needs shell interpolation or overwrite redirection."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
ANALYSIS = ROOT / "tests" / "fixtures" / "analysis-c01.json"
VALID_CASE = ROOT / "tests" / "fixtures" / "valid-c01.json"
CLOCK = "2026-08-06T00:00:00Z"
TEXT = "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。"
SHELL_TEXT = "我是 I 人'; printf __SHELL_INJECTION_REACHED__; # 所以我不行 $(touch marker)"


def run_cli(*args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        input=stdin,
        capture_output=True,
        check=False,
    )


class SafeTextIngressTests(unittest.TestCase):
    def test_scaffold_reads_literal_text_from_file_and_creates_output_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v58-scaffold-") as temp:
            base = Path(temp)
            source = base / "user-input.txt"
            output = base / "scaffold.json"
            marker = base / "marker"
            source.write_text(SHELL_TEXT, encoding="utf-8")

            first = run_cli(
                "scaffold",
                "--text-file",
                str(source),
                "--out",
                str(output),
                "--clock",
                CLOCK,
            )
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            case = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(SHELL_TEXT, case["evidence"][0]["text"])
            self.assertFalse(marker.exists())

            sentinel = output.read_bytes()
            second = run_cli(
                "scaffold",
                "--text-file",
                str(source),
                "--out",
                str(output),
                "--clock",
                CLOCK,
            )
            self.assertNotEqual(0, second.returncode)
            self.assertIn("output_exists", second.stdout + second.stderr)
            self.assertEqual(sentinel, output.read_bytes())

    def test_scaffold_can_read_stdin_without_a_shell_command_string(self) -> None:
        result = run_cli("scaffold", "--stdin", "--clock", CLOCK, stdin=SHELL_TEXT)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(SHELL_TEXT, json.loads(result.stdout)["evidence"][0]["text"])

    def test_render_refuses_to_overwrite_an_existing_report(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v58-render-") as temp:
            report = Path(temp) / "report.md"
            report.write_text("preserve\n", encoding="utf-8")
            result = run_cli("render", str(VALID_CASE), "--out", str(report))
            self.assertNotEqual(0, result.returncode)
            self.assertIn("output_exists", result.stdout + result.stderr)
            self.assertEqual("preserve\n", report.read_text(encoding="utf-8"))

    def test_persistent_free_text_uses_files_for_init_record_and_review(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v58-lifecycle-") as temp:
            base = Path(temp)
            case_dir = base / "case"
            input_file = base / "user-input.txt"
            input_file.write_text(TEXT, encoding="utf-8")
            initialized = run_cli(
                "init",
                "--text-file",
                str(input_file),
                "--case-dir",
                str(case_dir),
                "--clock",
                CLOCK,
            )
            self.assertEqual(0, initialized.returncode, initialized.stdout + initialized.stderr)
            planned = run_cli(
                "plan",
                "--case-dir",
                str(case_dir),
                "--analysis",
                str(ANALYSIS),
                "--clock",
                "2026-08-06T00:01:00Z",
            )
            self.assertEqual(0, planned.returncode, planned.stdout + planned.stderr)
            confirmation_file = base / "user-confirmation.txt"
            confirmation_file.write_text(
                "我愿意开始这个现实实验。", encoding="utf-8"
            )
            started = run_cli(
                "start",
                "--case-dir",
                str(case_dir),
                "--confirmation-file",
                str(confirmation_file),
                "--clock",
                "2026-08-06T00:02:00Z",
            )
            self.assertEqual(0, started.returncode, started.stdout + started.stderr)

            observation_file = base / "observation.json"
            observation = {
                "source_text": "完成了三分钟团队更新'; printf __RECORD_INJECTION__; #",
                "fact": "完成了三分钟团队更新",
                "context": "团队周会 $(touch marker)",
                "timeframe": "今天",
            }
            observation_file.write_text(
                json.dumps(observation, ensure_ascii=False), encoding="utf-8"
            )
            recorded = run_cli(
                "record",
                "--case-dir",
                str(case_dir),
                "--kind",
                "experiment_result",
                "--observation-file",
                str(observation_file),
                "--operation-id",
                "v58-safe-record",
                "--clock",
                "2026-08-06T00:03:00Z",
            )
            self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
            self.assertFalse((base / "marker").exists())

            rationale_file = base / "rationale.txt"
            rationale_file.write_text(
                "一次结果只复核预登记窄命题，不能定义人格。 $(touch marker)",
                encoding="utf-8",
            )
            reviewed = run_cli(
                "review",
                "--case-dir",
                str(case_dir),
                "--classification",
                "inconclusive",
                "--rationale-file",
                str(rationale_file),
                "--clock",
                "2026-08-14T00:04:00Z",
            )
            self.assertEqual(0, reviewed.returncode, reviewed.stdout + reviewed.stderr)
            self.assertFalse((base / "marker").exists())

    def test_operator_docs_do_not_interpolate_user_prose_into_shell_argv(self) -> None:
        for relative in ("SKILL.md", "README.md", "docs/quickstart.md"):
            text = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("--text-file", text, relative)
            self.assertNotIn("--text '<", text, relative)
            self.assertNotIn("> ./scaffold.json", text, relative)
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("--observation-file", skill)
        self.assertIn("--rationale-file", skill)
        self.assertNotIn("--source-text '<", skill)
        self.assertNotIn("--rationale '<", skill)


if __name__ == "__main__":
    unittest.main()
