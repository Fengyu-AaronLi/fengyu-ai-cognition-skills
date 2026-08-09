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
from test_round37_semantic_truthfulness_red import _append_fact  # noqa: E402


def first_story(case_id: str) -> dict:
    draft = _standard_shell("我认为他在架空我。", case_id)
    _append_story(draft, "我认为他在架空我。", "interpretation")
    if casefile.validate_casefile(draft):
        raise AssertionError(casefile.validate_casefile(draft))
    return draft


def add_retraction_transition(second: dict) -> None:
    span = next(
        item
        for item in second["source_spans"]
        if item["input_id"] == second["current_input_id"]
        and (
            "不是我的判断" in item["text"]
            or "我撤回" in item["text"]
            or "我收回" in item["text"]
            or "我不再认为" in item["text"]
        )
    )
    second["claims"][0]["epistemic_status"] = "retracted"
    second["evidence"].append(
        {
            "id": "E3",
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "user_report",
            "exact_quote": span["text"],
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


def anchored_explicit_feeling_case(text: str, case_id: str) -> dict:
    draft = _standard_shell(text, case_id)
    span = next(
        item
        for item in draft["source_spans"]
        if item["input_id"] == draft["current_input_id"]
        and any(marker in item["text"] for marker in ("难过", "焦虑", "失望"))
    )
    quote = span["text"]
    draft["claims"].append(
        {
            "id": "C1",
            "kind": "explicit_feeling",
            "text": quote,
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "explicit_self_report",
            "exact_quote": quote,
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
            "exact_quote": quote,
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


class Round39SemanticScopeRedTests(unittest.TestCase):
    def test_third_party_disavowal_cannot_retract_the_users_story(self) -> None:
        first = first_story("round39-third-party-retraction")
        second = casefile.start_update(
            first,
            "他声称上一轮的解释不是我的判断。老板今天取消了会议。",
        )
        _append_fact(second, "老板今天取消了会议。", "C2", "E2")
        unchanged_codes = {
            item["code"] for item in casefile.validate_casefile(second, previous=first)
        }
        self.assertNotIn("RETRACTED_STORY_STATUS_NOT_UPDATED", unchanged_codes)

        add_retraction_transition(second)
        changed_codes = {
            item["code"] for item in casefile.validate_casefile(second, previous=first)
        }
        self.assertIn("RETRACTION_NOT_EXPLICIT", changed_codes)

    def test_common_first_person_retractions_enter_the_lifecycle(self) -> None:
        texts = (
            "我撤回“他在架空我”这个判断。老板今天取消了会议。",
            "我不再认为他在架空我。老板今天取消了会议。",
            "我收回之前关于架空的判断。老板今天取消了会议。",
        )
        for index, text in enumerate(texts, start=1):
            with self.subTest(text=text):
                first = first_story(f"round39-first-party-retraction-{index}")
                second = casefile.start_update(first, text)
                _append_fact(second, "老板今天取消了会议。", "C2", "E2")
                codes = {
                    item["code"]
                    for item in casefile.validate_casefile(second, previous=first)
                }
                self.assertIn("RETRACTED_STORY_STATUS_NOT_UPDATED", codes)
                self.assertNotIn("USER_STORY_CLAIM_MISSING", codes)

    def test_nested_other_person_feelings_are_not_users_feelings(self) -> None:
        texts = (
            "我对他说她很难过。",
            "我因为女儿很难过所以请假。",
            "我对她的难过表示理解。",
        )
        for index, text in enumerate(texts, start=1):
            with self.subTest(text=text):
                self.assertFalse(casefile.is_explicit_feeling(text))
                draft = anchored_explicit_feeling_case(
                    text, f"round39-feeling-{index}"
                )
                self.assertIn(
                    "CLAIM_KIND_MISMATCH",
                    {item["code"] for item in casefile.validate_casefile(draft)},
                )

    def test_nonasserted_and_identity_surfaces_never_become_candidates(self) -> None:
        texts = (
            "我希望我亲眼看到他把杯子摔碎了。",
            "假如我亲眼看到他把杯子摔碎了。",
            "梦里我亲眼看到他把杯子摔碎了。",
            "梦中我亲眼看到他把杯子摔碎了。",
            "我估计他把杯子拿走了。",
            "我亲眼看到他是个控制狂。",
            "我亲眼看到他是个渣男。",
        )
        for index, text in enumerate(texts, start=1):
            with self.subTest(text=text):
                draft = casefile.make_draft(text, f"round39-candidate-{index}", "standard")
                self.assertEqual([], draft["unclassified_observation_candidates"])

    def test_nonhuman_text_sources_are_not_current_human_positions(self) -> None:
        texts = (
            "语音助手回答“我会留下”。",
            "客服自动回复说“我会留下”。",
            "海报写道“我会留下”。",
            "邮件写道“我会留下”。",
        )
        for index, text in enumerate(texts, start=1):
            with self.subTest(text=text):
                draft = _standard_shell(text, f"round39-nonhuman-{index}")
                _append_stated_position(draft, "我会留下", "C1", "E1")
                self.assertIn(
                    "DIRECT_QUOTE_PROVENANCE_UNKNOWN",
                    {item["code"] for item in casefile.validate_casefile(draft)},
                )

    def test_life_event_scoped_quotes_are_historical_not_current(self) -> None:
        for index, text in enumerate(
            ("他生前说“我会留下”。", "他临终前说“我会留下”。"),
            start=1,
        ):
            with self.subTest(text=text):
                draft = _standard_shell(text, f"round39-historical-{index}")
                _append_stated_position(draft, "我会留下", "C1", "E1")
                self.assertIn(
                    "DIRECT_QUOTE_NOT_CURRENT",
                    {item["code"] for item in casefile.validate_casefile(draft)},
                )

    def test_current_first_person_commitment_is_not_rejected(self) -> None:
        draft = _standard_shell(
            "我郑重承诺“我会留下”。", "round39-current-commitment"
        )
        _append_stated_position(draft, "我会留下", "C1", "E1")
        self.assertEqual([], casefile.validate_casefile(draft))


if __name__ == "__main__":
    unittest.main()
