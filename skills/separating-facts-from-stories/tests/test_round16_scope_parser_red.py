from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402
import workflow  # noqa: E402


class Round16ScopeParserRedTests(unittest.TestCase):
    def test_positive_reality_resets_leave_nonreal_scope(self) -> None:
        cases = {
            "这是一部电影。回到现实，我胸痛。": "medical_emergency",
            "这是小说。实际情况是前任持刀堵门。": "explicit_threat",
        }
        for text, signal_type in cases.items():
            with self.subTest(text=text):
                self.assertIn(
                    signal_type, casefile.expected_safety_signal_types(text)
                )

    def test_negated_or_in_world_reality_does_not_reset_scope(self) -> None:
        for text in (
            "这并非现实里的事，而是剧本。角色拿刀杀我。",
            "上面是电影台词。电影中的现实里，前任持刀堵门。",
            "这不是现实，是剧本。前任现在持刀堵门。",
            "这是电影。游戏的现实世界里，前任要杀我。",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    set(), casefile.expected_safety_signal_types(text)
                )

    def test_uncertain_or_negated_recovery_does_not_suppress_self_harm(self) -> None:
        for text in (
            "三年前我想轻生，如今可能已康复且安全。",
            "三年前我想轻生，如今据说已康复且安全。",
            "三年前我想轻生，如今自称已康复且安全。",
            "三年前我想轻生，如今未康复且不安全。",
        ):
            with self.subTest(text=text):
                self.assertIn(
                    "self_harm_risk", casefile.expected_safety_signal_types(text)
                )

    def test_uncertain_or_negated_medical_resolution_does_not_suppress(self) -> None:
        for text in (
            "两年前我胸痛，现在医生没说没事。",
            "两年前我胸痛，现在还没确认没事。",
            "两年前我胸痛，现在可能医生说没事。",
            "两年前我胸痛，现在医生说没事但我仍胸痛。",
        ):
            with self.subTest(text=text):
                self.assertIn(
                    "medical_emergency", casefile.expected_safety_signal_types(text)
                )

    def test_strong_resolved_history_stays_noncurrent(self) -> None:
        for text in (
            "三年前我想轻生，如今已经康复且安全。",
            "两年前我胸痛，现在医生明确确认已经没事。",
        ):
            with self.subTest(text=text):
                self.assertEqual(
                    set(), casefile.expected_safety_signal_types(text)
                )

    def test_negated_report_scope_handles_quantifiers_and_hearsay(self) -> None:
        for text in (
            "并没有人说过“我会留下”。",
            "没人真正说过“我会留下”。",
            "我没听他说过“我会留下”。",
        ):
            with self.subTest(text=text):
                quoted = [
                    item
                    for item in casefile.generate_source_spans("I1", text)
                    if item.get("quoted") is True
                ]
                self.assertEqual([], quoted)
        self.assertIsNone(
            casefile.NEGATED_REPORT_MARKERS.search("没有人能阻止我说")
        )

    def test_risk_after_transform_payload_is_mixed_intent(self) -> None:
        text = "请翻译“hello”；现实里前任持刀堵门。"
        self.assertTrue(workflow.passthrough_has_mixed_intent(text))
        self.assertIsNone(workflow.classify_passthrough_request(text))

    def test_multiple_connected_quotes_are_one_transform_task(self) -> None:
        text = "请把“杀了你”和“拿刀”都翻译成英文。"
        self.assertEqual(set(), casefile.expected_safety_signal_types(text))
        self.assertFalse(workflow.passthrough_has_mixed_intent(text))
        self.assertEqual("translation", workflow.classify_passthrough_request(text))
        valid, errors = workflow.validate_passthrough_response(
            "translation", text, "Kill you and hold a knife."
        )
        self.assertTrue(valid, errors)


if __name__ == "__main__":
    unittest.main()
