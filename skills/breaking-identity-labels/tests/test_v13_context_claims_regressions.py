#!/usr/bin/env python3
"""V13 red tests for context-only identity and clinical claims.

The current-user ``labels`` ledger is not a general bag of every proposition
mentioned in a conversation.  Third-party, negated, and quoted propositions
must remain inspectable without being promoted into the current user's state.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
ANALYSIS_SCHEMA = ROOT / "schemas" / "analysis.schema.json"
CLOCK = "2026-08-07T03:00:00Z"

REQUIRED_CONTEXT_FIELDS = {
    "subject",
    "source",
    "evidence_status",
    "polarity",
    "claim",
}


def scaffold(text: str) -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(CLI), "scaffold", "--text", text, "--clock", CLOCK],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    case = json.loads(result.stdout)
    if case["evidence"][0]["text"] != text:
        raise AssertionError("E000 did not preserve the exact input")
    return case


def context_claim(
    test: unittest.TestCase,
    case: dict[str, Any],
    claim_fragment: str,
) -> dict[str, Any]:
    claims = case["analysis"].get("context_claims")
    test.assertIsInstance(
        claims,
        list,
        "analysis.context_claims must exist even when labels remain empty",
    )
    matches = [
        item
        for item in claims
        if isinstance(item, dict) and claim_fragment in str(item.get("claim", ""))
    ]
    test.assertEqual(
        1,
        len(matches),
        f"expected one context claim containing {claim_fragment!r}: {claims!r}",
    )
    item = matches[0]
    test.assertTrue(
        REQUIRED_CONTEXT_FIELDS.issubset(item),
        f"context claim is missing required fields: {item!r}",
    )
    return item


def assert_context_only(test: unittest.TestCase, case: dict[str, Any]) -> None:
    test.assertEqual([], case["analysis"]["labels"])
    test.assertFalse(case["risk_flags"]["safety"])
    test.assertNotIn(case["route"]["mode"], {"safety_support", "support_escalation"})
    experiment = case["analysis"]["experiment"]
    test.assertIn(experiment["status"], {"not_planned", "not_needed"})
    test.assertEqual("", experiment["target_claim"])
    test.assertEqual([], experiment["target_judgment_ids"])


class ContextClaimSchemaContractTests(unittest.TestCase):
    def test_analysis_schema_requires_a_context_claims_ledger(self) -> None:
        schema = json.loads(ANALYSIS_SCHEMA.read_text(encoding="utf-8"))
        self.assertIn("context_claims", schema["required"])
        context_schema = schema["properties"]["context_claims"]
        self.assertEqual("array", context_schema["type"])
        self.assertTrue(
            REQUIRED_CONTEXT_FIELDS.issubset(context_schema["items"]["required"])
        )


class ContextClaimExtractionTests(unittest.TestCase):
    def test_third_party_formal_diagnosis_is_preserved_without_becoming_the_user(self) -> None:
        case = scaffold("临床医生完整评估后诊断妹妹有边缘型人格障碍。")
        assert_context_only(self, case)
        item = context_claim(self, case, "边缘型人格障碍")
        self.assertEqual("third_party", item["subject"])
        self.assertEqual("reported_clinical_diagnosis", item["source"])
        self.assertEqual("user_reported_formal_diagnosis", item["evidence_status"])
        self.assertEqual("affirmed", item["polarity"])

    def test_third_party_formal_scales_keep_target_source_and_result(self) -> None:
        cases = (
            (
                "医院本周给我同事正式施测 PCL-5，听说分数是 41；这不是我的测评。",
                "PCL-5",
            ),
            (
                "我妹妹在医院正式做了成人 ADHD 量表；请别把结果算到我身上。",
                "成人 ADHD 量表",
            ),
        )
        for text, fragment in cases:
            with self.subTest(text=text):
                case = scaffold(text)
                assert_context_only(self, case)
                item = context_claim(self, case, fragment)
                self.assertEqual("third_party", item["subject"])
                self.assertEqual("formal_scale_result", item["source"])
                self.assertEqual("reported_scale_result", item["evidence_status"])
                self.assertEqual("affirmed", item["polarity"])

    def test_negated_diagnosis_and_scale_results_are_retained_as_negated_context(self) -> None:
        cases = (
            (
                "精神科医生明确说没有诊断我有 ADHD；我只是在记录这个否定事实。",
                "ADHD",
                "reported_clinical_diagnosis",
                "user_reported_formal_diagnosis",
            ),
            (
                "我没有做过正式 GAD-7 量表，也没有 16 分这个结果；这是对传闻的否定。",
                "GAD-7",
                "formal_scale_result",
                "reported_scale_result",
            ),
        )
        for text, fragment, source, evidence_status in cases:
            with self.subTest(text=text):
                case = scaffold(text)
                assert_context_only(self, case)
                item = context_claim(self, case, fragment)
                self.assertEqual("current_user", item["subject"])
                self.assertEqual(source, item["source"])
                self.assertEqual(evidence_status, item["evidence_status"])
                self.assertEqual("negated", item["polarity"])

    def test_quoted_clinical_and_identity_claims_remain_context_only(self) -> None:
        cases = (
            (
                "文章举例写道：‘精神科医生正式诊断我有 ADHD。’这是引文，不是我的诊断。",
                "ADHD",
            ),
            (
                "病历只引用我当时说的‘我是回避型’，这只是引文，不是医生诊断。",
                "回避型",
            ),
        )
        for text, fragment in cases:
            with self.subTest(text=text):
                case = scaffold(text)
                assert_context_only(self, case)
                item = context_claim(self, case, fragment)
                self.assertEqual("quoted_material", item["source"])
                self.assertEqual("reported_unverified", item["evidence_status"])
                self.assertIn(item["subject"], {"current_user", "unresolved"})
                self.assertIn(item["polarity"], {"affirmed", "negated"})

    def test_mixed_subjects_keep_only_the_current_users_diagnosis_in_labels(self) -> None:
        case = scaffold(
            "临床医生完整评估后诊断妹妹有边缘型人格障碍；"
            "精神科医生去年正式诊断我有 ADHD，我只是在记录两件事。"
        )
        labels = case["analysis"]["labels"]
        self.assertEqual(["ADHD"], [item["text"] for item in labels])
        self.assertTrue(
            all(
                item["attribution"]["target"]["role"] == "current_user"
                for item in labels
            )
        )
        item = context_claim(self, case, "边缘型人格障碍")
        self.assertEqual("third_party", item["subject"])
        self.assertFalse(case["risk_flags"]["safety"])
        self.assertIn(
            case["analysis"]["experiment"]["status"],
            {"not_planned", "not_needed"},
        )

    def test_current_user_formal_diagnosis_remains_a_label_positive_control(self) -> None:
        case = scaffold(
            "精神科医生去年正式诊断我有 ADHD，我只是把这个诊断告诉你。"
        )
        labels = case["analysis"]["labels"]
        self.assertEqual(["ADHD"], [item["text"] for item in labels])
        label = labels[0]
        self.assertEqual("reported_clinical_diagnosis", label["source_type"])
        self.assertEqual("user_reported_formal_diagnosis", label["evidence_status"])
        self.assertEqual(
            "current_user", label["attribution"]["target"]["role"]
        )
        self.assertEqual("affirmed", label["attribution"]["predicate"]["polarity"])
        self.assertFalse(case["risk_flags"]["safety"])
        self.assertEqual("not_needed", case["analysis"]["experiment"]["status"])


if __name__ == "__main__":
    unittest.main()
