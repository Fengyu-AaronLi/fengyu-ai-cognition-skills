#!/usr/bin/env python3
"""R71 contract: the regression runner must re-derive dependency closure."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_regressions.py"
SYNC = ROOT / "scripts" / "sync_regression_dependencies.py"


SPEC = importlib.util.spec_from_file_location("identity_v71_regression_runner", RUNNER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load regression runner")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

SYNC_SPEC = importlib.util.spec_from_file_location("identity_v71_dependency_sync", SYNC)
if SYNC_SPEC is None or SYNC_SPEC.loader is None:
    raise RuntimeError("cannot load dependency synchronizer")
SYNC_MODULE = importlib.util.module_from_spec(SYNC_SPEC)
SYNC_SPEC.loader.exec_module(SYNC_MODULE)


class RegressionDependencyClosedWorldContract(unittest.TestCase):
    def test_hash_valid_but_incomplete_manifest_is_rejected(self) -> None:
        identities = SYNC_MODULE.expected_identities(ROOT, ROOT.parents[1])
        payload = {
            "schema_version": "1.0",
            "files": SYNC_MODULE.records_for(ROOT, ROOT.parents[1], identities),
        }
        removed = next(
            index
            for index, item in enumerate(payload["files"])
            if item["scope"] == "skill" and item["path"] == "README.md"
        )
        payload["files"].pop(removed)
        with tempfile.TemporaryDirectory(prefix="identity-v71-dependency-") as temp:
            path = Path(temp) / "incomplete.json"
            path.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                MODULE.RegressionManifestError,
                "regression_dependency_inventory_missing",
            ):
                MODULE.verify_dependency_manifest(path)


if __name__ == "__main__":
    unittest.main()
