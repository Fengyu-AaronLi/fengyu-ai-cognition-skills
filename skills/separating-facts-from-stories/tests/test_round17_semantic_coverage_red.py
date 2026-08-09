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


def _append_observation(
    draft: dict[str, Any], span: dict[str, Any], claim_id: str, evidence_id: str
) -> None:
    observation_type = casefile.derive_observation_type(span["text"], span)
    assert observation_type is not None
    source_type = casefile._expected_source_type_for_span(span)
    if source_type is None:
        source_type = "user_direct_observation"
    draft["claims"].append(
        {
            "id": claim_id,
            "kind": "observable_fact",
            "observation_type": observation_type,
            "text": span["text"],
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": source_type,
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


def _first_observation(draft: dict[str, Any]) -> dict[str, Any]:
    return next(
        span
        for span in draft["source_spans"]
        if casefile.derive_observation_type(span["text"], span) is not None
        and casefile._expected_source_type_for_span(span) != "secondhand"
    )


class Round17SemanticCoverageRedTests(unittest.TestCase):
    def test_truth_status_compositions_do_not_leak_positive_facts(self) -> None:
        offenders: list[tuple[str, list[str]]] = []
        for text in (
            "老板取消会议不是事实。",
            "老板取消会议并非真的。",
            "老板取消会议是假新闻。",
            "老板取消会议恐怕是假的。",
            "老板取消会议传闻不实。",
            "老板取消会议大概没发生。",
            "老板取消会议据称没有发生。",
        ):
            facts = [
                span["text"]
                for span in casefile.generate_source_spans("I1", text)
                if casefile.derive_observation_type(span["text"], span)
                is not None
            ]
            if facts:
                offenders.append((text, facts))
        self.assertEqual([], offenders)

    def test_initial_case_cannot_omit_the_users_story(self) -> None:
        draft = _standard_shell(
            "他看了消息六个小时没回。他肯定不爱我。",
            "round17-story-coverage",
        )
        _append_observation(draft, _first_observation(draft), "C1", "E1")
        codes = {item["code"] for item in casefile.validate_casefile(draft)}
        self.assertIn("USER_STORY_CLAIM_MISSING", codes)

    def test_initial_case_cannot_omit_an_explicit_feeling(self) -> None:
        draft = _standard_shell(
            "我很害怕。老板取消了会议。", "round17-feeling-coverage"
        )
        _append_observation(draft, _first_observation(draft), "C1", "E1")
        codes = {item["code"] for item in casefile.validate_casefile(draft)}
        self.assertIn("EXPLICIT_FEELING_CLAIM_MISSING", codes)

    def test_initial_case_cannot_hide_a_second_observation(self) -> None:
        draft = _standard_shell(
            "老板取消了会议。老板删除了文档。", "round17-fact-coverage"
        )
        _append_observation(draft, _first_observation(draft), "C1", "E1")
        codes = {item["code"] for item in casefile.validate_casefile(draft)}
        self.assertIn("OBSERVABLE_FACT_CLAIM_MISSING", codes)

    def test_analysis_request_is_not_misclassified_as_a_user_story(self) -> None:
        draft = _standard_shell(
            "老板取消了会议。帮我分析他的真实动机。",
            "round17-request-exclusion",
        )
        _append_observation(draft, _first_observation(draft), "C1", "E1")
        self.assertEqual([], casefile.validate_casefile(draft))

    def test_labelled_role_evidence_must_be_self_scoped(self) -> None:
        claim = {
            "kind": "interpretation",
            "source_ref": "P1",
            "exact_quote": "公司已经决定架空我。",
        }
        unrelated = {
            "source_ref": "E1",
            "exact_quote": "上海团队的系统审批权限取消。",
        }
        self.assertEqual(
            {"does_not_establish"},
            casefile._allowed_relation_for_claim_evidence(claim, unrelated),
        )
        self.assertIn(
            "supports",
            casefile._allowed_relation_for_claim_evidence(
                claim,
                {
                    "source_ref": "E2",
                    "exact_quote": "我登录系统时发现审批权限取消。",
                },
            ),
        )


if __name__ == "__main__":
    unittest.main()
