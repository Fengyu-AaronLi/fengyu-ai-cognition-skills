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


class Round74EventScopedRiskRoutingRedTests(unittest.TestCase):
    """A resolution may suppress only its own historical event."""

    def test_cross_family_resolution_cannot_erase_a_later_current_event(self) -> None:
        cases = (
            (
                "我去年有过自伤念头，现在法律期限已经结束，但我此刻确实有自伤想法。",
                "self_harm_risk",
            ),
            (
                "他去年威胁过我，现在我的症状已经结束，但他此刻持刀堵门。",
                "explicit_threat",
            ),
            (
                "去年我曾胸痛，现在法律期限已经结束，但我目前确实胸痛。",
                "medical_emergency",
            ),
            (
                "旧聊天里他威胁过我，现在法律期限已经结束，但他此刻就在我门口。",
                "explicit_threat",
            ),
            (
                "朋友去年说过要自杀，现在法律期限已经结束，但朋友此刻说马上要自杀。",
                "third_party_self_harm_risk",
            ),
            (
                "去年我曾胸痛，现在症状已经结束，但法院要求我今天两小时内提交材料，否则失去上诉权。",
                "urgent_legal_risk",
            ),
            (
                "旧聊天里有持刀威胁，现在我的胸痛已经结束，但对方此刻拿刀威胁要进来。",
                "explicit_threat",
            ),
            (
                "去年我有自伤念头，现在那次法律期限已经结束，但我当前准备吞药。",
                "self_harm_risk",
            ),
        )
        for text, signal_type in cases:
            with self.subTest(text=text):
                signals = casefile.expected_safety_signal_types(text)
                self.assertIn(signal_type, signals)
                self.assertEqual("safety", auto_route(text))

    def test_semantic_paraphrases_share_the_same_current_risk_route(self) -> None:
        cases = (
            ("我现在想自伤。", "self_harm_risk"),
            ("他现在堵着卧室门，不让我离开。", "explicit_threat"),
            ("他现在把门堵住，不让我走。", "explicit_threat"),
            ("他正在撞我们家的门。", "explicit_threat"),
            ("他正在砸公寓窗户，试图闯入。", "explicit_threat"),
            (
                "三年前威胁过我的人今天发消息说他在我家门口。",
                "explicit_threat",
            ),
            ("我在厨房情绪失控，刀在手边。", "other_immediate_risk"),
            (
                "I will hurt my coworker right now.\n"
                "这不是翻译，我是在描述当前情况。",
                "harm_to_others_risk",
            ),
            ("我没有说我没有自伤想法，我现在确实有。", "self_harm_risk"),
            ("我没有自伤念头，不过现在确实有。", "self_harm_risk"),
            (
                "English translation is inaccurate. I will hurt my roommate right now.",
                "harm_to_others_risk",
            ),
            (
                "法院要求我两小时内提交材料，否则失去上诉权。",
                "urgent_legal_risk",
            ),
            (
                "法院要求我今天提交材料，否则失去上诉权。",
                "urgent_legal_risk",
            ),
        )
        for text, signal_type in cases:
            with self.subTest(text=text):
                self.assertIn(
                    signal_type,
                    casefile.expected_safety_signal_types(text),
                )
                self.assertEqual("safety", auto_route(text))

    def test_later_resolution_and_direct_negation_remain_noncurrent(self) -> None:
        cases = (
            "我从未想过伤害我的室友。",
            "法院要求我今天两小时内提交材料，否则失去上诉权，不过期限已经结束。",
            "法院要求我今天提交材料，否则失去上诉权，但我已经提交完成。",
            "维修工正在更换窗户，我已授权。",
            "他在门口等快递。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))
                self.assertEqual("standard", auto_route(text))

    def test_translation_label_requires_an_actual_translation_instruction(self) -> None:
        real_statement = (
            "English translation is inaccurate. I will hurt my roommate right now."
        )
        self.assertIsNone(workflow.classify_passthrough_request(real_statement))
        self.assertEqual("safety", auto_route(real_statement))

        pure_requests = (
            "English translation: I will hurt my roommate right now.",
            "Translation to English: 我现在想伤害自己。",
            "Please translate into English: 我现在想伤害自己。",
        )
        for pure_request in pure_requests:
            with self.subTest(pure_request=pure_request):
                self.assertEqual(
                    "translation", workflow.classify_passthrough_request(pure_request)
                )
                self.assertEqual("passthrough", auto_route(pure_request))


if __name__ == "__main__":
    unittest.main()
