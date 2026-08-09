#!/usr/bin/env python3
"""Verify an immutable red-stage command receipt without rewriting its history."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path, PurePosixPath


class RedEvidenceError(RuntimeError):
    """A stable verification failure."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_json(path: Path, code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RedEvidenceError(code) from error
    if not isinstance(value, dict):
        raise RedEvidenceError(code)
    return value


def within(root: Path, supplied: Path, code: str) -> Path:
    target = supplied.expanduser()
    if not target.is_absolute():
        target = root / target
    target = target.resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise RedEvidenceError(code) from error
    return target


def registered_test_hash(manifest: dict, relative: str) -> str | None:
    files = manifest.get("files")
    if not isinstance(files, list):
        return None
    matches = [
        item.get("sha256")
        for item in files
        if isinstance(item, dict) and item.get("path") == relative
    ]
    return matches[0] if len(matches) == 1 and isinstance(matches[0], str) else None


def parse_failure_count(stdout: str, stderr: str) -> int:
    combined = stdout + "\n" + stderr
    if re.search(
        r"^Ran [1-9][0-9]* tests?(?:\s+in\s+[^\n]+)?$",
        combined,
        re.MULTILINE,
    ) is None:
        raise RedEvidenceError("red_evidence_not_test_output")
    summary = re.search(r"^FAILED \(([^\n)]*)\)$", combined, re.MULTILINE)
    if summary is None:
        raise RedEvidenceError("red_evidence_not_assertion_failure")
    details = summary.group(1)
    failures = re.search(r"(?:^|,\s*)failures=([0-9]+)(?:,|$)", details)
    errors = re.search(r"(?:^|,\s*)errors=([0-9]+)(?:,|$)", details)
    if failures is None or int(failures.group(1)) < 1:
        raise RedEvidenceError("red_evidence_not_assertion_failure")
    if errors is not None and int(errors.group(1)) > 0:
        raise RedEvidenceError("red_evidence_contains_test_error")
    return int(failures.group(1))


def historical_test_binding(
    argv: object,
    test_relative: str,
    current_test_path: Path,
    workflow: dict,
    step_id: str,
) -> tuple[str, str]:
    """Bind an immutable historical path by identity, not the checkout root."""

    if not isinstance(argv, list) or len(argv) < 2:
        raise RedEvidenceError("red_evidence_receipt_binding_invalid")
    recorded = argv[1]
    if not isinstance(recorded, str) or not recorded or "\x00" in recorded:
        raise RedEvidenceError("red_evidence_receipt_binding_invalid")
    historical = PurePosixPath(recorded)
    expected = PurePosixPath(test_relative)
    if (
        not historical.is_absolute()
        or ".." in historical.parts
        or len(historical.parts) < len(expected.parts)
        or historical.parts[-len(expected.parts) :] != expected.parts
    ):
        raise RedEvidenceError("red_evidence_receipt_binding_invalid")

    steps = workflow.get("steps")
    if isinstance(steps, list):
        matches = [
            step
            for step in steps
            if isinstance(step, dict) and step.get("id") == step_id
        ]
        if len(matches) == 1:
            step = matches[0]
            template = step.get("argv")
            if (
                step.get("kind") != "command"
                or step.get("expected") != "red"
                or not isinstance(template, list)
                or len(template) != len(argv)
                or template[0] != "{python}"
                or not isinstance(template[1], str)
                or not template[1].endswith("/" + test_relative)
                or argv[2:] != template[2:]
            ):
                raise RedEvidenceError("red_evidence_workflow_step_invalid")
        elif matches:
            raise RedEvidenceError("red_evidence_workflow_step_invalid")
    current = Path(recorded).expanduser().resolve()
    mode = "current_root" if current == current_test_path.resolve() else "relocated_root"
    return recorded, mode


