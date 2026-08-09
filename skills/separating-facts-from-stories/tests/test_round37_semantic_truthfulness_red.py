from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
from test_round19_semantic_lifecycle_red import (  # noqa: E402
    _append_stated_position,
    _append_story,
    _standard_shell,
)
from test_round33_candidate_lifecycle_red import (  # noqa: E402
    add_candidate_only_completion_fields,
)
from test_round35_human_evidence_limits_red import (  # noqa: E402
    artifact_with_unverified_material,
)


def _append_fact(
    draft: dict, quote: str, claim_id: str, evidence_id: str
) -> None:
    span = next(
        item
        for item in draft["source_spans"]
        if item["input_id"] == draft["current_input_id"]
        and item["text"] == quote
    )
    observation_type = casefile.derive_observation_type(quote, span)
    if observation_type is None:
        raise AssertionError(f"fixture is not a finite observation: {quote}")
    draft["claims"].append(
        {
            "id": claim_id,
            "kind": "observable_fact",
            "observation_type": observation_type,
            "text": quote,
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "user_direct_observation",
            "exact_quote": quote,
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
            "exact_quote": quote,
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


def _explicit_feeling_case(text: str, case_id: str) -> dict:
    draft = _standard_shell(text, case_id)
    span = next(
        item
        for item in draft["source_spans"]
        if item["input_id"] == draft["current_input_id"]
        and item["text"] == text
    )
    draft["claims"].append(
        {
            "id": "C1",
            "kind": "explicit_feeling",
            "text": text,
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "explicit_self_report",
            "exact_quote": text,
            "epistemic_status": "reported",
            "diagnostic_boundary": False,
        }
    )
    draft["evidence"].append(
        {
            "id": "E1",
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "explicit_self_report",
            "exact_quote": text,
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
    return draft


class Round37SemanticTruthfulnessRedTests(unittest.TestCase):
    def test_nonreal_uncertain_and_identity_text_never_becomes_candidate(self) -> None:
        texts = (
            "我梦到我亲眼看到他把杯子摔碎了。",
            "我想象我亲眼看到他把杯子摔碎了。",
            "我怀疑他昨天把杯子摔碎了。",
            "我亲眼看到他是个自私的人。",
        )
        for index, text in enumerate(texts, start=1):
            with self.subTest(text=text):
                draft = casefile.make_draft(text, f"round37-candidate-{index}", "standard")
                self.assertEqual([], draft["unclassified_observation_candidates"])

    def test_artifact_generated_and_historical_quotes_are_not_current_positions(self) -> None:
        cases = {
            "公告写道“我会留下”。": "DIRECT_QUOTE_PROVENANCE_UNKNOWN",
            "机器人回答“我会留下”。": "DIRECT_QUOTE_PROVENANCE_UNKNOWN",
            "他去世前说“我会留下”。": "DIRECT_QUOTE_NOT_CURRENT",
            "他离职前说“我会留下”。": "DIRECT_QUOTE_NOT_CURRENT",
            "他已经说过“我会留下”。": "DIRECT_QUOTE_NOT_CURRENT",
        }
        for index, (text, expected) in enumerate(cases.items(), start=1):
            with self.subTest(text=text):
                draft = _standard_shell(text, f"round37-quote-{index}")
                _append_stated_position(draft, "我会留下", "C1", "E1")
                codes = {
                    item["code"] for item in casefile.validate_casefile(draft)
                }
                self.assertIn(expected, codes)

    def test_common_prepositional_and_causal_feelings_are_preserved(self) -> None:
        for index, text in enumerate(
            (
                "我对他很失望。",
                "我为这件事感到难过。",
                "我因为这件事很焦虑。",
            ),
            start=1,
        ):
            with self.subTest(text=text):
                draft = _explicit_feeling_case(text, f"round37-feeling-{index}")
                self.assertEqual([], casefile.validate_casefile(draft))
                self.assertIn(text, casefile.render_markdown(draft))

    def test_unverified_artifact_requires_nonoptional_truth_limit(self) -> None:
        artifact = artifact_with_unverified_material()
        artifact["evidence"][0]["limitations"] = ["single_party_report"]
        codes = {
            item["code"] for item in casefile.validate_casefile(artifact)
        }
        self.assertIn("ARTIFACT_LIMITATION_REQUIRED", codes)

    def test_candidate_only_update_has_a_valid_completion_path(self) -> None:
        first = casefile.make_draft(
            "他昨天把杯子摔碎了。", "round37-candidate-update", "standard"
        )
        add_candidate_only_completion_fields(first)
        self.assertEqual([], casefile.validate_casefile(first))

        second = casefile.start_update(first, "他今天把杯子拿走了。")
        self.assertTrue(
            any(
                item["input_id"] == second["current_input_id"]
                for item in second["unclassified_observation_candidates"]
            )
        )
        self.assertEqual([], casefile.validate_casefile(second, previous=first))

    def test_retracted_story_must_leave_current_view_and_remain_auditable(self) -> None:
        first = _standard_shell(
            "我认为他在架空我。", "round37-retracted-story"
        )
        _append_story(first, "我认为他在架空我。", "interpretation")
        self.assertEqual([], casefile.validate_casefile(first))

        second = casefile.start_update(
            first,
            "上一轮关于架空的解释不是我的判断。老板今天取消了会议。",
        )
        _append_fact(second, "老板今天取消了会议。", "C2", "E2")
        unchanged_codes = {
            item["code"]
            for item in casefile.validate_casefile(second, previous=first)
        }
        self.assertIn("RETRACTED_STORY_STATUS_NOT_UPDATED", unchanged_codes)

        retraction_span = next(
            item
            for item in second["source_spans"]
            if item["input_id"] == second["current_input_id"]
            and "不是我的判断" in item["text"]
        )
        second["claims"][0]["epistemic_status"] = "retracted"
        second["evidence"].append(
            {
                "id": "E3",
                "input_id": retraction_span["input_id"],
                "source_span_id": retraction_span["id"],
                "source_ref": retraction_span["source_ref"],
                "source_type": "user_report",
                "exact_quote": retraction_span["text"],
                "can_establish": [],
                "cannot_establish": ["C1"],
                "limitations": ["single_party_report"],
            }
        )
        second["evidence_links"].append(
            {
                "proposition_id": "C1",
                "evidence_ref": "E3",
                "relation": "does_not_establish",
                "strength": "none",
                "reason": "source_scope_limit",
            }
        )
        second["change_log"] = [
            {
                "target_id": "C1",
                "from_status": "unverified",
                "to_status": "retracted",
                "reason_evidence_refs": ["E3"],
            }
        ]

        self.assertEqual([], casefile.validate_casefile(second, previous=first))
        response = casefile.render_markdown(second)
        current_section = response.split("## 3. 用户当前的解释", 1)[1].split(
            "## 4.", 1
        )[0]
        self.assertNotIn("我认为他在架空我", current_section)
        self.assertIn("已被用户明确撤回的历史解释", response)
        self.assertIn("我认为他在架空我", response)


if __name__ == "__main__":
    unittest.main()
