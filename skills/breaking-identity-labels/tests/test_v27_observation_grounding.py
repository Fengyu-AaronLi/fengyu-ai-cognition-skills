#!/usr/bin/env python3
"""V27 red contracts for behavior-only, evidence-bound observations."""

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
SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v27", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def source_observation(item: dict, *, context: str, frequency: str, timeframe: str) -> dict:
    return {
        "text": item["text"],
        "context": context,
        "frequency": frequency,
        "timeframe": timeframe,
        "source": copy.deepcopy(item["source"]),
    }


class ObservationGroundingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.base = json.loads(DEMO.read_text(encoding="utf-8"))
        if MODULE.validate_case(cls.base):
            raise AssertionError(MODULE.validate_case(cls.base))

    def test_label_or_judgment_span_cannot_be_added_as_behavior(self) -> None:
        for field in ("labels", "judgments"):
            with self.subTest(field=field):
                case = copy.deepcopy(self.base)
                source_item = case["analysis"][field][0]
                case["analysis"]["observations"].append(
                    source_observation(
                        source_item,
                        context="童年创伤触发",
                        frequency="永远",
                        timeframe="从出生至今",
                    )
                )
                codes = {item["code"] for item in MODULE.validate_case(case)}
                self.assertIn("observation_not_behavior", codes, codes)

    def test_e000_observation_metadata_cannot_be_invented(self) -> None:
        case = copy.deepcopy(self.base)
        source_item = case["analysis"]["observations"][0]
        case["analysis"]["observations"].append(
            source_observation(
                source_item,
                context="所有工作和关系",
                frequency="每次",
                timeframe="一生",
            )
        )
        codes = {item["code"] for item in MODULE.validate_case(case)}
        self.assertIn("observation_metadata_unbound", codes, codes)


if __name__ == "__main__":
    unittest.main()
