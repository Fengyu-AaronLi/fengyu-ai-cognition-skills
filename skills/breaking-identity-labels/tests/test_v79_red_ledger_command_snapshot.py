#!/usr/bin/env python3
"""R79 red contract for migration-aware workflow input snapshots."""

from __future__ import annotations

import runpy
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts" / "run_evolution.py"
LEDGER = ROOT / "evals" / "red-evidence-manifest.json"
TEST_MANIFEST = ROOT / "evals" / "test-generation-manifest.json"


class RedLedgerCommandSnapshotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.controller = runpy.run_path(str(CONTROLLER))

    def test_snapshot_accepts_historical_test_hash_and_binds_current_migration_chain(self) -> None:
        expand = self.controller["expand_evolution_input_files"]
        step = {
            "input_files": ["evals/red-evidence-manifest.json"],
        }
        with tempfile.TemporaryDirectory(prefix="identity-v79-red-snapshot-") as temp:
            paths = expand(
                ROOT,
                Path(temp),
                step,
                require_available=True,
            )

        relative = {path.relative_to(ROOT).as_posix() for path in paths}
        self.assertIn(LEDGER.relative_to(ROOT).as_posix(), relative)
        self.assertIn(TEST_MANIFEST.relative_to(ROOT).as_posix(), relative)
        self.assertIn("tests/test_v67_runtime_adversarial.py", relative)
        self.assertIn("tests/test_v72_red_evidence_closure.py", relative)
        self.assertIn("evals/test-migrations/v74-v67-user-confirmation.json", relative)
        self.assertIn("evals/test-migrations/v76-v72-red-ledger-history.json", relative)


if __name__ == "__main__":
    unittest.main()
