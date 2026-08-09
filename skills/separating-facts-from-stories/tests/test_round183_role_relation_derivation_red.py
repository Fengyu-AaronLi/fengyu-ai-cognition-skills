#!/usr/bin/env python3
"""Round 183 RED: recognized one-way role signals require their weak relation."""

from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
REAL_ARTIFACT = (
    SKILL_DIR
    / "evals/raw/with-skill-v44-host-run-20260806-r2/bidirectional-evidence-on-one-claim/artifacts/separation.json"
)
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


class Round183RoleRelationDerivationRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.artifact = json.loads(REAL_ARTIFACT.read_text(encoding="utf-8"))

    def test_real_model_cannot_downgrade_recognized_counter_signal_to_unknown(self) -> None:
        errors = casefile.validate_casefile(self.artifact)
        unsupported = [
            item
            for item in errors
            if item["code"] == "RELATION_SEMANTICALLY_UNSUPPORTED"
        ]
        self.assertEqual(1, len(unsupported))
        self.assertIn("conflicts", unsupported[0]["message"])

    def test_repairing_atomic_counter_signal_to_conflicts_passes(self) -> None:
        repaired = copy.deepcopy(self.artifact)
        target = next(
            item
            for item in repaired["evidence_links"]
            if item["proposition_id"] == "C1" and item["evidence_ref"] == "E3"
        )
        target.update(
            relation="conflicts",
            strength="weak",
            reason="counter_signal_with_limited_scope",
        )
        self.assertEqual([], casefile.validate_casefile(repaired))

    def test_unrecognized_or_mixed_signal_remains_fail_closed(self) -> None:
        allowed = casefile._allowed_relation_for_claim_evidence(
            {
                "kind": "interpretation",
                "source_ref": "P1",
                "exact_quote": "公司已经决定架空我。",
            },
            {
                "source_ref": "E9",
                "source_label": "E9",
                "source_type": "user_report",
                "exact_quote": "今天办公室换了座位。",
            },
        )
        self.assertEqual({"does_not_establish"}, allowed)


if __name__ == "__main__":
    unittest.main()
