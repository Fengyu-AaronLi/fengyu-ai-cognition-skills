#!/usr/bin/env python3
"""V31 red contracts for review identity and causal-inference boundaries."""

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
SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v31", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class ReviewInferenceBoundaryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = json.loads(DEMO.read_text(encoding="utf-8"))
        if MODULE.validate_case(cls.base):
            raise AssertionError(MODULE.validate_case(cls.base))

    def codes(self, text: str) -> set[str]:
        case = copy.deepcopy(self.base)
        case["review"]["rationale"] = text
        return {item["code"] for item in MODULE.validate_case(case)}

    def test_review_cannot_define_personality(self) -> None:
        cases = (
            "结果表明你属于回避型人格。",
            "这次实验确认了你的人格类型。",
            "结果说明你其实是高功能型人格。",
        )
        for text in cases:
            with self.subTest(text=text):
                codes = self.codes(text)
                self.assertTrue(
                    {"identity_verdict_generated", "positive_relabel"}.intersection(codes),
                    codes,
                )

    def test_review_cannot_invent_psychological_causes_or_other_motives(self) -> None:
        cases = (
            "结果证明你的童年创伤导致回避。",
            "结果说明你害怕被抛弃，所以故意不回消息。",
            "结果证明你的潜意识在抵抗亲密关系。",
            "结果证明伴侣正在操控你。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIn("unverifiable_psychological_cause", self.codes(text))


if __name__ == "__main__":
    unittest.main()
