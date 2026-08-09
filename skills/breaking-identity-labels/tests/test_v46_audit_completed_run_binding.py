#!/usr/bin/env python3
"""V46 contracts: every real audit receipt binds one completed evolution run."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts" / "run_evolution.py"
SPEC = importlib.util.spec_from_file_location("identity_run_evolution_v46", CONTROLLER)
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


class AuditCompletedRunFixture:
    audit_id = "independent_attribution_audit"
    receipt_id = "v46-attribution"

    def __init__(self, root: Path) -> None:
        self.root = root
        self.evidence_dir = root / "evals" / "receipts" / self.receipt_id
        self.evidence_dir.mkdir(parents=True)
        for name, content in {
            "preregistration.json": "{\"cases\":[\"A1\"]}\n",
            "environment.json": "{\"python\":\"fixture\"}\n",
            "command.stdout.txt": "Ran 1 test\nOK\n",
            "command.stderr.txt": "",
            "raw-output.txt": "Ran 1 test\nOK\n",
        }.items():
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
        self.completed_run = {
            "run_dir": "evals/runs/v46-run-a",
            "run_id": "v46-run-a",
            "candidate_id": "candidate-v46",
            "workflow_id": "breaking-identity-labels-v2-evolution",
            "workflow_path": "workflows/evolution-loop.json",
            "workflow_sha256": "7" * 64,
            "run_state_sha256": "8" * 64,
            "event_count": 4,
            "event_head_sha256": "9" * 64,
            "receipt_tree_sha256": "a" * 64,
            "completed_artifacts": copy.deepcopy(self.artifacts),
        }
        self.state = {
            "candidate_id": "candidate-v46",
            "artifacts": copy.deepcopy(self.artifacts),
            "test_manifest_sha256": "b" * 64,
            "completed_run": copy.deepcopy(self.completed_run),
        }
        prefix = f"evals/receipts/{self.receipt_id}"
        self.receipt = {
            "schema_version": "1.1",
            "receipt_id": self.receipt_id,
            "audit_id": self.audit_id,
            "candidate": {
                "candidate_id": "candidate-v46",
                "artifacts": copy.deepcopy(self.artifacts),
                "test_manifest_sha256": "b" * 64,
            },
            "completed_run": copy.deepcopy(self.completed_run),
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

    def validate(self) -> set[str]:
        write_json(self.receipt_path, self.receipt)
        errors, _, _ = MODULE.validate_audit_receipt(
            self.root,
            self.receipt_path.relative_to(self.root).as_posix(),
            self.audit_id,
            self.state,
        )
        return set(errors)


class AuditCompletedRunBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v46-audit-")
        self.fixture = AuditCompletedRunFixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_exact_completed_run_binding_is_accepted(self) -> None:
        self.assertEqual(set(), self.fixture.validate())

    def test_legacy_unbound_receipt_cannot_enter_a_real_frozen_state(self) -> None:
        self.fixture.receipt["schema_version"] = "1.0"
        self.fixture.receipt.pop("completed_run")

        self.assertIn(
            "audit_receipt_completed_run_required",
            self.fixture.validate(),
        )

    def test_same_candidate_bytes_from_another_run_cannot_be_replayed(self) -> None:
        self.fixture.receipt["completed_run"]["run_id"] = "v46-run-b"
        self.fixture.receipt["completed_run"]["run_dir"] = "evals/runs/v46-run-b"
        self.fixture.receipt["completed_run"]["run_state_sha256"] = "c" * 64

        self.assertIn(
            "audit_receipt_completed_run_mismatch",
            self.fixture.validate(),
        )

    def test_completed_run_integrity_heads_are_individually_bound(self) -> None:
        original = copy.deepcopy(self.fixture.receipt["completed_run"])
        cases = [
            (
                "run_state_sha256",
                "c" * 64,
                "audit_receipt_run_state_hash_mismatch",
            ),
            ("event_count", 5, "audit_receipt_event_head_mismatch"),
            (
                "event_head_sha256",
                "d" * 64,
                "audit_receipt_event_head_mismatch",
            ),
            (
                "receipt_tree_sha256",
                "e" * 64,
                "audit_receipt_receipt_tree_mismatch",
            ),
        ]
        for field, forged, code in cases:
            with self.subTest(field=field):
                self.fixture.receipt["completed_run"] = copy.deepcopy(original)
                self.fixture.receipt["completed_run"][field] = forged
                errors = self.fixture.validate()
                self.assertIn(code, errors)
                self.assertIn("audit_receipt_completed_run_mismatch", errors)

    def test_completed_run_must_cross_bind_candidate_and_artifacts(self) -> None:
        forged = copy.deepcopy(self.fixture.receipt["completed_run"])
        forged["candidate_id"] = "another-candidate"
        forged["completed_artifacts"]["runtime_sha256"] = "d" * 64
        self.fixture.receipt["completed_run"] = forged
        self.fixture.state["completed_run"] = copy.deepcopy(forged)

        self.assertIn(
            "audit_receipt_completed_run_cross_binding_mismatch",
            self.fixture.validate(),
        )


if __name__ == "__main__":
    unittest.main()
