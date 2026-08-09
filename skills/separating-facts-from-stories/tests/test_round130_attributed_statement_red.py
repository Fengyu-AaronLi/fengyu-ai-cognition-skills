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
    draft["actions"] = [{"id": "A1", "action_type": "neutral_check", **action}]
    draft["user_decisions"] = ["evidence_threshold"]
    return draft


def _append_claim_and_evidence(
    draft: dict[str, Any],
    span: dict[str, Any],
    *,
    claim_id: str,
    evidence_id: str,
    kind: str,
    source_type: str,
    status: str,
    observation_type: str | None = None,
) -> None:
    claim = {
        "id": claim_id,
        "kind": kind,
        "text": span["text"],
        "input_id": span["input_id"],
        "source_span_id": span["id"],
        "source_ref": span["source_ref"],
        "source_type": source_type,
        "exact_quote": span["text"],
        "epistemic_status": status,
        "diagnostic_boundary": False,
    }
    if observation_type is not None:
        claim["observation_type"] = observation_type
    draft["claims"].append(claim)
    draft["evidence"].append(
        {
            "id": evidence_id,
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": source_type,
            "exact_quote": span["text"],
            "can_establish": [claim_id],
            "cannot_establish": [],
            "limitations": ["single_party_report"],
        }
    )
    draft["evidence_links"].append(
        {
            "proposition_id": claim_id,
            "evidence_ref": evidence_id,
            "relation": "supports",
            "strength": "direct",
            "reason": "anchor_matches_report",
        }
    )


def _previous_revision() -> dict[str, Any]:
    previous = _standard_shell(
        "他看了消息六个小时没回。", "round130-attributed-statement"
    )
    span = next(
        item
        for item in previous["source_spans"]
        if item["text"] == "他看了消息六个小时没回。"
    )
    _append_claim_and_evidence(
        previous,
        span,
        claim_id="C1",
        evidence_id="E1",
        kind="observable_fact",
        source_type="user_direct_observation",
        status="reported",
        observation_type="communication_event",
    )
    assert casefile.validate_casefile(previous) == []
    return previous


def _quote_span(draft: dict[str, Any], text: str) -> dict[str, Any]:
    return next(
        item
        for item in draft["source_spans"]
        if item.get("quoted") is True and item["text"] == text
    )


class Round130AttributedStatementRedTests(unittest.TestCase):
    """A direct account is attributable without promoting its content to fact."""

    def test_pure_quoted_update_has_a_first_class_attributed_statement(self) -> None:
        previous = _previous_revision()
        current = casefile.start_update(
            previous, "他回复：‘手机送修，刚拿回来’。"
        )
        span = _quote_span(current, "手机送修，刚拿回来")

        self.assertEqual(
            "attributed_statement",
            casefile.derive_claim_kind_for_span(
                span["text"], span, current["inputs"][-1]["text"]
            ),
        )
        _append_claim_and_evidence(
            current,
            span,
            claim_id="C2",
            evidence_id="E2",
            kind="attributed_statement",
            source_type="direct_quote",
            status="directly_stated",
        )

        self.assertEqual([], casefile.validate_casefile(current, previous=previous))
        rendered = casefile.render_markdown(current)
        self.assertIn("手机送修，刚拿回来", rendered)
        self.assertIn("不等同于客观事实", rendered)
        self.assertIn("不证明引语内容为事件事实", rendered)

    def test_quoted_action_cannot_be_promoted_to_observable_fact(self) -> None:
        previous = _previous_revision()
        current = casefile.start_update(
            previous, "他回复：‘手机送修，刚拿回来’。"
        )
        full_quote = _quote_span(current, "手机送修，刚拿回来")
        action_quote = _quote_span(current, "手机送修，")
        _append_claim_and_evidence(
            current,
            full_quote,
            claim_id="C2",
            evidence_id="E2",
            kind="attributed_statement",
            source_type="direct_quote",
            status="directly_stated",
        )
        _append_claim_and_evidence(
            current,
            action_quote,
            claim_id="C3",
            evidence_id="E3",
            kind="observable_fact",
            source_type="user_direct_observation",
            status="reported",
            observation_type="task_or_action_event",
        )

        codes = {
            item["code"]
            for item in casefile.validate_casefile(current, previous=previous)
        }
        self.assertIn("FACT_TYPE_UNSUPPORTED", codes)

    def test_nonasserted_or_secondhand_quotes_do_not_become_attributed_statements(self) -> None:
        texts = (
            "电影台词：‘手机送修，刚拿回来’。",
            "他没说：‘手机送修，刚拿回来’。",
            "同事转述他原话：‘手机送修，刚拿回来’。",
            "我撤回刚才引用的‘手机送修，刚拿回来’。",
        )
        for text in texts:
            with self.subTest(text=text):
                draft = casefile.make_draft(text, "round130-negative", "standard")
                kinds = {
                    casefile.derive_claim_kind_for_span(
                        span["text"], span, text
                    )
                    for span in draft["source_spans"]
                    if span.get("quoted") is True
                }
                self.assertNotIn("attributed_statement", kinds)

    def test_past_account_is_not_mislabelled_as_current_position(self) -> None:
        text = "去年他说：‘手机送修，刚拿回来’。"
        draft = casefile.make_draft(text, "round130-past", "standard")
        span = _quote_span(draft, "手机送修，刚拿回来")
        self.assertEqual(
            "attributed_statement",
            casefile.derive_claim_kind_for_span(span["text"], span, text),
        )
        self.assertNotEqual(
            "stated_position",
            casefile.derive_claim_kind_for_span(span["text"], span, text),
        )


if __name__ == "__main__":
    unittest.main()
