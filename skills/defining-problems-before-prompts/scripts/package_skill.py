#!/usr/bin/env python3
"""Build a verified runtime-only Skill bundle from an explicit allowlist."""

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


SKILL_NAME = "defining-problems-before-prompts"
SOURCE_ROOT = Path(os.path.abspath(__file__)).parent.parent
MANIFEST_PATH = SOURCE_ROOT / "install-manifest.json"


class PackageError(RuntimeError):
    """Fail-closed packaging error."""


def _load_allowlist() -> tuple[str, ...]:
    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PackageError("install manifest is unreadable") from exc
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema_version") != "1.0"
        or manifest.get("skill") != SKILL_NAME
        or not isinstance(manifest.get("files"), list)
    ):
        raise PackageError("install manifest has an invalid contract")
    files = manifest["files"]
    if not all(isinstance(item, str) and item.strip() for item in files):
        raise PackageError("install manifest contains an invalid path")
    if files != sorted(set(files)):
        raise PackageError("install manifest paths must be sorted and unique")
    for relative in files:
        path = Path(relative)
        if path.is_absolute() or ".." in path.parts:
            raise PackageError("install manifest path escapes the Skill root")
    return tuple(files)


def _source_files(allowlist: tuple[str, ...]) -> list[tuple[str, Path, int]]:
    if SOURCE_ROOT.is_symlink():
        raise PackageError("source Skill root must not be a symbolic link")
    resolved_root = SOURCE_ROOT.resolve(strict=True)
    files: list[tuple[str, Path, int]] = []
    for relative in allowlist:
        source = SOURCE_ROOT / relative
        ancestor = SOURCE_ROOT
        for part in Path(relative).parts[:-1]:
            ancestor /= part
            try:
                ancestor_stat = ancestor.lstat()
            except FileNotFoundError as exc:
                raise PackageError(f"allowlisted file is missing: {relative}") from exc
            if stat.S_ISLNK(ancestor_stat.st_mode):
                raise PackageError(
                    f"allowlisted path has a symbolic link ancestor: {relative}"
                )
        try:
            source_stat = source.lstat()
        except FileNotFoundError as exc:
            raise PackageError(f"allowlisted file is missing: {relative}") from exc
        if not stat.S_ISREG(source_stat.st_mode) or source.is_symlink():
            raise PackageError(f"allowlisted path is not a regular file: {relative}")
        resolved_source = source.resolve(strict=True)
        if not resolved_source.is_relative_to(resolved_root):
            raise PackageError(f"allowlisted file resolves outside the Skill root: {relative}")
        files.append((relative, resolved_source, stat.S_IMODE(source_stat.st_mode)))
    return files


def _tree_sha256(root: Path, allowlist: tuple[str, ...], *, exact: bool) -> str:
    if exact:
        actual = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and not path.is_symlink()
        )
        if actual != list(allowlist):
            raise PackageError("bundle differs from the install allowlist")
        if any(path.is_symlink() for path in root.rglob("*")):
            raise PackageError("bundle contains a symbolic link")
    digest = hashlib.sha256()
    for relative in allowlist:
        data = (root / relative).read_bytes()
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _copy_files(files: list[tuple[str, Path, int]], stage: Path) -> None:
    for relative, source, mode in files:
        destination = stage / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with source.open("rb") as reader, destination.open("xb") as writer:
            shutil.copyfileobj(reader, writer)
            writer.flush()
            os.fsync(writer.fileno())
        destination.chmod(mode)


def _remove_tree(path: Path) -> None:
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.exists():
        shutil.rmtree(path)


def package(target_root: Path) -> dict[str, str]:
    allowlist = _load_allowlist()
    files = _source_files(allowlist)
    source_hash = _tree_sha256(SOURCE_ROOT, allowlist, exact=False)

    target_root.mkdir(parents=True, exist_ok=True)
    if target_root.is_symlink() or not target_root.is_dir():
        raise PackageError("target root must be a real directory")
    target_root = target_root.resolve(strict=True)
    target = target_root / SKILL_NAME
    if target.exists() or target.is_symlink():
        raise PackageError("bundle target already exists")

    lock_path = target_root / f".{SKILL_NAME}.package.lock"
    try:
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as exc:
        raise PackageError("another package build is in progress") from exc

    stage: Path | None = None
    try:
        os.close(lock_fd)
        stage = Path(tempfile.mkdtemp(prefix=f".{SKILL_NAME}.stage-", dir=target_root))
        _copy_files(files, stage)
        staged_hash = _tree_sha256(stage, allowlist, exact=True)
        if staged_hash != source_hash:
            raise PackageError("staged bundle does not match its source")
        os.rename(stage, target)
        stage = None
        target_hash = _tree_sha256(target, allowlist, exact=True)
        if target_hash != source_hash:
            _remove_tree(target)
            raise PackageError("published bundle failed final verification")
        return {
            "bundle": str(target),
            "skill": SKILL_NAME,
            "source_tree_sha256": source_hash,
            "target_tree_sha256": target_hash,
        }
    finally:
        if stage is not None:
            _remove_tree(stage)
        try:
            lock_path.unlink()
        except FileNotFoundError:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the runtime-only Skill bundle.")
    parser.add_argument("--target-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        result = package(args.target_root.expanduser())
    except (OSError, PackageError) as exc:
        print(f"package failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
