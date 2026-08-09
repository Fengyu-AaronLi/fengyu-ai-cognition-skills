#!/usr/bin/env python3
"""R80 red contract for separating test and non-test dependency ledgers."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_MANIFEST = ROOT / "evals" / "regression-dependency-manifest.json"
RED_LEDGER = ROOT / "evals" / "red-evidence-manifest.json"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


class RedDependencyLedgerSeparationTests(unittest.TestCase):
    def test_raw_red_evidence_is_closed_but_tests_are_not_duplicated(self) -> None:
        """Raw evidence is a non-test input; test bytes belong to the test manifest."""

        dependencies = {
            item["path"]
            for item in load_json(DEPENDENCY_MANIFEST)["files"]
            if item["scope"] == "skill"
        }
        records = load_json(RED_LEDGER)["records"]
        evidence_paths = {record["evidence"]["path"] for record in records}
        test_paths = {
            test["path"]
            for record in records
            for test in record["tests"]
        }

        self.assertLessEqual(
            evidence_paths,
            dependencies,
            "every raw red record read by the verifier must be hash-closed",
        )
        duplicated_tests = sorted(test_paths & dependencies)
        self.assertEqual(
            [],
            duplicated_tests,
            "test modules belong only to test-generation-manifest.json",
        )


if __name__ == "__main__":
    unittest.main()
