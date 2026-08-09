#!/usr/bin/env python3
"""Run an exact hash-bound regression selection for the evolution workflow."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import importlib
import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[1]
SUITES = {
    "architecture": (
        "test_v13_architecture_integrity_regressions.py",
        "test_v13_context_claims_regressions.py",
        "test_v13_executable_evolution_loop.py",
        "test_v14_*.py",
    ),
    "full": ("test_*.py",),
}


class RegressionManifestError(RuntimeError):
    """A stable pre-execution manifest failure."""


def expected_dependency_identities() -> set[tuple[str, str]]:
    """Derive the inventory independently instead of trusting the listed set."""

    synchronizer = ROOT / "scripts" / "sync_regression_dependencies.py"
    spec = importlib.util.spec_from_file_location(
        "breaking_identity_dependency_inventory",
        synchronizer,
    )
    if spec is None or spec.loader is None:
        raise RegressionManifestError("regression_dependency_inventory_unavailable")
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
        return set(module.expected_identities(ROOT, REPOSITORY_ROOT))
    except Exception as error:
        code = str(error)
        if not code.startswith("regression_dependency_"):
            code = "regression_dependency_inventory_invalid"
        raise RegressionManifestError(code) from error


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def registered_test_paths(manifest_path: Path) -> list[str]:
    """Return the exact registered test inventory after closed-world validation."""

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RegressionManifestError("regression_manifest_invalid") from error
    if not isinstance(manifest, dict) or manifest.get("schema_version") != "1.0":
        raise RegressionManifestError("regression_manifest_invalid")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise RegressionManifestError("regression_manifest_invalid")

    registered: list[str] = []
    for item in files:
        if not isinstance(item, dict):
            raise RegressionManifestError("regression_manifest_invalid")
        relative = item.get("path")
        expected = item.get("sha256")
        if (
            not isinstance(relative, str)
            or not relative.startswith("tests/test_")
            or not relative.endswith(".py")
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not isinstance(expected, str)
            or len(expected) != 64
        ):
            raise RegressionManifestError("regression_manifest_invalid")
        if relative in registered:
            raise RegressionManifestError("regression_manifest_duplicate")
        path = (ROOT / relative).resolve()
        try:
            path.relative_to(ROOT)
        except ValueError as error:
            raise RegressionManifestError("regression_manifest_unsafe_path") from error
        if not path.is_file() or path.is_symlink():
            raise RegressionManifestError("regression_manifest_test_missing")
        if sha256_file(path) != expected:
            raise RegressionManifestError("regression_manifest_hash_mismatch")
        registered.append(relative)

    actual = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests").glob("test_*.py")
        if path.is_file() and not path.is_symlink()
    )
    if sorted(registered) != actual:
        raise RegressionManifestError("regression_manifest_inventory_mismatch")

    support_files = manifest.get("support_files")
    if not isinstance(support_files, list):
        raise RegressionManifestError("regression_manifest_support_invalid")
    registered_support: list[str] = []
    for item in support_files:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise RegressionManifestError("regression_manifest_support_invalid")
        relative = item.get("path")
        expected = item.get("sha256")
        if (
            not isinstance(relative, str)
            or not relative.startswith("tests/")
            or relative.startswith("tests/test_")
            or "__pycache__" in Path(relative).parts
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not isinstance(expected, str)
            or len(expected) != 64
        ):
            raise RegressionManifestError("regression_manifest_support_invalid")
        if relative in registered_support:
            raise RegressionManifestError("regression_manifest_support_duplicate")
        path = (ROOT / relative).resolve()
        try:
            path.relative_to(ROOT)
        except ValueError as error:
            raise RegressionManifestError(
                "regression_manifest_support_unsafe_path"
            ) from error
        if not path.is_file() or path.is_symlink():
            raise RegressionManifestError("regression_manifest_support_missing")
        if sha256_file(path) != expected:
            raise RegressionManifestError("regression_manifest_support_hash_mismatch")
        registered_support.append(relative)

    actual_support = sorted(
        path.relative_to(ROOT).as_posix()
        for path in (ROOT / "tests").rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and not (
            path.parent == ROOT / "tests"
            and path.name.startswith("test_")
            and path.suffix == ".py"
        )
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    )
    if sorted(registered_support) != actual_support:
        raise RegressionManifestError("regression_manifest_support_inventory_mismatch")
    return actual


def verify_dependency_manifest(manifest_path: Path) -> None:
    """Fail before imports unless every declared non-test dependency still matches."""

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RegressionManifestError("regression_dependency_manifest_invalid") from error
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"schema_version", "files"}
        or manifest.get("schema_version") != "1.0"
        or not isinstance(manifest.get("files"), list)
        or not manifest["files"]
    ):
        raise RegressionManifestError("regression_dependency_manifest_invalid")
    identities: list[tuple[str, str]] = []
    for record in manifest["files"]:
        if not isinstance(record, dict) or set(record) != {"scope", "path", "sha256"}:
            raise RegressionManifestError("regression_dependency_manifest_invalid")
        scope, relative, expected = record.get("scope"), record.get("path"), record.get("sha256")
        if (
            scope not in {"skill", "repository"}
            or not isinstance(relative, str)
            or Path(relative).is_absolute()
            or ".." in Path(relative).parts
            or not isinstance(expected, str)
            or len(expected) != 64
        ):
            raise RegressionManifestError("regression_dependency_manifest_invalid")
        base = ROOT if scope == "skill" else REPOSITORY_ROOT
        target = (base / relative).resolve()
        try:
            target.relative_to(base.resolve())
        except ValueError as error:
            raise RegressionManifestError("regression_dependency_manifest_unsafe_path") from error
        if not target.is_file() or target.is_symlink():
            raise RegressionManifestError("regression_dependency_missing")
        if sha256_file(target) != expected:
            raise RegressionManifestError("regression_dependency_hash_mismatch")
        identities.append((scope, relative))
    if identities != sorted(set(identities)):
        raise RegressionManifestError("regression_dependency_manifest_invalid")
    observed = set(identities)
    expected = expected_dependency_identities()
    if expected - observed:
        raise RegressionManifestError("regression_dependency_inventory_missing")
    if observed - expected:
        raise RegressionManifestError("regression_dependency_inventory_extra")


def selected_test_paths(registered: list[str], suite: str) -> list[str]:
    patterns = SUITES[suite]
    selected = [
        relative
        for relative in registered
        if any(fnmatch.fnmatch(Path(relative).name, pattern) for pattern in patterns)
    ]
    if not selected:
        raise RegressionManifestError("regression_suite_empty")
    return selected


def run_suite(relative_paths: list[str]) -> bool:
    tests_dir = str(ROOT / "tests")
    if tests_dir not in sys.path:
        sys.path.insert(0, tests_dir)
    loader = unittest.defaultTestLoader
    suite = unittest.TestSuite()
    for relative in relative_paths:
        module = importlib.import_module(Path(relative).stem)
        suite.addTests(loader.loadTestsFromModule(module))
    return unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()


def regression_input_snapshot(
    test_manifest_path: Path,
    dependency_manifest_path: Path,
) -> dict[str, str] | None:
    """Capture actual pre-run bytes, independent of the manifests' saved hashes."""

    if (
        not test_manifest_path.is_file()
        or test_manifest_path.is_symlink()
        or not dependency_manifest_path.is_file()
        or dependency_manifest_path.is_symlink()
    ):
        return None
    try:
        test_manifest = json.loads(test_manifest_path.read_text(encoding="utf-8"))
        dependency_manifest = json.loads(
            dependency_manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError):
        return None
    snapshot = {
        "manifest:test": sha256_file(test_manifest_path),
        "manifest:dependency": sha256_file(dependency_manifest_path),
    }
    for collection in (
        test_manifest.get("files", []) if isinstance(test_manifest, dict) else [],
        test_manifest.get("support_files", []) if isinstance(test_manifest, dict) else [],
    ):
        if not isinstance(collection, list):
            continue
        for item in collection:
            if not isinstance(item, dict) or not isinstance(item.get("path"), str):
                continue
            relative = item["path"]
            target = (ROOT / relative).resolve()
            key = f"test:{relative}"
            snapshot[key] = (
                sha256_file(target)
                if target.is_file() and not target.is_symlink()
                else "missing"
            )
    records = dependency_manifest.get("files", []) if isinstance(dependency_manifest, dict) else []
    if isinstance(records, list):
        for item in records:
            if not isinstance(item, dict):
                continue
            scope, relative = item.get("scope"), item.get("path")
            if scope not in {"skill", "repository"} or not isinstance(relative, str):
                continue
            base = ROOT if scope == "skill" else REPOSITORY_ROOT
            target = (base / relative).resolve()
            key = f"dependency:{scope}:{relative}"
            snapshot[key] = (
                sha256_file(target)
                if target.is_file() and not target.is_symlink()
                else "missing"
            )
    return dict(sorted(snapshot.items()))


