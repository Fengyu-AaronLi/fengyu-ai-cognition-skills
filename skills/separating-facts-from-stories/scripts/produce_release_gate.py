#!/usr/bin/env python3
"""Execute the fixed release recipe and produce a source-bound stop gate.

The producer is intentionally deterministic and non-interactive.  It never
accepts arbitrary commands.  Every subprocess runs without a shell, under an
isolated Python, with a named timeout and a durable raw receipt.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import hashlib
import importlib.util
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = "1.1.0"
RECIPE_VERSION = "2.0.0"
SKILL_NAME = "separating-facts-from-stories"
DEFAULT_TIMEOUT_SECONDS = 300
INSTALL_TIMEOUT_SECONDS = 3600
ISOLATION_FLAGS = ("-I", "-S", "-B")
REQUIRED_GATE_CHECKS = (
    "p0_zero",
    "reproducible_p1_zero",
    "unit_tests",
    "self_test",
    "frozen_eval_18_of_18",
    "artifacts_16_of_16",
    "clean_install",
    "verify_install",
    "rollback",
)
ARTIFACT_ROLES = {
    "p0_zero": "reviewer_report",
    "reproducible_p1_zero": "reviewer_report",
    "unit_tests": "unit_test_log",
    "self_test": "self_test_log",
    "frozen_eval_18_of_18": "machine_report",
    "artifacts_16_of_16": "eval_artifact_report",
    "clean_install": "install_manifest",
    "verify_install": "verification_report",
    "rollback": "rollback_receipt",
}
REQUIRED_REVIEW_SCOPE = (
    "runtime_semantics",
    "safety_routing",
    "state_integrity",
    "release_evidence",
    "packaging_installation",
    "documentation_claims",
)
REVIEW_TRUST_BOUNDARY = (
    "controller_observed_local_codex_process_and_thread_not_external_identity_proof"
)
PROCESS_FAMILY_TOKEN_ENV = "SFFS_RELEASE_PROCESS_FAMILY"
PROCESS_FAMILY_TRUST_BOUNDARY = "cooperative_inherited_token_not_os_sandbox"
PROCESS_FAMILY_GRACE_SECONDS = 0.25


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_tree_directories(root: Path) -> None:
    directories = [path for path in root.rglob("*") if path.is_dir()]
    for path in sorted(directories, key=lambda item: len(item.parts), reverse=True):
        fsync_directory(path)
    fsync_directory(root)


def _publish_directory_no_replace(staging: Path, final: Path) -> None:
    """Atomically publish a directory without replacing any existing target."""
    libc = ctypes.CDLL(None, use_errno=True)
    if sys.platform == "darwin" and hasattr(libc, "renamex_np"):
        result = libc.renamex_np(
            os.fsencode(staging), os.fsencode(final), ctypes.c_uint(0x00000004)
        )
        if result == 0:
            return
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise RuntimeError(f"NO_REPLACE_TARGET_EXISTS: {final}")
        raise OSError(error, os.strerror(error), str(final))
    if sys.platform.startswith("linux") and hasattr(libc, "renameat2"):
        result = libc.renameat2(
            ctypes.c_int(-100),
            os.fsencode(staging),
            ctypes.c_int(-100),
            os.fsencode(final),
            ctypes.c_uint(1),
        )
        if result == 0:
            return
        error = ctypes.get_errno()
        if error in {errno.EEXIST, errno.ENOTEMPTY}:
            raise RuntimeError(f"NO_REPLACE_TARGET_EXISTS: {final}")
        raise OSError(error, os.strerror(error), str(final))
    raise RuntimeError("NO_REPLACE_PUBLICATION_UNSUPPORTED")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def _copy_regular_snapshot_file(source: Path, destination: Path) -> dict[str, Any]:
    """Copy one stable regular file without following links or reusing its inode."""
    try:
        before = source.lstat()
    except OSError as exc:
        raise RuntimeError(f"SNAPSHOT_INPUT_INVALID: {source}: {exc}") from exc
    if not source.is_file() or source.is_symlink() or before.st_nlink != 1:
        raise RuntimeError(f"SNAPSHOT_INPUT_LINK: {source}")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(source, flags)
    try:
        observed = os.fstat(descriptor)
        if (
            observed.st_dev != before.st_dev
            or observed.st_ino != before.st_ino
            or observed.st_size != before.st_size
            or observed.st_nlink != 1
        ):
            raise RuntimeError(f"SNAPSHOT_INPUT_CHANGED: {source}")
        chunks: list[bytes] = []
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
        payload = b"".join(chunks)
    finally:
        os.close(descriptor)
    after = source.lstat()
    if (
        after.st_dev != before.st_dev
        or after.st_ino != before.st_ino
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or after.st_nlink != 1
    ):
        raise RuntimeError(f"SNAPSHOT_INPUT_CHANGED: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    fsync_directory(destination.parent)
    copied = destination.stat()
    if copied.st_dev == before.st_dev and copied.st_ino == before.st_ino:
        raise RuntimeError(f"SNAPSHOT_COPY_REUSED_INODE: {source}")
    return {"sha256": sha256_bytes(payload), "size": len(payload)}


def _snapshot_tree_files(root: Path) -> list[Path]:
    if not root.is_dir() or root.is_symlink():
        raise RuntimeError(f"SNAPSHOT_INPUT_INVALID: {root}")
    files: list[Path] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"SNAPSHOT_INPUT_LINK: {path}")
        if path.is_file():
            if path.stat().st_nlink != 1:
                raise RuntimeError(f"SNAPSHOT_INPUT_LINK: {path}")
            files.append(path)
        elif not path.is_dir():
            raise RuntimeError(f"SNAPSHOT_INPUT_INVALID: {path}")
    return files


def materialize_release_basis(
    *,
    repo_root: Path,
    source_files: list[str],
    expected_source: dict[str, Any],
    eval_root: Path,
    review_paths: tuple[Path, Path],
    destination_parent: Path,
) -> dict[str, Any]:
    """Publish immutable proof inputs under their canonical content digest."""
    repo_root = repo_root.resolve()
    if snapshot_files(repo_root, source_files) != expected_source:
        raise RuntimeError("SOURCE_DRIFT_BEFORE_RETENTION")
    destination_parent.mkdir(parents=True, exist_ok=True)
    staging = destination_parent / f".staging-{uuid.uuid4().hex}"
    staging.mkdir()
    entries: dict[str, dict[str, Any]] = {}

    def copy(source: Path, logical: PurePosixPath) -> None:
        key = logical.as_posix()
        if key in entries:
            return
        entries[key] = _copy_regular_snapshot_file(source, staging / key)

    for relative in source_files:
        copy(repo_root / relative, PurePosixPath("source") / relative)
        copy(repo_root / relative, PurePosixPath("reviews") / relative)
    copied_source_hashes = {
        relative: entries[(PurePosixPath("source") / relative).as_posix()]["sha256"]
        for relative in source_files
    }
    if copied_source_hashes != expected_source.get("files"):
        raise RuntimeError("SOURCE_DRIFT_DURING_RETENTION")
    eval_root = eval_root.resolve()
    try:
        eval_root.relative_to(repo_root)
    except ValueError as exc:
        raise RuntimeError("EVAL_SNAPSHOT_OUTSIDE_REPO") from exc
    for source in _snapshot_tree_files(eval_root):
        copy(source, PurePosixPath("eval") / source.relative_to(eval_root).as_posix())

    retained_review_paths: list[str] = []
    for report_path in review_paths:
        report_path = report_path.resolve()
        try:
            report_relative = report_path.relative_to(repo_root).as_posix()
        except ValueError as exc:
            raise RuntimeError("REVIEW_SNAPSHOT_OUTSIDE_REPO") from exc
        report = _read_json(report_path, "review attestation")
        artifact = report.get("review_artifact")
        source_identity = report.get("source_identity")
        host_receipt = report.get("host_execution_receipt")
        if (
            not isinstance(artifact, dict)
            or not isinstance(artifact.get("path"), str)
            or not isinstance(source_identity, dict)
            or not isinstance(source_identity.get("path"), str)
            or not isinstance(host_receipt, dict)
            or not isinstance(host_receipt.get("path"), str)
        ):
            raise RuntimeError("REVIEW_SNAPSHOT_INVALID")
        artifact_path = repo_root / artifact["path"]
        identity_path = repo_root / source_identity["path"]
        receipt_path = repo_root / host_receipt["path"]
        receipt = _read_json(receipt_path, "review host execution receipt")
        copy(report_path, PurePosixPath("reviews") / report_relative)
        copy(artifact_path, PurePosixPath("reviews") / artifact["path"])
        copy(identity_path, PurePosixPath("reviews") / source_identity["path"])
        copy(receipt_path, PurePosixPath("reviews") / host_receipt["path"])
        receipt_artifacts = receipt.get("artifacts")
        if not isinstance(receipt_artifacts, dict):
            raise RuntimeError("REVIEW_SNAPSHOT_INVALID")
        for descriptor in receipt_artifacts.values():
            if not isinstance(descriptor, dict) or not isinstance(
                descriptor.get("path"), str
            ):
                raise RuntimeError("REVIEW_SNAPSHOT_INVALID")
            receipt_artifact = receipt_path.parent / descriptor["path"]
            try:
                receipt_artifact_relative = receipt_artifact.relative_to(repo_root)
            except ValueError as exc:
                raise RuntimeError("REVIEW_SNAPSHOT_OUTSIDE_REPO") from exc
            copy(
                receipt_artifact,
                PurePosixPath("reviews") / receipt_artifact_relative.as_posix(),
            )
        retained_review_paths.append(
            (PurePosixPath("reviews") / report_relative).as_posix()
        )

    ordered = dict(sorted(entries.items()))
    digest = sha256_bytes(canonical_bytes(ordered))
    index = {
        "schema_version": SCHEMA_VERSION,
        "sha256": digest,
        "files": ordered,
        "source_sha256": expected_source["sha256"],
        "trust_boundary": "retained_local_snapshot_not_external_signature",
    }
    write_json(staging / "snapshot-index.json", index)
    _fsync_tree_directories(staging)
    final = destination_parent / digest
    if final.exists():
        raise RuntimeError(f"RELEASE_BASIS_EXISTS: {digest}")
    try:
        _publish_directory_no_replace(staging, final)
    except RuntimeError as exc:
        if "NO_REPLACE_TARGET_EXISTS" not in str(exc):
            raise
        raise RuntimeError(f"RELEASE_BASIS_EXISTS: {digest}") from exc
    fsync_directory(destination_parent)
    basis = {
        "schema_version": SCHEMA_VERSION,
        "sha256": digest,
        "root": str(final.resolve()),
        "index_path": str((final / "snapshot-index.json").resolve()),
        "index_sha256": file_sha256(final / "snapshot-index.json"),
        "source_sha256": expected_source["sha256"],
        "source_root": str((final / "source").resolve()),
        "eval_root": str((final / "eval").resolve()),
        "review_root": str((final / "reviews").resolve()),
        "review_paths": retained_review_paths,
    }
    validate_release_basis(basis)
    return basis


def validate_release_basis(basis: dict[str, Any]) -> None:
    """Re-hash every retained byte; a mutable or linked basis fails closed."""
    try:
        root = Path(basis["root"])
        index_path = Path(basis["index_path"])
    except (KeyError, TypeError) as exc:
        raise RuntimeError("RELEASE_BASIS_TAMPERED: malformed basis") from exc
    if root.is_symlink() or not root.is_dir() or index_path != root / "snapshot-index.json":
        raise RuntimeError("RELEASE_BASIS_TAMPERED: invalid root")
    if root.name != basis.get("sha256") or file_sha256(index_path) != basis.get(
        "index_sha256"
    ):
        raise RuntimeError("RELEASE_BASIS_TAMPERED: index identity")
    index = _read_json(index_path, "release basis index")
    if index.get("sha256") != basis.get("sha256"):
        raise RuntimeError("RELEASE_BASIS_TAMPERED: digest mismatch")
    if index.get("source_sha256") != basis.get("source_sha256"):
        raise RuntimeError("RELEASE_BASIS_TAMPERED: source identity")
    retained_source = {
        relative.removeprefix("source/"): metadata["sha256"]
        for relative, metadata in index.get("files", {}).items()
        if relative.startswith("source/") and isinstance(metadata, dict)
    }
    if sha256_bytes(canonical_bytes(dict(sorted(retained_source.items())))) != basis.get(
        "source_sha256"
    ):
        raise RuntimeError("RELEASE_BASIS_TAMPERED: source bytes do not match identity")
    expected = index.get("files")
    if not isinstance(expected, dict) or sha256_bytes(canonical_bytes(expected)) != basis.get(
        "sha256"
    ):
        raise RuntimeError("RELEASE_BASIS_TAMPERED: malformed index")
    actual_paths = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != index_path
    }
    if actual_paths != set(expected):
        raise RuntimeError("RELEASE_BASIS_TAMPERED: file set")
    for relative, metadata in expected.items():
        path = root / relative
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise RuntimeError(f"RELEASE_BASIS_TAMPERED: linked file {relative}")
        if metadata != {"sha256": file_sha256(path), "size": path.stat().st_size}:
            raise RuntimeError(f"RELEASE_BASIS_TAMPERED: bytes changed {relative}")


def materialize_canonical_install_artifact(
    *, installed: Path, destination_parent: Path, source_basis_sha256: str
) -> dict[str, Any]:
    """Retain the install produced from the source snapshot as a tree artifact."""
    installed = installed.resolve()
    destination_parent.mkdir(parents=True, exist_ok=True)
    staging = destination_parent / f".staging-{uuid.uuid4().hex}"
    staging.mkdir()
    entries: dict[str, dict[str, Any]] = {}
    for source in _snapshot_tree_files(installed):
        relative = source.relative_to(installed).as_posix()
        entries[relative] = _copy_regular_snapshot_file(source, staging / relative)
    ordered = dict(sorted(entries.items()))
    digest = sha256_bytes(canonical_bytes(ordered))
    index = {
        "schema_version": SCHEMA_VERSION,
        "sha256": digest,
        "files": ordered,
        "built_from": "retained_source_snapshot",
        "source_basis_sha256": source_basis_sha256,
        "trust_boundary": "retained_local_snapshot_not_external_signature",
    }
    write_json(staging / "artifact-index.json", index)
    _fsync_tree_directories(staging)
    final = destination_parent / digest
    if final.exists():
        raise RuntimeError(f"CANONICAL_INSTALL_EXISTS: {digest}")
    try:
        _publish_directory_no_replace(staging, final)
    except RuntimeError as exc:
        if "NO_REPLACE_TARGET_EXISTS" not in str(exc):
            raise
        raise RuntimeError(f"CANONICAL_INSTALL_EXISTS: {digest}") from exc
    fsync_directory(destination_parent)
    artifact = {
        "schema_version": SCHEMA_VERSION,
        "sha256": digest,
        "root": str(final.resolve()),
        "index_path": str((final / "artifact-index.json").resolve()),
        "index_sha256": file_sha256(final / "artifact-index.json"),
        "built_from": "retained_source_snapshot",
        "source_basis_sha256": source_basis_sha256,
    }
    validate_canonical_install_artifact(artifact)
    return artifact


def validate_canonical_install_artifact(artifact: dict[str, Any]) -> None:
    try:
        root = Path(artifact["root"])
        index_path = Path(artifact["index_path"])
    except (KeyError, TypeError) as exc:
        raise RuntimeError("CANONICAL_INSTALL_TAMPERED: malformed") from exc
    if (
        root.is_symlink()
        or not root.is_dir()
        or root.name != artifact.get("sha256")
        or index_path != root / "artifact-index.json"
        or file_sha256(index_path) != artifact.get("index_sha256")
    ):
        raise RuntimeError("CANONICAL_INSTALL_TAMPERED: identity")
    index = _read_json(index_path, "canonical install index")
    expected = index.get("files")
    if (
        index.get("sha256") != artifact.get("sha256")
        or index.get("built_from") != "retained_source_snapshot"
        or index.get("source_basis_sha256") != artifact.get("source_basis_sha256")
        or not isinstance(expected, dict)
        or sha256_bytes(canonical_bytes(expected)) != artifact.get("sha256")
    ):
        raise RuntimeError("CANONICAL_INSTALL_TAMPERED: index")
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != index_path
    }
    if actual != set(expected):
        raise RuntimeError("CANONICAL_INSTALL_TAMPERED: file set")
    for relative, metadata in expected.items():
        path = root / relative
        if path.is_symlink() or not path.is_file() or path.stat().st_nlink != 1:
            raise RuntimeError(f"CANONICAL_INSTALL_TAMPERED: linked {relative}")
        if metadata != {"sha256": file_sha256(path), "size": path.stat().st_size}:
            raise RuntimeError(f"CANONICAL_INSTALL_TAMPERED: bytes {relative}")


def isolated_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _darwin_process_is_gone_or_zombie(pid: int) -> bool:
    """Resolve procargs EINVAL without treating a live process as absent."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        pass
    except OSError as exc:
        if exc.errno == errno.ESRCH:
            return True
        raise RuntimeError(f"process state check failed for pid {pid}: {exc}") from exc

    try:
        process = subprocess.Popen(
            ["/bin/ps", "-p", str(pid), "-o", "pid=,state="],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=os.environ.copy(),
        )
        stdout, stderr = process.communicate(timeout=5)
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"process state check failed for pid {pid}: {exc}") from exc
    if process.returncode != 0:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        except PermissionError:
            pass
        except OSError as exc:
            if exc.errno == errno.ESRCH:
                return True
            raise RuntimeError(
                f"process state check failed for pid {pid}: {exc}"
            ) from exc
        raise RuntimeError(
            f"process state check failed for pid {pid}: {stderr.strip()}"
        )
    lines = stdout.splitlines()
    if len(lines) != 1:
        raise RuntimeError(f"malformed process state for pid {pid}")
    fields = lines[0].split()
    if len(fields) != 2:
        raise RuntimeError(f"malformed process state for pid {pid}")
    try:
        observed_pid = int(fields[0])
    except ValueError as exc:
        raise RuntimeError(f"malformed process state for pid {pid}") from exc
    state = fields[1]
    if observed_pid != pid or not state:
        raise RuntimeError(f"malformed process state for pid {pid}")
    return state.startswith("Z")


