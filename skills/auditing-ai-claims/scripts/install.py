#!/usr/bin/env python3
"""Install the executable auditing-ai-claims bundle without local evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import sys
import tempfile
from pathlib import Path


SKILL_NAME = "auditing-ai-claims"
SCRIPT_PATH = Path(os.path.abspath(__file__))
SOURCE_ROOT = SCRIPT_PATH.parent.parent

# Keep this list explicit. Evaluation traces, tests, examples, launch material,
# caches, and local audit artifacts are intentionally not part of an install.
INSTALL_ALLOWLIST = (
    "SKILL.md",
    "agents/openai.yaml",
    "LICENSE",
    "NOTICE.md",
    "PROVENANCE.md",
    "references/runtime-contract.md",
    "references/source-policy.md",
    "references/status-policy.md",
    "references/workflow-loop.md",
    "schemas/assessment.schema.json",
    "schemas/candidates.schema.json",
    "schemas/claim-ledger.schema.json",
    "schemas/claim.schema.json",
    "schemas/countercheck.schema.json",
    "schemas/evidence.schema.json",
    "schemas/gate-report.schema.json",
    "schemas/source-receipt.schema.json",
    "schemas/source-transaction.schema.json",
    "schemas/summary.schema.json",
    "schemas/workflow-next.schema.json",
    "scripts/claim_audit.py",
    "templates/assessment.json",
    "templates/candidates.json",
    "templates/claim.json",
    "templates/countercheck.json",
    "templates/evidence.json",
    "templates/summary.json",
)


class InstallError(RuntimeError):
    """A fail-closed installation error."""


def _reject_source_symlinks(root: Path) -> None:
    if root.is_symlink() or SCRIPT_PATH.is_symlink():
        raise InstallError("source skill tree contains a symbolic link")
    for current_root, directory_names, file_names in os.walk(root, followlinks=False):
        current = Path(current_root)
        for name in directory_names + file_names:
            if (current / name).is_symlink():
                raise InstallError("source skill tree contains a symbolic link")


def _validated_source_files(root: Path) -> list[tuple[str, Path, int]]:
    _reject_source_symlinks(root)
    files: list[tuple[str, Path, int]] = []
    for relative in INSTALL_ALLOWLIST:
        source = root / relative
        try:
            source_stat = source.lstat()
        except FileNotFoundError as exc:
            raise InstallError(f"allowlisted source file is missing: {relative}") from exc
        if not stat.S_ISREG(source_stat.st_mode):
            raise InstallError(f"allowlisted source is not a regular file: {relative}")
        files.append((relative, source, stat.S_IMODE(source_stat.st_mode)))
    return files


def _tree_sha256(
    root: Path, relative_paths: tuple[str, ...], *, require_exact: bool = False
) -> str:
    digest = hashlib.sha256()
    expected_paths = sorted(relative_paths)
    actual_paths = expected_paths
    if require_exact:
        actual_paths = []
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise InstallError("tree hash refused a symbolic link")
            if path.is_file():
                actual_paths.append(path.relative_to(root).as_posix())
        if actual_paths != expected_paths:
            raise InstallError("installed tree differs from the runtime allowlist")

    for relative in actual_paths:
        path = root / relative
        if path.is_symlink() or not path.is_file():
            raise InstallError(f"tree hash refused a non-regular file: {relative}")
        data = path.read_bytes()
        encoded_path = relative.encode("utf-8")
        digest.update(len(encoded_path).to_bytes(8, "big"))
        digest.update(encoded_path)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _copy_to_stage(
    source_files: list[tuple[str, Path, int]], stage: Path
) -> None:
    for relative, source, source_mode in source_files:
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as reader, destination.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        destination.chmod(source_mode)


def _remove_install_tree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def install(target_root: Path) -> dict[str, str]:
    source_files = _validated_source_files(SOURCE_ROOT)
    source_hash = _tree_sha256(SOURCE_ROOT, INSTALL_ALLOWLIST)

    target_root.mkdir(parents=True, exist_ok=True)
    if target_root.is_symlink() or not target_root.is_dir():
        raise InstallError("target root must be a real directory")
    target_root = target_root.resolve(strict=True)
    target = target_root / SKILL_NAME
    if target.exists() or target.is_symlink():
        raise InstallError("installation target already exists")

    lock_path = target_root / f".{SKILL_NAME}.install.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise InstallError("another installation is already in progress") from exc

    stage: Path | None = None
    published = False
    try:
        os.close(lock_fd)
        stage = Path(
            tempfile.mkdtemp(prefix=f".{SKILL_NAME}.staging-", dir=target_root)
        )
        _copy_to_stage(source_files, stage)
        target_hash = _tree_sha256(stage, INSTALL_ALLOWLIST, require_exact=True)
        if target_hash != source_hash:
            raise InstallError("staged files do not match the allowlisted source")
        if target.exists() or target.is_symlink():
            raise InstallError("installation target already exists")

        # The sibling-directory rename publishes the fully verified tree in one
        # filesystem operation. os.rename also refuses a populated target;
        # the lock serializes this installer and the explicit checks refuse
        # every pre-existing target, including a symbolic link.
        os.rename(stage, target)
        published = True
        installed_hash = _tree_sha256(target, INSTALL_ALLOWLIST, require_exact=True)
        if installed_hash != source_hash:
            raise InstallError("installed files do not match the allowlisted source")
        payload = {
            "skill": SKILL_NAME,
            "source": str(SOURCE_ROOT.resolve(strict=True)),
            "target": str(target.resolve(strict=True)),
            "source_tree_sha256": source_hash,
            "target_tree_sha256": installed_hash,
        }
        published = False
        stage = None
        return payload
    finally:
        try:
            if published and stage is not None and (target.exists() or target.is_symlink()):
                try:
                    os.rename(target, stage)
                except OSError:
                    _remove_install_tree(target)
            if stage is not None:
                _remove_install_tree(stage)
        finally:
            try:
                lock_path.unlink()
            except FileNotFoundError:
                pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Install the audited runtime-only Skill bundle."
    )
    parser.add_argument(
        "--target-root",
        required=True,
        type=Path,
        help="Skill root that will receive auditing-ai-claims",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        payload = install(args.target_root.expanduser())
    except (InstallError, OSError) as exc:
        print(f"install failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
