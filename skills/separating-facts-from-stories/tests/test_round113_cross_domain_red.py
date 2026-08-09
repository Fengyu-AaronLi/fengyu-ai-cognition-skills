from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

from casefile import make_draft, validate_casefile  # noqa: E402


STORY_KINDS = {
    "interpretation",
    "motive_inference",
    "identity_claim",
    "prediction",
}

ACTION = {
    "id": "A1",
    "action_type": "record_pattern",
    "text": "记录后续发生的具体行为、时间和结果",
    "timing": "next",
    "risk": "low",
    "reversible": True,
    "motive_independent": True,
    "produces_new_evidence": True,
}

UNKNOWN = {
    "id": "U1",
    "unknown_type": "future_behavior_or_outcome",
    "text": "后续行为或结果是否会按当前推断发生",
    "status": "open",
    "resolved_by_evidence_refs": [],
}


def _claim_spec(
    exact_quote: str,
    kind: str,
    source_type: str,
) -> tuple[str, str, str]:
    return exact_quote, kind, source_type


def _authored_casefile(
    input_text: str,
    case_id: str,
    specs: tuple[tuple[str, str, str], ...],
) -> dict:
    """Author a minimal casefile using only the public runtime entrypoints."""
    data = make_draft(input_text, case_id, "auto")
    if data["mode"] != "standard":
        raise AssertionError(f"expected standard mode, got {data['mode']!r}")

    spans_by_text = {
        span["text"]: span
        for span in data["source_spans"]
    }
    for index, (exact_quote, kind, source_type) in enumerate(specs, 1):
        span = spans_by_text.get(exact_quote)
        if span is None:
            raise AssertionError(
                f"missing generated span {exact_quote!r} for {input_text!r}"
            )

        claim_id = f"C{index}"
        evidence_id = f"E{index}"
        direct = kind in {
            "observable_fact",
            "explicit_feeling",
            "stated_position",
        }
        if kind == "stated_position":
            epistemic_status = "directly_stated"
        elif kind in {"observable_fact", "explicit_feeling"}:
            epistemic_status = "reported"
        else:
            epistemic_status = "unverified"

        claim = {
            "id": claim_id,
            "kind": kind,
            "text": exact_quote,
            "input_id": "I1",
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": source_type,
            "exact_quote": exact_quote,
            "epistemic_status": epistemic_status,
            "diagnostic_boundary": kind == "identity_claim",
        }
        data["claims"].append(claim)

        if source_type == "secondhand":
            limitations = ["secondhand"]
        elif source_type == "unverified_artifact":
            limitations = ["artifact_not_verified"]
        else:
            limitations = ["single_party_report"]

        data["evidence"].append(
            {
                "id": evidence_id,
                "input_id": "I1",
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": source_type,
                "exact_quote": exact_quote,
                "can_establish": [claim_id] if direct else [],
                "cannot_establish": [] if direct else [claim_id],
                "limitations": limitations,
            }
        )
        data["evidence_links"].append(
            {
                "proposition_id": claim_id,
                "evidence_ref": evidence_id,
                "relation": "supports" if direct else "does_not_establish",
                "strength": "direct" if direct else "none",
                "reason": "anchor_matches_report" if direct else "source_scope_limit",
            }
        )

    data["unknowns"] = [copy.deepcopy(UNKNOWN)]
    data["actions"] = [copy.deepcopy(ACTION)]
    data["user_decisions"] = ["evidence_threshold"]
    return data


def _errors(data: dict) -> list[dict[str, str]]:
    return validate_casefile(data)


def _codes(errors: list[dict[str, str]]) -> set[str]:
    return {item["code"] for item in errors}


