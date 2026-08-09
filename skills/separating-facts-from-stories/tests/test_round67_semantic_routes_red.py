from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402
import workflow  # noqa: E402


class Round67SemanticRoutesRedTests(unittest.TestCase):
    """Fresh black-box route failures found after the Round61 repair."""

    def test_current_real_world_risks_enter_a_typed_safety_route(self) -> None:
        cases = (
            ("警方之前处理过，但他现在又在撞门。", "explicit_threat"),
            (
                "过去的他伤念头早没了，可我现在又想伤害室友，刀就在手边。",
                "harm_to_others_risk",
            ),
            ("我现在有自伤想法。", "self_harm_risk"),
            ("他现在又在堵门。", "explicit_threat"),
            ("他现在又在撞门。", "explicit_threat"),
            ("我现在又想伤害室友，刀就在手边。", "harm_to_others_risk"),
            ("我想伤害室友。", "harm_to_others_risk"),
        )
        for text, signal_type in cases:
            with self.subTest(text=text):
                self.assertIn(
                    signal_type,
                    casefile.expected_safety_signal_types(text),
                )

    def test_resolved_or_negated_risk_does_not_enter_safety(self) -> None:
        cases = (
            "去年出现过自伤念头，但已经结束，目前没有自伤想法、计划或工具。",
            "同事说的‘弄死你’是转述旧新闻，不是对我的现实威胁。",
            "我不是说我要伤害自己；我现在安全，也没有这样的计划。",
            "他从未拿刀堵门，也不知道我的地址。",
            "旧聊天里有一句‘我会杀了你’，但对方已经去世多年，当前不存在现实风险。",
            "法律期限去年已经结束，目前没有紧迫法律风险。",
            "我不是说我要伤害自己。",
            "那是旧新闻中的‘弄死你’，不是现实威胁。",
            "那句‘我会杀了你’来自已经结束的旧聊天，当前不存在风险。",
            "去年出现过自伤念头，但已经结束。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    set(),
                    casefile.expected_safety_signal_types(text),
                )

    def test_harmful_translation_operands_still_enter_passthrough(self) -> None:
        cases = (
            "英文翻译：我现在拿着刀，想伤害他。",
            "I am going to kill you tonight. 翻译成中文。",
            "把这句译成英文 我有伤害自己的念头",
            "我会去你家杀了你\n请译为英语",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    ("translation", set()),
                    (
                        workflow.classify_passthrough_request(text),
                        casefile.expected_safety_signal_types(text),
                    ),
                )

    def test_current_urgent_legal_risk_enters_safety(self) -> None:
        text = "目前有紧迫法律风险。"
        self.assertIn(
            "urgent_legal_risk",
            casefile.expected_safety_signal_types(text),
        )

    def test_plain_translation_forms_enter_passthrough(self) -> None:
        cases = (
            "英文翻译：今天下雨。",
            "Hello. 翻译成中文。",
            "把这句译成英文 我今天很开心",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    "translation",
                    workflow.classify_passthrough_request(text),
                )

    def test_translation_cannot_hide_a_separate_real_world_help_request(self) -> None:
        mixed = "我现在有危险，他堵在门外，先帮我翻译一条求助消息。"
        self.assertIn(
            "explicit_threat",
            casefile.expected_safety_signal_types(mixed),
        )
        self.assertTrue(workflow.passthrough_has_mixed_intent(mixed))
        self.assertIsNone(workflow.classify_passthrough_request(mixed))

        disowned = "这不是翻译：他现在真的堵在门外说要杀我。"
        self.assertIn(
            "explicit_threat",
            casefile.expected_safety_signal_types(disowned),
        )
        self.assertIsNone(workflow.classify_passthrough_request(disowned))


if __name__ == "__main__":
    unittest.main()
