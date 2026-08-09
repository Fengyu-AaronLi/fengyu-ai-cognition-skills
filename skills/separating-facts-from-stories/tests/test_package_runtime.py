import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
PACKAGER = SKILL_DIR / "scripts" / "package_runtime.py"
SKILL_NAME = "separating-facts-from-stories"


def load_packager():
    spec = importlib.util.spec_from_file_location("package_runtime_test", PACKAGER)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def release_bound_unit_gate(module, release_evidence, scope):
    modules = sorted(module.REQUIRED_TEST_FILES)
    by_path = {
        item["path"]: item["sha256"] for item in release_evidence.values()
    }
    source_files = sorted(
        path.removeprefix("tests/")
        for path in by_path
        if path.startswith("tests/") and path.endswith(".py")
    )
    source_hashes = {
        name: by_path[f"tests/{name}"] for name in source_files
    }
    source_set_sha256 = hashlib.sha256(
        json.dumps(
            source_hashes,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    counts = {name: 1 for name in modules}
    return {
        "exit_code": 0,
        "test_modules": modules,
        "test_module_count": len(modules),
        "module_test_counts": counts,
        "tests_run": sum(counts.values()),
        "test_source_files": source_files,
        "test_source_count": len(source_files),
        "test_source_set_sha256": source_set_sha256,
        "isolated_python": True,
        "site_disabled": True,
        "bytecode_cache_isolated": True,
        "isolation_flags": [
            "-I",
            "-S",
            "-B",
            "-X",
            "pycache_prefix=<ephemeral>",
        ],
        "unittest_module_path": str(Path(unittest.__file__).resolve()),
        "scope": scope,
    }


class RuntimePackagingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_packager()

    def test_cli_requires_eval_root_and_creates_no_destination(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target_root = Path(temp_dir) / "skills"
            completed = subprocess.run(
                [sys.executable, str(PACKAGER), "--target-root", str(target_root)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("EVAL_ROOT_REQUIRED", completed.stderr)
            self.assertFalse((target_root / SKILL_NAME).exists())

    def test_incomplete_eval_root_blocks_install(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_root = root / "skills"
            eval_root = root / "incomplete-eval"
            eval_root.mkdir()
            completed = subprocess.run(
                [
                    sys.executable,
                    str(PACKAGER),
                    "--target-root",
                    str(target_root),
                    "--eval-root",
                    str(eval_root),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("EVAL_GATE_FAILED", completed.stderr)
            self.assertFalse((target_root / SKILL_NAME).exists())

    def test_eval_report_contract_rejects_partial_or_failed_runs(self):
        bad = {
            "valid": True,
            "expected_case_count": 18,
            "completed_case_count": 17,
            "expected_artifact_count": 16,
            "artifact_count": 16,
            "passed": 16,
            "failed": 0,
            "suite_errors": [],
        }
        with self.assertRaisesRegex(OSError, "EVAL_GATE_FAILED"):
            self.module.validate_eval_report(bad)

    def test_packager_rejects_report_created_before_release_source_changes(self):
        changed_release_sources = (
            "SKILL.md",
            "scripts/casefile.py",
            "schemas/casefile.schema.json",
            "scripts/workflow.py",
        )
        for changed_relative in changed_release_sources:
            with self.subTest(changed_release_source=changed_relative):
                with tempfile.TemporaryDirectory() as temp_dir:
                    root = Path(temp_dir)
                    source = root / SKILL_NAME
                    shutil.copytree(SKILL_DIR, source)
                    eval_root = root / "eval"
                    eval_root.mkdir()
                    report_path = eval_root / "machine-report.json"
                    release_evidence = {
                        name: {
                            "path": relative,
                            "sha256": hashlib.sha256(
                                (source / relative).read_bytes()
                            ).hexdigest(),
                        }
                        for name, relative in self.module.RELEASE_EVIDENCE_FILES.items()
                    }
                    report = {
                        "valid": True,
                        "expected_case_count": 18,
                        "completed_case_count": 18,
                        "expected_artifact_count": 16,
                        "artifact_count": 16,
                        "passed": 16,
                        "failed": 0,
                        "suite_errors": [],
                        "missing_cases": [],
                        "evaluation_context_sha256": "a" * 64,
                        "results": [{"valid": True}] * 16,
                        "case_results": [{"valid": True}] * 18,
                        "release_evidence": release_evidence,
                    }
                    report_path.write_text(
                        json.dumps(report, ensure_ascii=False), encoding="utf-8"
                    )

                    changed_path = source / changed_relative
                    changed_path.write_bytes(changed_path.read_bytes() + b"\n")
                    eval_gate = {
                        "report": report,
                        "report_path": str(report_path),
                        "report_sha256": hashlib.sha256(
                            report_path.read_bytes()
                        ).hexdigest(),
                    }
                    runtime_stub = mock.Mock(
                        SKILL_VERSION="test",
                        SCHEMA_VERSION="test",
                        VALIDATOR_VERSION="test",
                    )
                    with mock.patch.object(
                        self.module,
                        "preflight",
                        return_value=(runtime_stub, {"identity_match": True}),
                    ), mock.patch.object(
                        self.module,
                        "run_unit_test_gate",
                        return_value={
                            "exit_code": 0,
                            "tests_run": 1,
                            "scope": "release-source-binding-red-test",
                        },
                    ), mock.patch.object(
                        self.module, "run_eval_gate", return_value=eval_gate
                    ):
                        with self.assertRaisesRegex(
                            OSError, "EVAL_SOURCE_HASH_MISMATCH"
                        ):
                            self.module.package_runtime(
                                source, root / "installed-skills", eval_root
                            )

    def test_runtime_allowlist_manifest_verify_and_identity(self):
        self.assertTrue(PACKAGER.exists(), f"missing runtime packager: {PACKAGER}")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target_root = root / ".agents" / "skills"
            eval_root = root / "eval"
            eval_root.mkdir()
            report_path = eval_root / "machine-report.json"
            release_evidence = {
                name: {
                    "path": relative,
                    "sha256": hashlib.sha256(
                        (SKILL_DIR / relative).read_bytes()
                    ).hexdigest(),
                }
                for name, relative in self.module.RELEASE_EVIDENCE_FILES.items()
            }
            context_path = eval_root / "evaluation-context.json"
            context_path.write_text(
                json.dumps({"release_evidence": release_evidence}),
                encoding="utf-8",
            )
            context_sha256 = hashlib.sha256(context_path.read_bytes()).hexdigest()
            report_path.write_text(
                json.dumps(
                    {
                        "valid": True,
                        "expected_case_count": 18,
                        "completed_case_count": 18,
                        "expected_artifact_count": 16,
                        "artifact_count": 16,
                        "passed": 16,
                        "failed": 0,
                        "suite_errors": [],
                        "missing_cases": [],
                        "evaluation_context_sha256": context_sha256,
                        "results": [{"valid": True}] * 16,
                        "case_results": [{"valid": True}] * 18,
                        "release_evidence": release_evidence,
                    }
                ),
                encoding="utf-8",
            )
            unit_gate = release_bound_unit_gate(
                self.module, release_evidence, "runtime-contract"
            )
            eval_gate = {
                "report": json.loads(report_path.read_text(encoding="utf-8")),
                "report_path": str(report_path),
                "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
                "context_path": str(context_path),
                "context_sha256": context_sha256,
                "isolated_python": True,
                "site_disabled": True,
                "bytecode_writes_disabled": True,
                "isolation_flags": ["-I", "-S", "-B"],
                "runner_path": "scripts/run_evals.py",
                "runner_sha256": release_evidence["eval_runner"]["sha256"],
            }
            with mock.patch.object(
                self.module, "run_unit_test_gate", return_value=unit_gate
            ), mock.patch.object(
                self.module, "run_eval_gate", return_value=eval_gate
            ):
                installed = self.module.package_runtime(
                    SKILL_DIR, target_root, eval_root
                )

            expected = {
                "SKILL.md",
                "README.md",
                "LICENSE",
                "CC-BY-NC-4.0-LEGALCODE.txt",
                "NOTICE.md",
                "PROVENANCE.md",
                "problem-spec.md",
                "upstream-audit.md",
                "zero-threshold-prompt.md",
                "evals/legacy-migration-corpus.json",
                "scripts/casefile.py",
                "scripts/workflow.py",
                "scripts/package_runtime.py",
                "schemas/casefile.schema.json",
                "references/claim-taxonomy.md",
                "references/casefile-contract.md",
                "references/evidence-and-hypotheses.md",
                "references/safety-routing.md",
                "references/workflow-loop.md",
                "evidence/machine-report.json",
                "evidence/evaluation-context.json",
                "runtime-manifest.json",
            }
            actual = {
                str(path.relative_to(installed))
                for path in installed.rglob("*")
                if path.is_file()
            }
            self.assertEqual(expected, actual)
            manifest = json.loads(
                (installed / "runtime-manifest.json").read_text(encoding="utf-8")
            )
            self.assertEqual(SKILL_NAME, manifest["skill"])
            self.assertTrue(manifest["preflight"]["identity_match"])
            self.assertEqual(unit_gate, manifest["release_gate"]["unit_tests"])
            self.assertEqual(18, manifest["release_gate"]["eval"]["completed_case_count"])
            for relative, digest in manifest["files"].items():
                content = (installed / relative).read_bytes()
                self.assertEqual(digest, hashlib.sha256(content).hexdigest())

            verification = self.module.verify_install(installed)
            self.assertTrue(verification["valid"], verification)
            cli_verify = subprocess.run(
                [sys.executable, str(PACKAGER), "--verify", str(installed)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, cli_verify.returncode, cli_verify.stderr)
            workflow_help = subprocess.run(
                [
                    sys.executable,
                    str(installed / "scripts" / "workflow.py"),
                    "--help",
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, workflow_help.returncode, workflow_help.stderr)
            self.assertIn("bounded fact-story separation workflow", workflow_help.stdout)

            (installed / "SKILL.md").write_text(
                (installed / "SKILL.md").read_text(encoding="utf-8") + "\nchanged\n",
                encoding="utf-8",
            )
            tampered = self.module.verify_install(installed)
            self.assertFalse(tampered["valid"])
            self.assertIn("HASH_MISMATCH", {item["code"] for item in tampered["errors"]})


if __name__ == "__main__":
    unittest.main()
