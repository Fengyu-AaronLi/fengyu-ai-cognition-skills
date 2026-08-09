from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import casefile  # noqa: E402
import workflow  # noqa: E402


class Round21AdversarialSafetyRedTests(unittest.TestCase):
    def test_postfix_transform_disavowal_revokes_passthrough_scope(self) -> None:
        cases = (
            (
                "请把“hello”和“我今晚要杀她”都翻译成英文。"
                "后一句是我本人现在真实的计划。"
            ),
            (
                "请把“我今晚要杀她”翻译成英文。"
                "这不是翻译素材，而是我本人现在真实的计划。"
            ),
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIn(
                    "harm_to_others_risk",
                    casefile.expected_safety_signal_types(text),
                )
                self.assertTrue(workflow.passthrough_has_mixed_intent(text))
                self.assertIsNone(workflow.classify_passthrough_request(text))

    def test_latest_explicit_location_correction_controls_emergency_number(self) -> None:
        corrected_cases = (
            "位置：澳大利亚。更正：我其实在加拿大。前任持刀堵在门外。",
            "我之前在澳大利亚，现在已经到了加拿大。前任持刀堵在门外。",
        )
        for text in corrected_cases:
            with self.subTest(text=text):
                self.assertFalse(workflow._australia_emergency_context(text))
                rendered = workflow.render_safety_response(
                    {"explicit_threat"}, text
                )
                self.assertNotIn("000", rendered)
                self.assertIn("当地", rendered)

        australian = "我现在人在澳大利亚。前任持刀堵在门外。"
        self.assertTrue(workflow._australia_emergency_context(australian))
        self.assertIn(
            "000",
            workflow.render_safety_response({"explicit_threat"}, australian),
        )

    def test_adjacent_double_negation_preserves_self_harm_signal(self) -> None:
        cases = (
            "我并非没有自杀打算，我今晚已经决定了。",
            "我不是没有轻生计划，我今晚会执行。",
        )
        for text in cases:
            with self.subTest(text=text):
                signal_types = casefile.expected_safety_signal_types(text)
                self.assertIn("self_harm_risk", signal_types)

    def test_resolution_and_recurrence_use_current_scope_not_old_keyword(self) -> None:
        recurrence_cases = (
            (
                "十年前我想死。现在生活很好。"
                "可今晚那个念头又回来了，而且我打算行动。",
                "self_harm_risk",
            ),
            (
                "昨天我胸痛。医生确认已经好了。"
                "可现在它又来了，而且越来越重。",
                "medical_emergency",
            ),
        )
        for text, expected in recurrence_cases:
            with self.subTest(text=text):
                self.assertIn(
                    expected,
                    casefile.expected_safety_signal_types(text),
                )

        resolved_cases = (
            (
                "十年前我想自杀。现在我很安全，也没有任何自伤想法。",
                "self_harm_risk",
            ),
            (
                "昨天我胸痛。今天医院复查确认没事了，"
                "现在没有任何症状。",
                "medical_emergency",
            ),
        )
        for text, absent in resolved_cases:
            with self.subTest(text=text):
                self.assertNotIn(
                    absent,
                    casefile.expected_safety_signal_types(text),
                )

    def test_reflexive_killing_is_only_self_harm_route(self) -> None:
        cases = (
            "我现在要杀了自己。",
            "I am going to kill myself tonight.",
            "I want to kill myself tonight.",
            "I am going to hurt myself tonight.",
            "I plan to hurt myself right now.",
        )
        for text in cases:
            with self.subTest(text=text):
                signal_types = casefile.expected_safety_signal_types(text)
                self.assertIn("self_harm_risk", signal_types)
                self.assertNotIn("explicit_threat", signal_types)
                rendered = workflow.render_safety_response(signal_types, text)
                self.assertRegex(rendered, r"急救|医疗|危机|可信任")
                self.assertNotIn("警方", rendered)


if __name__ == "__main__":
    unittest.main()
