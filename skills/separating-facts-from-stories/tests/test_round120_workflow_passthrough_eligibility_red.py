from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
WORKFLOW = SKILL_DIR / "scripts" / "workflow.py"
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import workflow  # noqa: E402


TIMELINE_ROWS = (
    "\n[T1] 2026-08-01，甲称已提交申请。"
    "\n[T2] 2026-08-03，乙称从未收到。"
)


class Round120WorkflowPassthroughEligibilityRedTests(unittest.TestCase):
    """Sourced timelines may bypass the Skill only when no analysis remains."""

    def run_workflow(self, *args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(WORKFLOW), *map(str, args)],
            cwd=SKILL_DIR,
            text=True,
            capture_output=True,
            check=False,
        )

    def start(self, root: Path, text: str, mode: str = "auto"):
        input_path = root / "input.txt"
        input_path.write_text(text, encoding="utf-8")
        workspace = root / "session"
        result = self.run_workflow(
            "start",
            "--input",
            input_path,
            "--workspace",
            workspace,
            "--case-id",
            "round120-passthrough-eligibility",
            "--mode",
            mode,
        )
        return result, workspace

    def test_pure_sourced_timeline_remains_passthrough(self) -> None:
        text = (
            "请把以下已明确标注来源的事实整理成时间线，不要分析："
            + TIMELINE_ROWS
        )
        self.assertEqual("sourced_timeline", workflow.classify_passthrough_request(text))

    def test_explicitly_negated_conclusion_remains_pure_passthrough(self) -> None:
        text = (
            "请把以下已明确标注来源的事实整理成时间线，"
            "不要给出结论，不要比较可信度："
            + TIMELINE_ROWS
        )
        self.assertEqual(
            "sourced_timeline", workflow.classify_passthrough_request(text)
        )

    def test_sourced_timeline_with_followup_analysis_is_not_passthrough_eligible(
        self,
    ) -> None:
        followups = (
            "并给出结论",
            "并总结其中的规律",
            "并找出双方说法的矛盾",
            "并比较双方说法谁更可信",
            "并据此给我一个行动方案",
        )
        for followup in followups:
            text = (
                "请把以下已明确标注来源的事实整理成时间线，"
                f"{followup}：{TIMELINE_ROWS}"
            )
            with self.subTest(followup=followup):
                self.assertIsNone(workflow.classify_passthrough_request(text))

    def test_auto_routes_timeline_plus_conclusion_through_standard_skill(self) -> None:
        text = (
            "请把以下已明确标注来源的事实整理成时间线，并给出结论："
            + TIMELINE_ROWS
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result, workspace = self.start(Path(temp_dir), text)

            self.assertEqual(0, result.returncode, result.stderr)
            state = json.loads(result.stdout)
            self.assertEqual("standard", state["mode"])
            self.assertEqual("awaiting_authoring", state["phase"])
            self.assertTrue((workspace / "casefile.json").is_file())

    def test_explicit_passthrough_rejects_timeline_plus_source_credibility(self) -> None:
        text = (
            "请把以下已明确标注来源的事实整理成时间线，"
            "并比较双方说法谁更可信："
            + TIMELINE_ROWS
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result, workspace = self.start(Path(temp_dir), text, "passthrough")

            self.assertNotEqual(0, result.returncode)
            self.assertIn("PASSTHROUGH_MIXED_INTENT", result.stderr)
            self.assertFalse(workspace.exists())

    def test_safety_signal_still_overrides_sourced_timeline_passthrough(self) -> None:
        text = (
            "请把以下已明确标注来源的事实整理成时间线："
            "\n[T1] 2026-08-01，我提交了申请。"
            "\n[T2] 现实中我刚吞下一整瓶药。"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result, _ = self.start(Path(temp_dir), text)

            self.assertEqual(0, result.returncode, result.stderr)
            state = json.loads(result.stdout)
            self.assertEqual("safety", state["mode"])
            self.assertEqual("safety_action_required", state["phase"])


if __name__ == "__main__":
    unittest.main()
