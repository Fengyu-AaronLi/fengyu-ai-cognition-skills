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


def _span(draft: dict[str, Any], quote: str, *, current: bool = True) -> dict[str, Any]:
    input_id = draft["current_input_id"] if current else None
    return next(
        item
        for item in draft["source_spans"]
        if item["text"] == quote
        and (input_id is None or item["input_id"] == input_id)
    )


def _append_stated_position(
    draft: dict[str, Any], quote: str, claim_id: str, evidence_id: str
) -> None:
    span = _span(draft, quote)
    draft["claims"].append(
        {
            "id": claim_id,
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
            "id": evidence_id,
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "direct_quote",
            "exact_quote": quote,
            "can_establish": [claim_id],
            "cannot_establish": [],
            "limitations": ["time_scope_limited"],
        }
    )
    draft["evidence_links"].append(
        {
            "proposition_id": claim_id,
            "evidence_ref": evidence_id,
            "relation": "supports",
            "strength": "direct",
            "reason": "direct_current_statement_only",
        }
    )


def _append_story(
    draft: dict[str, Any], quote: str, kind: str, *, boundary: bool = False
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
            "diagnostic_boundary": boundary,
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


def _explicit_correction_revision() -> tuple[dict[str, Any], dict[str, Any]]:
    previous = _standard_shell(
        "老板说：“我会留下”。", "round19-supersession"
    )
    _append_stated_position(previous, "我会留下", "C1", "E1")
    assert casefile.validate_casefile(previous) == []

    current = casefile.start_update(
        previous,
        "老板明确改口，从“我会留下”改为“我会离开”。",
    )
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


class Round19SemanticLifecycleRedTests(unittest.TestCase):
    def test_absolute_and_relative_past_quotes_are_not_current_positions(self) -> None:
        for text in (
            "他在2024年说：“我决定离开。”",
            "他在两个月前说：“我决定离开。”",
            "他在2024-01-02说：“我决定离开。”",
        ):
            with self.subTest(text=text):
                draft = _standard_shell(text, "round19-past-quote")
                _append_stated_position(draft, "我决定离开。", "C1", "E1")
                codes = {
                    item["code"] for item in casefile.validate_casefile(draft)
                }
                self.assertIn("STATED_POSITION_NOT_CURRENT", codes)

    def test_postfixed_hearsay_reclassifies_the_preceding_observation(self) -> None:
        for text in (
            "[我的观察] 老板取消了项目会，我是从小李那里听来的。",
            "[我的观察] 老板取消了项目会，消息来自小李。",
            "[我的观察] 老板取消了项目会，这是小李后来告诉我的。",
        ):
            with self.subTest(text=text):
                span = next(
                    item
                    for item in casefile.generate_source_spans("I1", text)
                    if item["text"] == "老板取消了项目会，"
                )
                self.assertEqual(
                    "secondhand", casefile._expected_source_type_for_span(span)
                )

    def test_story_claim_kind_is_semantically_derived(self) -> None:
        examples = (
            ("他是NPD。", "interpretation"),
            ("他永远不会回来。", "motive_inference"),
            ("他不爱我。", "prediction"),
        )
        for text, wrong_kind in examples:
            with self.subTest(text=text, wrong_kind=wrong_kind):
                draft = _standard_shell(text, "round19-story-kind")
                _append_story(draft, text, wrong_kind)
                codes = {
                    item["code"] for item in casefile.validate_casefile(draft)
                }
                self.assertIn("CLAIM_KIND_NOT_DERIVED", codes)

    def test_current_direct_position_cannot_be_downgraded_to_interpretation(self) -> None:
        text = "他说：“我决定离开。”"
        draft = _standard_shell(text, "round19-position-kind")
        _append_story(draft, "我决定离开。", "interpretation")
        codes = {item["code"] for item in casefile.validate_casefile(draft)}
        self.assertIn("CLAIM_KIND_NOT_DERIVED", codes)

    def test_role_evidence_requires_current_first_party_direct_scope(self) -> None:
        claim = {
            "kind": "interpretation",
            "source_ref": "P1",
            "exact_quote": "我认为自己被架空。",
        }
        rejected = (
            "我听说小李的审批权限已经失效。",
            "我猜小李的审批权限已经失效。",
            "我从同事那里听说我的审批权限已经失效。",
            "三年前我的审批权限已经失效。",
            "我确认我的审批权限并非已经失效。",
            "小李的审批权限今天已经失效。",
        )
        for quote in rejected:
            with self.subTest(quote=quote):
                allowed = casefile._allowed_relation_for_claim_evidence(
                    claim, {"source_ref": "E1", "exact_quote": quote}
                )
                self.assertEqual({"does_not_establish"}, allowed)

        self.assertIn(
            "supports",
            casefile._allowed_relation_for_claim_evidence(
                claim,
                {
                    "source_ref": "E2",
                    "exact_quote": "我的审批权限今天已经失效。",
                },
            ),
        )
        self.assertIn(
            "conflicts",
            casefile._allowed_relation_for_claim_evidence(
                claim,
                {
                    "source_ref": "E3",
                    "exact_quote": "财务系统今天仍允许我审批项目支出。",
                },
            ),
        )

    def test_secondhand_role_evidence_cannot_change_revision_status(self) -> None:
        previous = _standard_shell(
            "[P1] 我认为自己被架空。", "round19-role-update"
        )
        _append_story(previous, "我认为自己被架空。", "interpretation")
        self.assertEqual([], casefile.validate_casefile(previous))

        current = casefile.start_update(
            previous,
            "[E2] 我从同事那里听说我的审批权限已经失效。",
        )
        span = _span(
            current, "我从同事那里听说我的审批权限已经失效。"
        )
        current["claims"].append(
            {
                "id": "C2",
                "kind": "interpretation",
                "text": span["text"],
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "secondhand",
                "exact_quote": span["text"],
                "epistemic_status": "unverified",
                "diagnostic_boundary": False,
            }
        )
        current["evidence"].append(
            {
                "id": "E2",
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "secondhand",
                "exact_quote": span["text"],
                "can_establish": ["C1"],
                "cannot_establish": ["C2"],
                "limitations": ["secondhand"],
            }
        )
        current["evidence_links"].extend(
            [
                {
                    "proposition_id": "C2",
                    "evidence_ref": "E2",
                    "relation": "does_not_establish",
                    "strength": "none",
                    "reason": "source_scope_limit",
                },
                {
                    "proposition_id": "C1",
                    "evidence_ref": "E2",
                    "relation": "supports",
                    "strength": "weak",
                    "reason": "behavior_is_compatible_but_not_diagnostic",
                },
            ]
        )
        current["claims"][0]["epistemic_status"] = "weakly_supported"
        current["change_log"] = [
            {
                "target_id": "C1",
                "from_status": "unverified",
                "to_status": "weakly_supported",
                "reason_evidence_refs": ["E2"],
            }
        ]
        codes = {
            item["code"]
            for item in casefile.validate_casefile(current, previous=previous)
        }
        self.assertIn("RELATION_SEMANTICALLY_UNSUPPORTED", codes)
        self.assertIn("CHANGE_REASON_NOT_CAUSAL", codes)

    def test_explicit_current_correction_supersedes_and_renders_history(self) -> None:
        previous, current = _explicit_correction_revision()
        self.assertEqual(
            [], casefile.validate_casefile(current, previous=previous)
        )
        rendered = casefile.render_markdown(current)
        fact_section = rendered.split("## 2.", maxsplit=1)[0]
        self.assertNotIn("我会留下", fact_section)
        self.assertIn("## 已被明确更正的历史表态", rendered)
        self.assertIn("我会留下", rendered)

    def test_contradiction_without_explicit_correction_cannot_supersede(self) -> None:
        previous, current = _explicit_correction_revision()
        replacement_text = "老板说：“我会离开”。"
        current = casefile.start_update(previous, replacement_text)
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
        codes = {
            item["code"]
            for item in casefile.validate_casefile(current, previous=previous)
        }
        self.assertIn("SUPERSESSION_NOT_EXPLICIT", codes)

    def test_supersession_requires_a_new_current_direct_replacement(self) -> None:
        previous, current = _explicit_correction_revision()
        current["change_log"][0]["superseded_by_claim_id"] = "C1"
        codes = {
            item["code"]
            for item in casefile.validate_casefile(current, previous=previous)
        }
        self.assertIn("SUPERSESSION_REPLACEMENT_INVALID", codes)


if __name__ == "__main__":
    unittest.main()
