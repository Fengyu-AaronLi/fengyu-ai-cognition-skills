from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import workflow  # noqa: E402


class Round119NegatedAnalysisRoutingRedTests(unittest.TestCase):
    """A prohibition on analysis is not itself an analysis request."""

    def test_negated_analysis_directives_preserve_formatting_passthrough(self) -> None:
        cases = (
            "请把事件按时间升序整理成 JSON 数组，不分析心理或动机。来源：[T1] 她取消约会。",
            "请把事件整理成表格，不要分析关系状态。来源：[T1] 她取消约会。",
            "请把事件整理成表格，无需推断真实动机。来源：[T1] 她取消约会。",
            "请把事件整理成表格，不做判断。来源：[T1] 她取消约会。",
            "请把事件整理成表格，禁止解读心理。来源：[T1] 她取消约会。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertFalse(workflow.passthrough_has_mixed_intent(text))
                self.assertIn(
                    workflow.classify_passthrough_request(text),
                    {"formatting", "sourced_timeline"},
                )

    def test_positive_analysis_after_a_negated_clause_still_vetoes_passthrough(self) -> None:
        text = (
            "请把事件整理成表格，不分析格式以外的内容，"
            "但请判断她对我的态度。来源：[T1] 她取消约会。"
        )
        self.assertTrue(workflow.passthrough_has_mixed_intent(text))
        self.assertIsNone(workflow.classify_passthrough_request(text))

    def test_multiple_quoted_timeline_rows_are_owned_by_the_format_task(self) -> None:
        text = (
            "请只把下面三条事件按时间升序整理成 JSON 数组，保留 "
            "source_ref 和 quote，不分析心理或动机。\n\n"
            "[T3] 2026-08-05 17:20，“会议纪要已发送。”\n"
            "[T1] 2026-08-05 09:00，“会议改到周五下午三点。”\n"
            "[T2] 2026-08-05 11:30，“收到，我会参加。”"
        )
        self.assertFalse(
            workflow.passthrough_has_mixed_intent(text),
            "Quoted fields inside an explicitly sourced timeline are data "
            "cells, not unowned second tasks.",
        )
        self.assertIn(
            workflow.classify_passthrough_request(text),
            {"formatting", "sourced_timeline"},
        )


if __name__ == "__main__":
    unittest.main()
