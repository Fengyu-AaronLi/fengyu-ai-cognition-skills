#!/usr/bin/env python3
"""V11 red contracts for the executable evolution and release gate."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts" / "run_evolution.py"
AUDIT_IDS = (
    "independent_attribution_audit",
    "independent_clinical_safety_audit",
    "independent_state_integrity_audit",
    "release_package_audit",
)
DEMO_FILES = (
    ".case.lock",
    "analysis.json",
    "case.json",
    "demo-input.txt",
    "events.head.json",
    "events.jsonl",
    "report.md",
    "run-manifest.json",
)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def tree_digest(root: Path, paths: list[Path]) -> str:
    records = [
        {
            "bytes": path.stat().st_size,
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256(path.read_bytes()),
        }
        for path in sorted(paths)
    ]
    return sha256(
        json.dumps(
            records,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


class EvolutionFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        for relative in (
            "scripts",
            "schemas",
            "tests",
            "workflows",
            "evals/runs",
            "examples/real-run",
            "evals/receipts",
        ):
            (root / relative).mkdir(parents=True, exist_ok=True)
        (root / "scripts" / "identity_label_case.py").write_text(
            "print('runtime')\n", encoding="utf-8"
        )
        (root / "scripts" / "build_package.py").write_text(
            """#!/usr/bin/env python3
