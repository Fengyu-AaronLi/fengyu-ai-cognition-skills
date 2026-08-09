#!/usr/bin/env python3
"""V30 red contracts for implicit label-to-capability and future verdicts."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "identity_label_case.py"
SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v30", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
CLOCK = "2026-08-06T00:00:00Z"


class ImplicitIdentityVerdictTests(unittest.TestCase):
    def test_open_phrasings_trigger_deconstruction_and_preserve_the_verdict(self) -> None:
        cases = (
            "AI说我是INTJ。看来领导岗和我没缘分。",
            "既然我是I人，我还是别争取晋升了。",
            "我被说成回避型，难怪亲密关系走不到最后。",
            "AI根据聊天说我没自制力。那我就不用再报考试了。",
            "我是P人，长期项目交给别人更合适。",
            "MBTI报告说我INFJ，所以我应该拒绝这个管理职位。",
            "AI判断我内向，因此公开表达这条路就到此为止。",
        )
        for text in cases:
            with self.subTest(text=text):
                case = MODULE.scaffold_case(text, None, CLOCK)
                self.assertEqual("deconstruct", case["route"]["mode"])
                self.assertTrue(case["route"]["trigger"])
                self.assertTrue(case["analysis"]["judgments"], case["analysis"])


if __name__ == "__main__":
    unittest.main()
