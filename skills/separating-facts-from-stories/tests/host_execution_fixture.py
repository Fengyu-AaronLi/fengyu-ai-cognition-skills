"""Synthetic host receipts for deterministic release-controller unit tests.

These fixtures exercise the same byte and identity bindings as a real local
Codex run without starting a model from the unit-test suite.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import uuid
from pathlib import Path
from typing import Any


TRUST_BOUNDARY = (
    "controller_observed_local_codex_process_and_thread_not_external_identity_proof"
)
ISOLATION_DESCRIPTION = "fresh codex exec --ephemeral; no resume; host observed"
REVIEW_SCOPE = (
    "runtime_semantics",
    "safety_routing",
    "state_integrity",
    "release_evidence",
    "packaging_installation",
    "documentation_claims",
)
HOST_PATH = Path(__file__).resolve().parents[1] / "scripts" / "codex_exec_host.py"


def _load_host():
    spec = importlib.util.spec_from_file_location("host_execution_fixture_runtime", HOST_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load host execution runtime")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare_review_source(repo_root: Path) -> str:
    """Create a minimal manifest when needed and return its canonical source ID."""
    root = repo_root.resolve()
    manifest_path = root / "workflows" / "separating-facts-release-sources.json"
    if not manifest_path.exists():
        source_path = root / "review-source.txt"
        source_path.write_text("review source fixture\n", encoding="utf-8")
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "source_files": [
                        "review-source.txt",
                        "workflows/separating-facts-release-sources.json",
                    ],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    declared = manifest["source_files"]
    files = {relative: sha256(root / relative) for relative in declared}
    return hashlib.sha256(canonical_bytes(dict(sorted(files.items())))).hexdigest()


def _source_identity(repo_root: Path, source_sha256: str) -> dict[str, Any]:
    root = repo_root.resolve()
    manifest_path = root / "workflows" / "separating-facts-release-sources.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = dict(
        sorted(
            (relative, sha256(root / relative))
            for relative in manifest["source_files"]
        )
    )
    observed = hashlib.sha256(canonical_bytes(files)).hexdigest()
    if observed != source_sha256:
        raise ValueError("fixture source_sha256 does not match source manifest bytes")
    manifest_relative = "workflows/separating-facts-release-sources.json"
    return {
        "schema_version": "review_source_identity.v1",
        "source_sha256": observed,
        "files": files,
        "manifest_path": manifest_relative,
        "manifest_sha256": files[manifest_relative],
    }


def _descriptor(path: Path, receipt_dir: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(receipt_dir).as_posix(),
        "sha256": sha256(path),
        "bytes": path.stat().st_size,
    }


def write_host_review(
    repo_root: Path,
    attestation_type: str,
    source_sha256: str,
    *,
    findings: list[dict[str, Any]] | None = None,
    suffix: str | None = None,
) -> tuple[Path, dict[str, Any]]:
    root = repo_root.resolve()
    host = _load_host()
    source_identity = _source_identity(root, source_sha256)
    normalized_findings: list[dict[str, Any]] = []
    for finding in list(findings or []):
        normalized = dict(finding)
        finding_id = str(normalized.get("finding_id", "fixture-finding"))
        normalized.setdefault("summary", f"Fixture finding {finding_id}.")
        normalized.setdefault("reproducer", "Run the deterministic fixture reproducer.")
        normalized.setdefault("actual", "The fixture observes the invalid result.")
        normalized.setdefault("expected", "The fixture expects the valid result.")
        normalized_findings.append(normalized)
    suffix = suffix or uuid.uuid4().hex
    run_root = root / ".ao-output" / "reviews" / suffix
    run_dir = run_root / attestation_type
    run_dir.mkdir(parents=True)
    identity_path = run_root / "source-identity.json"
    if not identity_path.exists():
        identity_path.write_text(
            json.dumps(source_identity, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    fake_codex = root / ".test-host-reviews" / "fixture-codex"
    if not fake_codex.exists():
        fake_codex.parent.mkdir(parents=True, exist_ok=True)
        fake_codex.write_text("fixture codex binary\n", encoding="utf-8")
    host_run_id = f"host-{suffix}"
    thread_id = f"thread-{suffix}"
    payload = {
        "schema_version": host.REVIEW_PAYLOAD_SCHEMA_VERSION,
        "attestation_type": attestation_type,
        "source_sha256": source_sha256,
        "review_scope": list(REVIEW_SCOPE),
        "covered_severities": ["P0", "P1"],
        "findings": normalized_findings,
    }
    payload_text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    prompt = run_dir / "prompt.txt"
    events = run_dir / "events.jsonl"
    stderr = run_dir / "stderr.txt"
    last_message = run_dir / "last-message.txt"
    prompt.write_text(
        host.build_review_prompt(
            repo_root=root,
            attestation_type=attestation_type,
            source_sha256=source_sha256,
        ),
        encoding="utf-8",
    )
    events.write_text(
        "\n".join(
            json.dumps(event, ensure_ascii=False)
            for event in (
                {"type": "thread.started", "thread_id": thread_id},
                {"type": "turn.started"},
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": payload_text},
                },
                {"type": "turn.completed"},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    stderr.write_text("", encoding="utf-8")
    last_message.write_text(payload_text, encoding="utf-8")
    argv = [
        str(fake_codex.resolve()),
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--json",
        "--sandbox",
        host.REVIEW_SANDBOX,
        "--model",
        host.REVIEW_MODEL,
        "--config",
        f'model_reasoning_effort="{host.REVIEW_REASONING_EFFORT}"',
        "--cd",
        str(root),
        "--output-last-message",
        str(last_message),
        "-",
    ]
    receipt = {
        "schema_version": "1.0.0",
        "receipt_type": "host_execution_receipt.v1",
        "trust_boundary": TRUST_BOUNDARY,
        "host_run_id": host_run_id,
        "execution_kind": "review",
        "subject_id": attestation_type,
        "started_at": "2026-08-06T00:00:00+00:00",
        "finished_at": "2026-08-06T00:00:01+00:00",
        "command": {
            "codex_cli_path": str(fake_codex.resolve()),
            "codex_cli_sha256": sha256(fake_codex),
            "codex_cli_version": "fixture-codex 1.0",
            "argv": argv,
            "argv_sha256": hashlib.sha256(canonical_bytes(argv)).hexdigest(),
            "cwd": str(root),
            "model": host.REVIEW_MODEL,
            "reasoning_effort": host.REVIEW_REASONING_EFFORT,
            "sandbox": host.REVIEW_SANDBOX,
            "ephemeral": True,
            "resume": False,
            "ignore_user_config": True,
            "ignore_rules": True,
        },
        "process": {
            "pid": 1000 + (sum(suffix.encode("utf-8")) % 30000),
            "exit_code": 0,
            "timed_out": False,
            "duration_ms": 1000,
        },
        "bindings": {
            "prompt_sha256": sha256(prompt),
            "input_sha256": None,
            "context_sha256": sha256(identity_path),
            "source_sha256": source_sha256,
        },
        "model_execution": {
            "thread_id": thread_id,
            "turn_started_count": 1,
            "turn_completed_count": 1,
            "agent_message_count": 1,
        },
        "event_parse_errors": [],
        "artifacts": {
            "prompt": _descriptor(prompt, run_dir),
            "events": _descriptor(events, run_dir),
            "stderr": _descriptor(stderr, run_dir),
            "last_message": _descriptor(last_message, run_dir),
        },
    }
    receipt_path = run_dir / "host-execution-receipt.json"
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = {
        "schema_version": host.REVIEW_ATTESTATION_SCHEMA_VERSION,
        "attestation_type": attestation_type,
        "source_sha256": source_sha256,
        "reviewer_id": host_run_id,
        "execution_id": thread_id,
        "model_environment": {
            "runner": host_run_id,
            "model": host.REVIEW_MODEL,
            "isolation": ISOLATION_DESCRIPTION,
            "reasoning": host.REVIEW_REASONING_EFFORT,
            "execution_id": thread_id,
        },
        "review_scope": list(REVIEW_SCOPE),
        "covered_severities": ["P0", "P1"],
        "review_artifact": {
            "path": last_message.relative_to(root).as_posix(),
            "sha256": sha256(last_message),
        },
        "source_identity": {
            "path": identity_path.relative_to(root).as_posix(),
            "sha256": sha256(identity_path),
        },
        "host_execution_receipt": {
            "path": receipt_path.relative_to(root).as_posix(),
            "sha256": sha256(receipt_path),
        },
        "trust_boundary": TRUST_BOUNDARY,
        "findings": normalized_findings,
    }
    report_dir = run_root / "attestations"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"{attestation_type}.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report_path, report
