from __future__ import annotations

from datetime import datetime
import sys
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
from test_round19_semantic_lifecycle_red import (  # noqa: E402
    _append_stated_position,
    _span,
    _standard_shell,
)


class Round25SemanticBindingRedTests(unittest.TestCase):
    def test_cross_sentence_postfix_hearsay_binds_to_preceding_quote(self) -> None:
        text = "老板说：“我决定离开。”。这句话是同事转述给我的。"
        draft = casefile.make_draft(text, "round25-postfix-quote", "standard")
        span = _span(draft, "我决定离开。")
        self.assertEqual(
            "secondhand", casefile._expected_source_type_for_span(span)
        )
        scope_error = casefile._direct_quote_scope_error(text, span)
        self.assertIsNotNone(scope_error)
        self.assertEqual("DIRECT_QUOTE_NOT_ASSERTED", scope_error[0])
        self.assertNotEqual(
            "stated_position",
            casefile.derive_claim_kind_for_span(span["text"], span, text),
        )

        control = "老板说：“我决定离开。”。随后同事转述了另一段安排。"
        control_draft = casefile.make_draft(
            control, "round25-postfix-control", "standard"
        )
        control_span = _span(control_draft, "我决定离开。")
        self.assertNotEqual(
            "secondhand",
            casefile._expected_source_type_for_span(control_span),
        )

    def test_role_evidence_fails_closed_across_speaker_polarity_time_and_entity(self) -> None:
        base_claim = {
            "kind": "interpretation",
            "source_ref": "P1",
            "exact_quote": "我认为自己被架空。",
        }
        past_year = str(
            datetime.now().astimezone().date().year - 1
        ).translate(str.maketrans("0123456789", "０１２３４５６７８９"))
        cases: tuple[dict[str, Any], dict[str, Any]] = (
            (
                base_claim,
                {
                    "source_ref": "E1",
                    "source_type": "direct_quote",
                    "source_label": "老板原话",
                    "exact_quote": "我的职责和审批权限保持不变。",
                },
            ),
            (
                base_claim,
                {
                    "source_ref": "E1",
                    "source_type": "user_direct_observation",
                    "exact_quote": "我的职责和审批权限并非保持不变。",
                },
            ),
            (
                base_claim,
                {
                    "source_ref": "E1",
                    "source_type": "user_direct_observation",
                    "exact_quote": f"{past_year}年我的职责和审批权限保持不变。",
                },
            ),
            (
                {
                    "kind": "interpretation",
                    "source_ref": "P1",
                    "exact_quote": "我认为乙公司在架空我。",
                },
                {
                    "source_ref": "E1",
                    "source_type": "user_direct_observation",
                    "exact_quote": "甲公司的系统今天仍允许我审批项目支出。",
                },
            ),
        )
        for claim, evidence in cases:
            with self.subTest(evidence=evidence["exact_quote"]):
                self.assertEqual(
                    {"does_not_establish"},
                    casefile._allowed_relation_for_claim_evidence(
                        claim, evidence
                    ),
                )

    def test_explicit_today_date_is_current_not_historical(self) -> None:
        today = datetime.now().astimezone().date()
        date_text = f"{today.year}年{today.month}月{today.day}日"
        text = f"今天（{date_text}）老板说：“我决定离开。”。"
        draft = casefile.make_draft(text, "round25-today", "standard")
        span = _span(draft, "我决定离开。")
        self.assertFalse(casefile._direct_quote_has_past_scope(text, span))
        self.assertEqual(
            "stated_position",
            casefile.derive_claim_kind_for_span(span["text"], span, text),
        )

    def test_supersession_keeps_organizational_unit_in_speaker_identity(self) -> None:
        previous = _standard_shell(
            "第一事业部老板说：“我会留下”。",
            "round25-division-speaker",
        )
        _append_stated_position(previous, "我会留下", "C1", "E1")
        self.assertEqual([], casefile.validate_casefile(previous))

        current = casefile.start_update(
            previous,
            "第二事业部老板明确改口，从“我会留下”改为“我会离开”。",
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
        codes = {
            item["code"]
            for item in casefile.validate_casefile(current, previous=previous)
        }
        self.assertIn("SUPERSESSION_NOT_EXPLICIT", codes)

    def test_renderer_keeps_epistemic_categories_and_quote_context_visible(self) -> None:
        text = "老板今天说：“我决定离开。”。"
        spans = casefile.generate_source_spans("I1", text)
        quote_span = next(item for item in spans if item["text"] == "我决定离开。")
        data = {
            "mode": "standard",
            "inputs": [{"id": "I1", "text": text}],
            "source_spans": spans,
            "claims": [
                {
                    "id": "C1",
                    "kind": "observable_fact",
                    "exact_quote": "消息六个小时没有回复。",
                    "source_ref": "F1",
                    "source_type": "user_report",
                    "epistemic_status": "reported",
                },
                {
                    "id": "C2",
                    "kind": "stated_position",
                    "exact_quote": "我决定离开。",
                    "input_id": "I1",
                    "source_span_id": quote_span["id"],
                    "source_ref": "Q1",
                    "source_type": "direct_quote",
                    "epistemic_status": "directly_stated",
                },
                {
                    "id": "C3",
                    "kind": "interpretation",
                    "exact_quote": "他在排挤我。",
                    "source_ref": "P1",
                    "source_type": "user_report",
                    "epistemic_status": "unverified",
                },
                {
                    "id": "C4",
                    "kind": "identity_claim",
                    "exact_quote": "我就是个失败者。",
                    "source_ref": "P2",
                    "source_type": "user_report",
                    "epistemic_status": "unverified",
                },
                {
                    "id": "C5",
                    "kind": "prediction",
                    "exact_quote": "我永远做不成事。",
                    "source_ref": "P3",
                    "source_type": "user_report",
                    "epistemic_status": "unverified",
                },
            ],
            "evidence": [],
            "evidence_links": [],
            "unknowns": [],
            "hypotheses": [],
            "actions": [],
            "user_decisions": [],
        }
        rendered = casefile.render_markdown(data)
        fact_section = rendered.split(
            "## 1A. 相关人员的直接表态", maxsplit=1
        )[0]
        self.assertIn("消息六个小时没有回复", fact_section)
        self.assertNotIn("我决定离开", fact_section)
        self.assertIn("## 1A. 相关人员的直接表态", rendered)
        position_section = rendered.split(
            "## 1A. 相关人员的直接表态", maxsplit=1
        )[1].split("## 2.", maxsplit=1)[0]
        self.assertIn("老板今天说", position_section)
        self.assertIn("只证明这句话被直接表述", position_section)
        self.assertIn("[事件解释]", rendered)
        self.assertIn("[身份定性]", rendered)
        self.assertIn("[未来预测]", rendered)


if __name__ == "__main__":
    unittest.main()
