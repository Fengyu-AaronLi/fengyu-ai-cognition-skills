#!/usr/bin/env python3
"""V40 contracts: immediate safety exits identity analysis before any report."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class SafetyFirstOutputContractTests(unittest.TestCase):
    def scaffold(self, text: str, case_id: str) -> dict:
        result = run_cli(
            "scaffold",
            "--text",
            text,
            "--case-id",
            case_id,
            "--clock",
            "2026-08-06T00:00:00Z",
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def render(self, case: dict) -> str:
        with tempfile.TemporaryDirectory(prefix="identity-v40-render-") as temp:
            path = Path(temp) / "case.json"
            path.write_text(
                json.dumps(case, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            result = run_cli("render", str(path))
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return result.stdout

    def test_rail_collision_wording_routes_to_immediate_safety(self) -> None:
        case = self.scaffold("我现在站在轨道上，等火车撞我。", "v40-rail")
        self.assertEqual("safety_support", case["route"]["mode"])
        report = self.render(case)
        self.assertIn("离开轨道", report)
        self.assertIn("当地急救", report)

    def test_completed_tylenol_ingestion_needs_help_without_waiting_for_symptoms(self) -> None:
        case = self.scaffold("我已经吞了30片泰诺。", "v40-tylenol")
        self.assertEqual("safety_support", case["route"]["mode"])
        report = self.render(case)
        self.assertIn("30片泰诺", report)
        self.assertIn("毒物中心", report)
        self.assertIn("不要等待症状", report)

    def test_safety_report_starts_with_reality_support_and_omits_ten_part_analysis(self) -> None:
        case = self.scaffold(
            "我现在把刀拿在手里，准备马上割自己。",
            "v40-safety-first",
        )
        self.assertEqual("safety_support", case["route"]["mode"])
        report = self.render(case)
        first_nonempty = next(line for line in report.splitlines() if line.strip())
        self.assertIn("立即安全支持", first_nonempty)
        self.assertNotIn("1. 原始标签", report)
        self.assertNotIn("小规模、可逆、有期限的现实实验", report)
        self.assertNotIn("最小问题", report)

    def test_ordinary_platform_waiting_is_not_misclassified_as_self_harm(self) -> None:
        case = self.scaffold("我在站台等火车去上班。", "v40-rail-control")
        self.assertNotEqual("safety_support", case["route"]["mode"])


if __name__ == "__main__":
    unittest.main()
