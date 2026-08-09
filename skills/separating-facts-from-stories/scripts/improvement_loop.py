#!/usr/bin/env python3
"""Durable evidence controller for bounded Skill improvement rounds.

This runtime does not call an LLM or edit product source.  It records evidence,
advances a bounded loop, executes one fixed release-proof recipe, recovers
prepared transitions, and authorizes only explicitly scoped write proposals.
"""

from __future__ import annotations

import argparse
import ctypes
import errno
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager, redirect_stdout
from io import StringIO
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn


STATE_FILE = "loop-state.json"
PENDING_FILE = "pending-transition.json"
SCHEMA_VERSION = "1.1.0"
SOURCE_MANIFEST_SCHEMA_VERSION = "1.0.0"
PRODUCER_TIMEOUT_SECONDS = 3600
PRODUCER_RECIPE_VERSION = "2.0.0"
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
REQUIRED_EXECUTION_GRAPH = (
    ("preflight_snapshot", ()),
    ("adversarial_review", ("preflight_snapshot",)),
    ("red_green_fix", ("adversarial_review",)),
    ("deterministic_gate", ("red_green_fix",)),
    ("independent_recheck", ("deterministic_gate",)),
    ("source_freeze", ("independent_recheck",)),
    ("frozen_eval_prepare", ("source_freeze",)),
    ("isolated_eval", ("frozen_eval_prepare",)),
    ("eval_audit", ("isolated_eval",)),
    ("clean_install", ("eval_audit",)),
    ("rollback_validation", ("clean_install",)),
    ("evidence_gate", ("rollback_validation",)),
    ("loop_decision", ("evidence_gate",)),
)
REQUIRED_BACK_EDGE = "loop_decision -> preflight_snapshot"
EXECUTION_MODE_LEGACY = "legacy_gate"
EXECUTION_MODE_GRAPH = "execution_graph"
EXTERNAL_EXECUTION_STEPS = tuple(
    step_id
    for step_id, _ in REQUIRED_EXECUTION_GRAPH
    if step_id not in {
        "clean_install",
        "rollback_validation",
        "evidence_gate",
        "loop_decision",
    }
)
CONTROLLER_EXECUTION_STEPS = (
    "clean_install",
    "rollback_validation",
    "evidence_gate",
    "loop_decision",
)
PHASE_PRIMARY_ROLES = {
    "preflight_snapshot": "preflight_report",
    "adversarial_review": "review_pair_attestation",
    "red_green_fix": "red_green_fix_attestation",
    "deterministic_gate": "deterministic_gate_report",
    "independent_recheck": "recheck_pair_attestation",
    "source_freeze": "source_freeze_index",
    "frozen_eval_prepare": "eval_prepare_report",
    "isolated_eval": "isolated_eval_dispatch_attestation",
    "eval_audit": "eval_audit_report",
}
PHASE_RECEIPT_TYPE = "phase_receipt.v1"
PHASE_WORK_ORDER_TYPE = "phase_work_order.v1"
GRAPH_HOST_RECEIPT_TYPE = "graph_host_execution_receipt.v1"
GRAPH_RUNNER_TRUST_BOUNDARY = (
    "controller_observed_fixed_local_process_not_external_signature"
)
GRAPH_WORKER_BUNDLE_VERSION = "graph_worker_bundle.v1"
GRAPH_WORKER_TIMEOUT_SECONDS = 60
SOURCE_EPOCH_PLAN_TYPE = "source_epoch_plan.v2"
CONTROLLER_FINDING_PREFIXES = ("SOURCE-DRIFT-R",)
COMMAND_EXECUTION_RECEIPT_TYPE = "command_execution_receipt.v1"
COMMAND_EXECUTION_TRUST_BOUNDARY = (
    "local_attestation_only_not_cryptographic_signature"
)
FINDING_FIELDS = (
    "finding_id",
    "severity",
    "summary",
    "reproducer",
    "actual",
    "expected",
)
PROTECTED_PREFIXES = (
    PurePosixPath("10-自媒体/12-观点索引"),
    PurePosixPath("10-自媒体/17-观点库HL"),
    PurePosixPath("10-自媒体/13-选题库"),
    PurePosixPath("10-自媒体/11-已发布文案"),
    PurePosixPath("80-投资"),
)
REQUIRED_DENIED_OPERATIONS = ("delete", "push", "publish")
GATE_EVIDENCE_FIELDS = (
    "path",
    "sha256",
    "json_pointer",
    "expected",
)
GATE_ARTIFACT_ROLES = {
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
COMMAND_PROOF_CHECKS = {
    "unit_tests",
    "self_test",
    "frozen_eval_18_of_18",
    "artifacts_16_of_16",
    "clean_install",
    "verify_install",
    "rollback",
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


class LoopError(Exception):
    def __init__(self, code: str, message: str, *, exit_code: int = 2):
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code


class StructuredArgumentParser(argparse.ArgumentParser):
    """Route CLI usage failures through the controller JSON error channel."""

    def error(self, message: str) -> NoReturn:
        raise LoopError("ARGUMENT_ERROR", message)


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def emit(value: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def fail(code: str, message: str, *, exit_code: int = 2) -> NoReturn:
    raise LoopError(code, message, exit_code=exit_code)


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)
    fsync_directory(path.parent)


def atomic_write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    with temporary.open("x", encoding="utf-8") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    if path.exists() or path.is_symlink():
        temporary.unlink()
        fail("RUNNER_OUTPUT_CONFLICT", f"runner output already exists: {path}")
    os.replace(temporary, path)
    fsync_directory(path.parent)


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


@contextmanager
def controller_lock(state_dir_value: str | Path):
    state_dir = Path(state_dir_value).resolve()
    lock_path = state_dir.with_name(f".{state_dir.name}.controller.lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_object(path: Path, code: str, label: str) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        fail(code, f"{label} is required: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(code, f"{label} is not valid JSON: {exc}")
    if not isinstance(value, dict):
        fail(code, f"{label} must be a JSON object")
    return value


def lexical_relative(root: Path, value: str | Path, code: str) -> PurePosixPath:
    supplied = Path(value)
    lexical = supplied if supplied.is_absolute() else root / supplied
    lexical = Path(os.path.abspath(lexical))
    try:
        relative = lexical.relative_to(root)
    except ValueError:
        fail(code, f"path is outside candidate repository: {value}")
    return PurePosixPath(relative.as_posix())


def resolve_repo_path(
    root: Path,
    value: str | Path,
    *,
    outside_code: str = "PATH_OUTSIDE_REPO",
    require_file: bool = False,
) -> tuple[Path, str]:
    relative = lexical_relative(root, value, outside_code)
    lexical = root.joinpath(*relative.parts)
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            fail("PATH_SYMLINK_ESCAPE", f"symbolic links are not allowed: {value}")
    resolved = lexical.resolve(strict=False)
    try:
        resolved.relative_to(root)
    except ValueError:
        fail("PATH_SYMLINK_ESCAPE", f"path resolves outside candidate repository: {value}")
    if require_file and (not resolved.is_file() or resolved.is_symlink()):
        fail("SOURCE_FILE_INVALID", f"source must be a regular in-repository file: {value}")
    return resolved, relative.as_posix()


def _unquote_yaml_scalar(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_inline_yaml_list(value: str, number: int) -> list[str]:
    match = re.fullmatch(r"\[(.*)\]", value.strip())
    if match is None:
        fail(
            "WORKFLOW_POLICY_INVALID",
            f"step dependencies must use an inline list at line {number}",
        )
    body = match.group(1).strip()
    if not body:
        return []
    items = [_unquote_yaml_scalar(item.strip()) for item in body.split(",")]
    if any(not item for item in items) or len(items) != len(set(items)):
        fail(
            "WORKFLOW_POLICY_INVALID",
            f"step dependencies must be non-empty and unique at line {number}",
        )
    return items


def parse_workflow_policy(path: Path) -> dict[str, Any]:
    """Parse the small policy subset this controller is authorized to enforce.

    This is deliberately not a general YAML parser. Unsupported or ambiguous
    syntax fails closed instead of being guessed.
    """
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        fail("WORKFLOW_POLICY_INVALID", f"workflow cannot be read: {exc}")
    sections: dict[str, dict[str, Any]] = {}
    steps: list[dict[str, Any]] = []
    current_step: dict[str, Any] | None = None
    section: str | None = None
    list_key: str | None = None
    for number, raw in enumerate(lines, start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        if "\t" in raw:
            fail("WORKFLOW_POLICY_INVALID", f"tabs are not supported at line {number}")
        if not raw.startswith(" "):
            match = re.fullmatch(r"([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?", raw)
            if not match:
                continue
            section = match.group(1)
            list_key = None
            if not match.group(2):
                sections.setdefault(section, {})
            continue
        if section == "steps":
            step_match = re.fullmatch(
                r"  - id:\s*([A-Za-z_][A-Za-z0-9_-]*)\s*", raw
            )
            if step_match is not None:
                current_step = {
                    "id": step_match.group(1),
                    "depends_on": [],
                }
                steps.append(current_step)
                continue
            dependency_match = re.fullmatch(
                r"    depends_on:\s*(\[.*\])\s*", raw
            )
            if dependency_match is not None:
                if current_step is None:
                    fail(
                        "WORKFLOW_POLICY_INVALID",
                        f"step dependency appears before an id at line {number}",
                    )
                current_step["depends_on"] = _parse_inline_yaml_list(
                    dependency_match.group(1), number
                )
                continue
            if raw.startswith("    "):
                continue
            fail(
                "WORKFLOW_POLICY_INVALID",
                f"unsupported step syntax at line {number}",
            )
        if section not in {"controller", "loop_policy", "write_policy"}:
            continue
        if raw.startswith("  ") and not raw.startswith("    "):
            match = re.fullmatch(
                r"  ([A-Za-z_][A-Za-z0-9_-]*):(?:\s*(.*))?", raw
            )
            if not match:
                fail(
                    "WORKFLOW_POLICY_INVALID",
                    f"unsupported policy syntax at line {number}",
                )
            key, scalar = match.group(1), match.group(2)
            if scalar:
                sections.setdefault(section, {})[key] = _unquote_yaml_scalar(scalar)
                list_key = None
            else:
                sections.setdefault(section, {})[key] = []
                list_key = key
            continue
        if raw.startswith("    - ") and list_key is not None:
            value = _unquote_yaml_scalar(raw[6:])
            if not value:
                fail("WORKFLOW_POLICY_INVALID", f"empty list item at line {number}")
            target = sections.setdefault(section, {}).setdefault(list_key, [])
            if not isinstance(target, list):
                fail("WORKFLOW_POLICY_INVALID", f"mixed scalar/list at line {number}")
            target.append(value)

    controller = sections.get("controller", {})
    loop_policy = sections.get("loop_policy", {})
    write_policy = sections.get("write_policy", {})
    if controller.get("schema_version") != SCHEMA_VERSION:
        fail(
            "WORKFLOW_POLICY_INVALID",
            f"workflow controller schema must be {SCHEMA_VERSION}",
        )
    source_manifest = controller.get("source_manifest")
    controller_executable = controller.get("executable")
    stop_authority = controller.get("stop_authority", "legacy_external_gate")
    execution_mode = controller.get(
        "execution_mode",
        (
            EXECUTION_MODE_GRAPH
            if stop_authority == "controller_prove_stop"
            else EXECUTION_MODE_LEGACY
        ),
    )
    gate_producer = controller.get("gate_producer")
    try:
        max_rounds = int(str(loop_policy.get("max_rounds", "")))
    except ValueError:
        fail("WORKFLOW_POLICY_INVALID", "workflow max_rounds must be an integer")
    gate_checks = loop_policy.get("required_gate_checks")
    back_edge = loop_policy.get("back_edge")
    allowed_roots = write_policy.get("allowed_roots")
    denied = write_policy.get("denied_operations")
    if (
        not 1 <= max_rounds <= 100
        or not isinstance(controller_executable, str)
        or not controller_executable
        or not isinstance(source_manifest, str)
        or not source_manifest
        or stop_authority not in {"legacy_external_gate", "controller_prove_stop"}
        or execution_mode not in {EXECUTION_MODE_LEGACY, EXECUTION_MODE_GRAPH}
        or (
            stop_authority == "controller_prove_stop"
            and execution_mode != EXECUTION_MODE_GRAPH
        )
        or (
            stop_authority == "legacy_external_gate"
            and execution_mode != EXECUTION_MODE_LEGACY
        )
        or (
            stop_authority == "controller_prove_stop"
            and (not isinstance(gate_producer, str) or not gate_producer)
        )
        or (
            stop_authority == "legacy_external_gate"
            and gate_producer is not None
            and (not isinstance(gate_producer, str) or not gate_producer)
        )
        or not isinstance(gate_checks, list)
        or tuple(gate_checks) != REQUIRED_GATE_CHECKS
        or not isinstance(allowed_roots, list)
        or not allowed_roots
        or any(not isinstance(item, str) or not item for item in allowed_roots)
        or not isinstance(denied, list)
        or not set(REQUIRED_DENIED_OPERATIONS).issubset(denied)
    ):
        fail(
            "WORKFLOW_POLICY_INVALID",
            "workflow must define the exact stop checks, bounded rounds, write roots, and denied operations",
        )
    expected_graph = [
        {"id": step_id, "depends_on": list(dependencies)}
        for step_id, dependencies in REQUIRED_EXECUTION_GRAPH
    ]
    if execution_mode == EXECUTION_MODE_GRAPH and (
        back_edge != REQUIRED_BACK_EDGE or steps != expected_graph
    ):
        fail(
            "WORKFLOW_POLICY_INVALID",
            "workflow must define the exact acyclic execution graph and dependencies",
        )
    normalized_roots = sorted(dict.fromkeys(item.rstrip("/") or "." for item in allowed_roots))
    return {
        "schema_version": SCHEMA_VERSION,
        "controller_executable": controller_executable,
        "stop_authority": stop_authority,
        "execution_mode": execution_mode,
        "gate_producer": gate_producer,
        "source_manifest": source_manifest,
        "max_rounds": max_rounds,
        "required_gate_checks": list(gate_checks),
        "back_edge": REQUIRED_BACK_EDGE,
        "execution_graph": expected_graph,
        "allowed_write_roots": normalized_roots,
        "denied_operations": sorted(dict.fromkeys(denied)),
    }


def parse_source_manifest(
    repo_root: Path,
    manifest_value: str,
    *,
    workflow_relative: str,
    controller_executable: str,
) -> tuple[dict[str, str], list[str]]:
    manifest_path, manifest_relative = resolve_repo_path(
        repo_root,
        manifest_value,
        outside_code="SOURCE_MANIFEST_INVALID",
        require_file=True,
    )
    document = read_object(
        manifest_path,
        "SOURCE_MANIFEST_INVALID",
        "release source manifest",
    )
    if set(document) != {"schema_version", "source_files"}:
        fail(
            "SOURCE_MANIFEST_INVALID",
            "source manifest must contain only schema_version and source_files",
        )
    if document.get("schema_version") != SOURCE_MANIFEST_SCHEMA_VERSION:
        fail(
            "SOURCE_MANIFEST_INVALID",
            f"source manifest schema must be {SOURCE_MANIFEST_SCHEMA_VERSION}",
        )
    declared = document.get("source_files")
    if (
        not isinstance(declared, list)
        or not declared
        or any(not isinstance(item, str) or not item for item in declared)
        or len(set(declared)) != len(declared)
        or declared != sorted(declared)
        or workflow_relative not in declared
        or controller_executable not in declared
        or manifest_relative not in declared
    ):
        fail(
            "SOURCE_MANIFEST_INVALID",
            "source_files must be a sorted unique list containing the controller, workflow, and manifest",
        )
    normalized: list[str] = []
    for value in declared:
        _, relative = resolve_repo_path(
            repo_root,
            value,
            outside_code="SOURCE_MANIFEST_INVALID",
            require_file=True,
        )
        if relative != value:
            fail(
                "SOURCE_MANIFEST_INVALID",
                f"source path is not normalized: {value}",
            )
        normalized.append(relative)
    return (
        {"path": manifest_relative, "sha256": file_sha256(manifest_path)},
        normalized,
    )


def execution_step_ids(policy: dict[str, Any]) -> list[str]:
    return [item["id"] for item in policy["execution_graph"]]


def execution_dependencies(policy: dict[str, Any]) -> dict[str, list[str]]:
    return {
        item["id"]: list(item["depends_on"])
        for item in policy["execution_graph"]
    }


def validate_iteration_step_ledger_shape(
    iteration: dict[str, Any],
    policy: dict[str, Any],
) -> None:
    """Validate that a graph iteration is an exact ordered prefix of the DAG."""
    if policy.get("execution_mode") == EXECUTION_MODE_LEGACY:
        if (
            iteration.get("next_step") != "preflight_snapshot"
            or iteration.get("step_ledger") != []
            or iteration.get("active_work_order") is not None
        ):
            fail("STATE_INVALID", "legacy iteration contains graph execution state")
        return

    ledger = iteration.get("step_ledger")
    if not isinstance(ledger, list):
        fail("STATE_INVALID", "graph iteration step_ledger must be a list")
    step_ids = execution_step_ids(policy)
    observed_ids: list[str] = []
    for entry in ledger:
        if (
            not isinstance(entry, dict)
            or set(entry)
            != {
                "step_id",
                "receipt",
                "work_order",
                "attempt_id",
                "source_sha256",
                "dependency_receipts",
                "artifacts",
            }
            or not isinstance(entry.get("step_id"), str)
            or not isinstance(entry.get("receipt"), dict)
            or set(entry["receipt"]) != {"path", "sha256"}
            or not isinstance(entry["receipt"].get("path"), str)
            or not _is_sha256(entry["receipt"].get("sha256"))
            or (
                entry.get("work_order") is not None
                and (
                    not isinstance(entry["work_order"], dict)
                    or set(entry["work_order"]) != {"path", "sha256"}
                    or not isinstance(entry["work_order"].get("path"), str)
                    or not _is_sha256(entry["work_order"].get("sha256"))
                )
            )
            or not isinstance(entry.get("attempt_id"), str)
            or not entry["attempt_id"]
            or not _is_sha256(entry.get("source_sha256"))
            or not isinstance(entry.get("dependency_receipts"), dict)
            or any(
                not isinstance(key, str) or not _is_sha256(value)
                for key, value in entry["dependency_receipts"].items()
            )
            or not isinstance(entry.get("artifacts"), list)
            or not entry["artifacts"]
        ):
            fail("STATE_INVALID", "graph step ledger entry is malformed")
        observed_ids.append(entry["step_id"])
    if observed_ids != step_ids[: len(observed_ids)]:
        fail("STATE_INVALID", "graph step ledger is not an ordered DAG prefix")
    expected_next = step_ids[len(observed_ids)] if len(observed_ids) < len(step_ids) else None
    if iteration.get("next_step") != expected_next:
        fail("STATE_INVALID", "graph next_step differs from the ledger prefix")
    active = iteration.get("active_work_order")
    if active is not None and (
        not isinstance(active, dict)
        or set(active) != {"step_id", "attempt_id", "path", "sha256"}
        or active.get("step_id") != expected_next
        or not isinstance(active.get("attempt_id"), str)
        or not active["attempt_id"]
        or not isinstance(active.get("path"), str)
        or not active["path"]
        or not _is_sha256(active.get("sha256"))
    ):
        fail("STATE_INVALID", "active phase work order is malformed or stale")


def _phase_receipt_path(
    repo_root: Path,
    state: dict[str, Any],
    value: str | Path,
    *,
    error_code: str,
) -> tuple[Path, str]:
    path, relative = resolve_repo_path(
        repo_root,
        value,
        outside_code=error_code,
        require_file=True,
    )
    state_relative = PurePosixPath(
        Path(state["state_dir"]).relative_to(repo_root).as_posix()
    )
    if not path_is_within(PurePosixPath(relative), state_relative):
        fail(error_code, "phase receipt must be stored inside the controller state directory")
    return path, relative


def _phase_work_order_path(
    repo_root: Path,
    state: dict[str, Any],
    value: str | Path,
    *,
    error_code: str,
) -> tuple[Path, str]:
    path, relative = resolve_repo_path(
        repo_root,
        value,
        outside_code=error_code,
        require_file=True,
    )
    state_relative = PurePosixPath(
        Path(state["state_dir"]).relative_to(repo_root).as_posix()
    )
    if not path_is_within(PurePosixPath(relative), state_relative):
        fail(error_code, "phase work order must be stored inside the controller state directory")
    return path, relative


def validate_phase_work_order(
    repo_root: Path,
    state: dict[str, Any],
    iteration: dict[str, Any],
    reference: dict[str, str],
    *,
    expected_step_id: str,
    expected_source_sha256: str,
    expected_dependencies: dict[str, str],
    error_code: str,
) -> dict[str, Any]:
    try:
        path, relative = _phase_work_order_path(
            repo_root,
            state,
            reference["path"],
            error_code=error_code,
        )
    except (KeyError, TypeError):
        fail(error_code, "phase work order reference is malformed")
    if file_sha256(path) != reference.get("sha256"):
        fail(error_code, "phase work order hash mismatch")
    work_order = read_object(path, error_code, "phase work order")
    required = {
        "schema_version",
        "work_order_type",
        "controller_run_id",
        "state_dir",
        "iteration_id",
        "source_sha256",
        "step_id",
        "attempt_id",
        "dependency_receipts",
    }
    if (
        set(work_order) != required
        or work_order.get("schema_version") != SCHEMA_VERSION
        or work_order.get("work_order_type") != PHASE_WORK_ORDER_TYPE
        or work_order.get("controller_run_id") != state["controller_run_id"]
        or work_order.get("state_dir") != state["state_dir"]
        or work_order.get("iteration_id") != iteration["iteration_id"]
        or work_order.get("source_sha256") != expected_source_sha256
        or work_order.get("step_id") != expected_step_id
        or not isinstance(work_order.get("attempt_id"), str)
        or not work_order["attempt_id"]
        or work_order.get("dependency_receipts") != expected_dependencies
    ):
        fail(error_code, "phase work order identity or dependency root is invalid")
    return {
        "document": work_order,
        "reference": {"path": relative, "sha256": reference["sha256"]},
    }


def _is_red_test_source_path(value: Any) -> bool:
    if not isinstance(value, str) or not value:
        return False
    path = PurePosixPath(value)
    return (
        "tests" in path.parts
        and path.name.startswith("test_")
        and path.suffix == ".py"
    )


def validate_source_epoch_record_shape(value: Any) -> None:
    required = {
        "plan",
        "attempt_id",
        "source_before_sha256",
        "red_source_sha256",
        "source_after_sha256",
        "source_before_files",
        "red_source_files",
        "source_after_files",
        "finding_ids",
        "red_tests",
        "finding_red_tests",
        "red_changes",
        "implementation_changes",
    }
    if not isinstance(value, dict) or set(value) != required:
        fail("STATE_INVALID", "source epoch record is malformed")
    if (
        not isinstance(value.get("plan"), dict)
        or set(value["plan"]) != {"path", "sha256"}
        or not isinstance(value["plan"].get("path"), str)
        or not _is_sha256(value["plan"].get("sha256"))
        or not isinstance(value.get("attempt_id"), str)
        or not value["attempt_id"]
        or not _is_sha256(value.get("source_before_sha256"))
        or not _is_sha256(value.get("red_source_sha256"))
        or not _is_sha256(value.get("source_after_sha256"))
        or not isinstance(value.get("source_before_files"), dict)
        or not isinstance(value.get("red_source_files"), dict)
        or not isinstance(value.get("source_after_files"), dict)
        or value["source_before_sha256"]
        != canonical_sha256(value["source_before_files"])
        or value["red_source_sha256"]
        != canonical_sha256(value["red_source_files"])
        or value["source_after_sha256"]
        != canonical_sha256(value["source_after_files"])
        or not isinstance(value.get("finding_ids"), list)
        or any(not isinstance(item, str) or not item for item in value["finding_ids"])
        or value["finding_ids"] != sorted(value["finding_ids"])
        or len(value["finding_ids"]) != len(set(value["finding_ids"]))
        or not isinstance(value.get("red_tests"), list)
        or not isinstance(value.get("finding_red_tests"), list)
        or not isinstance(value.get("red_changes"), list)
        or not isinstance(value.get("implementation_changes"), list)
    ):
        fail("STATE_INVALID", "source epoch identity or file maps are malformed")


def read_source_epoch_plan(
    repo_root: Path,
    state: dict[str, Any],
    iteration: dict[str, Any],
    plan_value: str | Path,
    *,
    require_live_before: bool,
    error_code: str,
) -> dict[str, Any]:
    plan_path, plan_relative = _phase_work_order_path(
        repo_root,
        state,
        plan_value,
        error_code=error_code,
    )
    plan = read_object(plan_path, error_code, "source epoch plan")
    required = {
        "schema_version",
        "plan_type",
        "controller_run_id",
        "iteration_id",
        "attempt_id",
        "source_before_sha256",
        "red_source_sha256",
        "source_after_sha256",
        "source_before_files",
        "red_source_files",
        "source_after_files",
        "finding_red_tests",
        "red_changes",
        "implementation_changes",
    }
    active_work_order = iteration.get("active_work_order")
    expected_attempt = (
        active_work_order.get("attempt_id")
        if require_live_before and isinstance(active_work_order, dict)
        else plan.get("attempt_id")
    )
    if (
        set(plan) != required
        or plan.get("schema_version") != SCHEMA_VERSION
        or plan.get("plan_type") != SOURCE_EPOCH_PLAN_TYPE
        or plan.get("controller_run_id") != state["controller_run_id"]
        or plan.get("iteration_id") != iteration["iteration_id"]
        or plan.get("attempt_id") != expected_attempt
        or not isinstance(plan.get("source_before_files"), dict)
        or not isinstance(plan.get("red_source_files"), dict)
        or not isinstance(plan.get("source_after_files"), dict)
        or set(plan["source_before_files"]) != set(state["source_files"])
        or set(plan["red_source_files"]) != set(state["source_files"])
        or set(plan["source_after_files"]) != set(state["source_files"])
        or list(plan["source_before_files"]) != sorted(plan["source_before_files"])
        or list(plan["red_source_files"]) != sorted(plan["red_source_files"])
        or list(plan["source_after_files"]) != sorted(plan["source_after_files"])
        or plan.get("source_before_sha256")
        != canonical_sha256(plan["source_before_files"])
        or plan.get("red_source_sha256")
        != canonical_sha256(plan["red_source_files"])
        or plan.get("source_after_sha256")
        != canonical_sha256(plan["source_after_files"])
        or any(
            not _is_sha256(file_sha256_value)
            for file_map in (
                plan["source_before_files"],
                plan["red_source_files"],
                plan["source_after_files"],
            )
            for file_sha256_value in file_map.values()
        )
        or not isinstance(plan.get("finding_red_tests"), list)
        or not isinstance(plan.get("red_changes"), list)
        or not isinstance(plan.get("implementation_changes"), list)
    ):
        fail(error_code, "source epoch plan identity or snapshots are invalid")
    if require_live_before and (
        plan["source_before_files"] != state["source_snapshot"]["files"]
        or plan["source_before_sha256"] != state["source_snapshot"]["sha256"]
    ):
        fail(error_code, "source epoch plan does not bind the live before snapshot")

    normalized_finding_red_tests: list[dict[str, str]] = []
    seen_finding_ids: set[str] = set()
    for red_test in plan["finding_red_tests"]:
        if (
            not isinstance(red_test, dict)
            or set(red_test) != {"finding_id", "path", "sha256"}
            or not isinstance(red_test.get("finding_id"), str)
            or not red_test["finding_id"]
            or red_test["finding_id"] in seen_finding_ids
            or red_test.get("path") not in state["source_files"]
            or not _is_sha256(red_test.get("sha256"))
            or not _is_red_test_source_path(red_test["path"])
            or plan["red_source_files"].get(red_test["path"])
            != red_test["sha256"]
            or plan["source_after_files"].get(red_test["path"])
            != red_test["sha256"]
        ):
            fail(error_code, "source epoch finding RED binding is invalid")
        seen_finding_ids.add(red_test["finding_id"])
        normalized_finding_red_tests.append(dict(red_test))
    if normalized_finding_red_tests != sorted(
        normalized_finding_red_tests,
        key=lambda item: (item["finding_id"], item["path"], item["sha256"]),
    ):
        fail(error_code, "source epoch finding RED bindings must be sorted")

    normalized_red_tests: list[dict[str, str]] = []
    for item in normalized_finding_red_tests:
        red_test = {"path": item["path"], "sha256": item["sha256"]}
        if red_test not in normalized_red_tests:
            normalized_red_tests.append(red_test)
    normalized_red_tests.sort(key=lambda item: (item["path"], item["sha256"]))

    control_paths = {
        state["workflow"]["path"],
        state["workflow_policy"]["controller_executable"],
        state["source_manifest"]["path"],
    }
    gate_producer = state["workflow_policy"].get("gate_producer")
    if isinstance(gate_producer, str) and gate_producer:
        control_paths.add(gate_producer)
    red_test_paths = {item["path"] for item in normalized_red_tests}

    normalized_red_changes: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    for change in plan["red_changes"]:
        if (
            not isinstance(change, dict)
            or set(change) != {"path", "before_blob", "red_blob"}
            or not isinstance(change.get("path"), str)
            or change["path"] in seen_paths
            or change["path"] not in state["source_files"]
            or change["path"] in control_paths
            or change["path"] not in red_test_paths
            or not _is_red_test_source_path(change["path"])
            or not isinstance(change.get("before_blob"), dict)
            or set(change["before_blob"]) != {"path", "sha256"}
            or not _is_sha256(change["before_blob"].get("sha256"))
            or not isinstance(change.get("red_blob"), dict)
            or set(change["red_blob"]) != {"path", "sha256"}
            or not _is_sha256(change["red_blob"].get("sha256"))
        ):
            fail(error_code, "source epoch RED change is malformed or outside authority")
        relative = PurePosixPath(change["path"])
        if protected_path(relative) or not any(
            path_is_within(relative, PurePosixPath(root))
            for root in state["allowed_write_roots"]
        ):
            fail(error_code, "source epoch RED change targets a protected path")
        before_blob_path, before_blob_relative = _phase_work_order_path(
            repo_root,
            state,
            change["before_blob"]["path"],
            error_code=error_code,
        )
        red_blob_path, red_blob_relative = _phase_work_order_path(
            repo_root,
            state,
            change["red_blob"]["path"],
            error_code=error_code,
        )
        if (
            file_sha256(before_blob_path) != change["before_blob"]["sha256"]
            or plan["source_before_files"].get(change["path"])
            != change["before_blob"]["sha256"]
            or file_sha256(red_blob_path) != change["red_blob"]["sha256"]
            or plan["red_source_files"].get(change["path"])
            != change["red_blob"]["sha256"]
            or plan["source_after_files"].get(change["path"])
            != change["red_blob"]["sha256"]
            or change["before_blob"]["sha256"]
            == change["red_blob"]["sha256"]
        ):
            fail(
                error_code,
                "source epoch before/RED blobs do not match S0, Sr, and S1",
            )
        seen_paths.add(change["path"])
        normalized_red_changes.append(
            {
                "path": change["path"],
                "before_blob": {
                    "path": before_blob_relative,
                    "sha256": change["before_blob"]["sha256"],
                },
                "red_blob": {
                    "path": red_blob_relative,
                    "sha256": change["red_blob"]["sha256"],
                },
            }
        )
    if normalized_red_changes != sorted(
        normalized_red_changes, key=lambda item: item["path"]
    ):
        fail(error_code, "source epoch RED changes must be sorted")
    observed_red_changed = sorted(
        path
        for path in state["source_files"]
        if plan["source_before_files"][path] != plan["red_source_files"][path]
    )
    if observed_red_changed != [item["path"] for item in normalized_red_changes]:
        fail(error_code, "source epoch RED map contains an undeclared change")

    normalized_implementation_changes: list[dict[str, Any]] = []
    seen_implementation_paths: set[str] = set()
    for change in plan["implementation_changes"]:
        if (
            not isinstance(change, dict)
            or set(change) != {"path", "red_blob", "after_blob"}
            or not isinstance(change.get("path"), str)
            or change["path"] in seen_implementation_paths
            or change["path"] not in state["source_files"]
            or change["path"] in control_paths
            or _is_red_test_source_path(change["path"])
            or not isinstance(change.get("red_blob"), dict)
            or set(change["red_blob"]) != {"path", "sha256"}
            or not _is_sha256(change["red_blob"].get("sha256"))
            or not isinstance(change.get("after_blob"), dict)
            or set(change["after_blob"]) != {"path", "sha256"}
            or not _is_sha256(change["after_blob"].get("sha256"))
        ):
            fail(
                error_code,
                "source epoch implementation change is malformed or outside authority",
            )
        relative = PurePosixPath(change["path"])
        if protected_path(relative) or not any(
            path_is_within(relative, PurePosixPath(root))
            for root in state["allowed_write_roots"]
        ):
            fail(error_code, "source epoch implementation targets a protected path")
        red_blob_path, red_blob_relative = _phase_work_order_path(
            repo_root,
            state,
            change["red_blob"]["path"],
            error_code=error_code,
        )
        after_blob_path, after_blob_relative = _phase_work_order_path(
            repo_root,
            state,
            change["after_blob"]["path"],
            error_code=error_code,
        )
        if (
            file_sha256(red_blob_path) != change["red_blob"]["sha256"]
            or plan["red_source_files"].get(change["path"])
            != change["red_blob"]["sha256"]
            or file_sha256(after_blob_path) != change["after_blob"]["sha256"]
            or plan["source_after_files"].get(change["path"])
            != change["after_blob"]["sha256"]
            or change["red_blob"]["sha256"]
            == change["after_blob"]["sha256"]
        ):
            fail(error_code, "source epoch Sr/S1 blobs do not match implementation")
        seen_implementation_paths.add(change["path"])
        normalized_implementation_changes.append(
            {
                "path": change["path"],
                "red_blob": {
                    "path": red_blob_relative,
                    "sha256": change["red_blob"]["sha256"],
                },
                "after_blob": {
                    "path": after_blob_relative,
                    "sha256": change["after_blob"]["sha256"],
                },
            }
        )
    if normalized_implementation_changes != sorted(
        normalized_implementation_changes, key=lambda item: item["path"]
    ):
        fail(error_code, "source epoch implementation changes must be sorted")
    observed_implementation_changed = sorted(
        path
        for path in state["source_files"]
        if plan["red_source_files"][path] != plan["source_after_files"][path]
    )
    if observed_implementation_changed != [
        item["path"] for item in normalized_implementation_changes
    ]:
        fail(error_code, "source epoch after map contains an undeclared change")
    if seen_paths & seen_implementation_paths:
        fail(error_code, "RED and implementation changes must use disjoint paths")

    record = {
        "plan": {"path": plan_relative, "sha256": file_sha256(plan_path)},
        "attempt_id": plan["attempt_id"],
        "source_before_sha256": plan["source_before_sha256"],
        "red_source_sha256": plan["red_source_sha256"],
        "source_after_sha256": plan["source_after_sha256"],
        "source_before_files": dict(sorted(plan["source_before_files"].items())),
        "red_source_files": dict(sorted(plan["red_source_files"].items())),
        "source_after_files": dict(sorted(plan["source_after_files"].items())),
        "finding_ids": sorted(seen_finding_ids),
        "red_tests": normalized_red_tests,
        "finding_red_tests": normalized_finding_red_tests,
        "red_changes": normalized_red_changes,
        "implementation_changes": normalized_implementation_changes,
    }
    validate_source_epoch_record_shape(record)
    return record


def _graph_worker_relative(state: dict[str, Any]) -> str:
    controller = PurePosixPath(
        state["workflow_policy"]["controller_executable"]
    )
    return controller.with_name("graph_phase_worker.py").as_posix()


def _validate_graph_artifact_descriptor(
    repo_root: Path,
    descriptor: Any,
    *,
    phase_artifacts: list[dict[str, str]],
    error_code: str,
) -> Path:
    if (
        not isinstance(descriptor, dict)
        or set(descriptor) != {"path", "sha256", "bytes"}
        or not isinstance(descriptor.get("path"), str)
        or not _is_sha256(descriptor.get("sha256"))
        or type(descriptor.get("bytes")) is not int
        or descriptor["bytes"] < 0
    ):
        fail(error_code, "graph host artifact descriptor is malformed")
    path, relative = resolve_repo_path(
        repo_root,
        descriptor["path"],
        outside_code=error_code,
        require_file=True,
    )
    if (
        relative != descriptor["path"]
        or path.stat().st_size != descriptor["bytes"]
        or file_sha256(path) != descriptor["sha256"]
        or not any(
            artifact["path"] == relative
            and artifact["sha256"] == descriptor["sha256"]
            for artifact in phase_artifacts
        )
    ):
        fail(error_code, "graph host artifact bytes are unbound or changed")
    return path


def validate_graph_host_execution(
    repo_root: Path,
    state: dict[str, Any],
    iteration: dict[str, Any],
    phase_receipt: dict[str, Any],
    phase_artifacts: list[dict[str, str]],
    *,
    error_code: str,
) -> dict[str, Any]:
    host_refs = [
        artifact
        for artifact in phase_artifacts
        if artifact["role"] == "host_execution_receipt"
    ]
    if len(host_refs) != 1:
        fail(error_code, "controller-owned phase requires one host execution receipt")
    host_path, _ = resolve_repo_path(
        repo_root,
        host_refs[0]["path"],
        outside_code=error_code,
        require_file=True,
    )
    host = read_object(host_path, error_code, "graph host execution receipt")
    required = {
        "schema_version",
        "receipt_type",
        "trust_boundary",
        "controller_run_id",
        "iteration_id",
        "source_before_sha256",
        "source_after_sha256",
        "step_id",
        "attempt_id",
        "execution_id",
        "work_order",
        "command",
        "process",
        "artifacts",
    }
    producer = phase_receipt["producer"]
    if (
        set(host) != required
        or host.get("schema_version") != SCHEMA_VERSION
        or host.get("receipt_type") != GRAPH_HOST_RECEIPT_TYPE
        or host.get("trust_boundary") != GRAPH_RUNNER_TRUST_BOUNDARY
        or host.get("controller_run_id") != state["controller_run_id"]
        or host.get("iteration_id") != iteration["iteration_id"]
        or host.get("source_before_sha256") != phase_receipt["source_sha256"]
        or host.get("source_after_sha256") != phase_receipt["source_sha256"]
        or host.get("step_id") != phase_receipt["step_id"]
        or host.get("attempt_id") != phase_receipt["attempt_id"]
        or host.get("execution_id") != producer.get("execution_id")
        or host.get("work_order") != phase_receipt["work_order"]
        or producer.get("actor_id") != "improvement_loop.graph_runner"
        or producer.get("trust_boundary") != GRAPH_RUNNER_TRUST_BOUNDARY
    ):
        fail(error_code, "graph host execution identity is malformed or stale")
    worker_relative = _graph_worker_relative(state)
    worker_path, _ = resolve_repo_path(
        repo_root,
        worker_relative,
        outside_code=error_code,
        require_file=True,
    )
    if state["source_snapshot"]["files"].get(worker_relative) != file_sha256(
        worker_path
    ):
        fail(error_code, "graph worker is not part of the frozen source")
    work_order_path, _ = resolve_repo_path(
        repo_root,
        phase_receipt["work_order"]["path"],
        outside_code=error_code,
        require_file=True,
    )
    expected_argv = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        str(worker_path),
        "--step",
        phase_receipt["step_id"],
        "--state",
        str(state_path(Path(state["state_dir"]))),
        "--work-order",
        str(work_order_path),
    ]
    command = host.get("command")
    if (
        not isinstance(command, dict)
        or set(command)
        != {
            "argv",
            "argv_sha256",
            "cwd",
            "shell",
            "timeout_seconds",
            "worker_sha256",
        }
        or command.get("argv") != expected_argv
        or command.get("argv_sha256") != canonical_sha256(expected_argv)
        or command.get("cwd") != str(repo_root.resolve())
        or command.get("shell") is not False
        or command.get("timeout_seconds") != GRAPH_WORKER_TIMEOUT_SECONDS
        or command.get("worker_sha256") != file_sha256(worker_path)
    ):
        fail(error_code, "graph host command is not the fixed recipe")
    process = host.get("process")
    family = process.get("process_family") if isinstance(process, dict) else None
    if (
        not isinstance(process, dict)
        or set(process)
        != {"pid", "exit_code", "timed_out", "duration_ms", "process_family"}
        or type(process.get("pid")) is not int
        or process["pid"] <= 0
        or process.get("exit_code") != 0
        or process.get("timed_out") is not False
        or type(process.get("duration_ms")) is not int
        or process["duration_ms"] < 0
        or not isinstance(family, dict)
        or family.get("confirmed_empty") is not True
        or family.get("trust_boundary") != PROCESS_FAMILY_TRUST_BOUNDARY
    ):
        fail(error_code, "graph host process result is not a successful observation")
    raw_artifacts = host.get("artifacts")
    if not isinstance(raw_artifacts, dict) or set(raw_artifacts) != {
        "stdout",
        "stderr",
    }:
        fail(error_code, "graph host output artifact set is malformed")
    stdout_path = _validate_graph_artifact_descriptor(
        repo_root,
        raw_artifacts["stdout"],
        phase_artifacts=phase_artifacts,
        error_code=error_code,
    )
    _validate_graph_artifact_descriptor(
        repo_root,
        raw_artifacts["stderr"],
        phase_artifacts=phase_artifacts,
        error_code=error_code,
    )
    try:
        bundle = json.loads(stdout_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(error_code, f"graph worker stdout is not one JSON object: {exc}")
    if (
        not isinstance(bundle, dict)
        or set(bundle)
        != {"schema_version", "step_id", "summary", "result", "finding_events"}
        or bundle.get("schema_version") != GRAPH_WORKER_BUNDLE_VERSION
        or bundle.get("step_id") != phase_receipt["step_id"]
        or not isinstance(bundle.get("summary"), str)
        or not bundle["summary"].strip()
        or not isinstance(bundle.get("result"), dict)
        or not isinstance(bundle.get("finding_events"), list)
        or any(not isinstance(item, dict) for item in bundle["finding_events"])
        or phase_receipt["summary"] != bundle["summary"]
        or phase_receipt["finding_events"] != bundle["finding_events"]
    ):
        fail(error_code, "graph worker bundle is malformed or not reflected in phase receipt")
    primary_role = PHASE_PRIMARY_ROLES[phase_receipt["step_id"]]
    primary = [item for item in phase_artifacts if item["role"] == primary_role]
    if len(primary) != 1:
        fail(error_code, "graph worker bundle lacks its typed primary artifact")
    primary_path, _ = resolve_repo_path(
        repo_root,
        primary[0]["path"],
        outside_code=error_code,
        require_file=True,
    )
    primary_document = read_object(primary_path, error_code, "graph primary artifact")
    if primary_document.get("result") != bundle["result"]:
        fail(error_code, "graph primary artifact does not match observed worker stdout")
    return bundle


def validate_phase_receipt(
    repo_root: Path,
    state: dict[str, Any],
    iteration: dict[str, Any],
    *,
    receipt_path: Path,
    receipt_relative: str,
    receipt: dict[str, Any],
    expected_step_id: str,
    expected_dependencies: dict[str, str],
    expected_work_order: dict[str, str] | None,
    expected_source_sha256: str,
    expected_work_order_source_sha256: str,
    error_code: str = "STEP_RECEIPT_INVALID",
    frozen_source_root: Path | None = None,
) -> dict[str, Any]:
    required_fields = {
        "schema_version",
        "receipt_type",
        "controller_run_id",
        "attempt_id",
        "work_order",
        "iteration_id",
        "source_sha256",
        "step_id",
        "status",
        "dependency_receipts",
        "producer",
        "summary",
        "artifacts",
        "finding_events",
    }
    if set(receipt) != required_fields:
        fail(error_code, "phase receipt fields do not match the fixed contract")
    producer = receipt.get("producer")
    if receipt.get("controller_run_id") != state["controller_run_id"]:
        fail(
            "RUN_ID_MISMATCH"
            if error_code == "STEP_RECEIPT_INVALID"
            else error_code,
            "phase receipt belongs to another controller run",
        )
    if (
        receipt.get("schema_version") != SCHEMA_VERSION
        or receipt.get("receipt_type") != PHASE_RECEIPT_TYPE
        or not isinstance(receipt.get("attempt_id"), str)
        or not receipt["attempt_id"]
        or receipt.get("work_order") != expected_work_order
        or receipt.get("iteration_id") != iteration["iteration_id"]
        or receipt.get("source_sha256") != expected_source_sha256
        or receipt.get("step_id") != expected_step_id
        or receipt.get("status") != "succeeded"
        or receipt.get("dependency_receipts") != expected_dependencies
        or not isinstance(receipt.get("summary"), str)
        or not receipt["summary"].strip()
        or not isinstance(producer, dict)
        or set(producer) != {"actor_id", "execution_id", "trust_boundary"}
        or any(
            not isinstance(producer.get(key), str) or not producer[key].strip()
            for key in producer
        )
        or not isinstance(receipt.get("finding_events"), list)
        or any(not isinstance(item, dict) for item in receipt["finding_events"])
    ):
        fail(error_code, "phase receipt identity, status, dependency, or producer is invalid")
    if expected_work_order is not None:
        validated_work_order = validate_phase_work_order(
            repo_root,
            state,
            iteration,
            expected_work_order,
            expected_step_id=expected_step_id,
            expected_source_sha256=expected_work_order_source_sha256,
            expected_dependencies=expected_dependencies,
            error_code=error_code,
        )
        work_order = validated_work_order["document"]
        if (
            receipt["attempt_id"] != work_order["attempt_id"]
            or receipt["step_id"] != work_order["step_id"]
            or receipt["dependency_receipts"]
            != work_order["dependency_receipts"]
        ):
            fail(error_code, "phase receipt does not consume its exact work order")

    artifacts = receipt.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        fail(error_code, "phase receipt must bind at least one artifact")
    normalized_artifacts: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for artifact in artifacts:
        if (
            not isinstance(artifact, dict)
            or set(artifact) != {"role", "path", "sha256"}
            or not isinstance(artifact.get("role"), str)
            or not artifact["role"].strip()
            or not isinstance(artifact.get("path"), str)
            or not artifact["path"]
            or not _is_sha256(artifact.get("sha256"))
        ):
            fail(error_code, "phase receipt artifact is malformed")
        try:
            artifact_root = (
                frozen_source_root
                if frozen_source_root is not None
                and artifact["path"] in state["source_files"]
                else repo_root
            )
            artifact_path, artifact_relative = resolve_repo_path(
                artifact_root,
                artifact["path"],
                outside_code=error_code,
                require_file=True,
            )
        except LoopError as exc:
            fail(error_code, f"phase artifact is unavailable: {exc.code}: {exc.message}")
        if artifact_relative in seen_paths:
            fail(error_code, "phase receipt artifact paths must be unique")
        if artifact_relative == receipt_relative:
            fail(error_code, "phase receipt cannot cite itself as an artifact")
        if file_sha256(artifact_path) != artifact["sha256"]:
            fail(error_code, f"phase artifact hash mismatch: {artifact_relative}")
        seen_paths.add(artifact_relative)
        normalized_artifacts.append(
            {
                "role": artifact["role"],
                "path": artifact_relative,
                "sha256": artifact["sha256"],
            }
        )

    if producer.get("trust_boundary") == GRAPH_RUNNER_TRUST_BOUNDARY:
        validate_graph_host_execution(
            repo_root,
            state,
            iteration,
            receipt,
            normalized_artifacts,
            error_code=error_code,
        )
    elif producer.get("actor_id") == "improvement_loop.graph_runner":
        fail(error_code, "graph runner identity requires host-observed execution")

    validate_phase_payload(
        repo_root,
        state,
        iteration,
        receipt,
        normalized_artifacts,
        error_code=(
            "PHASE_PAYLOAD_INVALID"
            if error_code == "STEP_RECEIPT_INVALID"
            else error_code
        ),
    )

    return {
        "step_id": expected_step_id,
        "receipt": {
            "path": receipt_relative,
            "sha256": file_sha256(receipt_path),
        },
        "work_order": expected_work_order,
        "attempt_id": receipt["attempt_id"],
        "source_sha256": expected_source_sha256,
        "dependency_receipts": dict(expected_dependencies),
        "artifacts": normalized_artifacts,
    }


_HOST_REVIEW_RUNTIME: Any | None = None


def _load_host_review_runtime() -> Any:
    global _HOST_REVIEW_RUNTIME
    if _HOST_REVIEW_RUNTIME is not None:
        return _HOST_REVIEW_RUNTIME
    path = Path(__file__).resolve().parent / "codex_exec_host.py"
    if not path.is_file() or path.is_symlink():
        fail("PHASE_PAYLOAD_INVALID", "host review runtime is unavailable")
    spec = importlib.util.spec_from_file_location("sffs_loop_host_review", path)
    if spec is None or spec.loader is None:
        fail("PHASE_PAYLOAD_INVALID", "host review runtime cannot be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    _HOST_REVIEW_RUNTIME = module
    return module


def _validated_phase_review_pair(
    repo_root: Path,
    references: Any,
    *,
    source_sha256: str,
    error_code: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if not isinstance(references, list) or len(references) != 2:
        fail(error_code, "review phase requires exactly two host attestations")
    expected_types = ("p0_zero", "reproducible_p1_zero")
    reports: dict[str, dict[str, Any]] = {}
    host = _load_host_review_runtime()
    for reference in references:
        if (
            not isinstance(reference, dict)
            or set(reference) != {"attestation_type", "path", "sha256"}
            or reference.get("attestation_type") not in expected_types
            or not _is_sha256(reference.get("sha256"))
        ):
            fail(error_code, "review attestation reference is malformed")
        attestation_type = reference["attestation_type"]
        if attestation_type in reports:
            fail(error_code, "review attestation types must be unique")
        try:
            report_path, _ = resolve_repo_path(
                repo_root,
                reference.get("path"),
                outside_code=error_code,
                require_file=True,
            )
        except LoopError:
            raise
        if file_sha256(report_path) != reference["sha256"]:
            fail(error_code, "review attestation hash does not match its bytes")
        report = read_object(report_path, error_code, "review attestation")
        host_reference = report.get("host_execution_receipt")
        if not isinstance(host_reference, dict) or not isinstance(
            host_reference.get("path"), str
        ):
            fail(error_code, "review attestation lacks host execution evidence")
        try:
            expected = host.derive_review_attestation(
                receipt_path=repo_root / host_reference["path"],
                repo_root=repo_root,
                attestation_type=attestation_type,
                source_sha256=source_sha256,
                verify_source_files=error_code != "STATE_EVIDENCE_INVALID",
            )
        except (OSError, RuntimeError, ValueError) as exc:
            fail(error_code, f"review host attestation is invalid: {exc}")
        if report != expected:
            fail(error_code, "review attestation is not derived from its host receipt")
        reports[attestation_type] = report
    if set(reports) != set(expected_types):
        fail(error_code, "review phase requires both fixed attestation types")
    p0 = reports["p0_zero"]
    p1 = reports["reproducible_p1_zero"]
    if (
        p0["reviewer_id"] == p1["reviewer_id"]
        or p0["execution_id"] == p1["execution_id"]
        or p0["host_execution_receipt"] == p1["host_execution_receipt"]
        or p0["review_artifact"] == p1["review_artifact"]
        or {
            item["finding_id"]: canonical_sha256(item)
            for item in p0["findings"]
        }
        != {
            item["finding_id"]: canonical_sha256(item)
            for item in p1["findings"]
        }
    ):
        fail(error_code, "review attestations are reused or disagree on findings")
    return p0, p1


def validate_phase_payload(
    repo_root: Path,
    state: dict[str, Any],
    iteration: dict[str, Any],
    receipt: dict[str, Any],
    artifacts: list[dict[str, str]],
    *,
    error_code: str,
) -> None:
    """Validate the phase-specific primary evidence behind a generic envelope."""
    step_id = receipt["step_id"]
    expected_role = PHASE_PRIMARY_ROLES.get(step_id)
    if expected_role is None:
        return
    primary = [item for item in artifacts if item["role"] == expected_role]
    if len(primary) != 1:
        fail(error_code, f"{step_id} requires exactly one {expected_role} artifact")
    primary_path, _ = resolve_repo_path(
        repo_root,
        primary[0]["path"],
        outside_code=error_code,
        require_file=True,
    )
    payload = read_object(primary_path, error_code, f"{step_id} phase payload")
    if (
        set(payload)
        != {
            "schema_version",
            "evidence_type",
            "controller_run_id",
            "iteration_id",
            "source_sha256",
            "result",
        }
        or payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("evidence_type") != f"{step_id}.v1"
        or payload.get("controller_run_id") != state["controller_run_id"]
        or payload.get("iteration_id") != iteration["iteration_id"]
        or payload.get("source_sha256") != receipt["source_sha256"]
        or not isinstance(payload.get("result"), dict)
    ):
        fail(error_code, f"{step_id} phase payload identity is malformed or stale")
    result = payload["result"]
    events = receipt["finding_events"]

    if step_id == "preflight_snapshot":
        expected_keys = {
            "source_file_count",
            "source_manifest_sha256",
            "workflow_sha256",
            "controller_sha256",
            "tests_root",
            "protected_changes",
            "denied_operations",
        }
        tests_root = result.get("tests_root")
        controller_path = state["workflow_policy"]["controller_executable"]
        valid = (
            set(result) == expected_keys
            and result.get("source_file_count") == len(state["source_files"])
            and result.get("source_manifest_sha256")
            == state["source_manifest"]["sha256"]
            and result.get("workflow_sha256") == state["workflow"]["sha256"]
            and result.get("controller_sha256")
            == state["source_snapshot"]["files"].get(controller_path)
            and isinstance(tests_root, str)
            and (repo_root / tests_root).is_dir()
            and result.get("protected_changes") == []
            and result.get("denied_operations")
            == sorted(state["workflow_policy"]["denied_operations"])
        )
    elif step_id in {"adversarial_review", "independent_recheck"}:
        expected_keys = {
            "review_attestations",
            "reviewer_ids",
            "execution_ids",
            "raw_artifact_sha256s",
            "finding_ids",
            "trust_boundary",
        }
        action = "open" if step_id == "adversarial_review" else "close"
        raw_event_ids = [
            event.get("finding_id")
            for event in events
            if event.get("action") == action
        ]
        event_ids = (
            sorted(raw_event_ids)
            if all(isinstance(item, str) and item for item in raw_event_ids)
            else None
        )
        reviewer_ids = result.get("reviewer_ids")
        execution_ids = result.get("execution_ids")
        raw_hashes = result.get("raw_artifact_sha256s")
        p0_report, p1_report = _validated_phase_review_pair(
            repo_root,
            result.get("review_attestations"),
            source_sha256=receipt["source_sha256"],
            error_code=error_code,
        )
        derived_reviewer_ids = [
            p0_report["reviewer_id"],
            p1_report["reviewer_id"],
        ]
        derived_execution_ids = [
            p0_report["execution_id"],
            p1_report["execution_id"],
        ]
        derived_raw_hashes = [
            p0_report["review_artifact"]["sha256"],
            p1_report["review_artifact"]["sha256"],
        ]
        reported_findings = p0_report["findings"]
        reported_finding_ids = sorted(item["finding_id"] for item in reported_findings)
        projected_open_events = {
            item["finding_id"]: canonical_sha256(
                {
                    "action": "open",
                    "finding_id": item["finding_id"],
                    "severity": item["severity"],
                    "summary": item["summary"],
                    "reproducer": item["reproducer"],
                    "actual": item["actual"],
                    "expected": item["expected"],
                }
            )
            for item in reported_findings
        }
        observed_open_events = {
            item.get("finding_id"): canonical_sha256(item)
            for item in events
            if item.get("action") == "open"
            and isinstance(item.get("finding_id"), str)
        }
        review_finding_contract_valid = (
            all(
                item.get("status") == "open"
                and item.get("reproducible") is True
                for item in reported_findings
            )
            and (
                reported_finding_ids == event_ids
                and projected_open_events == observed_open_events
                if step_id == "adversarial_review"
                else reported_findings == []
            )
        )
        valid = (
            set(result) == expected_keys
            and isinstance(reviewer_ids, list)
            and len(reviewer_ids) == 2
            and all(isinstance(item, str) and item for item in reviewer_ids)
            and len(set(reviewer_ids)) == 2
            and isinstance(execution_ids, list)
            and len(execution_ids) == 2
            and all(isinstance(item, str) and item for item in execution_ids)
            and len(set(execution_ids)) == 2
            and isinstance(raw_hashes, list)
            and len(raw_hashes) == 2
            and all(_is_sha256(item) for item in raw_hashes)
            and len(set(raw_hashes)) == 2
            and reviewer_ids == derived_reviewer_ids
            and execution_ids == derived_execution_ids
            and raw_hashes == derived_raw_hashes
            and result.get("finding_ids") == event_ids
            and result.get("trust_boundary") == REVIEW_TRUST_BOUNDARY
            and review_finding_contract_valid
        )
    elif step_id == "red_green_fix":
        expected_keys = {
            "before_source_sha256",
            "red_source_sha256",
            "after_source_sha256",
            "fixed_finding_ids",
            "full_regression",
        }
        raw_fixed_ids = [
            event.get("finding_id")
            for event in events
            if event.get("action") == "fix_claimed"
        ]
        fixed_ids = (
            sorted(raw_fixed_ids)
            if all(isinstance(item, str) and item for item in raw_fixed_ids)
            else None
        )
        regression = result.get("full_regression")
        pending_epoch = iteration.get("pending_source_epoch")
        committed_epoch = iteration.get("source_epoch")
        source_epoch = (
            pending_epoch
            if isinstance(pending_epoch, dict)
            else committed_epoch
            if isinstance(committed_epoch, dict)
            else None
        )
        expected_before = (
            source_epoch["source_before_sha256"]
            if isinstance(source_epoch, dict)
            else receipt["source_sha256"]
        )
        expected_after = (
            source_epoch["source_after_sha256"]
            if isinstance(source_epoch, dict)
            else receipt["source_sha256"]
        )
        expected_red = (
            source_epoch["red_source_sha256"]
            if isinstance(source_epoch, dict)
            else receipt["source_sha256"]
        )
        if (
            isinstance(source_epoch, dict)
            and fixed_ids != source_epoch["finding_ids"]
        ):
            fail(
                "SOURCE_EPOCH_FINDING_MISMATCH"
                if error_code == "STEP_RECEIPT_INVALID"
                else error_code,
                "fix events must cover exactly the findings bound by the source epoch",
            )
        valid = (
            set(result) == expected_keys
            and result.get("before_source_sha256") == expected_before
            and result.get("red_source_sha256") == expected_red
            and result.get("after_source_sha256") == expected_after
            and result.get("fixed_finding_ids") == fixed_ids
            and isinstance(regression, dict)
            and set(regression)
            == {"tests_run", "failures", "errors", "skipped", "exit_code"}
            and type(regression.get("tests_run")) is int
            and regression["tests_run"] > 0
            and regression.get("failures") == 0
            and regression.get("errors") == 0
            and regression.get("skipped") == 0
            and regression.get("exit_code") == 0
        )
    elif step_id == "deterministic_gate":
        expected_names = [
            "unit_tests",
            "self_test",
            "markdown_links",
            "workflow_lifecycle",
        ]
        commands = result.get("commands")
        valid = (
            set(result) == {"commands"}
            and isinstance(commands, list)
            and [item.get("name") for item in commands if isinstance(item, dict)]
            == expected_names
            and all(
                set(item)
                == {"name", "exit_code", "tests_run", "failures", "errors", "skipped"}
                and item["exit_code"] == 0
                and type(item["tests_run"]) is int
                and item["tests_run"] > 0
                and item["failures"] == 0
                and item["errors"] == 0
                and item["skipped"] == 0
                for item in commands
            )
        )
    elif step_id == "source_freeze":
        open_ids = sorted(
            finding_id
            for finding_id, item in state["finding_ledger"].items()
            if item["status"] == "open"
        )
        valid = (
            set(result)
            == {
                "source_sha256",
                "source_file_count",
                "source_manifest_sha256",
                "open_finding_ids",
            }
            and result.get("source_sha256") == receipt["source_sha256"]
            and result.get("source_file_count") == len(state["source_files"])
            and result.get("source_manifest_sha256")
            == state["source_manifest"]["sha256"]
            and result.get("open_finding_ids") == open_ids == []
        )
    elif step_id == "frozen_eval_prepare":
        valid = (
            set(result)
            == {
                "root_was_absent",
                "case_count",
                "output_count",
                "suite_sha256",
                "evaluation_context_sha256",
            }
            and result.get("root_was_absent") is True
            and result.get("case_count") == 18
            and result.get("output_count") == 0
            and _is_sha256(result.get("suite_sha256"))
            and _is_sha256(result.get("evaluation_context_sha256"))
        )
    elif step_id == "isolated_eval":
        runner_ids = result.get("runner_ids")
        execution_ids = result.get("execution_ids")
        valid = (
            set(result)
            == {"case_count", "runner_ids", "execution_ids", "trust_boundary"}
            and result.get("case_count") == 18
            and isinstance(runner_ids, list)
            and len(runner_ids) == 18
            and all(isinstance(item, str) and item for item in runner_ids)
            and len(set(runner_ids)) == 18
            and isinstance(execution_ids, list)
            and len(execution_ids) == 18
            and all(isinstance(item, str) and item for item in execution_ids)
            and len(set(execution_ids)) == 18
            and result.get("trust_boundary")
            == "external_dispatch_attestation_not_isolation_proof"
        )
    elif step_id == "eval_audit":
        valid = (
            set(result)
            == {"valid", "case_count", "artifact_count", "missing", "suite_errors"}
            and result.get("valid") is True
            and result.get("case_count") == 18
            and result.get("artifact_count") == 16
            and result.get("missing") == []
            and result.get("suite_errors") == []
        )
    else:
        valid = False
    if not valid:
        fail(error_code, f"{step_id} phase payload does not prove its contract")


def validate_persisted_step_evidence(
    repo_root: Path,
    state: dict[str, Any],
    *,
    frozen_source_root: Path | None = None,
) -> None:
    if state["workflow_policy"].get("execution_mode") != EXECUTION_MODE_GRAPH:
        return
    for iteration in state["iterations"]:
        for key in ("pending_source_epoch", "source_epoch"):
            record = iteration.get(key)
            if record is None:
                continue
            try:
                rebuilt = read_source_epoch_plan(
                    repo_root,
                    state,
                    iteration,
                    record["plan"]["path"],
                    require_live_before=False,
                    error_code="STATE_EVIDENCE_INVALID",
                )
            except LoopError as exc:
                if exc.code == "STATE_EVIDENCE_INVALID":
                    raise
                fail(
                    "STATE_EVIDENCE_INVALID",
                    f"persisted source epoch is invalid: {exc.code}: {exc.message}",
                )
            if rebuilt != record:
                fail(
                    "STATE_EVIDENCE_INVALID",
                    "persisted source epoch differs from its plan and blobs",
                )
    dependencies = execution_dependencies(state["workflow_policy"])
    for iteration in state["iterations"]:
        accepted: dict[str, str] = {}
        active_source_sha256 = iteration["source_sha256"]
        for entry in iteration["step_ledger"]:
            step_id = entry["step_id"]
            work_order_source_sha256 = active_source_sha256
            if step_id == "red_green_fix" and isinstance(
                iteration.get("source_epoch"), dict
            ):
                epoch = iteration["source_epoch"]
                if epoch.get("source_before_sha256") != active_source_sha256:
                    fail(
                        "STATE_EVIDENCE_INVALID",
                        "source epoch does not continue the prior phase source",
                    )
                expected_source_sha256 = epoch.get("source_after_sha256")
            else:
                expected_source_sha256 = active_source_sha256
            expected_dependencies = {
                dependency: accepted[dependency]
                for dependency in dependencies[step_id]
            }
            try:
                receipt_path, receipt_relative = _phase_receipt_path(
                    repo_root,
                    state,
                    entry["receipt"]["path"],
                    error_code="STATE_EVIDENCE_INVALID",
                )
                if file_sha256(receipt_path) != entry["receipt"]["sha256"]:
                    fail(
                        "STATE_EVIDENCE_INVALID",
                        f"phase receipt hash mismatch: {receipt_relative}",
                    )
                receipt = read_object(
                    receipt_path,
                    "STATE_EVIDENCE_INVALID",
                    "persisted phase receipt",
                )
                rebuilt = validate_phase_receipt(
                    repo_root,
                    state,
                    iteration,
                    receipt_path=receipt_path,
                    receipt_relative=receipt_relative,
                    receipt=receipt,
                    expected_step_id=step_id,
                    expected_dependencies=expected_dependencies,
                    expected_work_order=entry["work_order"],
                    expected_source_sha256=expected_source_sha256,
                    expected_work_order_source_sha256=work_order_source_sha256,
                    error_code="STATE_EVIDENCE_INVALID",
                    frozen_source_root=frozen_source_root,
                )
            except LoopError as exc:
                if exc.code == "STATE_EVIDENCE_INVALID":
                    raise
                fail(
                    "STATE_EVIDENCE_INVALID",
                    f"persisted phase evidence is invalid: {exc.code}: {exc.message}",
                )
            if rebuilt != entry:
                fail(
                    "STATE_EVIDENCE_INVALID",
                    f"persisted phase ledger differs from receipt: {receipt_relative}",
                )
            accepted[step_id] = entry["receipt"]["sha256"]
            active_source_sha256 = expected_source_sha256
        if active_source_sha256 != iteration["active_source_sha256"]:
            fail(
                "STATE_EVIDENCE_INVALID",
                "phase source epochs do not reach the iteration active source",
            )
        active = iteration.get("active_work_order")
        if active is not None:
            expected_dependencies = {
                dependency: accepted[dependency]
                for dependency in dependencies[iteration["next_step"]]
            }
            rebuilt = validate_phase_work_order(
                repo_root,
                state,
                iteration,
                {"path": active["path"], "sha256": active["sha256"]},
                expected_step_id=iteration["next_step"],
                expected_source_sha256=state["source_snapshot"]["sha256"],
                expected_dependencies=expected_dependencies,
                error_code="STATE_EVIDENCE_INVALID",
            )
            if (
                rebuilt["document"]["attempt_id"] != active["attempt_id"]
                or rebuilt["document"]["step_id"] != active["step_id"]
            ):
                fail(
                    "STATE_EVIDENCE_INVALID",
                    "active work order differs from its persisted reference",
                )


def validate_finding_ledger_shape(state: dict[str, Any]) -> None:
    ledger = state.get("finding_ledger")
    if not isinstance(ledger, dict):
        fail("STATE_INVALID", "finding_ledger must be an object")
    for finding_id, item in ledger.items():
        if (
            not isinstance(finding_id, str)
            or not finding_id
            or not isinstance(item, dict)
            or set(item)
            != {
                "finding",
                "status",
                "opened_round",
                "opened_by",
                "red_test",
                "superseded_fixes",
                "fix",
                "closure",
            }
        ):
            fail("STATE_INVALID", "finding ledger entry is malformed")
        finding = item.get("finding")
        opened_by = item.get("opened_by")
        if (
            not isinstance(finding, dict)
            or set(finding) != set(FINDING_FIELDS)
            or finding.get("finding_id") != finding_id
            or any(
                not isinstance(finding.get(key), str) or not finding[key].strip()
                for key in FINDING_FIELDS
            )
            or finding.get("severity") not in {"P0", "P1"}
            or item.get("status") not in {"open", "closed"}
            or type(item.get("opened_round")) is not int
            or not 1 <= item["opened_round"] <= state["current_round"]
            or not isinstance(opened_by, dict)
            or set(opened_by) != {"kind", "evidence_sha256"}
            or opened_by.get("kind")
            not in {"gate", "review_receipt", "source_drift"}
            or not _is_sha256(opened_by.get("evidence_sha256"))
            or (
                opened_by.get("kind") == "review_receipt"
                and finding_id.startswith(CONTROLLER_FINDING_PREFIXES)
            )
        ):
            fail("STATE_INVALID", "finding identity or opening evidence is malformed")
        red_test = item.get("red_test")
        if red_test is not None and (
            not isinstance(red_test, dict)
            or set(red_test) != {"path", "sha256"}
            or not isinstance(red_test.get("path"), str)
            or not _is_sha256(red_test.get("sha256"))
        ):
            fail("STATE_INVALID", "finding red_test is malformed")
        superseded_fixes = item.get("superseded_fixes")
        if not isinstance(superseded_fixes, list):
            fail("STATE_INVALID", "finding superseded_fixes must be an array")
        for key in ("fix", "closure"):
            value = item.get(key)
            if value is None:
                continue
            required = {
                "round",
                "receipt_sha256",
                "event_sha256",
                "execution_id",
                "actor_id",
            }
            if key == "fix":
                required |= {"red_execution_id", "green_execution_id"}
            if key == "closure":
                required |= {"disposition", "recheck_execution_id"}
            if (
                not isinstance(value, dict)
                or set(value) != required
                or type(value.get("round")) is not int
                or not 1 <= value["round"] <= state["current_round"]
                or not _is_sha256(value.get("receipt_sha256"))
                or not _is_sha256(value.get("event_sha256"))
                or not isinstance(value.get("execution_id"), str)
                or not value["execution_id"]
                or not isinstance(value.get("actor_id"), str)
                or not value["actor_id"]
                or (
                    key == "fix"
                    and (
                        not isinstance(value.get("red_execution_id"), str)
                        or not value["red_execution_id"]
                        or not isinstance(value.get("green_execution_id"), str)
                        or not value["green_execution_id"]
                        or value["red_execution_id"]
                        == value["green_execution_id"]
                    )
                )
                or (
                    key == "closure"
                    and (
                        value.get("disposition") != "not_reproduced"
                        or not isinstance(value.get("recheck_execution_id"), str)
                        or not value["recheck_execution_id"]
                    )
                )
            ):
                fail("STATE_INVALID", f"finding {key} evidence is malformed")
        seen_superseded_events: set[str] = set()
        for value in superseded_fixes:
            required = {
                "round",
                "receipt_sha256",
                "event_sha256",
                "execution_id",
                "actor_id",
                "red_execution_id",
                "green_execution_id",
                "superseded_round",
                "superseded_by_source_sha256",
            }
            if (
                not isinstance(value, dict)
                or set(value) != required
                or type(value.get("round")) is not int
                or type(value.get("superseded_round")) is not int
                or not 1 <= value["round"] <= value["superseded_round"] <= state["current_round"]
                or not _is_sha256(value.get("receipt_sha256"))
                or not _is_sha256(value.get("event_sha256"))
                or value["event_sha256"] in seen_superseded_events
                or not _is_sha256(value.get("superseded_by_source_sha256"))
                or not isinstance(value.get("execution_id"), str)
                or not value["execution_id"]
                or not isinstance(value.get("actor_id"), str)
                or not value["actor_id"]
                or not isinstance(value.get("red_execution_id"), str)
                or not value["red_execution_id"]
                or not isinstance(value.get("green_execution_id"), str)
                or not value["green_execution_id"]
                or value["red_execution_id"] == value["green_execution_id"]
            ):
                fail("STATE_INVALID", "superseded finding fix is malformed")
            seen_superseded_events.add(value["event_sha256"])
        if item["status"] == "open" and item.get("closure") is not None:
            fail("STATE_INVALID", "open finding cannot contain closure evidence")
        if item["status"] == "closed" and (
            item.get("fix") is None or item.get("closure") is None
        ):
            fail("STATE_INVALID", "closed finding lacks fix or recheck evidence")


def _artifact_reference(
    event_value: Any,
    artifacts: list[dict[str, str]],
    *,
    with_exit_code: bool,
) -> dict[str, Any]:
    expected = {"path", "sha256", "exit_code"} if with_exit_code else {"path", "sha256"}
    if (
        not isinstance(event_value, dict)
        or set(event_value) != expected
        or not isinstance(event_value.get("path"), str)
        or not _is_sha256(event_value.get("sha256"))
        or (
            with_exit_code
            and type(event_value.get("exit_code")) is not int
        )
    ):
        fail("FINDING_CLOSURE_INVALID", "finding event artifact reference is malformed")
    if not any(
        artifact["path"] == event_value["path"]
        and artifact["sha256"] == event_value["sha256"]
        for artifact in artifacts
    ):
        fail(
            "FINDING_CLOSURE_INVALID",
            "finding event references an artifact outside its phase receipt",
        )
    return dict(event_value)


def _command_execution_receipt(
    state: dict[str, Any],
    *,
    phase_receipt: dict[str, Any],
    event_value: Any,
    finding_id: str,
    expected_role: str,
    expected_source_sha256: str,
    expected_red_test: dict[str, str],
    expected_causal_parent: dict[str, str],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Read and semantically validate one command result artifact.

    The finding event carries only a content-addressed reference.  Exit codes
    and test counts are derived from this typed artifact and never from the
    event that requests a ledger mutation.
    """
    reference = _artifact_reference(
        event_value,
        phase_receipt["artifacts"],
        with_exit_code=False,
    )
    descriptor = next(
        (
            artifact
            for artifact in phase_receipt["artifacts"]
            if artifact["path"] == reference["path"]
            and artifact["sha256"] == reference["sha256"]
        ),
        None,
    )
    if not isinstance(descriptor, dict) or descriptor.get("role") != expected_role:
        fail(
            "FINDING_CLOSURE_INVALID",
            f"{expected_role} must reference an artifact with the same role",
        )
    repo_root = Path(state["repo_root"])
    artifact_path, artifact_relative = resolve_repo_path(
        repo_root,
        reference["path"],
        outside_code="FINDING_CLOSURE_INVALID",
        require_file=True,
    )
    if artifact_relative != reference["path"] or file_sha256(artifact_path) != reference[
        "sha256"
    ]:
        fail("FINDING_CLOSURE_INVALID", "command receipt identity changed")
    command_receipt = read_object(
        artifact_path,
        "FINDING_CLOSURE_INVALID",
        f"{expected_role} command receipt",
    )
    required_fields = {
        "schema_version",
        "receipt_type",
        "controller_run_id",
        "iteration_id",
        "source_sha256",
        "phase_step_id",
        "phase_execution_id",
        "finding_id",
        "role",
        "execution_id",
        "red_test",
        "causal_parent",
        "command",
        "result",
        "producer",
    }
    iteration = state["iterations"][-1]
    producer = command_receipt.get("producer")
    phase_producer = phase_receipt["producer"]
    if (
        set(command_receipt) != required_fields
        or command_receipt.get("schema_version") != SCHEMA_VERSION
        or command_receipt.get("receipt_type") != COMMAND_EXECUTION_RECEIPT_TYPE
        or command_receipt.get("controller_run_id") != state["controller_run_id"]
        or command_receipt.get("iteration_id") != iteration["iteration_id"]
        or command_receipt.get("source_sha256") != expected_source_sha256
        or command_receipt.get("phase_step_id") != phase_receipt["step_id"]
        or command_receipt.get("phase_execution_id")
        != phase_producer["execution_id"]
        or command_receipt.get("finding_id") != finding_id
        or command_receipt.get("role") != expected_role
        or not isinstance(command_receipt.get("execution_id"), str)
        or not command_receipt["execution_id"].strip()
        or command_receipt.get("red_test") != expected_red_test
        or command_receipt.get("causal_parent") != expected_causal_parent
        or not isinstance(producer, dict)
        or set(producer) != {"actor_id", "trust_boundary"}
        or producer.get("actor_id") != phase_producer["actor_id"]
        or producer.get("trust_boundary") != COMMAND_EXECUTION_TRUST_BOUNDARY
    ):
        fail(
            "FINDING_CLOSURE_INVALID",
            f"{expected_role} command receipt is stale, unbound, or malformed",
        )

    command = command_receipt.get("command")
    if (
        not isinstance(command, dict)
        or set(command) != {"argv", "cwd", "shell", "timeout_seconds"}
        or not isinstance(command.get("argv"), list)
        or not command["argv"]
        or any(not isinstance(item, str) or not item for item in command["argv"])
        or expected_red_test["path"] not in command["argv"]
        or command.get("cwd") != str(repo_root.resolve())
        or command.get("shell") is not False
        or type(command.get("timeout_seconds")) is not int
        or not 1 <= command["timeout_seconds"] <= PRODUCER_TIMEOUT_SECONDS
    ):
        fail(
            "FINDING_CLOSURE_INVALID",
            f"{expected_role} command invocation is not bound to the frozen RED test",
        )

    result = command_receipt.get("result")
    if (
        not isinstance(result, dict)
        or set(result)
        != {
            "ran",
            "timed_out",
            "exit_code",
            "tests_run",
            "failures",
            "errors",
            "skipped",
            "classification",
        }
        or result.get("ran") is not True
        or result.get("timed_out") is not False
        or type(result.get("exit_code")) is not int
        or any(
            type(result.get(key)) is not int or result[key] < 0
            for key in ("tests_run", "failures", "errors", "skipped")
        )
        or result["tests_run"] < 1
        or result["failures"] + result["errors"] + result["skipped"]
        > result["tests_run"]
    ):
        fail(
            "FINDING_CLOSURE_INVALID",
            f"{expected_role} command result is malformed or did not run tests",
        )
    expected_classification = {
        "red_run": "expected_failure_reproduced",
        "green_run": "passed",
        "independent_recheck": "not_reproduced",
    }[expected_role]
    if expected_role == "red_run":
        valid_result = (
            result["exit_code"] != 0
            and result["failures"] >= 1
            and result["errors"] == 0
            and result["classification"] == expected_classification
        )
    else:
        valid_result = (
            result["exit_code"] == 0
            and result["failures"] == 0
            and result["errors"] == 0
            and result["classification"] == expected_classification
        )
    if not valid_result:
        fail(
            "FINDING_CLOSURE_INVALID",
            f"{expected_role} command result does not prove the required outcome",
        )
    return command_receipt, reference


def apply_finding_events(
    state: dict[str, Any],
    *,
    step_id: str,
    receipt: dict[str, Any],
    receipt_sha256: str,
) -> None:
    events = receipt["finding_events"]
    allowed_action = {
        "adversarial_review": "open",
        "red_green_fix": "fix_claimed",
        "independent_recheck": "close",
    }.get(step_id)
    if events and allowed_action is None:
        fail(
            "FINDING_EVENT_INVALID",
            f"{step_id} is not authorized to mutate the finding ledger",
        )
    ledger = state["finding_ledger"]
    current_round = state["current_round"]
    producer = receipt["producer"]
    artifacts = receipt["artifacts"]
    for event in events:
        if event.get("action") != allowed_action:
            fail(
                "FINDING_EVENT_INVALID",
                f"{step_id} may only record {allowed_action!r} finding events",
            )
        finding_id = event.get("finding_id")
        if not isinstance(finding_id, str) or not finding_id:
            fail("FINDING_EVENT_INVALID", "finding event lacks finding_id")
        if allowed_action == "open":
            if set(event) != {"action", *FINDING_FIELDS}:
                fail("FINDING_EVENT_INVALID", "finding open event is malformed")
            finding = {key: event[key] for key in FINDING_FIELDS}
            if (
                any(not isinstance(value, str) or not value.strip() for value in finding.values())
                or finding["severity"] not in {"P0", "P1"}
                or finding_id in ledger
                or finding_id.startswith(CONTROLLER_FINDING_PREFIXES)
            ):
                fail("FINDING_EVENT_INVALID", "finding open event is invalid or duplicated")
            ledger[finding_id] = {
                "finding": finding,
                "status": "open",
                "opened_round": current_round,
                "opened_by": {
                    "kind": "review_receipt",
                    "evidence_sha256": receipt_sha256,
                },
                "red_test": None,
                "superseded_fixes": [],
                "fix": None,
                "closure": None,
            }
            continue

        item = ledger.get(finding_id)
        if not isinstance(item, dict) or item.get("status") != "open":
            fail("FINDING_CLOSURE_INVALID", "finding is absent or is not open")
        if allowed_action == "fix_claimed":
            if set(event) != {
                "action",
                "finding_id",
                "red_test",
                "red_run",
                "green_run",
            }:
                fail("FINDING_CLOSURE_INVALID", "fix event is malformed")
            red_test = _artifact_reference(
                event["red_test"], artifacts, with_exit_code=False
            )
            source_epoch = state["iterations"][-1].get("source_epoch")
            if isinstance(source_epoch, dict):
                red_source_sha256 = source_epoch["red_source_sha256"]
                green_source_sha256 = source_epoch["source_after_sha256"]
            else:
                red_source_sha256 = state["iterations"][-1][
                    "active_source_sha256"
                ]
                green_source_sha256 = red_source_sha256
            red_run, red_run_reference = _command_execution_receipt(
                state,
                phase_receipt=receipt,
                event_value=event["red_run"],
                finding_id=finding_id,
                expected_role="red_run",
                expected_source_sha256=red_source_sha256,
                expected_red_test=red_test,
                expected_causal_parent={
                    "kind": "finding_opening",
                    "sha256": item["opened_by"]["evidence_sha256"],
                },
            )
            green_run, _ = _command_execution_receipt(
                state,
                phase_receipt=receipt,
                event_value=event["green_run"],
                finding_id=finding_id,
                expected_role="green_run",
                expected_source_sha256=green_source_sha256,
                expected_red_test=red_test,
                expected_causal_parent={
                    "kind": "red_run",
                    "sha256": red_run_reference["sha256"],
                },
            )
            if isinstance(source_epoch, dict):
                expected_epoch_red_test = next(
                    (
                        {
                            "path": binding["path"],
                            "sha256": binding["sha256"],
                        }
                        for binding in source_epoch["finding_red_tests"]
                        if binding["finding_id"] == finding_id
                    ),
                    None,
                )
                if red_test != expected_epoch_red_test:
                    fail(
                        "FINDING_CLOSURE_INVALID",
                        "fix event RED test differs from its source epoch binding",
                    )
            used_command_ids = {
                execution_id
                for ledger_item in ledger.values()
                for evidence_value in [
                    ledger_item.get("fix"),
                    ledger_item.get("closure"),
                    *ledger_item.get("superseded_fixes", []),
                ]
                if isinstance(evidence_value, dict)
                for execution_id in (
                    evidence_value.get("red_execution_id"),
                    evidence_value.get("green_execution_id"),
                    evidence_value.get("recheck_execution_id"),
                )
                if isinstance(execution_id, str)
            }
            if (
                red_test["path"] not in state["source_files"]
                or state["source_snapshot"]["files"].get(red_test["path"])
                != red_test["sha256"]
                or red_run["execution_id"] == green_run["execution_id"]
                or red_run["execution_id"] in used_command_ids
                or green_run["execution_id"] in used_command_ids
                or item.get("fix") is not None
                or (
                    item.get("red_test") is not None
                    and item["red_test"] != red_test
                )
            ):
                fail(
                    "FINDING_CLOSURE_INVALID",
                    "fix must bind one frozen RED test, a failing run, and a distinct passing run",
                )
            item["red_test"] = red_test
            item["fix"] = {
                "round": current_round,
                "receipt_sha256": receipt_sha256,
                "event_sha256": canonical_sha256(event),
                "execution_id": producer["execution_id"],
                "actor_id": producer["actor_id"],
                "red_execution_id": red_run["execution_id"],
                "green_execution_id": green_run["execution_id"],
            }
            continue

        if set(event) != {
            "action",
            "finding_id",
            "disposition",
            "recheck",
        }:
            fail("FINDING_CLOSURE_INVALID", "closure event is malformed")
        fix = item.get("fix")
        if not isinstance(fix, dict) or not isinstance(item.get("red_test"), dict):
            fail(
                "FINDING_CLOSURE_INVALID",
                "closure requires a recorded RED and GREEN fix",
            )
        recheck, _ = _command_execution_receipt(
            state,
            phase_receipt=receipt,
            event_value=event["recheck"],
            finding_id=finding_id,
            expected_role="independent_recheck",
            expected_source_sha256=state["iterations"][-1][
                "active_source_sha256"
            ],
            expected_red_test=item["red_test"],
            expected_causal_parent={
                "kind": "fix_event",
                "sha256": fix["event_sha256"],
            },
        )
        used_command_ids = {
            execution_id
            for ledger_item in ledger.values()
            for evidence_value in [
                ledger_item.get("fix"),
                ledger_item.get("closure"),
                *ledger_item.get("superseded_fixes", []),
            ]
            if isinstance(evidence_value, dict)
            for execution_id in (
                evidence_value.get("red_execution_id"),
                evidence_value.get("green_execution_id"),
                evidence_value.get("recheck_execution_id"),
            )
            if isinstance(execution_id, str)
        }
        if (
            event.get("disposition") != "not_reproduced"
            or producer["execution_id"] == fix["execution_id"]
            or producer["actor_id"] == fix["actor_id"]
            or recheck["execution_id"] in used_command_ids
        ):
            fail(
                "FINDING_CLOSURE_INVALID",
                "closure requires a distinct independent execution after RED and GREEN",
            )
        item["status"] = "closed"
        item["closure"] = {
            "round": current_round,
            "receipt_sha256": receipt_sha256,
            "event_sha256": canonical_sha256(event),
            "execution_id": producer["execution_id"],
            "actor_id": producer["actor_id"],
            "recheck_execution_id": recheck["execution_id"],
            "disposition": "not_reproduced",
        }


def supersede_open_fixes_for_source_drift(
    ledger: dict[str, dict[str, Any]],
    *,
    superseded_round: int,
    superseded_by_source_sha256: str,
) -> None:
    """Invalidate unclosed GREEN claims while retaining their immutable audit IDs."""
    for item in ledger.values():
        fix = item.get("fix")
        if item.get("status") != "open" or not isinstance(fix, dict):
            continue
        superseded = dict(fix)
        superseded["superseded_round"] = superseded_round
        superseded["superseded_by_source_sha256"] = superseded_by_source_sha256
        item["superseded_fixes"].append(superseded)
        item["fix"] = None


def validate_persisted_finding_evidence(
    repo_root: Path,
    state: dict[str, Any],
) -> None:
    if state["workflow_policy"].get("execution_mode") != EXECUTION_MODE_GRAPH:
        if state["finding_ledger"]:
            fail(
                "STATE_EVIDENCE_INVALID",
                "legacy workflow cannot persist a graph finding ledger",
            )
        return

    receipts: dict[str, dict[str, Any]] = {}
    for iteration in state["iterations"]:
        for entry in iteration["step_ledger"]:
            receipt_path, _ = _phase_receipt_path(
                repo_root,
                state,
                entry["receipt"]["path"],
                error_code="STATE_EVIDENCE_INVALID",
            )
            receipts[entry["receipt"]["sha256"]] = read_object(
                receipt_path,
                "STATE_EVIDENCE_INVALID",
                "finding phase receipt",
            )

    projected: dict[str, dict[str, Any]] = {}
    for index, iteration in enumerate(state["iterations"]):
        round_number = iteration["round"]
        expected_carried = sorted(
            finding_id
            for finding_id, item in projected.items()
            if item["status"] == "open"
        )
        if iteration["carried_findings"] != expected_carried:
            fail(
                "STATE_EVIDENCE_INVALID",
                f"round {round_number} carried findings differ from replayed history",
            )

        replay_state = {
            "controller_run_id": state["controller_run_id"],
            "repo_root": state["repo_root"],
            "current_round": round_number,
            "source_files": state["source_files"],
            "source_snapshot": {
                "sha256": iteration["active_source_sha256"],
                "files": state["source_snapshot"]["files"],
            },
            "iterations": [iteration],
            "finding_ledger": projected,
        }
        for entry in iteration["step_ledger"]:
            receipt = receipts.get(entry["receipt"]["sha256"])
            if receipt is None:
                fail(
                    "STATE_EVIDENCE_INVALID",
                    f"finding event receipt is missing: {entry['receipt']['path']}",
                )
            try:
                apply_finding_events(
                    replay_state,
                    step_id=entry["step_id"],
                    receipt=receipt,
                    receipt_sha256=entry["receipt"]["sha256"],
                )
            except LoopError as exc:
                fail(
                    "STATE_EVIDENCE_INVALID",
                    f"finding event replay failed: {exc.code}: {exc.message}",
                )

        if "decision" not in iteration:
            continue
        finding = iteration.get("finding")
        red_test = iteration.get("red_test")
        gate = iteration["gate_result"]
        if finding is None:
            if iteration["decision"] != "STOP" or red_test is not None:
                fail(
                    "STATE_EVIDENCE_INVALID",
                    f"round {round_number} terminal finding evidence is missing",
                )
            continue
        if (
            not isinstance(finding, dict)
            or set(finding) != set(FINDING_FIELDS)
            or any(
                not isinstance(finding.get(key), str) or not finding[key].strip()
                for key in FINDING_FIELDS
            )
            or finding["severity"] not in {"P0", "P1"}
            or finding["finding_id"] in projected
            or iteration["decision"] == "STOP"
        ):
            fail(
                "STATE_EVIDENCE_INVALID",
                f"round {round_number} terminal finding is malformed or duplicated",
            )

        if gate["code"] == "SOURCE_DRIFT_INVALIDATED_GATE":
            following = (
                state["iterations"][index + 1]
                if index + 1 < len(state["iterations"])
                else None
            )
            observed = state.get("observed_source_snapshot")
            expected_actual = (
                following["source_sha256"]
                if isinstance(following, dict)
                else observed.get("sha256")
                if isinstance(observed, dict)
                else None
            )
            if (
                red_test is not None
                or finding["finding_id"] != f"SOURCE-DRIFT-R{round_number:03d}"
                or finding["expected"] != iteration["active_source_sha256"]
                or finding["actual"] != expected_actual
                or gate["all_true"] is not False
            ):
                fail(
                    "STATE_EVIDENCE_INVALID",
                    f"round {round_number} source-drift finding is inconsistent",
                )
            supersede_open_fixes_for_source_drift(
                projected,
                superseded_round=round_number,
                superseded_by_source_sha256=expected_actual,
            )
            opened_by = {
                "kind": "source_drift",
                "evidence_sha256": canonical_sha256(
                    {
                        "before": finding["expected"],
                        "after": finding["actual"],
                    }
                ),
            }
        elif gate["code"] == "GATE_VALID":
            if (
                gate["valid"] is not True
                or gate["evidence_verified"] is not True
                or gate["all_true"] is not False
                or not isinstance(red_test, dict)
                or set(red_test) != {"path", "sha256"}
            ):
                fail(
                    "STATE_EVIDENCE_INVALID",
                    f"round {round_number} gate finding is inconsistent",
                )
            opened_by = {
                "kind": "gate",
                "evidence_sha256": gate["sha256"],
            }
        else:
            fail(
                "STATE_EVIDENCE_INVALID",
                f"round {round_number} uses an unknown finding source",
            )
        projected[finding["finding_id"]] = {
            "finding": finding,
            "status": "open",
            "opened_round": round_number,
            "opened_by": opened_by,
            "red_test": red_test,
            "superseded_fixes": [],
            "fix": None,
            "closure": None,
        }

    if projected != state["finding_ledger"]:
        fail(
            "STATE_EVIDENCE_INVALID",
            "persisted finding ledger differs from deterministic event replay",
        )


def json_pointer_value(document: Any, pointer: str) -> Any:
    if pointer == "":
        return document
    if not isinstance(pointer, str) or not pointer.startswith("/"):
        fail("GATE_EVIDENCE_INVALID", "evidence json_pointer must start with /")
    current = document
    for raw_part in pointer[1:].split("/"):
        part = raw_part.replace("~1", "/").replace("~0", "~")
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list) and part.isdigit() and int(part) < len(current):
            current = current[int(part)]
        else:
            fail("GATE_EVIDENCE_INVALID", f"json pointer does not exist: {pointer}")
    return current


def source_snapshot(repo_root: Path, source_files: list[str]) -> dict[str, Any]:
    files: dict[str, str] = {}
    for relative in source_files:
        path, normalized = resolve_repo_path(repo_root, relative, require_file=True)
        if normalized in files:
            fail("SOURCE_FILE_INVALID", f"duplicate source file: {normalized}")
        files[normalized] = file_sha256(path)
    if not files:
        fail("SOURCE_FILE_INVALID", "at least one source file is required")
    ordered = dict(sorted(files.items()))
    return {"sha256": canonical_sha256(ordered), "files": ordered}


def require_unchanged_source_manifest(
    repo_root: Path, state: dict[str, Any]
) -> None:
    identity = state["source_manifest"]
    path, _ = resolve_repo_path(
        repo_root,
        identity["path"],
        outside_code="SOURCE_MANIFEST_CHANGED",
        require_file=True,
    )
    if file_sha256(path) != identity["sha256"]:
        fail(
            "SOURCE_MANIFEST_CHANGED",
            "the authoritative release source manifest changed; start a fresh loop run",
        )


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_retained_tree(
    repo_root: Path,
    *,
    root_value: Any,
    index_value: Any,
    index_sha256: Any,
    expected_digest: Any,
    index_name: str,
    error_code: str,
) -> None:
    root, root_relative = resolve_repo_path(
        repo_root, root_value, outside_code=error_code, require_file=False
    )
    index, index_relative = resolve_repo_path(
        repo_root, index_value, outside_code=error_code, require_file=True
    )
    if (
        not root.is_dir()
        or root.is_symlink()
        or root.name != expected_digest
        or index != root / index_name
        or not _is_sha256(index_sha256)
        or file_sha256(index) != index_sha256
    ):
        fail(error_code, f"retained tree identity is invalid: {root_relative}")
    document = read_object(index, error_code, "retained snapshot index")
    files = document.get("files")
    if (
        document.get("sha256") != expected_digest
        or not isinstance(files, dict)
        or canonical_sha256(files) != expected_digest
    ):
        fail(error_code, f"retained tree index is invalid: {index_relative}")
    observed: set[str] = set()
    for path in root.rglob("*"):
        if path.is_symlink():
            fail(error_code, f"retained tree contains a symlink: {path}")
        if path.is_file() and path != index:
            relative = path.relative_to(root).as_posix()
            observed.add(relative)
            metadata = files.get(relative)
            if (
                path.stat().st_nlink != 1
                or not isinstance(metadata, dict)
                or metadata
                != {"sha256": file_sha256(path), "size": path.stat().st_size}
            ):
                fail(error_code, f"retained tree bytes changed: {relative}")
    if observed != set(files):
        fail(error_code, "retained tree file set differs from its index")


def validate_release_basis_reference(repo_root: Path, basis: Any) -> None:
    required = {
        "schema_version",
        "sha256",
        "root_path",
        "index_path",
        "index_sha256",
        "source_sha256",
        "canonical_install",
        "trust_boundary",
    }
    if (
        not isinstance(basis, dict)
        or set(basis) != required
        or basis.get("schema_version") != SCHEMA_VERSION
        or not _is_sha256(basis.get("sha256"))
        or not _is_sha256(basis.get("source_sha256"))
        or basis.get("trust_boundary")
        != "retained_local_snapshot_not_external_signature"
    ):
        fail("RELEASE_BASIS_INVALID", "release basis contract is malformed")
    _validate_retained_tree(
        repo_root,
        root_value=basis["root_path"],
        index_value=basis["index_path"],
        index_sha256=basis["index_sha256"],
        expected_digest=basis["sha256"],
        index_name="snapshot-index.json",
        error_code="RELEASE_BASIS_INVALID",
    )
    basis_index, _ = resolve_repo_path(
        repo_root,
        basis["index_path"],
        outside_code="RELEASE_BASIS_INVALID",
        require_file=True,
    )
    basis_document = read_object(
        basis_index, "RELEASE_BASIS_INVALID", "release basis index"
    )
    if basis_document.get("source_sha256") != basis["source_sha256"]:
        fail("RELEASE_BASIS_INVALID", "release basis source identity was relabelled")
    retained_source = {
        relative.removeprefix("source/"): metadata.get("sha256")
        for relative, metadata in basis_document.get("files", {}).items()
        if relative.startswith("source/") and isinstance(metadata, dict)
    }
    if canonical_sha256(dict(sorted(retained_source.items()))) != basis["source_sha256"]:
        fail("RELEASE_BASIS_INVALID", "retained source bytes do not match identity")
    install = basis["canonical_install"]
    if (
        not isinstance(install, dict)
        or set(install)
        != {
            "sha256",
            "root_path",
            "index_path",
            "index_sha256",
            "built_from",
            "source_basis_sha256",
        }
        or not _is_sha256(install.get("sha256"))
        or install.get("built_from") != "retained_source_snapshot"
        or install.get("source_basis_sha256") != basis.get("sha256")
    ):
        fail("RELEASE_BASIS_INVALID", "canonical install contract is malformed")
    _validate_retained_tree(
        repo_root,
        root_value=install["root_path"],
        index_value=install["index_path"],
        index_sha256=install["index_sha256"],
        expected_digest=install["sha256"],
        index_name="artifact-index.json",
        error_code="RELEASE_BASIS_INVALID",
    )


def validate_state_shape(state: dict[str, Any]) -> None:
    """Reject same-version partial or internally inconsistent state objects."""
    required = {
        "schema_version",
        "controller_run_id",
        "repo_root",
        "state_dir",
        "workflow",
        "workflow_policy",
        "source_manifest",
        "source_files",
        "allowed_write_roots",
        "max_rounds",
        "current_round",
        "status",
        "decision",
        "source_snapshot",
        "iterations",
        "finding_ledger",
    }
    if not required.issubset(state):
        fail("STATE_INVALID", "loop state is missing required fields")
    if state.get("schema_version") != SCHEMA_VERSION:
        fail("STATE_INVALID", "unsupported loop state schema")
    if (
        not isinstance(state.get("controller_run_id"), str)
        or re.fullmatch(r"run-[0-9a-f]{32}", state["controller_run_id"]) is None
    ):
        fail("STATE_INVALID", "controller_run_id is malformed")
    if not isinstance(state.get("repo_root"), str) or not state["repo_root"]:
        fail("STATE_INVALID", "repo_root is missing")
    if not isinstance(state.get("state_dir"), str) or not state["state_dir"]:
        fail("STATE_INVALID", "state_dir is missing")

    workflow = state.get("workflow")
    if (
        not isinstance(workflow, dict)
        or not isinstance(workflow.get("path"), str)
        or not workflow["path"]
        or not _is_sha256(workflow.get("sha256"))
    ):
        fail("STATE_INVALID", "workflow identity is malformed")

    workflow_policy = state.get("workflow_policy")
    if (
        not isinstance(workflow_policy, dict)
        or workflow_policy.get("schema_version") != SCHEMA_VERSION
        or not isinstance(workflow_policy.get("controller_executable"), str)
        or not workflow_policy["controller_executable"]
        or workflow_policy.get("stop_authority")
        not in {"legacy_external_gate", "controller_prove_stop"}
        or workflow_policy.get("execution_mode")
        not in {EXECUTION_MODE_LEGACY, EXECUTION_MODE_GRAPH}
        or (
            workflow_policy.get("stop_authority") == "controller_prove_stop"
            and workflow_policy.get("execution_mode") != EXECUTION_MODE_GRAPH
        )
        or (
            workflow_policy.get("stop_authority") == "legacy_external_gate"
            and workflow_policy.get("execution_mode") != EXECUTION_MODE_LEGACY
        )
        or (
            workflow_policy.get("stop_authority") == "controller_prove_stop"
            and (
                not isinstance(workflow_policy.get("gate_producer"), str)
                or not workflow_policy["gate_producer"]
            )
        )
        or not isinstance(workflow_policy.get("source_manifest"), str)
        or not workflow_policy["source_manifest"]
        or type(workflow_policy.get("max_rounds")) is not int
        or workflow_policy.get("required_gate_checks") != list(REQUIRED_GATE_CHECKS)
        or workflow_policy.get("back_edge") != REQUIRED_BACK_EDGE
        or workflow_policy.get("execution_graph")
        != [
            {"id": step_id, "depends_on": list(dependencies)}
            for step_id, dependencies in REQUIRED_EXECUTION_GRAPH
        ]
        or not isinstance(workflow_policy.get("allowed_write_roots"), list)
        or not workflow_policy["allowed_write_roots"]
        or not isinstance(workflow_policy.get("denied_operations"), list)
        or any(
            not isinstance(item, str) or not item
            for item in workflow_policy.get("denied_operations", [])
        )
        or not set(REQUIRED_DENIED_OPERATIONS).issubset(
            workflow_policy["denied_operations"]
        )
    ):
        fail("STATE_INVALID", "workflow policy is malformed")

    source_manifest = state.get("source_manifest")
    if (
        not isinstance(source_manifest, dict)
        or not isinstance(source_manifest.get("path"), str)
        or not source_manifest["path"]
        or not _is_sha256(source_manifest.get("sha256"))
        or source_manifest["path"] != workflow_policy["source_manifest"]
    ):
        fail("STATE_INVALID", "source manifest identity is malformed")

    source_files = state.get("source_files")
    if (
        not isinstance(source_files, list)
        or not source_files
        or any(not isinstance(item, str) or not item for item in source_files)
        or len(set(source_files)) != len(source_files)
        or source_files != sorted(source_files)
        or workflow["path"] not in source_files
        or workflow_policy["controller_executable"] not in source_files
        or source_manifest["path"] not in source_files
    ):
        fail("STATE_INVALID", "source_files are malformed or omit the workflow")

    allowed_roots = state.get("allowed_write_roots")
    if (
        not isinstance(allowed_roots, list)
        or not allowed_roots
        or any(not isinstance(item, str) or not item for item in allowed_roots)
        or len(set(allowed_roots)) != len(allowed_roots)
    ):
        fail("STATE_INVALID", "allowed_write_roots are malformed")

    max_rounds = state.get("max_rounds")
    current_round = state.get("current_round")
    if (
        type(max_rounds) is not int
        or not 1 <= max_rounds <= 100
        or max_rounds > workflow_policy["max_rounds"]
        or type(current_round) is not int
        or not 1 <= current_round <= max_rounds
    ):
        fail("STATE_INVALID", "round bounds are malformed")

    status = state.get("status")
    decision = state.get("decision")
    if status not in {"active", "completed", "blocked"}:
        fail("STATE_INVALID", "loop status is invalid")
    valid_decisions = {
        "active": {None, "LOOP"},
        "completed": {"STOP"},
        "blocked": {"BUDGET_EXHAUSTED"},
    }
    if decision not in valid_decisions[status]:
        fail("STATE_INVALID", "loop status and decision are inconsistent")
    validate_finding_ledger_shape(state)

    snapshot = state.get("source_snapshot")
    if not isinstance(snapshot, dict):
        fail("STATE_INVALID", "source_snapshot is malformed")
    files = snapshot.get("files")
    if (
        not isinstance(files, dict)
        or list(files) != sorted(files)
        or set(files) != set(source_files)
        or any(not isinstance(key, str) or not _is_sha256(value) for key, value in files.items())
        or not _is_sha256(snapshot.get("sha256"))
        or snapshot["sha256"] != canonical_sha256(files)
    ):
        fail("STATE_INVALID", "source_snapshot does not bind source_files")
    if files.get(workflow["path"]) != workflow["sha256"]:
        fail("STATE_INVALID", "workflow identity differs from the source snapshot")
    if files.get(source_manifest["path"]) != source_manifest["sha256"]:
        fail("STATE_INVALID", "source manifest identity differs from the source snapshot")

    observed_snapshot = state.get("observed_source_snapshot")
    if observed_snapshot is not None:
        observed_files = (
            observed_snapshot.get("files")
            if isinstance(observed_snapshot, dict)
            else None
        )
        if (
            (status, decision)
            not in {("blocked", "BUDGET_EXHAUSTED"), ("completed", "STOP")}
            or not isinstance(observed_files, dict)
            or list(observed_files) != sorted(observed_files)
            or set(observed_files) != set(source_files)
            or any(
                not isinstance(key, str) or not _is_sha256(value)
                for key, value in observed_files.items()
            )
            or not _is_sha256(observed_snapshot.get("sha256"))
            or observed_snapshot["sha256"] != canonical_sha256(observed_files)
        ):
            fail("STATE_INVALID", "observed_source_snapshot is malformed")

    iterations = state.get("iterations")
    if not isinstance(iterations, list) or not iterations:
        fail("STATE_INVALID", "iterations are missing")
    for index, iteration in enumerate(iterations, start=1):
        if (
            not isinstance(iteration, dict)
            or iteration.get("round") != index
            or not isinstance(iteration.get("iteration_id"), str)
            or not _is_sha256(iteration.get("source_sha256"))
            or not _is_sha256(iteration.get("active_source_sha256"))
            or iteration.get("iteration_id")
            != iteration_id(index, iteration["source_sha256"])
            or iteration.get("source_epoch") is not None
            and not isinstance(iteration.get("source_epoch"), dict)
            or iteration.get("pending_source_epoch") is not None
            and not isinstance(iteration.get("pending_source_epoch"), dict)
            or not isinstance(iteration.get("carried_findings"), list)
            or any(
                not isinstance(item, str) or not item
                for item in iteration["carried_findings"]
            )
        ):
            fail("STATE_INVALID", "iteration history is malformed")
        source_epoch = iteration.get("source_epoch")
        pending_source_epoch = iteration.get("pending_source_epoch")
        if source_epoch is not None:
            validate_source_epoch_record_shape(source_epoch)
        if pending_source_epoch is not None:
            validate_source_epoch_record_shape(pending_source_epoch)
        if source_epoch is not None and pending_source_epoch is not None:
            fail("STATE_INVALID", "source epoch cannot be pending and committed")
        if source_epoch is None and (
            iteration["active_source_sha256"] != iteration["source_sha256"]
        ):
            fail("STATE_INVALID", "iteration active source lacks a source epoch")
        if source_epoch is not None and (
            source_epoch["source_before_sha256"] != iteration["source_sha256"]
            or source_epoch["source_after_sha256"]
            != iteration["active_source_sha256"]
        ):
            fail("STATE_INVALID", "committed source epoch does not bind the iteration")
        if pending_source_epoch is not None and (
            pending_source_epoch["source_before_sha256"]
            != iteration["active_source_sha256"]
            or iteration.get("next_step") != "red_green_fix"
            or not isinstance(iteration.get("active_work_order"), dict)
            or pending_source_epoch["attempt_id"]
            != iteration["active_work_order"]["attempt_id"]
        ):
            fail("STATE_INVALID", "pending source epoch lacks its fix work order")
        validate_iteration_step_ledger_shape(iteration, workflow_policy)
    if len(iterations) != current_round or iterations[-1]["round"] != current_round:
        fail("STATE_INVALID", "current_round does not match iteration history")
    if iterations[-1]["active_source_sha256"] != snapshot["sha256"]:
        fail("STATE_INVALID", "current iteration does not bind source_snapshot")

    completed_count = len(iterations) if status != "active" else len(iterations) - 1
    for index, iteration in enumerate(iterations):
        is_completed_iteration = index < completed_count
        if not is_completed_iteration:
            if any(
                key in iteration
                for key in ("finding", "red_test", "gate_result", "decision")
            ):
                fail("STATE_INVALID", "active iteration contains a terminal decision")
            continue
        gate = iteration.get("gate_result")
        iteration_decision = iteration.get("decision")
        if (
            not isinstance(gate, dict)
            or not isinstance(gate.get("path"), str)
            or not _is_sha256(gate.get("sha256"))
            or not isinstance(gate.get("checks"), dict)
            or set(gate["checks"]) != set(REQUIRED_GATE_CHECKS)
            or any(type(gate["checks"].get(key)) is not bool for key in REQUIRED_GATE_CHECKS)
            or type(gate.get("valid")) is not bool
            or type(gate.get("all_true")) is not bool
            or type(gate.get("evidence_verified")) is not bool
            or not isinstance(gate.get("evidence"), dict)
            or not isinstance(gate.get("code"), str)
            or iteration_decision not in {"LOOP", "STOP", "BUDGET_EXHAUSTED"}
        ):
            fail("STATE_INVALID", "completed iteration lacks a bound gate decision")
        if iteration_decision == "STOP" and not (
            gate["valid"] is True
            and gate["all_true"] is True
            and gate["evidence_verified"] is True
            and gate["code"] == "GATE_VALID"
        ):
            fail("STATE_INVALID", "STOP is not backed by a verified all-true gate")
        if (
            iteration_decision == "STOP"
            and workflow_policy.get("execution_mode") == EXECUTION_MODE_GRAPH
            and len(iteration["step_ledger"]) != len(REQUIRED_EXECUTION_GRAPH)
        ):
            fail("STATE_INVALID", "graph STOP lacks a complete execution ledger")
        if (
            iteration_decision == "STOP"
            and workflow_policy.get("stop_authority") == "controller_prove_stop"
            and (
                not isinstance(gate.get("producer"), dict)
                or gate["producer"].get("authority") != "controller_prove_stop"
                or gate["producer"].get("recipe_version")
                != PRODUCER_RECIPE_VERSION
                or gate["producer"].get("script_path")
                != (
                    f"{gate.get('release_basis', {}).get('root_path', '')}/source/"
                    f"{workflow_policy.get('gate_producer')}"
                )
            )
        ):
            fail("STATE_INVALID", "STOP lacks controller-owned executable proof")
        if (
            iteration_decision == "STOP"
            and workflow_policy.get("stop_authority") == "controller_prove_stop"
        ):
            validate_release_basis_reference(Path(state["repo_root"]), gate.get("release_basis"))
        if iteration_decision != "STOP" and gate["all_true"] is True:
            fail("STATE_INVALID", "non-STOP iteration cannot retain an all-true gate")

    if status == "completed" and iterations[-1].get("decision") != "STOP":
        fail("STATE_INVALID", "completed loop does not end in STOP")
    if status == "completed" and state.get("release_basis") != iterations[-1][
        "gate_result"
    ].get("release_basis"):
        fail("STATE_INVALID", "completed STOP does not bind its retained release basis")
    if status == "blocked" and iterations[-1].get("decision") != "BUDGET_EXHAUSTED":
        fail("STATE_INVALID", "blocked loop lacks a budget-exhausted decision")


def iteration_id(round_number: int, source_hash: str) -> str:
    return f"r{round_number:03d}-{source_hash[:12]}"


def state_path(state_dir: Path) -> Path:
    return state_dir / STATE_FILE


def validate_current_workflow_policy(repo_root: Path, state: dict[str, Any]) -> None:
    try:
        workflow_path, _ = resolve_repo_path(
            repo_root,
            state["workflow"]["path"],
            outside_code="WORKFLOW_POLICY_CHANGED",
            require_file=True,
        )
        current_policy = parse_workflow_policy(workflow_path)
    except LoopError as exc:
        fail(
            "WORKFLOW_POLICY_CHANGED",
            f"current workflow policy cannot continue this run: {exc.code}: {exc.message}",
        )
    if current_policy != state["workflow_policy"]:
        fail(
            "WORKFLOW_POLICY_CHANGED",
            "material workflow policy drift requires a fresh loop run",
        )


def validate_persisted_red_tests(repo_root: Path, state: dict[str, Any]) -> None:
    frozen = set(state["source_files"])
    for iteration in state["iterations"]:
        red_test = iteration.get("red_test")
        if red_test is None:
            continue
        if (
            not isinstance(red_test, dict)
            or set(red_test) != {"path", "sha256"}
            or not isinstance(red_test.get("path"), str)
            or not _is_sha256(red_test.get("sha256"))
            or red_test["path"] not in frozen
        ):
            fail("STATE_EVIDENCE_INVALID", "historical red test is not frozen")
        try:
            path, relative = resolve_repo_path(
                repo_root,
                red_test["path"],
                outside_code="STATE_EVIDENCE_INVALID",
                require_file=True,
            )
        except LoopError as exc:
            fail(
                "STATE_EVIDENCE_INVALID",
                f"historical red test is unavailable: {exc.code}: {exc.message}",
            )
        if relative != red_test["path"] or file_sha256(path) != red_test["sha256"]:
            fail(
                "STATE_EVIDENCE_INVALID",
                f"historical red test changed: {red_test['path']}",
            )


def load_state(state_dir_value: str | Path) -> tuple[Path, dict[str, Any]]:
    state_dir = Path(state_dir_value).resolve()
    state = read_object(state_path(state_dir), "STATE_REQUIRED", "loop state")
    validate_state_shape(state)
    repo_text = state["repo_root"]
    repo_root = Path(repo_text).resolve()
    try:
        state_dir.relative_to(repo_root)
    except ValueError:
        fail("STATE_INVALID", "state directory is outside its candidate repository")
    if state.get("state_dir") != str(state_dir):
        fail("STATE_INVALID", "state directory does not match persisted identity")
    retained_stop = (
        state.get("status") == "completed"
        and state.get("decision") == "STOP"
        and isinstance(state.get("release_basis"), dict)
    )
    retained_source_root: Path | None = None
    if retained_stop:
        validate_release_basis_reference(repo_root, state["release_basis"])
        retained_root, _ = resolve_repo_path(
            repo_root,
            state["release_basis"]["root_path"],
            outside_code="RELEASE_BASIS_INVALID",
        )
        retained_source_root = retained_root / "source"
    validation_source_root = retained_source_root or repo_root
    validate_current_workflow_policy(validation_source_root, state)
    manifest_identity = state["source_manifest"]
    manifest_path, _ = resolve_repo_path(
        validation_source_root,
        manifest_identity["path"],
        outside_code="STATE_INVALID",
        require_file=True,
    )
    # If the manifest bytes are unchanged, its declaration is authoritative
    # over the persisted source list.  A changed manifest is handled as source
    # drift by advance/resume and requires a fresh run before STOP.
    if (
        file_sha256(manifest_path) == manifest_identity["sha256"]
        and not retained_stop
    ):
        _, declared_files = parse_source_manifest(
            repo_root,
            manifest_identity["path"],
            workflow_relative=state["workflow"]["path"],
            controller_executable=state["workflow_policy"]["controller_executable"],
        )
        if declared_files != state["source_files"]:
            fail("STATE_INVALID", "persisted source_files differ from the source manifest")
    validate_persisted_gate_evidence(repo_root, state)
    validate_persisted_red_tests(validation_source_root, state)
    validate_persisted_step_evidence(
        repo_root,
        state,
        frozen_source_root=retained_source_root,
    )
    validate_persisted_finding_evidence(repo_root, state)
    return state_dir, state


def command_start(args: argparse.Namespace) -> int:
    repo_root = Path(args.repo_root).resolve()
    if not repo_root.is_dir():
        fail("REPO_INVALID", f"candidate repository does not exist: {repo_root}")
    if not 1 <= args.max_rounds <= 100:
        fail("MAX_ROUNDS_INVALID", "max_rounds must be between 1 and 100")

    workflow_path, workflow_relative = resolve_repo_path(
        repo_root, args.workflow, require_file=True
    )
    workflow_policy = parse_workflow_policy(workflow_path)
    if args.max_rounds > workflow_policy["max_rounds"]:
        fail(
            "WORKFLOW_POLICY_VIOLATION",
            "CLI max_rounds may only equal or tighten the workflow maximum",
        )
    source_manifest, declared_source_files = parse_source_manifest(
        repo_root,
        workflow_policy["source_manifest"],
        workflow_relative=workflow_relative,
        controller_executable=workflow_policy["controller_executable"],
    )
    supplied_source_files: list[str] = []
    for value in args.source_file:
        _, relative = resolve_repo_path(repo_root, value, require_file=True)
        supplied_source_files.append(relative)
    if len(set(supplied_source_files)) != len(supplied_source_files):
        fail("SOURCE_FILE_INVALID", "source files must be unique")
    if supplied_source_files:
        supplied_set = set(supplied_source_files)
        supplied_set.add(workflow_relative)
        supplied_set.add(workflow_policy["controller_executable"])
        supplied_set.add(source_manifest["path"])
        if sorted(supplied_set) != declared_source_files:
            fail(
                "SOURCE_MANIFEST_MISMATCH",
                "CLI source files must equal the fixed release source manifest after governance files are added",
            )
    source_files = declared_source_files

    allowed_roots: list[str] = []
    for value in args.allow_write:
        _, relative = resolve_repo_path(repo_root, value)
        normalized = relative.rstrip("/") or "."
        if normalized not in allowed_roots:
            allowed_roots.append(normalized)
    if not allowed_roots:
        fail("WRITE_SCOPE_INVALID", "at least one allowed write root is required")
    allowed_roots.sort()
    policy_roots = [PurePosixPath(item) for item in workflow_policy["allowed_write_roots"]]
    for item in allowed_roots:
        proposed = PurePosixPath(item)
        if not any(path_is_within(proposed, root) for root in policy_roots):
            fail(
                "WORKFLOW_POLICY_VIOLATION",
                f"CLI write root expands the workflow policy: {item}",
            )

    state_relative = lexical_relative(repo_root, args.state_dir, "PATH_OUTSIDE_REPO")
    state_dir = repo_root.joinpath(*state_relative.parts).resolve(strict=False)
    try:
        state_dir.relative_to(repo_root)
    except ValueError:
        fail("PATH_SYMLINK_ESCAPE", "state directory resolves outside repository")
    if state_dir.exists():
        fail("STATE_EXISTS", f"state directory already exists: {state_dir}")
    if not any(path_is_within(state_relative, PurePosixPath(item)) for item in allowed_roots):
        fail("WRITE_SCOPE_DENIED", "state directory is outside allowed write roots")

    snapshot = source_snapshot(repo_root, source_files)
    first_id = iteration_id(1, snapshot["sha256"])
    state: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "controller_run_id": f"run-{uuid.uuid4().hex}",
        "repo_root": str(repo_root),
        "state_dir": str(state_dir),
        "workflow": {
            "path": workflow_relative,
            "sha256": file_sha256(workflow_path),
        },
        "workflow_policy": workflow_policy,
        "source_manifest": source_manifest,
        "source_files": source_files,
        "allowed_write_roots": allowed_roots,
        "max_rounds": args.max_rounds,
        "current_round": 1,
        "status": "active",
        "decision": None,
        "source_snapshot": snapshot,
        "finding_ledger": {},
        "iterations": [
            {
                "round": 1,
                "iteration_id": first_id,
                "source_sha256": snapshot["sha256"],
                "active_source_sha256": snapshot["sha256"],
                "source_epoch": None,
                "pending_source_epoch": None,
                "carried_findings": [],
                "next_step": "preflight_snapshot",
                "active_work_order": None,
                "step_ledger": [],
            }
        ],
    }
    state_dir.mkdir(parents=True)
    atomic_write_json(state_path(state_dir), state)
    emit(state)
    return 0


def path_is_within(path: PurePosixPath, root: PurePosixPath) -> bool:
    if root.as_posix() == ".":
        return True
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def protected_path(relative: PurePosixPath) -> bool:
    if ".claude" in relative.parts or relative.name == "CLAUDE.md":
        return True
    if relative.name.startswith(("VP-", "HL-", "TP-")):
        return True
    return any(path_is_within(relative, prefix) for prefix in PROTECTED_PREFIXES)


def gate_result(
    gate_path: Path,
    gate_relative: str,
    gate: dict[str, Any],
    *,
    valid: bool,
    code: str,
    evidence_verified: bool,
) -> dict[str, Any]:
    checks = gate["checks"]
    result = {
        "path": gate_relative,
        "sha256": file_sha256(gate_path),
        "checks": checks,
        "evidence": gate.get("evidence", {}),
        "evidence_verified": evidence_verified,
        "valid": valid,
        "all_true": (
            valid
            and evidence_verified
            and all(checks[key] is True for key in REQUIRED_GATE_CHECKS)
        ),
        "code": code,
    }
    if isinstance(gate.get("producer"), dict):
        result["producer"] = gate["producer"]
    if isinstance(gate.get("release_basis"), dict):
        result["release_basis"] = gate["release_basis"]
    return result


def validate_gate_shape(gate: dict[str, Any]) -> None:
    checks = gate.get("checks")
    if (
        gate.get("schema_version") != SCHEMA_VERSION
        or not isinstance(gate.get("iteration_id"), str)
        or not isinstance(gate.get("source_sha256"), str)
        or not isinstance(checks, dict)
        or set(checks) != set(REQUIRED_GATE_CHECKS)
        or any(type(checks.get(key)) is not bool for key in REQUIRED_GATE_CHECKS)
    ):
        fail("GATE_INVALID", "gate must contain the exact required boolean checks")
    if "evidence" not in gate:
        fail(
            "GATE_EVIDENCE_REQUIRED",
            "every gate check must bind a repository evidence artifact",
        )
    evidence = gate.get("evidence")
    if not isinstance(evidence, dict) or set(evidence) != set(REQUIRED_GATE_CHECKS):
        fail(
            "GATE_EVIDENCE_INVALID",
            "gate evidence must contain the exact required checks",
        )
    for key in REQUIRED_GATE_CHECKS:
        item = evidence.get(key)
        if (
            not isinstance(item, dict)
            or set(item) != set(GATE_EVIDENCE_FIELDS)
            or not isinstance(item.get("path"), str)
            or not item["path"]
            or not _is_sha256(item.get("sha256"))
            or item.get("json_pointer") != "/passed"
            or type(item.get("expected")) is not bool
            or item.get("expected") is not checks[key]
        ):
            fail(
                "GATE_EVIDENCE_INVALID",
                f"gate evidence entry is malformed: {key}",
            )
    evidence_paths = [evidence[key]["path"] for key in REQUIRED_GATE_CHECKS]
    if len(set(evidence_paths)) != len(evidence_paths):
        fail(
            "GATE_EVIDENCE_INVALID",
            "each gate check requires its own typed evidence document",
        )
    producer = gate.get("producer")
    if producer is not None and (
        not isinstance(producer, dict)
        or set(producer)
        != {
            "authority",
            "recipe_version",
            "script_path",
            "script_sha256",
            "raw_receipt_index_path",
            "raw_receipt_index_sha256",
        }
        or producer.get("authority") != "controller_prove_stop"
        or producer.get("recipe_version") != PRODUCER_RECIPE_VERSION
        or not isinstance(producer.get("script_path"), str)
        or not producer["script_path"]
        or not _is_sha256(producer.get("script_sha256"))
        or not isinstance(producer.get("raw_receipt_index_path"), str)
        or not producer["raw_receipt_index_path"]
        or not _is_sha256(producer.get("raw_receipt_index_sha256"))
    ):
        fail("GATE_PRODUCER_INVALID", "gate producer attestation is malformed")


def _gate_proof_failure(check: str, message: str) -> NoReturn:
    code = (
        "ROLLBACK_EVIDENCE_INVALID"
        if check == "rollback"
        else "GATE_EVIDENCE_INVALID"
    )
    fail(code, f"{check}: {message}")


def _nonnegative_integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def validate_typed_gate_proof(
    check: str,
    document: dict[str, Any],
    *,
    evidence_relative: str,
) -> None:
    if document.get("gate_check") != check or type(document.get("passed")) is not bool:
        _gate_proof_failure(check, "evidence must name exactly one gate_check and passed result")
    proof = document.get("proof")
    if not isinstance(proof, dict):
        _gate_proof_failure(check, "proof must be an object")
    commands = document.get("commands")
    if not isinstance(commands, list):
        _gate_proof_failure(check, "commands must be an array")
    for command in commands:
        if (
            not isinstance(command, dict)
            or set(command) != {"argv", "exit_code"}
            or not isinstance(command.get("argv"), list)
            or not command["argv"]
            or any(not isinstance(item, str) or not item for item in command["argv"])
            or type(command.get("exit_code")) is not int
        ):
            _gate_proof_failure(check, "command receipt is malformed")
    if check in COMMAND_PROOF_CHECKS and not commands:
        _gate_proof_failure(check, "this gate requires at least one command receipt")

    derived: bool
    if check in {"p0_zero", "reproducible_p1_zero"}:
        expected = {
            "open_count",
            "reviewer_id",
            "execution_id",
            "model_environment",
            "review_scope",
            "host_execution_receipt_sha256",
            "trust_boundary",
        }
        environment = proof.get("model_environment")
        if set(proof) != expected:
            _gate_proof_failure(check, "review proof fields are malformed")
        if (
            not _nonnegative_integer(proof.get("open_count"))
            or not isinstance(proof.get("reviewer_id"), str)
            or not proof["reviewer_id"].strip()
            or not isinstance(proof.get("execution_id"), str)
            or not proof["execution_id"].strip()
            or not isinstance(environment, dict)
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
            or proof.get("review_scope") != list(REQUIRED_REVIEW_SCOPE)
            or not _is_sha256(proof.get("host_execution_receipt_sha256"))
            or proof.get("trust_boundary") != REVIEW_TRUST_BOUNDARY
        ):
            _gate_proof_failure(check, "review proof fields are malformed")
        derived = proof["open_count"] == 0
    elif check == "unit_tests":
        expected = {
            "tests_run",
            "failures",
            "errors",
            "skipped",
            "expected_failures",
            "test_source_set_sha256",
        }
        if set(proof) != expected or any(
            not _nonnegative_integer(proof.get(field))
            for field in expected - {"test_source_set_sha256"}
        ) or not _is_sha256(proof.get("test_source_set_sha256")):
            _gate_proof_failure(check, "unit test proof fields are malformed")
        derived = (
            proof["tests_run"] > 0
            and all(proof[field] == 0 for field in ("failures", "errors", "skipped", "expected_failures"))
            and all(command["exit_code"] == 0 for command in commands)
        )
    elif check == "self_test":
        if set(proof) != {"checks_run", "failures"} or not all(
            _nonnegative_integer(proof.get(field))
            for field in ("checks_run", "failures")
        ):
            _gate_proof_failure(check, "self-test proof fields are malformed")
        derived = (
            proof["checks_run"] > 0
            and proof["failures"] == 0
            and all(command["exit_code"] == 0 for command in commands)
        )
    elif check == "frozen_eval_18_of_18":
        expected = {"expected_cases", "completed_cases", "missing_cases", "suite_errors"}
        if set(proof) != expected or not all(
            _nonnegative_integer(proof.get(field)) for field in expected
        ):
            _gate_proof_failure(check, "eval case proof fields are malformed")
        derived = (
            proof == {
                "expected_cases": 18,
                "completed_cases": 18,
                "missing_cases": 0,
                "suite_errors": 0,
            }
            and all(command["exit_code"] == 0 for command in commands)
        )
    elif check == "artifacts_16_of_16":
        expected = {"expected_artifacts", "completed_artifacts", "passed", "failed"}
        if set(proof) != expected or not all(
            _nonnegative_integer(proof.get(field)) for field in expected
        ):
            _gate_proof_failure(check, "eval artifact proof fields are malformed")
        derived = (
            proof == {
                "expected_artifacts": 16,
                "completed_artifacts": 16,
                "passed": 16,
                "failed": 0,
            }
            and all(command["exit_code"] == 0 for command in commands)
        )
    elif check == "clean_install":
        expected = {
            "destination_was_absent",
            "installed_file_count",
            "manifest_sha256",
            "install_exit_code",
        }
        if set(proof) != expected:
            _gate_proof_failure(check, "clean-install proof fields are malformed")
        derived = (
            proof.get("destination_was_absent") is True
            and type(proof.get("installed_file_count")) is int
            and proof["installed_file_count"] > 0
            and _is_sha256(proof.get("manifest_sha256"))
            and proof.get("install_exit_code") == 0
            and all(command["exit_code"] == 0 for command in commands)
        )
    elif check == "verify_install":
        expected = {"valid", "error_count", "manifest_sha256", "verify_exit_code"}
        if set(proof) != expected:
            _gate_proof_failure(check, "verify-install proof fields are malformed")
        derived = (
            proof.get("valid") is True
            and proof.get("error_count") == 0
            and _is_sha256(proof.get("manifest_sha256"))
            and proof.get("verify_exit_code") == 0
            and all(command["exit_code"] == 0 for command in commands)
        )
    elif check == "rollback":
        expected = {
            "operation",
            "installed_path",
            "baseline_state_sha256",
            "rolled_back_state_sha256",
            "install_absent_during_rollback",
            "original_path_absent_in_fresh_python_process",
            "restore_verified",
            "installed_manifest_sha256",
            "restored_manifest_sha256",
        }
        if set(proof) != expected:
            _gate_proof_failure(check, "rollback proof fields are malformed")
        derived = (
            proof.get("operation") == "file_level_rollback_and_restore"
            and isinstance(proof.get("installed_path"), str)
            and bool(proof["installed_path"])
            and _is_sha256(proof.get("baseline_state_sha256"))
            and proof.get("baseline_state_sha256") == proof.get("rolled_back_state_sha256")
            and proof.get("install_absent_during_rollback") is True
            and proof.get("original_path_absent_in_fresh_python_process") is True
            and proof.get("restore_verified") is True
            and _is_sha256(proof.get("installed_manifest_sha256"))
            and proof.get("installed_manifest_sha256") == proof.get("restored_manifest_sha256")
            and len(commands) >= 3
            and all(command["exit_code"] == 0 for command in commands)
        )
    else:
        _gate_proof_failure(check, "unsupported gate proof type")
    if document["passed"] is not derived:
        _gate_proof_failure(check, "passed does not match the derived proof result")

    artifacts = document.get("artifacts")
    required_role = GATE_ARTIFACT_ROLES[check]
    if not isinstance(artifacts, list) or not artifacts:
        _gate_proof_failure(check, "at least one typed underlying artifact is required")
    if not any(
        isinstance(item, dict) and item.get("role") == required_role
        for item in artifacts
    ):
        _gate_proof_failure(
            check,
            f"evidence must bind an artifact with role {required_role}: {evidence_relative}",
        )


def validate_command_receipt_bindings(
    repo_root: Path,
    check: str,
    document: dict[str, Any],
    *,
    raw_dir: Path,
    indexed_receipts: dict[str, str],
) -> None:
    commands = document.get("commands")
    references = document.get("command_receipts")
    if (
        not isinstance(commands, list)
        or not isinstance(references, list)
        or len(references) != len(commands)
    ):
        fail(
            "GATE_COMMAND_RECEIPT_MISMATCH",
            f"{check}: each command summary requires one raw receipt",
        )
    if len({item.get("path") for item in references if isinstance(item, dict)}) != len(
        references
    ):
        fail(
            "GATE_COMMAND_RECEIPT_MISMATCH",
            f"{check}: raw command receipt paths must be unique",
        )
    expected_environment = {
        "PYTHONPATH": "removed",
        "PYTHONHOME": "removed",
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }
    required_receipt_fields = {
        "schema_version",
        "recipe_version",
        "step_id",
        "argv",
        "cwd",
        "timeout_seconds",
        "shell",
        "environment_policy",
        "exit_code",
        "timed_out",
        "stdout",
        "stderr",
        "process_family_policy",
    }
    for index, (command, reference) in enumerate(
        zip(commands, references, strict=True), start=1
    ):
        if (
            not isinstance(reference, dict)
            or set(reference) != {"path", "sha256"}
            or not isinstance(reference.get("path"), str)
            or not _is_sha256(reference.get("sha256"))
        ):
            fail(
                "GATE_COMMAND_RECEIPT_MISMATCH",
                f"{check}: command receipt reference {index} is malformed",
            )
        receipt_path, relative = resolve_repo_path(
            repo_root,
            reference["path"],
            outside_code="GATE_COMMAND_RECEIPT_MISMATCH",
            require_file=True,
        )
        if receipt_path.parent.resolve() != raw_dir.resolve():
            fail(
                "GATE_COMMAND_RECEIPT_MISMATCH",
                f"{check}: command receipt is outside the indexed raw directory",
            )
        digest = file_sha256(receipt_path)
        if (
            digest != reference["sha256"]
            or indexed_receipts.get(receipt_path.name) != digest
        ):
            fail(
                "GATE_COMMAND_RECEIPT_MISMATCH",
                f"{check}: command receipt hash is not bound by the raw index: {relative}",
            )
        receipt = read_object(
            receipt_path,
            "GATE_COMMAND_RECEIPT_MISMATCH",
            "raw command receipt",
        )
        if (
            set(receipt) != required_receipt_fields
            or receipt.get("schema_version") != SCHEMA_VERSION
            or receipt.get("recipe_version") != PRODUCER_RECIPE_VERSION
            or not isinstance(receipt.get("step_id"), str)
            or not receipt["step_id"]
            or receipt.get("argv") != command.get("argv")
            or receipt.get("exit_code") != command.get("exit_code")
            or receipt.get("exit_code") != 0
            or receipt.get("timed_out") is not False
            or receipt.get("shell") is not False
            or receipt.get("environment_policy") != expected_environment
            or type(receipt.get("timeout_seconds")) is not int
            or receipt["timeout_seconds"] <= 0
            or not isinstance(receipt.get("cwd"), str)
            or not Path(receipt["cwd"]).is_absolute()
            or not isinstance(receipt.get("stdout"), str)
            or not isinstance(receipt.get("stderr"), str)
            or not isinstance(receipt.get("process_family_policy"), dict)
            or set(receipt["process_family_policy"])
            != {
                "token_sha256",
                "same_uid_only",
                "confirmed_empty",
                "trust_boundary",
            }
            or not _is_sha256(receipt["process_family_policy"].get("token_sha256"))
            or receipt["process_family_policy"].get("same_uid_only") is not True
            or receipt["process_family_policy"].get("confirmed_empty") is not True
            or receipt["process_family_policy"].get("trust_boundary")
            != "cooperative_inherited_token_not_os_sandbox"
        ):
            fail(
                "GATE_COMMAND_RECEIPT_MISMATCH",
                f"{check}: raw command receipt contradicts its passing summary: {relative}",
            )


def validate_gate_evidence(
    repo_root: Path,
    gate: dict[str, Any],
    *,
    iteration_id_value: str,
    source_sha256: str,
) -> None:
    if isinstance(gate.get("release_basis"), dict):
        validate_release_basis_reference(repo_root, gate.get("release_basis"))
        if gate["release_basis"].get("source_sha256") != source_sha256:
            fail("RELEASE_BASIS_INVALID", "release basis binds a different source")
    producer = gate.get("producer")
    indexed_receipts: dict[str, str] = {}
    raw_dir: Path | None = None
    if isinstance(producer, dict):
        producer_script, producer_relative = resolve_repo_path(
            repo_root,
            producer["script_path"],
            outside_code="GATE_PRODUCER_INVALID",
            require_file=True,
        )
        if file_sha256(producer_script) != producer["script_sha256"]:
            fail(
                "GATE_PRODUCER_INVALID",
                f"producer script hash mismatch: {producer_relative}",
            )
        receipt_index_path, receipt_index_relative = resolve_repo_path(
            repo_root,
            producer["raw_receipt_index_path"],
            outside_code="GATE_PRODUCER_INVALID",
            require_file=True,
        )
        if file_sha256(receipt_index_path) != producer["raw_receipt_index_sha256"]:
            fail(
                "GATE_PRODUCER_INVALID",
                f"raw receipt index hash mismatch: {receipt_index_relative}",
            )
        receipt_index = read_object(
            receipt_index_path,
            "GATE_PRODUCER_INVALID",
            "raw receipt index",
        )
        if (
            receipt_index.get("schema_version") != SCHEMA_VERSION
            or receipt_index.get("recipe_version") != PRODUCER_RECIPE_VERSION
            or receipt_index.get("iteration_id") != iteration_id_value
            or receipt_index.get("source_sha256") != source_sha256
            or not isinstance(receipt_index.get("receipts"), dict)
            or not receipt_index["receipts"]
            or any(
                not isinstance(name, str) or not _is_sha256(digest)
                for name, digest in receipt_index["receipts"].items()
            )
        ):
            fail("GATE_PRODUCER_INVALID", "raw receipt index is malformed or stale")
        raw_dir = receipt_index_path.parent / "raw"
        indexed_receipts = dict(receipt_index["receipts"])
        for name, digest in receipt_index["receipts"].items():
            if Path(name).name != name or name in {".", ".."}:
                fail("GATE_PRODUCER_INVALID", "raw receipt name is not normalized")
            receipt_path = raw_dir / name
            if (
                not receipt_path.is_file()
                or receipt_path.is_symlink()
                or file_sha256(receipt_path) != digest
            ):
                fail(
                    "GATE_PRODUCER_INVALID",
                    f"raw receipt is missing or changed: {name}",
                )
    cache: dict[str, dict[str, Any]] = {}
    artifact_owners: dict[str, str] = {}
    documents_by_check: dict[str, dict[str, Any]] = {}
    for key in REQUIRED_GATE_CHECKS:
        item = gate["evidence"][key]
        path, relative = resolve_repo_path(
            repo_root,
            item["path"],
            outside_code="GATE_EVIDENCE_INVALID",
            require_file=True,
        )
        if file_sha256(path) != item["sha256"]:
            fail("GATE_EVIDENCE_INVALID", f"evidence hash mismatch: {relative}")
        document = cache.get(relative)
        if document is None:
            document = read_object(path, "GATE_EVIDENCE_INVALID", "gate evidence")
            cache[relative] = document
        if (
            document.get("schema_version") != SCHEMA_VERSION
            or document.get("iteration_id") != iteration_id_value
            or document.get("source_sha256") != source_sha256
        ):
            fail(
                "GATE_EVIDENCE_INVALID",
                f"evidence does not bind the current iteration and source: {relative}",
            )
        validate_typed_gate_proof(
            key,
            document,
            evidence_relative=relative,
        )
        if isinstance(producer, dict):
            assert raw_dir is not None
            validate_command_receipt_bindings(
                repo_root,
                key,
                document,
                raw_dir=raw_dir,
                indexed_receipts=indexed_receipts,
            )
        documents_by_check[key] = document
        artifacts = document.get("artifacts")
        if not isinstance(artifacts, list) or not artifacts:
            fail(
                "GATE_EVIDENCE_INVALID",
                f"evidence must bind at least one underlying artifact: {relative}",
            )
        for artifact in artifacts:
            if (
                not isinstance(artifact, dict)
                or set(artifact) != {"role", "path", "sha256"}
                or not isinstance(artifact.get("role"), str)
                or not artifact["role"]
                or not isinstance(artifact.get("path"), str)
                or not _is_sha256(artifact.get("sha256"))
            ):
                fail(
                    "GATE_EVIDENCE_INVALID",
                    f"evidence artifact entry is malformed: {relative}",
                )
            artifact_path, artifact_relative = resolve_repo_path(
                repo_root,
                artifact["path"],
                outside_code="GATE_EVIDENCE_INVALID",
                require_file=True,
            )
            if file_sha256(artifact_path) != artifact["sha256"]:
                fail(
                    "GATE_EVIDENCE_INVALID",
                    f"underlying artifact hash mismatch: {artifact_relative}",
                )
            if artifact_relative == relative:
                _gate_proof_failure(
                    key,
                    "evidence document cannot cite itself as its underlying artifact",
                )
            prior_owner = artifact_owners.get(artifact_relative)
            if prior_owner is not None and prior_owner != key:
                fail(
                    "GATE_ARTIFACT_REUSE",
                    "one underlying artifact cannot prove multiple gate checks: "
                    f"{artifact_relative} ({prior_owner}, {key})",
                )
            artifact_owners[artifact_relative] = key
        observed = json_pointer_value(document, item["json_pointer"])
        if type(observed) is not bool or observed is not gate["checks"][key]:
            fail(
                "GATE_EVIDENCE_INVALID",
                f"evidence assertion differs from gate check: {key}",
            )
    clean_manifest = documents_by_check["clean_install"]["proof"][
        "manifest_sha256"
    ]
    verify_manifest = documents_by_check["verify_install"]["proof"][
        "manifest_sha256"
    ]
    rollback_proof = documents_by_check["rollback"]["proof"]
    if not (
        clean_manifest
        == verify_manifest
        == rollback_proof["installed_manifest_sha256"]
        == rollback_proof["restored_manifest_sha256"]
    ):
        fail(
            "GATE_INSTALL_CHAIN_MISMATCH",
            "clean install, verification, rollback, and restore must bind one manifest",
        )


def validate_persisted_gate_evidence(
    repo_root: Path,
    state: dict[str, Any],
) -> None:
    """Re-attest every persisted gate that still claims verified validity."""
    for iteration in state["iterations"]:
        result = iteration.get("gate_result")
        if not isinstance(result, dict) or result.get("code") != "GATE_VALID":
            continue
        try:
            gate_path, gate_relative = resolve_repo_path(
                repo_root,
                result["path"],
                outside_code="STATE_EVIDENCE_INVALID",
                require_file=True,
            )
            if file_sha256(gate_path) != result["sha256"]:
                fail(
                    "STATE_EVIDENCE_INVALID",
                    f"persisted gate hash mismatch: {gate_relative}",
                )
            gate = read_object(
                gate_path,
                "STATE_EVIDENCE_INVALID",
                "persisted gate",
            )
            validate_gate_shape(gate)
            if (
                gate.get("iteration_id") != iteration["iteration_id"]
                or gate.get("source_sha256")
                != iteration["active_source_sha256"]
                or gate.get("checks") != result.get("checks")
                or gate.get("evidence") != result.get("evidence")
                or gate.get("producer") != result.get("producer")
                or gate.get("release_basis") != result.get("release_basis")
                or result.get("valid") is not True
                or result.get("evidence_verified") is not True
                or result.get("all_true")
                is not all(
                    gate["checks"][key] is True for key in REQUIRED_GATE_CHECKS
                )
            ):
                fail(
                    "STATE_EVIDENCE_INVALID",
                    f"persisted gate decision differs from its bound file: {gate_relative}",
                )
            validate_gate_evidence(
                repo_root,
                gate,
                iteration_id_value=iteration["iteration_id"],
                source_sha256=iteration["active_source_sha256"],
            )
        except LoopError as exc:
            if exc.code == "STATE_EVIDENCE_INVALID":
                raise
            fail(
                "STATE_EVIDENCE_INVALID",
                f"persisted gate evidence is no longer valid: {exc.code}: {exc.message}",
            )


def read_finding(path: Path) -> dict[str, str]:
    value = read_object(path, "FINDING_REQUIRED", "finding")
    if any(not isinstance(value.get(key), str) or not value[key].strip() for key in FINDING_FIELDS):
        fail("FINDING_INVALID", "finding is missing a required string field")
    if value["severity"] not in {"P0", "P1"}:
        fail("FINDING_INVALID", "finding severity must be P0 or P1")
    return {key: value[key] for key in FINDING_FIELDS}


def prepare_transition(
    state_dir: Path,
    before: dict[str, Any],
    after: dict[str, Any],
) -> dict[str, Any]:
    pending = state_dir / PENDING_FILE
    if pending.exists():
        fail("RECOVERY_REQUIRED", "a prepared transition must be resumed first")
    transaction_id = (
        f"r{before['current_round']:03d}-to-r{after['current_round']:03d}-"
        f"{uuid.uuid4().hex[:12]}"
    )
    intent = {
        "schema_version": SCHEMA_VERSION,
        "transaction_id": transaction_id,
        "status": "prepared",
        "before_state_sha256": canonical_sha256(before),
        "after_state_sha256": canonical_sha256(after),
        "after_state": after,
    }
    atomic_write_json(pending, intent)
    return intent


def archive_committed_transition(state_dir: Path, intent: dict[str, Any]) -> None:
    committed = dict(intent)
    committed["status"] = "committed"
    pending = state_dir / PENDING_FILE
    atomic_write_json(pending, committed)
    transactions = state_dir / "transactions"
    transactions.mkdir(parents=True, exist_ok=True)
    fsync_directory(state_dir)
    archive = transactions / f"{intent['transaction_id']}.json"
    if archive.exists():
        fail("TRANSACTION_CONFLICT", "transaction archive already exists")
    os.replace(pending, archive)
    fsync_directory(transactions)
    fsync_directory(state_dir)


def archive_aborted_transition(
    state_dir: Path,
    intent: dict[str, Any],
    *,
    reason: str,
    observed_snapshot: dict[str, Any],
) -> None:
    aborted = dict(intent)
    aborted["status"] = "aborted"
    aborted["abort_reason"] = reason
    aborted["observed_source_snapshot"] = observed_snapshot
    pending = state_dir / PENDING_FILE
    atomic_write_json(pending, aborted)
    transactions = state_dir / "transactions"
    transactions.mkdir(parents=True, exist_ok=True)
    fsync_directory(state_dir)
    archive = transactions / f"{intent['transaction_id']}-aborted.json"
    if archive.exists():
        fail("TRANSACTION_CONFLICT", "aborted transaction archive already exists")
    os.replace(pending, archive)
    fsync_directory(transactions)
    fsync_directory(state_dir)


def source_drift_transition(
    before: dict[str, Any],
    base_after: dict[str, Any],
    current_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Turn a stale prepared/completed decision into an auditable next round."""
    after = json.loads(json.dumps(base_after, ensure_ascii=False))
    completed = after["iterations"][-1]
    # A source epoch change invalidates any issued but unconsumed phase nonce.
    # The work-order file remains as audit evidence, but it is no longer active.
    completed["active_work_order"] = None
    completed["pending_source_epoch"] = None
    frozen_sha256 = str(base_after["source_snapshot"]["sha256"])
    completed["finding"] = {
        "finding_id": f"SOURCE-DRIFT-R{after['current_round']:03d}",
        "severity": "P1",
        "summary": "Release evidence changed after the iteration snapshot.",
        "reproducer": "Recompute the explicit source file set.",
        "actual": current_snapshot["sha256"],
        "expected": frozen_sha256,
    }
    completed["red_test"] = None
    prior_gate = completed.get("gate_result")
    if not isinstance(prior_gate, dict):
        prior_gate = {
            "path": "recovery",
            "sha256": canonical_sha256(
                {"iteration_id": completed["iteration_id"]}
            ),
            "checks": {key: False for key in REQUIRED_GATE_CHECKS},
            "evidence": {},
        }
    prior_gate["evidence_verified"] = False
    prior_gate["valid"] = False
    prior_gate["all_true"] = False
    prior_gate["code"] = "SOURCE_DRIFT_INVALIDATED_GATE"
    completed["gate_result"] = prior_gate

    if after["workflow_policy"].get("execution_mode") == EXECUTION_MODE_GRAPH:
        supersede_open_fixes_for_source_drift(
            after["finding_ledger"],
            superseded_round=after["current_round"],
            superseded_by_source_sha256=current_snapshot["sha256"],
        )
        drift_id = completed["finding"]["finding_id"]
        if drift_id not in after["finding_ledger"]:
            after["finding_ledger"][drift_id] = {
                "finding": completed["finding"],
                "status": "open",
                "opened_round": after["current_round"],
                "opened_by": {
                    "kind": "source_drift",
                    "evidence_sha256": canonical_sha256(
                        {
                            "before": frozen_sha256,
                            "after": current_snapshot["sha256"],
                        }
                    ),
                },
                "red_test": None,
                "superseded_fixes": [],
                "fix": None,
                "closure": None,
            }

    if after["current_round"] >= after["max_rounds"]:
        completed["decision"] = "BUDGET_EXHAUSTED"
        after["decision"] = "BUDGET_EXHAUSTED"
        after["status"] = "blocked"
        after["stop_reason"] = "max_rounds_reached"
        after["observed_source_snapshot"] = current_snapshot
    else:
        completed["decision"] = "LOOP"
        next_round = after["current_round"] + 1
        carried = (
            sorted(
                finding_id_value
                for finding_id_value, item in after["finding_ledger"].items()
                if item["status"] == "open"
            )
            if after["workflow_policy"].get("execution_mode")
            == EXECUTION_MODE_GRAPH
            else [completed["finding"]["finding_id"]]
        )
        after["iterations"].append(
            next_iteration(
                next_round,
                current_snapshot,
                carried,
            )
        )
        after["current_round"] = next_round
        after["decision"] = "LOOP"
        after["status"] = "active"
        after["source_snapshot"] = current_snapshot
        after["workflow"]["sha256"] = current_snapshot["files"][
            after["workflow"]["path"]
        ]
    validate_state_shape(after)
    return after


def commit_transition(
    state_dir: Path,
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    validate_state_shape(after)
    repo_root = Path(after["repo_root"])
    validate_persisted_gate_evidence(repo_root, after)
    validate_persisted_step_evidence(repo_root, after)
    validate_persisted_finding_evidence(repo_root, after)
    retained_stop = (
        after.get("status") == "completed"
        and after.get("decision") == "STOP"
        and isinstance(after.get("release_basis"), dict)
    )
    if retained_stop:
        validate_release_basis_reference(repo_root, after["release_basis"])
    expected_source_snapshot = after.get(
        "observed_source_snapshot", after["source_snapshot"]
    )
    observed_source_snapshot = source_snapshot(repo_root, after["source_files"])
    if not retained_stop and observed_source_snapshot != expected_source_snapshot:
        fail(
            "SOURCE_DRIFT_DURING_COMMIT",
            "source changed after gate validation and before transition commit",
        )
    live = read_object(state_path(state_dir), "STATE_REQUIRED", "loop state")
    if canonical_sha256(live) != canonical_sha256(before):
        fail("STATE_CONFLICT", "live state changed before transition commit")
    intent = prepare_transition(state_dir, before, after)
    observed_source_snapshot = source_snapshot(repo_root, after["source_files"])
    if retained_stop:
        validate_release_basis_reference(repo_root, after["release_basis"])
    elif observed_source_snapshot != expected_source_snapshot:
        archive_aborted_transition(
            state_dir,
            intent,
            reason="source_drift_before_publish",
            observed_snapshot=observed_source_snapshot,
        )
        fail(
            "SOURCE_DRIFT_DURING_COMMIT",
            "source changed while the transition was being prepared",
        )
    if os.environ.get("SFFS_IMPROVEMENT_LOOP_FAILPOINT") == "after_prepare":
        fail("SIMULATED_CRASH", "transition prepared but not committed", exit_code=70)
    atomic_write_json(state_path(state_dir), after)
    archive_committed_transition(state_dir, intent)


def next_iteration(
    round_number: int,
    snapshot: dict[str, Any],
    carried_findings: list[str],
) -> dict[str, Any]:
    return {
        "round": round_number,
        "iteration_id": iteration_id(round_number, snapshot["sha256"]),
        "source_sha256": snapshot["sha256"],
        "active_source_sha256": snapshot["sha256"],
        "source_epoch": None,
        "pending_source_epoch": None,
        "carried_findings": carried_findings,
        "next_step": "preflight_snapshot",
        "active_work_order": None,
        "step_ledger": [],
    }


def require_execution_prefix(
    state: dict[str, Any],
    required_steps: tuple[str, ...],
    *,
    code: str,
) -> None:
    policy = state["workflow_policy"]
    if policy.get("execution_mode") != EXECUTION_MODE_GRAPH:
        fail(code, "the workflow is not configured for executable graph receipts")
    observed = [
        entry["step_id"] for entry in state["iterations"][-1]["step_ledger"]
    ]
    if observed[: len(required_steps)] != list(required_steps) or len(observed) < len(
        required_steps
    ):
        missing = list(required_steps[len(observed) :])
        fail(
            code,
            "required workflow steps are incomplete"
            + (f": {', '.join(missing)}" if missing else ""),
        )


def command_begin_step(args: argparse.Namespace) -> int:
    """Issue one run-bound, single-use work order for the next external phase."""
    state_dir, before = load_state(args.state_dir)
    if before.get("status") != "active":
        fail("LOOP_TERMINAL", "only an active loop can begin a workflow step")
    policy = before["workflow_policy"]
    if policy.get("execution_mode") != EXECUTION_MODE_GRAPH:
        fail("WORKFLOW_GRAPH_REQUIRED", "begin-step requires execution_graph mode")
    iteration = before["iterations"][-1]
    expected_step = iteration.get("next_step")
    if expected_step is None:
        fail("WORKFLOW_ALREADY_COMPLETE", "the current workflow graph is complete")
    if args.step_id != expected_step:
        fail(
            "WORKFLOW_STEP_OUT_OF_ORDER",
            f"expected {expected_step}, received {args.step_id}",
        )
    if expected_step not in EXTERNAL_EXECUTION_STEPS:
        fail(
            "CONTROLLER_STEP_EXTERNAL_RECEIPT_FORBIDDEN",
            f"{expected_step} is owned by the fixed controller recipe",
        )
    if iteration.get("active_work_order") is not None:
        active = iteration["active_work_order"]
        validate_phase_work_order(
            Path(before["repo_root"]),
            before,
            iteration,
            {"path": active["path"], "sha256": active["sha256"]},
            expected_step_id=expected_step,
            expected_source_sha256=before["source_snapshot"]["sha256"],
            expected_dependencies={
                dependency: {
                    entry["step_id"]: entry["receipt"]["sha256"]
                    for entry in iteration["step_ledger"]
                }[dependency]
                for dependency in execution_dependencies(policy)[expected_step]
            },
            error_code="WORK_ORDER_INVALID",
        )
        emit(before)
        return 0
    if expected_step == "source_freeze":
        open_findings = sorted(
            finding_id
            for finding_id, item in before["finding_ledger"].items()
            if item["status"] == "open"
        )
        if open_findings:
            fail(
                "OPEN_FINDINGS_REMAIN",
                f"source freeze is blocked by open findings: {', '.join(open_findings)}",
            )

    repo_root = Path(before["repo_root"])
    require_unchanged_source_manifest(repo_root, before)
    observed_snapshot = source_snapshot(repo_root, before["source_files"])
    if observed_snapshot != before["source_snapshot"]:
        fail(
            "SOURCE_DRIFT_INVALIDATED_STEPS",
            "source changed before the phase work order was issued",
        )
    accepted = {
        entry["step_id"]: entry["receipt"]["sha256"]
        for entry in iteration["step_ledger"]
    }
    dependencies = execution_dependencies(policy)[expected_step]
    dependency_receipts = {
        dependency: accepted[dependency] for dependency in dependencies
    }
    attempt_id = f"attempt-{uuid.uuid4().hex}"
    work_order = {
        "schema_version": SCHEMA_VERSION,
        "work_order_type": PHASE_WORK_ORDER_TYPE,
        "controller_run_id": before["controller_run_id"],
        "state_dir": before["state_dir"],
        "iteration_id": iteration["iteration_id"],
        "source_sha256": iteration["active_source_sha256"],
        "step_id": expected_step,
        "attempt_id": attempt_id,
        "dependency_receipts": dependency_receipts,
    }
    order_dir = state_dir / "work-orders"
    order_path = order_dir / f"{iteration['iteration_id']}-{expected_step}-{attempt_id}.json"
    if order_path.exists():
        fail("WORK_ORDER_CONFLICT", "phase work order path already exists")
    atomic_write_json(order_path, work_order)
    after = json.loads(json.dumps(before, ensure_ascii=False))
    after["iterations"][-1]["active_work_order"] = {
        "step_id": expected_step,
        "attempt_id": attempt_id,
        "path": order_path.relative_to(repo_root).as_posix(),
        "sha256": file_sha256(order_path),
    }
    commit_transition(state_dir, before, after)
    emit(after)
    return 0


def command_authorize_fix(args: argparse.Namespace) -> int:
    """Authorize one exact, add-nothing/delete-nothing source epoch for TDD."""
    state_dir, before = load_state(args.state_dir)
    if before.get("status") != "active":
        fail("LOOP_TERMINAL", "only an active loop can authorize a fix")
    if before["workflow_policy"].get("execution_mode") != EXECUTION_MODE_GRAPH:
        fail("WORKFLOW_GRAPH_REQUIRED", "authorize-fix requires execution_graph mode")
    iteration = before["iterations"][-1]
    if (
        iteration.get("next_step") != "red_green_fix"
        or not isinstance(iteration.get("active_work_order"), dict)
    ):
        fail(
            "FIX_WORK_ORDER_REQUIRED",
            "begin-step red_green_fix must issue a work order before authorization",
        )
    existing = iteration.get("pending_source_epoch")
    repo_root = Path(before["repo_root"])
    require_unchanged_source_manifest(repo_root, before)
    observed = source_snapshot(repo_root, before["source_files"])
    if observed != before["source_snapshot"]:
        fail(
            "SOURCE_DRIFT_BEFORE_AUTHORIZATION",
            "fix authorization requires the exact before snapshot",
        )
    record = read_source_epoch_plan(
        repo_root,
        before,
        iteration,
        args.plan,
        require_live_before=True,
        error_code="SOURCE_EPOCH_PLAN_INVALID",
    )
    open_findings = sorted(
        finding_id
        for finding_id, item in before["finding_ledger"].items()
        if item["status"] == "open"
    )
    if record["finding_ids"] != open_findings:
        fail(
            "SOURCE_EPOCH_PLAN_INVALID",
            "source epoch must cover every open finding",
        )
    red_by_finding = {
        item["finding_id"]: {"path": item["path"], "sha256": item["sha256"]}
        for item in record["finding_red_tests"]
    }
    for finding_id in open_findings:
        existing_red_test = before["finding_ledger"][finding_id].get("red_test")
        if existing_red_test is not None and (
            not isinstance(existing_red_test, dict)
            or existing_red_test != red_by_finding[finding_id]
        ):
            fail(
                "SOURCE_EPOCH_PLAN_INVALID",
                f"source epoch changed the bound RED test: {finding_id}",
            )
    if open_findings and not record["implementation_changes"]:
        fail(
            "SOURCE_EPOCH_PLAN_INVALID",
            "a finding fix epoch must name at least one implementation change after RED",
        )
    if not open_findings and (
        record["red_changes"] or record["implementation_changes"]
    ):
        fail(
            "SOURCE_EPOCH_PLAN_INVALID",
            "a no-finding red_green phase cannot smuggle source changes",
        )
    if existing is not None:
        if existing != record:
            fail("SOURCE_EPOCH_ALREADY_AUTHORIZED", "a different fix epoch is active")
        emit(before)
        return 0
    after = json.loads(json.dumps(before, ensure_ascii=False))
    after["iterations"][-1]["pending_source_epoch"] = record
    commit_transition(state_dir, before, after)
    emit(after)
    return 0


def _runner_artifact_reference(
    repo_root: Path, path: Path, role: str
) -> dict[str, str]:
    return {
        "role": role,
        "path": path.relative_to(repo_root).as_posix(),
        "sha256": file_sha256(path),
    }


def _runner_host_descriptor(repo_root: Path, path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(repo_root).as_posix(),
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }


def _finalize_graph_execution(
    *,
    state_dir: Path,
    before: dict[str, Any],
    iteration: dict[str, Any],
    step_id: str,
    active: dict[str, Any],
    execution_dir: Path,
) -> int:
    repo_root = Path(before["repo_root"])
    stdout_path = execution_dir / "stdout.json"
    stderr_path = execution_dir / "stderr.txt"
    primary_path = execution_dir / "phase-evidence.json"
    host_path = execution_dir / "host-execution-receipt.json"
    phase_receipt_path = execution_dir / "phase-receipt.json"
    required = (stdout_path, stderr_path, primary_path, host_path)
    if any(not path.is_file() or path.is_symlink() for path in required):
        fail(
            "RUNNER_OUTCOME_UNKNOWN",
            "runner bytes are partial; the fixed command will not be guessed or rerun",
        )
    observed_snapshot = source_snapshot(repo_root, before["source_files"])
    if observed_snapshot != before["source_snapshot"]:
        fail(
            "RUNNER_SOURCE_MUTATION",
            f"read-only graph worker changed release source during {step_id}",
        )
    try:
        bundle = json.loads(stdout_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail("RUNNER_BUNDLE_INVALID", f"worker stdout is not one JSON object: {exc}")
    if (
        not isinstance(bundle, dict)
        or set(bundle)
        != {"schema_version", "step_id", "summary", "result", "finding_events"}
        or bundle.get("schema_version") != GRAPH_WORKER_BUNDLE_VERSION
        or bundle.get("step_id") != step_id
        or not isinstance(bundle.get("summary"), str)
        or not bundle["summary"].strip()
        or not isinstance(bundle.get("result"), dict)
        or not isinstance(bundle.get("finding_events"), list)
        or any(not isinstance(item, dict) for item in bundle["finding_events"])
    ):
        fail("RUNNER_BUNDLE_INVALID", "worker bundle violates the fixed contract")
    host = read_object(host_path, "RUNNER_HOST_INVALID", "graph host receipt")
    execution_id = host.get("execution_id")
    if not isinstance(execution_id, str) or not execution_id:
        fail("RUNNER_HOST_INVALID", "graph host receipt lacks execution identity")
    source_sha = iteration["active_source_sha256"]
    accepted = {
        entry["step_id"]: entry["receipt"]["sha256"]
        for entry in iteration["step_ledger"]
    }
    dependencies = execution_dependencies(before["workflow_policy"])[step_id]
    phase_receipt = {
        "schema_version": SCHEMA_VERSION,
        "receipt_type": PHASE_RECEIPT_TYPE,
        "controller_run_id": before["controller_run_id"],
        "attempt_id": active["attempt_id"],
        "work_order": {"path": active["path"], "sha256": active["sha256"]},
        "iteration_id": iteration["iteration_id"],
        "source_sha256": source_sha,
        "step_id": step_id,
        "status": "succeeded",
        "dependency_receipts": {
            dependency: accepted[dependency] for dependency in dependencies
        },
        "producer": {
            "actor_id": "improvement_loop.graph_runner",
            "execution_id": execution_id,
            "trust_boundary": GRAPH_RUNNER_TRUST_BOUNDARY,
        },
        "summary": bundle["summary"],
        "artifacts": [
            _runner_artifact_reference(
                repo_root, primary_path, PHASE_PRIMARY_ROLES[step_id]
            ),
            _runner_artifact_reference(
                repo_root, host_path, "host_execution_receipt"
            ),
            _runner_artifact_reference(repo_root, stdout_path, "worker_stdout"),
            _runner_artifact_reference(repo_root, stderr_path, "worker_stderr"),
        ],
        "finding_events": bundle["finding_events"],
    }
    if phase_receipt_path.exists() or phase_receipt_path.is_symlink():
        existing = read_object(
            phase_receipt_path, "RUNNER_PHASE_RECEIPT_INVALID", "phase receipt"
        )
        if existing != phase_receipt:
            fail(
                "RUNNER_PHASE_RECEIPT_INVALID",
                "persisted phase receipt differs from retained host execution",
            )
    else:
        atomic_write_json(phase_receipt_path, phase_receipt)
    with redirect_stdout(StringIO()):
        command_record_step(
            argparse.Namespace(
                state_dir=str(state_dir),
                step_id=step_id,
                receipt=str(phase_receipt_path),
            )
        )
    _, after = load_state(state_dir)
    emit(after)
    return 0


def command_run_next(args: argparse.Namespace) -> int:
    """Execute the current graph node through one controller-owned recipe."""
    state_dir, before = load_state(args.state_dir)
    if before.get("status") != "active":
        fail("LOOP_TERMINAL", "only an active loop can run a workflow step")
    iteration = before["iterations"][-1]
    step_id = iteration.get("next_step")
    if step_id != "preflight_snapshot":
        fail(
            "RUNNER_RECIPE_UNAVAILABLE",
            f"no fixed controller recipe is registered for {step_id}",
        )
    if iteration.get("active_work_order") is None:
        with redirect_stdout(StringIO()):
            command_begin_step(
                argparse.Namespace(state_dir=str(state_dir), step_id=step_id)
            )
        state_dir, before = load_state(state_dir)
        iteration = before["iterations"][-1]
    active = iteration["active_work_order"]
    repo_root = Path(before["repo_root"])
    worker_relative = _graph_worker_relative(before)
    worker_path, _ = resolve_repo_path(
        repo_root,
        worker_relative,
        outside_code="RUNNER_RECIPE_INVALID",
        require_file=True,
    )
    if before["source_snapshot"]["files"].get(worker_relative) != file_sha256(
        worker_path
    ):
        fail("RUNNER_RECIPE_INVALID", "fixed graph worker is not source-bound")
    work_order_path, _ = resolve_repo_path(
        repo_root,
        active["path"],
        outside_code="RUNNER_RECIPE_INVALID",
        require_file=True,
    )
    execution_dir = (
        state_dir
        / "executions"
        / f"{iteration['iteration_id']}-{step_id}-{active['attempt_id']}"
    )
    if execution_dir.exists() or execution_dir.is_symlink():
        return _finalize_graph_execution(
            state_dir=state_dir,
            before=before,
            iteration=iteration,
            step_id=step_id,
            active=active,
            execution_dir=execution_dir,
        )
    execution_dir.mkdir(parents=True)
    fsync_directory(execution_dir.parent)
    stdout_path = execution_dir / "stdout.json"
    stderr_path = execution_dir / "stderr.txt"
    primary_path = execution_dir / "phase-evidence.json"
    host_path = execution_dir / "host-execution-receipt.json"
    phase_receipt_path = execution_dir / "phase-receipt.json"
    argv = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        str(worker_path),
        "--step",
        step_id,
        "--state",
        str(state_path(state_dir)),
        "--work-order",
        str(work_order_path),
    ]
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment[PROCESS_FAMILY_TOKEN_ENV] = uuid.uuid4().hex
    started = time.monotonic()
    try:
        completed = _run_in_process_group(
            argv,
            cwd=repo_root,
            environment=environment,
            timeout_seconds=GRAPH_WORKER_TIMEOUT_SECONDS,
        )
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        atomic_write_text(stdout_path, _subprocess_output_text(exc.stdout))
        atomic_write_text(stderr_path, _subprocess_output_text(exc.stderr))
        fail("RUNNER_TIMEOUT", f"fixed graph worker timed out for {step_id}")
    duration_ms = int((time.monotonic() - started) * 1000)
    atomic_write_text(stdout_path, completed.stdout)
    atomic_write_text(stderr_path, completed.stderr)
    if completed.returncode != 0:
        fail(
            "RUNNER_WORKER_FAILED",
            f"fixed graph worker exited {completed.returncode} for {step_id}",
        )
    observed_snapshot = source_snapshot(repo_root, before["source_files"])
    if observed_snapshot != before["source_snapshot"]:
        fail(
            "RUNNER_SOURCE_MUTATION",
            f"read-only graph worker changed release source during {step_id}",
        )
    try:
        bundle = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        fail("RUNNER_BUNDLE_INVALID", f"worker stdout is not one JSON object: {exc}")
    if (
        not isinstance(bundle, dict)
        or set(bundle)
        != {"schema_version", "step_id", "summary", "result", "finding_events"}
        or bundle.get("schema_version") != GRAPH_WORKER_BUNDLE_VERSION
        or bundle.get("step_id") != step_id
        or not isinstance(bundle.get("summary"), str)
        or not bundle["summary"].strip()
        or not isinstance(bundle.get("result"), dict)
        or not isinstance(bundle.get("finding_events"), list)
        or any(not isinstance(item, dict) for item in bundle["finding_events"])
    ):
        fail("RUNNER_BUNDLE_INVALID", "worker bundle violates the fixed contract")
    source_sha = iteration["active_source_sha256"]
    primary = {
        "schema_version": SCHEMA_VERSION,
        "evidence_type": f"{step_id}.v1",
        "controller_run_id": before["controller_run_id"],
        "iteration_id": iteration["iteration_id"],
        "source_sha256": source_sha,
        "result": bundle["result"],
    }
    atomic_write_json(primary_path, primary)
    execution_id = f"graph-exec-{uuid.uuid4()}"
    host_receipt = {
        "schema_version": SCHEMA_VERSION,
        "receipt_type": GRAPH_HOST_RECEIPT_TYPE,
        "trust_boundary": GRAPH_RUNNER_TRUST_BOUNDARY,
        "controller_run_id": before["controller_run_id"],
        "iteration_id": iteration["iteration_id"],
        "source_before_sha256": source_sha,
        "source_after_sha256": observed_snapshot["sha256"],
        "step_id": step_id,
        "attempt_id": active["attempt_id"],
        "execution_id": execution_id,
        "work_order": {"path": active["path"], "sha256": active["sha256"]},
        "command": {
            "argv": argv,
            "argv_sha256": canonical_sha256(argv),
            "cwd": str(repo_root.resolve()),
            "shell": False,
            "timeout_seconds": GRAPH_WORKER_TIMEOUT_SECONDS,
            "worker_sha256": file_sha256(worker_path),
        },
        "process": {
            "pid": completed.pid,
            "exit_code": completed.returncode,
            "timed_out": timed_out,
            "duration_ms": duration_ms,
            "process_family": completed.process_family_policy,
        },
        "artifacts": {
            "stdout": _runner_host_descriptor(repo_root, stdout_path),
            "stderr": _runner_host_descriptor(repo_root, stderr_path),
        },
    }
    atomic_write_json(host_path, host_receipt)
    if os.environ.get("SFFS_GRAPH_RUNNER_FAILPOINT") == "after_host_receipt":
        fail(
            "SIMULATED_RUNNER_CRASH",
            "host receipt persisted before the phase transition",
            exit_code=70,
        )
    return _finalize_graph_execution(
        state_dir=state_dir,
        before=before,
        iteration=iteration,
        step_id=step_id,
        active=active,
        execution_dir=execution_dir,
    )


def command_record_step(args: argparse.Namespace) -> int:
    """Accept exactly the next external phase receipt and advance the DAG cursor."""
    state_dir, before = load_state(args.state_dir)
    if before.get("status") != "active":
        fail("LOOP_TERMINAL", "only an active loop can record a workflow step")
    policy = before["workflow_policy"]
    if policy.get("execution_mode") != EXECUTION_MODE_GRAPH:
        fail("WORKFLOW_GRAPH_REQUIRED", "record-step requires execution_graph mode")
    iteration = before["iterations"][-1]
    expected_step = iteration.get("next_step")
    if expected_step is None:
        fail("WORKFLOW_ALREADY_COMPLETE", "the current workflow graph is complete")
    if args.step_id != expected_step:
        fail(
            "WORKFLOW_STEP_OUT_OF_ORDER",
            f"expected {expected_step}, received {args.step_id}",
        )
    if expected_step not in EXTERNAL_EXECUTION_STEPS:
        fail(
            "CONTROLLER_STEP_EXTERNAL_RECEIPT_FORBIDDEN",
            f"{expected_step} is owned by the fixed controller recipe",
        )
    if iteration.get("active_work_order") is None:
        fail("WORK_ORDER_REQUIRED", "begin-step must issue a work order first")
    if expected_step == "source_freeze":
        open_findings = sorted(
            finding_id
            for finding_id, item in before["finding_ledger"].items()
            if item["status"] == "open"
        )
        if open_findings:
            fail(
                "OPEN_FINDINGS_REMAIN",
                f"source freeze is blocked by open findings: {', '.join(open_findings)}",
            )

    repo_root = Path(before["repo_root"])
    require_unchanged_source_manifest(repo_root, before)
    observed_snapshot = source_snapshot(repo_root, before["source_files"])
    pending_source_epoch = iteration.get("pending_source_epoch")
    open_findings = sorted(
        finding_id
        for finding_id, item in before["finding_ledger"].items()
        if item["status"] == "open"
    )
    if (
        expected_step == "red_green_fix"
        and open_findings
        and not isinstance(pending_source_epoch, dict)
    ):
        fail(
            "SOURCE_EPOCH_AUTHORIZATION_REQUIRED",
            "a real finding fix requires an authorized before-to-after source epoch",
        )
    if isinstance(pending_source_epoch, dict):
        if (
            expected_step != "red_green_fix"
            or observed_snapshot["sha256"]
            != pending_source_epoch["source_after_sha256"]
            or observed_snapshot["files"]
            != pending_source_epoch["source_after_files"]
        ):
            fail(
                "SOURCE_EPOCH_AFTER_MISMATCH",
                "live source does not equal the exact authorized after snapshot",
            )
    elif observed_snapshot != before["source_snapshot"]:
        fail(
            "SOURCE_DRIFT_INVALIDATED_STEPS",
            "source changed after the iteration opened; start a new loop round",
        )

    receipt_path, receipt_relative = _phase_receipt_path(
        repo_root,
        before,
        args.receipt,
        error_code="STEP_RECEIPT_INVALID",
    )
    receipt = read_object(receipt_path, "STEP_RECEIPT_INVALID", "phase receipt")
    if expected_step == "red_green_fix" and isinstance(
        pending_source_epoch, dict
    ):
        raw_claimed_finding_ids = [
            event.get("finding_id")
            for event in receipt.get("finding_events", [])
            if isinstance(event, dict) and event.get("action") == "fix_claimed"
        ]
        if not all(
            isinstance(finding_id, str) and finding_id
            for finding_id in raw_claimed_finding_ids
        ):
            fail(
                "FINDING_EVENT_INVALID",
                "fix events must use non-empty string finding IDs",
            )
        claimed_finding_ids = sorted(raw_claimed_finding_ids)
        if claimed_finding_ids != pending_source_epoch["finding_ids"]:
            fail(
                "SOURCE_EPOCH_FINDING_MISMATCH",
                "fix events must cover exactly the findings bound by the source epoch",
            )
    accepted = {
        entry["step_id"]: entry["receipt"]["sha256"]
        for entry in iteration["step_ledger"]
    }
    dependencies = execution_dependencies(policy)[expected_step]
    expected_dependencies = {
        dependency: accepted[dependency] for dependency in dependencies
    }
    entry = validate_phase_receipt(
        repo_root,
        before,
        iteration,
        receipt_path=receipt_path,
        receipt_relative=receipt_relative,
        receipt=receipt,
        expected_step_id=expected_step,
        expected_dependencies=expected_dependencies,
        expected_work_order={
            "path": iteration["active_work_order"]["path"],
            "sha256": iteration["active_work_order"]["sha256"],
        },
        expected_source_sha256=(
            iteration["pending_source_epoch"]["source_after_sha256"]
            if expected_step == "red_green_fix"
            and isinstance(iteration.get("pending_source_epoch"), dict)
            else iteration["active_source_sha256"]
        ),
        expected_work_order_source_sha256=iteration["active_source_sha256"],
    )

    after = json.loads(json.dumps(before, ensure_ascii=False))
    target_iteration = after["iterations"][-1]
    if isinstance(pending_source_epoch, dict):
        target_iteration["source_epoch"] = pending_source_epoch
        target_iteration["pending_source_epoch"] = None
        target_iteration["active_source_sha256"] = pending_source_epoch[
            "source_after_sha256"
        ]
        after["source_snapshot"] = observed_snapshot
    target_iteration["step_ledger"].append(entry)
    apply_finding_events(
        after,
        step_id=expected_step,
        receipt=receipt,
        receipt_sha256=entry["receipt"]["sha256"],
    )
    if expected_step == "independent_recheck":
        unclosed_carried = [
            finding_id
            for finding_id in target_iteration["carried_findings"]
            if (
                after["finding_ledger"].get(finding_id, {}).get("status") != "closed"
                or after["finding_ledger"][finding_id]["closure"]["round"]
                != after["current_round"]
            )
        ]
        if unclosed_carried:
            fail(
                "CARRIED_FINDING_NOT_CLOSED",
                "independent recheck did not close carried findings in this round: "
                + ", ".join(unclosed_carried),
            )
        still_open = sorted(
            finding_id
            for finding_id, item in after["finding_ledger"].items()
            if item["status"] == "open"
        )
        if still_open:
            fail(
                "OPEN_FINDINGS_REMAIN",
                "independent recheck must close every open finding before the graph advances: "
                + ", ".join(still_open),
            )
    step_ids = execution_step_ids(policy)
    next_index = len(target_iteration["step_ledger"])
    target_iteration["next_step"] = (
        step_ids[next_index] if next_index < len(step_ids) else None
    )
    target_iteration["active_work_order"] = None
    commit_transition(state_dir, before, after)
    emit(after)
    return 0


def write_controller_step_receipts(
    state: dict[str, Any],
    output_dir_value: str | Path,
    artifacts_by_step: dict[str, dict[str, str]],
    *,
    execution_id: str,
) -> list[str]:
    """Materialize one typed receipt for each controller-owned terminal phase."""
    require_execution_prefix(
        state,
        EXTERNAL_EXECUTION_STEPS,
        code="WORKFLOW_STEPS_INCOMPLETE",
    )
    if state["iterations"][-1].get("next_step") != CONTROLLER_EXECUTION_STEPS[0]:
        fail(
            "CONTROLLER_STEP_RECEIPTS_INVALID",
            "controller terminal receipts may only start at clean_install",
        )
    if (
        not isinstance(artifacts_by_step, dict)
        or set(artifacts_by_step) != set(CONTROLLER_EXECUTION_STEPS)
        or not isinstance(execution_id, str)
        or not execution_id.strip()
    ):
        fail(
            "CONTROLLER_STEP_RECEIPTS_INVALID",
            "terminal steps require one distinct artifact mapping and execution id",
        )
    repo_root = Path(state["repo_root"])
    output_relative = lexical_relative(
        repo_root,
        output_dir_value,
        "CONTROLLER_STEP_RECEIPTS_INVALID",
    )
    state_relative = PurePosixPath(
        Path(state["state_dir"]).relative_to(repo_root).as_posix()
    )
    if not path_is_within(output_relative, state_relative):
        fail(
            "CONTROLLER_STEP_RECEIPTS_INVALID",
            "terminal receipts must be written inside the state directory",
        )
    output_dir = repo_root.joinpath(*output_relative.parts).resolve(strict=False)
    try:
        output_dir.relative_to(repo_root)
    except ValueError:
        fail("CONTROLLER_STEP_RECEIPTS_INVALID", "terminal receipt path escapes repo")
    if output_dir.exists() and (not output_dir.is_dir() or output_dir.is_symlink()):
        fail(
            "CONTROLLER_STEP_RECEIPTS_INVALID",
            "terminal receipt output must be a regular directory",
        )

    iteration = state["iterations"][-1]
    accepted = {
        entry["step_id"]: entry["receipt"]["sha256"]
        for entry in iteration["step_ledger"]
    }
    dependencies = execution_dependencies(state["workflow_policy"])
    receipt_paths: list[str] = []
    for step_id in CONTROLLER_EXECUTION_STEPS:
        artifact = artifacts_by_step[step_id]
        if (
            not isinstance(artifact, dict)
            or set(artifact) != {"role", "path", "sha256"}
            or not isinstance(artifact.get("role"), str)
            or not artifact["role"].strip()
            or not isinstance(artifact.get("path"), str)
            or not _is_sha256(artifact.get("sha256"))
        ):
            fail(
                "CONTROLLER_STEP_RECEIPTS_INVALID",
                f"terminal artifact is malformed: {step_id}",
            )
        artifact_path, artifact_relative = resolve_repo_path(
            repo_root,
            artifact["path"],
            outside_code="CONTROLLER_STEP_RECEIPTS_INVALID",
            require_file=True,
        )
        if file_sha256(artifact_path) != artifact["sha256"]:
            fail(
                "CONTROLLER_STEP_RECEIPTS_INVALID",
                f"terminal artifact hash mismatch: {artifact_relative}",
            )
        dependency_receipts = {
            dependency: accepted[dependency]
            for dependency in dependencies[step_id]
        }
        receipt = {
            "schema_version": SCHEMA_VERSION,
            "receipt_type": PHASE_RECEIPT_TYPE,
            "controller_run_id": state["controller_run_id"],
            "attempt_id": f"{execution_id}-{step_id}",
            "work_order": None,
            "iteration_id": iteration["iteration_id"],
            "source_sha256": iteration["active_source_sha256"],
            "step_id": step_id,
            "status": "succeeded",
            "dependency_receipts": dependency_receipts,
            "producer": {
                "actor_id": "improvement_loop.controller",
                "execution_id": execution_id,
                "trust_boundary": "controller_fixed_recipe_local_execution",
            },
            "summary": f"Controller fixed recipe completed {step_id}.",
            "artifacts": [
                {
                    "role": artifact["role"],
                    "path": artifact_relative,
                    "sha256": artifact["sha256"],
                }
            ],
            "finding_events": [],
        }
        receipt_path = output_dir / f"{step_id}.receipt.json"
        if receipt_path.exists():
            fail(
                "CONTROLLER_STEP_RECEIPTS_INVALID",
                f"terminal receipt already exists: {receipt_path}",
            )
        atomic_write_json(receipt_path, receipt)
        relative = receipt_path.relative_to(repo_root).as_posix()
        receipt_paths.append(relative)
        accepted[step_id] = file_sha256(receipt_path)
    return receipt_paths


def append_controller_step_receipts(
    state: dict[str, Any],
    receipt_paths: list[str],
) -> dict[str, Any]:
    if (
        not isinstance(receipt_paths, list)
        or len(receipt_paths) != len(CONTROLLER_EXECUTION_STEPS)
        or any(not isinstance(item, str) or not item for item in receipt_paths)
    ):
        fail(
            "CONTROLLER_STEP_RECEIPTS_INVALID",
            "all four controller terminal receipts are required",
        )
    require_execution_prefix(
        state,
        EXTERNAL_EXECUTION_STEPS,
        code="CONTROLLER_STEP_RECEIPTS_INVALID",
    )
    after = json.loads(json.dumps(state, ensure_ascii=False))
    iteration = after["iterations"][-1]
    if iteration.get("next_step") != CONTROLLER_EXECUTION_STEPS[0]:
        fail(
            "CONTROLLER_STEP_RECEIPTS_INVALID",
            "terminal receipt append must begin at clean_install",
        )
    repo_root = Path(after["repo_root"])
    dependencies = execution_dependencies(after["workflow_policy"])
    accepted = {
        entry["step_id"]: entry["receipt"]["sha256"]
        for entry in iteration["step_ledger"]
    }
    for expected_step, receipt_value in zip(
        CONTROLLER_EXECUTION_STEPS, receipt_paths, strict=True
    ):
        try:
            receipt_path, receipt_relative = _phase_receipt_path(
                repo_root,
                after,
                receipt_value,
                error_code="CONTROLLER_STEP_RECEIPTS_INVALID",
            )
            receipt = read_object(
                receipt_path,
                "CONTROLLER_STEP_RECEIPTS_INVALID",
                "controller phase receipt",
            )
            expected_dependencies = {
                dependency: accepted[dependency]
                for dependency in dependencies[expected_step]
            }
            entry = validate_phase_receipt(
                repo_root,
                after,
                iteration,
                receipt_path=receipt_path,
                receipt_relative=receipt_relative,
                receipt=receipt,
                expected_step_id=expected_step,
                expected_dependencies=expected_dependencies,
                expected_work_order=None,
                expected_source_sha256=iteration["active_source_sha256"],
                expected_work_order_source_sha256=iteration["active_source_sha256"],
                error_code="CONTROLLER_STEP_RECEIPTS_INVALID",
            )
        except LoopError as exc:
            if exc.code == "CONTROLLER_STEP_RECEIPTS_INVALID":
                raise
            fail(
                "CONTROLLER_STEP_RECEIPTS_INVALID",
                f"terminal phase receipt is invalid: {exc.code}: {exc.message}",
            )
        iteration["step_ledger"].append(entry)
        accepted[expected_step] = entry["receipt"]["sha256"]
    iteration["next_step"] = None
    validate_iteration_step_ledger_shape(iteration, after["workflow_policy"])
    return after


def command_advance(args: argparse.Namespace) -> int:
    state_dir, before = load_state(args.state_dir)
    if before.get("status") != "active":
        fail("LOOP_TERMINAL", "only an active loop can advance")
    if (
        before["workflow_policy"].get("execution_mode") == EXECUTION_MODE_GRAPH
        and before["iterations"][-1].get("active_work_order") is not None
    ):
        fail(
            "WORK_ORDER_ACTIVE",
            "advance cannot bypass an issued phase work order",
        )
    repo_root = Path(before["repo_root"])
    supplied_gate = Path(args.gate)
    gate_value: str | Path = (
        supplied_gate.resolve() if supplied_gate.is_absolute() else supplied_gate
    )
    gate_path, gate_relative = resolve_repo_path(
        repo_root,
        gate_value,
        outside_code="GATE_PATH_OUTSIDE_REPO",
        require_file=False,
    )
    gate = read_object(gate_path, "GATE_REQUIRED", "gate")
    validate_gate_shape(gate)

    controller_owned_stop = (
        before["workflow_policy"].get("stop_authority")
        == "controller_prove_stop"
    )
    stop_authorized = getattr(args, "stop_authorized", False) is True
    retained_stop_attempt = (
        controller_owned_stop
        and stop_authorized
        and isinstance(gate.get("release_basis"), dict)
    )
    if not retained_stop_attempt:
        require_unchanged_source_manifest(repo_root, before)
    current_snapshot = source_snapshot(repo_root, before["source_files"])
    current_iteration = before["iterations"][-1]
    source_drifted = current_snapshot["sha256"] != before["source_snapshot"]["sha256"]

    if source_drifted and not retained_stop_attempt:
        result = gate_result(
            gate_path,
            gate_relative,
            gate,
            valid=False,
            code="SOURCE_DRIFT_INVALIDATED_GATE",
            evidence_verified=False,
        )
        finding = {
            "finding_id": f"SOURCE-DRIFT-R{before['current_round']:03d}",
            "severity": "P1",
            "summary": "Release evidence changed after the iteration snapshot.",
            "reproducer": "Recompute the explicit source file set.",
            "actual": current_snapshot["sha256"],
            "expected": before["source_snapshot"]["sha256"],
        }
        red_test = None
    else:
        if (
            gate.get("iteration_id") != current_iteration.get("iteration_id")
            or gate.get("source_sha256") != before["source_snapshot"]["sha256"]
        ):
            fail("GATE_STALE", "gate does not bind the current iteration and source")
        validate_gate_evidence(
            repo_root,
            gate,
            iteration_id_value=current_iteration["iteration_id"],
            source_sha256=before["source_snapshot"]["sha256"],
        )
        result = gate_result(
            gate_path,
            gate_relative,
            gate,
            valid=True,
            code="GATE_VALID",
            evidence_verified=True,
        )
        finding = None
        red_test = None
        if result["all_true"] and controller_owned_stop and not stop_authorized:
            fail(
                "EXTERNAL_STOP_FORBIDDEN",
                "an all-true external gate cannot authorize STOP; use prove-stop",
            )
        if result["all_true"] and controller_owned_stop and (
            not isinstance(gate.get("producer"), dict)
            or gate["producer"].get("authority") != "controller_prove_stop"
            or gate["producer"].get("script_path")
            != (
                f"{gate.get('release_basis', {}).get('root_path', '')}/source/"
                f"{before['workflow_policy'].get('gate_producer')}"
            )
        ):
            fail(
                "GATE_PRODUCER_REQUIRED",
                "controller-owned STOP requires an executable producer receipt",
            )
        if not result["all_true"]:
            if not args.finding or not args.red_test:
                fail("LOOP_EVIDENCE_REQUIRED", "a failed gate requires finding and red test")
            finding_path = Path(args.finding).resolve()
            finding = read_finding(finding_path)
            supplied_red_test = Path(args.red_test)
            red_test_value: str | Path = (
                supplied_red_test.resolve()
                if supplied_red_test.is_absolute()
                else supplied_red_test
            )
            test_path, test_relative = resolve_repo_path(
                repo_root, red_test_value, require_file=True
            )
            if test_relative not in before["source_files"]:
                fail(
                    "RED_TEST_NOT_FROZEN",
                    "red test must belong to the authoritative source manifest",
                )
            red_test = {"path": test_relative, "sha256": file_sha256(test_path)}

    if (
        result["all_true"]
        and controller_owned_stop
        and before["workflow_policy"].get("execution_mode") == EXECUTION_MODE_GRAPH
    ):
        controller_step_receipts = getattr(args, "controller_step_receipts", None)
        if not stop_authorized or not isinstance(controller_step_receipts, list):
            fail(
                "CONTROLLER_STEP_RECEIPTS_REQUIRED",
                "controller-owned STOP requires four terminal phase receipts",
            )
        after = append_controller_step_receipts(before, controller_step_receipts)
    else:
        after = json.loads(json.dumps(before, ensure_ascii=False))
    completed = after["iterations"][-1]
    completed["finding"] = finding
    completed["red_test"] = red_test
    completed["gate_result"] = result

    if (
        before["workflow_policy"].get("execution_mode") == EXECUTION_MODE_GRAPH
        and finding is not None
    ):
        finding_id_value = finding["finding_id"]
        if finding_id_value in after["finding_ledger"]:
            fail("FINDING_DUPLICATE", f"finding id already exists: {finding_id_value}")
        if result["code"] == "SOURCE_DRIFT_INVALIDATED_GATE":
            opened_by = {
                "kind": "source_drift",
                "evidence_sha256": canonical_sha256(
                    {
                        "before": finding["expected"],
                        "after": finding["actual"],
                    }
                ),
            }
        else:
            opened_by = {
                "kind": "gate",
                "evidence_sha256": result["sha256"],
            }
        after["finding_ledger"][finding_id_value] = {
            "finding": finding,
            "status": "open",
            "opened_round": before["current_round"],
            "opened_by": opened_by,
            "red_test": red_test,
            "superseded_fixes": [],
            "fix": None,
            "closure": None,
        }

    if result["all_true"]:
        completed["decision"] = "STOP"
        after["decision"] = "STOP"
        after["status"] = "completed"
        if isinstance(result.get("release_basis"), dict):
            after["release_basis"] = result["release_basis"]
            after["observed_source_snapshot"] = current_snapshot
    elif before["current_round"] >= before["max_rounds"]:
        completed["decision"] = "BUDGET_EXHAUSTED"
        after["decision"] = "BUDGET_EXHAUSTED"
        after["status"] = "blocked"
        after["stop_reason"] = "max_rounds_reached"
        if source_drifted:
            after["observed_source_snapshot"] = current_snapshot
        else:
            after["source_snapshot"] = current_snapshot
            after["workflow"]["sha256"] = current_snapshot["files"][
                after["workflow"]["path"]
            ]
    else:
        completed["decision"] = "LOOP"
        next_round = before["current_round"] + 1
        if before["workflow_policy"].get("execution_mode") == EXECUTION_MODE_GRAPH:
            carried = sorted(
                finding_id_value
                for finding_id_value, item in after["finding_ledger"].items()
                if item["status"] == "open"
            )
        else:
            carried = [finding["finding_id"]] if finding is not None else []
        after["iterations"].append(
            next_iteration(next_round, current_snapshot, carried)
        )
        after["current_round"] = next_round
        after["source_snapshot"] = current_snapshot
        after["workflow"]["sha256"] = current_snapshot["files"][
            after["workflow"]["path"]
        ]
        after["decision"] = "LOOP"
        after["status"] = "active"

    commit_transition(state_dir, before, after)
    emit(after)
    return 0


def _isolated_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return environment


def _subprocess_output_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


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
    """Read exact environment entries through KERN_PROCARGS2."""
    libc = ctypes.CDLL(None, use_errno=True)
    sysctl = getattr(libc, "sysctl", None)
    if sysctl is None:
        raise RuntimeError("exact process environment enumeration is unavailable")
    mib = (ctypes.c_int * 3)(1, 49, pid)
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
    marker = f"{PROCESS_FAMILY_TOKEN_ENV}={token}".encode("utf-8")
    result: list[int] = []
    excluded = {os.getpid()}
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


def _signal_processes(pids: list[int], sig: signal.Signals) -> None:
    for pid in pids:
        try:
            os.kill(pid, sig)
        except ProcessLookupError:
            pass


def clean_process_family(token: str, *, original_pgid: int | None) -> dict[str, Any]:
    try:
        if original_pgid is not None:
            try:
                os.killpg(original_pgid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
        marked = enumerate_process_family(token)
        if marked:
            _signal_processes(marked, signal.SIGSTOP)
            _signal_processes(marked, signal.SIGTERM)
            deadline = time.monotonic() + 0.25
            while time.monotonic() < deadline and enumerate_process_family(token):
                time.sleep(0.02)
            marked = enumerate_process_family(token)
            if marked:
                _signal_processes(marked, signal.SIGKILL)
                deadline = time.monotonic() + 2.0
                while time.monotonic() < deadline and enumerate_process_family(token):
                    time.sleep(0.02)
        remaining = enumerate_process_family(token)
    except (OSError, subprocess.SubprocessError, RuntimeError) as exc:
        raise RuntimeError(f"PROCESS_FAMILY_CLEANUP_INCOMPLETE: {exc}") from exc
    if remaining:
        raise RuntimeError("PROCESS_FAMILY_CLEANUP_INCOMPLETE: marked processes remain")
    return {
        "token_sha256": hashlib.sha256(token.encode("utf-8")).hexdigest(),
        "same_uid_only": True,
        "confirmed_empty": True,
        "trust_boundary": PROCESS_FAMILY_TRUST_BOUNDARY,
    }


def _run_in_process_group(
    argv: list[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
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
            output=_subprocess_output_text(stdout)
            or _subprocess_output_text(first_timeout.stdout),
            stderr=_subprocess_output_text(stderr)
            or _subprocess_output_text(first_timeout.stderr),
        )
        timeout_error.process_family_policy = family_policy
        raise timeout_error from first_timeout
    family_policy = clean_process_family(token, original_pgid=None)
    completed = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    completed.process_family_policy = family_policy
    completed.pid = process.pid
    return completed


def command_prove_stop(args: argparse.Namespace) -> int:
    """Exclusively execute the frozen recipe, then authorize its all-true gate."""
    state_dir, state = load_state(args.state_dir)
    if state.get("status") != "active":
        fail("LOOP_TERMINAL", "only an active loop can prove STOP")
    policy = state["workflow_policy"]
    if policy.get("stop_authority") != "controller_prove_stop":
        fail(
            "PROVE_STOP_NOT_CONFIGURED",
            "this workflow does not assign STOP authority to prove-stop",
        )
    require_execution_prefix(
        state,
        EXTERNAL_EXECUTION_STEPS,
        code="WORKFLOW_STEPS_INCOMPLETE",
    )
    open_findings = sorted(
        finding_id
        for finding_id, item in state["finding_ledger"].items()
        if item["status"] == "open"
    )
    if open_findings:
        fail(
            "OPEN_FINDINGS_REMAIN",
            f"prove-stop is blocked by open findings: {', '.join(open_findings)}",
        )
    carried = state["iterations"][-1]["carried_findings"]
    stale_closures = [
        finding_id
        for finding_id in carried
        if (
            state["finding_ledger"].get(finding_id, {}).get("status") != "closed"
            or state["finding_ledger"][finding_id]["closure"]["round"]
            != state["current_round"]
        )
    ]
    if stale_closures:
        fail(
            "CARRIED_FINDING_NOT_CLOSED",
            "carried findings lack a closure in the current round: "
            + ", ".join(stale_closures),
        )
    producer_value = policy.get("gate_producer")
    if not isinstance(producer_value, str) or not producer_value:
        fail("PROVE_STOP_NOT_CONFIGURED", "gate producer is not configured")
    repo_root = Path(state["repo_root"])
    producer_path, _ = resolve_repo_path(
        repo_root,
        producer_value,
        outside_code="GATE_PRODUCER_INVALID",
        require_file=True,
    )
    eval_root, _ = resolve_repo_path(
        repo_root,
        args.eval_root,
        outside_code="EVAL_ROOT_INVALID",
        require_file=False,
    )
    if not eval_root.is_dir() or eval_root.is_symlink():
        fail("EVAL_ROOT_INVALID", "eval root must be a regular in-repository directory")
    review_paths: list[Path] = []
    for value in (args.p0_review, args.p1_review):
        path, _ = resolve_repo_path(
            repo_root,
            value,
            outside_code="REVIEW_ATTESTATION_INVALID",
            require_file=True,
        )
        review_paths.append(path)
    recheck_entry = next(
        (
            entry
            for entry in state["iterations"][-1]["step_ledger"]
            if entry["step_id"] == "independent_recheck"
        ),
        None,
    )
    if not isinstance(recheck_entry, dict):
        fail(
            "STOP_REVIEW_LINEAGE_INVALID",
            "independent recheck review evidence is absent",
        )
    primary = next(
        (
            item
            for item in recheck_entry["artifacts"]
            if item["role"] == PHASE_PRIMARY_ROLES["independent_recheck"]
        ),
        None,
    )
    if not isinstance(primary, dict):
        fail(
            "STOP_REVIEW_LINEAGE_INVALID",
            "independent recheck primary evidence is absent",
        )
    recheck_payload_path, _ = resolve_repo_path(
        repo_root,
        primary["path"],
        outside_code="STOP_REVIEW_LINEAGE_INVALID",
        require_file=True,
    )
    recheck_payload = read_object(
        recheck_payload_path,
        "STOP_REVIEW_LINEAGE_INVALID",
        "independent recheck payload",
    )
    references = recheck_payload.get("result", {}).get("review_attestations")
    expected_by_type = {
        reference.get("attestation_type"): reference
        for reference in references
        if isinstance(reference, dict)
    } if isinstance(references, list) else {}
    for attestation_type, path in zip(
        ("p0_zero", "reproducible_p1_zero"), review_paths, strict=True
    ):
        reference = expected_by_type.get(attestation_type)
        relative = path.relative_to(repo_root).as_posix()
        if (
            not isinstance(reference, dict)
            or reference.get("path") != relative
            or reference.get("sha256") != file_sha256(path)
        ):
            fail(
                "STOP_REVIEW_LINEAGE_INVALID",
                "prove-stop review pair differs from independent recheck evidence",
            )

    require_unchanged_source_manifest(repo_root, state)
    before_snapshot = source_snapshot(repo_root, state["source_files"])
    if before_snapshot != state["source_snapshot"]:
        fail(
            "SOURCE_DRIFT_INVALIDATED_GATE",
            "source changed before executable proof began",
        )
    producer_sha_before = file_sha256(producer_path)
    iteration_id_value = state["iterations"][-1]["iteration_id"]
    attempt_id = f"{iteration_id_value}-{uuid.uuid4().hex[:12]}"
    output_dir = state_dir / "proofs" / attempt_id
    argv = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        str(producer_path),
        "--repo-root",
        str(repo_root),
        "--state-file",
        str(state_path(state_dir)),
        "--eval-root",
        str(eval_root),
        "--p0-review",
        str(review_paths[0]),
        "--p1-review",
        str(review_paths[1]),
        "--output-dir",
        str(output_dir),
    ]
    environment = _isolated_environment()
    try:
        completed = _run_in_process_group(
            argv,
            cwd=repo_root,
            environment=environment,
            timeout_seconds=PRODUCER_TIMEOUT_SECONDS,
        )
        timed_out = False
        stdout = completed.stdout
        stderr = completed.stderr
        exit_code: int | None = completed.returncode
        process_family_policy = getattr(
            completed,
            "process_family_policy",
            {
                "token_sha256": None,
                "same_uid_only": True,
                "confirmed_empty": False,
                "trust_boundary": PROCESS_FAMILY_TRUST_BOUNDARY,
            },
        )
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = _subprocess_output_text(exc.stdout)
        stderr = _subprocess_output_text(exc.stderr)
        exit_code = None
        process_family_policy = getattr(
            exc,
            "process_family_policy",
            {
                "token_sha256": None,
                "same_uid_only": True,
                "confirmed_empty": False,
                "trust_boundary": PROCESS_FAMILY_TRUST_BOUNDARY,
            },
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    after_snapshot = source_snapshot(repo_root, state["source_files"])
    producer_sha_after = file_sha256(producer_path)
    controller_receipt = {
        "schema_version": SCHEMA_VERSION,
        "authority": "controller_prove_stop",
        "recipe_version": PRODUCER_RECIPE_VERSION,
        "attempt_id": attempt_id,
        "argv": argv,
        "cwd": str(repo_root),
        "timeout_seconds": PRODUCER_TIMEOUT_SECONDS,
        "shell": False,
        "environment_policy": {
            "PYTHONPATH": "removed",
            "PYTHONHOME": "removed",
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        "exit_code": exit_code,
        "timed_out": timed_out,
        "stdout": stdout,
        "stderr": stderr,
        "process_family_policy": process_family_policy,
        "source_before_sha256": before_snapshot["sha256"],
        "source_after_sha256": after_snapshot["sha256"],
        "producer_before_sha256": producer_sha_before,
        "producer_after_sha256": producer_sha_after,
        "live_tree_diverged_after_snapshot": after_snapshot != before_snapshot,
        "release_subject": "retained_release_basis_not_live_tree",
    }
    atomic_write_json(output_dir / "controller-producer-receipt.json", controller_receipt)
    retained_basis_parent = output_dir / "release-bases"
    retained_basis_present = (
        retained_basis_parent.is_dir()
        and not retained_basis_parent.is_symlink()
        and any(
            path.is_dir()
            and not path.is_symlink()
            and (path / "snapshot-index.json").is_file()
            for path in retained_basis_parent.iterdir()
        )
    )
    if after_snapshot != before_snapshot and not retained_basis_present:
        fail(
            "SOURCE_DRIFT_DURING_PROOF",
            "live source changed before a retained release basis was produced",
        )
    if timed_out:
        fail("PROVE_STOP_TIMEOUT", "release gate producer exceeded its named timeout")
    if exit_code != 0:
        fail(
            "PROVE_STOP_FAILED",
            "release gate producer failed; inspect the retained raw receipt",
        )
    try:
        producer_result = json.loads(stdout)
    except json.JSONDecodeError as exc:
        fail("GATE_PRODUCER_INVALID", f"producer output is not JSON: {exc}")
    if (
        not isinstance(producer_result, dict)
        or producer_result.get("valid") is not True
        or not isinstance(producer_result.get("gate"), str)
    ):
        fail("GATE_PRODUCER_INVALID", "producer did not return a valid gate path")
    gate_path, _ = resolve_repo_path(
        repo_root,
        producer_result["gate"],
        outside_code="GATE_PRODUCER_INVALID",
        require_file=True,
    )
    gate = read_object(gate_path, "GATE_PRODUCER_INVALID", "producer gate")
    validate_gate_shape(gate)
    if (
        gate.get("iteration_id") != iteration_id_value
        or gate.get("source_sha256") != state["source_snapshot"]["sha256"]
    ):
        fail("GATE_PRODUCER_INVALID", "producer gate is stale for this iteration")
    validate_gate_evidence(
        repo_root,
        gate,
        iteration_id_value=iteration_id_value,
        source_sha256=state["source_snapshot"]["sha256"],
    )
    terminal_artifact_dir = output_dir / "terminal-artifacts"
    terminal_documents = {
        "clean_install": {
            "schema_version": SCHEMA_VERSION,
            "step_id": "clean_install",
            "source_sha256": state["source_snapshot"]["sha256"],
            "evidence": {
                "clean_install": gate["evidence"]["clean_install"],
                "verify_install": gate["evidence"]["verify_install"],
            },
        },
        "rollback_validation": {
            "schema_version": SCHEMA_VERSION,
            "step_id": "rollback_validation",
            "source_sha256": state["source_snapshot"]["sha256"],
            "evidence": {"rollback": gate["evidence"]["rollback"]},
        },
        "evidence_gate": {
            "schema_version": SCHEMA_VERSION,
            "step_id": "evidence_gate",
            "source_sha256": state["source_snapshot"]["sha256"],
            "gate": {
                "path": gate_path.relative_to(repo_root).as_posix(),
                "sha256": file_sha256(gate_path),
            },
        },
        "loop_decision": {
            "schema_version": SCHEMA_VERSION,
            "step_id": "loop_decision",
            "source_sha256": state["source_snapshot"]["sha256"],
            "decision": "STOP",
            "controller_receipt": {
                "path": (output_dir / "controller-producer-receipt.json")
                .relative_to(repo_root)
                .as_posix(),
                "sha256": file_sha256(
                    output_dir / "controller-producer-receipt.json"
                ),
            },
        },
    }
    terminal_artifacts: dict[str, dict[str, str]] = {}
    for step_id, document in terminal_documents.items():
        artifact_path = terminal_artifact_dir / f"{step_id}.json"
        atomic_write_json(artifact_path, document)
        terminal_artifacts[step_id] = {
            "role": f"{step_id}_evidence",
            "path": artifact_path.relative_to(repo_root).as_posix(),
            "sha256": file_sha256(artifact_path),
        }
    controller_step_receipts = write_controller_step_receipts(
        state,
        output_dir / "workflow-receipts",
        terminal_artifacts,
        execution_id=attempt_id,
    )
    advance_args = argparse.Namespace(
        state_dir=str(state_dir),
        gate=str(gate_path),
        finding=None,
        red_test=None,
        stop_authorized=True,
        controller_step_receipts=controller_step_receipts,
    )
    return command_advance(advance_args)


def command_resume(args: argparse.Namespace) -> int:
    state_dir, current = load_state(args.state_dir)
    pending_path = state_dir / PENDING_FILE
    if not pending_path.exists():
        repo_root = Path(current["repo_root"])
        retained_stop = (
            current.get("status") == "completed"
            and current.get("decision") == "STOP"
            and isinstance(current.get("release_basis"), dict)
        )
        if retained_stop:
            validate_release_basis_reference(repo_root, current["release_basis"])
            emit(current)
            return 0
        require_unchanged_source_manifest(repo_root, current)
        snapshot = source_snapshot(repo_root, current["source_files"])
        iteration = current["iterations"][-1]
        pending_epoch = iteration.get("pending_source_epoch")
        if isinstance(pending_epoch, dict):
            authorized_snapshots = (
                (
                    pending_epoch["source_before_sha256"],
                    pending_epoch["source_before_files"],
                ),
                (
                    pending_epoch["red_source_sha256"],
                    pending_epoch["red_source_files"],
                ),
                (
                    pending_epoch["source_after_sha256"],
                    pending_epoch["source_after_files"],
                ),
            )
            if any(
                snapshot["sha256"] == expected_sha256
                and snapshot["files"] == expected_files
                for expected_sha256, expected_files in authorized_snapshots
            ):
                emit(current)
                return 0
        recoverable_status = current.get("status") == "active" or (
            current.get("status") == "completed"
            and current.get("decision") == "STOP"
        )
        if recoverable_status and snapshot != current["source_snapshot"]:
            recovered = source_drift_transition(current, current, snapshot)
            commit_transition(state_dir, current, recovered)
            emit(recovered)
            return 0
        emit(current)
        return 0
    intent = read_object(pending_path, "TRANSACTION_INVALID", "pending transition")
    after = intent.get("after_state")
    if (
        intent.get("schema_version") != SCHEMA_VERSION
        or intent.get("status") not in {"prepared", "committed", "aborted"}
        or not isinstance(intent.get("transaction_id"), str)
        or not isinstance(after, dict)
        or not _is_sha256(intent.get("before_state_sha256"))
        or not _is_sha256(intent.get("after_state_sha256"))
        or intent.get("after_state_sha256") != canonical_sha256(after)
    ):
        fail("TRANSACTION_INVALID", "pending transition is malformed")
    validate_state_shape(after)
    repo_root = Path(current["repo_root"])
    retained_stop = (
        after.get("status") == "completed"
        and after.get("decision") == "STOP"
        and isinstance(after.get("release_basis"), dict)
    )
    retained_source_root: Path | None = None
    if retained_stop:
        validate_release_basis_reference(repo_root, after["release_basis"])
        retained_root, _ = resolve_repo_path(
            repo_root,
            after["release_basis"]["root_path"],
            outside_code="RELEASE_BASIS_INVALID",
        )
        retained_source_root = retained_root / "source"
    try:
        validate_persisted_gate_evidence(repo_root, after)
        validate_persisted_red_tests(retained_source_root or repo_root, after)
        validate_persisted_step_evidence(
            repo_root,
            after,
            frozen_source_root=retained_source_root,
        )
        validate_persisted_finding_evidence(repo_root, after)
    except LoopError as exc:
        observed = source_snapshot(repo_root, current["source_files"])
        archive_aborted_transition(
            state_dir,
            intent,
            reason=f"state_evidence_invalid:{exc.code}",
            observed_snapshot=observed,
        )
        if exc.code == "STATE_EVIDENCE_INVALID":
            raise
        fail(
            "STATE_EVIDENCE_INVALID",
            f"prepared transition evidence is invalid: {exc.code}: {exc.message}",
        )
    current_hash = canonical_sha256(current)
    before_matches = current_hash == intent.get("before_state_sha256")
    after_matches = current_hash == intent.get("after_state_sha256")
    if not before_matches and not after_matches:
        fail("TRANSACTION_CONFLICT", "state matches neither side of pending transition")

    if retained_stop:
        validate_release_basis_reference(repo_root, after["release_basis"])
    else:
        require_unchanged_source_manifest(repo_root, current)
    snapshot = (
        after.get("observed_source_snapshot", after["source_snapshot"])
        if retained_stop
        else source_snapshot(repo_root, current["source_files"])
    )
    source_drifted = snapshot["sha256"] != after["source_snapshot"]["sha256"]

    if intent["status"] == "committed":
        if not after_matches:
            fail("TRANSACTION_CONFLICT", "committed transition state is not published")
        archive_committed_transition(state_dir, intent)
    elif intent["status"] == "aborted":
        archive_aborted_transition(
            state_dir,
            intent,
            reason=str(intent.get("abort_reason", "recovery")),
            observed_snapshot=intent.get("observed_source_snapshot", snapshot),
        )
    elif source_drifted and not retained_stop:
        if after_matches:
            archive_committed_transition(state_dir, intent)
        else:
            archive_aborted_transition(
                state_dir,
                intent,
                reason="source_drift",
                observed_snapshot=snapshot,
            )
    else:
        if before_matches:
            atomic_write_json(state_path(state_dir), after)
            current = after
        archive_committed_transition(state_dir, intent)

    if source_drifted and not retained_stop:
        # Recovery must continue from the state that was actually published.
        # A prepared transition whose after-state never reached loop-state.json
        # is archived as aborted above and cannot contribute findings, fixes,
        # closures, or step receipts to the recovered round.
        recovered = source_drift_transition(current, current, snapshot)
        commit_transition(state_dir, current, recovered)
        current = recovered
    emit(current)
    return 0


def command_guard(args: argparse.Namespace) -> int:
    _, state = load_state(args.state_dir)
    operation = args.operation
    denial_codes = {
        "delete": "DELETE_DENIED",
        "push": "PUSH_DENIED",
        "publish": "PUBLISH_DENIED",
    }
    if operation in denial_codes:
        fail(denial_codes[operation], f"{operation} is outside this controller's authority")
    if operation != "write":
        fail("OPERATION_DENIED", f"unsupported operation: {operation}")
    if not args.path:
        fail("PATH_REQUIRED", "write proposals require a path")

    repo_root = Path(state["repo_root"])
    relative = lexical_relative(repo_root, args.path, "PATH_OUTSIDE_REPO")
    if protected_path(relative):
        fail("PROTECTED_PATH", f"path is protected: {relative.as_posix()}")
    candidate = repo_root.joinpath(*relative.parts)
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(repo_root)
    except ValueError:
        fail("PATH_SYMLINK_ESCAPE", f"path escapes through a symbolic link: {args.path}")
    if not any(
        path_is_within(relative, PurePosixPath(item))
        for item in state["allowed_write_roots"]
    ):
        fail("WRITE_SCOPE_DENIED", f"path is outside configured write roots: {relative}")
    emit({"allowed": True, "operation": "write", "path": relative.as_posix()})
    return 0


def parser() -> argparse.ArgumentParser:
    root = StructuredArgumentParser(description=__doc__)
    subparsers = root.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start")
    start.add_argument("--repo-root", required=True)
    start.add_argument("--workflow", required=True)
    start.add_argument("--state-dir", required=True)
    start.add_argument("--source-file", action="append", default=[])
    start.add_argument("--allow-write", action="append", required=True)
    start.add_argument("--max-rounds", required=True, type=int)
    start.set_defaults(handler=command_start)

    advance = subparsers.add_parser("advance")
    advance.add_argument("--state-dir", required=True)
    advance.add_argument("--gate", required=True)
    advance.add_argument("--finding")
    advance.add_argument("--red-test")
    advance.set_defaults(handler=command_advance)

    begin_step = subparsers.add_parser("begin-step")
    begin_step.add_argument("--state-dir", required=True)
    begin_step.add_argument("--step-id", required=True)
    begin_step.set_defaults(handler=command_begin_step)

    authorize_fix = subparsers.add_parser("authorize-fix")
    authorize_fix.add_argument("--state-dir", required=True)
    authorize_fix.add_argument("--plan", required=True)
    authorize_fix.set_defaults(handler=command_authorize_fix)

    record_step = subparsers.add_parser("record-step")
    record_step.add_argument("--state-dir", required=True)
    record_step.add_argument("--step-id", required=True)
    record_step.add_argument("--receipt", required=True)
    record_step.set_defaults(handler=command_record_step)

    run_next = subparsers.add_parser("run-next")
    run_next.add_argument("--state-dir", required=True)
    run_next.set_defaults(handler=command_run_next)

    prove_stop = subparsers.add_parser("prove-stop")
    prove_stop.add_argument("--state-dir", required=True)
    prove_stop.add_argument("--eval-root", required=True)
    prove_stop.add_argument("--p0-review", required=True)
    prove_stop.add_argument("--p1-review", required=True)
    prove_stop.set_defaults(handler=command_prove_stop)

    resume = subparsers.add_parser("resume")
    resume.add_argument("--state-dir", required=True)
    resume.set_defaults(handler=command_resume)

    guard = subparsers.add_parser("guard")
    guard.add_argument("--state-dir", required=True)
    guard.add_argument("--operation", required=True)
    guard.add_argument("--path")
    guard.set_defaults(handler=command_guard)
    return root


def main(argv: list[str] | None = None) -> int:
    try:
        args = parser().parse_args(argv)
        if args.command in {
            "advance",
            "begin-step",
            "authorize-fix",
            "record-step",
            "run-next",
            "prove-stop",
            "resume",
            "guard",
        }:
            with controller_lock(args.state_dir):
                return int(args.handler(args))
        return int(args.handler(args))
    except LoopError as exc:
        emit({"allowed": False, "error": {"code": exc.code, "message": exc.message}})
        return exc.exit_code
    except (OSError, UnicodeError) as exc:
        emit(
            {
                "allowed": False,
                "error": {"code": "IO_ERROR", "message": str(exc)},
            }
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
