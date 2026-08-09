#!/usr/bin/env python3
"""V55 adversarial checks for audit receipt 1.2 input integrity."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts" / "run_evolution.py"
V46_TEST = ROOT / "tests" / "test_v46_audit_completed_run_binding.py"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


CONTROLLER_MODULE = load_module("v55_controller", CONTROLLER)
V46_MODULE = load_module("v55_v46_fixture", V46_TEST)


class AuditReceiptInputIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v55-audit-")
        self.fixture = V46_MODULE.AuditCompletedRunFixture(Path(self.temporary.name))
        script = self.fixture.root / "scripts" / "audit.py"
        input_path = self.fixture.root / "inputs" / "case-set.json"
        script.parent.mkdir(parents=True)
        input_path.parent.mkdir(parents=True)
        script.write_text("print('audit pass')\n", encoding="utf-8")
        input_path.write_text('{"cases":["A1"]}\n', encoding="utf-8")
        command = self.fixture.receipt["commands"][0]
        command.update(
            {
                "argv": ["python3", str(script)],
                "script_path": "scripts/audit.py",
                "script_sha256": V46_MODULE.digest(script),
                "input_snapshot": {
                    "cwd": ".",
                    "environment": {"PYTHONHASHSEED": "0"},
                    "files": [
                        {
                            "path": "inputs/case-set.json",
                            "sha256": V46_MODULE.digest(input_path),
                        },
                        {
                            "path": "scripts/audit.py",
                            "sha256": V46_MODULE.digest(script),
                        },
                    ],
                },
            }
        )
        self.fixture.receipt["schema_version"] = "1.2"
        self.input_path = input_path

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def validate(self) -> set[str]:
        V46_MODULE.write_json(self.fixture.receipt_path, self.fixture.receipt)
        errors, _, _ = CONTROLLER_MODULE.validate_audit_receipt(
            self.fixture.root,
            self.fixture.receipt_path.relative_to(self.fixture.root).as_posix(),
            self.fixture.audit_id,
            self.fixture.state,
        )
        return set(errors)

    def test_receipt_12_with_sorted_hash_bound_inputs_is_accepted(self) -> None:
        self.assertEqual(set(), self.validate())

    def test_input_byte_change_invalidates_an_otherwise_passing_receipt(self) -> None:
        self.assertEqual(set(), self.validate())
        self.input_path.write_text('{"cases":["forged"]}\n', encoding="utf-8")
        self.assertIn("audit_receipt_input_hash_mismatch", self.validate())

    def test_missing_snapshot_cannot_be_downgraded_while_claiming_version_12(self) -> None:
        self.fixture.receipt["commands"][0].pop("input_snapshot")
        errors = self.validate()
        self.assertIn("audit_receipt_schema_invalid", errors)
        self.assertIn("audit_receipt_input_snapshot_invalid", errors)

    def test_legacy_version_11_fixture_remains_accepted(self) -> None:
        receipt = copy.deepcopy(self.fixture.receipt)
        receipt["schema_version"] = "1.1"
        command = receipt["commands"][0]
        command.pop("script_path")
        command.pop("script_sha256")
        command.pop("input_snapshot")
        self.fixture.receipt = receipt
        self.assertEqual(set(), self.validate())


if __name__ == "__main__":
    unittest.main()
