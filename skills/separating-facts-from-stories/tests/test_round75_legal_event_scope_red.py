from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402
import workflow  # noqa: E402


def auto_route(text: str) -> str:
    if casefile.expected_safety_signal_types(text):
        return "safety"
    if workflow.classify_passthrough_request(text) is not None:
        return "passthrough"
    return "standard"


class Round75LegalEventScopeRedTests(unittest.TestCase):
    """Urgency components must belong to one asserted legal event."""

    def test_same_event_imminent_material_deadlines_route_to_safety(self) -> None:
        cases = (
            "法院通知我今天是上诉最后期限。",
            "法院通知我明天是申诉最后期限。",
            "法院文件显示今天是紧迫期限。",
            "法院要求我两小时内提交材料，否则失去上诉权。",
            "法院要求我今天提交材料，否则失去上诉权。",
            "目前有紧迫法律风险。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIn(
                    "urgent_legal_risk",
                    casefile.expected_safety_signal_types(text),
                )
                self.assertEqual("safety", auto_route(text))

    def test_distant_or_resolved_deadlines_stay_out_of_safety(self) -> None:
        cases = (
            "法院通知我下个月是提交期限。",
            "法院通知我三个月后截止。",
            "法院要求我今天提交材料，否则失去上诉权，但我已经提交完成。",
            "法院要求我今天提交材料，否则失去上诉权，不过期限已经结束。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))
                self.assertEqual("standard", auto_route(text))

    def test_urgency_fragments_cannot_be_joined_across_events(self) -> None:
        cases = (
            "今天我要提交课程材料。上周参观了法院。否则我会失去上诉权这个词怎么翻译？",
            "我今天去法院参观。项目材料下个月提交。课本举例说逾期会失去上诉权。",
            "法院在新闻里出现。今天课程截止。请解释‘失去上诉权’这个词。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertNotIn(
                    "urgent_legal_risk",
                    casefile.expected_safety_signal_types(text),
                )
                self.assertNotEqual("safety", auto_route(text))

    def test_translation_operand_keeps_legal_words_inside_passthrough(self) -> None:
        text = "请翻译成英文：法院要求我今天提交材料，否则失去上诉权。"
        self.assertEqual(set(), casefile.expected_safety_signal_types(text))
        self.assertEqual("translation", workflow.classify_passthrough_request(text))
        self.assertEqual("passthrough", auto_route(text))


if __name__ == "__main__":
    unittest.main()
