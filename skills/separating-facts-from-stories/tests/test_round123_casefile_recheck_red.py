from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round123CasefileRecheckRedTests(unittest.TestCase):
    """Fresh semantic adversaries for speaker, scope, and atom ownership."""

    def test_nearest_explicit_user_speech_frame_owns_the_quote(self) -> None:
        for text in (
            "老板问我，我回答：“我会离开。”",
            "同事提醒我后，我说：“我会离开。”",
        ):
            with self.subTest(text=text):
                quote = next(
                    span
                    for span in casefile.generate_source_spans("I1", text)
                    if span["quoted"] is True
                )
                self.assertEqual(
                    "user",
                    casefile._quoted_speaker_role(
                        text, quote["start"], quote["end"]
                    ),
                )

    def test_non_user_agent_delivery_is_not_a_direct_principal_position(self) -> None:
        for text in (
            "秘书代老板对我说：“我会离开。”",
            "秘书受老板委托对我说：“我会离开。”",
        ):
            with self.subTest(text=text):
                quote = next(
                    span
                    for span in casefile.generate_source_spans("I1", text)
                    if span["quoted"] is True
                )
                self.assertIsNotNone(
                    casefile._direct_quote_scope_error(text, quote)
                )
                self.assertIsNone(
                    casefile.derive_claim_kind_for_span(
                        quote["text"], quote, text
                    )
                )

    def test_first_person_epistemic_reset_does_not_inherit_hearsay(self) -> None:
        for connector in ("而", "反而"):
            text = f"同事告诉我，他不爱我，{connector}我认为他是回避型。"
            with self.subTest(connector=connector):
                current_judgment = next(
                    span
                    for span in casefile.generate_source_spans("I1", text)
                    if "我认为他是回避型" in span["text"]
                )
                kind = casefile.derive_claim_kind_for_span(
                    current_judgment["text"], current_judgment, text
                )
                self.assertEqual("identity_claim", kind)
                self.assertEqual(
                    "user_report",
                    casefile._expected_source_type_for_claim_span(
                        current_judgment, kind
                    ),
                )

    def test_contrastive_replacement_without_comma_is_currently_asserted(self) -> None:
        text = "我不是说他不爱我而是说他是回避型。"
        classified = [
            casefile.derive_claim_kind_for_span(span["text"], span, text)
            for span in casefile.generate_source_spans("I1", text)
        ]

        self.assertNotIn("motive_inference", classified)
        self.assertEqual(1, classified.count("identity_claim"))

    def test_only_if_quote_without_comma_is_not_a_current_position(self) -> None:
        text = "只有老板说：“你不用参加。”我才离开。"
        quote = next(
            span
            for span in casefile.generate_source_spans("I1", text)
            if span["quoted"] is True
        )

        self.assertIsNotNone(casefile._direct_quote_scope_error(text, quote))
        self.assertIsNone(
            casefile.derive_claim_kind_for_span(quote["text"], quote, text)
        )

    def test_ideographic_comma_parallel_actions_remain_two_facts(self) -> None:
        text = "老板取消了会议、删除了文档。"
        observation_types = [
            casefile.derive_observation_type(span["text"], span)
            for span in casefile.generate_source_spans("I1", text)
        ]

        self.assertEqual(
            ["participation_or_schedule_event", "task_or_action_event"],
            observation_types,
        )


if __name__ == "__main__":
    unittest.main()
