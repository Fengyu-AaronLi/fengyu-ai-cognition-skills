from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


def artifact_with_unverified_material() -> dict:
    text = (
        "[C｜截图] 老板连续两次没让我参加会议。\n"
        "[我的判断] 我认为他在架空我。"
    )
    draft = casefile.make_draft(text, "round35-artifact-limit", "standard")
    fact_span = next(
        span
        for span in draft["source_spans"]
        if span["source_ref"] == "C" and "没让我参加会议" in span["text"]
    )
    story_span = next(
        span
        for span in draft["source_spans"]
        if "我认为他在架空我" in span["text"]
    )
    draft["claims"] = [
        {
            "id": "C1",
            "kind": "observable_fact",
            "observation_type": casefile.derive_observation_type(
                fact_span["text"], fact_span
            ),
            "text": fact_span["text"],
            "input_id": fact_span["input_id"],
            "source_span_id": fact_span["id"],
            "source_ref": fact_span["source_ref"],
            "source_type": "unverified_artifact",
            "exact_quote": fact_span["text"],
            "epistemic_status": "reported",
            "diagnostic_boundary": False,
        },
        {
            "id": "C2",
            "kind": "interpretation",
            "text": story_span["text"],
            "input_id": story_span["input_id"],
            "source_span_id": story_span["id"],
            "source_ref": story_span["source_ref"],
            "source_type": "user_report",
            "exact_quote": story_span["text"],
            "epistemic_status": "unverified",
            "diagnostic_boundary": False,
        },
    ]
    draft["evidence"] = [
        {
            "id": "E1",
            "input_id": fact_span["input_id"],
            "source_span_id": fact_span["id"],
            "source_ref": fact_span["source_ref"],
            "source_type": "unverified_artifact",
            "exact_quote": fact_span["text"],
            "can_establish": ["C1"],
            "cannot_establish": ["C2"],
            "limitations": ["artifact_not_verified", "missing_context"],
        }
    ]
    draft["evidence_links"] = [
        {
            "proposition_id": "C1",
            "evidence_ref": "E1",
            "relation": "supports",
            "strength": "direct",
            "reason": "anchor_matches_report",
        },
        {
            "proposition_id": "C2",
            "evidence_ref": "E1",
            "relation": "does_not_establish",
            "strength": "none",
            "reason": "artifact_scope_limited",
        },
    ]
    draft["unknowns"] = [
        {
            "id": "U1",
            "unknown_type": "source_provenance_or_context",
            "text": casefile.UNKNOWN_CATALOG["source_provenance_or_context"],
            "status": "open",
            "resolved_by_evidence_refs": [],
        }
    ]
    action = dict(casefile.ACTION_CATALOG["neutral_check"])
    action.pop("modes")
    draft["actions"] = [
        {"id": "A1", "action_type": "neutral_check", **action}
    ]
    draft["user_decisions"] = ["employment_continuation"]
    return draft


class Round35HumanEvidenceLimitsRedTests(unittest.TestCase):
    def test_human_response_translates_material_source_limitations(self) -> None:
        artifact = artifact_with_unverified_material()
        self.assertEqual([], casefile.validate_casefile(artifact))

        response = casefile.render_markdown(artifact)
        self.assertIn("材料真实性尚未核验", response)
        self.assertIn("材料上下文不完整", response)
        for internal_code in (
            "artifact_not_verified",
            "missing_context",
            "unverified_artifact",
        ):
            with self.subTest(internal_code=internal_code):
                self.assertNotIn(internal_code, response)


if __name__ == "__main__":
    unittest.main()
