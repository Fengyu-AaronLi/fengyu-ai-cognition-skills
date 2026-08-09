#!/usr/bin/env python3
"""Execute frozen eval cases through one fixed, host-observed Codex run each.

The caller chooses only a prepared eval root and a frozen case identifier.  It
cannot replace the prompt, command, argv, artifact contract, or case result.
The host launcher retains process and Codex-thread evidence, then authors the
case-result from those observed bytes before the independent auditor decides
whether the case passed.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from types import ModuleType
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
HOST_SCRIPT = SCRIPT_DIR / "codex_exec_host.py"
AUDITOR_SCRIPT = SCRIPT_DIR / "run_evals.py"
DEFAULT_TIMEOUT_SECONDS = 1800
PROMPT_FILENAME = "host-eval-prompt.txt"
CONTROL_DIRECTORY = ".control"
HOST_DIRECTORY = ".host"


class HostEvalRunnerError(RuntimeError):
    """A fixed-runner precondition or postcondition was not satisfied."""


def _load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise HostEvalRunnerError(f"MODULE_LOAD_FAILED:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HOST = _load_module(HOST_SCRIPT, "sffs_host_eval_codex_exec")
AUDITOR = _load_module(AUDITOR_SCRIPT, "sffs_host_eval_auditor")
DEFAULT_MODEL = HOST.EVAL_MODEL
DEFAULT_REASONING_EFFORT = HOST.EVAL_REASONING_EFFORT
DEFAULT_SANDBOX = HOST.EVAL_SANDBOX
RUNTIME_DIRECTORY = HOST.EVAL_RUNTIME_DIRECTORY


def _assert_prepared_case(eval_root: Path, case_id: str) -> tuple[Path, Path]:
    try:
        root = eval_root.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HostEvalRunnerError("EVAL_ROOT_MISSING") from exc
    if case_id not in AUDITOR.EXPECTED_CASES:
        raise HostEvalRunnerError("EVAL_CASE_ID_NOT_FROZEN")
    case_dir = (root / case_id).resolve(strict=True)
    try:
        case_dir.relative_to(root)
    except ValueError as exc:
        raise HostEvalRunnerError("EVAL_CASE_OUTSIDE_ROOT") from exc
    input_path = case_dir / "input.json"
    context_path = root / AUDITOR.EVALUATION_CONTEXT_FILE
    if (
        not input_path.is_file()
        or input_path.is_symlink()
        or not context_path.is_file()
        or context_path.is_symlink()
    ):
        raise HostEvalRunnerError("EVAL_ROOT_NOT_PREPARED")
    _, _, context_errors = AUDITOR.inspect_evaluation_context(root)
    if context_errors:
        codes = ",".join(sorted({item["code"] for item in context_errors}))
        raise HostEvalRunnerError(f"EVAL_CONTEXT_INVALID:{codes}")
    return case_dir, context_path


def _assert_current_context(eval_root: Path) -> None:
    _, _, errors = AUDITOR.inspect_evaluation_context(eval_root)
    if errors:
        codes = ",".join(sorted({item["code"] for item in errors}))
        raise HostEvalRunnerError(f"EVAL_SOURCE_DRIFT_AFTER_EXECUTION:{codes}")


def _control_dir(eval_root: Path, case_id: str) -> Path:
    return eval_root / CONTROL_DIRECTORY / case_id


def _host_dir(eval_root: Path, case_id: str) -> Path:
    return eval_root / HOST_DIRECTORY / case_id


def _assert_input_only(case_dir: Path) -> None:
    entries = sorted(path.name for path in case_dir.iterdir())
    if entries != ["input.json"]:
        raise HostEvalRunnerError("EVAL_CASE_NOT_INPUT_ONLY")


def prepare_runtime_materials(
    *, eval_root: Path, case_dir: Path, case_id: str
) -> dict[str, list[str]]:
    """Extract the frozen envelope into immutable raw inputs for one fixed run."""
    root = eval_root.resolve(strict=True)
    directory = case_dir.resolve(strict=True)
    try:
        directory.relative_to(root)
    except ValueError as exc:
        raise HostEvalRunnerError("EVAL_CASE_OUTSIDE_ROOT") from exc
    input_path = directory / "input.json"
    try:
        envelope = json.loads(input_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HostEvalRunnerError("EVAL_INPUT_ENVELOPE_INVALID") from exc
    expected = AUDITOR.expected_input_payload(
        case_id, AUDITOR.EXPECTED_CASES[case_id]
    )
    if envelope != expected:
        raise HostEvalRunnerError("EVAL_INPUT_ENVELOPE_MISMATCH")
    texts = envelope.get("turns") if "turns" in envelope else [envelope.get("input")]
    if (
        not isinstance(texts, list)
        or not texts
        or any(not isinstance(item, str) for item in texts)
    ):
        raise HostEvalRunnerError("EVAL_RAW_INPUT_INVALID")
    layout = HOST.eval_runtime_layout(case_id)
    if len(texts) != len(layout["input_paths"]):
        raise HostEvalRunnerError("EVAL_RUNTIME_INPUT_COUNT_MISMATCH")
    runtime_dir = directory / RUNTIME_DIRECTORY
    try:
        runtime_dir.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise HostEvalRunnerError("EVAL_RUNTIME_DIRECTORY_EXISTS") from exc
    for relative, value in zip(layout["input_paths"], texts, strict=True):
        target = directory / relative
        try:
            with target.open("x", encoding="utf-8") as handle:
                handle.write(value)
        except FileExistsError as exc:
            raise HostEvalRunnerError("EVAL_RUNTIME_INPUT_EXISTS") from exc
        target.chmod(0o444)
    for relative in layout["workspace_paths"]:
        if (directory / relative).exists() or (directory / relative).is_symlink():
            raise HostEvalRunnerError("EVAL_RUNTIME_WORKSPACE_EXISTS")
    return layout


def _recover_retained_result(
    *, eval_root: Path, case_dir: Path, case_id: str
) -> dict[str, Any] | None:
    """Replay retained host evidence; never guess or repeat an uncertain run."""
    result_path = case_dir / "case-result.json"
    if result_path.is_file() and not result_path.is_symlink():
        return AUDITOR.audit_case_result(
            eval_root,
            case_id,
            AUDITOR.EXPECTED_CASES[case_id],
        )
    if result_path.exists() or result_path.is_symlink():
        raise HostEvalRunnerError("EVAL_CASE_RESULT_INVALID")

    prompt_path = _control_dir(eval_root, case_id) / PROMPT_FILENAME
    host_dir = _host_dir(eval_root, case_id)
    host_receipt = host_dir / "host-execution-receipt.json"
    if host_receipt.is_file() and not host_receipt.is_symlink():
        _assert_current_context(eval_root)
        try:
            HOST.bind_eval_case_result(
                receipt_path=host_receipt,
                eval_root=eval_root,
                case_id=case_id,
            )
        except FileExistsError:
            pass
        return AUDITOR.audit_case_result(
            eval_root,
            case_id,
            AUDITOR.EXPECTED_CASES[case_id],
        )
    if (
        prompt_path.exists()
        or prompt_path.is_symlink()
        or host_dir.exists()
        or host_dir.is_symlink()
    ):
        raise HostEvalRunnerError("EVAL_OUTCOME_UNKNOWN")
    _assert_input_only(case_dir)
    return None


def build_prompt(*, eval_root: Path, case_dir: Path, case_id: str) -> str:
    """Build the fixed prompt from host-controlled paths and frozen case type."""
    return HOST.build_eval_prompt(
        eval_root=eval_root,
        case_dir=case_dir,
        case_id=case_id,
    )


def run_case(
    *,
    eval_root: Path,
    case_id: str,
    codex_path: Path,
) -> dict[str, Any]:
    """Execute and audit exactly one previously unattempted prepared case."""
    case_dir, context_path = _assert_prepared_case(eval_root, case_id)
    root = eval_root.resolve(strict=True)
    retained = _recover_retained_result(
        eval_root=root,
        case_dir=case_dir,
        case_id=case_id,
    )
    if retained is not None:
        return retained
    codex = codex_path.resolve(strict=True)
    if not codex.is_file() or codex.is_symlink():
        raise HostEvalRunnerError("CODEX_BINARY_INVALID")

    control_parent = root / CONTROL_DIRECTORY
    if control_parent.is_symlink():
        raise HostEvalRunnerError("EVAL_CONTROL_DIRECTORY_INVALID")
    control_parent.mkdir(mode=0o700, exist_ok=True)
    control_dir = _control_dir(root, case_id)
    try:
        control_dir.mkdir(mode=0o700)
    except FileExistsError as exc:
        raise HostEvalRunnerError("EVAL_CASE_ALREADY_CLAIMED") from exc
    prepare_runtime_materials(
        eval_root=root,
        case_dir=case_dir,
        case_id=case_id,
    )
    prompt_path = control_dir / PROMPT_FILENAME
    try:
        with prompt_path.open("x", encoding="utf-8") as handle:
            handle.write(
                build_prompt(eval_root=root, case_dir=case_dir, case_id=case_id)
            )
    except FileExistsError as exc:
        raise HostEvalRunnerError("EVAL_CASE_ALREADY_CLAIMED") from exc
    host_dir = _host_dir(root, case_id)
    receipt_path = HOST.run_codex_execution(
        codex_path=codex,
        prompt_path=prompt_path,
        output_dir=host_dir,
        cwd=case_dir,
        execution_kind="eval",
        subject_id=case_id,
        model=DEFAULT_MODEL,
        reasoning_effort=DEFAULT_REASONING_EFFORT,
        sandbox=DEFAULT_SANDBOX,
        timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        input_path=case_dir / "input.json",
        context_path=context_path,
        source_sha256=AUDITOR.runtime_snapshot_sha256(root),
    )
    if os.environ.get("SFFS_HOST_EVAL_FAILPOINT") == "after_host_receipt":
        raise HostEvalRunnerError("TEST_FAILPOINT:after_host_receipt")
    _assert_current_context(root)
    HOST.bind_eval_case_result(
        receipt_path=receipt_path,
        eval_root=root,
        case_id=case_id,
    )
    result = AUDITOR.audit_case_result(
        root,
        case_id,
        AUDITOR.EXPECTED_CASES[case_id],
    )
    return result


def run_suite(*, eval_root: Path, codex_path: Path) -> dict[str, Any]:
    """Resume a frozen suite without overwriting or rerunning retained evidence."""
    root = eval_root.resolve(strict=True)
    _assert_current_context(root)
    reused_case_ids: list[str] = []
    attempted_case_ids: list[str] = []
    blocked_case_ids: list[str] = []
    execution_errors: list[dict[str, str]] = []
    observed_results: list[dict[str, Any]] = []
    for case_id, case in sorted(AUDITOR.EXPECTED_CASES.items()):
        result_path = root / case_id / "case-result.json"
        if result_path.exists() or result_path.is_symlink():
            audited = AUDITOR.audit_case_result(root, case_id, case)
            observed_results.append(audited)
            if audited.get("valid") is True:
                reused_case_ids.append(case_id)
            else:
                blocked_case_ids.append(case_id)
            continue
        attempted_case_ids.append(case_id)
        try:
            observed_results.append(
                run_case(
                    eval_root=root,
                    case_id=case_id,
                    codex_path=codex_path,
                )
            )
        except (HostEvalRunnerError, HOST.HostExecutionError, OSError, ValueError) as exc:
            execution_errors.append({"case_id": case_id, "error": str(exc)})
    final_audit = AUDITOR.audit_root(root)
    return {
        "valid": final_audit.get("valid") is True and not execution_errors,
        "eval_root": str(root),
        "expected_case_count": len(AUDITOR.EXPECTED_CASES),
        "reused_case_ids": reused_case_ids,
        "attempted_case_ids": attempted_case_ids,
        "blocked_case_ids": blocked_case_ids,
        "execution_errors": execution_errors,
        "observed_results": observed_results,
        "audit": final_audit,
    }


def parser() -> argparse.ArgumentParser:
    cli = argparse.ArgumentParser(description=__doc__)
    subparsers = cli.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="run one frozen prepared case")
    run.add_argument("--eval-root", required=True)
    run.add_argument("--case-id", required=True)
    run_suite_parser = subparsers.add_parser(
        "run-suite", help="run or safely resume the complete frozen suite"
    )
    run_suite_parser.add_argument("--eval-root", required=True)
    return cli


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    codex = shutil.which("codex")
    if not codex:
        print(json.dumps({"valid": False, "error": "CODEX_NOT_FOUND"}, ensure_ascii=False))
        return 2
    try:
        if args.command == "run-suite":
            result = run_suite(
                eval_root=Path(args.eval_root),
                codex_path=Path(codex),
            )
        else:
            result = run_case(
                eval_root=Path(args.eval_root),
                case_id=args.case_id,
                codex_path=Path(codex),
            )
    except (HostEvalRunnerError, HOST.HostExecutionError, OSError, ValueError) as exc:
        print(json.dumps({"valid": False, "error": str(exc)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("valid") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
