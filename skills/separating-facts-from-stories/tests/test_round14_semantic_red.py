from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import casefile  # noqa: E402
import workflow  # noqa: E402


def _find_span(draft: dict[str, Any], text: str) -> dict[str, Any] | None:
    return next(
        (span for span in draft["source_spans"] if span.get("text") == text),
        None,
    )


def _add_single_claim(
    draft: dict[str, Any],
    span: dict[str, Any],
    *,
    claim_id: str = "C1",
    evidence_id: str = "E1",
    kind: str,
    source_type: str,
    observation_type: str | None,
    epistemic_status: str,
    reason: str,
) -> None:
    draft["claims"].append(
        {
            "id": claim_id,
            "kind": kind,
            "observation_type": observation_type,
            "text": span["text"],
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": source_type,
            "exact_quote": span["text"],
            "epistemic_status": epistemic_status,
            "diagnostic_boundary": False,
        }
    )
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
            "reason": reason,
        }
    )


def _complete_standard_case(draft: dict[str, Any]) -> None:
    draft["unknowns"] = [
        {
            "id": "U1",
            "unknown_type": "event_cause_or_context",
            "text": "当前事件的具体原因或上下文是什么",
            "status": "open",
            "resolved_by_evidence_refs": [],
        }
    ]
    draft["actions"] = [
        {
            "id": "A1",
            "action_type": "neutral_check",
            "text": "围绕具体安排、职责、边界或时间做一次中性核对",
            "timing": "next",
            "risk": "low",
            "reversible": True,
            "motive_independent": True,
            "produces_new_evidence": True,
        }
    ]
    draft["user_decisions"] = ["evidence_threshold"]


def _observable_case(
    input_text: str,
    span_text: str,
    *,
    case_id: str,
) -> dict[str, Any] | None:
    draft = casefile.make_draft(input_text, case_id, "standard")
    span = _find_span(draft, span_text)
    if span is None:
        return None
    _add_single_claim(
        draft,
        span,
        kind="observable_fact",
        source_type="user_direct_observation",
        observation_type="participation_or_schedule_event",
        epistemic_status="reported",
        reason="anchor_matches_report",
    )
    _complete_standard_case(draft)
    return draft


def _case_question_or_denial_tail_cannot_be_detached_and_promoted_to_fact() -> None:
    offenders: list[str] = []
    for input_text in (
        "老板取消周会对吗？",
        "老板取消周会纯属谣言。",
    ):
        draft = _observable_case(
            input_text,
            "老板取消周会",
            case_id="round14-tail-scope",
        )
        if draft is not None and not casefile.validate_casefile(draft):
            offenders.append(input_text)

    assert not offenders, (
        "question or denial scope was stripped before the proposition was "
        f"validated as an observable fact: {offenders}"
    )


def _case_third_party_feeling_cannot_validate_as_user_explicit_feeling() -> None:
    draft = casefile.make_draft("我女儿害怕。", "round14-third-party-feeling", "standard")
    span = _find_span(draft, "我女儿害怕。")
    if span is None:
        return
    _add_single_claim(
        draft,
        span,
        kind="explicit_feeling",
        source_type="explicit_self_report",
        observation_type=None,
        epistemic_status="reported",
        reason="anchor_matches_report",
    )
    _complete_standard_case(draft)

    assert casefile.validate_casefile(draft), (
        "a feeling whose experiencer is the user's daughter validated as the "
        "user's own explicit self-report"
    )


def _case_observation_label_cannot_override_explicit_secondhand_context() -> None:
    input_text = "[我的观察] 据秘书转述，老板取消周会。"
    draft = casefile.make_draft(input_text, "round14-secondhand-label", "standard")
    span = _find_span(draft, "老板取消周会。")
    if span is None:
        return
    _add_single_claim(
        draft,
        span,
        kind="observable_fact",
        source_type="user_direct_observation",
        observation_type="participation_or_schedule_event",
        epistemic_status="reported",
        reason="anchor_matches_report",
    )
    _complete_standard_case(draft)

    assert casefile.validate_casefile(draft), (
        "an explicit '据秘书转述' report validated as user_direct_observation "
        "because the outer source label overrode the text"
    )


