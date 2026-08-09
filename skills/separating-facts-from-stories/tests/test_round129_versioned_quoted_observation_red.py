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


def _append_observation(
    draft: dict[str, Any], span: dict[str, Any], claim_id: str, evidence_id: str
) -> None:
    observation_type = casefile.derive_observation_type(span["text"], span)
    assert observation_type is not None
    draft["claims"].append(
        {
            "id": claim_id,
            "kind": "observable_fact",
            "observation_type": observation_type,
            "text": span["text"],
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "user_direct_observation",
            "exact_quote": span["text"],
            "epistemic_status": "reported",
            "diagnostic_boundary": False,
        }
    )
    draft["evidence"].append(
        {
            "id": evidence_id,
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "user_direct_observation",
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


def _append_attributed_statement(
    draft: dict[str, Any], span: dict[str, Any], claim_id: str, evidence_id: str
) -> None:
    draft["claims"].append(
        {
            "id": claim_id,
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
            "id": evidence_id,
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "direct_quote",
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


class Round129VersionedQuotedObservationRedTests(unittest.TestCase):
    """A relayed quote cannot be both forbidden as fact and mandatory as fact."""

    def test_quoted_action_spans_are_not_mandatory_observations_in_update(self) -> None:
        previous = _standard_shell(
            "他看了消息六个小时没回。", "round129-versioned-quoted-observation"
        )
        previous_span = next(
            item
            for item in previous["source_spans"]
            if item["text"] == "他看了消息六个小时没回。"
        )
        _append_observation(previous, previous_span, "C1", "E1")
        self.assertEqual([], casefile.validate_casefile(previous))

        current = casefile.start_update(
            previous,
            "他后来回复原话是‘手机送修，刚拿回来’，并发来当天维修单。",
        )
        current_input_id = current["current_input_id"]
        quoted_action_spans = [
            item
            for item in current["source_spans"]
            if item["input_id"] == current_input_id
            and item.get("quoted") is True
            and casefile.derive_observation_type(item["text"], item) is not None
        ]
        self.assertEqual(
            ["手机送修，", "刚拿回来"],
            [item["text"] for item in quoted_action_spans],
        )
        full_quote = next(
            item
            for item in current["source_spans"]
            if item["input_id"] == current_input_id
            and item.get("quoted") is True
            and item["text"] == "手机送修，刚拿回来"
        )
        _append_attributed_statement(current, full_quote, "C2", "E2")

        unquoted_observation_spans = [
            item
            for item in current["source_spans"]
            if item["input_id"] == current_input_id
            and item.get("quoted") is not True
            and casefile.derive_observation_type(item["text"], item) is not None
            and casefile._expected_source_type_for_span(item) != "secondhand"
        ]
        self.assertIn(
            "并发来当天维修单。",
            [item["text"] for item in unquoted_observation_spans],
        )
        for offset, span in enumerate(unquoted_observation_spans, start=3):
            _append_observation(current, span, f"C{offset}", f"E{offset}")

        errors = casefile.validate_casefile(current, previous=previous)
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
