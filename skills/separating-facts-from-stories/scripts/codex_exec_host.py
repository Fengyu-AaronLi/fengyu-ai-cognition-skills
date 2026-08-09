#!/usr/bin/env python3
"""Launch one fresh Codex CLI process and retain host-observed evidence.

The child model never authors this receipt.  The parent process derives the
local process identity, Codex thread identifier, command, hashes, and outcome
from the invocation it performed.  This proves a bounded local observation,
not external reviewer identity and not cryptographic resistance to a malicious
same-UID host operator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any


SCHEMA_VERSION = "1.0.0"
RECEIPT_TYPE = "host_execution_receipt.v1"
TRUST_BOUNDARY = (
    "controller_observed_local_codex_process_and_thread_not_external_identity_proof"
)
ISOLATION_DESCRIPTION = "fresh codex exec --ephemeral; no resume; host observed"
REVIEW_PAYLOAD_SCHEMA_VERSION = "review_payload.v2"
REVIEW_ATTESTATION_SCHEMA_VERSION = "1.4.0"
REVIEW_SOURCE_IDENTITY_SCHEMA_VERSION = "review_source_identity.v1"
REVIEW_SCOPE = (
    "runtime_semantics",
    "safety_routing",
    "state_integrity",
    "release_evidence",
    "packaging_installation",
    "documentation_claims",
)
EVAL_NO_CASEFILE_CASES = {
    "translation-non-trigger",
    "validator-rejects-epistemic-violations",
    "sourced-timeline-passthrough",
}
EVAL_PASSTHROUGH_CASES = {
    "translation-non-trigger",
    "sourced-timeline-passthrough",
}
EVAL_VERSIONED_CASE = "versioned-evidence-update"
EVAL_RUNTIME_DIRECTORY = ".runtime"
EVAL_RUNTIME_INPUT_PATTERN = "input-{revision}.txt"
EVAL_RUNTIME_WORKSPACE_PATTERN = "workspace-{revision}"
EXECUTION_KINDS = {"eval", "review", "phase"}
SANDBOX_MODES = {"read-only", "workspace-write"}
REASONING_EFFORTS = {"low", "medium", "high", "xhigh"}
DEFAULT_TIMEOUT_SECONDS = 900
MAX_TIMEOUT_SECONDS = 3600
ARTIFACT_NAMES = {
    "prompt": "prompt.txt",
    "events": "events.jsonl",
    "stderr": "stderr.txt",
    "last_message": "last-message.txt",
}
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
EVAL_MODEL = "gpt-5.5"
EVAL_REASONING_EFFORT = "high"
EVAL_SANDBOX = "workspace-write"
REVIEW_MODEL = "gpt-5.5"
REVIEW_REASONING_EFFORT = "high"
REVIEW_SANDBOX = "read-only"
REVIEW_OUTPUT_ROOT = PurePosixPath(".ao-output/reviews")


class HostExecutionError(RuntimeError):
    pass


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _eval_artifact_contract(case_id: str) -> str:
    artifacts, receipts = _required_eval_artifacts(case_id)
    artifact_lines = "\n".join(f"  - {item}" for item in artifacts) or "  - none"
    receipt_lines = "\n".join(f"  - {item}" for item in receipts) or "  - none"
    return (
        "Canonical artifacts that the host will promote after execution:\n"
        f"{artifact_lines}\n"
        "Canonical validator receipts that the host will create or promote:\n"
        f"{receipt_lines}"
    )


def eval_runtime_layout(case_id: str) -> dict[str, list[str]]:
    """Return fixed model-readable inputs and the only allowed workspaces."""
    revisions = 2 if case_id == EVAL_VERSIONED_CASE else 1
    input_paths = [
        f"{EVAL_RUNTIME_DIRECTORY}/"
        f"{EVAL_RUNTIME_INPUT_PATTERN.format(revision=revision)}"
        for revision in range(1, revisions + 1)
    ]
    workspace_paths = (
        []
        if case_id == "validator-rejects-epistemic-violations"
        else [
            f"{EVAL_RUNTIME_DIRECTORY}/"
            f"{EVAL_RUNTIME_WORKSPACE_PATTERN.format(revision=revision)}"
            for revision in range(1, revisions + 1)
        ]
    )
    validation_paths = (
        [f"{EVAL_RUNTIME_DIRECTORY}/invalid-validation.json"]
        if case_id == "validator-rejects-epistemic-violations"
        else []
    )
    return {
        "input_paths": input_paths,
        "workspace_paths": workspace_paths,
        "validation_paths": validation_paths,
    }


def _eval_final_response_contract(case_id: str) -> str:
    if case_id == "translation-non-trigger":
        return "Return only the English translation on one line."
    if case_id == "sourced-timeline-passthrough":
        return "Return only the requested bare JSON array, without a Markdown fence."
    if case_id == "validator-rejects-epistemic-violations":
        return (
            "Run the frozen validator against RUNTIME_INVALID_FIXTURE, save its "
            "report at RUNTIME_VALIDATION_RECEIPT, and return exactly that report "
            "JSON as the final message. A validator exit code of 1 is expected."
        )
    if case_id == "json-artifact-and-validation-receipt":
        return (
            'Return only {"artifact_path":"artifacts/separation.json",'
            '"valid":true,"error_count":0} as JSON, with no Markdown fence.'
        )
    if case_id == "versioned-evidence-update":
        return (
            "After both revisions validate, return only the rendered final "
            "revision response, with no preface or postscript."
        )
    if case_id in {
        "immediate-safety-override",
        "safety-interrupt-before-artifact-work",
    }:
        return (
            "Return only the exact bytes of RUNTIME_WORKSPACE_1/"
            "safety-response.md, with no preface or postscript."
        )
    return (
        "After the artifact validates, return only the runtime-rendered final "
        "response, with no preface or postscript."
    )


def build_eval_prompt(*, eval_root: Path, case_dir: Path, case_id: str) -> str:
    """Return the only prompt accepted by the prepared-eval binder."""
    root = eval_root.resolve(strict=True)
    directory = case_dir.resolve(strict=True)
    if any(
        re.search(r"[\x00-\x1f\x7f]", str(value))
        for value in (root, directory, SKILL_DIR)
    ):
        raise HostExecutionError("EVAL_PATH_UNSAFE")
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise HostExecutionError("EVAL_CASE_OUTSIDE_ROOT") from exc
    layout = eval_runtime_layout(case_id)
    input_bindings = "\n".join(
        f"RUNTIME_INPUT_{index}: {directory / relative}"
        for index, relative in enumerate(layout["input_paths"], start=1)
    )
    workspace_bindings = "\n".join(
        f"RUNTIME_WORKSPACE_{index}: {directory / relative}"
        for index, relative in enumerate(layout["workspace_paths"], start=1)
    )
    if not workspace_bindings:
        workspace_bindings = "RUNTIME_WORKSPACES: none"
    special_bindings = ""
    if case_id == "validator-rejects-epistemic-violations":
        special_bindings = (
            f"\nRUNTIME_INVALID_FIXTURE: "
            f"{root / 'runtime-snapshot' / 'evals' / 'fixtures' / 'invalid-epistemic.json'}"
            f"\nRUNTIME_VALIDATION_RECEIPT: "
            f"{directory / layout['validation_paths'][0]}"
        )
    return f"""You are executing one fresh, isolated evaluation of the local Skill.

