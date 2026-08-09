#!/usr/bin/env python3
"""Synchronize or verify the closed non-test dependency inventory.

This tool is intentionally separate from ``run_regressions.py``.  A release
operator may explicitly synchronize a candidate after source changes; a test
run may only verify the already frozen inventory and must never repair it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Iterable


DEFAULT_SKILL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPOSITORY_ROOT = DEFAULT_SKILL_ROOT.parents[1]
DEFAULT_MANIFEST = DEFAULT_SKILL_ROOT / "evals" / "regression-dependency-manifest.json"

REPOSITORY_FILES = ("LICENSE", "NOTICE.md", "provenance.yml")
CORE_SKILL_FILES = (
    "LICENSE",
    "Makefile",
    "NOTICE.md",
    "PROVENANCE.md",
    "README.md",
    "SKILL.md",
    "SOURCE_OF_TRUTH.md",
    "VERSION",
    "problem-spec.md",
    "zero-threshold-prompt.md",
)
IMMUTABLE_TREES = (
    "agents",
    "docs",
    "examples",
    "launch",
    "references",
    "schemas",
    "scripts",
    "templates",
    "workflows",
)
FORBIDDEN_EXACT = {
    "evals/evolution-log.md",
    "evals/regression-dependency-manifest.json",
    "evals/release-gate.json",
}
FORBIDDEN_PREFIXES = (
    "dist/",
    "evals/blocker-resolutions/",
    "evals/receipts/",
    "evals/runs/",
)
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class DependencyInventoryError(RuntimeError):
    """One stable, machine-readable dependency inventory failure."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_json(payload: object) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")


def safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise DependencyInventoryError("regression_dependency_unsafe_path")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or path.as_posix() != value:
        raise DependencyInventoryError("regression_dependency_unsafe_path")
    return value


def forbidden_skill_path(relative: str) -> bool:
    path = Path(relative)
    return bool(
        relative in FORBIDDEN_EXACT
        or any(relative.startswith(prefix) for prefix in FORBIDDEN_PREFIXES)
        or "__pycache__" in path.parts
        or "dist" in path.parts
        or path.suffix == ".pyc"
        or path.name.endswith(".lock")
        or path.name.startswith(".v2-eval-")
        or path.name.startswith(".v2-boundary-")
    )


def resolve_regular(base: Path, relative: str) -> Path:
    relative = safe_relative(relative)
    target = base / relative
    if target.is_symlink():
        raise DependencyInventoryError("regression_dependency_symlink")
    try:
        target.resolve(strict=False).relative_to(base.resolve())
    except ValueError as error:
        raise DependencyInventoryError("regression_dependency_unsafe_path") from error
    if not target.is_file():
        raise DependencyInventoryError("regression_dependency_missing")
    return target


