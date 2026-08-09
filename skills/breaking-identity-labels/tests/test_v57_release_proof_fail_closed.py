#!/usr/bin/env python3
"""V57 adversarial contracts for a fail-closed local release proof."""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts" / "run_evolution.py"
REGRESSION_RUNNER = ROOT / "scripts" / "run_regressions.py"
PACKAGE_BUILDER = ROOT / "scripts" / "build_package.py"
PACKAGE_EQUIVALENCE = ROOT / "scripts" / "verify_package_equivalence.py"
V46_TEST = ROOT / "tests" / "test_v46_audit_completed_run_binding.py"
MANIFEST = ROOT / "evals" / "test-generation-manifest.json"

if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


CONTROLLER_MODULE = load_module("v57_controller", CONTROLLER)
REGRESSION_MODULE = load_module("v57_regression_runner", REGRESSION_RUNNER)
PACKAGE_MODULE = load_module("v57_package_builder", PACKAGE_BUILDER)
EQUIVALENCE_MODULE = load_module("v57_package_equivalence", PACKAGE_EQUIVALENCE)
V46_MODULE = load_module("v57_v46_fixture", V46_TEST)


class CurrentAuditReceiptContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v57-audit-")
        self.fixture = V46_MODULE.AuditCompletedRunFixture(Path(self.temporary.name))

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def validate(self, *, current: bool = True) -> set[str]:
        V46_MODULE.write_json(self.fixture.receipt_path, self.fixture.receipt)
        errors, _, _ = CONTROLLER_MODULE.validate_audit_receipt(
            self.fixture.root,
            self.fixture.receipt_path.relative_to(self.fixture.root).as_posix(),
            self.fixture.audit_id,
            self.fixture.state,
            enforce_current_contract=current,
        )
        return set(errors)

    def upgrade_to_current(self) -> None:
        root = self.fixture.root
        script = root / "audits" / "attribution.py"
        case_set = root / "inputs" / "attribution-cases.json"
        script.parent.mkdir(parents=True)
        case_set.parent.mkdir(parents=True)
        script.write_text("print('audit pass')\n", encoding="utf-8")
        case_set.write_text('{"cases":["A1"]}\n', encoding="utf-8")

        evidence_dir = self.fixture.evidence_dir
        preregistration = {
            "schema_version": "1.0",
            "audit_id": self.fixture.audit_id,
            "candidate_id": self.fixture.state["candidate_id"],
            "completed_run_sha256": self.fixture.completed_run["run_state_sha256"],
            "objective": "Attempt to falsify the frozen candidate.",
            "commands": [
                {
                    "argv": ["audits/attribution.py"],
                    "input_files": [
                        "audits/attribution.py",
                        "inputs/attribution-cases.json",
                    ],
                }
            ],
            "pass_condition": "The preregistered command exits zero.",
            "live_model_called": False,
        }
        prereg_path = evidence_dir / "preregistration.json"
        V46_MODULE.write_json(prereg_path, preregistration)
        self.fixture.receipt["schema_version"] = "1.2"
        self.fixture.receipt["preregistration"]["case_set_sha256"] = digest(prereg_path)
        command = self.fixture.receipt["commands"][0]
        command.update(
            {
                "argv": ["python3", str(script.resolve())],
                "script_path": "audits/attribution.py",
                "script_sha256": digest(script),
                "input_snapshot": {
                    "cwd": ".",
                    "environment": {"PYTHONHASHSEED": "0"},
                    "files": [
                        {"path": "audits/attribution.py", "sha256": digest(script)},
                        {
                            "path": "inputs/attribution-cases.json",
                            "sha256": digest(case_set),
                        },
                    ],
                },
            }
        )

    def rewrite_preregistration(self, mutate) -> None:
        path = self.fixture.evidence_dir / "preregistration.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        V46_MODULE.write_json(path, value)
        self.fixture.receipt["preregistration"]["case_set_sha256"] = digest(path)

    def test_current_candidate_rejects_legacy_11_receipt(self) -> None:
        self.assertIn("audit_receipt_current_schema_required", self.validate())
        self.assertEqual(set(), self.validate(current=False))

    def test_current_receipt_binds_preregistered_command_and_inputs(self) -> None:
        self.upgrade_to_current()
        self.assertEqual(set(), self.validate())

        self.rewrite_preregistration(
            lambda value: value["commands"][0].__setitem__(
                "argv", ["audits/different.py"]
            )
        )
        self.assertIn("audit_receipt_preregistered_command_mismatch", self.validate())

    def test_preregistered_input_set_cannot_diverge_from_snapshot(self) -> None:
        self.upgrade_to_current()
        self.rewrite_preregistration(
            lambda value: value["commands"][0].__setitem__(
                "input_files", ["audits/attribution.py"]
            )
        )
        self.assertIn("audit_receipt_preregistered_input_mismatch", self.validate())


class RegressionInputClosureTests(unittest.TestCase):
    def test_manifest_hash_binds_the_complete_non_code_fixture_inventory(self) -> None:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        declared = {
            item["path"]: item["sha256"] for item in payload["support_files"]
        }
        actual = {
            path.relative_to(ROOT).as_posix(): digest(path)
            for path in (ROOT / "tests").rglob("*")
            if path.is_file()
            and not path.is_symlink()
            and not path.name.startswith("test_")
            and "__pycache__" not in path.parts
        }
        self.assertEqual(actual, declared)
        self.assertIn("tests/fixtures/analysis-c01.json", declared)
        self.assertIn("tests/fixtures/valid-c01.json", declared)

    def test_regression_runner_refuses_a_manifest_without_support_files(self) -> None:
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        payload.pop("support_files")
        with tempfile.TemporaryDirectory(prefix="identity-v57-manifest-") as temp:
            path = Path(temp) / "manifest.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(REGRESSION_MODULE.RegressionManifestError):
                REGRESSION_MODULE.registered_test_paths(path)

    def test_release_snapshot_inventory_includes_fixture_bytes(self) -> None:
        paths = {
            path.relative_to(ROOT).as_posix()
            for path in CONTROLLER_MODULE.test_inventory_paths(ROOT)
        }
        self.assertIn("tests/fixtures/analysis-c01.json", paths)
        self.assertIn("tests/fixtures/valid-c01.json", paths)


class PackageManifestEquivalenceTests(unittest.TestCase):
    def test_package_manifest_has_a_closed_top_level_schema(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v57-package-") as temp:
            package = Path(temp) / "breaking-identity-labels"
            PACKAGE_MODULE.build_package(package, None)
            manifest_path = package / "PACKAGE-MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["unbound_metadata"] = "different in each form"
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(PACKAGE_MODULE.PackageError):
                PACKAGE_MODULE.verify_directory(package)

    def test_equivalence_requires_identical_manifest_bytes_as_well_as_tree(self) -> None:
        tree = "1" * 64
        results = [
            {
                "package": name,
                "manifest_sha256": manifest,
                "tree_sha256": tree,
            }
            for name, manifest in (
                ("directory", "2" * 64),
                ("archive", "3" * 64),
                ("installed", "2" * 64),
            )
        ]
        with mock.patch.object(
            EQUIVALENCE_MODULE,
            "verify_package",
            side_effect=copy.deepcopy(results),
        ):
            with self.assertRaises(EQUIVALENCE_MODULE.PackageError):
                EQUIVALENCE_MODULE.verify(Path("a"), Path("b.zip"), Path("c"))


if __name__ == "__main__":
    unittest.main()
