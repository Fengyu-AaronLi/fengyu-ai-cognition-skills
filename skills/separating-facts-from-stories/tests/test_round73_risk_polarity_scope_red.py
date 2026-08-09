from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round73RiskPolarityScopeRedTests(unittest.TestCase):
    """A new risk synonym must share polarity and history semantics."""

    def test_double_negated_self_harm_remains_affirmative(self) -> None:
        cases = (
            "我不是没有自伤想法，我现在确实有。",
            "我并非没有自伤念头，我现在确实有。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIn(
                    "self_harm_risk",
                    casefile.expected_safety_signal_types(text),
                )

    def test_historical_weapon_access_with_explicit_resolution_is_not_current(self) -> None:
        cases = (
            "去年情绪失控时刀在手边，现在刀已经收走且没有风险。",
            "以前刀就在手边，后来已经收走，目前没有现实危险。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))

    def test_current_weapon_recurrence_overrides_old_resolution(self) -> None:
        text = "去年情绪失控时刀在手边，后来收走了，但今天刀又在手边。"
        self.assertIn(
            "other_immediate_risk",
            casefile.expected_safety_signal_types(text),
        )


if __name__ == "__main__":
    unittest.main()
