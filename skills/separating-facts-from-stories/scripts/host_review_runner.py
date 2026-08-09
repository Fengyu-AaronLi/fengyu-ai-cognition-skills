#!/usr/bin/env python3
"""Run the fixed two-pass Codex review contract and bind host evidence.

The public CLI accepts no prompt, model, working-directory, sandbox, source
hash, output-directory, or argv override.  Those values are derived from the
repository and enforced again by ``codex_exec_host.py`` when each attestation
is bound.  This is local host evidence, not external reviewer identity proof.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import uuid
from pathlib import Path, PurePosixPath
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
REPO_ROOT = SKILL_DIR.parents[1]
SOURCE_MANIFEST = Path("workflows/separating-facts-release-sources.json")
ATTESTATION_TYPES = ("p0_zero", "reproducible_p1_zero")


class HostReviewRunnerError(RuntimeError):
    pass


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise HostReviewRunnerError(f"MODULE_LOAD_FAILED:{path.name}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


HOST = _load_module("sffs_host_review_exec", SCRIPT_DIR / "codex_exec_host.py")
PRODUCER = _load_module(
    "sffs_host_review_producer", SCRIPT_DIR / "produce_release_gate.py"
)


def _safe_source_file(repo_root: Path, value: str) -> tuple[Path, str]:
    relative = PurePosixPath(value)
    if (
        relative.is_absolute()
        or relative.as_posix() != value
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise HostReviewRunnerError("REVIEW_SOURCE_PATH_INVALID")
    root = repo_root.resolve(strict=True)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise HostReviewRunnerError("REVIEW_SOURCE_SYMLINK_INVALID")
    try:
        path = current.resolve(strict=True)
        path.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise HostReviewRunnerError("REVIEW_SOURCE_PATH_INVALID") from exc
    if not path.is_file() or path.is_symlink():
        raise HostReviewRunnerError("REVIEW_SOURCE_FILE_INVALID")
    return path, relative.as_posix()


def source_snapshot(repo_root: Path) -> dict[str, Any]:
    root = repo_root.resolve(strict=True)
    if re.search(r"[\x00-\x1f\x7f]", str(root)):
        raise HostReviewRunnerError("REVIEW_PATH_UNSAFE")
    manifest_path, manifest_relative = _safe_source_file(root, SOURCE_MANIFEST.as_posix())
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HostReviewRunnerError("REVIEW_SOURCE_MANIFEST_INVALID") from exc
    if not isinstance(manifest, dict) or set(manifest) != {"schema_version", "source_files"}:
        raise HostReviewRunnerError("REVIEW_SOURCE_MANIFEST_INVALID")
    declared = manifest.get("source_files")
    if (
        manifest.get("schema_version") != "1.0.0"
        or not isinstance(declared, list)
        or not declared
        or any(not isinstance(item, str) or not item for item in declared)
        or declared != sorted(declared)
        or len(set(declared)) != len(declared)
        or manifest_relative not in declared
    ):
        raise HostReviewRunnerError("REVIEW_SOURCE_MANIFEST_INVALID")
    files: dict[str, str] = {}
    for value in declared:
        path, relative = _safe_source_file(root, value)
        files[relative] = HOST.file_sha256(path)
    ordered = dict(sorted(files.items()))
    return {
        "source_sha256": hashlib.sha256(HOST.canonical_bytes(ordered)).hexdigest(),
        "files": ordered,
        "manifest_path": manifest_relative,
        "manifest_sha256": HOST.file_sha256(manifest_path),
    }


def _assert_same_source(repo_root: Path, expected: dict[str, Any]) -> None:
    observed = source_snapshot(repo_root)
    if observed != expected:
        raise HostReviewRunnerError("REVIEW_SOURCE_DRIFT")


def _run_one(
    *,
    repo_root: Path,
    run_root: Path,
    codex_path: Path,
    attestation_type: str,
    source: dict[str, Any],
    source_identity_path: Path,
) -> Path:
    control_dir = run_root / ".control"
    control_dir.mkdir(parents=True, exist_ok=True)
    prompt_path = control_dir / f"{attestation_type}.txt"
    prompt_bytes = HOST.build_review_prompt(
        repo_root=repo_root,
        attestation_type=attestation_type,
        source_sha256=source["source_sha256"],
    ).encode("utf-8")
    HOST._atomic_write_bytes(prompt_path, prompt_bytes)
    receipt_path = HOST.run_codex_execution(
        codex_path=codex_path,
        prompt_path=prompt_path,
        output_dir=run_root / attestation_type,
        cwd=repo_root,
        execution_kind="review",
        subject_id=attestation_type,
        model=HOST.REVIEW_MODEL,
        reasoning_effort=HOST.REVIEW_REASONING_EFFORT,
        sandbox=HOST.REVIEW_SANDBOX,
        timeout_seconds=HOST.DEFAULT_TIMEOUT_SECONDS,
        input_path=None,
        context_path=source_identity_path,
        source_sha256=source["source_sha256"],
    )
    _assert_same_source(repo_root, source)
    return receipt_path


def run_pair(*, repo_root: Path, codex_path: Path) -> dict[str, Any]:
    root = repo_root.resolve(strict=True)
    codex = codex_path.resolve(strict=True)
    source = source_snapshot(root)
    run_id = f"review-{uuid.uuid4()}"
    run_root = root / ".ao-output" / "reviews" / run_id
    run_root.mkdir(parents=True, mode=0o700)
    source_identity_path = run_root / "source-identity.json"
    HOST._atomic_write_json(
        source_identity_path,
        {
            "schema_version": HOST.REVIEW_SOURCE_IDENTITY_SCHEMA_VERSION,
            **source,
        },
    )
    reports: dict[str, Path] = {}
    for attestation_type in ATTESTATION_TYPES:
        receipt = _run_one(
            repo_root=root,
            run_root=run_root,
            codex_path=codex,
            attestation_type=attestation_type,
            source=source,
            source_identity_path=source_identity_path,
        )
        report_path = run_root / "attestations" / f"{attestation_type}.json"
        HOST.write_review_attestation(
            receipt_path=receipt,
            repo_root=root,
            attestation_type=attestation_type,
            source_sha256=source["source_sha256"],
            output_path=report_path,
        )
        reports[attestation_type] = report_path
    _assert_same_source(root, source)
    p0 = json.loads(reports["p0_zero"].read_text(encoding="utf-8"))
    p1 = json.loads(
        reports["reproducible_p1_zero"].read_text(encoding="utf-8")
    )
    p0_open, p1_open = PRODUCER.validate_review_pair(
        p0,
        p1,
        source_sha256=source["source_sha256"],
        repo_root=root,
    )
    return {
        "valid": p0_open == 0 and p1_open == 0,
        "trust_boundary": HOST.TRUST_BOUNDARY,
        "source_sha256": source["source_sha256"],
        "run_root": str(run_root),
        "review_attestations": {
            key: str(value) for key, value in sorted(reports.items())
        },
        "p0_open": p0_open,
        "reproducible_p1_open": p1_open,
    }


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_subparsers(dest="command", required=True).add_parser(
        "run-pair",
        help="run the fixed two-pass review contract for the current repository",
    )
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.command != "run-pair":
        return 2
    codex = shutil.which("codex")
    if not codex:
        print(json.dumps({"valid": False, "error": "CODEX_NOT_FOUND"}))
        return 2
    try:
        result = run_pair(repo_root=REPO_ROOT, codex_path=Path(codex))
    except (HostReviewRunnerError, HOST.HostExecutionError, OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