def _darwin_process_environment(pid: int) -> list[bytes] | None:
    """Read one process environment through KERN_PROCARGS2 without argv matching."""
    libc = ctypes.CDLL(None, use_errno=True)
    sysctl = getattr(libc, "sysctl", None)
    if sysctl is None:
        raise RuntimeError("exact process environment enumeration is unavailable")
    mib = (ctypes.c_int * 3)(1, 49, pid)  # CTL_KERN, KERN_PROCARGS2, pid
    size = ctypes.c_size_t()
    if sysctl(mib, 3, None, ctypes.byref(size), None, 0) != 0:
        error = ctypes.get_errno()
        if error == errno.ESRCH:
            return None
        if error == errno.EINVAL:
            if _darwin_process_is_gone_or_zombie(pid):
                return None
            raise RuntimeError(
                f"KERN_PROCARGS2 EINVAL for live non-zombie pid {pid}"
            )
        raise OSError(error, os.strerror(error))
    if size.value < ctypes.sizeof(ctypes.c_int):
        raise RuntimeError(f"malformed KERN_PROCARGS2 payload for pid {pid}")
    buffer = ctypes.create_string_buffer(size.value)
    if sysctl(mib, 3, buffer, ctypes.byref(size), None, 0) != 0:
        error = ctypes.get_errno()
        if error == errno.ESRCH:
            return None
        if error == errno.EINVAL:
            if _darwin_process_is_gone_or_zombie(pid):
                return None
            raise RuntimeError(
                f"KERN_PROCARGS2 EINVAL for live non-zombie pid {pid}"
            )
        raise OSError(error, os.strerror(error))
    payload = bytes(buffer.raw[: size.value])
    integer_size = ctypes.sizeof(ctypes.c_int)
    argc = int.from_bytes(payload[:integer_size], sys.byteorder, signed=True)
    if argc < 0 or argc > 1_000_000:
        raise RuntimeError(f"malformed KERN_PROCARGS2 argc for pid {pid}")
    cursor = integer_size
    executable_end = payload.find(b"\0", cursor)
    if executable_end < 0:
        raise RuntimeError(f"malformed KERN_PROCARGS2 executable for pid {pid}")
    cursor = executable_end + 1
    while cursor < len(payload) and payload[cursor] == 0:
        cursor += 1
    for _ in range(argc):
        argument_end = payload.find(b"\0", cursor)
        if argument_end < 0:
            raise RuntimeError(f"malformed KERN_PROCARGS2 argv for pid {pid}")
        cursor = argument_end + 1
    return [entry for entry in payload[cursor:].split(b"\0") if entry]