def load_json(path: Path, code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DependencyInventoryError(code) from error
    if not isinstance(value, dict):
        raise DependencyInventoryError(code)
    return value


def add_tree(
    identities: set[tuple[str, str]],
    skill_root: Path,
    directory: str,
) -> None:
    tree = skill_root / directory
    if not tree.exists():
        return
    if tree.is_symlink() or not tree.is_dir():
        raise DependencyInventoryError("regression_dependency_symlink")
    for path in tree.rglob("*"):
        relative = path.relative_to(skill_root).as_posix()
        if path.is_symlink():
            if not forbidden_skill_path(relative):
                raise DependencyInventoryError("regression_dependency_symlink")
            continue
        if path.is_file() and not forbidden_skill_path(relative):
            identities.add(("skill", relative))


def add_declared_skill_path(
    identities: set[tuple[str, str]],
    skill_root: Path,
    value: object,
) -> None:
    relative = safe_relative(value)
    if forbidden_skill_path(relative):
        raise DependencyInventoryError("regression_dependency_forbidden_path")
    resolve_regular(skill_root, relative)
    identities.add(("skill", relative))


def add_baseline_bindings(
    identities: set[tuple[str, str]],
    skill_root: Path,
    manifest_path: Path,
) -> None:
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return
    payload = load_json(manifest_path, "regression_dependency_baseline_manifest_invalid")
    bindings = payload.get("bindings", {})
    if not isinstance(bindings, dict):
        raise DependencyInventoryError("regression_dependency_baseline_manifest_invalid")
    for binding in bindings.values():
        if not isinstance(binding, dict) or "path" not in binding:
            raise DependencyInventoryError("regression_dependency_baseline_manifest_invalid")
        add_declared_skill_path(identities, skill_root, binding["path"])
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        raise DependencyInventoryError("regression_dependency_baseline_manifest_invalid")
    for case in cases:
        if not isinstance(case, dict):
            raise DependencyInventoryError("regression_dependency_baseline_manifest_invalid")
        raw_record = case.get("raw_record")
        if isinstance(raw_record, dict) and raw_record.get("path"):
            add_declared_skill_path(identities, skill_root, raw_record["path"])


def add_live_e2e_tree(
    identities: set[tuple[str, str]],
    skill_root: Path,
    manifest_path: Path,
) -> None:
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return
    payload = load_json(manifest_path, "regression_dependency_live_manifest_invalid")
    bindings = payload.get("bindings", {})
    if not isinstance(bindings, dict):
        raise DependencyInventoryError("regression_dependency_live_manifest_invalid")
    for binding in bindings.values():
        if not isinstance(binding, dict) or "path" not in binding:
            raise DependencyInventoryError("regression_dependency_live_manifest_invalid")
        add_declared_skill_path(identities, skill_root, binding["path"])

    run_paths: list[Path] = []
    cases = payload.get("cases", [])
    if not isinstance(cases, list):
        raise DependencyInventoryError("regression_dependency_live_manifest_invalid")
    for case in cases:
        if not isinstance(case, dict):
            raise DependencyInventoryError("regression_dependency_live_manifest_invalid")
        run = case.get("run")
        if isinstance(run, dict) and run.get("path"):
            relative = safe_relative(run["path"])
            resolve_regular(skill_root, relative)
            run_paths.append(Path(relative))
    review = payload.get("review")
    if isinstance(review, dict) and review.get("path"):
        relative = safe_relative(review["path"])
        resolve_regular(skill_root, relative)
        run_paths.append(Path(relative))
    if not run_paths:
        return
    common_parent = Path(os.path.commonpath([str(path.parent) for path in run_paths]))
    common_relative = safe_relative(common_parent.as_posix())
    add_tree(identities, skill_root, common_relative)


def add_test_migrations(
    identities: set[tuple[str, str]],
    skill_root: Path,
    migrations_root: Path,
) -> None:
    if not migrations_root.exists():
        return
    if migrations_root.is_symlink() or not migrations_root.is_dir():
        raise DependencyInventoryError("regression_dependency_symlink")
    for receipt_path in sorted(migrations_root.glob("*.json")):
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise DependencyInventoryError("regression_dependency_symlink")
        relative = receipt_path.relative_to(skill_root).as_posix()
        identities.add(("skill", relative))
        receipt = load_json(
            receipt_path,
            "regression_dependency_migration_receipt_invalid",
        )
        evidence = receipt.get("evidence", [])
        if not isinstance(evidence, list):
            raise DependencyInventoryError(
                "regression_dependency_migration_receipt_invalid"
            )
        for item in evidence:
            if not isinstance(item, dict) or not item.get("path"):
                raise DependencyInventoryError(
                    "regression_dependency_migration_receipt_invalid"
                )
            add_declared_skill_path(identities, skill_root, item["path"])


def add_red_evidence_bindings(
    identities: set[tuple[str, str]],
    skill_root: Path,
    manifest_path: Path,
) -> None:
    if not manifest_path.is_file() or manifest_path.is_symlink():
        return
    payload = load_json(
        manifest_path,
        "regression_dependency_red_evidence_manifest_invalid",
    )
    records = payload.get("records")
    if (
        payload.get("schema_version") != "1.0"
        or payload.get("append_only") is not True
        or not isinstance(records, list)
    ):
        raise DependencyInventoryError(
            "regression_dependency_red_evidence_manifest_invalid"
        )
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("tests"), list):
            raise DependencyInventoryError(
                "regression_dependency_red_evidence_manifest_invalid"
            )
        evidence = record.get("evidence")
        if not isinstance(evidence, dict) or not evidence.get("path"):
            raise DependencyInventoryError(
                "regression_dependency_red_evidence_manifest_invalid"
            )
        add_declared_skill_path(identities, skill_root, evidence["path"])
        for test in record["tests"]:
            if not isinstance(test, dict) or not test.get("path"):
                raise DependencyInventoryError(
                    "regression_dependency_red_evidence_manifest_invalid"
                )


def expected_identities(
    skill_root: Path,
    repository_root: Path,
) -> list[tuple[str, str]]:
    skill_root = skill_root.expanduser().resolve()
    repository_root = repository_root.expanduser().resolve()
    identities: set[tuple[str, str]] = set()
    for relative in REPOSITORY_FILES:
        resolve_regular(repository_root, relative)
        identities.add(("repository", relative))
    for relative in CORE_SKILL_FILES:
        resolve_regular(skill_root, relative)
        identities.add(("skill", relative))
    for directory in IMMUTABLE_TREES:
        add_tree(identities, skill_root, directory)

    evals_root = skill_root / "evals"
    if evals_root.is_dir() and not evals_root.is_symlink():
        for path in evals_root.iterdir():
            relative = path.relative_to(skill_root).as_posix()
            if path.is_symlink():
                if not forbidden_skill_path(relative):
                    raise DependencyInventoryError("regression_dependency_symlink")
                continue
            if path.is_file() and not forbidden_skill_path(relative):
                identities.add(("skill", relative))
        add_tree(identities, skill_root, "evals/schemas")
        add_baseline_bindings(
            identities,
            skill_root,
            evals_root / "baseline-evidence-manifest.json",
        )
        add_live_e2e_tree(
            identities,
            skill_root,
            evals_root / "live-e2e-manifest.json",
        )
        add_red_evidence_bindings(
            identities,
            skill_root,
            evals_root / "red-evidence-manifest.json",
        )
        add_test_migrations(identities, skill_root, evals_root / "test-migrations")
        preregistration = (
            evals_root / "raw/v2-forward/attribution-blind-v9/preregistration.json"
        )
        if preregistration.is_file() and not preregistration.is_symlink():
            identities.add(
                ("skill", preregistration.relative_to(skill_root).as_posix())
            )
    elif evals_root.exists():
        raise DependencyInventoryError("regression_dependency_symlink")
    return sorted(identities)


