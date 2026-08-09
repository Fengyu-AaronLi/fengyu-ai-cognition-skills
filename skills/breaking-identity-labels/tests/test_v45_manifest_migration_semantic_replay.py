#!/usr/bin/env python3
"""V45 contracts: test migrations replay receipt meaning, not only file hashes."""

from __future__ import annotations

import copy
import hashlib
import json
import runpy
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts" / "run_evolution.py"
MANIFEST = ROOT / "evals" / "test-generation-manifest.json"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ManifestMigrationSemanticReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = runpy.run_path(str(CONTROLLER))
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def history_errors(self, manifest: dict) -> set[str]:
        return set(self.module["validate_manifest_migration_history"](ROOT, manifest))

    def test_checked_in_migration_history_semantically_replays(self) -> None:
        self.assertEqual(set(), self.history_errors(copy.deepcopy(self.manifest)))

    def test_receipt_for_another_test_cannot_be_substituted_by_hash(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        target = next(
            record
            for record in manifest["files"]
            if record["path"] == "tests/test_v11_evolution_controller.py"
        )
        wrong = ROOT / "evals" / "test-migrations" / "v37-v14-governance-freeze-binding.json"
        target["migration_history"][0]["receipt_path"] = wrong.relative_to(ROOT).as_posix()
        target["migration_history"][0]["receipt_sha256"] = digest(wrong)

        errors = self.history_errors(manifest)

        self.assertIn("test_migration_receipt_semantic_mismatch", errors)

    def test_deleting_history_does_not_orphan_existing_receipts_silently(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        target = next(
            record
            for record in manifest["files"]
            if record["path"] == "tests/test_v11_evolution_controller.py"
        )
        target.pop("migration_history")

        errors = self.history_errors(manifest)

        self.assertIn("test_migration_receipt_unreferenced", errors)

    def test_manifest_schema_is_an_executable_contract(self) -> None:
        manifest = copy.deepcopy(self.manifest)
        manifest["forged_field"] = True

        errors = set(self.module["validate_test_manifest"](ROOT, manifest))

        self.assertIn("test_manifest_schema_invalid", errors)


if __name__ == "__main__":
    unittest.main()
