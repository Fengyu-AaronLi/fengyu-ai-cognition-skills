from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


ClaimSpec = tuple[str, str, str, str | None]


class Round115ProvenanceBlindRedTests(unittest.TestCase):
    """Black-box semantic regressions through make_draft/validate_casefile."""

    FACT_SPEC: ClaimSpec = (
        "我今天收到邮件。",
        "observable_fact",
        "user_direct_observation",
        "communication_event",
    )

    def _exact_span(
        self, draft: dict[str, Any], exact_quote: str
    ) -> dict[str, Any]:
        matches = [
            span
            for span in draft["source_spans"]
            if span["text"] == exact_quote
        ]
        self.assertEqual(
            1,
            len(matches),
            f"expected one public source span for {exact_quote!r}: "
            f"{[(item['text'], item['source_label']) for item in draft['source_spans']]}",
        )
        return matches[0]

    def _optional_exact_span(
        self, draft: dict[str, Any], exact_quote: str
    ) -> dict[str, Any] | None:
        matches = [
            span
            for span in draft["source_spans"]
            if span["text"] == exact_quote
        ]
        self.assertLessEqual(len(matches), 1)
        return matches[0] if matches else None

    def _add_claim(
        self,
        draft: dict[str, Any],
        span: dict[str, Any],
        kind: str,
        source_type: str,
        observation_type: str | None,
    ) -> None:
        position = len(draft["claims"]) + 1
        claim_id = f"C{position}"
        evidence_id = f"E{position}"
        direct = kind in {
            "observable_fact",
            "explicit_feeling",
            "stated_position",
        }
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
                "epistemic_status": (
                    "reported"
                    if kind in {"observable_fact", "explicit_feeling"}
                    else "directly_stated"
                    if kind == "stated_position"
                    else "unverified"
                ),
                "diagnostic_boundary": kind == "identity_claim",
            }
        )
        limitations = (
            ["secondhand", "missing_context"]
            if source_type == "secondhand"
            else ["single_party_report"]
        )
        draft["evidence"].append(
            {
                "id": evidence_id,
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": source_type,
                "exact_quote": span["text"],
                "can_establish": [claim_id] if direct else [],
                "cannot_establish": [] if direct else [claim_id],
                "limitations": limitations,
            }
        )
        draft["evidence_links"].append(
            {
                "proposition_id": claim_id,
                "evidence_ref": evidence_id,
                "relation": "supports" if direct else "does_not_establish",
                "strength": "direct" if direct else "none",
                "reason": (
                    "anchor_matches_report" if direct else "source_scope_limit"
                ),
            }
        )

    def _finish_standard(self, draft: dict[str, Any]) -> dict[str, Any]:
        draft["unknowns"] = [
            {
                "id": "U1",
                "unknown_type": "future_behavior_or_outcome",
                "text": "后续行为或结果是否会按当前推断发生",
                "status": "open",
                "resolved_by_evidence_refs": [],
            }
        ]
        draft["actions"] = [
            {
                "id": "A1",
                "action_type": "record_pattern",
                "text": "记录后续发生的具体行为、时间和结果",
                "timing": "next",
                "risk": "low",
                "reversible": True,
                "motive_independent": True,
                "produces_new_evidence": True,
            }
        ]
        draft["user_decisions"] = ["evidence_threshold"]
        return draft

    def _artifact(
        self, text: str, specs: list[ClaimSpec]
    ) -> dict[str, Any]:
        draft = casefile.make_draft(text, "round115-provenance-blind", "standard")
        for exact_quote, kind, source_type, observation_type in specs:
            self._add_claim(
                draft,
                self._exact_span(draft, exact_quote),
                kind,
                source_type,
                observation_type,
            )
        return self._finish_standard(draft)

    def test_conditional_consequent_cannot_escape_report_scope(self) -> None:
        cases = [
            (
                "如果同事说老板会开掉我，我注定会失败。我今天收到邮件。",
                "我注定会失败。",
            ),
            (
                "假如朋友表示公司会撤掉我，我永远不会成功。我今天收到邮件。",
                "我永远不会成功。",
            ),
        ]
        for text, consequent in cases:
            with self.subTest(text=text):
                corrected = self._artifact(text, [self.FACT_SPEC])
                self.assertEqual([], casefile.validate_casefile(corrected))

                bad = self._artifact(
                    text,
                    [
                        (consequent, "prediction", "secondhand", None),
                        self.FACT_SPEC,
                    ],
                )
                self.assertTrue(
                    casefile.validate_casefile(bad),
                    "a comma-split consequent governed by 如果/假如 is not an "
                    "asserted prediction and must not validate as secondhand",
                )

    def test_bare_first_person_prediction_resets_hearsay_ownership(self) -> None:
        cases = [
            (
                "同事说老板会开掉我，但我注定会失败。",
                "同事说老板会开掉我。我注定会失败。",
                "我注定会失败。",
            ),
            (
                "秘书转述公司会撤掉我，然而我永远不会成功。",
                "秘书转述公司会撤掉我。我永远不会成功。",
                "我永远不会成功。",
            ),
        ]
        for bad_text, corrected_text, prediction in cases:
            with self.subTest(text=bad_text):
                corrected = self._artifact(
                    corrected_text,
                    [(prediction, "prediction", "user_report", None)],
                )
                self.assertEqual([], casefile.validate_casefile(corrected))

                bad = self._artifact(
                    bad_text,
                    [(prediction, "prediction", "secondhand", None)],
                )
                self.assertTrue(
                    casefile.validate_casefile(bad),
                    "a new first-person conclusion after a contrast owns its "
                    "provenance and cannot inherit the preceding speaker",
                )

    def test_temporal_first_person_feeling_resets_hearsay_ownership(self) -> None:
        cases = [
            (
                "同事说老板会开掉我，但我现在很害怕。我今天收到邮件。",
                "同事说老板会开掉我。我现在很害怕。我今天收到邮件。",
                "我现在很害怕。",
            ),
            (
                "朋友表示公司会撤掉我，然而我此刻很焦虑。我今天收到邮件。",
                "朋友表示公司会撤掉我。我此刻很焦虑。我今天收到邮件。",
                "我此刻很焦虑。",
            ),
        ]
        for bad_text, corrected_text, feeling in cases:
            with self.subTest(text=bad_text):
                corrected = self._artifact(
                    corrected_text,
                    [
                        (feeling, "explicit_feeling", "explicit_self_report", None),
                        self.FACT_SPEC,
                    ],
                )
                self.assertEqual([], casefile.validate_casefile(corrected))

                bad = self._artifact(bad_text, [self.FACT_SPEC])
                self.assertTrue(
                    casefile.validate_casefile(bad),
                    "现在/此刻 does not turn the user's named feeling into "
                    "secondhand material that may be silently omitted",
                )

    def test_positive_quote_after_negated_quote_cannot_be_swallowed(self) -> None:
        cases = [
            (
                "他没有说“我会离开”，而是说“我会留下”。我今天收到邮件。",
                "他没有说“我会离开”。他说“我会留下”。我今天收到邮件。",
                "我会留下",
            ),
            (
                "她没表示“我不会参加活动”，而是说“我会参加活动”。我今天收到邮件。",
                "她没表示“我不会参加活动”。她说“我会参加活动”。我今天收到邮件。",
                "我会参加活动",
            ),
        ]
        for bad_text, corrected_text, positive_quote in cases:
            with self.subTest(text=bad_text):
                corrected = self._artifact(
                    corrected_text,
                    [
                        (
                            positive_quote,
                            "stated_position",
                            "direct_quote",
                            None,
                        ),
                        self.FACT_SPEC,
                    ],
                )
                self.assertEqual([], casefile.validate_casefile(corrected))

                bad = self._artifact(bad_text, [self.FACT_SPEC])
                self.assertTrue(
                    casefile.validate_casefile(bad),
                    "而是 opens an affirmative corrective quote; the earlier "
                    "negation cannot suppress that current stated position",
                )

    def test_explicit_feeling_cannot_hide_coordinated_prediction(self) -> None:
        cases = [
            (
                "我很焦虑并且我永远不会成功。",
                "我很焦虑。我永远不会成功。",
                "我很焦虑。",
                "我永远不会成功。",
            ),
            (
                "我很失望而且我绝不会再被重用。",
                "我很失望。我绝不会再被重用。",
                "我很失望。",
                "我绝不会再被重用。",
            ),
        ]
        for bad_text, corrected_text, feeling, prediction in cases:
            with self.subTest(text=bad_text):
                corrected = self._artifact(
                    corrected_text,
                    [
                        (
                            feeling,
                            "explicit_feeling",
                            "explicit_self_report",
                            None,
                        ),
                        (prediction, "prediction", "user_report", None),
                    ],
                )
                self.assertEqual([], casefile.validate_casefile(corrected))

                draft = casefile.make_draft(
                    bad_text, "round115-provenance-blind", "standard"
                )
                composite = self._optional_exact_span(draft, bad_text)
                if composite is None:
                    # A future implementation may fix this by splitting the
                    # coordinated layers before validation.
                    continue
                self._add_claim(
                    draft,
                    composite,
                    "explicit_feeling",
                    "explicit_self_report",
                    None,
                )
                bad = self._finish_standard(draft)
                self.assertTrue(
                    casefile.validate_casefile(bad),
                    "an explicit feeling claim cannot satisfy coverage for an "
                    "independently asserted coordinated future prediction",
                )


if __name__ == "__main__":
    unittest.main()
