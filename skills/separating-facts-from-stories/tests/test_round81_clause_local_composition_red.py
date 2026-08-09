from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round81ClauseLocalCompositionRedTests(unittest.TestCase):
    """Risk predicates may not assemble one event from unrelated clauses."""

    def test_unrelated_slots_across_sentences_do_not_form_a_risk_event(self) -> None:
        cases = (
            "My ex is outside my door for an agreed property pickup. A kitchen knife is on the table. I told the smart speaker to kill the lights.",
            "The bailiff is at my door for a scheduled document delivery. I will leave in ten minutes for class.",
            "My brother says he is driving to his boss's house now for dinner. I will shoot a photo there, and the antique rifle remains locked at the museum.",
            "厨房有做饭产生的烟雾。幻灯片里的火焰图案正在往楼梯方向蔓延。",
            "快递员发来我家门口照片，确认包裹已经放在门口。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))

    def test_later_current_event_survives_an_earlier_benign_event(self) -> None:
        cases = (
            (
                "The locksmith opened the stuck door and left. My ex is forcing my door open right now.",
                "explicit_threat",
            ),
            (
                "The courier delivered a package earlier. A stranger is following me to my front door now.",
                "access_or_location_exposure",
            ),
        )
        for text, signal_type in cases:
            with self.subTest(text=text):
                self.assertIn(signal_type, casefile.expected_safety_signal_types(text))


if __name__ == "__main__":
    unittest.main()
