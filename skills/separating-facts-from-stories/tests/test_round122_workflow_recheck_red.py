from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import workflow  # noqa: E402


class Round122WorkflowRecheckRedTests(unittest.TestCase):
    """Sourced-timeline passthrough requires a pure, owned timeline task."""

    def test_common_source_tagged_quote_layouts_are_eligible(self) -> None:
        cases = (
            (
                "请把以下已明确标注来源的记录整理成时间线：\n"
                "2026年8月1日 来源：邮件，原文：‘项目启动’。\n"
                "2026年8月2日 来源：短信，原文：‘会议改期’。"
            ),
            (
                "请整理成时间线：\n"
                "来源：邮件\n"
                "日期：2026年8月1日\n"
                "原文：‘项目启动’"
            ),
            "请把以下来源整理成时间线：2026年8月1日，来源：邮件，原文：‘项目启动’。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    "sourced_timeline", workflow.classify_passthrough_request(text)
                )

    def test_incidental_source_and_timeline_words_do_not_create_a_task(self) -> None:
        cases = (
            "只是说明，不是任务：来源：邮件，已有时间线。请回答合同问题。",
            "这份材料的来源：邮件，里面提到既有时间线。请回答我能否依赖该条款。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(workflow.classify_passthrough_request(text))

    def test_natural_language_analysis_before_source_colon_is_not_passthrough(self) -> None:
        cases = (
            "请分析这份来源材料，输出时间线。来源：邮件。",
            "分析这些来源并按时间线解释延期原因。来源：项目邮件。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(workflow.classify_passthrough_request(text))

    def test_negated_timeline_task_is_not_passthrough(self) -> None:
        text = "请勿根据来源：聊天记录整理时间线，只分析双方谁可信。"
        self.assertIsNone(workflow.classify_passthrough_request(text))

    def test_second_task_after_sourced_payload_blocks_passthrough(self) -> None:
        cases = (
            (
                "请按时间线整理以下来源：\n"
                "2026-08-01 邮件：项目启动。\n"
                "另外，告诉我谁应负责。"
            ),
            "请按时间线整理以下来源：2026-08-01 邮件：项目启动。之后请判断负责人。",
            "请根据来源：邮件，给我一份时间线和行动建议。",
            "请按来源整理时间线：2026-08-01 收到邮件。第二项任务是评估谁更可信。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIsNone(workflow.classify_passthrough_request(text))


if __name__ == "__main__":
    unittest.main()
