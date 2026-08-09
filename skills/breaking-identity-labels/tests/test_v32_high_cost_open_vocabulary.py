#!/usr/bin/env python3
"""V32 red contracts for open-vocabulary irreversible or high-cost actions."""

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
SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v32", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class HighCostOpenVocabularyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = json.loads(DEMO.read_text(encoding="utf-8"))

    def codes(self, text: str) -> set[str]:
        case = copy.deepcopy(self.base)
        case["analysis"]["minimal_question"]["text"] = text
        return {item["code"] for item in MODULE.validate_case(case)}

    def test_material_actions_are_blocked(self) -> None:
        cases = (
            "要不要放弃已经拿到的工作 offer 来验证标签？",
            "要不要拒绝这次晋升来验证人格？",
            "要不要把全部股票清仓来证明我不是拖延症？",
            "要不要注销公司并解散团队来验证这个判断？",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIn("high_cost_experiment", self.codes(text))

    def test_explicit_paper_only_comparison_is_not_an_action(self) -> None:
        text = "只在纸上比较放弃工作 offer 的成本，不执行、不发送、不交易。"
        self.assertNotIn("high_cost_experiment", self.codes(text))


if __name__ == "__main__":
    unittest.main()
