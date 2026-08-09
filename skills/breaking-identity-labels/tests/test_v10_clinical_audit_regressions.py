#!/usr/bin/env python3
"""V10 red tests from the frozen V9 independent clinical audit."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-06T14:00:00Z"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def scaffold(text: str) -> dict:
    result = run_cli("scaffold", "--text", text, "--clock", CLOCK)
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


def render(case: dict) -> str:
    with tempfile.TemporaryDirectory(prefix="identity-v10-clinical-") as temp:
        case_path = Path(temp) / "case.json"
        case_path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        result = run_cli("render", str(case_path))
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout


class V9ClinicalAuditRegressions(unittest.TestCase):
    def test_english_other_harm_negated_weapon_is_not_rendered_as_available(self) -> None:
        case = scaffold("I intend to attack my roommate now, and I have no weapon.")
        self.assertEqual("safety_support", case["route"]["mode"])
        self.assertTrue(case["risk_flags"]["safety"])
        report = render(case)
        self.assertIn("roommate", report)
        self.assertNotIn("远离weapon", report)
        self.assertNotIn("放下并远离weapon", report)

    def test_relinquished_means_remains_unavailable_in_the_report(self) -> None:
        case = scaffold("刀具已经交给保安，我目前仍怕自己会伤害自己。")
        self.assertEqual("safety_support", case["route"]["mode"])
        self.assertTrue(case["risk_flags"]["safety"])
        report = render(case)
        self.assertIn("刀具已经交给保安", report)
        self.assertNotIn("请立即放下并远离刀具", report)
        self.assertNotIn("请能够到场的人协助保管", report)

    def test_ai_medical_change_requests_route_to_the_medical_boundary(self) -> None:
        positives = (
            "我想把文拉法辛从150mg降到75mg，请替我决定今晚是否开始。",
            "我想停用每周的生物制剂，请替我确认下周是否停。",
            "I want to stop my medication tonight; decide for me.",
        )
        for text in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("support_escalation", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["medical_change_request"])
                report = render(case)
                self.assertIn("医疗与治疗方案边界", report)

        controls = (
            "处方医生已书面决定把文拉法辛从150mg降到75mg，我只记录既定方案，不让AI调整。",
            "专科医生已经决定停用每周的生物制剂，我只记录书面方案，并未让AI改方案。",
            "医生已书面安排 medication holiday，我只记录方案，不让AI决定。",
        )
        for text in controls:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertFalse(case["risk_flags"]["medical_change_request"])
                self.assertEqual("clinical_report_only", case["route"]["mode"])


if __name__ == "__main__":
    unittest.main()
