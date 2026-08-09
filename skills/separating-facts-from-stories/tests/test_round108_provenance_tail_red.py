from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


def _standard_shell(text: str, case_id: str) -> dict[str, Any]:
    draft = casefile.make_draft(text, case_id, "standard")
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
    draft["actions"] = [
        {"id": "A1", "action_type": "neutral_check", **action}
    ]
    draft["user_decisions"] = ["evidence_threshold"]
    return draft


def _span(draft: dict[str, Any], quote: str) -> dict[str, Any]:
    return next(
        item
        for item in draft["source_spans"]
        if item["input_id"] == draft["current_input_id"]
        and item["text"] == quote
    )


def _append_stated_position(draft: dict[str, Any], quote: str) -> None:
    span = _span(draft, quote)
    draft["claims"].append(
        {
            "id": "C1",
            "kind": "stated_position",
            "text": quote,
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "direct_quote",
            "exact_quote": quote,
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
            "exact_quote": quote,
            "can_establish": ["C1"],
            "cannot_establish": [],
            "limitations": ["time_scope_limited"],
        }
    )
    draft["evidence_links"].append(
        {
            "proposition_id": "C1",
            "evidence_ref": "E1",
            "relation": "supports",
            "strength": "direct",
            "reason": "direct_current_statement_only",
        }
    )


def _append_story(
    draft: dict[str, Any], quote: str, kind: str
) -> None:
    span = _span(draft, quote)
    draft["claims"].append(
        {
            "id": "C1",
            "kind": kind,
            "text": quote,
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "user_report",
            "exact_quote": quote,
            "epistemic_status": "unverified",
            "diagnostic_boundary": False,
        }
    )
    draft["evidence"].append(
        {
            "id": "E1",
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "user_report",
            "exact_quote": quote,
            "can_establish": [],
            "cannot_establish": ["C1"],
            "limitations": ["single_party_report"],
        }
    )
    draft["evidence_links"].append(
        {
            "proposition_id": "C1",
            "evidence_ref": "E1",
            "relation": "does_not_establish",
            "strength": "none",
            "reason": "source_scope_limit",
        }
    )


def _codes(draft: dict[str, Any]) -> set[str]:
    return {item["code"] for item in casefile.validate_casefile(draft)}


class Round108ProvenanceTailRedTests(unittest.TestCase):
    """Public-validator RED coverage for the remaining provenance tails."""

    direct_quote_rejection_codes = {
        "SOURCE_TYPE_MISMATCH",
        "DIRECT_QUOTE_NOT_ASSERTED",
        "CLAIM_KIND_NOT_DERIVED",
    }

    def test_compound_secondhand_labels_beat_quote_carriers(self) -> None:
        examples = (
            ("[转告｜邮件] 他说：“我会离开。”", "我会离开。"),
            ("[录音｜传话] 老板说：“我会离开。”", "我会离开。"),
        )
        for text, quote in examples:
            with self.subTest(text=text):
                draft = _standard_shell(text, "round108-compound-label")
                _append_stated_position(draft, quote)
                self.assertTrue(
                    _codes(draft) & self.direct_quote_rejection_codes
                )

    def test_proxy_message_senders_cannot_create_direct_quotes(self) -> None:
        examples = (
            ("我替他发来原话：“我会离开。”", "我会离开。"),
            (
                "我按他给的原文代发消息说：“我会离开。”",
                "我会离开。",
            ),
        )
        for text, quote in examples:
            with self.subTest(text=text):
                draft = _standard_shell(text, "round108-proxy-sender")
                _append_stated_position(draft, quote)
                self.assertTrue(
                    _codes(draft) & self.direct_quote_rejection_codes
                )

    def test_fresh_hearsay_cannot_fall_back_to_user_report(self) -> None:
        examples = (
            ("网传老板在架空我。", "网传老板在架空我。"),
            (
                "群聊传出的风声是老板在架空我。",
                "群聊传出的风声是老板在架空我。",
            ),
        )
        for text, quote in examples:
            with self.subTest(text=text):
                draft = _standard_shell(text, "round108-fresh-hearsay")
                _append_story(draft, quote, "interpretation")
                self.assertIn("SOURCE_TYPE_MISMATCH", _codes(draft))

    def test_postfixed_relay_context_revokes_direct_quote_status(self) -> None:
        examples = (
            (
                "他说：“我会离开。”，这是邮件转述的。",
                "我会离开。",
            ),
            (
                "老板说：“我会留下。”，这段话来自群聊里的转述。",
                "我会留下。",
            ),
        )
        for text, quote in examples:
            with self.subTest(text=text):
                draft = _standard_shell(text, "round108-postfix-relay")
                _append_stated_position(draft, quote)
                self.assertTrue(
                    _codes(draft) & self.direct_quote_rejection_codes
                )

    def test_first_person_ownership_resets_prior_secondhand_context(self) -> None:
        examples = (
            (
                "同事说他忙，但我认定他不爱我。",
                "我认定他不爱我。",
            ),
            (
                "朋友说他忙，不过这是我得出的结论：他不爱我。",
                "这是我得出的结论：他不爱我。",
            ),
        )
        for text, quote in examples:
            with self.subTest(text=text):
                draft = _standard_shell(text, "round108-owner-reset")
                _append_story(draft, quote, "motive_inference")
                self.assertNotIn("SOURCE_TYPE_MISMATCH", _codes(draft))


if __name__ == "__main__":
    unittest.main()
