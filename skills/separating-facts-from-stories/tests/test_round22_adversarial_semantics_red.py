from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
from test_round19_semantic_lifecycle_red import (  # noqa: E402
    _append_stated_position,
    _span,
    _standard_shell,
)


def _supersession_revision(
    previous_text: str,
    current_text: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    previous = _standard_shell(previous_text, "round22-supersession")
    _append_stated_position(previous, "我会留下", "C1", "E1")
    assert casefile.validate_casefile(previous) == []

    current = casefile.start_update(previous, current_text)
    _append_stated_position(current, "我会离开", "C2", "E2")
    current["claims"][0]["epistemic_status"] = "superseded"
    current["change_log"] = [
        {
            "target_id": "C1",
            "from_status": "directly_stated",
            "to_status": "superseded",
            "reason_evidence_refs": ["E2"],
            "superseded_by_claim_id": "C2",
        }
    ]
    return previous, current


class Round22AdversarialSemanticsRedTests(unittest.TestCase):
    def test_equivalent_story_forms_have_one_derived_kind(self) -> None:
        cases = (
            ("他是个骗子。", "他是个骗子。", "identity_claim"),
            ("他这辈子都回不来了。", "他这辈子都回不来了。", "prediction"),
            ("他存着害我的心。", "他存着害我的心。", "motive_inference"),
            (
                "[原话] 老板说：“我已经决定走了”。",
                "我已经决定走了",
                "stated_position",
            ),
        )
        for text, quote, expected in cases:
            with self.subTest(text=text):
                draft = casefile.make_draft(text, "round22-kind", "standard")
                span = _span(draft, quote)
                self.assertEqual(
                    expected,
                    casefile.derive_claim_kind_for_span(quote, span, text),
                )

    def test_postfix_provenance_variants_reclassify_prior_observation(self) -> None:
        cases = (
            "[我的观察] 老板取消了项目会，这是小李转达给我的。",
            "[我的观察] 老板取消了项目会，这是小李传话给我的。",
            "[我的观察] 老板取消了项目会，这是小李透露给我的。",
            "[我的观察] 老板取消了项目会，我是通过小李得知的。",
            "[我的观察] 老板取消了项目会，消息来源是小李。",
        )
        for text in cases:
            with self.subTest(text=text):
                span = next(
                    item
                    for item in casefile.generate_source_spans("I1", text)
                    if item["text"] == "老板取消了项目会，"
                )
                self.assertEqual(
                    "secondhand", casefile._expected_source_type_for_span(span)
                )

    def test_unicode_and_natural_past_time_scopes_are_not_current(self) -> None:
        cases = (
            "老板在二〇二四年说：“我会留下”。",
            "老板在２０２４年说：“我会留下”。",
            "老板在2024 年说：“我会留下”。",
            "老板本月初说：“我会留下”。",
            "老板上季度说：“我会留下”。",
            "老板一年半前说：“我会留下”。",
            "老板两年多前说：“我会留下”。",
        )
        for text in cases:
            with self.subTest(text=text):
                draft = casefile.make_draft(text, "round22-past", "standard")
                span = _span(draft, "我会留下")
                self.assertTrue(casefile._direct_quote_has_past_scope(text, span))

    def test_role_evidence_fails_closed_on_scope_source_time_and_polarity(self) -> None:
        claim = {
            "kind": "interpretation",
            "source_ref": "P1",
            "exact_quote": "我被架空了。",
        }
        rejected = (
            "不能说我的审批权限已经失效。",
            "我的同事小李审批权限失效。",
            "听人讲，我的审批权限失效。",
            "据我所知，我的审批权限失效。",
            "上季度我的审批权限失效。",
        )
        for quote in rejected:
            with self.subTest(quote=quote):
                allowed = casefile._allowed_relation_for_claim_evidence(
                    claim,
                    {"source_ref": "E1", "exact_quote": quote},
                )
                self.assertEqual({"does_not_establish"}, allowed)

        for prefix in ("听人讲", "据我所知"):
            text = f"[E1] {prefix}，我的审批权限失效。"
            span = next(
                item
                for item in casefile.generate_source_spans("I1", text)
                if item["text"] == "我的审批权限失效。"
            )
            self.assertEqual(
                "secondhand", casefile._expected_source_type_for_span(span)
            )

    def test_supersession_rejects_entity_source_and_time_drift(self) -> None:
        cases = (
            (
                "甲公司的老板说：“我会留下”。",
                "乙公司的老板明确改口，从“我会留下”改为“我会离开”。",
                "SUPERSESSION_NOT_EXPLICIT",
            ),
            (
                "老板说：“我会留下”。",
                "秘书转达：老板明确改口，从“我会留下”改为“我会离开”。",
                "SUPERSESSION_NOT_EXPLICIT",
            ),
            (
                "老板说：“我会留下”。",
                "二〇二四年，老板明确改口，从“我会留下”改为“我会离开”。",
                "SUPERSESSION_NOT_EXPLICIT",
            ),
        )
        for previous_text, current_text, expected_code in cases:
            with self.subTest(current_text=current_text):
                previous, current = _supersession_revision(
                    previous_text, current_text
                )
                codes = {
                    item["code"]
                    for item in casefile.validate_casefile(
                        current, previous=previous
                    )
                }
                self.assertIn(expected_code, codes)


if __name__ == "__main__":
    unittest.main()
