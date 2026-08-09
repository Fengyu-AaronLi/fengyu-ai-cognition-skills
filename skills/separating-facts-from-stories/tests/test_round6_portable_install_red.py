import hashlib
import importlib.util
import json
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
    spec = importlib.util.spec_from_file_location("package_runtime_round6", PACKAGER)
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


class Round6PortableInstallRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_packager()

    def package_fixture(self, root: Path) -> tuple[Path, Path]:
        target_root = root / "project" / ".agents" / "skills"
        eval_root = root / "eval"
        eval_root.mkdir()
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
            json.dumps({"release_evidence": release_evidence}, ensure_ascii=False),
            encoding="utf-8",
        )
        context_sha256 = hashlib.sha256(context_path.read_bytes()).hexdigest()
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
            "evaluation_context_sha256": context_sha256,
            "results": [{"valid": True}] * 16,
            "case_results": [{"valid": True}] * 18,
            "release_evidence": release_evidence,
        }
        report_path = eval_root / "machine-report.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")
        eval_gate = {
            "report": report,
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
        unit_gate = release_bound_unit_gate(
            self.module, release_evidence, "round6-red"
        )
        with mock.patch.object(
            self.module,
            "run_unit_test_gate",
            return_value=unit_gate,
        ), mock.patch.object(self.module, "run_eval_gate", return_value=eval_gate):
            installed = self.module.package_runtime(SKILL_DIR, target_root, eval_root)
        return installed, eval_root

    def test_bundle_contains_its_verify_command_and_local_eval_evidence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            installed, _ = self.package_fixture(Path(temp_dir))
            self.assertTrue((installed / "scripts" / "package_runtime.py").is_file())
            self.assertTrue((installed / "evidence" / "machine-report.json").is_file())
            self.assertTrue((installed / "evidence" / "evaluation-context.json").is_file())
            completed = subprocess.run(
                [
                    sys.executable,
                    str(installed / "scripts" / "package_runtime.py"),
                    "--verify",
                    str(installed),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)

    def test_verify_remains_valid_after_original_eval_root_is_moved(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            installed, eval_root = self.package_fixture(root)
            eval_root.rename(root / "eval-moved-after-install")
            verification = self.module.verify_install(installed)
            self.assertTrue(verification["valid"], verification)

    def test_packaged_machine_report_tampering_is_detected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            installed, _ = self.package_fixture(Path(temp_dir))
            report_path = installed / "evidence" / "machine-report.json"
            report_path.write_bytes(report_path.read_bytes() + b"\n")
            verification = self.module.verify_install(installed)
            self.assertFalse(verification["valid"])
            self.assertIn(
                "MACHINE_REPORT_HASH_MISMATCH",
                {item["code"] for item in verification["errors"]},
            )


if __name__ == "__main__":
    unittest.main()
