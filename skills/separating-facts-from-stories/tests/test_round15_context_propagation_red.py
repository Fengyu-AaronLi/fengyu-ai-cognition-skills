from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import casefile  # noqa: E402
import workflow  # noqa: E402


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


def _span(draft: dict[str, Any], text: str) -> dict[str, Any]:
    return next(item for item in draft["source_spans"] if item["text"] == text)


def _append_observable(
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


class Round15ContextPropagationRedTests(unittest.TestCase):
    def test_truth_scope_survives_question_and_comma_segmentation(self) -> None:
        offenders: list[tuple[str, list[str]]] = []
        for text in (
            "老板取消了会议？",
            "老板取消了会议，不是真的。",
            "老板取消周会是谣言。",
            "老板取消周会未必是真的。",
            "老板取消周会据说是假的。",
        ):
            facts = [
                item["text"]
                for item in casefile.generate_source_spans("I1", text)
                if casefile.derive_observation_type(item["text"], item) is not None
            ]
            if facts:
                offenders.append((text, facts))
        self.assertEqual([], offenders)

    def test_pronoun_report_scope_propagates_to_unquoted_spans(self) -> None:
        for text, target in (
            ("他说，系统显示我的权限取消。", "系统显示我的权限取消。"),
            ("他说，我很害怕。", "我很害怕。"),
        ):
            with self.subTest(text=text):
                span = next(
                    item
                    for item in casefile.generate_source_spans("I1", text)
                    if item["text"] == target
                )
                self.assertEqual(
                    "secondhand", casefile._expected_source_type_for_span(span)
                )

    def test_post_quote_past_scope_blocks_current_position(self) -> None:
        for text in (
            "他说：“我会留下”，那是去年。",
            "他说：“我会留下”。这是他去年说的。",
        ):
            with self.subTest(text=text):
                quote = next(
                    item
                    for item in casefile.generate_source_spans("I1", text)
                    if item.get("quoted") is True and item["text"] == "我会留下"
                )
                self.assertTrue(casefile._direct_quote_has_past_scope(text, quote))

    def test_labelled_interpretation_rejects_cross_entity_evidence(self) -> None:
        allowed = casefile._allowed_relation_for_claim_evidence(
            {
                "kind": "interpretation",
                "source_ref": "P1",
                "exact_quote": "我觉得老板在架空我。",
            },
            {
                "source_ref": "E1",
                "exact_quote": "另一家公司权限取消。",
            },
        )
        self.assertEqual({"does_not_establish"}, allowed)

    def test_update_observation_requires_observable_fact_kind(self) -> None:
        previous = _standard_shell("老板取消了会议。", "round15-update-kind")
        first_span = _span(previous, "老板取消了会议。")
        _append_observable(previous, first_span, "C1", "E1")
        self.assertEqual([], casefile.validate_casefile(previous))

        current = casefile.start_update(previous, "老板取消了项目会。")
        current_span = next(
            item
            for item in current["source_spans"]
            if item["input_id"] == current["current_input_id"]
            and casefile.derive_observation_type(item["text"], item) is not None
        )
        current["claims"].append(
            {
                "id": "C2",
                "kind": "interpretation",
                "text": current_span["text"],
                "input_id": current_span["input_id"],
                "source_span_id": current_span["id"],
                "source_ref": current_span["source_ref"],
                "source_type": "user_report",
                "exact_quote": current_span["text"],
                "epistemic_status": "unverified",
                "diagnostic_boundary": False,
            }
        )
        current["evidence"].append(
            {
                "id": "E2",
                "input_id": current_span["input_id"],
                "source_span_id": current_span["id"],
                "source_ref": current_span["source_ref"],
                "source_type": "user_report",
                "exact_quote": current_span["text"],
                "can_establish": [],
                "cannot_establish": ["C2"],
                "limitations": ["single_party_report"],
            }
        )
        current["evidence_links"].append(
            {
                "proposition_id": "C2",
                "evidence_ref": "E2",
                "relation": "does_not_establish",
                "strength": "none",
                "reason": "source_scope_limit",
            }
        )
        codes = {
            item["code"]
            for item in casefile.validate_casefile(current, previous=previous)
        }
        self.assertIn("CURRENT_OBSERVATION_CLAIM_MISSING", codes)

    def test_mixed_transform_variants_do_not_enter_passthrough(self) -> None:
        for text in (
            "请翻译“他没回”，再评价这意味着什么。",
            "Translate: he did not reply, and infer what it means.",
            "请翻译成英文：老板取消了会议。翻译后说明此举背后的心理。",
        ):
            with self.subTest(text=text):
                self.assertTrue(workflow.passthrough_has_mixed_intent(text))
                self.assertIsNone(workflow.classify_passthrough_request(text))

    def test_passthrough_rejects_directive_and_motive_expansion(self) -> None:
        request = "请翻译成英文：“老板取消了会议。”"
        for response in (
            "Quit your job immediately.",
            "He canceled it to humiliate you.",
        ):
            with self.subTest(response=response):
                valid, errors = workflow.validate_passthrough_response(
                    "translation", request, response
                )
                self.assertFalse(valid)
                self.assertIn("free_analysis_added", errors)

    def test_fiction_scope_has_structural_reality_reset(self) -> None:
        text = "上面是电影台词。可是现实里，他现在拿着刀站在我家门外。"
        self.assertIn(
            "explicit_threat", casefile.expected_safety_signal_types(text)
        )

    def test_transform_scope_ends_after_first_payload_quote(self) -> None:
        text = "请翻译“hello”，另外，他发消息说“今晚杀了你”。"
        self.assertIn(
            "explicit_threat", casefile.expected_safety_signal_types(text)
        )
        self.assertIsNone(workflow.classify_passthrough_request(text))

    def test_manual_type_cannot_duplicate_a_detected_type(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input.txt"
            workspace = root / "workspace"
            source.write_text("他发消息说今晚会杀了我。", encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(SKILL_DIR / "scripts" / "workflow.py"),
                    "start",
                    "--input",
                    str(source),
                    "--workspace",
                    str(workspace),
                    "--case-id",
                    "round15-overlap",
                    "--mode",
                    "safety",
                    "--safety-signal-type",
                    "explicit_threat",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, result.returncode)
            self.assertIn("MANUAL_SAFETY_TYPE_REDUNDANT", result.stderr)
            self.assertFalse(workspace.exists())

    def test_structured_sydney_location_gets_000(self) -> None:
        response = workflow.render_safety_response(
            {"medical_emergency"}, "所在地：悉尼。我胸痛。"
        )
        self.assertIn("000", response[:300])

    def test_resolved_history_variants_are_not_current_risk(self) -> None:
        for text in (
            "三年前我想轻生，如今已康复且安全。",
            "两年前我胸痛，现在医生说没事。",
        ):
            with self.subTest(text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))


if __name__ == "__main__":
    unittest.main()
