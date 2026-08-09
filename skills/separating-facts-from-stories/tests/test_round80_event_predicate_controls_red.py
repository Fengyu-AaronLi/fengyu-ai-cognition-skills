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


class Round80EventPredicateControlsRedTests(unittest.TestCase):
    """Risk slots must share one event, polarity, and authorization scope."""

    def test_negated_current_risk_slots_remain_standard(self) -> None:
        cases = (
            "He is not pointing a gun at me right now.",
            "My partner is not strangling me now.",
            "No one is losing blood quickly right now.",
            "The bailiff says we do not have to leave in ten minutes.",
            "I can promise I won't hurt myself tonight.",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))
                self.assertEqual("standard", auto_route(text))

    def test_authorized_rescue_training_and_benign_access_remain_standard(self) -> None:
        cases = (
            "The locksmith I hired is forcing the stuck door open.",
            "The firefighter broke my window to rescue me.",
            "The courier sent a photo of my house number for the delivery I requested.",
            "My friend used the spare key I gave her to enter my apartment.",
            "The coach is demonstrating a supervised chokehold; I am safe.",
            "I planted a training prop bomb and the exercise timer is running.",
            "My brother is driving to his boss's photo shoot and took his camera.",
            "I want to die of embarrassment.",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))
                self.assertEqual("standard", auto_route(text))

    def test_meta_transform_quote_is_not_a_real_risk_event(self) -> None:
        text = "请检查这段正则是否匹配“我想死”。"
        self.assertEqual(set(), casefile.expected_safety_signal_types(text))
        self.assertEqual("standard", auto_route(text))

    def test_authorization_in_one_event_cannot_hide_a_later_real_event(self) -> None:
        cases = (
            (
                "The locksmith I hired left. My ex is forcing my door open right now.",
                "explicit_threat",
            ),
            (
                "He said he is not carrying a gun, but he is pointing a gun at me right now.",
                "explicit_threat",
            ),
        )
        for text, signal_type in cases:
            with self.subTest(text=text):
                self.assertIn(signal_type, casefile.expected_safety_signal_types(text))
                self.assertEqual("safety", auto_route(text))


if __name__ == "__main__":
    unittest.main()
