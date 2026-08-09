from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
PACKAGER_PATH = SKILL_DIR / "scripts" / "package_runtime.py"
RUNNER_PATH = SKILL_DIR / "scripts" / "run_evals.py"
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import workflow  # noqa: E402
from test_casefile import valid_standard  # noqa: E402
import test_round4_release_gate_red as round4_release  # noqa: E402


class Round26ReleaseIntegrityRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.packager = round4_release.load_module(
            "round26_package_runtime", PACKAGER_PATH
        )
        cls.runner = round4_release.load_module(
            "round26_run_evals", RUNNER_PATH
        )

    def test_recursive_test_set_is_required_and_release_bound(self) -> None:
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
        for required in (
            "test_round21_adversarial_safety_red.py",
            "test_round22_adversarial_semantics_red.py",
            "test_round24_structural_safety_red.py",
            "test_round25_semantic_binding_red.py",
            "test_round26_release_integrity_red.py",
        ):
            self.assertIn(required, discovered)

    def test_recursive_gate_executes_a_nested_failure(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round26-tests-") as temp_dir:
            source = Path(temp_dir) / "source"
            tests_dir = source / "tests"
            nested = tests_dir / "nested"
            nested.mkdir(parents=True)
            (tests_dir / "test_top.py").write_text(
                "import unittest\n"
                "class Top(unittest.TestCase):\n"
                "    def test_ok(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            marker = Path(temp_dir) / "nested-ran.txt"
            (nested / "test_hidden.py").write_text(
                "import unittest\nfrom pathlib import Path\n"
                "class Hidden(unittest.TestCase):\n"
                "    def test_fails(self):\n"
                f"        Path({str(marker)!r}).write_text('ran')\n"
                "        self.fail('nested failure executed')\n",
                encoding="utf-8",
            )
            required = {"test_top.py", "nested/test_hidden.py"}
            evidence = {
                "test_top": "tests/test_top.py",
                "test_hidden": "tests/nested/test_hidden.py",
            }
            with mock.patch.object(
                self.packager, "REQUIRED_TEST_FILES", required
            ), mock.patch.object(
                self.packager, "RELEASE_EVIDENCE_FILES", evidence
            ):
                with self.assertRaisesRegex(OSError, "nested failure executed"):
                    self.packager.run_unit_test_gate(source)
            self.assertTrue(marker.is_file(), "nested test was never executed")

    def test_unit_gate_records_exact_module_and_count_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round26-count-") as temp_dir:
            source = Path(temp_dir) / "source"
            tests_dir = source / "tests"
            tests_dir.mkdir(parents=True)
            test_path = tests_dir / "test_top.py"
            test_path.write_text(
                "import unittest\n"
                "class Top(unittest.TestCase):\n"
                "    def test_one(self): self.assertTrue(True)\n"
                "    def test_two(self): self.assertEqual(2, 1 + 1)\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                self.packager, "REQUIRED_TEST_FILES", {"test_top.py"}
            ), mock.patch.object(
                self.packager,
                "RELEASE_EVIDENCE_FILES",
                {"test_top": "tests/test_top.py"},
            ):
                result = self.packager.run_unit_test_gate(source)
            self.assertEqual(["test_top.py"], result["test_modules"])
            self.assertEqual(1, result["test_module_count"])
            self.assertEqual({"test_top.py": 2}, result["module_test_counts"])
            self.assertEqual(2, result["tests_run"])
            expected_scope_hash = hashlib.sha256(
                json.dumps(
                    {"test_top.py": hashlib.sha256(test_path.read_bytes()).hexdigest()},
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(expected_scope_hash, result["test_source_set_sha256"])

    def test_test_symlinks_are_explicit_release_blockers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round26-symlink-") as temp_dir:
            source = Path(temp_dir) / "source"
            tests_dir = source / "tests"
            tests_dir.mkdir(parents=True)
            target = Path(temp_dir) / "outside.py"
            target.write_text("import unittest\n", encoding="utf-8")
            (tests_dir / "test_link.py").symlink_to(target)
            with mock.patch.object(
                self.packager, "REQUIRED_TEST_FILES", {"test_link.py"}
            ), mock.patch.object(
                self.packager,
                "RELEASE_EVIDENCE_FILES",
                {"test_link": "tests/test_link.py"},
            ):
                with self.assertRaisesRegex(OSError, "symlink"):
                    self.packager.run_unit_test_gate(source)

    def test_hash_failure_short_circuits_before_installed_code_executes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round26-tamper-") as temp_dir:
            root = Path(temp_dir)
            helper = round4_release.Round4ReleaseGateRedTests()
            helper.packager = self.packager
            helper.runner = self.runner
            installed = helper._make_installed_tree(root)
            marker = root / "tampered-code-executed.txt"
            runtime = installed / "scripts" / "casefile.py"
            runtime.write_text(
                runtime.read_text(encoding="utf-8")
                + f"\nPath({str(marker)!r}).write_text('executed', encoding='utf-8')\n",
                encoding="utf-8",
            )
            result = self.packager.verify_install(installed)
            self.assertFalse(result["valid"])
            self.assertIn(
                "HASH_MISMATCH", {item["code"] for item in result["errors"]}
            )
            self.assertFalse(marker.exists(), "tampered installed code executed")

    def test_preflight_binds_workflow_version_without_guessing(self) -> None:
        runtime, result = self.packager.preflight(SKILL_DIR)
        self.assertEqual(workflow.WORKFLOW_VERSION, result["workflow_version"])
        self.assertEqual(runtime.SKILL_VERSION, result["skill_version"])
        self.assertEqual(runtime.SCHEMA_VERSION, result["schema_version"])
        self.assertEqual(runtime.VALIDATOR_VERSION, result["validator_version"])

    def test_verify_rejects_legacy_or_forged_unit_gate_summary(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round26-unit-proof-") as temp_dir:
            root = Path(temp_dir)
            helper = round4_release.Round4ReleaseGateRedTests()
            helper.packager = self.packager
            helper.runner = self.runner
            installed = helper._make_installed_tree(root)
            manifest_path = installed / "runtime-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["release_gate"]["unit_tests"] = {
                "exit_code": 0,
                "tests_run": 999,
                "scope": "claimed complete without module evidence",
            }
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            result = self.packager.verify_install(installed)
            self.assertFalse(result["valid"])
            self.assertIn(
                "RELEASE_GATE_INVALID",
                {item["code"] for item in result["errors"]},
            )

    def test_verify_rejects_workflow_version_drift(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round26-version-") as temp_dir:
            root = Path(temp_dir)
            helper = round4_release.Round4ReleaseGateRedTests()
            helper.packager = self.packager
            helper.runner = self.runner
            installed = helper._make_installed_tree(root)
            manifest_path = installed / "runtime-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["workflow_version"] = "0.0.0"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            result = self.packager.verify_install(installed)
            self.assertFalse(result["valid"])
            self.assertIn(
                "VERSION_MISMATCH",
                {item["code"] for item in result["errors"]},
            )

    def test_start_initialization_is_atomic_and_retryable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round26-start-") as temp_dir:
            root = Path(temp_dir)
            input_path = root / "input.txt"
            input_path.write_text(
                "老板连续两次没让我参加会议。我认为他在架空我。",
                encoding="utf-8",
            )
            workspace = root / "workspace"
            args = argparse.Namespace(
                workspace=str(workspace),
                input=str(input_path),
                case_id="round26-atomic-start",
                mode="auto",
                safety_signal_type=[],
                max_attempts=2,
            )
            with mock.patch.object(
                workflow, "save_state", side_effect=RuntimeError("save failed")
            ):
                with self.assertRaises(workflow.WorkflowError) as raised:
                    workflow.command_start(args)
            self.assertEqual("WORKSPACE_INIT_INCOMPLETE", raised.exception.code)
            self.assertIn("staging preserved at", raised.exception.message)
            self.assertIn("save failed", raised.exception.message)
            self.assertFalse(workspace.exists())
            self.assertEqual(0, workflow.command_start(args))
            self.assertTrue((workspace / "state.json").is_file())

    def test_start_update_initialization_is_atomic_and_retryable(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round26-update-") as temp_dir:
            root = Path(temp_dir)
            previous_path = root / "revision-1.json"
            previous_path.write_text(
                json.dumps(valid_standard(), ensure_ascii=False),
                encoding="utf-8",
            )
            input_path = root / "input.txt"
            input_path.write_text(
                "老板今天再次没有让我参加项目会。",
                encoding="utf-8",
            )
            workspace = root / "workspace"
            args = argparse.Namespace(
                workspace=str(workspace),
                input=str(input_path),
                history=[str(previous_path)],
                mode="auto",
                safety_signal_type=[],
                max_attempts=2,
            )
            with mock.patch.object(
                workflow, "save_state", side_effect=RuntimeError("save failed")
            ):
                with self.assertRaises(workflow.WorkflowError) as raised:
                    workflow.command_start_update(args)
            self.assertEqual("WORKSPACE_INIT_INCOMPLETE", raised.exception.code)
            self.assertIn("staging preserved at", raised.exception.message)
            self.assertIn("save failed", raised.exception.message)
            self.assertFalse(workspace.exists())
            self.assertEqual(0, workflow.command_start_update(args))
            self.assertTrue((workspace / "state.json").is_file())


if __name__ == "__main__":
    unittest.main()
