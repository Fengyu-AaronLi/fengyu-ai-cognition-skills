from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round104StructuralClosureRedTests(unittest.TestCase):
    """New structural variants that remain open after the Round102 matrix."""

    @staticmethod
    def _span_containing(text: str, needle: str) -> dict[str, Any]:
        return next(
            item
            for item in casefile.generate_source_spans("I1", text)
            if needle in item["text"]
        )

    def test_assertion_scope_accepts_governing_prefaces_and_predicates(
        self,
    ) -> None:
        matrix = (
            (
                "evidence_preface",
                "现有证据尚不足以证明他不爱我。",
                "不爱我",
            ),
            (
                "single_signal_preface",
                "单凭这两次没回不足以证明他不爱我。",
                "证明他不爱我",
            ),
            (
                "withheld_determination",
                "我还不能断定他不爱我。",
                "不爱我",
            ),
            (
                "unable_to_confirm",
                "我无法确认他是回避型。",
                "回避型",
            ),
        )
        for family, text, needle in matrix:
            with self.subTest(family=family, text=text):
                span = self._span_containing(text, needle)
                self.assertIsNone(
                    casefile.derive_claim_kind_for_span(span["text"], span, text)
                )

    def test_story_coordination_closes_correlative_and_escalation_forms(
        self,
    ) -> None:
        matrix = (
            (
                "not_only",
                "他不仅不爱我还准备离开我。",
                ["motive_inference", "prediction"],
            ),
            (
                "not_merely",
                "他不光不爱我还准备离开我。",
                ["motive_inference", "prediction"],
            ),
            (
                "escalation",
                "他不爱我甚至准备离开我。",
                ["motive_inference", "prediction"],
            ),
            (
                "additive_workplace",
                "老板在架空我外加准备开掉我。",
                ["interpretation", "prediction"],
            ),
        )
        for family, text, expected in matrix:
            with self.subTest(family=family, text=text):
                spans = casefile.generate_source_spans("I1", text)
                self.assertEqual(
                    expected,
                    [
                        casefile.derive_claim_kind_for_span(
                            item["text"], item, text
                        )
                        for item in spans
                    ],
                )

    def test_nonfactive_scope_survives_modifiers_and_clefts(self) -> None:
        matrix = (
            ("durative_modifier", "我一直担心老板取消了会议。"),
            ("degree_modifier", "我最担心老板取消了会议。"),
            ("first_person_cleft", "我担心的是老板取消了会议。"),
            ("experiencer_cleft", "让我担心的是老板取消了会议。"),
        )
        for family, text in matrix:
            with self.subTest(family=family, text=text):
                span = self._span_containing(text, "老板取消了会议")
                self.assertIsNone(casefile.derive_observation_type(span["text"], span))
                codes = {
                    item["code"]
                    for item in casefile.validate_casefile(
                        casefile.make_draft(
                            text,
                            f"round104-nonfactive-{family}",
                            "standard",
                        )
                    )
                }
                self.assertNotIn("OBSERVABLE_FACT_CLAIM_MISSING", codes)

    def test_format_operation_ownership_supports_postfix_and_object_synonyms(
        self,
    ) -> None:
        matrix = (
            ("postfix", "“他不爱我。”，请只改格式。"),
            ("described_postfix", "原文如下：“他不爱我。”，请重新排版。"),
            ("give_bold", "请给“他不爱我”加粗。"),
            ("split_lines", "请把“他不爱我”拆成两行。"),
            ("do_layout", "请做一下排版：“他不爱我。”"),
        )
        for family, text in matrix:
            with self.subTest(family=family, text=text):
                draft = casefile.make_draft(text, f"round104-format-{family}", "auto")
                self.assertEqual("passthrough", draft["mode"])
                for span in draft["source_spans"]:
                    if span["quoted"] is not True:
                        self.assertIsNone(
                            casefile.derive_claim_kind_for_span(
                                span["text"], span, text
                            )
                        )

    def test_prediction_grammar_supports_named_actors_and_new_outcomes(
        self,
    ) -> None:
        matrix = (
            ("former_partner", "前任会回来。"),
            ("named_person", "小李准备离开。"),
            ("relationship_role", "男朋友不会再回来。"),
            ("future_contact", "他可能不会再联系我。"),
            ("company_redundancy", "公司准备裁掉我。"),
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
                        casefile.make_draft(
                            text,
                            f"round104-prediction-{family}",
                            "standard",
                        )
                    )
                }
                self.assertIn("USER_STORY_CLAIM_MISSING", codes)

    def test_quantity_grammar_supports_aspect_adverbs_and_voice(self) -> None:
        matrix = (
            ("successive", "她先后取消了两次约会。"),
            ("total", "她总共取消了两次约会。"),
            ("past_aspect", "她曾两次取消约会。"),
            ("ba_postposed_count", "她把约会取消了两次。"),
            ("passive", "约会被她取消了两次。"),
            ("cumulative", "她累计取消了两次约会。"),
        )
        for family, text in matrix:
            with self.subTest(family=family, text=text):
                span = casefile.generate_source_spans("I1", text)[0]
                self.assertEqual(
                    "participation_or_schedule_event",
                    casefile.derive_observation_type(span["text"], span),
                )


if __name__ == "__main__":
    unittest.main()