def records_for(
    skill_root: Path,
    repository_root: Path,
    identities: Iterable[tuple[str, str]],
) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for scope, relative in identities:
        base = skill_root if scope == "skill" else repository_root
        target = resolve_regular(base, relative)
        records.append(
            {"scope": scope, "path": relative, "sha256": sha256_file(target)}
        )
    return records


def read_manifest_records(
    manifest_path: Path,
    skill_root: Path,
    repository_root: Path,
) -> list[dict[str, str]]:
    payload = load_json(manifest_path, "regression_dependency_manifest_invalid")
    if set(payload) != {"schema_version", "files"} or payload.get("schema_version") != "1.0":
        raise DependencyInventoryError("regression_dependency_manifest_invalid")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        raise DependencyInventoryError("regression_dependency_manifest_invalid")
    records: list[dict[str, str]] = []
    identities: list[tuple[str, str]] = []
    for item in files:
        if not isinstance(item, dict) or set(item) != {"scope", "path", "sha256"}:
            raise DependencyInventoryError("regression_dependency_manifest_invalid")
        scope = item.get("scope")
        if scope not in {"skill", "repository"}:
            raise DependencyInventoryError("regression_dependency_manifest_invalid")
        relative = safe_relative(item.get("path"))
        if scope == "repository" and relative not in REPOSITORY_FILES:
            raise DependencyInventoryError("dependency_inventory_extra")
        if scope == "skill" and forbidden_skill_path(relative):
            raise DependencyInventoryError("regression_dependency_forbidden_path")
        expected_hash = item.get("sha256")
        if not isinstance(expected_hash, str) or SHA256_PATTERN.fullmatch(expected_hash) is None:
            raise DependencyInventoryError("regression_dependency_manifest_invalid")
        base = skill_root if scope == "skill" else repository_root
        target = resolve_regular(base, relative)
        if sha256_file(target) != expected_hash:
            raise DependencyInventoryError("regression_dependency_hash_mismatch")
        records.append({"scope": scope, "path": relative, "sha256": expected_hash})
        identities.append((scope, relative))
    if identities != sorted(set(identities)):
        raise DependencyInventoryError("regression_dependency_manifest_invalid")
    return records


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        try:
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
        except OSError:
            directory_descriptor = None
        if directory_descriptor is not None:
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    finally:
        if temporary.exists():
            temporary.unlink()


def emit(valid: bool, *, mode: str, count: int = 0, error: str | None = None) -> int:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "valid": valid,
        "mode": mode,
        "dependency_count": count,
        "errors": [] if error is None else [error],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if valid else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("check", "sync"))
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--skill-root", type=Path, default=DEFAULT_SKILL_ROOT)
    parser.add_argument(
        "--repository-root",
        type=Path,
        default=DEFAULT_REPOSITORY_ROOT,
    )
    args = parser.parse_args()
    skill_root = args.skill_root.expanduser().resolve()
    repository_root = args.repository_root.expanduser().resolve()
    manifest_path = args.manifest.expanduser().resolve()
    try:
        try:
            manifest_path.relative_to(skill_root)
        except ValueError as error:
            raise DependencyInventoryError(
                "regression_dependency_manifest_path_unsafe"
            ) from error
        identities = expected_identities(skill_root, repository_root)
        expected_records = records_for(
            skill_root,
            repository_root,
            identities,
        )
        if args.mode == "sync":
            atomic_write(
                manifest_path,
                canonical_json({"schema_version": "1.0", "files": expected_records}),
            )
            return emit(True, mode="sync", count=len(expected_records))

        observed_records = read_manifest_records(
            manifest_path,
            skill_root,
            repository_root,
        )
        observed = {(item["scope"], item["path"]) for item in observed_records}
        expected = set(identities)
        if expected - observed:
            raise DependencyInventoryError("dependency_inventory_missing")
        if observed - expected:
            raise DependencyInventoryError("dependency_inventory_extra")
        return emit(True, mode="check", count=len(expected_records))
    except DependencyInventoryError as error:
        return emit(False, mode=args.mode, error=str(error))


if __name__ == "__main__":
    raise SystemExit(main())
