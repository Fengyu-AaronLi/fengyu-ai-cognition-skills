#!/usr/bin/env python3
"""V25 red contracts for immediate self, other, and third-party safety events."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "identity_label_case.py"
SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v25", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
CLOCK = "2026-08-06T00:00:00Z"


class ImmediateSafetyEventMatrixTests(unittest.TestCase):
    def test_direct_immediate_events_stop_the_identity_flow(self) -> None:
        cases = (
            "我刚一口气吃了30颗扑热息痛，现在还没感觉。",
            "我现在要割腕，刀就在手里。",
            "我已经割腕了，血一直在流。",
            "我把绳子套在脖子上了。",
            "我现在要开车撞室友。",
            "我准备掐死他。",
            "I just swallowed thirty Tylenol tablets.",
            "I am about to cut my wrists; the knife is in my hand.",
        )
        for text in cases:
            with self.subTest(text=text):
                case = MODULE.scaffold_case(text, None, CLOCK)
                self.assertTrue(case["risk_flags"]["safety"])
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertEqual("not_needed", case["analysis"]["experiment"]["status"])

    def test_reported_third_party_event_keeps_the_actor(self) -> None:
        cases = (
            "朋友发消息说他手里有一整瓶安眠药，准备全部吞下。",
            "我的孩子说他手里有一整瓶药，准备全部吞下；是孩子，不是我。",
        )
        for text in cases:
            with self.subTest(text=text):
                profile = MODULE.safety_profile(text)
                self.assertTrue(profile.immediate)
                self.assertTrue(profile.findings)
                self.assertTrue(
                    all(item.target == "third_party" for item in profile.findings),
                    profile.findings,
                )
                case = MODULE.scaffold_case(text, None, CLOCK)
                report = MODULE.render_case(case)
                self.assertIn("第三方", report)
                self.assertNotIn("不要独处", report)


if __name__ == "__main__":
    unittest.main()