CASE_ID: {case_id}
CASE_DIR: {directory}
{input_bindings}
{workspace_bindings}
{special_bindings}
EVALUATION_CONTEXT: {root / 'evaluation-context.json'}
SKILL_ENTRYPOINT: {root / 'runtime-snapshot' / 'SKILL.md'}

Evaluation isolation rules:
1. Read user material only from the bound RUNTIME_INPUT files. They contain exact raw text, not a JSON envelope.
2. Read SKILL_ENTRYPOINT and only the runtime or reference files it directly requires for execution.
3. Do not read frozen suite definitions, evaluator tests, auditor source, prior eval roots, results reports, or any other case directory.
4. Do not modify Skill, repository, frozen input, or evaluation context files.
5. If a RUNTIME_WORKSPACE is bound, create and use exactly that nonexistent path with the Skill workflow. Do not create an alternate workspace after an error; use the bounded repair loop or stop.
6. Do not create CASE_DIR/artifacts, CASE_DIR/receipts, raw-output.txt, or case-result.json. The host promotes canonical artifacts and authors the result from the one bound workspace and observed execution evidence.
7. Follow the Skill workflow and its validator. Do not invent validation success or copy a workspace receipt as a canonical receipt.

{_eval_artifact_contract(case_id)}

Final response contract:
{_eval_final_response_contract(case_id)}
"""


def build_review_prompt(
    *, repo_root: Path, attestation_type: str, source_sha256: str
) -> str:
    """Return the only prompt accepted by the review attestation binder."""
    root = repo_root.resolve(strict=True)
    if attestation_type not in {"p0_zero", "reproducible_p1_zero"}:
        raise HostExecutionError("REVIEW_ATTESTATION_TYPE_INVALID")
    if not _is_sha256(source_sha256):
        raise HostExecutionError("SOURCE_SHA256_INVALID")
    if re.search(r"[\x00-\x1f\x7f]", str(root)):
        raise HostExecutionError("REVIEW_PATH_UNSAFE")
    scope = json.dumps(list(REVIEW_SCOPE), ensure_ascii=False, separators=(",", ":"))
    return f"""Perform one fresh independent review of the frozen local candidate.

REPOSITORY_ROOT: {root}
SOURCE_MANIFEST: {root / 'workflows' / 'separating-facts-release-sources.json'}
SOURCE_SHA256: {source_sha256}
ATTESTATION_TYPE: {attestation_type}

Review contract:
1. Do not trust prior review reports, result summaries, release claims, or self-reported pass flags.
2. Inspect the source files declared by SOURCE_MANIFEST and test current behavior where useful.
3. Cover exactly these scopes: {scope}
4. Report only currently reproducible open P0 or P1 findings. P0 can falsely pass a safety or release boundary, corrupt state, or authorize an invalid release. P1 is a reproducible correctness, integrity, or trust-boundary failure that does not meet P0.
5. Do not modify repository files and do not create remediation artifacts.
6. If no qualifying finding remains, use an empty findings array. Never invent a failure to satisfy the attestation name.

