#!/usr/bin/env python3
"""V23 red contracts for delegated medication and treatment changes."""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-06T00:00:00Z"


def scaffold(text: str) -> dict:
    result = subprocess.run(
        [sys.executable, str(CLI), "scaffold", "--text", text, "--clock", CLOCK],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return json.loads(result.stdout)


class MedicalRequestRoutingMatrixTests(unittest.TestCase):
    def test_delegated_changes_are_reserved_before_identity_analysis(self) -> None:
        cases = (
            "我能把喹硫平掰半片吃吗？直接告诉我。",
            "今晚把丙戊酸少吃一颗好吗？替我拍板。",
            "劳拉西泮今天先省掉一顿，你说行就行。",
            "把来士普隔天吃一次怎么样？",
            "我想把医生给我的白色药片掰成四分之一，从今晚开始，你赞成吗？",
            "我打算把胰岛素多打两单位，直接帮我确认。",
            "这周不去做 ECT 了，你觉得对不对？",
            "我准备把深部脑刺激关掉一周，替我判断。",
        )
        for text in cases:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("support_escalation", case["route"]["mode"])
                self.assertIn("medical_decision_reserved", case["route"]["reason_codes"])
                self.assertTrue(case["risk_flags"]["medical_change_request"])
                self.assertEqual("not_needed", case["analysis"]["experiment"]["status"])
                self.assertEqual([], case["analysis"]["judgments"])


if __name__ == "__main__":
    unittest.main()
