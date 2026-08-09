#!/usr/bin/env python3
"""V26 red contracts: experiment review cannot revoke diagnosis or care."""

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
SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v26", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ReviewReservedJudgmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = json.loads(DEMO.read_text(encoding="utf-8"))
        if MODULE.validate_case(cls.base):
            raise AssertionError(MODULE.validate_case(cls.base))

    def test_review_cannot_revoke_diagnosis_or_treatment_need(self) -> None:
        cases = (
            "结果说明你的 ADHD 已经不存在，不需要继续治疗。",
            "这证明之前的抑郁症是误诊。",
            "所以你不再符合双相障碍诊断。",
        )
        for text in cases:
            with self.subTest(text=text):
                case = copy.deepcopy(self.base)
                case["review"]["rationale"] = text
                codes = {item["code"] for item in MODULE.validate_case(case)}
                self.assertIn("diagnosis_override_generated", codes, codes)


if __name__ == "__main__":
    unittest.main()