def verify(args: argparse.Namespace) -> dict:
    root = args.root.expanduser().resolve()
    run_dir = within(root, args.run_dir, "red_evidence_run_path_unsafe")
    test_path = within(root, args.test_path, "red_evidence_test_path_unsafe")
    manifest_path = within(
        root,
        args.test_manifest,
        "red_evidence_manifest_path_unsafe",
    )
    if not test_path.is_file() or test_path.is_symlink():
        raise RedEvidenceError("red_evidence_test_missing")
    test_relative = test_path.relative_to(root).as_posix()
    manifest = load_json(manifest_path, "red_evidence_manifest_invalid")
    if registered_test_hash(manifest, test_relative) != sha256_file(test_path):
        raise RedEvidenceError("red_evidence_test_manifest_mismatch")

    state = load_json(run_dir / "run-state.json", "red_evidence_state_invalid")
    projection = state.get("steps", {}).get(args.step_id)
    if (
        state.get("status") != "failed"
        or not isinstance(projection, dict)
        or projection.get("status") != "failed"
        or projection.get("kind") != "command"
    ):
        raise RedEvidenceError("red_evidence_state_projection_invalid")
    receipt_relative = projection.get("receipt_path")
    receipt_sha256 = projection.get("receipt_sha256")
    if not isinstance(receipt_relative, str) or not isinstance(receipt_sha256, str):
        raise RedEvidenceError("red_evidence_receipt_projection_invalid")
    receipt_path = within(
        root,
        Path(receipt_relative),
        "red_evidence_receipt_path_unsafe",
    )
    if not receipt_path.is_file() or sha256_file(receipt_path) != receipt_sha256:
        raise RedEvidenceError("red_evidence_receipt_hash_mismatch")
    receipt = load_json(receipt_path, "red_evidence_receipt_invalid")

    workflow_relative = state.get("workflow_path")
    if not isinstance(workflow_relative, str):
        raise RedEvidenceError("red_evidence_workflow_binding_invalid")
    workflow_path = within(
        root,
        Path(workflow_relative),
        "red_evidence_workflow_path_unsafe",
    )
    workflow = load_json(workflow_path, "red_evidence_workflow_binding_invalid")
    if (
        not workflow_path.is_file()
        or sha256_file(workflow_path) != state.get("workflow_sha256")
        or receipt.get("workflow_sha256") != state.get("workflow_sha256")
    ):
        raise RedEvidenceError("red_evidence_workflow_binding_invalid")
    argv = receipt.get("argv")
    historical_path, binding_mode = historical_test_binding(
        receipt.get("argv"),
        test_relative,
        test_path,
        workflow,
        args.step_id,
    )
    if (
        receipt.get("schema_version") != "1.0"
        or receipt.get("run_id") != state.get("run_id")
        or receipt.get("candidate_id") != state.get("candidate_id")
        or receipt.get("step_id") != args.step_id
        or receipt.get("kind") != "command"
        or receipt.get("assertion") != "red"
        or not isinstance(receipt.get("exit_code"), int)
        or receipt["exit_code"] == 0
        or not isinstance(argv, list)
        or len(argv) < 2
    ):
        raise RedEvidenceError("red_evidence_receipt_binding_invalid")

    raw: dict[str, str] = {}
    raw_hashes: dict[str, str] = {}
    for stream in ("stdout", "stderr"):
        relative = receipt.get(f"{stream}_path")
        expected_hash = receipt.get(f"{stream}_sha256")
        if not isinstance(relative, str) or not isinstance(expected_hash, str):
            raise RedEvidenceError("red_evidence_raw_projection_invalid")
        raw_path = within(root, Path(relative), "red_evidence_raw_path_unsafe")
        if not raw_path.is_file() or sha256_file(raw_path) != expected_hash:
            raise RedEvidenceError("red_evidence_raw_hash_mismatch")
        raw[stream] = raw_path.read_text(encoding="utf-8")
        raw_hashes[stream] = expected_hash
    failure_count = parse_failure_count(raw["stdout"], raw["stderr"])
    return {
        "schema_version": "1.0",
        "valid": True,
        "run_id": state["run_id"],
        "candidate_id": state["candidate_id"],
        "step_id": args.step_id,
        "test_path": test_relative,
        "historical_test_path": historical_path,
        "historical_path_binding_mode": binding_mode,
        "historical_test_bytes_bound": False,
        "test_sha256": sha256_file(test_path),
        "receipt_sha256": receipt_sha256,
        "stdout_sha256": raw_hashes["stdout"],
        "stderr_sha256": raw_hashes["stderr"],
        "failure_count": failure_count,
        "historical_assertion_passed": receipt.get("assertion_passed"),
        "distribution_status": "local_unpublished",
        "publication_actions_performed": False,
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--root", required=True, type=Path)
    result.add_argument("--run-dir", required=True, type=Path)
    result.add_argument("--step-id", required=True)
    result.add_argument("--test-path", required=True, type=Path)
    result.add_argument("--test-manifest", required=True, type=Path)
    return result


def main() -> int:
    try:
        result = verify(parser().parse_args())
    except RedEvidenceError as error:
        print(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "valid": False,
                    "errors": [str(error)],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 3
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
