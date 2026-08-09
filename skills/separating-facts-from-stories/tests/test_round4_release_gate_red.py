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
RUNNER = SKILL_DIR / "scripts" / "run_evals.py"
SKILL_NAME = "separating-facts-from-stories"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Round4ReleaseGateRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.packager = load_module("round4_package_runtime", PACKAGER)
        cls.runner = load_module("round4_run_evals", RUNNER)

    def _release_report(self, source: Path) -> dict:
        release_evidence = {
            name: {
                "path": relative,
                "sha256": hashlib.sha256((source / relative).read_bytes()).hexdigest(),
            }
            for name, relative in self.packager.RELEASE_EVIDENCE_FILES.items()
        }
        return {
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

    def _make_installed_tree(self, root: Path, *, help_only_workflow: bool = False) -> Path:
        installed = root / SKILL_NAME
        for relative in self.packager.RUNTIME_FILES:
            source = SKILL_DIR / relative
            target = installed / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        if help_only_workflow:
            (installed / "scripts" / "workflow.py").write_text(
                """#!/usr/bin/env python3
import sys
WORKFLOW_VERSION = "2.1.0"
if '-h' in sys.argv or '--help' in sys.argv:
    print('Run the bounded fact-story separation workflow.')
    raise SystemExit(0)
raise SystemExit(97)
""",
                encoding="utf-8",
            )
        runtime = self.runner.CASEFILE
        release_sources = {}
        for name, relative in self.packager.RELEASE_EVIDENCE_FILES.items():
            candidate = installed / relative
            if not candidate.is_file():
                candidate = SKILL_DIR / relative
            release_sources[name] = {
                "path": relative,
                "sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
            }
        context_path = installed / self.packager.PACKAGED_EVIDENCE_FILES[1]
        context_path.parent.mkdir(parents=True, exist_ok=True)
        context_path.write_text(
            json.dumps({"release_evidence": release_sources}, ensure_ascii=False),
            encoding="utf-8",
        )
        machine_report = self._release_report(SKILL_DIR)
        machine_report["release_evidence"] = release_sources
        machine_report["evaluation_context_sha256"] = hashlib.sha256(
            context_path.read_bytes()
        ).hexdigest()
        machine_report_path = installed / self.packager.PACKAGED_EVIDENCE_FILES[0]
        machine_report_path.parent.mkdir(parents=True, exist_ok=True)
        machine_report_path.write_text(
            json.dumps(machine_report, ensure_ascii=False), encoding="utf-8"
        )
        release_evidence = dict(release_sources)
        release_evidence["machine_report"] = {
            "path": self.packager.PACKAGED_EVIDENCE_FILES[0],
            "sha256": hashlib.sha256(machine_report_path.read_bytes()).hexdigest(),
        }
        release_evidence["evaluation_context"] = {
            "path": self.packager.PACKAGED_EVIDENCE_FILES[1],
            "sha256": hashlib.sha256(context_path.read_bytes()).hexdigest(),
        }
        test_modules = sorted(self.packager.REQUIRED_TEST_FILES)
        test_source_files = sorted(
            Path(relative).relative_to("tests").as_posix()
            for relative in self.packager.RELEASE_EVIDENCE_FILES.values()
            if relative.startswith("tests/") and relative.endswith(".py")
        )
        test_source_hashes = {
            module: release_sources[
                next(
                    name
                    for name, relative in self.packager.RELEASE_EVIDENCE_FILES.items()
                    if relative == f"tests/{module}"
                )
            ]["sha256"]
            for module in test_source_files
        }
        test_source_set_sha256 = hashlib.sha256(
            json.dumps(
                test_source_hashes,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        module_test_counts = {module: 1 for module in test_modules}
        workflow_version = self.packager.read_python_string_constant(
            installed / "scripts" / "workflow.py", "WORKFLOW_VERSION"
        )
        manifest = {
            "skill": SKILL_NAME,
            "skill_version": runtime.SKILL_VERSION,
            "schema_version": runtime.SCHEMA_VERSION,
            "validator_version": runtime.VALIDATOR_VERSION,
            "workflow_version": workflow_version,
            "preflight": {
                "schema_json": True,
                "cli_help_exit": 0,
                "self_test_exit": 0,
                "workflow_help_exit": 0,
                "workflow_lifecycle": {
                    "exit_codes": {
                        "start": 0,
                        "check": 0,
                        "finalize": 0,
                        "status": 0,
                    },
                    "completed": True,
                    "integrity_valid": True,
                    "workflow_version": workflow_version,
                },
                "skill_version": runtime.SKILL_VERSION,
                "schema_version": runtime.SCHEMA_VERSION,
                "validator_version": runtime.VALIDATOR_VERSION,
                "workflow_version": workflow_version,
                "versions_match": True,
                "identity_match": True,
                "packaged_markdown_links_valid": True,
            },
            "release_gate": {
                "unit_tests": {
                    "exit_code": 0,
                    "test_modules": test_modules,
                    "test_module_count": len(test_modules),
                    "module_test_counts": module_test_counts,
                    "tests_run": sum(module_test_counts.values()),
                    "test_source_files": test_source_files,
                    "test_source_count": len(test_source_files),
                    "test_source_set_sha256": test_source_set_sha256,
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
                    "unittest_module_path": str(
                        Path(unittest.__file__).resolve()
                    ),
                    "scope": "round4 isolated fixture",
                },
                "eval_replay": {
                    "isolated_python": True,
                    "site_disabled": True,
                    "bytecode_writes_disabled": True,
                    "isolation_flags": ["-I", "-S", "-B"],
                    "runner_path": "scripts/run_evals.py",
                    "runner_sha256": release_sources["eval_runner"]["sha256"],
                },
                "eval": {
                    key: machine_report[key]
                    for key in (
                        "valid",
                        "expected_case_count",
                        "completed_case_count",
                        "expected_artifact_count",
                        "artifact_count",
                        "passed",
                        "failed",
                        "suite_errors",
                        "missing_cases",
                        "evaluation_context_sha256",
                    )
                },
            },
            "release_evidence": release_evidence,
            "files": {
                relative: hashlib.sha256((installed / relative).read_bytes()).hexdigest()
                for relative in (
                    *self.packager.RUNTIME_FILES,
                    *self.packager.PACKAGED_EVIDENCE_FILES,
                )
            },
        }
        (installed / "runtime-manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return installed

    def test_release_report_binds_every_behavior_and_release_gate_source(self):
        required = {
            "SKILL.md",
            "zero-threshold-prompt.md",
            "scripts/casefile.py",
            "scripts/workflow.py",
            "scripts/run_evals.py",
            "scripts/package_runtime.py",
            "schemas/casefile.schema.json",
            "references/claim-taxonomy.md",
            "references/casefile-contract.md",
            "references/evidence-and-hypotheses.md",
            "references/safety-routing.md",
            "references/workflow-loop.md",
            "evals/cases.json",
            "evals/capability-cases.json",
            "evals/fixtures/invalid-epistemic.json",
        }
        actual = set(self.packager.RELEASE_EVIDENCE_FILES.values())
        self.assertTrue(
            required.issubset(actual),
            f"release report leaves behavior-bearing files unbound: {sorted(required - actual)}",
        )

    def test_every_discovered_test_is_required_and_release_bound(self):
        tests_dir = SKILL_DIR / "tests"
        discovered = {
            str(path.relative_to(tests_dir))
            for path in tests_dir.rglob("test_*.py")
            if path.is_file() and not path.is_symlink()
        }
        discovered_sources = {
            str(path.relative_to(tests_dir))
            for path in tests_dir.rglob("*.py")
            if path.is_file() and not path.is_symlink()
        }
        release_bound = {
            str(Path(relative).relative_to("tests"))
            for relative in self.packager.RELEASE_EVIDENCE_FILES.values()
            if relative.startswith("tests/")
        }
        self.assertEqual(discovered, self.packager.REQUIRED_TEST_FILES)
        self.assertEqual(discovered_sources, release_bound)
        self.assertEqual(
            self.packager.RELEASE_EVIDENCE_FILES,
            self.runner.RELEASE_EVIDENCE_FILES,
        )

    def test_unit_gate_rejects_an_unbound_extra_test_module(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / SKILL_NAME
            shutil.copytree(SKILL_DIR, source)
            (source / "tests" / "test_unbound_extra.py").write_text(
                "import unittest\n\n"
                "class ExtraTest(unittest.TestCase):\n"
                "    def test_passes(self):\n"
                "        self.assertTrue(True)\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(OSError, "unbound test modules"):
                self.packager.run_unit_test_gate(source)

    def test_source_mutation_during_unit_gate_cannot_be_installed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / SKILL_NAME
            shutil.copytree(SKILL_DIR, source)
            report = self._release_report(source)
            report_path = root / "eval" / "machine-report.json"
            report_path.parent.mkdir()
            context_path = report_path.parent / "evaluation-context.json"
            context_path.write_text(
                json.dumps({"release_evidence": report["release_evidence"]}),
                encoding="utf-8",
            )
            report["evaluation_context_sha256"] = hashlib.sha256(
                context_path.read_bytes()
            ).hexdigest()
            report_path.write_text(json.dumps(report), encoding="utf-8")
            eval_gate = {
                "report": report,
                "report_path": str(report_path),
                "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
                "context_path": str(context_path),
                "context_sha256": hashlib.sha256(context_path.read_bytes()).hexdigest(),
            }
            runtime_stub = mock.Mock(
                SKILL_VERSION="test",
                SCHEMA_VERSION="test",
                VALIDATOR_VERSION="test",
            )

            def mutate_after_eval(_source: Path) -> dict:
                workflow = source / "scripts" / "workflow.py"
                workflow.write_bytes(workflow.read_bytes() + b"\n# changed after eval\n")
                return {"exit_code": 0, "tests_run": 1, "scope": "mutating-test"}

            with mock.patch.object(
                self.packager,
                "preflight",
                return_value=(runtime_stub, {"identity_match": True}),
            ), mock.patch.object(
                self.packager, "run_eval_gate", return_value=eval_gate
            ), mock.patch.object(
                self.packager, "run_unit_test_gate", side_effect=mutate_after_eval
            ):
                with self.assertRaisesRegex(OSError, "EVAL_SOURCE_HASH_MISMATCH"):
                    self.packager.package_runtime(
                        source, root / "installed-skills", report_path.parent
                    )

    def test_source_mutation_during_copy_cannot_be_installed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / SKILL_NAME
            shutil.copytree(SKILL_DIR, source)
            report = self._release_report(source)
            report_path = root / "eval" / "machine-report.json"
            report_path.parent.mkdir()
            context_path = report_path.parent / "evaluation-context.json"
            context_path.write_text(
                json.dumps({"release_evidence": report["release_evidence"]}),
                encoding="utf-8",
            )
            report["evaluation_context_sha256"] = hashlib.sha256(
                context_path.read_bytes()
            ).hexdigest()
            report_path.write_text(json.dumps(report), encoding="utf-8")
            eval_gate = {
                "report": report,
                "report_path": str(report_path),
                "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
                "context_path": str(context_path),
                "context_sha256": hashlib.sha256(context_path.read_bytes()).hexdigest(),
            }
            runtime_stub = mock.Mock(
                SKILL_VERSION="test",
                SCHEMA_VERSION="test",
                VALIDATOR_VERSION="test",
            )
            original_copy = shutil.copy2
            mutated = False

            def mutate_just_before_copy(source_file, target_file, *args, **kwargs):
                nonlocal mutated
                source_path = Path(source_file)
                if not mutated and source_path == source / "scripts" / "workflow.py":
                    source_path.write_bytes(
                        source_path.read_bytes() + b"\n# changed during copy\n"
                    )
                    mutated = True
                return original_copy(source_file, target_file, *args, **kwargs)

            with mock.patch.object(
                self.packager,
                "preflight",
                return_value=(runtime_stub, {"identity_match": True}),
            ), mock.patch.object(
                self.packager, "run_eval_gate", return_value=eval_gate
            ), mock.patch.object(
                self.packager,
                "run_unit_test_gate",
                return_value={"exit_code": 0, "tests_run": 1, "scope": "copy-race"},
            ), mock.patch.object(
                self.packager.shutil, "copy2", side_effect=mutate_just_before_copy
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "EVAL_SOURCE_HASH_MISMATCH|COPY_HASH_MISMATCH|RELEASE_EVIDENCE_MISMATCH",
                ):
                    self.packager.package_runtime(
                        source, root / "installed-skills", report_path.parent
                    )

    def test_unit_gate_cannot_hide_a_failing_packager_test_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir)
            tests = source / "tests"
            tests.mkdir()
            (tests / "test_runtime_guard.py").write_text(
                """import unittest
class RuntimeGuard(unittest.TestCase):
    def test_green(self):
        self.assertTrue(True)
""",
                encoding="utf-8",
            )
            (tests / "test_package_runtime.py").write_text(
                """import unittest
class PackagingGuard(unittest.TestCase):
    def test_release_blocker(self):
        self.fail('packaging release blocker')
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(OSError, "UNIT_TEST_GATE_FAILED"):
                self.packager.run_unit_test_gate(source)

    def test_unit_gate_rejects_missing_critical_test_modules(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir)
            tests = source / "tests"
            tests.mkdir()
            (tests / "test_one_green.py").write_text(
                """import unittest
class OneGreenTest(unittest.TestCase):
    def test_green(self):
        self.assertTrue(True)
""",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(OSError, "UNIT_TEST_GATE_FAILED"):
                self.packager.run_unit_test_gate(source)

    def test_unit_gate_rejects_skips_and_expected_failures(self):
        variants = {
            "skipped": """import unittest
class CriticalGuard(unittest.TestCase):
    @unittest.skip('dependency missing')
    def test_critical(self):
        self.fail('must run')
""",
            "expected_failure": """import unittest
class CriticalGuard(unittest.TestCase):
    @unittest.expectedFailure
    def test_critical(self):
        self.fail('known release defect')
""",
        }
        for name, source_text in variants.items():
            with self.subTest(variant=name), tempfile.TemporaryDirectory() as temp_dir:
                source = Path(temp_dir)
                tests = source / "tests"
                tests.mkdir()
                (tests / f"test_{name}.py").write_text(
                    source_text, encoding="utf-8"
                )
                with self.assertRaisesRegex(OSError, "UNIT_TEST_GATE_FAILED"):
                    self.packager.run_unit_test_gate(source)

    def test_machine_report_symlink_is_not_accepted_as_local_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            eval_root = root / "eval"
            eval_root.mkdir()
            report = self._release_report(SKILL_DIR)
            external = root / "external-machine-report.json"
            external.write_text(json.dumps(report), encoding="utf-8")
            (eval_root / "machine-report.json").symlink_to(external)
            completed = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(report), stderr=""
            )
            with mock.patch.object(
                self.packager.subprocess, "run", return_value=completed
            ):
                with self.assertRaisesRegex(OSError, "EVAL_GATE_FAILED"):
                    self.packager.run_eval_gate(SKILL_DIR, eval_root)

    def test_verify_rejects_manifest_without_release_gate_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            installed = self._make_installed_tree(Path(temp_dir))
            manifest_path = installed / "runtime-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest.pop("release_gate")
            manifest.pop("release_evidence")
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            result = self.packager.verify_install(installed)
        self.assertFalse(
            result["valid"],
            "file hashes alone must not be reported as a release-gated installation",
        )

    def test_verify_runs_complete_installed_workflow_not_only_help(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            installed = self._make_installed_tree(
                Path(temp_dir), help_only_workflow=True
            )
            result = self.packager.verify_install(installed)
        self.assertFalse(
            result["valid"],
            "a workflow that only supports --help must fail installed verification",
        )

    def test_verify_cross_checks_manifest_files_against_release_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            installed = self._make_installed_tree(Path(temp_dir))
            manifest_path = installed / "runtime-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            workflow = installed / "scripts" / "workflow.py"
            workflow.write_bytes(workflow.read_bytes() + b"\n# changed after release evidence\n")
            manifest["files"]["scripts/workflow.py"] = hashlib.sha256(
                workflow.read_bytes()
            ).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            result = self.packager.verify_install(installed)
        self.assertFalse(
            result["valid"],
            "recomputing the self-manifest must not erase a release-evidence mismatch",
        )

    def test_verify_cross_checks_machine_report_and_noninstalled_evidence(self):
        variants = ("machine_report_hash", "machine_report_missing", "eval_runner_hash")
        for variant in variants:
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                installed = self._make_installed_tree(root)
                manifest_path = installed / "runtime-manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if variant == "machine_report_hash":
                    manifest["release_evidence"]["machine_report"]["sha256"] = "0" * 64
                elif variant == "machine_report_missing":
                    manifest["release_evidence"]["machine_report"]["path"] = str(
                        root / "missing-machine-report.json"
                    )
                else:
                    manifest["release_evidence"]["eval_runner"]["sha256"] = "0" * 64
                manifest_path.write_text(
                    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                result = self.packager.verify_install(installed)
                self.assertFalse(
                    result["valid"],
                    "verify must bind the manifest to the retained machine report, "
                    "including release sources that are not copied into the runtime",
                )

    def test_invalid_fixture_replay_must_compare_fresh_error_receipt(self):
        case_id = "validator-rejects-epistemic-violations"
        case = self.runner.EXPECTED_CASES[case_id]
        fixture = SKILL_DIR / "evals" / "fixtures" / "invalid-epistemic.json"
        required_codes = (
            "ANCHOR_NOT_FOUND",
            "SOURCE_TYPE_MISMATCH",
            "CONCLUSION_EXCEEDS_EVIDENCE",
            "ACTION_REVERSIBILITY_FALSE",
        )
        forged_errors = [
            {"code": code, "path": f"/forged/{index}", "message": "saved only"}
            for index, code in enumerate(required_codes)
        ]
        forged_receipt = {
            "valid": False,
            "error_count": len(forged_errors),
            "validated_at": "2026-08-06T00:00:00+00:00",
            "artifact_path": str(fixture.resolve()),
            "artifact_sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
            "casefile_sha256": "0" * 64,
            "schema_version": self.runner.CASEFILE.SCHEMA_VERSION,
            "validator_version": self.runner.CASEFILE.VALIDATOR_VERSION,
            "errors": forged_errors,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / case_id
            case_dir.mkdir()
            input_payload = self.runner.expected_input_payload(case_id, case)
            (case_dir / "input.json").write_text(
                json.dumps(input_payload, ensure_ascii=False), encoding="utf-8"
            )
            (case_dir / "receipt.json").write_text(
                json.dumps(forged_receipt, ensure_ascii=False), encoding="utf-8"
            )
            (case_dir / "response.md").write_text(
                json.dumps(forged_receipt, ensure_ascii=False), encoding="utf-8"
            )
            case_result = {
                "case_id": case_id,
                "status": "completed",
                "model_environment": {
                    "runner": "claimed-runner",
                    "model": "claimed-model",
                    "isolation": self.runner.EXPECTED_ISOLATION,
                },
                "input_sha256": self.runner.expected_input_sha256(case_id, case),
                "raw_input_path": "input.json",
                "raw_output_path": "response.md",
                "artifact_paths": [],
                "receipt_paths": ["receipt.json"],
            }
            (case_dir / "case-result.json").write_text(
                json.dumps(case_result, ensure_ascii=False), encoding="utf-8"
            )
            with mock.patch.object(
                self.runner,
                "_run_casefile_cli",
                return_value=1,
            ):
                audited = self.runner.audit_case_result(root, case_id, case)
        self.assertFalse(
            audited["valid"],
            "exit code 1 alone cannot prove the current validator emitted the saved stable errors",
        )

    def test_prepared_eval_root_binds_model_run_to_release_source_snapshot(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "fresh-eval"
            prepared = self.runner.prepare_root(root)
            context_path = root / "evaluation-context.json"
            self.assertTrue(
                context_path.is_file() and not context_path.is_symlink(),
                "prepare must write a local source snapshot before any model output exists",
            )
            context = json.loads(context_path.read_text(encoding="utf-8"))
            self.assertEqual(
                self.runner.current_release_evidence(),
                context.get("release_evidence"),
            )
            context_sha = hashlib.sha256(context_path.read_bytes()).hexdigest()
            self.assertEqual(context_sha, prepared.get("evaluation_context_sha256"))

            context["release_evidence"]["skill"]["sha256"] = "0" * 64
            context_path.write_text(
                json.dumps(context, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            audited = self.runner.audit_root(root)
            codes = {item.get("code") for item in audited.get("suite_errors", [])}
            self.assertIn(
                "EVAL_CONTEXT_SOURCE_MISMATCH",
                codes,
                "an old or relabelled eval root must not be audited as a current-source run",
            )


if __name__ == "__main__":
    unittest.main()
