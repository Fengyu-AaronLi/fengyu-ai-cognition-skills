from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
PACKAGER_PATH = SKILL_DIR / "scripts" / "package_runtime.py"
sys.path.insert(0, str(SKILL_DIR / "tests"))

import test_round4_release_gate_red as round4_release  # noqa: E402


class Round28ReleaseEvidenceRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.packager = round4_release.load_module(
            "round28_package_runtime", PACKAGER_PATH
        )

    def _installed_fixture(self, root: Path) -> Path:
        helper = round4_release.Round4ReleaseGateRedTests()
        helper.packager = self.packager
        helper.runner = round4_release.load_module(
            "round28_run_evals", SKILL_DIR / "scripts" / "run_evals.py"
        )
        return helper._make_installed_tree(root)

    @staticmethod
    def _write_manifest(path: Path, value: object) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _leaf_paths(value: dict[str, object]) -> list[tuple[str, ...]]:
        paths: list[tuple[str, ...]] = []

        def visit(current: object, prefix: tuple[str, ...]) -> None:
            if isinstance(current, dict):
                for key, child in current.items():
                    visit(child, (*prefix, key))
            else:
                paths.append(prefix)

        visit(value, ())
        return paths

    @staticmethod
    def _parent_at(value: dict[str, object], path: tuple[str, ...]) -> dict[str, object]:
        current = value
        for part in path[:-1]:
            child = current[part]
            if not isinstance(child, dict):
                raise AssertionError(f"non-object preflight path: {'/'.join(path)}")
            current = child
        return current

    @staticmethod
    def _forged(value: object) -> object:
        if isinstance(value, bool):
            return not value
        if isinstance(value, int):
            return value + 17
        if isinstance(value, str):
            return value + "-forged"
        if value is None:
            return "forged"
        return {"forged": True}

    def test_non_object_manifest_is_structured_invalid_without_exception(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round28-manifest-") as temp_dir:
            installed = self._installed_fixture(Path(temp_dir))
            self._write_manifest(installed / "runtime-manifest.json", [])
            try:
                result = self.packager.verify_install(installed)
            except Exception as exc:  # pragma: no cover - this is the RED condition
                self.fail(
                    "verify_install must fail closed with structured MANIFEST_INVALID; "
                    f"it raised {type(exc).__name__}: {exc}"
                )
        self.assertFalse(result["valid"])
        self.assertIn(
            "MANIFEST_INVALID", {item["code"] for item in result["errors"]}
        )

    def test_duplicate_python_constant_is_rejected_as_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round28-constant-") as temp_dir:
            module_path = Path(temp_dir) / "workflow.py"
            module_path.write_text(
                'WORKFLOW_VERSION = "2.1.0"\n'
                'WORKFLOW_VERSION = "99.0.0"\n',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(OSError, "PYTHON_CONSTANT_AMBIGUOUS"):
                self.packager.read_python_string_constant(
                    module_path, "WORKFLOW_VERSION"
                )

    def test_every_missing_or_forged_preflight_leaf_invalidates_manifest(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round28-preflight-") as temp_dir:
            installed = self._installed_fixture(Path(temp_dir))
            manifest_path = installed / "runtime-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            runtime, fresh_preflight = self.packager.preflight(installed)
            manifest["preflight"] = fresh_preflight
            self._write_manifest(manifest_path, manifest)

            with mock.patch.object(
                self.packager,
                "preflight",
                return_value=(runtime, fresh_preflight),
            ):
                baseline = self.packager.verify_install(installed)
                self.assertTrue(
                    baseline["valid"],
                    f"pristine fixture must verify before mutation: {baseline['errors']}",
                )
                for path in self._leaf_paths(fresh_preflight):
                    label = "/".join(path)
                    with self.subTest(mutation="missing", path=label):
                        candidate = copy.deepcopy(manifest)
                        parent = self._parent_at(candidate["preflight"], path)
                        del parent[path[-1]]
                        self._write_manifest(manifest_path, candidate)
                        result = self.packager.verify_install(installed)
                        self.assertFalse(
                            result["valid"],
                            f"missing /preflight/{label} was accepted",
                        )
                    with self.subTest(mutation="forged", path=label):
                        candidate = copy.deepcopy(manifest)
                        parent = self._parent_at(candidate["preflight"], path)
                        parent[path[-1]] = self._forged(parent[path[-1]])
                        self._write_manifest(manifest_path, candidate)
                        result = self.packager.verify_install(installed)
                        self.assertFalse(
                            result["valid"],
                            f"forged /preflight/{label} was accepted",
                        )

    def test_all_test_python_sources_are_release_evidence_bound(self) -> None:
        tests_dir = SKILL_DIR / "tests"
        python_sources = {
            str(path.relative_to(SKILL_DIR))
            for path in tests_dir.rglob("*.py")
            if path.is_file() and not path.is_symlink()
        }
        release_bound = set(self.packager.RELEASE_EVIDENCE_FILES.values())
        self.assertEqual(
            python_sources,
            python_sources & release_bound,
            "every test module and imported helper under tests/**/*.py must be hashed",
        )

    def test_unit_gate_hashes_auxiliary_python_sources(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round28-helper-") as temp_dir:
            source = Path(temp_dir) / "source"
            tests_dir = source / "tests"
            tests_dir.mkdir(parents=True)
            helper_path = tests_dir / "fixture_helper.py"
            helper_path.write_text("VALUE = 7\n", encoding="utf-8")
            test_path = tests_dir / "test_contract.py"
            test_path.write_text(
                "import sys\n"
                f"sys.path.insert(0, {str(tests_dir)!r})\n"
                "import unittest\n"
                "from fixture_helper import VALUE\n"
                "class Contract(unittest.TestCase):\n"
                "    def test_helper(self): self.assertEqual(7, VALUE)\n",
                encoding="utf-8",
            )
            evidence = {
                "test_contract": "tests/test_contract.py",
                "test_fixture_helper": "tests/fixture_helper.py",
            }
            with mock.patch.object(
                self.packager, "REQUIRED_TEST_FILES", {"test_contract.py"}
            ), mock.patch.object(
                self.packager, "RELEASE_EVIDENCE_FILES", evidence
            ):
                result = self.packager.run_unit_test_gate(source)
            expected_hashes = {
                "fixture_helper.py": hashlib.sha256(helper_path.read_bytes()).hexdigest(),
                "test_contract.py": hashlib.sha256(test_path.read_bytes()).hexdigest(),
            }
            expected_set_hash = hashlib.sha256(
                json.dumps(
                    expected_hashes,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(
                sorted(expected_hashes), result["test_source_files"]
            )
            self.assertEqual(expected_set_hash, result["test_source_set_sha256"])

    def test_eval_runner_fixed_fixture_tree_is_release_evidence_bound(self) -> None:
        fixture_root = (
            SKILL_DIR / "evals" / "raw" / "with-skill-v4-capability"
        )
        fixture_files = {
            str(path.relative_to(SKILL_DIR))
            for path in fixture_root.rglob("*")
            if path.is_file() and not path.is_symlink()
        }
        self.assertTrue(fixture_files, "fixed eval-runner fixture tree is missing")
        release_bound = set(self.packager.RELEASE_EVIDENCE_FILES.values())
        missing = sorted(fixture_files - release_bound)
        self.assertEqual(
            [],
            missing,
            "test_eval_runner fixture bytes can change outside release evidence",
        )

    def test_lifecycle_smoke_reports_executed_workflow_version(self) -> None:
        _, result = self.packager.preflight(SKILL_DIR)
        static_version = self.packager.read_python_string_constant(
            SKILL_DIR / "scripts" / "workflow.py", "WORKFLOW_VERSION"
        )
        lifecycle = result["workflow_lifecycle"]
        self.assertEqual(
            static_version,
            lifecycle.get("workflow_version"),
            "lifecycle receipt must bind the version emitted by the executed workflow",
        )


if __name__ == "__main__":
    unittest.main()
