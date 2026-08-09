#!/usr/bin/env python3
"""Round 182 RED: source-level relation checks cannot be last-write-wins."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
AUDITOR_PATH = SKILL_DIR / "scripts" / "run_evals.py"
REAL_ARTIFACT = (
    SKILL_DIR
    / "evals/raw/with-skill-v44-host-run-20260806-r2/bidirectional-evidence-on-one-claim/artifacts/separation.json"
)


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Round182BidirectionalRelationAggregationRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.auditor = load(AUDITOR_PATH, "round182_eval_auditor")
        cls.artifact = json.loads(REAL_ARTIFACT.read_text(encoding="utf-8"))

    def relation_error_message(self, artifact: dict) -> str:
        errors = self.auditor.check_bidirectional(artifact)
        finding = next(
            item for item in errors if item["code"] == "BIDIRECTIONAL_LINKS_WRONG"
        )
        return finding["message"]

    def test_all_atomic_relations_for_one_source_are_retained(self) -> None:
        message = self.relation_error_message(self.artifact)
        self.assertIn("E2", message)
        self.assertIn("conflicts", message)
        self.assertIn("does_not_establish", message)

    def test_relation_result_is_independent_of_link_order(self) -> None:
        reversed_artifact = copy.deepcopy(self.artifact)
        reversed_artifact["evidence_links"] = list(
            reversed(reversed_artifact["evidence_links"])
        )
        self.assertEqual(
            self.relation_error_message(self.artifact),
            self.relation_error_message(reversed_artifact),
        )

    def test_fixing_every_e2_atomic_relation_closes_the_case_specific_failure(self) -> None:
        fixed = copy.deepcopy(self.artifact)
        evidence_source_by_id = {
            item["id"]: item["source_ref"] for item in fixed["evidence"]
        }
        proposition_id = next(
            item["id"] for item in fixed["claims"] if item["source_ref"] == "P1"
        )
        for link in fixed["evidence_links"]:
            if (
                link["proposition_id"] == proposition_id
                and evidence_source_by_id.get(link["evidence_ref"]) == "E2"
            ):
                link["relation"] = "conflicts"
        codes = {
            item["code"] for item in self.auditor.check_bidirectional(fixed)
        }
        self.assertNotIn("BIDIRECTIONAL_LINKS_WRONG", codes)


if __name__ == "__main__":
    unittest.main()