Return only one JSON object with exactly this shape, without a Markdown fence or commentary:
{{"schema_version":"{REVIEW_PAYLOAD_SCHEMA_VERSION}","attestation_type":"{attestation_type}","source_sha256":"{source_sha256}","review_scope":{scope},"covered_severities":["P0","P1"],"findings":[{{"finding_id":"stable-kebab-case-id","severity":"P0 or P1","summary":"concise defect","reproducer":"exact deterministic reproduction","actual":"observed result","expected":"required result","reproducible":true,"status":"open"}}]}}
"""


def _is_sha256(value: Any) -> bool:
    return bool(
        isinstance(value, str)
        and re.fullmatch(r"[0-9a-f]{64}", value) is not None
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists() or path.is_symlink():
            raise FileExistsError(path)
        os.replace(temporary, path)
        _fsync_directory(path.parent)
    except BaseException:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass
        raise


def _atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    _atomic_write_bytes(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def _artifact_descriptor(path: Path, receipt_dir: Path) -> dict[str, Any]:
    relative = path.relative_to(receipt_dir).as_posix()
    return {
        "path": relative,
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }


def parse_codex_events(payload: str) -> tuple[dict[str, Any], list[str]]:
    """Derive one thread and one completed turn from Codex JSONL stdout."""
    errors: list[str] = []
    events: list[dict[str, Any]] = []
    for number, raw in enumerate(payload.splitlines(), start=1):
        if not raw.strip():
            continue
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            errors.append(f"HOST_EVENT_JSON_INVALID:{number}")
            continue
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            errors.append(f"HOST_EVENT_SHAPE_INVALID:{number}")
            continue
        events.append(event)
    thread_ids = [
        event.get("thread_id")
        for event in events
        if event.get("type") == "thread.started"
        and isinstance(event.get("thread_id"), str)
        and event["thread_id"].strip()
    ]
    turn_started_count = sum(
        event.get("type") == "turn.started" for event in events
    )
    turn_completed_count = sum(
        event.get("type") == "turn.completed" for event in events
    )
    agent_messages = [
        event["item"].get("text")
        for event in events
        if event.get("type") == "item.completed"
        and isinstance(event.get("item"), dict)
        and event["item"].get("type") == "agent_message"
        and isinstance(event["item"].get("text"), str)
    ]
    if len(thread_ids) != 1 or len(set(thread_ids)) != 1:
        errors.append("HOST_EVENT_THREAD_COUNT_INVALID")
    if turn_started_count != 1:
        errors.append("HOST_EVENT_TURN_STARTED_COUNT_INVALID")
    if turn_completed_count != 1:
        errors.append("HOST_EVENT_TURN_COMPLETED_COUNT_INVALID")
    if not agent_messages:
        errors.append("HOST_EVENT_AGENT_MESSAGE_MISSING")
    derived = {
        "thread_id": thread_ids[0] if len(thread_ids) == 1 else None,
        "turn_started_count": turn_started_count,
        "turn_completed_count": turn_completed_count,
        "agent_message_count": len(agent_messages),
        "last_agent_message": agent_messages[-1] if agent_messages else None,
    }
    return derived, errors


def _terminate_process_group(process: subprocess.Popen[str]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    try:
        process.wait(timeout=2)
        return
    except subprocess.TimeoutExpired:
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def _codex_version(codex_path: Path) -> str:
    completed = subprocess.run(
        [str(codex_path), "--version"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
        shell=False,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise HostExecutionError("CODEX_VERSION_UNAVAILABLE")
    return completed.stdout.strip()


def run_codex_execution(
    *,
    codex_path: Path,
    prompt_path: Path,
    output_dir: Path,
    cwd: Path,
    execution_kind: str,
    subject_id: str,
    model: str,
    reasoning_effort: str,
    sandbox: str,
    timeout_seconds: int,
    input_path: Path | None,
    context_path: Path | None,
    source_sha256: str | None,
) -> Path:
    """Run one non-resumed Codex process and atomically retain its receipt."""
    codex_path = codex_path.resolve(strict=True)
    prompt_path = prompt_path.resolve(strict=True)
    cwd = cwd.resolve(strict=True)
    output_dir = output_dir.resolve(strict=False)
    if execution_kind not in EXECUTION_KINDS:
        raise HostExecutionError("EXECUTION_KIND_INVALID")
    if not subject_id.strip():
        raise HostExecutionError("SUBJECT_ID_REQUIRED")
    if not model.strip():
        raise HostExecutionError("MODEL_REQUIRED")
    if reasoning_effort not in REASONING_EFFORTS:
        raise HostExecutionError("REASONING_EFFORT_INVALID")
    if sandbox not in SANDBOX_MODES:
        raise HostExecutionError("SANDBOX_MODE_INVALID")
    if not 1 <= timeout_seconds <= MAX_TIMEOUT_SECONDS:
        raise HostExecutionError("TIMEOUT_INVALID")
    if output_dir.exists() or output_dir.is_symlink():
        raise FileExistsError(output_dir)
    if not prompt_path.is_file() or prompt_path.is_symlink():
        raise HostExecutionError("PROMPT_INVALID")
    for optional in (input_path, context_path):
        if optional is not None and (
            not optional.resolve(strict=True).is_file() or optional.is_symlink()
        ):
            raise HostExecutionError("BINDING_FILE_INVALID")
    if source_sha256 is not None and not _is_sha256(source_sha256):
        raise HostExecutionError("SOURCE_SHA256_INVALID")

    prompt_bytes = prompt_path.read_bytes()
    try:
        prompt_text = prompt_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HostExecutionError("PROMPT_NOT_UTF8") from exc
    output_dir.mkdir(parents=True, mode=0o700)
    _fsync_directory(output_dir.parent)
    prompt_snapshot = output_dir / ARTIFACT_NAMES["prompt"]
    _atomic_write_bytes(prompt_snapshot, prompt_bytes)
    events_path = output_dir / ARTIFACT_NAMES["events"]
    stderr_path = output_dir / ARTIFACT_NAMES["stderr"]
    last_message_path = output_dir / ARTIFACT_NAMES["last_message"]
    host_run_id = f"host-{uuid.uuid4()}"
    codex_version = _codex_version(codex_path)
    argv = [
        str(codex_path),
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--json",
        "--sandbox",
        sandbox,
        "--model",
        model,
        "--config",
        f'model_reasoning_effort="{reasoning_effort}"',
        "--cd",
        str(cwd),
        "--output-last-message",
        str(last_message_path),
        "-",
    ]
    environment = os.environ.copy()
    environment.pop("PYTHONPATH", None)
    environment.pop("PYTHONHOME", None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    started_at = _utc_now()
    started = time.monotonic()
    process = subprocess.Popen(
        argv,
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment,
        shell=False,
        start_new_session=True,
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(input=prompt_text, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        timed_out = True
        _terminate_process_group(process)
        stdout, stderr = process.communicate()
    duration_ms = int((time.monotonic() - started) * 1000)
    finished_at = _utc_now()
    _atomic_write_bytes(events_path, stdout.encode("utf-8"))
    _atomic_write_bytes(stderr_path, stderr.encode("utf-8"))
    if not last_message_path.exists():
        _atomic_write_bytes(last_message_path, b"")
    elif last_message_path.is_symlink() or not last_message_path.is_file():
        raise HostExecutionError("LAST_MESSAGE_INVALID")
    model_execution, event_errors = parse_codex_events(stdout)
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "receipt_type": RECEIPT_TYPE,
        "trust_boundary": TRUST_BOUNDARY,
        "host_run_id": host_run_id,
        "execution_kind": execution_kind,
        "subject_id": subject_id,
        "started_at": started_at,
        "finished_at": finished_at,
        "command": {
            "codex_cli_path": str(codex_path),
            "codex_cli_sha256": file_sha256(codex_path),
            "codex_cli_version": codex_version,
            "argv": argv,
            "argv_sha256": hashlib.sha256(canonical_bytes(argv)).hexdigest(),
            "cwd": str(cwd),
            "model": model,
            "reasoning_effort": reasoning_effort,
            "sandbox": sandbox,
            "ephemeral": True,
            "resume": False,
            "ignore_user_config": True,
            "ignore_rules": True,
        },
        "process": {
            "pid": process.pid,
            "exit_code": process.returncode,
            "timed_out": timed_out,
            "duration_ms": duration_ms,
        },
        "bindings": {
            "prompt_sha256": hashlib.sha256(prompt_bytes).hexdigest(),
            "input_sha256": (
                file_sha256(input_path.resolve(strict=True))
                if input_path is not None
                else None
            ),
            "context_sha256": (
                file_sha256(context_path.resolve(strict=True))
                if context_path is not None
                else None
            ),
            "source_sha256": source_sha256,
        },
        "model_execution": {
            key: value
            for key, value in model_execution.items()
            if key != "last_agent_message"
        },
        "event_parse_errors": event_errors,
        "artifacts": {
            name: _artifact_descriptor(output_dir / filename, output_dir)
            for name, filename in ARTIFACT_NAMES.items()
        },
    }
    receipt_path = output_dir / "host-execution-receipt.json"
    _atomic_write_json(receipt_path, receipt)
    return receipt_path


def _safe_artifact_path(
    receipt_dir: Path, descriptor: Any
) -> tuple[Path | None, list[str]]:
    errors: list[str] = []
    if (
        not isinstance(descriptor, dict)
        or set(descriptor) != {"path", "sha256", "bytes"}
        or not isinstance(descriptor.get("path"), str)
        or not _is_sha256(descriptor.get("sha256"))
        or type(descriptor.get("bytes")) is not int
        or descriptor["bytes"] < 0
    ):
        return None, ["HOST_ARTIFACT_DESCRIPTOR_INVALID"]
    relative = PurePosixPath(descriptor["path"])
    if (
        relative.is_absolute()
        or relative.as_posix() != descriptor["path"]
        or any(part in {"", ".", ".."} for part in relative.parts)
    ):
        return None, ["HOST_ARTIFACT_PATH_INVALID"]
    path = receipt_dir.joinpath(*relative.parts)
    current = receipt_dir
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            errors.append("HOST_ARTIFACT_SYMLINK_INVALID")
            return None, errors
    if not path.is_file() or path.is_symlink():
        return None, ["HOST_ARTIFACT_MISSING"]
    if path.stat().st_size != descriptor["bytes"]:
        errors.append("HOST_ARTIFACT_SIZE_MISMATCH")
    if file_sha256(path) != descriptor["sha256"]:
        errors.append("HOST_ARTIFACT_HASH_MISMATCH")
    return path, errors


def validate_host_receipt(
    receipt_path: Path,
    *,
    expected_kind: str,
    expected_subject_id: str,
    expected_input_sha256: str | None,
    expected_context_sha256: str | None,
    expected_source_sha256: str | None,
) -> tuple[dict[str, Any], list[str]]:
    """Validate retained bytes and return identity derived from host evidence."""
    errors: list[str] = []
    if not receipt_path.is_file() or receipt_path.is_symlink():
        return {}, ["HOST_EXECUTION_RECEIPT_MISSING"]
    try:
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}, ["HOST_EXECUTION_RECEIPT_INVALID"]
    required = {
        "schema_version",
        "receipt_type",
        "trust_boundary",
        "host_run_id",
        "execution_kind",
        "subject_id",
        "started_at",
        "finished_at",
        "command",
        "process",
        "bindings",
        "model_execution",
        "event_parse_errors",
        "artifacts",
    }
    if not isinstance(receipt, dict) or set(receipt) != required:
        return {}, ["HOST_EXECUTION_RECEIPT_INVALID"]
    if (
        receipt.get("schema_version") != SCHEMA_VERSION
        or receipt.get("receipt_type") != RECEIPT_TYPE
        or receipt.get("trust_boundary") != TRUST_BOUNDARY
        or not isinstance(receipt.get("host_run_id"), str)
        or not receipt["host_run_id"].strip()
        or receipt.get("execution_kind") != expected_kind
        or receipt.get("subject_id") != expected_subject_id
    ):
        errors.append("HOST_EXECUTION_RECEIPT_INVALID")
    command = receipt.get("command")
    command_fields = {
        "codex_cli_path",
        "codex_cli_sha256",
        "codex_cli_version",
        "argv",
        "argv_sha256",
        "cwd",
        "model",
        "reasoning_effort",
        "sandbox",
        "ephemeral",
        "resume",
        "ignore_user_config",
        "ignore_rules",
    }
    if (
        not isinstance(command, dict)
        or set(command) != command_fields
        or not isinstance(command.get("argv"), list)
        or not command["argv"]
        or any(not isinstance(item, str) or not item for item in command["argv"])
        or command.get("argv_sha256")
        != hashlib.sha256(canonical_bytes(command.get("argv", []))).hexdigest()
        or not _is_sha256(command.get("codex_cli_sha256"))
        or command.get("sandbox") not in SANDBOX_MODES
        or command.get("reasoning_effort") not in REASONING_EFFORTS
        or command.get("ephemeral") is not True
        or command.get("resume") is not False
        or command.get("ignore_user_config") is not True
        or command.get("ignore_rules") is not True
    ):
        errors.append("HOST_COMMAND_INVALID")
    else:
        cli_path = Path(command["codex_cli_path"])
        if (
            not cli_path.is_file()
            or cli_path.is_symlink()
            or file_sha256(cli_path) != command["codex_cli_sha256"]
        ):
            errors.append("HOST_CODEX_BINARY_CHANGED")
    process = receipt.get("process")
    if (
        not isinstance(process, dict)
        or set(process) != {"pid", "exit_code", "timed_out", "duration_ms"}
        or type(process.get("pid")) is not int
        or process["pid"] <= 0
        or process.get("exit_code") != 0
        or process.get("timed_out") is not False
        or type(process.get("duration_ms")) is not int
        or process["duration_ms"] < 0
    ):
        errors.append("HOST_PROCESS_RESULT_INVALID")
    bindings = receipt.get("bindings")
    expected_bindings = {
        "input_sha256": expected_input_sha256,
        "context_sha256": expected_context_sha256,
        "source_sha256": expected_source_sha256,
    }
    if (
        not isinstance(bindings, dict)
        or set(bindings)
        != {"prompt_sha256", "input_sha256", "context_sha256", "source_sha256"}
        or not _is_sha256(bindings.get("prompt_sha256"))
        or any(bindings.get(key) != value for key, value in expected_bindings.items())
    ):
        errors.append("HOST_BINDING_MISMATCH")
    artifacts = receipt.get("artifacts")
    artifact_paths: dict[str, Path] = {}
    if not isinstance(artifacts, dict) or set(artifacts) != set(ARTIFACT_NAMES):
        errors.append("HOST_ARTIFACT_SET_INVALID")
    else:
        for role, descriptor in artifacts.items():
            path, artifact_errors = _safe_artifact_path(
                receipt_path.parent, descriptor
            )
            errors.extend(artifact_errors)
            if path is not None:
                artifact_paths[role] = path
    observed_execution: dict[str, Any] = {}
    if "events" in artifact_paths:
        observed_execution, event_errors = parse_codex_events(
            artifact_paths["events"].read_text(encoding="utf-8")
        )
        if event_errors:
            errors.append("HOST_EVENT_STREAM_INVALID")
        stored = receipt.get("model_execution")
        expected_stored = {
            key: value
            for key, value in observed_execution.items()
            if key != "last_agent_message"
        }
        if stored != expected_stored or receipt.get("event_parse_errors") != event_errors:
            errors.append("HOST_EVENT_DERIVATION_MISMATCH")
    if "last_message" in artifact_paths and observed_execution.get(
        "last_agent_message"
    ) is not None:
        last_message = artifact_paths["last_message"].read_text(encoding="utf-8")
        if last_message.strip() != observed_execution["last_agent_message"].strip():
            errors.append("HOST_LAST_MESSAGE_MISMATCH")
    derived = {
        "host_run_id": receipt.get("host_run_id"),
        "thread_id": observed_execution.get("thread_id"),
        "turn_started_count": observed_execution.get("turn_started_count"),
        "turn_completed_count": observed_execution.get("turn_completed_count"),
        "agent_message_count": observed_execution.get("agent_message_count"),
        "model": command.get("model") if isinstance(command, dict) else None,
        "reasoning_effort": (
            command.get("reasoning_effort") if isinstance(command, dict) else None
        ),
        "sandbox": command.get("sandbox") if isinstance(command, dict) else None,
        "cwd": command.get("cwd") if isinstance(command, dict) else None,
        "prompt_path": (
            str(artifact_paths["prompt"].resolve())
            if "prompt" in artifact_paths
            else None
        ),
        "last_message_path": (
            str(artifact_paths["last_message"].resolve())
            if "last_message" in artifact_paths
            else None
        ),
        "trust_boundary": TRUST_BOUNDARY,
    }
    return derived, sorted(set(errors))


def _repo_relative_regular_file(repo_root: Path, path: Path) -> tuple[Path, str]:
    root = repo_root.resolve(strict=True)
    candidate = path if path.is_absolute() else root / path
    try:
        lexical_relative = candidate.relative_to(root)
    except ValueError as exc:
        raise HostExecutionError("REVIEW_EVIDENCE_OUTSIDE_REPOSITORY") from exc
    if any(part in {"", ".", ".."} for part in lexical_relative.parts):
        raise HostExecutionError("REVIEW_EVIDENCE_OUTSIDE_REPOSITORY")
    current = root
    for part in lexical_relative.parts:
        current = current / part
        if current.is_symlink():
            raise HostExecutionError("REVIEW_EVIDENCE_SYMLINK_INVALID")
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(root)
    except (FileNotFoundError, ValueError) as exc:
        raise HostExecutionError("REVIEW_EVIDENCE_OUTSIDE_REPOSITORY") from exc
    if not resolved.is_file() or resolved.is_symlink():
        raise HostExecutionError("REVIEW_EVIDENCE_FILE_INVALID")
    return resolved, relative.as_posix()


def _validated_review_source_identity(
    *,
    repo_root: Path,
    receipt_path: Path,
    expected_source_sha256: str,
    source_root: Path | None = None,
    verify_source_files: bool = True,
) -> tuple[Path, str]:
    identity_path, identity_relative = _repo_relative_regular_file(
        repo_root, receipt_path.parent.parent / "source-identity.json"
    )
    try:
        identity = json.loads(identity_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HostExecutionError("REVIEW_SOURCE_IDENTITY_INVALID") from exc
    required = {
        "schema_version",
        "source_sha256",
        "files",
        "manifest_path",
        "manifest_sha256",
    }
    if (
        not isinstance(identity, dict)
        or set(identity) != required
        or identity.get("schema_version") != REVIEW_SOURCE_IDENTITY_SCHEMA_VERSION
        or identity.get("source_sha256") != expected_source_sha256
        or not isinstance(identity.get("files"), dict)
        or not identity["files"]
        or list(identity["files"]) != sorted(identity["files"])
        or any(
            not isinstance(relative, str)
            or not relative
            or not _is_sha256(digest)
            for relative, digest in identity["files"].items()
        )
        or hashlib.sha256(canonical_bytes(identity["files"])).hexdigest()
        != expected_source_sha256
        or not isinstance(identity.get("manifest_path"), str)
        or identity["manifest_path"] not in identity["files"]
        or identity.get("manifest_sha256")
        != identity["files"].get(identity["manifest_path"])
    ):
        raise HostExecutionError("REVIEW_SOURCE_IDENTITY_INVALID")
    if verify_source_files:
        root = (source_root or repo_root).resolve(strict=True)
        for relative, digest in identity["files"].items():
            path, normalized = _repo_relative_regular_file(root, Path(relative))
            if normalized != relative or file_sha256(path) != digest:
                raise HostExecutionError("REVIEW_SOURCE_IDENTITY_DRIFT")
        manifest_path, _ = _repo_relative_regular_file(
            root, Path(identity["manifest_path"])
        )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise HostExecutionError("REVIEW_SOURCE_IDENTITY_INVALID") from exc
        if (
            not isinstance(manifest, dict)
            or set(manifest) != {"schema_version", "source_files"}
            or manifest.get("schema_version") != "1.0.0"
            or manifest.get("source_files") != list(identity["files"])
        ):
            raise HostExecutionError("REVIEW_SOURCE_IDENTITY_INVALID")
    return identity_path, identity_relative


def derive_review_attestation(
    *,
    receipt_path: Path,
    repo_root: Path,
    attestation_type: str,
    source_sha256: str,
    source_root: Path | None = None,
    verify_source_files: bool = True,
) -> dict[str, Any]:
    """Derive a review report from one host-observed Codex last message."""
    if attestation_type not in {"p0_zero", "reproducible_p1_zero"}:
        raise HostExecutionError("REVIEW_ATTESTATION_TYPE_INVALID")
    if not _is_sha256(source_sha256):
        raise HostExecutionError("SOURCE_SHA256_INVALID")
    receipt_path, receipt_relative = _repo_relative_regular_file(
        repo_root, receipt_path
    )
    root = repo_root.resolve(strict=True)
    receipt_parts = PurePosixPath(receipt_relative).parts
    review_prefix = REVIEW_OUTPUT_ROOT.parts
    if (
        len(receipt_parts) != len(review_prefix) + 3
        or receipt_parts[: len(review_prefix)] != review_prefix
        or not receipt_parts[len(review_prefix)].strip()
        or receipt_parts[-2] != attestation_type
        or receipt_parts[-1] != "host-execution-receipt.json"
    ):
        raise HostExecutionError("REVIEW_EXECUTION_CONTRACT_MISMATCH")
    identity_path, identity_relative = _validated_review_source_identity(
        repo_root=root,
        receipt_path=receipt_path,
        expected_source_sha256=source_sha256,
        source_root=source_root,
        verify_source_files=verify_source_files,
    )
    derived, errors = validate_host_receipt(
        receipt_path,
        expected_kind="review",
        expected_subject_id=attestation_type,
        expected_input_sha256=None,
        expected_context_sha256=file_sha256(identity_path),
        expected_source_sha256=source_sha256,
    )
    if errors:
        raise HostExecutionError(
            "REVIEW_HOST_RECEIPT_INVALID:" + ",".join(sorted(set(errors)))
        )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    command = receipt["command"]
    execution_root = Path(command["cwd"])
    retained_mode = execution_root != root
    if retained_mode and (
        root.name != "reviews"
        or not (root.parent / "source").is_dir()
        or not (root.parent / "snapshot-index.json").is_file()
        or not execution_root.is_absolute()
    ):
        raise HostExecutionError("REVIEW_EXECUTION_CONTRACT_MISMATCH")
    prompt_path = Path(str(derived.get("prompt_path", "")))
    expected_prompt = build_review_prompt(
        repo_root=execution_root,
        attestation_type=attestation_type,
        source_sha256=source_sha256,
    )
    expected_argv = [
        command["codex_cli_path"],
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--json",
        "--sandbox",
        REVIEW_SANDBOX,
        "--model",
        REVIEW_MODEL,
        "--config",
        f'model_reasoning_effort="{REVIEW_REASONING_EFFORT}"',
        "--cd",
        str(execution_root),
        "--output-last-message",
        str(
            execution_root
            / PurePosixPath(receipt_relative).parent
            / ARTIFACT_NAMES["last_message"]
        ),
        "-",
    ]
    if (
        derived.get("cwd") != str(execution_root)
        or derived.get("model") != REVIEW_MODEL
        or derived.get("reasoning_effort") != REVIEW_REASONING_EFFORT
        or derived.get("sandbox") != REVIEW_SANDBOX
        or command.get("argv") != expected_argv
        or not prompt_path.is_file()
        or prompt_path.is_symlink()
        or prompt_path != receipt_path.parent / ARTIFACT_NAMES["prompt"]
        or prompt_path.read_text(encoding="utf-8") != expected_prompt
    ):
        raise HostExecutionError("REVIEW_EXECUTION_CONTRACT_MISMATCH")
    last_message_path, last_message_relative = _repo_relative_regular_file(
        repo_root, Path(derived["last_message_path"])
    )
    try:
        payload = json.loads(last_message_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HostExecutionError("REVIEW_PAYLOAD_INVALID_JSON") from exc
    required_payload = {
        "schema_version",
        "attestation_type",
        "source_sha256",
        "review_scope",
        "covered_severities",
        "findings",
    }
    if not isinstance(payload, dict) or set(payload) != required_payload:
        raise HostExecutionError("REVIEW_PAYLOAD_CONTRACT_INVALID")
    if (
        payload.get("schema_version") != REVIEW_PAYLOAD_SCHEMA_VERSION
        or payload.get("attestation_type") != attestation_type
        or payload.get("source_sha256") != source_sha256
        or payload.get("review_scope") != list(REVIEW_SCOPE)
        or payload.get("covered_severities") != ["P0", "P1"]
        or not isinstance(payload.get("findings"), list)
    ):
        raise HostExecutionError("REVIEW_PAYLOAD_BINDING_INVALID")
    finding_ids: set[str] = set()
    for finding in payload["findings"]:
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
            or finding.get("severity") not in {"P0", "P1"}
            or finding.get("reproducible") is not True
            or finding.get("status") != "open"
            or any(
                not isinstance(finding.get(field), str)
                or not finding[field].strip()
                for field in (
                    "finding_id",
                    "summary",
                    "reproducer",
                    "actual",
                    "expected",
                )
            )
            or finding["finding_id"] in finding_ids
        ):
            raise HostExecutionError("REVIEW_FINDING_CONTRACT_INVALID")
        finding_ids.add(finding["finding_id"])
    return {
        "schema_version": REVIEW_ATTESTATION_SCHEMA_VERSION,
        "attestation_type": attestation_type,
        "source_sha256": source_sha256,
        "reviewer_id": derived["host_run_id"],
        "execution_id": derived["thread_id"],
        "model_environment": {
            "runner": derived["host_run_id"],
            "model": derived["model"],
            "isolation": ISOLATION_DESCRIPTION,
            "reasoning": derived["reasoning_effort"],
            "execution_id": derived["thread_id"],
        },
        "review_scope": list(REVIEW_SCOPE),
        "covered_severities": ["P0", "P1"],
        "review_artifact": {
            "path": last_message_relative,
            "sha256": file_sha256(last_message_path),
        },
        "source_identity": {
            "path": identity_relative,
            "sha256": file_sha256(identity_path),
        },
        "host_execution_receipt": {
            "path": receipt_relative,
            "sha256": file_sha256(receipt_path),
        },
        "trust_boundary": TRUST_BOUNDARY,
        "findings": payload["findings"],
    }


def write_review_attestation(
    *,
    receipt_path: Path,
    repo_root: Path,
    attestation_type: str,
    source_sha256: str,
    output_path: Path,
) -> Path:
    report = derive_review_attestation(
        receipt_path=receipt_path,
        repo_root=repo_root,
        attestation_type=attestation_type,
        source_sha256=source_sha256,
    )
    root = repo_root.resolve(strict=True)
    try:
        output_path.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise HostExecutionError("REVIEW_REPORT_OUTSIDE_REPOSITORY") from exc
    _atomic_write_json(output_path, report)
    return output_path


def _required_eval_artifacts(case_id: str) -> tuple[list[str], list[str]]:
    if case_id == EVAL_VERSIONED_CASE:
        return (
            ["artifacts/revision-1.json", "artifacts/revision-2.json"],
            ["receipts/revision-1.json", "receipts/revision-2.json"],
        )
    if case_id in EVAL_NO_CASEFILE_CASES:
        return (
            [],
            ["receipts/validation.json"]
            if case_id == "validator-rejects-epistemic-violations"
            else [],
        )
    return ["artifacts/separation.json"], ["receipts/validation.json"]


def _eval_envelope_texts(input_path: Path) -> list[str]:
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HostExecutionError("EVAL_INPUT_ENVELOPE_INVALID") from exc
    values = payload.get("turns") if isinstance(payload, dict) and "turns" in payload else [payload.get("input") if isinstance(payload, dict) else None]
    if (
        not isinstance(values, list)
        or not values
        or any(not isinstance(item, str) for item in values)
    ):
        raise HostExecutionError("EVAL_RAW_INPUT_INVALID")
    return values


def _write_or_verify_bytes(destination: Path, payload: bytes, error_code: str) -> None:
    if destination.exists() or destination.is_symlink():
        if (
            not destination.is_file()
            or destination.is_symlink()
            or destination.read_bytes() != payload
        ):
            raise HostExecutionError(error_code)
        return
    _atomic_write_bytes(destination, payload)


def terminal_output_equal(left: bytes, right: bytes) -> bool:
    """Allow only the one final LF that Codex output-last-message may omit."""
    return left == right or left + b"\n" == right or right + b"\n" == left


def assert_runtime_final_output(
    *,
    case_dir: Path,
    case_id: str,
    layout: dict[str, list[str]],
    observed_output: bytes,
) -> None:
    """Bind the user-visible host message to the completed runtime workspace."""
    if not layout["workspace_paths"] or case_id == "json-artifact-and-validation-receipt":
        return
    workspace = case_dir / layout["workspace_paths"][-1]
    filename = (
        "safety-response.md"
        if case_id
        in {"immediate-safety-override", "safety-interrupt-before-artifact-work"}
        else "response.md"
    )
    expected = workspace / filename
    if (
        not expected.is_file()
        or expected.is_symlink()
        or not terminal_output_equal(observed_output, expected.read_bytes())
    ):
        raise HostExecutionError("EVAL_FINAL_RESPONSE_WORKSPACE_MISMATCH")


def _runtime_workspace_sources(
    *, eval_root: Path, case_dir: Path, case_id: str
) -> tuple[dict[str, list[str]], list[Path]]:
    """Validate exact host inputs and return completed workspace casefiles."""
    layout = eval_runtime_layout(case_id)
    runtime_dir = case_dir / EVAL_RUNTIME_DIRECTORY
    if not runtime_dir.is_dir() or runtime_dir.is_symlink():
        raise HostExecutionError("EVAL_RUNTIME_DIRECTORY_MISSING")
    texts = _eval_envelope_texts(case_dir / "input.json")
    if len(texts) != len(layout["input_paths"]):
        raise HostExecutionError("EVAL_RUNTIME_INPUT_COUNT_MISMATCH")
    for relative, text_value in zip(layout["input_paths"], texts, strict=True):
        input_value = case_dir / relative
        if (
            not input_value.is_file()
            or input_value.is_symlink()
            or input_value.read_text(encoding="utf-8") != text_value
            or (input_value.stat().st_mode & 0o222) != 0
        ):
            raise HostExecutionError("EVAL_RUNTIME_INPUT_MISMATCH")

    expected_casefiles = (
        []
        if case_id in EVAL_PASSTHROUGH_CASES
        else [
            (case_dir / relative / "casefile.json").resolve()
            for relative in layout["workspace_paths"]
        ]
    )
    discovered_casefiles = sorted(
        path.resolve()
        for path in runtime_dir.rglob("casefile.json")
        if path.is_file() and not path.is_symlink()
    )
    if discovered_casefiles != sorted(expected_casefiles):
        raise HostExecutionError("EVAL_RUNTIME_CASEFILE_SET_MISMATCH")

    for index, relative in enumerate(layout["workspace_paths"]):
        workspace = case_dir / relative
        state_path = workspace / "state.json"
        if (
            not workspace.is_dir()
            or workspace.is_symlink()
            or not state_path.is_file()
            or state_path.is_symlink()
        ):
            raise HostExecutionError("EVAL_RUNTIME_WORKSPACE_INVALID")
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise HostExecutionError("EVAL_RUNTIME_STATE_INVALID") from exc
        passthrough = case_id in EVAL_PASSTHROUGH_CASES
        common_state_valid = bool(
            isinstance(state, dict)
            and state.get("phase") == "completed"
            and state.get("case_id") == case_id
            and state.get("response_path") == "response.md"
        )
        passthrough_state_valid = bool(
            passthrough
            and state.get("mode") == "passthrough"
            and state.get("casefile_path") is None
            and state.get("passthrough_validation_path")
            == "passthrough-validation.json"
        )
        casefile_state_valid = bool(
            not passthrough
            and state.get("casefile_path") == "casefile.json"
            and isinstance(state.get("receipt_paths"), list)
            and state.get("receipt_paths")
        )
        if not common_state_valid or not (
            passthrough_state_valid or casefile_state_valid
        ):
            raise HostExecutionError("EVAL_RUNTIME_STATE_NOT_COMPLETED")
        workspace_input = workspace / "input.txt"
        expected_input = texts[index]
        if (
            not workspace_input.is_file()
            or workspace_input.is_symlink()
            or workspace_input.read_text(encoding="utf-8") != expected_input
        ):
            raise HostExecutionError("EVAL_RUNTIME_WORKSPACE_INPUT_MISMATCH")
        response = workspace / "response.md"
        if not response.is_file() or response.is_symlink():
            raise HostExecutionError("EVAL_RUNTIME_RESPONSE_MISSING")
        if passthrough:
            validation_path = workspace / "passthrough-validation.json"
            try:
                validation = json.loads(
                    validation_path.read_text(encoding="utf-8")
                )
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise HostExecutionError(
                    "EVAL_RUNTIME_PASSTHROUGH_VALIDATION_INVALID"
                ) from exc
            if not isinstance(validation, dict) or validation.get("valid") is not True:
                raise HostExecutionError(
                    "EVAL_RUNTIME_PASSTHROUGH_VALIDATION_INVALID"
                )
        if case_id in {
            "immediate-safety-override",
            "safety-interrupt-before-artifact-work",
        }:
            safety_response = workspace / "safety-response.md"
            if not safety_response.is_file() or safety_response.is_symlink():
                raise HostExecutionError("EVAL_RUNTIME_SAFETY_RESPONSE_MISSING")
    return layout, expected_casefiles


def _materialize_passthrough_workspace(
    *, eval_root: Path, case_dir: Path, case_id: str, observed_output: bytes
) -> None:
    """Run the deterministic passthrough state machine on host-observed output."""
    if case_id not in EVAL_PASSTHROUGH_CASES:
        return
    runtime_dir = case_dir / EVAL_RUNTIME_DIRECTORY
    if not runtime_dir.is_dir() or runtime_dir.is_symlink():
        return
    layout = eval_runtime_layout(case_id)
    workspace = case_dir / layout["workspace_paths"][0]
    if workspace.exists() or workspace.is_symlink():
        return
    response_source = runtime_dir / "observed-response.txt"
    _write_or_verify_bytes(
        response_source,
        observed_output,
        "EVAL_RUNTIME_OBSERVED_OUTPUT_RECOVERY_CONFLICT",
    )
    workflow = eval_root / "runtime-snapshot" / "scripts" / "workflow.py"
    commands = (
        [
            sys.executable,
            "-B",
            str(workflow),
            "start",
            "--input",
            str(case_dir / layout["input_paths"][0]),
            "--workspace",
            str(workspace),
            "--case-id",
            case_id,
            "--mode",
            "auto",
        ],
        [
            sys.executable,
            "-B",
            str(workflow),
            "complete-passthrough",
            "--workspace",
            str(workspace),
            "--response",
            str(response_source),
        ],
    )
    for command in commands:
        completed = subprocess.run(
            command,
            cwd=eval_root,
            text=True,
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "PYTHONNOUSERSITE": "1",
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
        if completed.returncode != 0:
            raise HostExecutionError("EVAL_RUNTIME_PASSTHROUGH_FAILED")


def _run_canonical_validator(
    *, eval_root: Path, artifact: Path, report: Path, previous: Path | None = None
) -> None:
    """Create a receipt for the promoted path with the frozen runtime validator."""
    report.parent.mkdir(parents=True, exist_ok=True)
    if report.exists() or report.is_symlink():
        try:
            current = json.loads(report.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise HostExecutionError("EVAL_CANONICAL_RECEIPT_RECOVERY_CONFLICT") from exc
        if (
            not isinstance(current, dict)
            or current.get("valid") is not True
            or current.get("error_count") != 0
            or current.get("errors") != []
            or current.get("artifact_path") != str(artifact.resolve())
            or current.get("artifact_sha256") != file_sha256(artifact)
        ):
            raise HostExecutionError("EVAL_CANONICAL_RECEIPT_RECOVERY_CONFLICT")
        return
    validator = eval_root / "runtime-snapshot" / "scripts" / "casefile.py"
    command = [
        sys.executable,
        "-I",
        "-S",
        "-B",
        str(validator),
        "validate",
        str(artifact),
    ]
    if previous is not None:
        command.extend(["--previous", str(previous)])
    command.extend(["--report", str(report)])
    completed = subprocess.run(
        command,
        cwd=eval_root,
        text=True,
        capture_output=True,
        check=False,
        env={
            **os.environ,
            "PYTHONNOUSERSITE": "1",
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        timeout=DEFAULT_TIMEOUT_SECONDS,
    )
    if completed.returncode != 0 or not report.is_file() or report.is_symlink():
        raise HostExecutionError("EVAL_CANONICAL_VALIDATION_FAILED")


def promote_eval_runtime_artifacts(
    *,
    eval_root: Path,
    case_dir: Path,
    case_id: str,
    observed_output: bytes,
) -> dict[str, list[str]]:
    """Promote one fixed completed workspace; never trust model-authored exports."""
    _materialize_passthrough_workspace(
        eval_root=eval_root,
        case_dir=case_dir,
        case_id=case_id,
        observed_output=observed_output,
    )
    layout, sources = _runtime_workspace_sources(
        eval_root=eval_root,
        case_dir=case_dir,
        case_id=case_id,
    )
    assert_runtime_final_output(
        case_dir=case_dir,
        case_id=case_id,
        layout=layout,
        observed_output=observed_output,
    )
    artifact_paths, receipt_paths = _required_eval_artifacts(case_id)
    if case_id == "validator-rejects-epistemic-violations":
        source = case_dir / layout["validation_paths"][0]
        fixture = (
            eval_root
            / "runtime-snapshot"
            / "evals"
            / "fixtures"
            / "invalid-epistemic.json"
        )
        try:
            report = json.loads(source.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise HostExecutionError("EVAL_RUNTIME_INVALID_RECEIPT_MISSING") from exc
        if (
            not isinstance(report, dict)
            or report.get("valid") is not False
            or not isinstance(report.get("error_count"), int)
            or report.get("error_count") != len(report.get("errors", []))
            or report.get("artifact_path") != str(fixture.resolve())
            or report.get("artifact_sha256") != file_sha256(fixture)
        ):
            raise HostExecutionError("EVAL_RUNTIME_INVALID_RECEIPT_INVALID")
        _write_or_verify_bytes(
            case_dir / receipt_paths[0],
            source.read_bytes(),
            "EVAL_CANONICAL_RECEIPT_RECOVERY_CONFLICT",
        )
        return layout
    if not artifact_paths:
        return layout
    destinations = [case_dir / relative for relative in artifact_paths]
    for source, destination in zip(sources, destinations, strict=True):
        _write_or_verify_bytes(
            destination,
            source.read_bytes(),
            "EVAL_CANONICAL_ARTIFACT_RECOVERY_CONFLICT",
        )
    for index, (artifact, receipt_relative) in enumerate(
        zip(destinations, receipt_paths, strict=True)
    ):
        previous = destinations[index - 1] if index > 0 else None
        _run_canonical_validator(
            eval_root=eval_root,
            artifact=artifact,
            report=case_dir / receipt_relative,
            previous=previous,
        )
    return layout


def bind_eval_case_result(
    *, receipt_path: Path, eval_root: Path, case_id: str
) -> Path:
    """Create one prepared case-result solely from retained host evidence."""
    eval_root = eval_root.resolve(strict=True)
    case_dir = (eval_root / case_id).resolve(strict=True)
    try:
        case_dir.relative_to(eval_root)
    except ValueError as exc:
        raise HostExecutionError("EVAL_CASE_OUTSIDE_ROOT") from exc
    input_path = case_dir / "input.json"
    context_path = eval_root / "evaluation-context.json"
    if (
        not input_path.is_file()
        or input_path.is_symlink()
        or not context_path.is_file()
        or context_path.is_symlink()
    ):
        raise HostExecutionError("EVAL_PREPARED_INPUT_MISSING")
    try:
        context_payload = json.loads(context_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HostExecutionError("EVAL_CONTEXT_INVALID") from exc
    runtime_snapshot = (
        context_payload.get("runtime_snapshot")
        if isinstance(context_payload, dict)
        else None
    )
    expected_runtime_sha256 = (
        runtime_snapshot.get("manifest_sha256")
        if isinstance(runtime_snapshot, dict)
        else None
    )
    if not _is_sha256(expected_runtime_sha256):
        raise HostExecutionError("EVAL_RUNTIME_SNAPSHOT_BINDING_MISSING")
    receipt_path, receipt_relative = _repo_relative_regular_file(
        eval_root, receipt_path
    )
    expected_host_dir = (eval_root / ".host" / case_id).resolve(strict=False)
    if receipt_path.parent != expected_host_dir:
        raise HostExecutionError("EVAL_HOST_DIRECTORY_MISMATCH")
    derived, errors = validate_host_receipt(
        receipt_path,
        expected_kind="eval",
        expected_subject_id=case_id,
        expected_input_sha256=file_sha256(input_path),
        expected_context_sha256=file_sha256(context_path),
        expected_source_sha256=expected_runtime_sha256,
    )
    if errors:
        raise HostExecutionError(
            "EVAL_HOST_RECEIPT_INVALID:" + ",".join(sorted(set(errors)))
        )
    expected_prompt = build_eval_prompt(
        eval_root=eval_root,
        case_dir=case_dir,
        case_id=case_id,
    )
    prompt_path = Path(str(derived.get("prompt_path", "")))
    if (
        derived.get("cwd") != str(case_dir)
        or derived.get("model") != EVAL_MODEL
        or derived.get("reasoning_effort") != EVAL_REASONING_EFFORT
        or derived.get("sandbox") != EVAL_SANDBOX
        or not prompt_path.is_file()
        or prompt_path.is_symlink()
        or prompt_path != receipt_path.parent / ARTIFACT_NAMES["prompt"]
        or prompt_path.read_text(encoding="utf-8") != expected_prompt
    ):
        raise HostExecutionError("EVAL_PROMPT_CONTRACT_MISMATCH")
    last_message_path, _ = _repo_relative_regular_file(
        eval_root, Path(derived["last_message_path"])
    )
    if not last_message_path.read_text(encoding="utf-8").strip():
        raise HostExecutionError("EVAL_LAST_MESSAGE_EMPTY")
    runtime_layout = promote_eval_runtime_artifacts(
        eval_root=eval_root,
        case_dir=case_dir,
        case_id=case_id,
        observed_output=last_message_path.read_bytes(),
    )
    if case_id == "validator-rejects-epistemic-violations":
        internal_receipt = case_dir / runtime_layout["validation_paths"][0]
        try:
            observed_report = json.loads(
                last_message_path.read_text(encoding="utf-8")
            )
            internal_report = json.loads(
                internal_receipt.read_text(encoding="utf-8")
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise HostExecutionError("EVAL_INVALID_FIXTURE_OUTPUT_MISMATCH") from exc
        if observed_report != internal_report:
            raise HostExecutionError("EVAL_INVALID_FIXTURE_OUTPUT_MISMATCH")
    raw_output_path = case_dir / "raw-output.txt"
    raw_output_bytes = last_message_path.read_bytes()
    if raw_output_path.exists() or raw_output_path.is_symlink():
        if (
            not raw_output_path.is_file()
            or raw_output_path.is_symlink()
            or raw_output_path.read_bytes() != raw_output_bytes
        ):
            raise HostExecutionError("EVAL_RAW_OUTPUT_RECOVERY_CONFLICT")
    else:
        _atomic_write_bytes(raw_output_path, raw_output_bytes)
    artifact_paths, receipt_paths = _required_eval_artifacts(case_id)
    for relative in [*artifact_paths, *receipt_paths]:
        _repo_relative_regular_file(case_dir, Path(relative))
    result = {
        "case_id": case_id,
        "status": "completed",
        "model_environment": {
            "runner": derived["host_run_id"],
            "model": derived["model"],
            "isolation": ISOLATION_DESCRIPTION,
            "reasoning_effort": derived["reasoning_effort"],
            "execution_id": derived["thread_id"],
        },
        "input_sha256": hashlib.sha256(
            canonical_bytes(json.loads(input_path.read_text(encoding="utf-8")))
        ).hexdigest(),
        "evaluation_context_sha256": file_sha256(context_path),
        "raw_input_path": "input.json",
        "raw_output_path": "raw-output.txt",
        "host_execution_receipt_path": receipt_relative,
        "runtime_input_paths": runtime_layout["input_paths"],
        "runtime_workspace_paths": runtime_layout["workspace_paths"],
        "runtime_validation_paths": runtime_layout["validation_paths"],
        "artifact_paths": artifact_paths,
        "receipt_paths": receipt_paths,
    }
    result_path = case_dir / "case-result.json"
    _atomic_write_json(result_path, result)
    return result_path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run")
    run.add_argument("--codex", default=shutil.which("codex"))
    run.add_argument("--prompt", required=True)
    run.add_argument("--output-dir", required=True)
    run.add_argument("--cwd", required=True)
    run.add_argument("--kind", choices=sorted(EXECUTION_KINDS), required=True)
    run.add_argument("--subject-id", required=True)
    run.add_argument("--model", required=True)
    run.add_argument("--reasoning-effort", choices=sorted(REASONING_EFFORTS), required=True)
    run.add_argument("--sandbox", choices=sorted(SANDBOX_MODES), required=True)
    run.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    run.add_argument("--input")
    run.add_argument("--context")
    run.add_argument("--source-sha256")
    bind_review = subparsers.add_parser("bind-review")
    bind_review.add_argument("--receipt", required=True)
    bind_review.add_argument("--repo-root", required=True)
    bind_review.add_argument(
        "--attestation-type",
        choices=("p0_zero", "reproducible_p1_zero"),
        required=True,
    )
    bind_review.add_argument("--source-sha256", required=True)
    bind_review.add_argument("--output", required=True)
    bind_eval = subparsers.add_parser("bind-eval")
    bind_eval.add_argument("--receipt", required=True)
    bind_eval.add_argument("--eval-root", required=True)
    bind_eval.add_argument("--case-id", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "bind-review":
        try:
            output = write_review_attestation(
                receipt_path=Path(args.receipt),
                repo_root=Path(args.repo_root),
                attestation_type=args.attestation_type,
                source_sha256=args.source_sha256,
                output_path=Path(args.output),
            )
            print(
                json.dumps(
                    {"valid": True, "review_attestation": str(output.resolve())},
                    ensure_ascii=False,
                )
            )
            return 0
        except (HostExecutionError, OSError, ValueError) as exc:
            print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
            return 2
    if args.command == "bind-eval":
        try:
            output = bind_eval_case_result(
                receipt_path=Path(args.receipt),
                eval_root=Path(args.eval_root),
                case_id=args.case_id,
            )
            print(
                json.dumps(
                    {"valid": True, "case_result": str(output.resolve())},
                    ensure_ascii=False,
                )
            )
            return 0
        except (HostExecutionError, OSError, UnicodeError, ValueError) as exc:
            print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
            return 2
    if args.kind == "review":
        print(
            json.dumps(
                {"valid": False, "error": "FIXED_REVIEW_RUNNER_REQUIRED"},
                ensure_ascii=False,
            )
        )
        return 2
    if not args.codex:
        print(json.dumps({"valid": False, "error": "CODEX_NOT_FOUND"}))
        return 2
    try:
        receipt_path = run_codex_execution(
            codex_path=Path(args.codex),
            prompt_path=Path(args.prompt),
            output_dir=Path(args.output_dir),
            cwd=Path(args.cwd),
            execution_kind=args.kind,
            subject_id=args.subject_id,
            model=args.model,
            reasoning_effort=args.reasoning_effort,
            sandbox=args.sandbox,
            timeout_seconds=args.timeout_seconds,
            input_path=Path(args.input) if args.input else None,
            context_path=Path(args.context) if args.context else None,
            source_sha256=args.source_sha256,
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        exit_code = receipt["process"]["exit_code"]
        timed_out = receipt["process"]["timed_out"]
        print(
            json.dumps(
                {
                    "valid": exit_code == 0 and timed_out is False,
                    "receipt": str(receipt_path.resolve()),
                    "host_run_id": receipt["host_run_id"],
                    "thread_id": receipt["model_execution"].get("thread_id"),
                },
                ensure_ascii=False,
            )
        )
        return 0 if exit_code == 0 and timed_out is False else 1
    except (HostExecutionError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
