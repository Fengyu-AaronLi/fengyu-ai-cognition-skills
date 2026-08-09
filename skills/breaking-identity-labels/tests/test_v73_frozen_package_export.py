from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTROLLER = ROOT / "scripts" / "run_evolution.py"
CURRENT_WORKFLOW = ROOT / "workflows" / "v68-final-release.json"

PACKAGE_SOURCE_FILES = (
    "SKILL.md",
    "VERSION",
    "SOURCE_OF_TRUTH.md",
    "README.md",
    "problem-spec.md",
    "PROVENANCE.md",
    "zero-threshold-prompt.md",
    "LICENSE",
    "NOTICE.md",
    "agents/openai.yaml",
    "schemas/analysis.schema.json",
    "schemas/case.schema.json",
    "schemas/event-head.schema.json",
    "schemas/event.schema.json",
    "schemas/workflow-next.schema.json",
    "templates/analysis.json",
    "references/evidence-classes.md",
    "references/policy-rules.md",
    "references/safety-boundaries.md",
    "docs/acceptance.md",
    "docs/evolution.md",
    "docs/quickstart.md",
    "scripts/build_package.py",
    "scripts/identity_label_case.py",
)


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def load_controller(path: Path):
    spec = importlib.util.spec_from_file_location("v73_run_evolution", path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def target_recipe(makefile: str, target: str) -> str:
    marker = target + ":"
    start = makefile.find(marker)
    if start < 0:
        return ""
    lines = makefile[start:].splitlines()
    selected = [lines[0]]
    for line in lines[1:]:
        if line and not line.startswith(("\t", " ")):
            break
        selected.append(line)
    return "\n".join(selected)


class FrozenPackageExportContractTests(unittest.TestCase):
    def test_release_targets_export_and_reverify_the_frozen_run(self) -> None:
        makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
        release = target_recipe(makefile, "release-package")
        verify = target_recipe(makefile, "release-package-check")

        self.assertIn("release-gate", release)
        self.assertIn(
            "scripts/run_evolution.py export-package",
            release,
            "release-package must copy and authenticate the completed run's sealed "
            "package bytes after the strict gate",
        )
        self.assertIn("--state", release)
        self.assertNotIn(
            "scripts/build_package.py build",
            release,
            "a post-gate live-tree rebuild is a TOCTOU path, not a frozen export",
        )

        self.assertIn("release-gate", verify)
        self.assertIn("scripts/run_evolution.py", verify)
        self.assertIn("--state", verify)
        self.assertNotIn(
            "scripts/build_package.py verify",
            verify,
            "raw package verification does not prove that the bytes came from the "
            "completed run named by the release state",
        )

    def test_current_workflow_hash_binds_the_archive_used_for_equivalence(self) -> None:
        workflow = json.loads(CURRENT_WORKFLOW.read_text(encoding="utf-8"))
        steps = workflow["steps"]
        by_id = {step["id"]: step for step in steps}
        equivalence = by_id["package_equivalence"]
        self.assertEqual("package_equivalence", steps[-1]["id"])
        self.assertIn("package_verify_installed", equivalence["depends_on"])
        self.assertIn(
            "{run_dir}/breaking-identity-labels.zip",
            equivalence["input_files"],
        )
        self.assertIn("{root}/scripts/build_package.py", equivalence["input_files"])
        self.assertIn(
            "{run_dir}/package/PACKAGE-MANIFEST.json",
            equivalence["input_files"],
        )

    def test_export_ignores_live_drift_and_rejects_frozen_archive_tampering(self) -> None:
        controller = load_controller(CONTROLLER)
        export = getattr(controller, "export_completed_run_package", None)
        self.assertTrue(
            callable(export),
            "run_evolution.py needs a reusable export_completed_run_package() "
            "primitive behind the public export-package CLI",
        )
        if not callable(export):
            return

        with tempfile.TemporaryDirectory(prefix="identity-v73-") as temp:
            fixture = Path(temp) / "breaking-identity-labels"
            fixture.mkdir()
            for relative in PACKAGE_SOURCE_FILES:
                source = ROOT / relative
                target = fixture / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            for relative in (
                "scripts/run_evolution.py",
                "scripts/build_demo.py",
                "evals/validate.py",
            ):
                source = ROOT / relative
                target = fixture / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
            # The copied governance controller validates its own run, event,
            # command and workflow records. Keep those source-only schemas in
            # the fixture without adding them to the runtime package allowlist.
            for source in (ROOT / "schemas").glob("*.json"):
                target = fixture / "schemas" / source.name
                if not target.exists():
                    shutil.copy2(source, target)
            demo_source = ROOT / "examples" / "real-run"
            shutil.copytree(demo_source, fixture / "examples" / "real-run")
            (fixture / "tests").mkdir()
            (fixture / "tests" / "fixture.txt").write_text(
                "v73 fixture\n", encoding="utf-8"
            )

            workflow_path = fixture / "workflows" / "v73-package.json"
            workflow_path.parent.mkdir()
            workflow = {
                "schema_version": "1.0",
                "workflow_id": "v73_frozen_package_fixture",
                "description": "Build once, then bind the generated archive as a later command input.",
                "steps": [
                    {
                        "id": "package_build",
                        "kind": "command",
                        "depends_on": [],
                        "description": "Build the package inside the immutable run directory.",
                        "argv": [
                            "{python}",
                            "{root}/scripts/build_package.py",
                            "build",
                            "--out",
                            "{run_dir}/package",
                            "--archive",
                            "{run_dir}/breaking-identity-labels.zip",
                        ],
                        "input_files": list(PACKAGE_SOURCE_FILES),
                        "expected": "exit_zero",
                    },
                    {
                        "id": "package_archive_bind",
                        "kind": "command",
                        "depends_on": ["package_build"],
                        "description": "Verify and hash-bind the exact archive produced by the run.",
                        "argv": [
                            "{python}",
                            "{root}/scripts/build_package.py",
                            "verify",
                            "--package",
                            "{run_dir}/breaking-identity-labels.zip",
                        ],
                        "input_files": [
                            "{root}/scripts/build_package.py",
                            "{run_dir}/breaking-identity-labels.zip",
                        ],
                        "expected": "exit_zero",
                    },
                ],
            }
            workflow_path.write_text(
                json.dumps(workflow, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            run_dir = fixture / "evals" / "runs" / "v73-package"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(fixture / "scripts" / "run_evolution.py"),
                    "run",
                    "--root",
                    str(fixture),
                    "--workflow",
                    str(workflow_path),
                    "--run-dir",
                    str(run_dir),
                    "--run-id",
                    "v73-package",
                    "--candidate-id",
                    "v73-package-candidate",
                ],
                cwd=fixture,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(
                0,
                completed.returncode,
                msg=f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}",
            )

            frozen_archive = run_dir / "breaking-identity-labels.zip"
            frozen_bytes = frozen_archive.read_bytes()
            frozen_sha256 = sha256_bytes(frozen_bytes)

            with (fixture / "SKILL.md").open("a", encoding="utf-8") as handle:
                handle.write("\nLIVE SOURCE DRIFT MUST NOT ENTER THE EXPORT\n")
            with (fixture / "scripts" / "build_package.py").open(
                "a", encoding="utf-8"
            ) as handle:
                handle.write("\n# LIVE BUILDER DRIFT MUST NOT ENTER THE EXPORT\n")

            rebuilt_dir = fixture / "dist" / "live-rebuild"
            rebuilt_archive = fixture / "dist" / "live-rebuild.zip"
            rebuilt = subprocess.run(
                [
                    sys.executable,
                    str(fixture / "scripts" / "build_package.py"),
                    "build",
                    "--out",
                    str(rebuilt_dir),
                    "--archive",
                    str(rebuilt_archive),
                ],
                cwd=fixture,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, rebuilt.returncode, msg=rebuilt.stderr)
            self.assertNotEqual(
                frozen_sha256,
                sha256_bytes(rebuilt_archive.read_bytes()),
                "the fixture must demonstrate that a live rebuild has drifted",
            )

            export_dir = fixture / "dist" / "frozen-export"
            export_archive = fixture / "dist" / "frozen-export.zip"
            result = export(
                fixture,
                run_dir,
                export_dir,
                export_archive,
            )
            self.assertIsInstance(result, dict)
            self.assertEqual(frozen_bytes, export_archive.read_bytes())
            self.assertEqual(frozen_sha256, result.get("archive_sha256"))
            self.assertEqual(
                json.loads((run_dir / "package" / "PACKAGE-MANIFEST.json").read_text()),
                json.loads((export_dir / "PACKAGE-MANIFEST.json").read_text()),
            )

            frozen_archive.write_bytes(frozen_bytes + b"v73-tamper")
            with self.assertRaises(controller.GateError) as raised:
                export(
                    fixture,
                    run_dir,
                    fixture / "dist" / "tampered-export",
                    fixture / "dist" / "tampered-export.zip",
                )
            self.assertIn(
                "frozen_package_archive_hash_mismatch",
                raised.exception.codes,
            )


if __name__ == "__main__":
    unittest.main()
