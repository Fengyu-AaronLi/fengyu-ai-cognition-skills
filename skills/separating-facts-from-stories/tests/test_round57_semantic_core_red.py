from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
from test_round19_semantic_lifecycle_red import (  # noqa: E402
    _append_story,
    _standard_shell,
)
from test_round37_semantic_truthfulness_red import (  # noqa: E402
    _explicit_feeling_case,
)
from test_round39_semantic_scope_red import add_retraction_transition  # noqa: E402


def span_texts(text: str) -> list[str]:
    return [item["text"] for item in casefile.generate_source_spans("I1", text)]


class Round57SemanticCoreRedTests(unittest.TestCase):
    """RED regressions for clause scope, feeling layers, and retraction-only updates."""

    def test_reply_question_is_not_split_or_upgraded_to_a_positive_fact(self) -> None:
        question = "他回复了我没有？"
        spans = casefile.generate_source_spans("I1", question)

        self.assertEqual([question], [item["text"] for item in spans])
        self.assertIsNone(casefile.derive_observation_type(question, spans[0]))
        self.assertEqual(
            [],
            casefile.make_draft(
                question, "round57-reply-question", "standard"
            )["unclassified_observation_candidates"],
        )

        statement = "他回复了我。"
        statement_span = casefile.generate_source_spans("I1", statement)[0]
        self.assertEqual(
            "communication_event",
            casefile.derive_observation_type(statement, statement_span),
        )

    def test_nested_reply_object_remains_one_fail_closed_proposition(self) -> None:
        nested = "他回复了我没有回复的消息。"
        spans = casefile.generate_source_spans("I1", nested)

        self.assertEqual([nested], [item["text"] for item in spans])
        self.assertIsNone(casefile.derive_observation_type(nested, spans[0]))
        candidates = casefile.make_draft(
            nested, "round57-nested-reply-object", "standard"
        )["unclassified_observation_candidates"]
        self.assertEqual([nested], [item["exact_quote"] for item in candidates])

        ordinary = "他回复了消息。"
        ordinary_span = casefile.generate_source_spans("I1", ordinary)[0]
        self.assertEqual(
            "communication_event",
            casefile.derive_observation_type(ordinary, ordinary_span),
        )

    def test_feeling_with_judgment_verb_has_exactly_one_epistemic_layer(self) -> None:
        text = "我觉得很难过。"
        span = casefile.generate_source_spans("I1", text)[0]

        self.assertTrue(casefile.is_explicit_feeling(text))
        self.assertIsNone(casefile.derive_claim_kind_for_span(text, span, text))

        draft = _explicit_feeling_case(text, "round57-feeling-only")
        self.assertEqual([], casefile.validate_casefile(draft))
        self.assertEqual(["explicit_feeling"], [item["kind"] for item in draft["claims"]])
        self.assertEqual(["C1"], draft["evidence"][0]["can_establish"])
        self.assertEqual([], draft["evidence"][0]["cannot_establish"])

        interpretation = "我觉得老板在架空我。"
        interpretation_span = casefile.generate_source_spans("I1", interpretation)[0]
        self.assertEqual(
            "interpretation",
            casefile.derive_claim_kind_for_span(
                interpretation,
                interpretation_span,
                interpretation,
            ),
        )

    def test_explicit_retraction_can_be_the_only_current_transition(self) -> None:
        first = _standard_shell(
            "我认为老板在架空我。", "round57-retraction-only"
        )
        _append_story(first, "我认为老板在架空我。", "interpretation")
        self.assertEqual([], casefile.validate_casefile(first))

        second = casefile.start_update(
            first, "我不再认为老板在架空我了。"
        )
        add_retraction_transition(second)

        self.assertEqual([], casefile.validate_casefile(second, previous=first))
        current_input_id = second["current_input_id"]
        self.assertFalse(
            any(
                item["input_id"] == current_input_id
                for item in second["claims"]
            ),
            "a retraction changes the prior claim; it must not invent a new current claim",
        )
        self.assertEqual("retracted", second["claims"][0]["epistemic_status"])

    def test_connector_matching_respects_word_boundaries(self) -> None:
        for text in (
            "我不这么认为了。",
            "我暂时不这么认为了。",
            "我已经认为了很久。",
        ):
            with self.subTest(text=text):
                self.assertEqual([text], span_texts(text))

        motive_clause = "他回复了我为了确认情况。"
        self.assertEqual(
            ["他回复了我", "为了确认情况。"],
            span_texts(motive_clause),
        )


if __name__ == "__main__":
    unittest.main()
