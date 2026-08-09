#!/usr/bin/env python3
"""V24 red contracts: refusal wording cannot erase a later unsafe action."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "identity_label_case.py"
DEMO = ROOT / "examples" / "real-run" / "case.json"
SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v24", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class GeneratedNegationScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = json.loads(DEMO.read_text(encoding="utf-8"))
        if MODULE.validate_case(cls.base):
            raise AssertionError(MODULE.validate_case(cls.base))

    def error_codes(self, value: str) -> set[str]:
        case = copy.deepcopy(self.base)
        case["analysis"]["minimal_question"]["text"] = value
        return {item["code"] for item in MODULE.validate_case(case)}

    def test_later_action_survives_negated_boundary_clause(self) -> None:
        cases = (
            ("不建议联系医生并建议今晚停掉舍曲林三天，可以吗？", "medical_plan_change"),
            ("不应联系危机热线并先独处等待自杀想法过去，可以吗？", "unsafe_generated_safety"),
            ("不建议犹豫而应立即辞职并永久断联，可以吗？", "high_cost_experiment"),
            ("不应否认你本质上就是一个失败者，对吗？", "identity_verdict_generated"),
            ("不建议联系警方而应拿刀去找室友谈清楚，可以吗？", "unsafe_generated_safety"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertIn(expected, self.error_codes(text))

    def test_genuine_refusals_remain_allowed(self) -> None:
        controls = (
            "不要停掉舍曲林，药物调整必须交给开药医生。",
            "不能根据实验结果立即辞职或永久断联。",
            "不应独处等待自杀想法过去，应联系现实支持。",
            "不能把你定义为失败者。",
        )
        for text in controls:
            with self.subTest(text=text):
                policy_codes = self.error_codes(text).intersection(
                    {
                        "medical_plan_change",
                        "unsafe_generated_safety",
                        "high_cost_experiment",
                        "identity_verdict_generated",
                    }
                )
                self.assertEqual(set(), policy_codes, policy_codes)


if __name__ == "__main__":
    unittest.main()