def _linux_process_environment(pid: int) -> list[bytes] | None:
    try:
        payload = Path(f"/proc/{pid}/environ").read_bytes()
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno in {errno.ENOENT, errno.ESRCH}:
            return None
        raise
    return [entry for entry in payload.split(b"\0") if entry]


def _same_uid_process_ids() -> list[int]:
    own_uid = os.getuid()
    if sys.platform.startswith("linux"):
        result: list[int] = []
        try:
            entries = Path("/proc").iterdir()
            for entry in entries:
                if not entry.name.isdigit():
                    continue
                try:
                    if entry.stat().st_uid == own_uid:
                        result.append(int(entry.name))
                except FileNotFoundError:
                    continue
        except OSError as exc:
            raise RuntimeError(f"process enumeration failed: {exc}") from exc
        return result
    if sys.platform == "darwin":
        process = subprocess.Popen(
            ["/bin/ps", "-axo", "pid=,uid="],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            env=os.environ.copy(),
        )
        stdout, stderr = process.communicate(timeout=5)
        if process.returncode != 0:
            raise RuntimeError(f"process enumeration failed: {stderr.strip()}")
        result = []
        for line in stdout.splitlines():
            if not line.strip():
                continue
            parts = line.split()
            if len(parts) != 2:
                raise RuntimeError("malformed process enumeration output")
            try:
                pid, uid = int(parts[0]), int(parts[1])
            except ValueError as exc:
                raise RuntimeError(
                    "malformed process enumeration output"
                ) from exc
            if uid == own_uid:
                result.append(pid)
        return result
    raise RuntimeError("exact process environment enumeration is unsupported")