class Round113CrossDomainRedTests(unittest.TestCase):
    """RED tests for cross-domain assertion and provenance composition."""

    def _assert_bad_rejected_and_corrected_accepted(
        self,
        *,
        input_text: str,
        bad_specs: tuple[tuple[str, str, str], ...],
        corrected_specs: tuple[tuple[str, str, str], ...],
        expected_rejection_codes: set[str],
    ) -> None:
        bad = _authored_casefile(
            input_text,
            "round113-bad",
            bad_specs,
        )
        corrected = _authored_casefile(
            input_text,
            "round113-corrected",
            corrected_specs,
        )
        bad_errors = _errors(bad)
        corrected_errors = _errors(corrected)

        # RED witness: the current validator returns [] for each internally
        # self-consistent bad artifact below.  The assertion expresses the
        # desired contract so the test turns green only after production rejects it.
        self.assertTrue(
            _codes(bad_errors) & expected_rejection_codes,
            "RED: semantically wrong but internally self-consistent artifact "
            f"was accepted; bad_errors={bad_errors!r}; "
            f"corrected_errors={corrected_errors!r}",
        )
        self.assertEqual([], corrected_errors)

    def test_negation_and_coordination_reset_artifact_or_secondhand_owner(
        self,
    ) -> None:
        cases = (
            {
                "input": "不是截图显示老板讨厌我，而是我本人认为老板是在排挤我。",
                "bad": (
                    _claim_spec(
                        "不是截图显示老板讨厌我，",
                        "motive_inference",
                        "unverified_artifact",
                    ),
                    _claim_spec(
                        "而是我本人认为老板是在排挤我。",
                        "interpretation",
                        "unverified_artifact",
                    ),
                ),
                "corrected": (
                    _claim_spec(
                        "而是我本人认为老板是在排挤我。",
                        "interpretation",
                        "user_report",
                    ),
                ),
            },
            {
                "input": "同事说老板讨厌我，而且我本人认为老板是在排挤我。",
                "bad": (
                    _claim_spec(
                        "同事说老板讨厌我，",
                        "motive_inference",
                        "secondhand",
                    ),
                    _claim_spec(
                        "而且我本人认为老板是在排挤我。",
                        "interpretation",
                        "secondhand",
                    ),
                ),
                "corrected": (
                    _claim_spec(
                        "同事说老板讨厌我，",
                        "motive_inference",
                        "secondhand",
                    ),
                    _claim_spec(
                        "而且我本人认为老板是在排挤我。",
                        "interpretation",
                        "user_report",
                    ),
                ),
            },
            {
                "input": "截图显示老板不在乎我，而且我本人认为老板是在针对我。",
                "bad": (
                    _claim_spec(
                        "截图显示老板不在乎我，",
                        "motive_inference",
                        "unverified_artifact",
                    ),
                    _claim_spec(
                        "而且我本人认为老板是在针对我。",
                        "interpretation",
                        "unverified_artifact",
                    ),
                ),
                "corrected": (
                    _claim_spec(
                        "截图显示老板不在乎我，",
                        "motive_inference",
                        "unverified_artifact",
                    ),
                    _claim_spec(
                        "而且我本人认为老板是在针对我。",
                        "interpretation",
                        "user_report",
                    ),
                ),
            },
        )
        for case in cases:
            with self.subTest(input=case["input"]):
                self._assert_bad_rejected_and_corrected_accepted(
                    input_text=case["input"],
                    bad_specs=case["bad"],
                    corrected_specs=case["corrected"],
                    expected_rejection_codes={
                        "CLAIM_KIND_NOT_DERIVED",
                        "CLAIM_KIND_MISMATCH",
                        "SOURCE_TYPE_MISMATCH",
                    },
                )

    def test_nonfactive_attitudes_and_concessive_scopes_do_not_assert_stories(
        self,
    ) -> None:
        cases = (
            {
                "input": "我希望同事说老板讨厌我，但我本人认为老板是在排挤我。",
                "bad": (
                    _claim_spec(
                        "我希望同事说老板讨厌我，",
                        "motive_inference",
                        "secondhand",
                    ),
                    _claim_spec(
                        "我本人认为老板是在排挤我。",
                        "interpretation",
                        "user_report",
                    ),
                ),
                "corrected": (
                    _claim_spec(
                        "我本人认为老板是在排挤我。",
                        "interpretation",
                        "user_report",
                    ),
                ),
            },
            {
                "input": "即便同事说老板讨厌我，我很难过。",
                "bad": (
                    _claim_spec(
                        "即便同事说老板讨厌我，",
                        "motive_inference",
                        "secondhand",
                    ),
                ),
                "corrected": (
                    _claim_spec(
                        "我很难过。",
                        "explicit_feeling",
                        "explicit_self_report",
                    ),
                ),
            },
            {
                "input": "我希望截图显示老板讨厌我，但我本人认为老板是在惩罚我。",
                "bad": (
                    _claim_spec(
                        "我希望截图显示老板讨厌我，",
                        "motive_inference",
                        "unverified_artifact",
                    ),
                    _claim_spec(
                        "我本人认为老板是在惩罚我。",
                        "interpretation",
                        "user_report",
                    ),
                ),
                "corrected": (
                    _claim_spec(
                        "我本人认为老板是在惩罚我。",
                        "interpretation",
                        "user_report",
                    ),
                ),
            },
        )
        for case in cases:
            with self.subTest(input=case["input"]):
                self._assert_bad_rejected_and_corrected_accepted(
                    input_text=case["input"],
                    bad_specs=case["bad"],
                    corrected_specs=case["corrected"],
                    expected_rejection_codes={
                        "CLAIM_KIND_NOT_DERIVED",
                        "CLAIM_KIND_MISMATCH",
                        "EXPLICIT_FEELING_CLAIM_MISSING",
                    },
                )

    def test_format_and_proxy_carriers_do_not_inherit_future_quote_prediction(
        self,
    ) -> None:
        cases = (
            {
                "input": "请把同事说的“老板明天会取消会议”整理成项目符号，但我认为他在排挤我。",
                "carrier": "请把同事说的“老板明天会取消会议”整理成项目符号，",
                "story": "我认为他在排挤我。",
            },
            {
                "input": "我念出同事的原话：“老板明天会取消会议”，不过我本人认为老板是在排挤我。",
                "carrier": "我念出同事的原话：“老板明天会取消会议”，",
                "story": "我本人认为老板是在排挤我。",
            },
            {
                "input": "我播放朋友的录音：“老板明天会取消会议”，但我本人认为老板是在针对我。",
                "carrier": "我播放朋友的录音：“老板明天会取消会议”，",
                "story": "我本人认为老板是在针对我。",
            },
        )
        for case in cases:
            with self.subTest(input=case["input"]):
                bad_specs = (
                    _claim_spec(case["carrier"], "prediction", "user_report"),
                    _claim_spec(case["story"], "interpretation", "user_report"),
                )
                corrected_specs = (
                    _claim_spec(case["story"], "interpretation", "user_report"),
                )
                self._assert_bad_rejected_and_corrected_accepted(
                    input_text=case["input"],
                    bad_specs=bad_specs,
                    corrected_specs=corrected_specs,
                    expected_rejection_codes={
                        "CLAIM_KIND_NOT_DERIVED",
                        "CLAIM_KIND_MISMATCH",
                    },
                )


if __name__ == "__main__":
    unittest.main()
