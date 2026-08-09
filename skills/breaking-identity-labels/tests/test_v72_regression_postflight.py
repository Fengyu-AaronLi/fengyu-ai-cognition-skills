#!/usr/bin/env python3
"""R72 red contracts for regression postflight integrity and read-only verify."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "run_regressions.py"


SPEC = importlib.util.spec_from_file_location("identity_v72_regression_runner", RUNNER)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("cannot load regression runner")
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


def invoke_main(test_manifest: Path, dependency_manifest: Path) -> tuple[int, str]:
    argv = [
        str(RUNNER),
        "--suite",
        "full",
        "--test-manifest",
        str(test_manifest),
        "--dependency-manifest",
        str(dependency_manifest),
    ]
    captured = io.StringIO()
    with mock.patch.object(sys, "argv", argv), contextlib.redirect_stderr(captured):
        result = MODULE.main()
    return result, captured.getvalue()


class MinimalRegressionFixture:
    def __init__(self, base: Path) -> None:
        self.repository_root = base / "repo"
        self.skill_root = self.repository_root / "skills" / "breaking-identity-labels"
        self.test_path = self.skill_root / "tests" / "test_fixture_pass.py"
        self.dependency_path = self.skill_root / "bound-input.txt"
        self.test_manifest = self.skill_root / "evals" / "test-generation-manifest.json"
        self.dependency_manifest = (
            self.skill_root / "evals" / "regression-dependency-manifest.json"
        )
        self.test_path.parent.mkdir(parents=True, exist_ok=True)
        self.test_path.write_text("# immutable passing test input\n", encoding="utf-8")
        self.dependency_path.write_text("immutable dependency input\n", encoding="utf-8")
        self.refresh_test_manifest()
        self.refresh_dependency_manifest()

    def refresh_test_manifest(self) -> None:
        write_json(
            self.test_manifest,
            {
                "schema_version": "1.0",
                "files": [
                    {
                        "path": "tests/test_fixture_pass.py",
                        "sha256": digest(self.test_path),
                    }
                ],
                "support_files": [],
            },
        )

    def refresh_dependency_manifest(self) -> None:
        write_json(
            self.dependency_manifest,
            {
                "schema_version": "1.0",
                "files": [
                    {
                        "scope": "skill",
                        "path": "bound-input.txt",
                        "sha256": digest(self.dependency_path),
                    }
                ],
            },
        )


class RegressionPostflightContractTests(unittest.TestCase):
    def test_both_manifests_and_inputs_are_revalidated_after_a_passing_suite(self) -> None:
        events: list[str] = []

        def verify_dependency(_path: Path) -> None:
            events.append("dependency")

        def verify_tests(_path: Path) -> list[str]:
            events.append("tests")
            return ["tests/test_fixture_pass.py"]

        def run_suite(_paths: list[str]) -> bool:
            events.append("suite")
            return True

        with tempfile.TemporaryDirectory(prefix="identity-v72-postflight-") as temp:
            manifest = Path(temp) / "manifest.json"
            with (
                mock.patch.object(MODULE, "verify_dependency_manifest", verify_dependency),
                mock.patch.object(MODULE, "registered_test_paths", verify_tests),
                mock.patch.object(MODULE, "run_suite", run_suite),
            ):
                returncode, stderr = invoke_main(manifest, manifest)
        self.assertEqual(0, returncode, stderr)
        suite_index = events.index("suite")
        self.assertEqual(2, events.count("dependency"), events)
        self.assertEqual(2, events.count("tests"), events)
        self.assertLess(events.index("dependency"), suite_index)
        self.assertLess(events.index("tests"), suite_index)
        self.assertGreater(len(events) - 1 - events[::-1].index("dependency"), suite_index)
        self.assertGreater(len(events) - 1 - events[::-1].index("tests"), suite_index)

    def run_mutation_case(self, mutate: str) -> tuple[int, str]:
        with tempfile.TemporaryDirectory(prefix="identity-v72-postflight-") as temp:
            fixture = MinimalRegressionFixture(Path(temp))

            def passing_suite(_paths: list[str]) -> bool:
                if mutate == "test":
                    fixture.test_path.write_text("# rewritten but still passing\n", encoding="utf-8")
                    fixture.refresh_test_manifest()
                else:
                    fixture.dependency_path.write_text("rewritten dependency\n", encoding="utf-8")
                    fixture.refresh_dependency_manifest()
                return True

            with (
                mock.patch.object(MODULE, "ROOT", fixture.skill_root.resolve()),
                mock.patch.object(
                    MODULE,
                    "REPOSITORY_ROOT",
                    fixture.repository_root.resolve(),
                ),
                mock.patch.object(
                    MODULE,
                    "expected_dependency_identities",
                    return_value={("skill", "bound-input.txt")},
                ),
                mock.patch.object(MODULE, "run_suite", passing_suite),
            ):
                return invoke_main(fixture.test_manifest, fixture.dependency_manifest)

    def test_passing_test_cannot_rewrite_bound_test_and_reseal_its_manifest(self) -> None:
        returncode, stderr = self.run_mutation_case("test")
        self.assertEqual(3, returncode, stderr)
        self.assertIn("regression_postflight_input_drift", stderr)

    def test_passing_test_cannot_rewrite_dependency_and_reseal_its_manifest(self) -> None:
        returncode, stderr = self.run_mutation_case("dependency")
        self.assertEqual(3, returncode, stderr)
        self.assertIn("regression_postflight_input_drift", stderr)


class MakeVerifyReadOnlyContractTests(unittest.TestCase):
    def test_verify_dry_run_contains_no_eval_demo_or_governance_writer(self) -> None:
        result = subprocess.run(
            ["make", "-n", "verify"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        output = result.stdout + result.stderr
        self.assertEqual(0, result.returncode, output)
        forbidden = (
            "evals/run_v2_evals.py",
            "scripts/build_demo.py",
            "sync_regression_dependencies.py sync",
            "run_evolution.py sync-tests",
            "run_evolution.py run",
            "build_package.py build",
        )
        for command in forbidden:
            with self.subTest(command=command):
                self.assertNotIn(command, output)
        self.assertIn("scripts/verify_evaluation.py", output)
        self.assertIn("scripts/verify_demo.py", output)


if __name__ == "__main__":
    unittest.main()