def enumerate_process_family(token: str) -> list[int]:
    """Enumerate same-UID processes which still expose the inherited token.

    This is a cooperative cleanup mechanism, not an OS security boundary.  A
    hostile child can clear its environment; callers must retain that boundary
    in receipts instead of claiming sandbox containment.
    """
    marker = f"{PROCESS_FAMILY_TOKEN_ENV}={token}".encode("utf-8")
    excluded = {os.getpid()}
    result: list[int] = []
    for pid in _same_uid_process_ids():
        if pid in excluded:
            continue
        if sys.platform == "darwin":
            entries = _darwin_process_environment(pid)
        elif sys.platform.startswith("linux"):
            entries = _linux_process_environment(pid)
        else:
            raise RuntimeError("exact process environment enumeration is unsupported")
        if entries is None:
            continue
        if marker in entries:
            result.append(pid)
    return sorted(set(result))


def _signal_many(pids: list[int], sig: signal.Signals) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            continue
        except PermissionError as exc:
            raise RuntimeError(f"cannot signal marked process {pid}: {exc}") from exc


def clean_process_family(token: str, *, original_pgid: int | None) -> dict[str, Any]:
    """Boundedly stop and remove every visible marked process, fail closed."""
    if original_pgid is not None:
        try:
            os.killpg(original_pgid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        marked = enumerate_process_family(token)
        if marked:
            _signal_many(marked, signal.SIGSTOP)
            _signal_many(marked, signal.SIGTERM)
            deadline = time.monotonic() + PROCESS_FAMILY_GRACE_SECONDS
            while time.monotonic() < deadline:
                remaining = enumerate_process_family(token)
                if not remaining:
                    break
                time.sleep(0.02)
            remaining = enumerate_process_family(token)
            if remaining:
                _signal_many(remaining, signal.SIGKILL)
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline:
                    remaining = enumerate_process_family(token)
                    if not remaining:
                        break
                    time.sleep(0.02)
        remaining = enumerate_process_family(token)
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        raise RuntimeError(f"PROCESS_FAMILY_CLEANUP_INCOMPLETE: {exc}") from exc
    if remaining:
        raise RuntimeError(
            "PROCESS_FAMILY_CLEANUP_INCOMPLETE: marked processes remain: "
            + ",".join(str(pid) for pid in remaining)
        )
    return {
        "token_sha256": sha256_bytes(token.encode("utf-8")),
        "same_uid_only": True,
        "confirmed_empty": True,
        "trust_boundary": PROCESS_FAMILY_TRUST_BOUNDARY,
    }


def _output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _run_in_process_group(
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    """Run a marked command and clean its cooperative process family."""
    token = environment.get(PROCESS_FAMILY_TOKEN_ENV)
    if not token:
        token = uuid.uuid4().hex
        environment = dict(environment)
        environment[PROCESS_FAMILY_TOKEN_ENV] = token
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        shell=False,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired as first_timeout:
        family_policy = clean_process_family(token, original_pgid=process.pid)
        try:
            stdout, stderr = process.communicate(timeout=2)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            family_policy = clean_process_family(token, original_pgid=process.pid)
            stdout, stderr = process.communicate(timeout=2)
        timeout_error = subprocess.TimeoutExpired(
            argv,
            timeout_seconds,
            output=_output_text(stdout) or _output_text(first_timeout.stdout),
            stderr=_output_text(stderr) or _output_text(first_timeout.stderr),
        )
        timeout_error.process_family_policy = family_policy
        raise timeout_error from first_timeout
    family_policy = clean_process_family(token, original_pgid=None)
    completed = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    completed.process_family_policy = family_policy
    return completed


def run_isolated_command(
    *,
    step_id: str,
    script: Path,
    arguments: list[str],
    cwd: Path,
    timeout_seconds: int,
    receipt_path: Path,
) -> dict[str, Any]:
    """Run one fixed Python script and persist its complete process receipt."""
    argv = [sys.executable, *ISOLATION_FLAGS, str(script), *arguments]
    environment = isolated_environment()
    receipt: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "recipe_version": RECIPE_VERSION,
        "step_id": step_id,
        "argv": argv,
        "cwd": str(cwd),
        "timeout_seconds": timeout_seconds,
        "shell": False,
        "environment_policy": {
            "PYTHONPATH": "removed",
            "PYTHONHOME": "removed",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
    }
    try:
        completed = _run_in_process_group(
            argv,
            cwd=cwd,
            environment=environment,
            timeout_seconds=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        receipt.update(
            {
                "exit_code": None,
                "timed_out": True,
                "stdout": _output_text(exc.stdout),
                "stderr": _output_text(exc.stderr),
                "process_family_policy": getattr(
                    exc,
                    "process_family_policy",
                    {
                        "token_sha256": None,
                        "same_uid_only": True,
                        "confirmed_empty": False,
                        "trust_boundary": PROCESS_FAMILY_TRUST_BOUNDARY,
                    },
                ),
            }
        )
        write_json(receipt_path, receipt)
        raise RuntimeError(f"RECIPE_TIMEOUT: {step_id}") from exc
    receipt.update(
        {
            "exit_code": completed.returncode,
            "timed_out": False,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "process_family_policy": completed.process_family_policy,
        }
    )
    write_json(receipt_path, receipt)
    return receipt


def snapshot_files(root: Path, source_files: list[str]) -> dict[str, Any]:
    files: dict[str, str] = {}
    root = root.resolve()
    for relative in source_files:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise RuntimeError(f"SOURCE_FILE_INVALID: {relative}")
        resolved = path.resolve()
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise RuntimeError(f"SOURCE_FILE_INVALID: {relative}") from exc
        files[relative] = file_sha256(path)
    ordered = dict(sorted(files.items()))
    return {"sha256": sha256_bytes(canonical_bytes(ordered)), "files": ordered}


def require_snapshot(
    root: Path, source_files: list[str], expected: dict[str, Any]
) -> None:
    actual = snapshot_files(root, source_files)
    if actual != expected:
        raise RuntimeError(
            "SOURCE_DRIFT_DURING_PROOF: "
            f"expected {expected.get('sha256')}, observed {actual.get('sha256')}"
        )


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be a regular JSON file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _load_codex_exec_host():
    path = Path(__file__).resolve().with_name("codex_exec_host.py")
    spec = importlib.util.spec_from_file_location(
        f"sffs_codex_exec_host_{uuid.uuid4().hex}", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("REVIEW_HOST_VALIDATOR_UNAVAILABLE")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _validated_repo_artifact(
    repo_root: Path, reference: Any, *, label: str
) -> tuple[str, str, Path]:
    if (
        not isinstance(reference, dict)
        or set(reference) != {"path", "sha256"}
        or not isinstance(reference.get("path"), str)
        or not reference["path"]
        or not isinstance(reference.get("sha256"), str)
        or len(reference["sha256"]) != 64
        or any(character not in "0123456789abcdef" for character in reference["sha256"])
    ):
        raise ValueError(f"{label} reference is malformed")
    relative = PurePosixPath(reference["path"])
    if (
        relative.is_absolute()
        or relative.as_posix() != reference["path"]
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        raise ValueError(f"{label} path must be normalized and repository-relative")
    root = repo_root.resolve()
    path = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{label} path cannot contain a symlink")
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"{label} must be an existing regular file")
    try:
        path.resolve().relative_to(root)
    except ValueError as exc:
        raise ValueError(f"{label} must remain inside the repository") from exc
    digest = file_sha256(path)
    if digest != reference["sha256"]:
        raise ValueError(f"{label} sha256 does not match its bytes")
    return relative.as_posix(), digest, path


def _validated_review_artifact(
    repo_root: Path, reference: Any
) -> tuple[str, str]:
    relative, digest, _ = _validated_repo_artifact(
        repo_root, reference, label="review artifact"
    )
    return relative, digest


def derive_review_open_count(
    report: dict[str, Any], *, expected_type: str, source_sha256: str,
    repo_root: Path,
) -> int:
    """Derive the review gate without trusting a reviewer-supplied pass flag."""
    if "passed" in report or "pass" in report or "all_clear" in report:
        raise ValueError("reviewer attestation cannot contain a self-reported pass")
    required = {
        "schema_version",
        "attestation_type",
        "source_sha256",
        "reviewer_id",
        "execution_id",
        "model_environment",
        "review_scope",
        "covered_severities",
        "review_artifact",
        "source_identity",
        "host_execution_receipt",
        "trust_boundary",
        "findings",
    }
    if set(report) != required:
        raise ValueError(
            "reviewer attestation has an unexpected host receipt contract"
        )
    host = _load_codex_exec_host()
    if report.get("schema_version") != host.REVIEW_ATTESTATION_SCHEMA_VERSION:
        raise ValueError("reviewer attestation schema is unsupported")
    if report.get("attestation_type") != expected_type:
        raise ValueError("reviewer attestation type is wrong")
    if report.get("source_sha256") != source_sha256:
        raise ValueError("reviewer attestation source does not match the frozen source")
    if not isinstance(report.get("reviewer_id"), str) or not report["reviewer_id"].strip():
        raise ValueError("reviewer identity is required")
    if not isinstance(report.get("execution_id"), str) or not report["execution_id"].strip():
        raise ValueError("review execution_id is required")
    environment = report.get("model_environment")
    if (
        not isinstance(environment, dict)
        or set(environment)
        != {"runner", "model", "isolation", "reasoning", "execution_id"}
        or any(
            not isinstance(environment.get(field), str)
            or not environment[field].strip()
            for field in (
                "runner",
                "model",
                "isolation",
                "reasoning",
                "execution_id",
            )
        )
    ):
        raise ValueError("review model_environment is required and must be structured")
    if report.get("review_scope") != list(REQUIRED_REVIEW_SCOPE):
        raise ValueError("review scope must equal the fixed complete scope")
    if report.get("covered_severities") != ["P0", "P1"]:
        raise ValueError("review attestation must cover P0 and P1")
    if report.get("trust_boundary") != REVIEW_TRUST_BOUNDARY:
        raise ValueError("review attestation must declare its host observation boundary")
    _validated_review_artifact(repo_root, report.get("review_artifact"))
    _, _, receipt_path = _validated_repo_artifact(
        repo_root,
        report.get("host_execution_receipt"),
        label="review host execution receipt",
    )
    try:
        expected_report = host.derive_review_attestation(
            receipt_path=receipt_path,
            repo_root=repo_root,
            attestation_type=expected_type,
            source_sha256=source_sha256,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"review host execution receipt is invalid: {exc}") from exc
    if report != expected_report:
        raise ValueError(
            "review attestation fields do not match the host execution receipt"
        )
    findings = report.get("findings")
    if not isinstance(findings, list):
        raise ValueError("review findings must be an array")
    wanted_severity = "P0" if expected_type == "p0_zero" else "P1"
    open_count = 0
    finding_ids: set[str] = set()
    for finding in findings:
        if (
            not isinstance(finding, dict)
            or set(finding)
            != {
                "finding_id",
                "severity",
                "summary",
                "reproducer",
                "actual",
                "expected",
                "reproducible",
                "status",
            }
            or not isinstance(finding.get("finding_id"), str)
            or finding.get("severity") not in {"P0", "P1"}
            or finding.get("reproducible") is not True
            or finding.get("status") != "open"
            or any(
                not isinstance(finding.get(field), str)
                or not finding[field].strip()
                for field in ("summary", "reproducer", "actual", "expected")
            )
        ):
            raise ValueError("review finding is malformed")
        if not finding["finding_id"].strip() or finding["finding_id"] in finding_ids:
            raise ValueError("review finding IDs must be non-empty and unique")
        finding_ids.add(finding["finding_id"])
        if finding["severity"] != wanted_severity or finding["status"] != "open":
            continue
        if wanted_severity == "P0" or finding["reproducible"] is True:
            open_count += 1
    return open_count


def validate_review_pair(
    p0_report: dict[str, Any],
    p1_report: dict[str, Any],
    *,
    source_sha256: str,
    repo_root: Path,
) -> tuple[int, int]:
    """Require two full-scope attestations over one identical findings set."""
    p0_open = derive_review_open_count(
        p0_report,
        expected_type="p0_zero",
        source_sha256=source_sha256,
        repo_root=repo_root,
    )
    p1_open = derive_review_open_count(
        p1_report,
        expected_type="reproducible_p1_zero",
        source_sha256=source_sha256,
        repo_root=repo_root,
    )
    if p0_report["reviewer_id"] == p1_report["reviewer_id"]:
        raise ValueError("reviewer_id must differ across the two attestations")
    if p0_report["execution_id"] == p1_report["execution_id"]:
        raise ValueError("execution_id must differ across the two attestations")
    p0_receipt = _validated_repo_artifact(
        repo_root,
        p0_report["host_execution_receipt"],
        label="P0 review host execution receipt",
    )
    p1_receipt = _validated_repo_artifact(
        repo_root,
        p1_report["host_execution_receipt"],
        label="P1 review host execution receipt",
    )
    if p0_receipt[0] == p1_receipt[0] or p0_receipt[1] == p1_receipt[1]:
        raise ValueError("review attestations cannot reuse a host execution receipt")
    p0_artifact = _validated_review_artifact(repo_root, p0_report["review_artifact"])
    p1_artifact = _validated_review_artifact(repo_root, p1_report["review_artifact"])
    if p0_artifact[0] == p1_artifact[0] or p0_artifact[1] == p1_artifact[1]:
        raise ValueError("review attestations cannot reuse a copied raw artifact")
    p0_findings = {
        item["finding_id"]: canonical_bytes(item)
        for item in p0_report["findings"]
    }
    p1_findings = {
        item["finding_id"]: canonical_bytes(item)
        for item in p1_report["findings"]
    }
    if p0_findings != p1_findings:
        raise ValueError("review attestations must cover the same findings set")
    return p0_open, p1_open


def fixed_recipe(
    *, repo_root: Path, eval_root: Path, target_root: Path
) -> list[dict[str, Any]]:
    """Return the non-user-extensible deterministic recipe description."""
    skill = repo_root / "skills" / SKILL_NAME
    scripts = skill / "scripts"
    installed = target_root / SKILL_NAME
    return [
        {
            "step_id": "unit_tests",
            "script": scripts / "package_runtime.py",
            "arguments": ["--unit-gate"],
            "receipt_name": "01-unit-tests.json",
            "timeout_seconds": INSTALL_TIMEOUT_SECONDS,
        },
        {
            "step_id": "self_test",
            "script": scripts / "casefile.py",
            "arguments": ["self-test"],
            "receipt_name": "02-self-test.json",
            "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        },
        {
            "step_id": "eval_replay",
            "script": scripts / "run_evals.py",
            "arguments": ["--root", str(eval_root)],
            "receipt_name": "03-eval-replay-cases.json",
            "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        },
        {
            "step_id": "eval_replay",
            "script": scripts / "run_evals.py",
            "arguments": ["--root", str(eval_root)],
            "receipt_name": "04-eval-replay-artifacts.json",
            "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        },
        {
            "step_id": "clean_install",
            "script": scripts / "package_runtime.py",
            "arguments": [
                "--target-root",
                str(target_root),
                "--eval-root",
                str(eval_root),
            ],
            "receipt_name": "05-clean-install.json",
            "timeout_seconds": INSTALL_TIMEOUT_SECONDS,
        },
        {
            "step_id": "verify_install",
            "script": installed / "scripts" / "package_runtime.py",
            "arguments": ["--verify", str(installed)],
            "receipt_name": "06-verify-install.json",
            "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        },
        {
            "step_id": "rollback_restore",
            "script": Path(__file__).resolve(),
            "arguments": [],
            "receipt_name": "07-rollback-summary.json",
            "timeout_seconds": DEFAULT_TIMEOUT_SECONDS,
        },
    ]


def _parse_stdout_json(receipt: dict[str, Any], step: str) -> dict[str, Any]:
    if receipt.get("exit_code") != 0:
        raise RuntimeError(f"RECIPE_COMMAND_FAILED: {step}")
    try:
        value = json.loads(str(receipt.get("stdout", "")))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"RECIPE_OUTPUT_INVALID: {step}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"RECIPE_OUTPUT_INVALID: {step}")
    return value


def _tree_hash(path: Path) -> str:
    files: dict[str, str] = {}
    if path.exists():
        if path.is_symlink() or not path.is_dir():
            raise RuntimeError(f"TREE_INVALID: {path}")
        for item in sorted(path.rglob("*")):
            if item.is_symlink():
                raise RuntimeError(f"TREE_SYMLINK_INVALID: {item}")
            if item.is_file():
                files[str(item.relative_to(path))] = file_sha256(item)
    return sha256_bytes(canonical_bytes(files))


def _relative_file(repo_root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError as exc:
        raise RuntimeError(f"EVIDENCE_OUTSIDE_REPO: {path}") from exc


def _command_summary(receipt: dict[str, Any]) -> dict[str, Any]:
    return {"argv": list(receipt["argv"]), "exit_code": int(receipt["exit_code"])}


MOVE_CODE = (
    "import os,sys; from pathlib import Path; "
    "a=Path(sys.argv[1]); b=Path(sys.argv[2]); "
    "b.parent.mkdir(parents=True,exist_ok=True); os.replace(a,b); "
    "fd=os.open(str(b.parent),os.O_RDONLY|getattr(os,'O_DIRECTORY',0)); "
    "os.fsync(fd); os.close(fd)"
)
ABSENCE_CODE = (
    "import sys; from pathlib import Path; "
    "p=Path(sys.argv[1]); raise SystemExit(0 if not p.exists() else 1)"
)


def _run_python_code(
    *, step_id: str, code: str, arguments: list[str], cwd: Path,
    receipt_path: Path, timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    argv = [sys.executable, *ISOLATION_FLAGS, "-c", code, *arguments]
    environment = isolated_environment()
    try:
        completed = _run_in_process_group(
            argv,
            cwd=cwd,
            environment=environment,
            timeout_seconds=timeout_seconds,
        )
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "recipe_version": RECIPE_VERSION,
            "step_id": step_id,
            "argv": argv,
            "cwd": str(cwd),
            "timeout_seconds": timeout_seconds,
            "shell": False,
            "environment_policy": {
                "PYTHONPATH": "removed", "PYTHONHOME": "removed",
                "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
            },
            "exit_code": completed.returncode,
            "timed_out": False,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
            "process_family_policy": completed.process_family_policy,
        }
    except subprocess.TimeoutExpired as exc:
        receipt = {
            "schema_version": SCHEMA_VERSION, "recipe_version": RECIPE_VERSION,
            "step_id": step_id, "argv": argv, "cwd": str(cwd),
            "timeout_seconds": timeout_seconds, "shell": False,
            "environment_policy": {
                "PYTHONPATH": "removed", "PYTHONHOME": "removed",
                "PYTHONNOUSERSITE": "1", "PYTHONDONTWRITEBYTECODE": "1",
            },
            "exit_code": None, "timed_out": True,
            "stdout": _output_text(exc.stdout), "stderr": _output_text(exc.stderr),
            "process_family_policy": getattr(
                exc,
                "process_family_policy",
                {
                    "token_sha256": None,
                    "same_uid_only": True,
                    "confirmed_empty": False,
                    "trust_boundary": PROCESS_FAMILY_TRUST_BOUNDARY,
                },
            ),
        }
    write_json(receipt_path, receipt)
    if receipt["exit_code"] != 0:
        raise RuntimeError(f"RECIPE_COMMAND_FAILED: {step_id}")
    return receipt


def _evidence_document(
    *, iteration_id: str, source_sha256: str, check: str, proof: dict[str, Any],
    commands: list[dict[str, Any]], command_receipt_paths: list[Path],
    artifact_path: Path, repo_root: Path,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "iteration_id": iteration_id,
        "source_sha256": source_sha256,
        "gate_check": check,
        "passed": True,
        "proof": proof,
        "commands": commands,
        "command_receipts": [
            {
                "path": _relative_file(repo_root, path),
                "sha256": file_sha256(path),
            }
            for path in command_receipt_paths
        ],
        "artifacts": [{
            "role": ARTIFACT_ROLES[check],
            "path": _relative_file(repo_root, artifact_path),
            "sha256": file_sha256(artifact_path),
        }],
    }


def produce(
    *, repo_root: Path, state_file: Path, eval_root: Path,
    p0_review: Path, p1_review: Path, output_dir: Path,
) -> Path:
    repo_root = repo_root.resolve()
    state = _read_json(state_file, "loop state")
    if state.get("repo_root") != str(repo_root) or state.get("status") != "active":
        raise RuntimeError("STATE_INVALID_FOR_PROOF")
    iteration = state.get("iterations", [{}])[-1]
    iteration_id = iteration.get("iteration_id")
    source_sha = iteration.get("active_source_sha256")
    source_files = state.get("source_files")
    frozen = state.get("source_snapshot")
    if (
        not isinstance(iteration_id, str)
        or not isinstance(source_sha, str)
        or not isinstance(source_files, list)
        or not isinstance(frozen, dict)
        or frozen.get("sha256") != source_sha
    ):
        raise RuntimeError("STATE_INVALID_FOR_PROOF")
    if output_dir.exists():
        raise RuntimeError("PROOF_OUTPUT_EXISTS")
    output_dir.mkdir(parents=True)
    raw_dir = output_dir / "raw"
    evidence_dir = output_dir / "evidence"
    raw_dir.mkdir()
    evidence_dir.mkdir()
    fsync_directory(output_dir)
    require_snapshot(repo_root, source_files, frozen)

    review_paths = (p0_review.resolve(), p1_review.resolve())
    for path in review_paths:
        _relative_file(repo_root, path)
    original_p0_report = _read_json(review_paths[0], "P0 reviewer attestation")
    original_p1_report = _read_json(review_paths[1], "P1 reviewer attestation")
    original_p0_open, original_p1_open = validate_review_pair(
        original_p0_report,
        original_p1_report,
        source_sha256=source_sha,
        repo_root=repo_root,
    )
    if original_p0_open or original_p1_open:
        raise RuntimeError(
            "REVIEW_GATE_OPEN: "
            f"p0={original_p0_open}, reproducible_p1={original_p1_open}"
        )
    release_basis = materialize_release_basis(
        repo_root=repo_root,
        source_files=source_files,
        expected_source=frozen,
        eval_root=eval_root.resolve(),
        review_paths=review_paths,
        destination_parent=output_dir / "release-bases",
    )
    execution_repo_root = Path(release_basis["source_root"])
    execution_eval_root = Path(release_basis["eval_root"])
    review_root = Path(release_basis["review_root"])
    retained_review_paths = tuple(
        Path(release_basis["root"]) / value
        for value in release_basis["review_paths"]
    )
    p0_report = _read_json(retained_review_paths[0], "P0 reviewer attestation")
    p1_report = _read_json(retained_review_paths[1], "P1 reviewer attestation")
    p0_open, p1_open = validate_review_pair(
        p0_report,
        p1_report,
        source_sha256=source_sha,
        repo_root=review_root,
    )
    if p0_open or p1_open:
        raise RuntimeError(
            f"REVIEW_GATE_OPEN: p0={p0_open}, reproducible_p1={p1_open}"
        )

    target_root = output_dir / "clean-target"
    baseline_state_sha = _tree_hash(target_root)
    recipe = fixed_recipe(
        repo_root=execution_repo_root,
        eval_root=execution_eval_root,
        target_root=target_root,
    )
    receipts: dict[str, dict[str, Any]] = {}

    def run_item(index: int) -> dict[str, Any]:
        item = recipe[index]
        validate_release_basis(release_basis)
        receipt = run_isolated_command(
            step_id=item["step_id"], script=item["script"],
            arguments=item["arguments"], cwd=execution_repo_root,
            timeout_seconds=item["timeout_seconds"],
            receipt_path=raw_dir / item["receipt_name"],
        )
        validate_release_basis(release_basis)
        if receipt["exit_code"] != 0:
            raise RuntimeError(f"RECIPE_COMMAND_FAILED: {item['step_id']}")
        return receipt

    unit_receipt = run_item(0)
    unit = _parse_stdout_json(unit_receipt, "unit_tests")
    receipts["unit_tests"] = unit_receipt
    self_receipt = run_item(1)
    self_result = _parse_stdout_json(self_receipt, "self_test")
    receipts["self_test"] = self_receipt
    eval_case_receipt = run_item(2)
    eval_case = _parse_stdout_json(eval_case_receipt, "eval_replay_cases")
    receipts["frozen_eval_18_of_18"] = eval_case_receipt
    eval_artifact_receipt = run_item(3)
    eval_artifact = _parse_stdout_json(eval_artifact_receipt, "eval_replay_artifacts")
    receipts["artifacts_16_of_16"] = eval_artifact_receipt
    if eval_case != eval_artifact:
        raise RuntimeError("EVAL_DOUBLE_REPLAY_MISMATCH")

    install_receipt = run_item(4)
    install = _parse_stdout_json(install_receipt, "clean_install")
    receipts["clean_install"] = install_receipt
    installed = target_root / SKILL_NAME
    if Path(str(install.get("installed", ""))).resolve() != installed.resolve():
        raise RuntimeError("INSTALL_DESTINATION_MISMATCH")
    manifest = installed / "runtime-manifest.json"
    if not manifest.is_file() or manifest.is_symlink():
        raise RuntimeError("INSTALL_MANIFEST_MISSING")
    manifest_sha = file_sha256(manifest)
    installed_file_count = sum(1 for path in installed.rglob("*") if path.is_file())

    verify_receipt = run_item(5)
    verify = _parse_stdout_json(verify_receipt, "verify_install")
    receipts["verify_install"] = verify_receipt
    if verify.get("valid") is not True or verify.get("error_count") != 0:
        raise RuntimeError("VERIFY_INSTALL_FAILED")

    holding = output_dir / "rollback-holding" / SKILL_NAME
    validate_release_basis(release_basis)
    move_out = _run_python_code(
        step_id="rollback_move_out", code=MOVE_CODE,
        arguments=[str(installed), str(holding)], cwd=execution_repo_root,
        receipt_path=raw_dir / "07a-rollback-move-out.json",
    )
    validate_release_basis(release_basis)
    absence = _run_python_code(
        step_id="rollback_absence_fresh_process", code=ABSENCE_CODE,
        arguments=[str(installed)], cwd=execution_repo_root,
        receipt_path=raw_dir / "07b-rollback-absence.json",
    )
    rolled_back_state_sha = _tree_hash(target_root)
    restore = _run_python_code(
        step_id="rollback_restore", code=MOVE_CODE,
        arguments=[str(holding), str(installed)], cwd=execution_repo_root,
        receipt_path=raw_dir / "07c-rollback-restore.json",
    )
    validate_release_basis(release_basis)
    post_verify = run_isolated_command(
        step_id="rollback_post_restore_verify",
        script=installed / "scripts" / "package_runtime.py",
        arguments=["--verify", str(installed)], cwd=execution_repo_root,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        receipt_path=raw_dir / "07d-rollback-post-verify.json",
    )
    validate_release_basis(release_basis)
    post_verify_result = _parse_stdout_json(post_verify, "rollback_post_restore_verify")
    restored_manifest_sha = file_sha256(installed / "runtime-manifest.json")
    rollback_commands = [move_out, absence, restore, post_verify]
    rollback_summary = {
        "schema_version": SCHEMA_VERSION,
        "recipe_version": RECIPE_VERSION,
        "step_id": "rollback_restore",
        "commands": rollback_commands,
        "baseline_state_sha256": baseline_state_sha,
        "rolled_back_state_sha256": rolled_back_state_sha,
        "install_absent_during_rollback": absence["exit_code"] == 0,
        "original_path_absent_in_fresh_python_process": absence["exit_code"] == 0,
        "restore_verified": (
            post_verify_result.get("valid") is True
            and post_verify_result.get("error_count") == 0
        ),
        "installed_manifest_sha256": manifest_sha,
        "restored_manifest_sha256": restored_manifest_sha,
    }
    rollback_summary_path = raw_dir / "07-rollback-summary.json"
    write_json(rollback_summary_path, rollback_summary)
    receipts["rollback"] = rollback_summary
    if not (
        baseline_state_sha == rolled_back_state_sha
        and rollback_summary["restore_verified"] is True
        and manifest_sha == restored_manifest_sha
    ):
        raise RuntimeError("ROLLBACK_RESTORE_FAILED")
    canonical_install = materialize_canonical_install_artifact(
        installed=installed,
        destination_parent=output_dir / "canonical-installs",
        source_basis_sha256=release_basis["sha256"],
    )
    canonical_manifest = Path(canonical_install["root"]) / "runtime-manifest.json"
    if file_sha256(canonical_manifest) != manifest_sha:
        raise RuntimeError("CANONICAL_INSTALL_MANIFEST_MISMATCH")

    self_checks = self_result.get("checks")
    if self_result.get("valid") is not True or not isinstance(self_checks, dict):
        raise RuntimeError("SELF_TEST_FAILED")
    expected_eval = {
        "valid": True,
        "expected_case_count": 18,
        "completed_case_count": 18,
        "expected_artifact_count": 16,
        "artifact_count": 16,
        "passed": 16,
        "failed": 0,
        "suite_errors": [],
        "missing_cases": [],
    }
    for key, expected in expected_eval.items():
        if eval_case.get(key) != expected:
            raise RuntimeError(f"EVAL_GATE_FAILED: {key}")

    unit_proof = {
        "tests_run": unit.get("tests_run"),
        "failures": 0,
        "errors": 0,
        "skipped": 0,
        "expected_failures": 0,
        "test_source_set_sha256": unit.get("test_source_set_sha256"),
    }
    proof_by_check = {
        "p0_zero": {
            "open_count": p0_open,
            "reviewer_id": p0_report["reviewer_id"],
            "execution_id": p0_report["execution_id"],
            "model_environment": p0_report["model_environment"],
            "review_scope": p0_report["review_scope"],
            "host_execution_receipt_sha256": p0_report[
                "host_execution_receipt"
            ]["sha256"],
            "trust_boundary": p0_report["trust_boundary"],
        },
        "reproducible_p1_zero": {
            "open_count": p1_open,
            "reviewer_id": p1_report["reviewer_id"],
            "execution_id": p1_report["execution_id"],
            "model_environment": p1_report["model_environment"],
            "review_scope": p1_report["review_scope"],
            "host_execution_receipt_sha256": p1_report[
                "host_execution_receipt"
            ]["sha256"],
            "trust_boundary": p1_report["trust_boundary"],
        },
        "unit_tests": unit_proof,
        "self_test": {"checks_run": len(self_checks), "failures": 0},
        "frozen_eval_18_of_18": {
            "expected_cases": 18, "completed_cases": 18,
            "missing_cases": 0, "suite_errors": 0,
        },
        "artifacts_16_of_16": {
            "expected_artifacts": 16, "completed_artifacts": 16,
            "passed": 16, "failed": 0,
        },
        "clean_install": {
            "destination_was_absent": True,
            "installed_file_count": installed_file_count,
            "manifest_sha256": manifest_sha,
            "install_exit_code": install_receipt["exit_code"],
        },
        "verify_install": {
            "valid": True, "error_count": 0,
            "manifest_sha256": manifest_sha,
            "verify_exit_code": verify_receipt["exit_code"],
        },
        "rollback": {
            "operation": "file_level_rollback_and_restore",
            "installed_path": str(installed),
            "baseline_state_sha256": baseline_state_sha,
            "rolled_back_state_sha256": rolled_back_state_sha,
            "install_absent_during_rollback": True,
            "original_path_absent_in_fresh_python_process": True,
            "restore_verified": True,
            "installed_manifest_sha256": manifest_sha,
            "restored_manifest_sha256": restored_manifest_sha,
        },
    }
    artifact_by_check = {
        "p0_zero": retained_review_paths[0],
        "reproducible_p1_zero": retained_review_paths[1],
        "unit_tests": raw_dir / recipe[0]["receipt_name"],
        "self_test": raw_dir / recipe[1]["receipt_name"],
        "frozen_eval_18_of_18": raw_dir / recipe[2]["receipt_name"],
        "artifacts_16_of_16": raw_dir / recipe[3]["receipt_name"],
        "clean_install": canonical_manifest,
        "verify_install": raw_dir / recipe[5]["receipt_name"],
        "rollback": rollback_summary_path,
    }
    commands_by_check = {
        "p0_zero": [], "reproducible_p1_zero": [],
        "unit_tests": [_command_summary(unit_receipt)],
        "self_test": [_command_summary(self_receipt)],
        "frozen_eval_18_of_18": [_command_summary(eval_case_receipt)],
        "artifacts_16_of_16": [_command_summary(eval_artifact_receipt)],
        "clean_install": [_command_summary(install_receipt)],
        "verify_install": [_command_summary(verify_receipt)],
        "rollback": [_command_summary(item) for item in rollback_commands],
    }
    command_receipts_by_check = {
        "p0_zero": [],
        "reproducible_p1_zero": [],
        "unit_tests": [raw_dir / recipe[0]["receipt_name"]],
        "self_test": [raw_dir / recipe[1]["receipt_name"]],
        "frozen_eval_18_of_18": [raw_dir / recipe[2]["receipt_name"]],
        "artifacts_16_of_16": [raw_dir / recipe[3]["receipt_name"]],
        "clean_install": [raw_dir / recipe[4]["receipt_name"]],
        "verify_install": [raw_dir / recipe[5]["receipt_name"]],
        "rollback": [
            raw_dir / "07a-rollback-move-out.json",
            raw_dir / "07b-rollback-absence.json",
            raw_dir / "07c-rollback-restore.json",
            raw_dir / "07d-rollback-post-verify.json",
        ],
    }
    gate_evidence: dict[str, dict[str, Any]] = {}
    for check in REQUIRED_GATE_CHECKS:
        document = _evidence_document(
            iteration_id=iteration_id, source_sha256=source_sha, check=check,
            proof=proof_by_check[check], commands=commands_by_check[check],
            command_receipt_paths=command_receipts_by_check[check],
            artifact_path=artifact_by_check[check], repo_root=repo_root,
        )
        evidence_path = evidence_dir / f"{check}.json"
        write_json(evidence_path, document)
        gate_evidence[check] = {
            "path": _relative_file(repo_root, evidence_path),
            "sha256": file_sha256(evidence_path),
            "json_pointer": "/passed",
            "expected": True,
        }

    receipt_index = {
        "schema_version": SCHEMA_VERSION,
        "recipe_version": RECIPE_VERSION,
        "iteration_id": iteration_id,
        "source_sha256": source_sha,
        "receipts": {
            path.name: file_sha256(path) for path in sorted(raw_dir.glob("*.json"))
        },
    }
    receipt_index_path = output_dir / "raw-receipt-index.json"
    write_json(receipt_index_path, receipt_index)
    validate_release_basis(release_basis)
    validate_canonical_install_artifact(canonical_install)
    producer_path = execution_repo_root / "skills" / SKILL_NAME / "scripts" / "produce_release_gate.py"
    gate_release_basis = {
        "schema_version": SCHEMA_VERSION,
        "sha256": release_basis["sha256"],
        "root_path": _relative_file(repo_root, Path(release_basis["root"])),
        "index_path": _relative_file(repo_root, Path(release_basis["index_path"])),
        "index_sha256": release_basis["index_sha256"],
        "source_sha256": release_basis["source_sha256"],
        "canonical_install": {
            "sha256": canonical_install["sha256"],
            "root_path": _relative_file(repo_root, Path(canonical_install["root"])),
            "index_path": _relative_file(repo_root, Path(canonical_install["index_path"])),
            "index_sha256": canonical_install["index_sha256"],
            "built_from": "retained_source_snapshot",
            "source_basis_sha256": release_basis["sha256"],
        },
        "trust_boundary": "retained_local_snapshot_not_external_signature",
    }
    gate = {
        "schema_version": SCHEMA_VERSION,
        "iteration_id": iteration_id,
        "source_sha256": source_sha,
        "checks": {check: True for check in REQUIRED_GATE_CHECKS},
        "evidence": gate_evidence,
        "release_basis": gate_release_basis,
        "producer": {
            "authority": "controller_prove_stop",
            "recipe_version": RECIPE_VERSION,
            "script_path": _relative_file(repo_root, producer_path),
            "script_sha256": file_sha256(producer_path),
            "raw_receipt_index_path": _relative_file(repo_root, receipt_index_path),
            "raw_receipt_index_sha256": file_sha256(receipt_index_path),
        },
    }
    gate_path = output_dir / "gate.json"
    write_json(gate_path, gate)
    validate_release_basis(release_basis)
    validate_canonical_install_artifact(canonical_install)
    return gate_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True)
    parser.add_argument("--state-file", required=True)
    parser.add_argument("--eval-root", required=True)
    parser.add_argument("--p0-review", required=True)
    parser.add_argument("--p1-review", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args(argv)
    try:
        gate = produce(
            repo_root=Path(args.repo_root), state_file=Path(args.state_file),
            eval_root=Path(args.eval_root), p0_review=Path(args.p0_review),
            p1_review=Path(args.p1_review), output_dir=Path(args.output_dir),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps({"valid": True, "gate": str(gate.resolve())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
