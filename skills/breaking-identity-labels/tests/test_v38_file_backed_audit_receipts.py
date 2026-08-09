#!/usr/bin/env python3
"""V38 contracts requiring audit hashes to point to real immutable files."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts" / "run_evolution.py"
SPEC = importlib.util.spec_from_file_location("identity_run_evolution_v38", CONTROLLER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load evolution controller")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class AuditReceiptFixture:
    audit_id = "independent_attribution_audit"
    receipt_id = "v38-attribution"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.evidence_dir = root / "evals" / "receipts" / self.receipt_id
        self.evidence_dir.mkdir(parents=True)
        contents = {
            "preregistration.json": "{\"cases\":[\"A1\"]}\n",
            "environment.json": "{\"python\":\"fixture\"}\n",
            "command.stdout.txt": "Ran 1 test\nOK\n",
            "command.stderr.txt": "",
            "raw-output.txt": "Ran 1 test\nOK\n",
        }
        for name, content in contents.items():
            (self.evidence_dir / name).write_text(content, encoding="utf-8")
        self.artifacts = {
            "runtime_sha256": "1" * 64,
            "schema_tree_sha256": "2" * 64,
            "tests_tree_sha256": "3" * 64,
            "demo_tree_sha256": "4" * 64,
            "package_tree_sha256": "5" * 64,
            "governance_tree_sha256": "6" * 64,
            "workflow_sha256": "7" * 64,
        }
        self.state = {
            "candidate_id": "candidate-v38",
            "artifacts": self.artifacts,
            "test_manifest_sha256": "8" * 64,
        }
        prefix = f"evals/receipts/{self.receipt_id}"
        self.receipt = {
            "schema_version": "1.0",
            "receipt_id": self.receipt_id,
            "audit_id": self.audit_id,
            "candidate": {
                "candidate_id": "candidate-v38",
                "artifacts": self.artifacts,
                "test_manifest_sha256": "8" * 64,
            },
            "preregistration": {
                "path": f"{prefix}/preregistration.json",
                "case_set_sha256": digest(self.evidence_dir / "preregistration.json"),
            },
            "environment": {
                "path": f"{prefix}/environment.json",
                "sha256": digest(self.evidence_dir / "environment.json"),
            },
            "commands": [
                {
                    "argv": ["python3", "tests/test_attribution.py"],
                    "exit_code": 0,
                    "stdout_path": f"{prefix}/command.stdout.txt",
                    "stdout_sha256": digest(self.evidence_dir / "command.stdout.txt"),
                    "stderr_path": f"{prefix}/command.stderr.txt",
                    "stderr_sha256": digest(self.evidence_dir / "command.stderr.txt"),
                }
            ],
            "raw_output_path": f"{prefix}/raw-output.txt",
            "raw_output_sha256": digest(self.evidence_dir / "raw-output.txt"),
            "manual_findings": [],
            "blockers": [],
            "status": "passed",
        }
        self.receipt_path = root / "evals" / "receipts" / "attribution.json"

    def save(self) -> str:
        write_json(self.receipt_path, self.receipt)
        return self.receipt_path.relative_to(self.root).as_posix()

    def validate(self) -> list[str]:
        relative = self.save()
        errors, _, _ = MODULE.validate_audit_receipt(
            self.root,
            relative,
            self.audit_id,
            self.state,
        )
        return errors


class FileBackedAuditReceiptTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v38-audit-")
        self.fixture = AuditReceiptFixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_real_file_backed_receipt_is_accepted(self) -> None:
        self.assertEqual([], self.fixture.validate())

    def test_plausible_hex_strings_without_paths_are_not_evidence(self) -> None:
        self.fixture.receipt["preregistration"].pop("path")
        self.fixture.receipt["environment"].pop("path")
        command = self.fixture.receipt["commands"][0]
        command.pop("stdout_path")
        command.pop("stderr_path")
        self.fixture.receipt.pop("raw_output_path")

        errors = set(self.fixture.validate())

        self.assertIn("audit_receipt_evidence_path_invalid", errors)

    def test_file_content_drift_is_rechecked_after_receipt_creation(self) -> None:
        self.assertEqual([], self.fixture.validate())
        (self.fixture.evidence_dir / "command.stdout.txt").write_text(
            "forged pass\n",
            encoding="utf-8",
        )

        errors = set(self.fixture.validate())

        self.assertIn("audit_receipt_evidence_hash_mismatch", errors)

    def test_receipt_cannot_borrow_a_hash_file_from_another_receipt_directory(self) -> None:
        other = self.fixture.root / "evals" / "receipts" / "other" / "stdout.txt"
        other.parent.mkdir(parents=True)
        other.write_text("borrowed\n", encoding="utf-8")
        command = self.fixture.receipt["commands"][0]
        command["stdout_path"] = other.relative_to(self.fixture.root).as_posix()
        command["stdout_sha256"] = digest(other)

        errors = set(self.fixture.validate())

        self.assertIn("audit_receipt_evidence_scope_invalid", errors)


if __name__ == "__main__":
    unittest.main()
