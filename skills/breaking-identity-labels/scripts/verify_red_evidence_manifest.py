#!/usr/bin/env python3
"""Verify the add-only red-evidence ledger and its sealed historical prefix."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath


TRUSTED_PREFIX_COUNT = 7
TRUSTED_PREFIX_SHA256 = "4abae9cd677f062c58b946c98714dcc5e2d0ca6cddd90ee2aa11edad75952660"


class RedLedgerError(RuntimeError):
    pass


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_file(root: Path, value: object) -> Path:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise RedLedgerError("red_evidence_artifact_unsafe_path")
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts or value != relative.as_posix():
        raise RedLedgerError("red_evidence_artifact_unsafe_path")
    target = root
    for part in relative.parts:
        target = target / part
        if target.is_symlink():
            raise RedLedgerError("red_evidence_artifact_unsafe_path")
    if not target.is_file():
        raise RedLedgerError("red_evidence_artifact_missing")
    return target


def load_manifest(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RedLedgerError("red_evidence_manifest_invalid") from error
    if not isinstance(value, dict):
        raise RedLedgerError("red_evidence_manifest_invalid")
    return value


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def verified_test_hashes(root: Path, required_paths: set[str]) -> dict[str, set[str]]:
    """Return current and historical test hashes backed by continuous receipts.

    Red evidence intentionally binds the test bytes that failed before a repair.
    A later test migration must not force the sealed red ledger to be rewritten,
    but the historical hash is accepted only when the current test manifest and
    every receipt form a continuous, file-backed chain to the current bytes.
    """

    manifest_path = root / "evals" / "test-generation-manifest.json"
    manifest = load_manifest(manifest_path)
    files = manifest.get("files")
    if manifest.get("schema_version") != "1.0" or not isinstance(files, list):
        raise RedLedgerError("red_evidence_test_manifest_invalid")

    records: dict[str, dict] = {}
    declared_hashes: dict[str, set[str]] = {}
    for record in files:
        if not isinstance(record, dict):
            raise RedLedgerError("red_evidence_test_manifest_invalid")
        relative = record.get("path")
        head = record.get("sha256")
        history = record.get("migration_history", [])
        if (
            not isinstance(relative, str)
            or relative in records
            or not is_sha256(head)
            or not isinstance(history, list)
        ):
            raise RedLedgerError("red_evidence_test_manifest_invalid")
        records[relative] = record
        hashes = {head}
        previous_to: str | None = None
        for entry in history:
            if not isinstance(entry, dict) or set(entry) != {
                "from_sha256",
                "to_sha256",
                "receipt_path",
                "receipt_sha256",
            }:
                raise RedLedgerError("red_evidence_test_migration_invalid")
            from_sha = entry.get("from_sha256")
            to_sha = entry.get("to_sha256")
            if not is_sha256(from_sha) or not is_sha256(to_sha):
                raise RedLedgerError("red_evidence_test_migration_invalid")
            if previous_to is not None and from_sha != previous_to:
                raise RedLedgerError("red_evidence_test_migration_chain_invalid")
            previous_to = to_sha
            hashes.update((from_sha, to_sha))
        if history and previous_to != head:
            raise RedLedgerError("red_evidence_test_migration_head_mismatch")
        declared_hashes[relative] = hashes

    verified: dict[str, set[str]] = {}
    receipt_keys = {
        "schema_version",
        "receipt_id",
        "test_path",
        "from_sha256",
        "to_sha256",
        "reason",
        "replacement_tests",
        "evidence",
        "reviewed_by",
        "reviewed_at",
    }
    for relative in sorted(required_paths):
        record = records.get(relative)
        if record is None:
            raise RedLedgerError("red_evidence_test_manifest_path_missing")
        target = safe_file(root, relative)
        if sha256(target) != record["sha256"]:
            raise RedLedgerError("red_evidence_test_manifest_head_mismatch")

        history = record.get("migration_history", [])
        allowed = {record["sha256"]}
        for entry in history:
            receipt_relative = entry["receipt_path"]
            if (
                not isinstance(receipt_relative, str)
                or not receipt_relative.startswith("evals/test-migrations/")
                or not receipt_relative.endswith(".json")
                or not is_sha256(entry["receipt_sha256"])
            ):
                raise RedLedgerError("red_evidence_test_migration_receipt_invalid")
            receipt_path = safe_file(root, receipt_relative)
            if sha256(receipt_path) != entry["receipt_sha256"]:
                raise RedLedgerError("red_evidence_test_migration_receipt_hash_mismatch")
            receipt = load_manifest(receipt_path)
            if set(receipt) != receipt_keys or receipt.get("schema_version") != "1.0":
                raise RedLedgerError("red_evidence_test_migration_receipt_invalid")
            if (
                receipt.get("test_path") != relative
                or receipt.get("from_sha256") != entry["from_sha256"]
                or receipt.get("to_sha256") != entry["to_sha256"]
            ):
                raise RedLedgerError("red_evidence_test_migration_receipt_semantic_mismatch")

            evidence = receipt.get("evidence")
            replacements = receipt.get("replacement_tests")
            if not isinstance(evidence, list) or not evidence or not isinstance(replacements, list) or not replacements:
                raise RedLedgerError("red_evidence_test_migration_receipt_invalid")
            for binding in evidence:
                if not isinstance(binding, dict) or set(binding) != {"path", "sha256"} or not is_sha256(binding.get("sha256")):
                    raise RedLedgerError("red_evidence_test_migration_receipt_invalid")
                evidence_path = safe_file(root, binding.get("path"))
                if sha256(evidence_path) != binding["sha256"]:
                    raise RedLedgerError("red_evidence_artifact_hash_mismatch")
            for binding in replacements:
                if not isinstance(binding, dict) or set(binding) != {"path", "sha256"} or not is_sha256(binding.get("sha256")):
                    raise RedLedgerError("red_evidence_test_migration_receipt_invalid")
                replacement_path = safe_file(root, binding.get("path"))
                replacement_hash = sha256(replacement_path)
                if replacement_hash != binding["sha256"] and binding["sha256"] not in declared_hashes.get(binding["path"], set()):
                    raise RedLedgerError("red_evidence_test_migration_receipt_replacement_hash_mismatch")
            allowed.update((entry["from_sha256"], entry["to_sha256"]))
        verified[relative] = allowed
    return verified


def verify(root: Path, manifest_path: Path) -> dict:
    root = root.expanduser().resolve()
    manifest_path = manifest_path.expanduser().resolve()
    try:
        manifest_path.relative_to(root)
    except ValueError as error:
        raise RedLedgerError("red_evidence_manifest_unsafe_path") from error
    manifest = load_manifest(manifest_path)
    if set(manifest) != {"schema_version", "append_only", "records", "sealed_prefix"}:
        raise RedLedgerError("red_evidence_manifest_invalid")
    if manifest.get("schema_version") != "1.0" or manifest.get("append_only") is not True:
        raise RedLedgerError("red_evidence_manifest_invalid")
    records = manifest.get("records")
    sealed = manifest.get("sealed_prefix")
    if not isinstance(records, list) or len(records) < TRUSTED_PREFIX_COUNT:
        raise RedLedgerError("red_evidence_sealed_prefix_invalid")
    if (
        not isinstance(sealed, dict)
        or set(sealed) != {"record_count", "sha256"}
        or sealed.get("record_count") != TRUSTED_PREFIX_COUNT
        or sealed.get("sha256") != TRUSTED_PREFIX_SHA256
        or hashlib.sha256(canonical_json(records[:TRUSTED_PREFIX_COUNT])).hexdigest()
        != TRUSTED_PREFIX_SHA256
    ):
        raise RedLedgerError("red_evidence_sealed_prefix_invalid")

    required_test_paths: set[str] = set()
    for record in records:
        if isinstance(record, dict) and isinstance(record.get("tests"), list):
            for binding in record["tests"]:
                if isinstance(binding, dict) and isinstance(binding.get("path"), str):
                    required_test_paths.add(binding["path"])
    allowed_test_hashes = verified_test_hashes(root, required_test_paths)

    seen: set[str] = set()
    artifact_count = 0
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            "evidence_id",
            "round_id",
            "evidence",
            "tests",
            "pre_fix_capture",
        }:
            raise RedLedgerError("red_evidence_record_invalid")
        evidence_id = record.get("evidence_id")
        if not isinstance(evidence_id, str) or not evidence_id or evidence_id in seen:
            raise RedLedgerError("red_evidence_record_invalid")
        seen.add(evidence_id)
        if not isinstance(record.get("round_id"), str) or re.fullmatch(r"R[1-9][0-9]*", record["round_id"]) is None:
            raise RedLedgerError("red_evidence_record_invalid")
        evidence = record.get("evidence")
        tests = record.get("tests")
        if not isinstance(evidence, dict) or not isinstance(tests, list) or not tests:
            raise RedLedgerError("red_evidence_record_invalid")
        bindings = [("evidence", evidence), *(("test", binding) for binding in tests)]
        for binding_kind, binding in bindings:
            if (
                not isinstance(binding, dict)
                or set(binding) != {"path", "sha256"}
                or not isinstance(binding.get("sha256"), str)
                or re.fullmatch(r"[0-9a-f]{64}", binding["sha256"]) is None
            ):
                raise RedLedgerError("red_evidence_record_invalid")
            target = safe_file(root, binding.get("path"))
            current_sha = sha256(target)
            if binding_kind == "evidence" and current_sha != binding["sha256"]:
                raise RedLedgerError("red_evidence_artifact_hash_mismatch")
            if (
                binding_kind == "test"
                and binding["sha256"] not in allowed_test_hashes.get(binding["path"], set())
            ):
                raise RedLedgerError("red_evidence_artifact_hash_mismatch")
            artifact_count += 1

        capture = record.get("pre_fix_capture")
        if not isinstance(capture, dict) or set(capture) != {"environment", "output"}:
            raise RedLedgerError("red_evidence_capture_invalid")
        evidence_text = safe_file(root, evidence["path"]).read_text(encoding="utf-8")
        for section, statuses in (("environment", {"recorded", "partial"}), ("output", {"recorded"})):
            value = capture.get(section)
            if (
                not isinstance(value, dict)
                or set(value) != {"status", "markers"}
                or value.get("status") not in statuses
                or not isinstance(value.get("markers"), list)
                or not value["markers"]
                or not all(isinstance(marker, str) and marker for marker in value["markers"])
            ):
                raise RedLedgerError("red_evidence_capture_invalid")
            if any(marker not in evidence_text for marker in value["markers"]):
                raise RedLedgerError("red_evidence_capture_marker_missing")

    return {
        "schema_version": "1.0",
        "valid": True,
        "record_count": len(records),
        "sealed_record_count": TRUSTED_PREFIX_COUNT,
        "artifact_count": artifact_count,
        "distribution_status": "local_unpublished",
        "publication_actions_performed": False,
        "errors": [],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = verify(args.root, args.manifest)
    except RedLedgerError as error:
        result = {
            "schema_version": "1.0",
            "valid": False,
            "errors": [str(error)],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
