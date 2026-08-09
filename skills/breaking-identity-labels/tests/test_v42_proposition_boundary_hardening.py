#!/usr/bin/env python3
"""V42 contracts: later questions and quoting must not rewrite earlier facts."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"


def scaffold(text: str, case_id: str) -> dict:
    result = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "scaffold",
            "--text",
            text,
            "--case-id",
            case_id,
            "--clock",
            "2026-08-06T00:00:00Z",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


class PropositionBoundaryHardeningTests(unittest.TestCase):
    def test_later_verdict_question_does_not_make_an_attributed_label_uncertain(self) -> None:
        case = scaffold(
            "同事在复盘里写我是“会议逃兵”，这是否证明我没有管理潜力？",
            "v42-attribution-question",
        )
        labels = {(item["text"], item["source_type"]) for item in case["analysis"]["labels"]}
        self.assertIn(("会议逃兵", "other_person_attribution"), labels)
        self.assertEqual("deconstruct", case["route"]["mode"])

    def test_personal_medical_record_remains_clinical_before_a_negated_implication(self) -> None:
        case = scaffold(
            "医院病历写明我被确诊为双相障碍；这不能推出我不适合管理。",
            "v42-clinical-negated-implication",
        )
        labels = {(item["text"], item["source_type"]) for item in case["analysis"]["labels"]}
        self.assertIn(("双相障碍", "reported_clinical_diagnosis"), labels)
        self.assertTrue(case["risk_flags"]["clinical"])
        self.assertEqual("clinical_report_only", case["route"]["mode"])
        self.assertEqual([], case["analysis"]["judgments"])

    def test_direct_questioned_label_remains_context_only(self) -> None:
        case = scaffold(
            "AI问我是不是“内向型”，我还没有确认。",
            "v42-direct-question-control",
        )
        self.assertEqual([], case["analysis"]["labels"])
        claims = {(item["claim"], item["polarity"]) for item in case["analysis"]["context_claims"]}
        self.assertIn(("内向型", "uncertain"), claims)

    def test_nested_quote_does_not_duplicate_one_observation(self) -> None:
        case = scaffold(
            "我陈述的事实是“上线前核对三遍”。请拆开标签和行为。",
            "v42-observation-quote",
        )
        observations = case["analysis"]["observations"]
        self.assertEqual(1, len(observations))
        self.assertEqual("上线前核对三遍", observations[0]["text"])

    def test_third_party_documented_diagnosis_is_not_promoted_to_the_user(self) -> None:
        case = scaffold(
            "论文写明患者被确诊为双相障碍，不是在描述我。",
            "v42-third-party-control",
        )
        self.assertEqual([], case["analysis"]["labels"])
        self.assertFalse(case["risk_flags"]["clinical"])


if __name__ == "__main__":
    unittest.main()
