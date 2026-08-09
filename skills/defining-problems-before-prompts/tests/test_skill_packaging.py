from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Iterable


SKILL_DIR = Path(__file__).resolve().parents[1]
SKILL_NAME = "defining-problems-before-prompts"
MANIFEST = SKILL_DIR / "install-manifest.json"
PACKAGER = SKILL_DIR / "scripts" / "package_skill.py"
RUNTIME_REPORT = SKILL_DIR / "evals" / "runtime" / "results.json"

REQUIRED_BUNDLE_FILES = {
    "SKILL.md",
    "LICENSE",
    "PROVENANCE.md",
    "VERSION",
    "agents/openai.yaml",
    "install-manifest.json",
    "scripts/dpbp",
    "runtime/routes.json",
    "schemas/request-envelope.schema.json",
    "schemas/problem-spec.schema.json",
    "schemas/problem-state.schema.json",
    "references/core.md",
    "references/field-semantics.md",
    "references/high-risk.md",
    "references/playbooks/ai-efficiency.md",
    "references/playbooks/ai-product.md",
    "references/playbooks/career-exit.md",
}

DEVELOPMENT_ROOTS = {"adapters", "evals", "examples", "launch", "tests"}
DEVELOPMENT_FILES = {
    "CHANGELOG.md",
    "README.md",
    "problem-spec.md",
    "zero-threshold-prompt.md",
}


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _absolute_strings(value: Any, location: str = "$") -> Iterable[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield from _absolute_strings(item, f"{location}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _absolute_strings(item, f"{location}[{index}]")
    elif isinstance(value, str) and (
        value.startswith("/")
        or value.startswith("\\\\")
        or re.match(r"^[A-Za-z]:[\\/]", value)
    ):
        yield f"{location}={value}"


class SkillPackagingContract(unittest.TestCase):
    def _manifest_files(self) -> list[str]:
        self.assertTrue(MANIFEST.is_file(), f"missing install manifest: {MANIFEST}")
        payload = json.loads(MANIFEST.read_text(encoding="utf-8"))
        self.assertEqual("1.0", payload.get("schema_version"))
        self.assertEqual(SKILL_NAME, payload.get("skill"))
        files = payload.get("files")
        self.assertIsInstance(files, list)
        return files

    def _build_bundle(self, target_root: Path) -> Path:
        self.assertTrue(PACKAGER.is_file(), f"missing packager: {PACKAGER}")
        result = subprocess.run(
            [sys.executable, str(PACKAGER), "--target-root", str(target_root)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        bundle = target_root / SKILL_NAME
        self.assertTrue(bundle.is_dir(), f"packager did not create {bundle}")
        return bundle

    def test_openai_yaml_has_discovery_metadata_contract(self) -> None:
        metadata_path = SKILL_DIR / "agents" / "openai.yaml"
        self.assertTrue(metadata_path.is_file(), f"missing metadata: {metadata_path}")
        metadata = metadata_path.read_text(encoding="utf-8")

        def quoted_value(key: str) -> str:
            match = re.search(rf'^\s+{re.escape(key)}:\s+"([^"]+)"\s*$', metadata, re.MULTILINE)
            self.assertIsNotNone(match, f"{key} must be a quoted non-empty string")
            assert match is not None
            return match.group(1)

        self.assertIn("interface:\n", metadata)
        self.assertTrue(quoted_value("display_name").strip())
        short_description = quoted_value("short_description")
        self.assertGreaterEqual(len(short_description), 25)
        self.assertLessEqual(len(short_description), 64)
        self.assertIn(f"${SKILL_NAME}", quoted_value("default_prompt"))
        self.assertRegex(metadata, r"(?m)^\s+allow_implicit_invocation:\s+true\s*$")

    def test_install_manifest_is_a_safe_complete_allowlist(self) -> None:
        files = self._manifest_files()
        self.assertEqual(sorted(set(files)), files, "manifest files must be sorted and unique")
        self.assertTrue(REQUIRED_BUNDLE_FILES.issubset(files))
        for relative in files:
            path = Path(relative)
            with self.subTest(path=relative):
                self.assertFalse(path.is_absolute())
                self.assertNotIn("..", path.parts)
                self.assertTrue((SKILL_DIR / path).is_file())

    def test_packager_produces_reproducible_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = self._build_bundle(root / "first")
            second = self._build_bundle(root / "second")
            expected = set(self._manifest_files())
            self.assertEqual(expected, set(_tree_hashes(first)))
            self.assertEqual(_tree_hashes(first), _tree_hashes(second))

    def test_packager_rejects_allowlisted_file_through_symlinked_parent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            copied_skill = root / "copied-skill"
            shutil.copytree(SKILL_DIR, copied_skill)

            outside_runtime = root / "outside-runtime"
            shutil.copytree(copied_skill / "runtime", outside_runtime)
            shutil.rmtree(copied_skill / "runtime")
            (copied_skill / "runtime").symlink_to(
                outside_runtime,
                target_is_directory=True,
            )

            target_root = root / "bundles"
            result = subprocess.run(
                [
                    sys.executable,
                    str(copied_skill / "scripts" / "package_skill.py"),
                    "--target-root",
                    str(target_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertNotEqual(0, result.returncode)
            self.assertIn("symbolic link", result.stderr)
            self.assertFalse((target_root / SKILL_NAME).exists())

    def test_install_bundle_excludes_development_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = self._build_bundle(Path(temp_dir) / "skills")
            relative_files = {
                path.relative_to(bundle).as_posix()
                for path in bundle.rglob("*")
                if path.is_file()
            }
            self.assertTrue(REQUIRED_BUNDLE_FILES.issubset(relative_files))
            self.assertTrue(DEVELOPMENT_FILES.isdisjoint(relative_files))
            self.assertTrue(
                DEVELOPMENT_ROOTS.isdisjoint(
                    {Path(relative).parts[0] for relative in relative_files}
                )
            )

    def test_install_bundle_doctor_runs_successfully(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            bundle = self._build_bundle(Path(temp_dir) / "skills")
            result = subprocess.run(
                [sys.executable, str(bundle / "scripts" / "dpbp"), "doctor"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertTrue(json.loads(result.stdout)["ok"])

    def test_runtime_report_contains_no_absolute_paths(self) -> None:
        payload = json.loads(RUNTIME_REPORT.read_text(encoding="utf-8"))
        absolute = list(_absolute_strings(payload))
        self.assertEqual([], absolute, "runtime report must contain only portable paths")

    def test_doctor_covers_metadata_and_every_route_resource(self) -> None:
        routes = json.loads(
            (SKILL_DIR / "runtime" / "routes.json").read_text(encoding="utf-8")
        )
        routed_resources = {
            relative
            for mode in routes["resources"].values()
            if isinstance(mode, dict)
            for resources in mode.values()
            for relative in resources
        }
        required = {"SKILL.md", "agents/openai.yaml", *routed_resources}
        result = subprocess.run(
            [sys.executable, str(SKILL_DIR / "scripts" / "dpbp"), "doctor"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)
        payload = json.loads(result.stdout)
        checks = {item["path"]: item["ok"] for item in payload["checks"]}
        missing = sorted(required - checks.keys())
        failed = sorted(path for path in required if path in checks and not checks[path])
        self.assertEqual([], missing, f"doctor does not cover: {missing}")
        self.assertEqual([], failed, f"doctor reports unhealthy resources: {failed}")


if __name__ == "__main__":
    unittest.main()
