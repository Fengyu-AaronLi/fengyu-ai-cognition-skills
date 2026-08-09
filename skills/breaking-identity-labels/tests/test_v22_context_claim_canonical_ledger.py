#!/usr/bin/env python3
"""V22 red contracts: context claims are a runtime-owned canonical ledger."""

from __future__ import annotations

import copy
import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "identity_label_case.py"
SPEC = importlib.util.spec_from_file_location("identity_label_runtime_v22", RUNTIME)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load identity label runtime")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
CLOCK = "2026-08-06T00:00:00Z"


def codes(case: dict) -> set[str]:
    return {item["code"] for item in MODULE.validate_case(case)}


class ContextClaimCanonicalLedgerTests(unittest.TestCase):
    def test_negated_diagnosis_cannot_gain_an_affirmed_duplicate(self) -> None:
        case = MODULE.scaffold_case(
            "AI说我是回避型，所以我永远经营不好关系；"
            "精神科医生明确说没有诊断我有 ADHD。",
            None,
            CLOCK,
        )
        negated = next(
            item for item in case["analysis"]["context_claims"]
            if item["claim"] == "ADHD"
        )
        forged = copy.deepcopy(negated)
        forged["polarity"] = "affirmed"
        case["analysis"]["context_claims"].append(forged)
        self.assertIn("context_claim_semantic_mismatch", codes(case))

    def test_third_party_diagnosis_cannot_be_reassigned_to_current_user(self) -> None:
        case = MODULE.scaffold_case(
            "临床医生完整评估后诊断妹妹有边缘型人格障碍；"
            "AI说我是回避型，所以我永远经营不好关系。",
            None,
            CLOCK,
        )
        claim = next(
            item for item in case["analysis"]["context_claims"]
            if item["claim"] == "边缘型人格障碍"
        )
        claim["subject"] = "current_user"
        self.assertIn("context_claim_semantic_mismatch", codes(case))

    def test_exact_duplicate_claim_is_rejected(self) -> None:
        case = MODULE.scaffold_case(
            "精神科医生明确说没有诊断我有 ADHD。",
            None,
            CLOCK,
        )
        case["analysis"]["context_claims"].append(
            copy.deepcopy(case["analysis"]["context_claims"][0])
        )
        self.assertIn("context_claim_semantic_mismatch", codes(case))


if __name__ == "__main__":
    unittest.main()
