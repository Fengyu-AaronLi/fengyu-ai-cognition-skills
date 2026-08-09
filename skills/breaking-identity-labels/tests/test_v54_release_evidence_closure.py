#!/usr/bin/env python3
"""V54 contracts for portable red evidence and byte-bound release execution."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflows" / "v51-final-release.json"
RED_VERIFIER = ROOT / "scripts" / "verify_red_evidence.py"
REGRESSION_RUNNER = ROOT / "scripts" / "run_regressions.py"
AUDIT_HARNESS = ROOT / "scripts" / "run_release_audits.py"
PACKAGE_BUILDER = ROOT / "scripts" / "build_package.py"
PACKAGE_EQUIVALENCE = ROOT / "scripts" / "verify_package_equivalence.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FinalWorkflowInputClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
        cls.steps = {step["id"]: step for step in cls.workflow["steps"]}
        cls.package_module = load_module("v54_package_builder", PACKAGE_BUILDER)
        cls.package_sources = {
            source.relative_to(ROOT).as_posix()
            for _destination, source in cls.package_module.PACKAGE_FILES
        }
        cls.package_destinations = {
            destination for destination, _source in cls.package_module.PACKAGE_FILES
        }

    def inputs(self, step_id: str) -> set[str]:
        return set(self.steps[step_id].get("input_files", []))

    def test_historical_red_step_binds_the_historical_workflow(self) -> None:
        self.assertIn(
            "workflows/v15-evolution.json",
            self.inputs("historical_red_evidence_verify"),
        )

    def test_full_regression_binds_and_explicitly_consumes_the_manifest(self) -> None:
        declared = self.inputs("full_regression")
        self.assertIn("evals/test-generation-manifest.json", declared)
        argv = self.steps["full_regression"]["argv"]
        self.assertIn("--test-manifest", argv)
        self.assertIn("{root}/evals/test-generation-manifest.json", argv)

    def test_eval_and_demo_steps_bind_every_runtime_schema_they_read(self) -> None:
        runtime_schemas = {
            "schemas/analysis.schema.json",
            "schemas/case.schema.json",
            "schemas/event-head.schema.json",
            "schemas/event.schema.json",
            "schemas/workflow-next.schema.json",
        }
        self.assertIn(
            "tests/fixtures/valid-c01.json",
            self.inputs("offline_eval"),
        )
        for step_id in ("offline_eval", "demo_build", "demo_verify"):
            self.assertTrue(runtime_schemas <= self.inputs(step_id), step_id)
        required_demo_sources = {
            "SKILL.md",
            "VERSION",
            "scripts/identity_label_case.py",
            "examples/real-run/demo-input.txt",
            "examples/real-run/analysis.json",
        }
        self.assertTrue(required_demo_sources <= self.inputs("demo_verify"))

    def test_package_build_binds_every_allowlisted_source(self) -> None:
        self.assertTrue(self.package_sources <= self.inputs("package_build"))

    def test_package_verification_and_install_bind_exact_generated_bytes(self) -> None:
        packaged = {
            f"{{run_dir}}/package/{path}" for path in self.package_destinations
        } | {"{run_dir}/package/PACKAGE-MANIFEST.json"}
        installed = {
            f"{{run_dir}}/installed-skills/breaking-identity-labels/{path}"
            for path in self.package_destinations
        } | {
            "{run_dir}/installed-skills/breaking-identity-labels/PACKAGE-MANIFEST.json"
        }
        archive = {"{run_dir}/breaking-identity-labels.zip"}
        self.assertEqual(packaged, self.inputs("package_verify_directory"))
        self.assertEqual(archive, self.inputs("package_verify_archive"))
        self.assertEqual(archive, self.inputs("package_install"))
        self.assertEqual(installed, self.inputs("package_verify_installed"))
        self.assertEqual(
            packaged | archive | installed,
            self.inputs("package_equivalence"),
        )


class RegisteredRegressionManifestTests(unittest.TestCase):
    def test_runner_resolves_the_exact_registered_hash_bound_file_set(self) -> None:
        module = load_module("v54_regression_runner", REGRESSION_RUNNER)
        manifest = ROOT / "evals" / "test-generation-manifest.json"
        registered = module.registered_test_paths(manifest)
        actual = sorted(
            path.relative_to(ROOT).as_posix()
            for path in (ROOT / "tests").glob("test_*.py")
            if path.is_file() and not path.is_symlink()
        )
        self.assertEqual(actual, registered)

        payload = json.loads(manifest.read_text(encoding="utf-8"))
        payload["files"] = payload["files"][:-1]
        with tempfile.TemporaryDirectory(prefix="identity-v54-manifest-") as temp:
            changed = Path(temp) / "manifest.json"
            write_json(changed, payload)
            with self.assertRaises(module.RegressionManifestError):
                module.registered_test_paths(changed)


class PortableRedEvidenceTests(unittest.TestCase):
    def fixture(self, root: Path, historical_test_path: str) -> tuple[Path, Path, Path]:
        test_relative = "tests/test_v54_portable_contract.py"
        test_path = root / test_relative
        test_path.parent.mkdir(parents=True)
        test_path.write_text("# current registered successor\n", encoding="utf-8")
        workflow = root / "workflows" / "v54-red.json"
        write_json(
            workflow,
            {"schema_version": "1.0", "workflow_id": "v54-red", "steps": []},
        )
        manifest = root / "evals" / "test-generation-manifest.json"
        write_json(
            manifest,
            {
                "schema_version": "1.0",
                "files": [
                    {
                        "generation": "v54",
                        "path": test_relative,
                        "sha256": digest(test_path),
                    }
                ],
            },
        )
        run_dir = root / "evals" / "runs" / "red"
        stdout = run_dir / "raw" / "red.stdout.txt"
        stderr = run_dir / "raw" / "red.stderr.txt"
        stdout.parent.mkdir(parents=True)
        stdout.write_text("", encoding="utf-8")
        stderr.write_text(
            "Ran 1 test in 0.001s\n\nFAILED (failures=1)\n",
            encoding="utf-8",
        )
        receipt = run_dir / "receipts" / "red.json"
        write_json(
            receipt,
            {
                "schema_version": "1.0",
                "run_id": "red",
                "candidate_id": "candidate-red",
                "workflow_sha256": digest(workflow),
                "step_id": "red",
                "kind": "command",
                "argv": [sys.executable, historical_test_path, "-v"],
                "exit_code": 1,
                "assertion": "red",
                "assertion_passed": False,
                "stdout_path": "evals/runs/red/raw/red.stdout.txt",
                "stdout_sha256": digest(stdout),
                "stderr_path": "evals/runs/red/raw/red.stderr.txt",
                "stderr_sha256": digest(stderr),
                "recorded_at": "2026-08-06T00:00:00Z",
            },
        )
        write_json(
            run_dir / "run-state.json",
            {
                "schema_version": "1.0",
                "run_id": "red",
                "candidate_id": "candidate-red",
                "workflow_path": "workflows/v54-red.json",
                "workflow_sha256": digest(workflow),
                "status": "failed",
                "steps": {
                    "red": {
                        "kind": "command",
                        "status": "failed",
                        "receipt_path": "evals/runs/red/receipts/red.json",
                        "receipt_sha256": digest(receipt),
                    }
                },
            },
        )
        return run_dir, test_path, manifest

    def verify(
        self, root: Path, run_dir: Path, test_path: Path, manifest: Path
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(RED_VERIFIER),
                "--root",
                str(root),
                "--run-dir",
                str(run_dir),
                "--step-id",
                "red",
                "--test-path",
                str(test_path),
                "--test-manifest",
                str(manifest),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_accepts_a_historical_absolute_path_from_a_different_checkout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v54-portable-red-") as temp:
            root = Path(temp)
            historical = (
                "/historical/checkout/skills/breaking-identity-labels/"
                "tests/test_v54_portable_contract.py"
            )
            run_dir, test_path, manifest = self.fixture(root, historical)
            result = self.verify(root, run_dir, test_path, manifest)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual(historical, payload["historical_test_path"])
            self.assertEqual(
                "tests/test_v54_portable_contract.py",
                payload["test_path"],
            )

    def test_rejects_a_historical_path_for_a_different_test(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v54-wrong-red-") as temp:
            root = Path(temp)
            run_dir, test_path, manifest = self.fixture(
                root,
                "/historical/checkout/tests/test_other_contract.py",
            )
            result = self.verify(root, run_dir, test_path, manifest)
            self.assertEqual(3, result.returncode, result.stdout + result.stderr)
            self.assertIn("red_evidence_receipt_binding_invalid", result.stdout)


class PackageAuditClosureTests(unittest.TestCase):
    def test_release_audit_preregisters_install_and_tree_equivalence(self) -> None:
        module = load_module("v54_audit_harness", AUDIT_HARNESS)
        suite = module.AUDIT_SUITES["release_package_audit"]
        flattened = [" ".join(command) for command in suite]
        self.assertTrue(any(" install " in f" {command} " for command in flattened))
        self.assertTrue(
            any("verify_package_equivalence.py" in command for command in flattened)
        )
        with tempfile.TemporaryDirectory(
            prefix="identity-v54-audit-inputs-", dir=ROOT
        ) as temp:
            evidence_dir = Path(temp)
            build_index = next(
                index
                for index, command in enumerate(suite)
                if command[0] == "scripts/build_package.py" and "build" in command
            )
            declared = module.audit_input_paths(
                "release_package_audit",
                build_index,
                suite[build_index],
                evidence_dir,
                require_available=True,
            )
            package_module = load_module("v54_package_sources", PACKAGE_BUILDER)
            expected = {
                source.resolve() for _destination, source in package_module.PACKAGE_FILES
            } | {PACKAGE_BUILDER.resolve()}
            self.assertEqual(expected, set(declared))

    def test_directory_zip_and_installed_copy_must_share_one_tree_digest(self) -> None:
        self.assertTrue(PACKAGE_EQUIVALENCE.is_file())
        with tempfile.TemporaryDirectory(prefix="identity-v54-package-") as temp:
            root = Path(temp)
            package = root / "package"
            archive = root / "breaking-identity-labels.zip"
            skills = root / "skills"
            built = subprocess.run(
                [
                    sys.executable,
                    str(PACKAGE_BUILDER),
                    "build",
                    "--out",
                    str(package),
                    "--archive",
                    str(archive),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, built.returncode, built.stdout + built.stderr)
            installed = subprocess.run(
                [
                    sys.executable,
                    str(PACKAGE_BUILDER),
                    "install",
                    "--package",
                    str(archive),
                    "--skills-dir",
                    str(skills),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, installed.returncode, installed.stdout + installed.stderr)
            command = [
                sys.executable,
                str(PACKAGE_EQUIVALENCE),
                "--directory",
                str(package),
                "--archive",
                str(archive),
                "--installed",
                str(skills / "breaking-identity-labels"),
            ]
            verified = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, verified.returncode, verified.stdout + verified.stderr)
            self.assertTrue(json.loads(verified.stdout)["valid"])

            skill_file = skills / "breaking-identity-labels" / "SKILL.md"
            skill_file.write_text(
                skill_file.read_text(encoding="utf-8") + "\nforged\n",
                encoding="utf-8",
            )
            rejected = subprocess.run(
                command,
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, rejected.returncode)


if __name__ == "__main__":
    unittest.main()