import json
print(json.dumps({"status": "built", "tree_sha256": "f" * 64}))
""",
            encoding="utf-8",
        )
        (root / "scripts" / "run_evolution.py").write_text(
            "# controller governance fixture\n", encoding="utf-8"
        )
        (root / "scripts" / "build_demo.py").write_text(
            "# demo builder governance fixture\n", encoding="utf-8"
        )
        (root / "evals" / "validate.py").write_text(
            "# evaluator governance fixture\n", encoding="utf-8"
        )
        (root / "scripts" / "worker.py").write_text("print('OK')\n", encoding="utf-8")
        write_json(root / "schemas" / "case.schema.json", {"type": "object"})
        write_json(root / "schemas" / "release-gate.schema.json", {"type": "object"})
        (root / "tests" / "test_v10_preserved.py").write_text(
            "# frozen generation\n", encoding="utf-8"
        )
        (root / "tests" / "test_v11_current.py").write_text(
            "# current generation\n", encoding="utf-8"
        )
        for name in DEMO_FILES:
            (root / "examples" / "real-run" / name).write_text(
                f"fixture:{name}\n", encoding="utf-8"
            )
        self.workflow_path = root / "workflows" / "v11-release.json"
        write_json(
            self.workflow_path,
            {
                "schema_version": "1.0",
                "workflow_id": "identity-v11-release-fixture",
                "steps": [
                    {
                        "id": "green",
                        "kind": "command",
                        "depends_on": [],
                        "argv": ["{python}", "{root}/scripts/worker.py"],
                        "expected": "exit_zero",
                    }
                ],
            },
        )
        self.write_test_manifest()

    @property
    def manifest_path(self) -> Path:
        return self.root / "evals" / "test-generation-manifest.json"

    @property
    def state_path(self) -> Path:
        return self.root / "evals" / "release-gate.json"

    def test_paths(self) -> list[Path]:
        return sorted((self.root / "tests").glob("test_*.py"))

    def write_test_manifest(self) -> None:
        files = [
            {
                "generation": "v10" if "_v10_" in path.name else "v11",
                "path": path.relative_to(self.root).as_posix(),
                "sha256": sha256(path.read_bytes()),
            }
            for path in self.test_paths()
        ]
        write_json(
            self.manifest_path,
            {
                "schema_version": "1.0",
                "generation_rules": [
                    {"generation": "v10", "minimum": 1, "pattern": "tests/test_v10_*.py"},
                    {"generation": "v11", "minimum": 1, "pattern": "tests/test_v11_*.py"},
                ],
                "files": files,
            },
        )

    def artifacts(self) -> dict[str, str]:
        return {
            "runtime_sha256": sha256(
                (self.root / "scripts" / "identity_label_case.py").read_bytes()
            ),
            "schema_tree_sha256": tree_digest(
                self.root, list((self.root / "schemas").glob("*.json"))
            ),
            "tests_tree_sha256": tree_digest(self.root, self.test_paths()),
            "demo_tree_sha256": tree_digest(
                self.root,
                [self.root / "examples" / "real-run" / name for name in DEMO_FILES],
            ),
            "package_tree_sha256": "f" * 64,
            "governance_tree_sha256": tree_digest(
                self.root,
                [
                    self.root / "scripts" / "run_evolution.py",
                    self.root / "scripts" / "build_package.py",
                    self.root / "scripts" / "build_demo.py",
                    self.root / "evals" / "validate.py",
                    self.root / "scripts" / "worker.py",
                ],
            ),
            "workflow_sha256": sha256(self.workflow_path.read_bytes()),
        }

    def controller(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CONTROLLER),
                *args,
                "--root",
                str(self.root),
                "--state",
                str(self.state_path),
                "--test-manifest",
                str(self.manifest_path),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def complete_run(self, candidate_id: str, run_name: str) -> Path:
        run_dir = self.root / "evals" / "runs" / run_name
        result = self.controller(
            "run",
            "--workflow",
            str(self.workflow_path),
            "--run-dir",
            str(run_dir),
            "--run-id",
            run_name,
            "--candidate-id",
            candidate_id,
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        return run_dir

    def write_state(self, *, passed: bool) -> None:
        completed_run = self.complete_run("v11-fixture", "v11-fixture-run")
        original_manifest = self.manifest_path.read_bytes()
        synced = self.controller("sync-tests")
        if synced.returncode != 0:
            raise AssertionError(synced.stdout + synced.stderr)
        try:
            frozen = self.controller(
                "freeze",
                "--candidate-id",
                "v11-fixture",
                "--workflow",
                str(self.workflow_path),
                "--completed-run-dir",
                str(completed_run),
                "--clock",
                "2026-08-06T00:00:00Z",
            )
        finally:
            self.manifest_path.write_bytes(original_manifest)
        if frozen.returncode != 0:
            raise AssertionError(frozen.stdout + frozen.stderr)
        frozen_state = json.loads(self.state_path.read_text(encoding="utf-8"))
        frozen_state["test_manifest_sha256"] = sha256(original_manifest)
        artifacts = frozen_state["artifacts"]
        audits = []
        for audit_id in AUDIT_IDS:
            evidence: list[str] = []
            receipt_hash = None
            if passed:
                relative = f"evals/receipts/{audit_id}.json"
                receipt_id = f"receipt-{audit_id}"
                evidence_root = self.root / "evals" / "receipts" / receipt_id
                evidence_root.mkdir(parents=True, exist_ok=True)
                script_relative = f"audits/{audit_id}.py"
                script_path = self.root / script_relative
                script_path.parent.mkdir(parents=True, exist_ok=True)
                script_path.write_text("print('fixture audit pass')\n", encoding="utf-8")
                preregistration = {
                    "schema_version": "1.0",
                    "audit_id": audit_id,
                    "candidate_id": "v11-fixture",
                    "completed_run_sha256": frozen_state["completed_run"]["run_state_sha256"],
                    "objective": "Attempt to falsify the frozen fixture candidate.",
                    "commands": [
                        {
                            "argv": [script_relative],
                            "input_files": [
                                script_relative,
                                "evals/test-generation-manifest.json",
                            ],
                        }
                    ],
                    "pass_condition": "The preregistered fixture command exits zero.",
                    "live_model_called": False,
                }
                evidence_files = {
                    "environment.json": "{\"environment\":\"fixture\"}\n",
                    "command.stdout.txt": "OK\n",
                    "command.stderr.txt": "",
                    "raw-output.txt": "OK\n",
                }
                for name, content in evidence_files.items():
                    (evidence_root / name).write_text(content, encoding="utf-8")
                write_json(evidence_root / "preregistration.json", preregistration)
                evidence_prefix = f"evals/receipts/{receipt_id}"
                receipt = {
                    "schema_version": "1.2",
                    "receipt_id": receipt_id,
                    "audit_id": audit_id,
                    "candidate": {
                        "candidate_id": "v11-fixture",
                        "artifacts": artifacts,
                        "test_manifest_sha256": sha256(self.manifest_path.read_bytes()),
                    },
                    "completed_run": frozen_state["completed_run"],
                    "preregistration": {
                        "path": f"{evidence_prefix}/preregistration.json",
                        "case_set_sha256": sha256(
                            (evidence_root / "preregistration.json").read_bytes()
                        ),
                    },
                    "environment": {
                        "path": f"{evidence_prefix}/environment.json",
                        "sha256": sha256(
                            (evidence_root / "environment.json").read_bytes()
                        ),
                    },
                    "commands": [
                        {
                            "argv": [sys.executable, str(script_path.resolve())],
                            "script_path": script_relative,
                            "script_sha256": sha256(script_path.read_bytes()),
                            "input_snapshot": {
                                "cwd": ".",
                                "environment": {"PYTHONHASHSEED": "0"},
                                "files": [
                                    {
                                        "path": script_relative,
                                        "sha256": sha256(script_path.read_bytes()),
                                    },
                                    {
                                        "path": "evals/test-generation-manifest.json",
                                        "sha256": sha256(self.manifest_path.read_bytes()),
                                    },
                                ],
                            },
                            "exit_code": 0,
                            "stdout_path": f"{evidence_prefix}/command.stdout.txt",
                            "stdout_sha256": sha256(
                                (evidence_root / "command.stdout.txt").read_bytes()
                            ),
                            "stderr_path": f"{evidence_prefix}/command.stderr.txt",
                            "stderr_sha256": sha256(
                                (evidence_root / "command.stderr.txt").read_bytes()
                            ),
                        }
                    ],
                    "raw_output_path": f"{evidence_prefix}/raw-output.txt",
                    "raw_output_sha256": sha256(
                        (evidence_root / "raw-output.txt").read_bytes()
                    ),
                    "manual_findings": [],
                    "blockers": [],
                    "status": "passed",
                }
                write_json(self.root / relative, receipt)
                evidence = [relative]
                receipt_hash = sha256((self.root / relative).read_bytes())
            audits.append(
                {
                    "audit_id": audit_id,
                    "artifact_sha256": artifacts if passed else None,
                    "blocker_count": 0,
                    "evidence": evidence,
                    "receipt_sha256": receipt_hash,
                    "status": "passed" if passed else "pending",
                }
            )
        blockers = [] if passed else [
            {
                "evidence": "tests/test_v11_current.py",
                "id": "v11-red-suite",
                "severity": "P0",
            }
        ]
        frozen_state.update(
            {
                "iteration": 11,
                "audits": audits,
                "blockers": blockers,
                "blocker_count": len(blockers),
                "decision": "candidate" if passed else "blocked",
            }
        )
        write_json(self.state_path, frozen_state)


class V11EvolutionControllerTests(unittest.TestCase):
    def run_controller(
        self, fixture: EvolutionFixture, *args: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CONTROLLER),
                *args,
                "--root",
                str(fixture.root),
                "--state",
                str(fixture.state_path),
                "--test-manifest",
                str(fixture.manifest_path),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_development_check_consumes_an_honest_blocked_gate_without_failing(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v11-evolution-") as temp:
            fixture = EvolutionFixture(Path(temp))
            fixture.write_state(passed=False)

            result = self.run_controller(fixture, "check", "--allow-blocked")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("blocked", payload["effective_decision"])
            self.assertFalse(payload["release_eligible"])
            self.assertEqual(1, payload["blocker_count"])

            strict = self.run_controller(fixture, "check", "--strict-release")
            self.assertEqual(2, strict.returncode, strict.stdout + strict.stderr)

    def test_runtime_drift_invalidates_every_previously_passing_audit(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v11-drift-") as temp:
            fixture = EvolutionFixture(Path(temp))
            fixture.write_state(passed=True)
            (fixture.root / "scripts" / "identity_label_case.py").write_text(
                "print('changed runtime')\n", encoding="utf-8"
            )

            result = self.run_controller(fixture, "check", "--allow-blocked")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("invalid_run", payload["effective_decision"])
            self.assertFalse(payload["release_eligible"])
            self.assertIn("runtime_sha256_drift", payload["invalidations"])
            self.assertEqual(
                {"invalid_run"},
                {audit["effective_status"] for audit in payload["audits"]},
            )

    def test_test_manifest_detects_generation_deletion_and_hash_tampering(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v11-tests-") as temp:
            fixture = EvolutionFixture(Path(temp))
            fixture.write_state(passed=False)
            removed = fixture.root / "tests" / "test_v10_preserved.py"
            removed.unlink()

            missing = self.run_controller(fixture, "check", "--allow-blocked")
            self.assertEqual(3, missing.returncode, missing.stdout + missing.stderr)
            missing_payload = json.loads(missing.stdout)
            self.assertIn("test_manifest_missing_file", missing_payload["errors"])
            self.assertIn("test_generation_below_minimum:v10", missing_payload["errors"])

            removed.write_text("# tampered generation\n", encoding="utf-8")
            tampered = self.run_controller(fixture, "check", "--allow-blocked")
            self.assertEqual(3, tampered.returncode, tampered.stdout + tampered.stderr)
            self.assertIn("test_manifest_hash_mismatch", json.loads(tampered.stdout)["errors"])

    def test_zero_blockers_and_four_current_audits_are_required_for_release(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v11-release-") as temp:
            fixture = EvolutionFixture(Path(temp))
            fixture.write_state(passed=True)

            result = self.run_controller(fixture, "check", "--strict-release")
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual("candidate", payload["effective_decision"])
            self.assertTrue(payload["release_eligible"])
            self.assertEqual(0, payload["blocker_count"])

            state = json.loads(fixture.state_path.read_text(encoding="utf-8"))
            state["audits"][0]["status"] = "pending"
            state["audits"][0]["artifact_sha256"] = None
            state["audits"][0]["evidence"] = []
            state["audits"][0]["receipt_sha256"] = None
            state["decision"] = "pending"
            write_json(fixture.state_path, state)
            pending = self.run_controller(fixture, "check", "--strict-release")
            self.assertEqual(2, pending.returncode, pending.stdout + pending.stderr)
            self.assertEqual("pending", json.loads(pending.stdout)["effective_decision"])

    def test_freeze_resets_audits_and_cannot_claim_candidate(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v11-freeze-") as temp:
            fixture = EvolutionFixture(Path(temp))
            fixture.write_state(passed=True)
            (fixture.root / "scripts" / "identity_label_case.py").write_text(
                "print('next candidate')\n", encoding="utf-8"
            )
            completed_run = fixture.complete_run("v12-red", "v12-red-run")

            result = self.run_controller(
                fixture,
                "freeze",
                "--candidate-id",
                "v12-red",
                "--workflow",
                str(fixture.workflow_path),
                "--completed-run-dir",
                str(completed_run),
                "--clock",
                "2026-08-07T00:00:00Z",
                "--blocker",
                "v12-red-suite:P0:tests/test_v11_current.py",
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            state = json.loads(fixture.state_path.read_text(encoding="utf-8"))
            self.assertEqual("blocked", state["decision"])
            self.assertEqual(1, state["blocker_count"])
            self.assertEqual(
                {"pending"}, {audit["status"] for audit in state["audits"]}
            )
            self.assertNotEqual(
                fixture.artifacts()["runtime_sha256"],
                sha256(b"print('runtime')\n"),
            )

    def test_package_contract_wires_controller_schema_and_strict_release_gate(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        workflow = (ROOT / "workflows" / "v2-evolution.yaml").read_text(encoding="utf-8")
        validator = (ROOT / "evals" / "validate.py").read_text(encoding="utf-8")
        for relative in (
            "scripts/run_evolution.py",
            "schemas/release-gate.schema.json",
            "evals/test-generation-manifest.json",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)
        self.assertIn("evolution-gate:", makefile)
        self.assertIn("release-gate:", makefile)
        self.assertIn("--strict-release", makefile)
        self.assertIn("executable_controller:", workflow)
        self.assertIn("scripts/run_evolution.py", workflow)
        self.assertIn("test-generation-manifest.json", validator)


if __name__ == "__main__":
    unittest.main()
