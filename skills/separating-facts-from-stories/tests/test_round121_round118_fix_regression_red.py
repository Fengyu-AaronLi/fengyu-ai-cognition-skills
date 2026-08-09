from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
CASEFILE_PATH = SKILL_DIR / "scripts" / "casefile.py"
SPEC = importlib.util.spec_from_file_location("round121_casefile", CASEFILE_PATH)
assert SPEC is not None and SPEC.loader is not None
CASEFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CASEFILE)


class Round121Round118FixRegressionRedTests(unittest.TestCase):
    def test_only_quantifier_without_cai_does_not_hide_real_observation(self):
        cases = (
            "只有一个事实，我看见他回复了消息。",
            "只有老板在场，我看见他回复了消息。",
        )
        for text in cases:
            with self.subTest(text=text):
                artifact = CASEFILE.make_draft(text, "ROUND121-ONLY", "standard")
                observation_span = next(
                    span
                    for span in artifact["source_spans"]
                    if span["text"] == "我看见他回复了消息。"
                )
                internal_tokens = {
                    part.strip()
                    for part in observation_span["source_label"].split("｜")
                }
                pending_span_ids = {
                    item["source_span_id"]
                    for item in artifact["unclassified_observation_candidates"]
                }

                self.assertNotIn("inferred_nonasserted_context", internal_tokens)
                self.assertIn(observation_span["id"], pending_span_ids)

    def test_recipient_slot_cannot_swallow_a_nested_reporting_clause(self):
        text = "我对老板说他说：“我决定离开。”"
        quote_span = next(
            span
            for span in CASEFILE.generate_source_spans("I1", text)
            if span["quoted"] is True
        )

        self.assertNotEqual(
            "user",
            CASEFILE._quoted_speaker_role(
                text, quote_span["start"], quote_span["end"]
            ),
        )

    def test_contrastive_only_if_quote_remains_nonasserted(self):
        for text in (
            "但只有老板说：“我决定离开”，我才辞职。",
            "不过只有老板说：“我决定离开”，我才辞职。",
        ):
            with self.subTest(text=text):
                quote_span = next(
                    span
                    for span in CASEFILE.generate_source_spans("I1", text)
                    if span["quoted"] is True
                )
                self.assertNotEqual(
                    "stated_position",
                    CASEFILE.derive_claim_kind_for_span(
                        quote_span["text"], quote_span, text
                    ),
                )

    def test_meta_negation_does_not_swallow_later_affirmative_story(self):
        cases = (
            "这不等于他故意排挤我但我认为他确实在排挤我。",
            "这不等于他故意排挤我，但我认为他确实在排挤我。",
        )
        for text in cases:
            with self.subTest(text=text):
                spans = CASEFILE.generate_source_spans("I1", text)
                classified = [
                    (span["text"], CASEFILE.derive_claim_kind_for_span(
                        span["text"], span, text
                    ))
                    for span in spans
                ]
                asserted = [item for item in classified if item[1] is not None]

                self.assertEqual(1, len(asserted), classified)
                self.assertIn("我认为他确实在排挤我", asserted[0][0])
                self.assertIn(
                    asserted[0][1], {"interpretation", "motive_inference"}
                )


if __name__ == "__main__":
    unittest.main()
