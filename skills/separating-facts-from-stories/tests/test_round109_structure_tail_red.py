from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round109StructureTailRedTests(unittest.TestCase):
    """Held-out structural tails beyond the Round102/104 matrices."""

    @staticmethod
    def _span_containing(text: str, needle: str) -> dict[str, Any]:
        return next(
            item
            for item in casefile.generate_source_spans("I1", text)
            if needle in item["text"]
        )

    @staticmethod
    def _validator_codes(draft: dict[str, Any]) -> list[str]:
        return [
            item["code"] for item in casefile.validate_casefile(draft)
        ]

    def test_directly_negated_determinations_remain_nonasserted(self) -> None:
        matrix = (
            "我暂时不认定他是回避型。",
            "我现阶段不认定他是NPD。",
        )
        for text in matrix:
            with self.subTest(text=text):
                draft = casefile.make_draft(
                    text, "round109-nonasserted", "standard"
                )
                span = draft["source_spans"][0]
                self.assertIsNone(
                    casefile.derive_claim_kind_for_span(
                        span["text"], span, text
                    )
                )
                self.assertNotIn(
                    "USER_STORY_CLAIM_MISSING",
                    self._validator_codes(draft),
                )

    def test_correlative_coordination_preserves_subjectless_predictions(
        self,
    ) -> None:
        matrix = (
            (
                "他既不爱我，也不会再回来。",
                ["motive_inference", "prediction"],
            ),
            (
                "老板既在架空我，也会辞退我。",
                ["interpretation", "prediction"],
            ),
        )
        for text, expected in matrix:
            with self.subTest(text=text):
                draft = casefile.make_draft(
                    text, "round109-coordination", "standard"
                )
                actual = [
                    casefile.derive_claim_kind_for_span(
                        span["text"], span, text
                    )
                    for span in draft["source_spans"]
                ]
                self.assertEqual(expected, actual)
                self.assertEqual(
                    len(expected),
                    self._validator_codes(draft).count(
                        "USER_STORY_CLAIM_MISSING"
                    ),
                )

    def test_suo_clefts_keep_attitude_complements_nonfactive(self) -> None:
        matrix = (
            ("我所担心的是老板取消了会议。", "老板取消了会议"),
            ("我所害怕的是对方取消了约会。", "对方取消了约会"),
        )
        for text, needle in matrix:
            with self.subTest(text=text):
                draft = casefile.make_draft(
                    text, "round109-nonfactive", "standard"
                )
                span = self._span_containing(text, needle)
                self.assertIn(
                    "inferred_nonfactive_context",
                    {
                        part.strip()
                        for part in str(span["source_label"]).split("｜")
                    },
                )
                self.assertIsNone(
                    casefile.derive_observation_type(span["text"], span)
                )
                self.assertNotIn(
                    "OBSERVABLE_FACT_CLAIM_MISSING",
                    self._validator_codes(draft),
                )

    def test_postfix_bold_requests_own_their_complete_operand(self) -> None:
        matrix = (
            "“他不爱我”，请只加粗。",
            "“他是回避型”，请只加粗。",
        )
        for text in matrix:
            with self.subTest(text=text):
                draft = casefile.make_draft(
                    text, "round109-formatting", "auto"
                )
                self.assertEqual("passthrough", draft["mode"])
                for span in draft["source_spans"]:
                    if span["quoted"] is not True:
                        self.assertIsNone(
                            casefile.derive_claim_kind_for_span(
                                span["text"], span, text
                            )
                        )

    def test_explicit_future_dates_without_modals_remain_predictions(
        self,
    ) -> None:
        matrix = (
            "公司下个月裁掉我。",
            "老板下周辞退我。",
        )
        for text in matrix:
            with self.subTest(text=text):
                draft = casefile.make_draft(
                    text, "round109-prediction", "standard"
                )
                span = draft["source_spans"][0]
                self.assertEqual(
                    "prediction",
                    casefile.derive_claim_kind_for_span(
                        span["text"], span, text
                    ),
                )
                self.assertEqual(
                    1,
                    self._validator_codes(draft).count(
                        "USER_STORY_CLAIM_MISSING"
                    ),
                )

    def test_fronted_quantity_passives_remain_observable(self) -> None:
        matrix = (
            "两次约会均被她取消。",
            "三次会议都被他取消。",
        )
        for text in matrix:
            with self.subTest(text=text):
                draft = casefile.make_draft(
                    text, "round109-quantity-passive", "standard"
                )
                span = draft["source_spans"][0]
                self.assertEqual(
                    "participation_or_schedule_event",
                    casefile.derive_observation_type(span["text"], span),
                )
                self.assertEqual(
                    1,
                    self._validator_codes(draft).count(
                        "OBSERVABLE_FACT_CLAIM_MISSING"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
