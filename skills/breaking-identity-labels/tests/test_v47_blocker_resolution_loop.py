#!/usr/bin/env python3
"""V47 contracts: carried blockers close only through bound verification evidence."""

from __future__ import annotations

import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from test_v14_evolution_lineage_and_governance import (
    CONTROLLER,
    V14Fixture,
    digest,
    result_payload,
    write_json,
)


SPEC = importlib.util.spec_from_file_location("identity_run_evolution_v47", CONTROLLER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load evolution controller")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class BlockerResolutionLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v47-resolution-")
        self.fixture = V14Fixture(Path(self.temporary.name))
        self.r1 = self.fixture.root / "evals" / "runs" / "v47-r1"
        first = self.fixture.start(
            self.fixture.workflow,
            self.r1,
            "v47-r1",
            "candidate-v47-r1",
        )
        if first.returncode != 0:
            raise AssertionError(first.stdout + first.stderr)
        self.r2 = self.fixture.root / "evals" / "runs" / "v47-r2"
        second = self.fixture.controller(
            "next-iteration",
            "--previous-run-dir",
            str(self.r1),
            "--run-dir",
            str(self.r2),
            "--run-id",
            "v47-r2",
            "--candidate-id",
            "candidate-v47-r2",
            "--carry-over-blocker",
            "B-V47:P0:evals/findings/v14.md",
        )
        if second.returncode != 0:
            raise AssertionError(second.stdout + second.stderr)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def make_receipt(self, *, name: str = "resolve-b-v47") -> tuple[str, Path]:
        state = json.loads((self.r2 / "run-state.json").read_text(encoding="utf-8"))
        binding = state["carry_over_blocker_bindings"][0]
        predecessor = MODULE.completed_run_binding(
            self.fixture.root,
            self.r2,
            state,
        )
        evolution_receipt_path = self.fixture.root / state["steps"]["green"]["receipt_path"]
        evolution_receipt = json.loads(evolution_receipt_path.read_text(encoding="utf-8"))
        command_script = Path(evolution_receipt["argv"][1]).resolve()
        command_script_relative = command_script.relative_to(
            self.fixture.root.resolve()
        ).as_posix()
        resolution_dir = self.fixture.root / "evals" / "blocker-resolutions" / name
        resolution_dir.mkdir(parents=True, exist_ok=True)
        fix = resolution_dir / "fix-evidence.md"
        regression = resolution_dir / "regression-evidence.md"
        fix.write_text("The candidate contains the implemented correction.\n", encoding="utf-8")
        regression.write_text(
            "The targeted regression and adjacent control were executed by the bound workflow step.\n",
            encoding="utf-8",
        )
        audit_receipt_id = f"audit-{name}"
        audit_evidence_dir = self.fixture.root / "evals" / "receipts" / audit_receipt_id
        audit_evidence_dir.mkdir(parents=True, exist_ok=True)
        verification = audit_evidence_dir / "blocker-verification.md"
        verification.write_text(
            "Independent regression replay passed and the original failure no longer reproduces.\n",
            encoding="utf-8",
        )
        write_json(
            audit_evidence_dir / "preregistration.json",
            {
                "schema_version": "1.0",
                "audit_id": "independent_state_integrity_audit",
                "candidate_id": state["candidate_id"],
                "completed_run_sha256": predecessor["run_state_sha256"],
                "objective": "Independently replay the bound regression that resolves B-V47.",
                "commands": [
                    {
                        "argv": [command_script_relative, *evolution_receipt["argv"][2:]],
                        "input_files": [command_script_relative],
                    }
                ],
                "pass_condition": "The exact bound regression command exits zero on the repaired run.",
                "live_model_called": False,
            },
        )
        for filename, content in {
            "environment.json": "{\"python\":\"fixture\"}\n",
            "command.stdout.txt": (
                self.fixture.root / evolution_receipt["stdout_path"]
            ).read_text(encoding="utf-8"),
            "command.stderr.txt": (
                self.fixture.root / evolution_receipt["stderr_path"]
            ).read_text(encoding="utf-8"),
            "raw-output.txt": "Ran 1 test\nOK\n",
        }.items():
            (audit_evidence_dir / filename).write_text(content, encoding="utf-8")
        audit_prefix = audit_evidence_dir.relative_to(self.fixture.root).as_posix()
        audit_receipt = {
            "schema_version": "1.2",
            "receipt_id": audit_receipt_id,
            "audit_id": "independent_state_integrity_audit",
            "candidate": {
                "candidate_id": state["candidate_id"],
                "artifacts": copy.deepcopy(state["completed_artifacts"]),
                "test_manifest_sha256": digest(self.fixture.manifest),
            },
            "completed_run": copy.deepcopy(predecessor),
            "preregistration": {
                "path": f"{audit_prefix}/preregistration.json",
                "case_set_sha256": digest(audit_evidence_dir / "preregistration.json"),
            },
            "environment": {
                "path": f"{audit_prefix}/environment.json",
                "sha256": digest(audit_evidence_dir / "environment.json"),
            },
            "commands": [
                {
                    "argv": evolution_receipt["argv"],
                    "script_path": command_script_relative,
                    "script_sha256": digest(command_script),
                    "input_snapshot": {
                        "cwd": ".",
                        "environment": {"PYTHONHASHSEED": "0"},
                        "files": [
                            {
                                "path": command_script_relative,
                                "sha256": digest(command_script),
                            }
                        ],
                    },
                    "exit_code": evolution_receipt["exit_code"],
                    "stdout_path": f"{audit_prefix}/command.stdout.txt",
                    "stdout_sha256": digest(audit_evidence_dir / "command.stdout.txt"),
                    "stderr_path": f"{audit_prefix}/command.stderr.txt",
                    "stderr_sha256": digest(audit_evidence_dir / "command.stderr.txt"),
                }
            ],
            "raw_output_path": f"{audit_prefix}/raw-output.txt",
            "raw_output_sha256": digest(audit_evidence_dir / "raw-output.txt"),
            "manual_findings": [
                {
                    "finding_id": "finding-B-V47",
                    "blocker_id": "B-V47",
                    "outcome": "resolved",
                    "summary": "The frozen failure no longer reproduces and adjacent controls still pass.",
                    "verification_step_ids": ["green"],
                    "evidence": [
                        {
                            "path": verification.relative_to(self.fixture.root).as_posix(),
                            "sha256": digest(verification),
                        }
                    ],
                }
            ],
            "blockers": [],
            "status": "passed",
        }
        audit_receipt_path = self.fixture.root / "evals" / "receipts" / f"{audit_receipt_id}.json"
        write_json(audit_receipt_path, audit_receipt)
        receipt = {
            "schema_version": "1.0",
            "receipt_id": name,
            "blocker": copy.deepcopy(binding),
            "source_predecessor": copy.deepcopy(state["predecessor_binding"]),
            "repaired_run": predecessor,
            "resolution": {
                "summary": "Implemented the narrow mechanism repair covered by the original blocker.",
                "evidence": [
                    {
                        "path": fix.relative_to(self.fixture.root).as_posix(),
                        "sha256": digest(fix),
                        "role": "implementation",
                    },
                    {
                        "path": regression.relative_to(self.fixture.root).as_posix(),
                        "sha256": digest(regression),
                        "role": "regression_test",
                    }
                ],
            },
            "verification": {
                "audit_receipt": {
                    "path": audit_receipt_path.relative_to(self.fixture.root).as_posix(),
                    "sha256": digest(audit_receipt_path),
                },
                "finding_id": "finding-B-V47",
            },
        }
        receipt_path = self.fixture.root / "evals" / "blocker-resolutions" / f"{name}.json"
        write_json(receipt_path, receipt)
        return receipt_path.relative_to(self.fixture.root).as_posix(), verification

    def advance_with_resolution(self, relative: str, *, name: str = "v47-r3"):
        target = self.fixture.root / "evals" / "runs" / name
        result = self.fixture.controller(
            "next-iteration",
            "--previous-run-dir",
            str(self.r2),
            "--run-dir",
            str(target),
            "--run-id",
            name,
            "--candidate-id",
            f"candidate-{name}",
            "--resolve-blocker",
            relative,
        )
        return result, target

    def test_verified_receipt_closes_only_the_named_blocker(self) -> None:
        relative, _ = self.make_receipt()
        result, r3 = self.advance_with_resolution(relative)

        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        state = json.loads((r3 / "run-state.json").read_text(encoding="utf-8"))
        self.assertEqual([], state["carry_over_blockers"])
        self.assertEqual([], state["carry_over_blocker_bindings"])
        self.assertEqual("B-V47", state["resolved_blocker_bindings"][0]["id"])
        self.assertEqual(
            "resolved",
            state["resolved_blocker_bindings"][0]["derived_status"],
        )

    def test_release_freeze_does_not_reanimate_a_verified_closed_blocker(self) -> None:
        relative, _ = self.make_receipt()
        advanced, r3 = self.advance_with_resolution(relative)
        self.assertEqual(0, advanced.returncode, advanced.stdout + advanced.stderr)

        frozen = self.fixture.controller(
            "freeze",
            "--candidate-id",
            "candidate-v47-r3",
            "--workflow",
            str(self.fixture.workflow),
            "--completed-run-dir",
            str(r3),
        )

        self.assertEqual(0, frozen.returncode, frozen.stdout + frozen.stderr)
        release = json.loads(self.fixture.release_state.read_text(encoding="utf-8"))
        self.assertEqual(0, release["blocker_count"])
        self.assertEqual("pending", release["decision"])
        self.assertEqual("B-V47", release["blocker_resolutions"][0]["id"])

    def test_resolution_must_bind_the_exact_completed_predecessor(self) -> None:
        relative, _ = self.make_receipt(name="wrong-predecessor")
        path = self.fixture.root / relative
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["repaired_run"]["run_id"] = "some-other-run"
        write_json(path, receipt)

        result, _ = self.advance_with_resolution(relative, name="v47-wrong-r3")

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn(
            "evolution_blocker_resolution_predecessor_mismatch",
            set(result_payload(result).get("errors", [])),
        )

    def test_plain_self_attestation_cannot_replace_a_passing_audit_receipt(self) -> None:
        relative, _ = self.make_receipt(name="self-attested")
        path = self.fixture.root / relative
        receipt = json.loads(path.read_text(encoding="utf-8"))
        receipt["verification"] = {
            "outcome": "resolved",
            "reviewed_by": "caller-chosen-name",
        }
        write_json(path, receipt)

        result, _ = self.advance_with_resolution(relative, name="v47-self-r3")

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn(
            "evolution_blocker_resolution_receipt_schema_invalid",
            set(result_payload(result).get("errors", [])),
        )

    def test_audit_receipt_from_another_completed_run_cannot_be_replayed(self) -> None:
        relative, _ = self.make_receipt(name="replayed-audit")
        resolution_path = self.fixture.root / relative
        resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
        audit_path = self.fixture.root / resolution["verification"]["audit_receipt"]["path"]
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit["completed_run"]["run_id"] = "another-completed-run"
        write_json(audit_path, audit)
        resolution["verification"]["audit_receipt"]["sha256"] = digest(audit_path)
        write_json(resolution_path, resolution)

        result, _ = self.advance_with_resolution(relative, name="v47-replay-r3")

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn(
            "evolution_blocker_resolution_verification_run_mismatch",
            set(result_payload(result).get("errors", [])),
        )

    def test_audit_command_must_match_the_bound_evolution_step(self) -> None:
        relative, _ = self.make_receipt(name="wrong-audit-command")
        resolution_path = self.fixture.root / relative
        resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
        audit_path = self.fixture.root / resolution["verification"]["audit_receipt"]["path"]
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit["commands"][0]["argv"] = ["python3", "some-unbound-check.py"]
        write_json(audit_path, audit)
        resolution["verification"]["audit_receipt"]["sha256"] = digest(audit_path)
        write_json(resolution_path, resolution)

        result, _ = self.advance_with_resolution(relative, name="v47-command-r3")

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn(
            "evolution_blocker_resolution_verification_invalid",
            set(result_payload(result).get("errors", [])),
        )

    def test_blocked_audit_cannot_close_a_blocker(self) -> None:
        relative, _ = self.make_receipt(name="blocked-audit")
        resolution_path = self.fixture.root / relative
        resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
        audit_path = self.fixture.root / resolution["verification"]["audit_receipt"]["path"]
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit["blockers"] = [{"id": "still-open", "severity": "P0"}]
        audit["status"] = "blocked"
        write_json(audit_path, audit)
        resolution["verification"]["audit_receipt"]["sha256"] = digest(audit_path)
        write_json(resolution_path, resolution)

        result, _ = self.advance_with_resolution(relative, name="v47-blocked-r3")

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn(
            "evolution_blocker_resolution_verification_not_passed",
            set(result_payload(result).get("errors", [])),
        )

    def test_release_gate_rejects_deleting_the_resolution_proof(self) -> None:
        relative, _ = self.make_receipt(name="release-proof")
        advanced, r3 = self.advance_with_resolution(relative, name="v47-proof-r3")
        self.assertEqual(0, advanced.returncode, advanced.stdout + advanced.stderr)
        frozen = self.fixture.controller(
            "freeze",
            "--candidate-id",
            "candidate-v47-proof-r3",
            "--workflow",
            str(self.fixture.workflow),
            "--completed-run-dir",
            str(r3),
        )
        self.assertEqual(0, frozen.returncode, frozen.stdout + frozen.stderr)
        release = json.loads(self.fixture.release_state.read_text(encoding="utf-8"))
        release.pop("blocker_resolutions")
        write_json(self.fixture.release_state, release)

        checked = self.fixture.controller("check", "--allow-blocked")

        self.assertEqual(3, checked.returncode, checked.stdout + checked.stderr)
        self.assertIn(
            "release_state_blocker_resolution_mismatch",
            set(result_payload(checked).get("errors", [])),
        )

    def test_resolution_evidence_is_continuously_revalidated(self) -> None:
        relative, verification = self.make_receipt(name="drifted-resolution")
        advanced, r3 = self.advance_with_resolution(relative, name="v47-drift-r3")
        self.assertEqual(0, advanced.returncode, advanced.stdout + advanced.stderr)
        verification.write_text("forged after closure\n", encoding="utf-8")

        status = self.fixture.controller("status", "--run-dir", str(r3))

        self.assertEqual(3, status.returncode, status.stdout + status.stderr)
        self.assertIn(
            "evolution_blocker_resolution_evidence_hash_mismatch",
            set(result_payload(status).get("errors", [])),
        )


if __name__ == "__main__":
    unittest.main()
