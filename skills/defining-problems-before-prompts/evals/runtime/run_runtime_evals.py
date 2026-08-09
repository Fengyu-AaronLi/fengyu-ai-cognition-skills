#!/usr/bin/env python3
"""Run the frozen, offline runtime acceptance suite.

This runner invokes only the local ``scripts/dpbp`` executable. It does not
call a model, open a socket, or infer problem semantics. The suite manifest is
the single source of truth for cases, expectations, fixture paths and hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Sequence


SCHEMA_VERSION = "1.0"
REPORT_TYPE = "offline-runtime-eval"
DEFAULT_SKILL_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SUITE_MANIFEST = DEFAULT_SKILL_ROOT / "evals" / "suite-manifest.json"


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return sha256_bytes(path.read_bytes())


def load_suite_manifest(manifest_path: Path, skill_root: Path) -> dict[str, Any]:
    """Load a hash-bound regression suite and fail closed on drift."""

    try:
        raw = manifest_path.read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("suite manifest is unreadable") from exc
    if not isinstance(manifest, dict) or set(manifest) != {
        "schema_version", "suite_id", "suite_version", "partitions", "policy"
    }:
        raise ValueError("suite manifest contract is invalid")
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("suite manifest schema version is unsupported")
    partitions = manifest.get("partitions")
    if not isinstance(partitions, dict) or set(partitions) != {"regression", "sealed_holdout"}:
        raise ValueError("suite partitions are invalid")
    if not isinstance(partitions.get("regression"), list) or not isinstance(partitions.get("sealed_holdout"), list):
        raise ValueError("suite partitions must be arrays")

    cases: list[dict[str, Any]] = []
    case_ids: set[str] = set()
    expected_fields = {"mode", "rule", "resources", "requires_spec"}
    for case in partitions["regression"]:
        required = {
            "case_id", "envelope_file", "envelope_sha256", "spec_file", "spec_sha256", "expected"
        }
        if not isinstance(case, dict) or set(case) != required:
            raise ValueError("regression case contract is invalid")
        case_id = case.get("case_id")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in case_ids:
            raise ValueError("regression case_id is invalid or duplicated")
        case_ids.add(case_id)
        expected = case.get("expected")
        if not isinstance(expected, dict) or set(expected) != expected_fields:
            raise ValueError("regression expectation contract is invalid")

        def resolve(relative: Any, field: str) -> Path:
            if not isinstance(relative, str):
                raise ValueError(f"{field} must be a relative path")
            relative_path = Path(relative)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ValueError(f"{field} escapes the suite root")
            return skill_root / relative_path

        envelope_path = resolve(case.get("envelope_file"), "envelope_file")
        if case.get("envelope_sha256") != sha256_file(envelope_path):
            raise ValueError(f"envelope fixture hash mismatch for {case_id}")
        spec_path: Path | None = None
        if case.get("spec_file") is not None:
            spec_path = resolve(case.get("spec_file"), "spec_file")
            if case.get("spec_sha256") != sha256_file(spec_path):
                raise ValueError(f"spec fixture hash mismatch for {case_id}")
        elif case.get("spec_sha256") is not None:
            raise ValueError(f"spec fixture hash exists without a file for {case_id}")
        if bool(expected.get("requires_spec")) != (spec_path is not None):
            raise ValueError(f"spec fixture requirement mismatch for {case_id}")
        cases.append(
            {
                "case_id": case_id,
                "envelope_path": envelope_path,
                "mode": expected["mode"],
                "resources": copy_json(expected["resources"]),
                "rule": expected["rule"],
                "requires_spec": expected["requires_spec"],
                "spec_path": spec_path,
            }
        )
    return {
        "cases": cases,
        "manifest_path": manifest_path,
        "manifest_sha256": sha256_bytes(raw),
        "policy": manifest["policy"],
        "sealed_holdout": partitions["sealed_holdout"],
        "suite_id": manifest["suite_id"],
        "suite_version": manifest["suite_version"],
    }


def copy_json(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def portable_path(path: Path, skill_root: Path) -> str:
    """Return a repository-relative path without leaking a host directory."""

    try:
        return path.resolve().relative_to(skill_root.resolve()).as_posix()
    except (OSError, ValueError):
        return f"external:{path.name}"


def append_code(codes: list[str], code: str) -> None:
    if code not in codes:
        codes.append(code)


def summarize_stdout(outputs: Sequence[bytes]) -> dict[str, Any]:
    """Summarize exact bytes without normalizing or parsing them first."""

    unique_hashes = sorted({sha256_bytes(output) for output in outputs})
    first = outputs[0] if outputs else b""
    return {
        "deterministic": bool(outputs) and len(set(outputs)) == 1,
        "stdout_bytes": len(first),
        "stdout_sha256": sha256_bytes(first) if outputs else None,
        "unique_stdout_count": len(set(outputs)),
        "unique_stdout_sha256": unique_hashes,
    }


def count_exit_codes(results: Sequence[subprocess.CompletedProcess[bytes]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for result in results:
        key = str(result.returncode)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: int(item[0])))


def run_local_cli(
    cli_path: Path,
    skill_root: Path,
    command: str,
    payload: bytes,
    *,
    offline: bool = False,
) -> subprocess.CompletedProcess[bytes]:
    arguments = [sys.executable, str(cli_path), command]
    if offline:
        arguments.append("--offline")
    return subprocess.run(
        arguments,
        input=payload,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=skill_root,
        check=False,
        timeout=15,
    )


def parse_json_bytes(value: bytes) -> dict[str, Any] | None:
    try:
        parsed = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def load_fixture(path: Path) -> tuple[bytes | None, dict[str, Any] | None, str | None]:
    if not path.is_file():
        return None, None, "FIXTURE_MISSING"
    try:
        raw = path.read_bytes()
    except OSError:
        return None, None, "FIXTURE_UNREADABLE"
    parsed = parse_json_bytes(raw)
    if parsed is None:
        return raw, None, "FIXTURE_INVALID_JSON"
    return raw, parsed, None


def routed_reference_paths(routes_path: Path) -> tuple[list[str], str | None]:
    """Return every reference path reachable from the gate resource table."""

    try:
        routes = json.loads(routes_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [], "ROUTES_ARTIFACT_MISSING"
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return [], "ROUTES_ARTIFACT_INVALID"
    if not isinstance(routes, dict) or "resources" not in routes:
        return [], "ROUTES_ARTIFACT_INVALID"

    found: set[str] = set()
    invalid = False

    def visit(value: Any) -> None:
        nonlocal invalid
        if isinstance(value, str):
            relative = Path(value)
            if (
                relative.is_absolute()
                or ".." in relative.parts
                or not value.startswith("references/")
            ):
                invalid = True
            else:
                found.add(value)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)
        else:
            invalid = True

    visit(routes["resources"])
    return sorted(found), "GATE_RESOURCE_PATH_INVALID" if invalid else None


def evaluate_gate(
    *,
    skill_root: Path,
    cli_path: Path,
    envelope_bytes: bytes,
    envelope: dict[str, Any],
    expectation: dict[str, Any],
    repetitions: int,
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    results: list[subprocess.CompletedProcess[bytes]] = []

    if not cli_path.is_file():
        append_code(failures, "RUNTIME_CLI_MISSING")
    else:
        for _ in range(repetitions):
            try:
                result = run_local_cli(
                    cli_path,
                    skill_root,
                    "gate",
                    envelope_bytes,
                    offline=True,
                )
            except subprocess.TimeoutExpired:
                append_code(failures, "GATE_TIMEOUT")
                break
            except OSError:
                append_code(failures, "GATE_INVOCATION_FAILED")
                break
            results.append(result)

    outputs = [result.stdout for result in results]
    stderr_outputs = [result.stderr for result in results if result.stderr]
    stdout_summary = summarize_stdout(outputs)

    if len(results) != repetitions:
        append_code(failures, "GATE_RUN_COUNT_MISMATCH")
    if any(result.returncode != 0 for result in results):
        append_code(failures, "GATE_NONZERO_EXIT")
    if stderr_outputs:
        append_code(failures, "GATE_STDERR_NOT_EMPTY")
    if outputs and not stdout_summary["deterministic"]:
        append_code(failures, "GATE_STDOUT_NONDETERMINISTIC")

    observed: dict[str, Any] = {}
    if outputs:
        parsed_output = parse_json_bytes(outputs[0])
        if parsed_output is None:
            append_code(failures, "GATE_OUTPUT_INVALID_JSON")
        else:
            observed = parsed_output

    original_request = envelope.get("original_request")
    expected_request_hash = (
        hashlib.sha256(original_request.encode("utf-8")).hexdigest()
        if isinstance(original_request, str)
        else None
    )
    if observed:
        if observed.get("mode") != expectation["mode"]:
            append_code(failures, "GATE_MODE_MISMATCH")
        if observed.get("resources") != expectation["resources"]:
            append_code(failures, "GATE_RESOURCES_MISMATCH")
        if observed.get("request_sha256") != expected_request_hash:
            append_code(failures, "GATE_REQUEST_HASH_MISMATCH")
        expected_execution = expectation["mode"] == "execute"
        if observed.get("execution_allowed") is not expected_execution:
            append_code(failures, "GATE_EXECUTION_FLAG_MISMATCH")
        trace = observed.get("trace")
        if not isinstance(trace, dict) or trace.get("rule") != expectation["rule"]:
            append_code(failures, "GATE_RULE_MISMATCH")

        resources = observed.get("resources")
        if isinstance(resources, list):
            for relative in resources:
                if not isinstance(relative, str) or not (skill_root / relative).is_file():
                    append_code(failures, "GATE_RESOURCE_MISSING")
                    break

        if expectation["mode"] == "execute":
            forbidden_keys = {"problem_spec", "spec", "questions"}
            if forbidden_keys.intersection(observed):
                append_code(failures, "EXECUTE_GATE_CONTAINS_SPEC")

    gate_result = {
        "expected": {
            "execution_allowed": expectation["mode"] == "execute",
            "mode": expectation["mode"],
            "request_sha256": expected_request_hash,
            "resources": expectation["resources"],
            "rule": expectation["rule"],
        },
        "exit_codes": count_exit_codes(results),
        "observed": observed,
        "repetitions": repetitions,
        "stderr_nonempty_runs": len(stderr_outputs),
        "stderr_sha256": sorted({sha256_bytes(value) for value in stderr_outputs}),
        "stdout": stdout_summary,
    }
    return gate_result, failures


def evaluate_spec(
    *,
    skill_root: Path,
    cli_path: Path,
    spec_path: Path,
    envelope: dict[str, Any],
    expectation: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    if not expectation["requires_spec"]:
        present = spec_path.exists()
        if present:
            append_code(failures, "EXECUTE_SPEC_FIXTURE_PRESENT")
        return {"path": portable_path(spec_path, skill_root), "present": present}, failures

    spec_bytes, spec, load_error = load_fixture(spec_path)
    if load_error == "FIXTURE_MISSING":
        append_code(failures, "SPEC_FIXTURE_MISSING")
    elif load_error == "FIXTURE_UNREADABLE":
        append_code(failures, "SPEC_FIXTURE_UNREADABLE")
    elif load_error == "FIXTURE_INVALID_JSON":
        append_code(failures, "SPEC_FIXTURE_INVALID_JSON")
    if spec_bytes is None or spec is None:
        return {"path": portable_path(spec_path, skill_root), "present": spec_path.is_file()}, failures

    original_request = envelope.get("original_request")
    request_hash = (
        hashlib.sha256(original_request.encode("utf-8")).hexdigest()
        if isinstance(original_request, str)
        else None
    )
    if spec.get("original_request") != original_request:
        append_code(failures, "SPEC_REQUEST_MISMATCH")
    if spec.get("request_sha256") != request_hash:
        append_code(failures, "SPEC_REQUEST_HASH_MISMATCH")
    if spec.get("request_id") != envelope.get("request_id"):
        append_code(failures, "SPEC_REQUEST_ID_MISMATCH")
    signals = envelope.get("signals")
    expected_domain = signals.get("domain") if isinstance(signals, dict) else None
    if spec.get("domain") != expected_domain:
        append_code(failures, "SPEC_DOMAIN_MISMATCH")
    if spec.get("mode") != expectation["mode"]:
        append_code(failures, "SPEC_MODE_MISMATCH")

    validate_result: subprocess.CompletedProcess[bytes] | None = None
    render_result: subprocess.CompletedProcess[bytes] | None = None
    if not cli_path.is_file():
        append_code(failures, "RUNTIME_CLI_MISSING")
    else:
        try:
            validate_result = run_local_cli(
                cli_path, skill_root, "validate", spec_bytes
            )
        except subprocess.TimeoutExpired:
            append_code(failures, "SPEC_VALIDATE_TIMEOUT")
        except OSError:
            append_code(failures, "SPEC_VALIDATE_INVOCATION_FAILED")

        try:
            render_result = run_local_cli(cli_path, skill_root, "render", spec_bytes)
        except subprocess.TimeoutExpired:
            append_code(failures, "SPEC_RENDER_TIMEOUT")
        except OSError:
            append_code(failures, "SPEC_RENDER_INVOCATION_FAILED")

    validation_output: dict[str, Any] = {}
    if validate_result is not None:
        if validate_result.returncode != 0:
            append_code(failures, "SPEC_VALIDATE_NONZERO_EXIT")
        if validate_result.stderr:
            append_code(failures, "SPEC_VALIDATE_STDERR_NOT_EMPTY")
        parsed_validate = parse_json_bytes(validate_result.stdout)
        if parsed_validate is None:
            append_code(failures, "SPEC_VALIDATE_OUTPUT_INVALID_JSON")
        else:
            validation_output = parsed_validate
            if parsed_validate.get("valid") is not True:
                append_code(failures, "SPEC_VALIDATE_REJECTED")

    if render_result is not None:
        if render_result.returncode != 0:
            append_code(failures, "SPEC_RENDER_NONZERO_EXIT")
        if render_result.stderr:
            append_code(failures, "SPEC_RENDER_STDERR_NOT_EMPTY")
        if not render_result.stdout:
            append_code(failures, "SPEC_RENDER_EMPTY")

    spec_result = {
        "fixture_sha256": sha256_bytes(spec_bytes),
        "path": portable_path(spec_path, skill_root),
        "present": True,
        "render": {
            "exit_code": render_result.returncode if render_result is not None else None,
            "stderr_bytes": len(render_result.stderr) if render_result is not None else 0,
            "stdout_bytes": len(render_result.stdout) if render_result is not None else 0,
            "stdout_sha256": (
                sha256_bytes(render_result.stdout)
                if render_result is not None and render_result.stdout
                else None
            ),
        },
        "validate": {
            "exit_code": validate_result.returncode if validate_result is not None else None,
            "stderr_bytes": len(validate_result.stderr) if validate_result is not None else 0,
            "stdout_sha256": (
                sha256_bytes(validate_result.stdout)
                if validate_result is not None and validate_result.stdout
                else None
            ),
            "valid": validation_output.get("valid") is True,
        },
    }
    return spec_result, failures


def evaluate_case(
    *,
    skill_root: Path,
    cli_path: Path,
    expectation: dict[str, Any],
    envelopes_dir: Path | None,
    specs_dir: Path | None,
    repetitions: int,
) -> dict[str, Any]:
    case_id = expectation["case_id"]
    failures: list[str] = []
    envelope_path = (
        envelopes_dir / f"{case_id}.json"
        if envelopes_dir is not None
        else expectation["envelope_path"]
    )
    envelope_bytes, envelope, load_error = load_fixture(envelope_path)
    if load_error == "FIXTURE_MISSING":
        append_code(failures, "ENVELOPE_FIXTURE_MISSING")
    elif load_error == "FIXTURE_UNREADABLE":
        append_code(failures, "ENVELOPE_FIXTURE_UNREADABLE")
    elif load_error == "FIXTURE_INVALID_JSON":
        append_code(failures, "ENVELOPE_FIXTURE_INVALID_JSON")

    case: dict[str, Any] = {
        "case_id": case_id,
        "envelope": {
            "fixture_sha256": sha256_bytes(envelope_bytes) if envelope_bytes is not None else None,
            "path": portable_path(envelope_path, skill_root),
            "present": envelope_path.is_file(),
        },
    }

    if specs_dir is not None:
        spec_path = specs_dir / f"{case_id}.json"
    elif expectation["spec_path"] is not None:
        spec_path = expectation["spec_path"]
    else:
        spec_path = skill_root / "evals" / "runtime" / "fixtures" / "specs" / f"{case_id}.json"
    if envelope_bytes is None or envelope is None:
        case["gate"] = {"not_run": True, "reason": "invalid envelope fixture"}
        case["spec"] = {
            "path": portable_path(spec_path, skill_root),
            "present": spec_path.is_file(),
        }
    else:
        gate_result, gate_failures = evaluate_gate(
            skill_root=skill_root,
            cli_path=cli_path,
            envelope_bytes=envelope_bytes,
            envelope=envelope,
            expectation=expectation,
            repetitions=repetitions,
        )
        case["gate"] = gate_result
        for code in gate_failures:
            append_code(failures, code)

        spec_result, spec_failures = evaluate_spec(
            skill_root=skill_root,
            cli_path=cli_path,
            spec_path=spec_path,
            envelope=envelope,
            expectation=expectation,
        )
        case["spec"] = spec_result
        for code in spec_failures:
            append_code(failures, code)

    case["failure_codes"] = sorted(failures)
    case["status"] = "pass" if not failures else "fail"
    return case


def collect_artifacts(skill_root: Path) -> tuple[dict[str, Any], list[str]]:
    runner_path = Path(__file__).resolve()
    paths = {
        "skill": skill_root / "SKILL.md",
        "cli": skill_root / "scripts" / "dpbp",
        "runner": runner_path,
        "version": skill_root / "VERSION",
        "request_envelope": skill_root / "schemas" / "request-envelope.schema.json",
        "problem_spec": skill_root / "schemas" / "problem-spec.schema.json",
        "problem_state": skill_root / "schemas" / "problem-state.schema.json",
        "routes": skill_root / "runtime" / "routes.json",
    }
    hashes = {name: sha256_file(path) for name, path in paths.items()}
    failures: list[str] = []
    if hashes["skill"] is None:
        append_code(failures, "SKILL_ARTIFACT_MISSING")
    if hashes["cli"] is None:
        append_code(failures, "RUNTIME_CLI_MISSING")
    if hashes["runner"] is None:
        append_code(failures, "RUNTIME_EVAL_RUNNER_MISSING")
    if hashes["version"] is None:
        append_code(failures, "VERSION_ARTIFACT_MISSING")
    if hashes["request_envelope"] is None:
        append_code(failures, "REQUEST_ENVELOPE_SCHEMA_MISSING")
    if hashes["problem_spec"] is None:
        append_code(failures, "PROBLEM_SPEC_SCHEMA_MISSING")
    if hashes["problem_state"] is None:
        append_code(failures, "PROBLEM_STATE_SCHEMA_MISSING")
    if hashes["routes"] is None:
        append_code(failures, "ROUTES_ARTIFACT_MISSING")

    version: str | None = None
    if hashes["version"] is not None:
        try:
            version = paths["version"].read_text(encoding="utf-8").strip()
        except (OSError, UnicodeDecodeError):
            append_code(failures, "VERSION_ARTIFACT_INVALID")
        if not version:
            version = None
            append_code(failures, "VERSION_ARTIFACT_INVALID")

    reference_paths, route_error = routed_reference_paths(paths["routes"])
    if route_error is not None:
        append_code(failures, route_error)
    reference_hashes = {
        relative: sha256_file(skill_root / relative)
        for relative in reference_paths
    }
    if any(value is None for value in reference_hashes.values()):
        append_code(failures, "GATE_REFERENCE_MISSING")

    return (
        {
            "cli_sha256": hashes["cli"],
            "gate_reference_sha256": reference_hashes,
            "routes_sha256": hashes["routes"],
            "runner_sha256": hashes["runner"],
            "schema_sha256": {
                "problem_spec": hashes["problem_spec"],
                "problem_state": hashes["problem_state"],
                "request_envelope": hashes["request_envelope"],
            },
            "skill_sha256": hashes["skill"],
            "version": version,
            "version_sha256": hashes["version"],
        },
        failures,
    )


def build_report(
    *,
    skill_root: Path,
    suite: dict[str, Any],
    repetitions: int,
    envelopes_dir: Path | None = None,
    specs_dir: Path | None = None,
) -> dict[str, Any]:
    cli_path = skill_root / "scripts" / "dpbp"
    artifacts, artifact_failures = collect_artifacts(skill_root)
    override_used = envelopes_dir is not None or specs_dir is not None
    if override_used:
        append_code(artifact_failures, "UNBOUND_FIXTURE_OVERRIDE")
    cases = [
        evaluate_case(
            skill_root=skill_root,
            cli_path=cli_path,
            envelopes_dir=envelopes_dir,
            specs_dir=specs_dir,
            expectation=expectation,
            repetitions=repetitions,
        )
        for expectation in suite["cases"]
    ]

    failure_codes = set(artifact_failures)
    for case in cases:
        failure_codes.update(case["failure_codes"])
    passed = sum(case["status"] == "pass" for case in cases)
    status = "pass" if not failure_codes and passed == len(cases) else "fail"
    return {
        "artifacts": artifacts,
        "cases": cases,
        "environment": {
            "gate_repetitions": repetitions,
            "machine": platform.machine(),
            "model_api_used": False,
            "network_used": False,
            "offline": True,
            "os": platform.platform(),
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
        },
        "failure_codes": sorted(failure_codes),
        "report_type": REPORT_TYPE,
        "schema_version": SCHEMA_VERSION,
        "status": status,
        "suite": {
            "binding_status": "unbound_override" if override_used else "manifest_bound",
            "declared_manifest_sha256": suite["manifest_sha256"],
            "manifest_sha256": None if override_used else suite["manifest_sha256"],
            "suite_id": suite["suite_id"],
            "suite_version": suite["suite_version"],
        },
        "summary": {
            "case_count": len(cases),
            "failed": len(cases) - passed,
            "passed": passed,
        },
    }


def positive_integer(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("repeat must be an integer") from error
    if parsed < 1:
        raise argparse.ArgumentTypeError("repeat must be at least 1")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run four frozen runtime evals without network or model APIs."
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Explicit JSON report path; its parent directory must already exist.",
    )
    parser.add_argument(
        "--repeat",
        type=positive_integer,
        default=100,
        help="Number of byte-for-byte gate repetitions per case (default: 100).",
    )
    parser.add_argument(
        "--skill-root",
        type=Path,
        default=DEFAULT_SKILL_ROOT,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="Override the hash-bound suite manifest.",
    )
    parser.add_argument(
        "--envelopes-dir",
        type=Path,
        default=None,
        help="Override the frozen envelope fixture directory.",
    )
    parser.add_argument(
        "--specs-dir",
        type=Path,
        default=None,
        help="Override the frozen Problem Spec fixture directory.",
    )
    return parser


def write_report(path: Path, report: dict[str, Any]) -> None:
    encoded = (
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    output = arguments.output.expanduser().resolve()
    if not output.parent.is_dir():
        parser.error("--output parent directory must already exist")
    if output.exists() and not output.is_file():
        parser.error("--output must name a file")

    skill_root = arguments.skill_root.expanduser().resolve()
    manifest_path = (
        arguments.manifest.expanduser().resolve()
        if arguments.manifest is not None
        else skill_root / "evals" / "suite-manifest.json"
    )
    try:
        suite = load_suite_manifest(manifest_path, skill_root)
    except ValueError as error:
        parser.error(str(error))
    envelopes_dir = (
        arguments.envelopes_dir.expanduser().resolve()
        if arguments.envelopes_dir is not None
        else None
    )
    specs_dir = (
        arguments.specs_dir.expanduser().resolve()
        if arguments.specs_dir is not None
        else None
    )
    report = build_report(
        skill_root=skill_root,
        suite=suite,
        envelopes_dir=envelopes_dir,
        specs_dir=specs_dir,
        repetitions=arguments.repeat,
    )
    write_report(output, report)
    return 0 if report["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