def print_postflight_error() -> None:
    print(
        json.dumps(
            {"valid": False, "errors": ["regression_postflight_input_drift"]},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ),
        file=sys.stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=sorted(SUITES), required=True)
    parser.add_argument(
        "--test-manifest",
        type=Path,
        default=ROOT / "evals" / "test-generation-manifest.json",
    )
    parser.add_argument(
        "--dependency-manifest",
        type=Path,
        default=ROOT / "evals" / "regression-dependency-manifest.json",
    )
    args = parser.parse_args()
    test_manifest_path = args.test_manifest.expanduser().resolve()
    dependency_manifest_path = args.dependency_manifest.expanduser().resolve()
    try:
        verify_dependency_manifest(dependency_manifest_path)
        registered = registered_test_paths(test_manifest_path)
        selected = selected_test_paths(registered, args.suite)
    except RegressionManifestError as error:
        print(
            json.dumps(
                {"valid": False, "errors": [str(error)]},
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 3
    before = regression_input_snapshot(test_manifest_path, dependency_manifest_path)
    passed = run_suite(selected)
    try:
        verify_dependency_manifest(dependency_manifest_path)
        registered_test_paths(test_manifest_path)
        after = regression_input_snapshot(test_manifest_path, dependency_manifest_path)
    except RegressionManifestError:
        print_postflight_error()
        return 3
    if before != after:
        print_postflight_error()
        return 3
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
