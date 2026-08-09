from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round99StoryPolarityAndPredictionRedTests(unittest.TestCase):
    """RED regressions found by independent post-Round98 black-box review."""

    def test_negated_first_person_story_attribution_is_not_reversed(self) -> None:
        for text in (
            "我不认为他不爱我。",
            "我不觉得他不爱我。",
            "我不是说他不爱我。",
            "我并不认为他不爱我。",
        ):
            with self.subTest(text=text):
                spans = casefile.generate_source_spans("I1", text)
                self.assertEqual([text], [item["text"] for item in spans])
                self.assertIsNone(
                    casefile.derive_claim_kind_for_span(text, spans[0], text)
                )
                missing = {
                    item["code"]
                    for item in casefile.validate_casefile(
                        casefile.make_draft(text, "round99-disavowal", "standard")
                    )
                }
                self.assertNotIn("USER_STORY_CLAIM_MISSING", missing)

    def test_explicit_third_party_departure_forecast_is_prediction(self) -> None:
        for text in (
            "他肯定会离开我。",
            "他会离开我。",
            "他准备离开我。",
            "她打算离开。",
            "对方计划回来。",
        ):
            with self.subTest(text=text):
                spans = casefile.generate_source_spans("I1", text)
                self.assertEqual([text], [item["text"] for item in spans])
                self.assertEqual(
                    "prediction",
                    casefile.derive_claim_kind_for_span(text, spans[0], text),
                )
                missing = {
                    item["code"]
                    for item in casefile.validate_casefile(
                        casefile.make_draft(text, "round99-prediction", "standard")
                    )
                }
                self.assertIn("USER_STORY_CLAIM_MISSING", missing)

    def test_first_person_plan_is_not_relabelled_as_prediction(self) -> None:
        for text in ("我会离开。", "我准备离开。", "我计划回来。"):
            with self.subTest(text=text):
                spans = casefile.generate_source_spans("I1", text)
                self.assertEqual([text], [item["text"] for item in spans])
                self.assertIsNone(
                    casefile.derive_claim_kind_for_span(text, spans[0], text)
                )


if __name__ == "__main__":
    unittest.main()
