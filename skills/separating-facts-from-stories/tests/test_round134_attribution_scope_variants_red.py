from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


DISALLOWED_VARIANTS = (
    "经朋友确认，他当时说：‘手机送修，刚拿回来’。",
    "我没亲耳听见，是同事告诉我他原话是：‘手机送修，刚拿回来’。",
    "语音转写显示他讲：‘手机送修，刚拿回来’。",
    "她授权助理回复：‘手机送修，刚拿回来’。",
    "助理以她的名义说：‘手机送修，刚拿回来’。",
    "访谈模拟里，他回答：‘手机送修，刚拿回来’。",
    "他说：‘手机送修了，对吧。’",
    "He said, “Was the phone repaired.”",
    "他说：‘手机送修，刚拿回来’，然后说前面的话不能算。",
    "这是同事转述的。她说：‘手机送修，刚拿回来’。",
    "下面内容来自同事转述：\n她说：‘手机送修，刚拿回来’。",
    "这是一个虚构案例。\n他回复：‘手机送修，刚拿回来’。",
)

POSITIVE_DIRECT_VARIANTS = (
    "今天他当面对我说：‘手机送修，刚拿回来’。",
    "老板刚刚回复：‘本周会议照常’。",
    "去年她在会上说：‘预算保持不变’。",
    "He said, “The phone was repaired.”",
    "张伟说：‘手机送修，刚拿回来’。",
    "他解释道：‘手机送修，刚拿回来’。",
    "我丈夫说：‘手机送修，刚拿回来’。",
    "She explained, “The phone is being repaired.”",
    "他说：‘我不知道手机有没有送修。’",
)


def _full_quote_span(draft: dict[str, Any]) -> dict[str, Any]:
    return max(
        (item for item in draft["source_spans"] if item.get("quoted") is True),
        key=lambda item: len(item["text"]),
    )


def _standard_shell(text: str) -> dict[str, Any]:
    draft = casefile.make_draft(text, "round134-attribution-scope", "standard")
    draft["unknowns"] = [
        {
            "id": "U1",
            "unknown_type": "event_cause_or_context",
            "text": casefile.UNKNOWN_CATALOG["event_cause_or_context"],
            "status": "open",
            "resolved_by_evidence_refs": [],
        }
    ]
    action = {
        key: value
        for key, value in casefile.ACTION_CATALOG["neutral_check"].items()
        if key != "modes"
    }
    draft["actions"] = [{"id": "A1", "action_type": "neutral_check", **action}]
    draft["user_decisions"] = ["evidence_threshold"]
    return draft


def _append_attributed_statement(
    draft: dict[str, Any], span: dict[str, Any]
) -> None:
    draft["claims"].append(
        {
            "id": "C1",
            "kind": "attributed_statement",
            "text": span["text"],
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "direct_quote",
            "exact_quote": span["text"],
            "epistemic_status": "directly_stated",
            "diagnostic_boundary": False,
        }
    )
    draft["evidence"].append(
        {
            "id": "E1",
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "direct_quote",
            "exact_quote": span["text"],
            "can_establish": ["C1"],
            "cannot_establish": [],
            "limitations": ["single_party_report"],
        }
    )
    draft["evidence_links"].append(
        {
            "proposition_id": "C1",
            "evidence_ref": "E1",
            "relation": "supports",
            "strength": "direct",
            "reason": "anchor_matches_report",
        }
    )


class Round134AttributionScopeVariantsRedTests(unittest.TestCase):
    def test_disallowed_variants_do_not_derive_direct_attribution(self) -> None:
        for text in DISALLOWED_VARIANTS:
            with self.subTest(text=text):
                draft = casefile.make_draft(text, "round134-derive", "standard")
                span = _full_quote_span(draft)
                self.assertNotEqual(
                    "attributed_statement",
                    casefile.derive_claim_kind_for_span(span["text"], span, text),
                )

    def test_disallowed_variants_fail_complete_casefile_validation(self) -> None:
        for text in DISALLOWED_VARIANTS:
            with self.subTest(text=text):
                draft = _standard_shell(text)
                span = _full_quote_span(draft)
                _append_attributed_statement(draft, span)
                codes = {item["code"] for item in casefile.validate_casefile(draft)}
                self.assertTrue(
                    {
                        "CLAIM_KIND_NOT_DERIVED",
                        "DIRECT_QUOTE_NOT_ASSERTED",
                        "DIRECT_QUOTE_PROVENANCE_UNKNOWN",
                        "SOURCE_TYPE_MISMATCH",
                    }
                    & codes,
                    codes,
                )

    def test_direct_human_declarative_controls_remain_attributed(self) -> None:
        for text in POSITIVE_DIRECT_VARIANTS:
            with self.subTest(text=text):
                draft = casefile.make_draft(text, "round134-positive", "standard")
                span = _full_quote_span(draft)
                self.assertEqual(
                    "attributed_statement",
                    casefile.derive_claim_kind_for_span(span["text"], span, text),
                )


if __name__ == "__main__":
    unittest.main()
