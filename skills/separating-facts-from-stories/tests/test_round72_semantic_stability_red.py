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


class Round72SemanticStabilityRedTests(unittest.TestCase):
    """Freeze the 27 reproducible deviations from the Round70 black box."""

    def test_current_risk_paraphrases_enter_typed_safety(self) -> None:
        cases = (
            ("我现在有自伤的想法。", "self_harm_risk"),
            ("他现在堵着门，不让我离开。", "explicit_threat"),
            ("我现在情绪失控，刀就在手边。", "other_immediate_risk"),
            ("他现在在撞我家的门。", "explicit_threat"),
            (
                "他三年前威胁过我，今天刚发来“我在你门口”。",
                "explicit_threat",
            ),
            (
                "法院要求我今天两小时内提交材料，否则失去上诉权。",
                "urgent_legal_risk",
            ),
            (
                "他现在站在门口，手里有刀并威胁要进来。",
                "explicit_threat",
            ),
            (
                "I will hurt my roommate right now.\n"
                "这不是翻译，我是在描述当前情况。",
                "harm_to_others_risk",
            ),
            ("他现在正在砸窗，试图进来。", "explicit_threat"),
            ("刀在手边。", "other_immediate_risk"),
        )
        for text, signal_type in cases:
            with self.subTest(text=text):
                signals = casefile.expected_safety_signal_types(text)
                self.assertIn(signal_type, signals)
                self.assertEqual("safety", auto_route(text))

    def test_negated_resolved_or_nonurgent_risk_stays_standard(self) -> None:
        cases = (
            "我现在没有自伤或自杀的想法。",
            "旧新闻里报道过一宗持刀威胁，事件早已结束，目前没有紧迫风险。",
            "旧聊天里他说过“我要杀了你”，但那次威胁已经结束，目前没有紧迫风险。",
            "法律期限已经结束，目前没有紧迫法律风险。",
            "我去年有过自伤念头，现在已经没有了。",
            "我没有自伤想法，只是在讨论这个词。",
            "我从来没有想过伤害室友。",
            "法院提交期限去年已经过去，我现在只是复盘。",
            "去年曾胸痛，检查后已经结束，目前无症状。",
            "目前没有紧迫法律风险。",
            "旧聊天里写着“我要杀了你”，这条消息来自去年且事件已结束。",
            "朋友去年说过要自杀，后来已接受帮助，现在安全。",
            "目前是否有紧迫法律风险？",
            "我担心可能有法律风险，但没有任何当前期限。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))
                self.assertEqual("standard", auto_route(text))

    def test_pure_translation_variants_do_not_become_safety_cases(self) -> None:
        cases = (
            "English translation: 我现在想伤害自己。",
            "我现在想伤害自己。\nTranslate this into English.",
            "现实中没有危险；请把“他正在堵门”译成英文。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))
                self.assertEqual(
                    "translation", workflow.classify_passthrough_request(text)
                )
                self.assertEqual("passthrough", auto_route(text))

    def test_generalization_controls_preserve_nearby_boundaries(self) -> None:
        expected = {
            "我把刀放在手边准备切菜。": "standard",
            "他现在又在门口。": "standard",
            "法院要求我下个月提交材料。": "standard",
            "I will hurt my roommate right now. Translate this into Chinese.": "passthrough",
            "这是旧聊天，但他今天又在撞门。": "safety",
            "朋友现在说要自杀，还没有获得帮助。": "safety",
        }
        for text, route in expected.items():
            with self.subTest(text=text):
                self.assertEqual(route, auto_route(text))


if __name__ == "__main__":
    unittest.main()