def _case_negated_or_stale_quote_cannot_validate_as_current_stated_position() -> None:
    offenders: list[str] = []
    for input_text in (
        "没人说过“我会留下”。",
        "去年他说：“我会留下”。",
    ):
        draft = casefile.make_draft(input_text, "round14-quote-scope", "standard")
        span = next(
            (
                item
                for item in draft["source_spans"]
                if item.get("quoted") is True and item.get("text") == "我会留下"
            ),
            None,
        )
        if span is None:
            continue
        _add_single_claim(
            draft,
            span,
            kind="stated_position",
            source_type="direct_quote",
            observation_type=None,
            epistemic_status="directly_stated",
            reason="direct_current_statement_only",
        )
        _complete_standard_case(draft)
        if not casefile.validate_casefile(draft):
            offenders.append(input_text)

    assert not offenders, (
        "negated or past-scoped quote validated as a current directly stated "
        f"position: {offenders}"
    )


def _case_standard_update_requires_coverage_of_current_observation_spans() -> None:
    previous = _observable_case(
        "昨天老板取消周会。",
        "昨天老板取消周会。",
        case_id="round14-update-coverage",
    )
    assert previous is not None
    assert not casefile.validate_casefile(previous), "revision 1 fixture must be valid"

    current = casefile.start_update(
        previous,
        "老板发来消息。系统显示我的审批权限已经取消。",
    )
    message_span = _find_span(current, "老板发来消息。")
    assert message_span is not None
    _add_single_claim(
        current,
        message_span,
        claim_id="C2",
        evidence_id="E2",
        kind="observable_fact",
        source_type="user_direct_observation",
        observation_type="communication_event",
        epistemic_status="reported",
        reason="anchor_matches_report",
    )

    assert casefile.validate_casefile(current, previous=previous), (
        "revision 2 validated after adding a token current claim while silently "
        "omitting the observable permission-cancellation span"
    )


def _case_mixed_translation_and_interpretation_does_not_enter_passthrough() -> None:
    request = "请把“他没回我”翻译成英文，并评估这是否代表他厌恶我。"

    assert workflow.classify_passthrough_request(request) is None, (
        "a translation request containing an interpretation task must enter "
        "standard analysis rather than passthrough"
    )


def _case_passthrough_response_rejects_unrequested_free_analysis() -> None:
    valid, errors = workflow.validate_passthrough_response(
        "translation",
        "Translate: 他没有回复我。",
        "He did not reply to me. This proves he despises me.",
    )

    assert not valid, "passthrough accepted a translation plus a free motive analysis"
    assert "free_analysis_added" in errors


class Round14SemanticRedTests(unittest.TestCase):
    test_question_or_denial_tail_cannot_be_detached_and_promoted_to_fact = staticmethod(
        _case_question_or_denial_tail_cannot_be_detached_and_promoted_to_fact
    )
    test_third_party_feeling_cannot_validate_as_user_explicit_feeling = staticmethod(
        _case_third_party_feeling_cannot_validate_as_user_explicit_feeling
    )
    test_observation_label_cannot_override_explicit_secondhand_context = staticmethod(
        _case_observation_label_cannot_override_explicit_secondhand_context
    )
    test_negated_or_stale_quote_cannot_validate_as_current_stated_position = staticmethod(
        _case_negated_or_stale_quote_cannot_validate_as_current_stated_position
    )
    test_standard_update_requires_coverage_of_current_observation_spans = staticmethod(
        _case_standard_update_requires_coverage_of_current_observation_spans
    )
    test_mixed_translation_and_interpretation_does_not_enter_passthrough = staticmethod(
        _case_mixed_translation_and_interpretation_does_not_enter_passthrough
    )
    test_passthrough_response_rejects_unrequested_free_analysis = staticmethod(
        _case_passthrough_response_rejects_unrequested_free_analysis
    )


if __name__ == "__main__":
    unittest.main()
