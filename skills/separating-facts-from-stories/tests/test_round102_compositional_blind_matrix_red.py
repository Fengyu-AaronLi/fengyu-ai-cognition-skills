from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round102CompositionalBlindMatrixRedTests(unittest.TestCase):
    """Blind metamorphic matrices for the nine open epistemic gaps."""

    @staticmethod
    def _span_containing(text: str, needle: str) -> dict[str, object]:
        return next(
            item
            for item in casefile.generate_source_spans("I1", text)
            if needle in item["text"]
        )

    def test_nonasserted_scope_variants_do_not_become_current_story_claims(
        self,
    ) -> None:
        matrix = (
            ("denied_attribution", "我并非认为他不爱我。", "不爱我"),
            ("insufficient_evidence", "这不足以证明他不爱我。", "不爱我"),
            ("qualified_evidence", "没有充分证据证明他不爱我。", "不爱我"),
            ("concessive_antecedent", "即使他不爱我，我也会留下。", "不爱我"),
            ("exception_antecedent", "除非他不爱我，否则我会留下。", "不爱我"),
            ("hypothetical_synonym", "假定他是回避型。", "回避型"),
            ("prefixed_hypothetical", "先假设他是回避型。", "回避型"),
        )
        for family, text, needle in matrix:
            with self.subTest(family=family, text=text):
                span = self._span_containing(text, needle)
                self.assertIsNone(
                    casefile.derive_claim_kind_for_span(span["text"], span, text)
                )

    def test_story_coordination_variants_preserve_every_epistemic_kind(
        self,
    ) -> None:
        matrix = (
            (
                "correlative",
                "他既不爱我又是回避型。",
                ["motive_inference", "identity_claim"],
            ),
            (
                "repeated_additive",
                "他又不爱我又是回避型。",
                ["motive_inference", "identity_claim"],
            ),
            (
                "compact_conjunction",
                "他不爱我且是回避型。",
                ["motive_inference", "identity_claim"],
            ),
            (
                "enumeration_punctuation",
                "他不爱我、是回避型。",
                ["motive_inference", "identity_claim"],
            ),
            (
                "interpretation_then_forecast",
                "老板在架空我又准备开掉我。",
                ["interpretation", "prediction"],
            ),
        )
        for family, text, expected in matrix:
            with self.subTest(family=family, text=text):
                spans = casefile.generate_source_spans("I1", text)
                actual = [
                    casefile.derive_claim_kind_for_span(item["text"], item, text)
                    for item in spans
                ]
                self.assertEqual(expected, actual)

    def test_nonfactive_feeling_complements_are_not_promoted_to_observations(
        self,
    ) -> None:
        matrix = (
            ("schedule", "我担心老板取消了会议。", "老板取消了会议"),
            ("communication", "我担心他没回消息。", "他没回消息"),
        )
        for family, text, needle in matrix:
            with self.subTest(family=family, text=text):
                span = self._span_containing(text, needle)
                self.assertIsNone(casefile.derive_observation_type(span["text"], span))
                codes = {
                    item["code"]
                    for item in casefile.validate_casefile(
                        casefile.make_draft(text, f"round102-nonfactive-{family}", "standard")
                    )
                }
                self.assertNotIn("OBSERVABLE_FACT_CLAIM_MISSING", codes)

    def test_feeling_sequence_boundaries_keep_actor_with_embedded_clause(
        self,
    ) -> None:
        matrix = (
            (
                "pronoun_actor",
                "我害怕他随后取消了会议。",
                ["我害怕", "他随后取消了会议。"],
            ),
            (
                "compound_actor",
                "我焦虑对方之后取消了约会。",
                ["我焦虑", "对方之后取消了约会。"],
            ),
        )
        for family, text, expected in matrix:
            with self.subTest(family=family, text=text):
                self.assertEqual(
                    expected,
                    [
                        item["text"]
                        for item in casefile.generate_source_spans("I1", text)
                    ],
                )

    def test_formatting_operation_variants_route_to_passthrough(self) -> None:
        matrix = (
            ("format_only", "只改格式：“他不爱我。”"),
            ("reformat", "请重新排版这句：“他不爱我。”"),
            ("bold_object_first", "请把原文“他不爱我”加粗。"),
            ("line_break_object_first", "请把原文“他不爱我”分成两行。"),
        )
        for family, text in matrix:
            with self.subTest(family=family, text=text):
                draft = casefile.make_draft(text, f"round102-format-{family}", "auto")
                self.assertEqual("passthrough", draft["mode"])
                for span in draft["source_spans"]:
                    if span["quoted"] is not True:
                        self.assertIsNone(
                            casefile.derive_claim_kind_for_span(
                                span["text"], span, text
                            )
                        )

    def test_first_person_ownership_resets_secondhand_provenance(self) -> None:
        matrix = (
            (
                "perspective",
                "同事说他爱我，但在我看来他不爱我。",
                "在我看来",
            ),
            (
                "possessive_view",
                "同事说他爱我，不过我的看法是他不爱我。",
                "我的看法",
            ),
            (
                "personal_judgment",
                "同事说他爱我，但我个人认为他不爱我。",
                "我个人认为",
            ),
            (
                "explicit_ownership",
                "同事说他爱我，但这是我自己的判断：他不爱我。",
                "我自己的判断",
            ),
        )
        for family, text, needle in matrix:
            with self.subTest(family=family, text=text):
                span = self._span_containing(text, needle)
                kind = casefile.derive_claim_kind_for_span(span["text"], span, text)
                self.assertNotEqual(
                    "secondhand", casefile._expected_source_type_for_span(span)
                )
                self.assertEqual(
                    "user_report",
                    casefile._expected_source_type_for_claim_span(span, kind),
                )

    def test_artifact_carrier_variants_preserve_non_user_provenance(self) -> None:
        matrix = (
            ("email", "邮件里写着他不爱我。"),
            ("recording", "录音里他说他不爱我。"),
            ("model_output", "模型输出说他不爱我。"),
            ("ai_output", "AI告诉我他不爱我。"),
            ("assessment", "测评结果显示他是NPD。"),
        )
        for family, text in matrix:
            with self.subTest(family=family, text=text):
                span = casefile.generate_source_spans("I1", text)[0]
                self.assertEqual(
                    "unverified_artifact",
                    casefile._expected_source_type_for_span(span),
                )

    def test_schedule_quantity_order_variants_remain_observable(self) -> None:
        matrix = (
            ("aspect_before_count", "她取消过两次约会。"),
            ("continuity_before_verb", "她连续取消了两次约会。"),
            ("successive_adverb", "她接连取消了两次约会。"),
            ("fronted_object", "两次约会她都取消了。"),
            ("ba_construction", "她把两次约会都取消了。"),
        )
        for family, text in matrix:
            with self.subTest(family=family, text=text):
                span = casefile.generate_source_spans("I1", text)[0]
                self.assertEqual(
                    "participation_or_schedule_event",
                    casefile.derive_observation_type(span["text"], span),
                )

    def test_prediction_surface_variants_are_not_silently_omitted(self) -> None:
        matrix = (
            ("negative_return", "他不会再回来。"),
            ("certain_negative_return", "他肯定不会回来。"),
            ("relationship_transition", "他肯定会跟我分手。"),
            ("workplace_termination", "老板会辞退我。"),
            ("near_future_departure", "他马上会离开我。"),
        )
        for family, text in matrix:
            with self.subTest(family=family, text=text):
                span = casefile.generate_source_spans("I1", text)[0]
                self.assertEqual(
                    "prediction",
                    casefile.derive_claim_kind_for_span(span["text"], span, text),
                )
                codes = {
                    item["code"]
                    for item in casefile.validate_casefile(
                        casefile.make_draft(text, f"round102-prediction-{family}", "standard")
                    )
                }
                self.assertIn("USER_STORY_CLAIM_MISSING", codes)


if __name__ == "__main__":
    unittest.main()
