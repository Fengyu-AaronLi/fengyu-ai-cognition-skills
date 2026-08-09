#!/usr/bin/env python3
"""Run one fixed internal isolated release-audit suite and emit a v1.2 receipt."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = ROOT.parents[1]
REPOSITORY_INPUT_PREFIX = "@repository/"
CONTROLLED_ENV = {"PYTHONHASHSEED": "0"}
PACKAGE_FILES = (
    "SKILL.md",
    "VERSION",
    "SOURCE_OF_TRUTH.md",
    "README.md",
    "problem-spec.md",
    "PROVENANCE.md",
    "zero-threshold-prompt.md",
    "LICENSE",
    "NOTICE.md",
    "agents/openai.yaml",
    "schemas/analysis.schema.json",
    "schemas/case.schema.json",
    "schemas/event-head.schema.json",
    "schemas/event.schema.json",
    "schemas/workflow-next.schema.json",
    "templates/analysis.json",
    "references/evidence-classes.md",
    "references/policy-rules.md",
    "references/safety-boundaries.md",
    "docs/acceptance.md",
    "docs/evolution.md",
    "docs/quickstart.md",
    "scripts/build_package.py",
    "scripts/identity_label_case.py",
)
PACKAGE_DIRECTORY_FILES = tuple(
    f"{{evidence_dir}}/package/{relative}" for relative in PACKAGE_FILES
) + ("{evidence_dir}/package/PACKAGE-MANIFEST.json",)
PACKAGE_INSTALLED_FILES = tuple(
    f"{{evidence_dir}}/installed-skills/breaking-identity-labels/{relative}"
    for relative in PACKAGE_FILES
) + (
    "{evidence_dir}/installed-skills/breaking-identity-labels/PACKAGE-MANIFEST.json",
)
PACKAGE_ARCHIVE = "{evidence_dir}/breaking-identity-labels.zip"
TEST_SUPPORT_FILES = (
    "tests/fixtures/analysis-c01.json",
    "tests/fixtures/valid-c01.json",
)
RUNTIME_DIRECT_INPUTS = (
    "scripts/identity_label_case.py",
    "schemas/analysis.schema.json",
    "schemas/case.schema.json",
    "schemas/event-head.schema.json",
    "schemas/event.schema.json",
    "schemas/workflow-next.schema.json",
    "templates/analysis.json",
)
BASELINE_EVIDENCE_FILES = (
    "evals/schemas/baseline-evidence-manifest.schema.json",
    "evals/baseline-evidence-manifest.json",
    "evals/cases.json",
    "evals/rubric.md",
    "evals/baseline-report.md",
    "evals/raw/baseline/C01-mbti-capability-verdict.md",
    "evals/raw/baseline/C02-attachment-side-taking.md",
    "evals/raw/baseline/C03-formal-adhd-diagnosis.md",
    "evals/raw/baseline/C04-stable-preference-control.md",
)
LIVE_E2E_EVIDENCE_FILES = (
    "SKILL.md",
    "problem-spec.md",
    "scripts/identity_label_case.py",
    "schemas/analysis.schema.json",
    "schemas/case.schema.json",
    "templates/analysis.json",
    "evals/schemas/live-e2e-manifest.schema.json",
    "evals/schemas/live-e2e-run.schema.json",
    "evals/live-e2e-manifest.json",
    "evals/raw/current-live-e2e-r64/C01-mbti-capability-verdict/input.txt",
    "evals/raw/current-live-e2e-r64/C01-mbti-capability-verdict/scaffold.json",
    "evals/raw/current-live-e2e-r64/C01-mbti-capability-verdict/model-analysis.raw.json",
    "evals/raw/current-live-e2e-r64/C01-mbti-capability-verdict/case.json",
    "evals/raw/current-live-e2e-r64/C01-mbti-capability-verdict/validate.json",
    "evals/raw/current-live-e2e-r64/C01-mbti-capability-verdict/report.md",
    "evals/raw/current-live-e2e-r64/C01-mbti-capability-verdict/delivered-output.md",
    "evals/raw/current-live-e2e-r64/C01-mbti-capability-verdict/run.json",
    "evals/raw/current-live-e2e-r64/C02-attachment-side-taking/input.txt",
    "evals/raw/current-live-e2e-r64/C02-attachment-side-taking/scaffold.json",
    "evals/raw/current-live-e2e-r64/C02-attachment-side-taking/model-analysis.raw.json",
    "evals/raw/current-live-e2e-r64/C02-attachment-side-taking/case.json",
    "evals/raw/current-live-e2e-r64/C02-attachment-side-taking/validate.json",
    "evals/raw/current-live-e2e-r64/C02-attachment-side-taking/report.md",
    "evals/raw/current-live-e2e-r64/C02-attachment-side-taking/delivered-output.md",
    "evals/raw/current-live-e2e-r64/C02-attachment-side-taking/run.json",
    "evals/raw/current-live-e2e-r64/C03-formal-adhd-diagnosis/input.txt",
    "evals/raw/current-live-e2e-r64/C03-formal-adhd-diagnosis/scaffold.json",
    "evals/raw/current-live-e2e-r64/C03-formal-adhd-diagnosis/model-analysis.raw.json",
    "evals/raw/current-live-e2e-r64/C03-formal-adhd-diagnosis/case.json",
    "evals/raw/current-live-e2e-r64/C03-formal-adhd-diagnosis/validate.json",
    "evals/raw/current-live-e2e-r64/C03-formal-adhd-diagnosis/report.md",
    "evals/raw/current-live-e2e-r64/C03-formal-adhd-diagnosis/delivered-output.md",
    "evals/raw/current-live-e2e-r64/C03-formal-adhd-diagnosis/run.json",
    "evals/raw/current-live-e2e-r64/C04-stable-preference-control/input.txt",
    "evals/raw/current-live-e2e-r64/C04-stable-preference-control/scaffold.json",
    "evals/raw/current-live-e2e-r64/C04-stable-preference-control/validate.json",
    "evals/raw/current-live-e2e-r64/C04-stable-preference-control/report.md",
    "evals/raw/current-live-e2e-r64/C04-stable-preference-control/delivered-output.md",
    "evals/raw/current-live-e2e-r64/C04-stable-preference-control/run.json",
    "evals/raw/current-live-e2e-r64/review.json",
)
TEST_EXTRA_INPUTS: dict[str, tuple[str, ...]] = {
    "tests/test_v63_adversarial_runtime.py": RUNTIME_DIRECT_INPUTS,
    "tests/test_v64_live_e2e_behavior.py": (
        "scripts/verify_live_e2e.py",
        *LIVE_E2E_EVIDENCE_FILES,
    ),
    "tests/test_v65_baseline_evidence.py": (
        "scripts/verify_baseline_evidence.py",
        *BASELINE_EVIDENCE_FILES,
    ),
}
AUDIT_DISPLAY_NAMES = {
    "independent_attribution_audit": "内部隔离审计：归因与证据边界",
    "independent_clinical_safety_audit": "内部隔离审计：临床与安全边界",
    "independent_state_integrity_audit": "内部隔离审计：状态与事务完整性",
    "release_package_audit": "内部隔离审计：发行证据与包等价",
}
AUDIT_SUITES: dict[str, tuple[tuple[str, ...], ...]] = {
    "independent_attribution_audit": (
        ("tests/test_v10_attribution_blind_regressions.py", "-v"),
        ("tests/test_v12_attribution_material_regressions.py", "-v"),
        ("tests/test_v22_context_claim_canonical_ledger.py", "-v"),
        ("tests/test_v27_observation_grounding.py", "-v"),
        ("tests/test_v29_clinical_attribution_matrix.py", "-v"),
        ("tests/test_v33_social_page_provenance.py", "-v"),
        ("tests/test_v42_proposition_boundary_hardening.py", "-v"),
        ("tests/test_v63_adversarial_runtime.py", "-v"),
    ),
    "independent_clinical_safety_audit": (
        ("tests/test_v10_clinical_audit_regressions.py", "-v"),
        ("tests/test_v12_preclinical_blockers.py", "-v"),
        ("tests/test_v12_safety_routing_regressions.py", "-v"),
        ("tests/test_v21_generated_output_safety_matrix.py", "-v"),
        ("tests/test_v23_medical_request_routing_matrix.py", "-v"),
        ("tests/test_v25_immediate_safety_event_matrix.py", "-v"),
        ("tests/test_v40_safety_first_output_contract.py", "-v"),
        ("tests/test_v41_route_specific_output_contracts.py", "-v"),
        ("tests/test_v63_adversarial_runtime.py", "-v"),
        ("tests/test_v66_runtime_safety.py", "-v"),
    ),
    "independent_state_integrity_audit": (
        ("tests/test_v10_state_transaction_regressions.py", "-v"),
        ("tests/test_v11_operation_integrity.py", "-v"),
        ("tests/test_v11_state_recovery_regressions.py", "-v"),
        ("tests/test_v34_evolution_event_semantic_replay.py", "-v"),
        ("tests/test_v35_command_execution_snapshot.py", "-v"),
        ("tests/test_v43_candidate_snapshot_and_schema_fail_closed.py", "-v"),
        ("tests/test_v45_manifest_migration_semantic_replay.py", "-v"),
        ("tests/test_v46_audit_completed_run_binding.py", "-v"),
        ("tests/test_v47_blocker_resolution_loop.py", "-v"),
        ("tests/test_v48_evolution_lock_and_execution_boundary.py", "-v"),
        ("tests/test_v63_adversarial_runtime.py", "-v"),
        ("tests/test_v66_state_preference.py", "-v"),
    ),
    "release_package_audit": (
        ("tests/test_release_package.py", "-v"),
        ("tests/test_release_loop_contract.py", "-v"),
        ("tests/test_v49_evaluation_freshness_contract.py", "-v"),
        ("tests/test_v50_demo_verifier.py", "-v"),
        ("tests/test_v64_live_e2e_behavior.py", "-v"),
        ("tests/test_v66_evidence_package.py", "-v"),
        (
            "scripts/verify_live_e2e.py",
            "--root",
            ".",
            "--manifest",
            "evals/live-e2e-manifest.json",
        ),
        ("tests/test_v65_baseline_evidence.py", "-v"),
        (
            "scripts/verify_baseline_evidence.py",
            "--root",
            ".",
            "--manifest",
            "evals/baseline-evidence-manifest.json",
        ),
        (
            "scripts/build_package.py",
            "build",
            "--out",
            "{evidence_dir}/package",
            "--archive",
            "{evidence_dir}/breaking-identity-labels.zip",
        ),
        (
            "scripts/build_package.py",
            "verify",
            "--package",
            "{evidence_dir}/package",
        ),
        (
            "scripts/build_package.py",
            "verify",
            "--package",
            "{evidence_dir}/breaking-identity-labels.zip",
        ),
        (
            "scripts/build_package.py",
            "install",
            "--package",
            "{evidence_dir}/breaking-identity-labels.zip",
            "--skills-dir",
            "{evidence_dir}/installed-skills",
        ),
        (
            "scripts/build_package.py",
            "verify",
            "--package",
            "{evidence_dir}/installed-skills/breaking-identity-labels",
        ),
        (
            "scripts/verify_package_equivalence.py",
            "--directory",
            "{evidence_dir}/package",
            "--archive",
            "{evidence_dir}/breaking-identity-labels.zip",
            "--installed",
            "{evidence_dir}/installed-skills/breaking-identity-labels",
        ),
    ),
}


class AuditHarnessError(RuntimeError):
    pass


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def relative(path: Path) -> str:
    target = path.resolve()
    try:
        return target.relative_to(ROOT).as_posix()
    except ValueError:
        try:
            return REPOSITORY_INPUT_PREFIX + target.relative_to(REPOSITORY_ROOT).as_posix()
        except ValueError as error:
            raise AuditHarnessError("audit_input_path_unsafe") from error


def regression_dependency_templates() -> tuple[str, ...]:
    manifest_path = ROOT / "evals" / "regression-dependency-manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditHarnessError("audit_dependency_manifest_invalid") from error
    if set(manifest) != {"schema_version", "files"} or manifest.get("schema_version") != "1.0":
        raise AuditHarnessError("audit_dependency_manifest_invalid")
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise AuditHarnessError("audit_dependency_manifest_invalid")
    identities: list[tuple[str, str]] = []
    values: list[str] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"scope", "path", "sha256"}:
            raise AuditHarnessError("audit_dependency_manifest_invalid")
        scope, relative_path, expected = record.get("scope"), record.get("path"), record.get("sha256")
        if (
            scope not in {"skill", "repository"}
            or not isinstance(relative_path, str)
            or Path(relative_path).is_absolute()
            or ".." in Path(relative_path).parts
            or not isinstance(expected, str)
            or re.fullmatch(r"[0-9a-f]{64}", expected) is None
        ):
            raise AuditHarnessError("audit_dependency_manifest_invalid")
        template = relative_path if scope == "skill" else REPOSITORY_INPUT_PREFIX + relative_path
        base = ROOT if scope == "skill" else REPOSITORY_ROOT
        target = (base / relative_path).resolve()
        try:
            target.relative_to(base)
        except ValueError as error:
            raise AuditHarnessError("audit_dependency_manifest_invalid") from error
        if not target.is_file() or target.is_symlink() or sha256_file(target) != expected:
            raise AuditHarnessError("audit_dependency_manifest_hash_mismatch")
        identities.append((scope, relative_path))
        values.append(template)
    if identities != sorted(set(identities)):
        raise AuditHarnessError("audit_dependency_manifest_invalid")
    return tuple(values)


def audit_input_templates(
    audit_id: str,
    command_index: int,
    command: tuple[str, ...],
) -> tuple[str, ...]:
    """Return the fixed direct-input declaration for one audit command."""

    del command_index
    declared: list[str] = [command[0]]
    if command[0].startswith("tests/"):
        declared.append("evals/test-generation-manifest.json")
        declared.append("evals/regression-dependency-manifest.json")
        declared.extend(regression_dependency_templates())
        declared.extend(TEST_SUPPORT_FILES)
        declared.extend(TEST_EXTRA_INPUTS.get(command[0], ()))
    elif audit_id == "release_package_audit":
        if command[0] == "scripts/verify_live_e2e.py":
            declared.extend(LIVE_E2E_EVIDENCE_FILES)
        elif command[0] == "scripts/verify_baseline_evidence.py":
            declared.extend(BASELINE_EVIDENCE_FILES)
        elif command[0] == "scripts/build_package.py" and command[1] == "build":
            declared.extend(PACKAGE_FILES)
        elif command[0] == "scripts/build_package.py" and command[1] == "verify":
            target = command[-1]
            if target == "{evidence_dir}/package":
                declared.extend(PACKAGE_DIRECTORY_FILES)
            elif target == PACKAGE_ARCHIVE:
                declared.append(PACKAGE_ARCHIVE)
            elif target == "{evidence_dir}/installed-skills/breaking-identity-labels":
                declared.extend(PACKAGE_INSTALLED_FILES)
            else:
                raise AuditHarnessError("audit_package_input_declaration_invalid")
        elif command[0] == "scripts/build_package.py" and command[1] == "install":
            declared.append(PACKAGE_ARCHIVE)
        elif command[0] == "scripts/verify_package_equivalence.py":
            declared.extend(PACKAGE_DIRECTORY_FILES)
            declared.append(PACKAGE_ARCHIVE)
            declared.extend(PACKAGE_INSTALLED_FILES)
            declared.append("scripts/build_package.py")
        else:
            raise AuditHarnessError("audit_package_input_declaration_invalid")
    return tuple(dict.fromkeys(declared))


def audit_input_paths(
    audit_id: str,
    command_index: int,
    command: tuple[str, ...],
    evidence_dir: Path,
    *,
    require_available: bool,
) -> list[Path]:
    """Resolve one preregistered input set within the Skill root."""

    evidence_dir = evidence_dir.expanduser().resolve()
    try:
        evidence_dir.relative_to(ROOT)
    except ValueError as error:
        raise AuditHarnessError("audit_evidence_dir_unsafe") from error
    paths: list[Path] = []
    for template in audit_input_templates(audit_id, command_index, command):
        rendered = template.replace("{evidence_dir}", str(evidence_dir))
        if "{" in rendered or "}" in rendered or "\x00" in rendered:
            raise AuditHarnessError("audit_input_path_invalid")
        if rendered.startswith(REPOSITORY_INPUT_PREFIX):
            relative_path = rendered[len(REPOSITORY_INPUT_PREFIX) :]
            if Path(relative_path).is_absolute() or ".." in Path(relative_path).parts:
                raise AuditHarnessError("audit_input_path_unsafe")
            candidate = REPOSITORY_ROOT / relative_path
            allowed_root = REPOSITORY_ROOT
        else:
            candidate = Path(rendered)
            if not candidate.is_absolute():
                candidate = ROOT / candidate
            allowed_root = ROOT
        target = candidate.resolve()
        try:
            target.relative_to(allowed_root)
        except ValueError as error:
            raise AuditHarnessError("audit_input_path_unsafe") from error
        if require_available and (not target.is_file() or target.is_symlink()):
            raise AuditHarnessError("audit_input_unavailable")
        paths.append(target)
    if len(paths) != len(set(paths)):
        raise AuditHarnessError("audit_input_duplicate")
    return sorted(paths, key=relative)


def input_snapshot(paths: list[Path]) -> dict:
    return {
        "cwd": ".",
        "environment": dict(CONTROLLED_ENV),
        "files": [
            {"path": relative(path), "sha256": sha256_file(path)} for path in paths
        ],
    }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise AuditHarnessError(f"audit_refuses_overwrite:{relative(path)}")
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        raise


def write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise AuditHarnessError(f"audit_refuses_overwrite:{relative(path)}")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def read_json(path: Path, code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise AuditHarnessError(code) from error
    if not isinstance(value, dict):
        raise AuditHarnessError(code)
    return value


def suite_errors() -> list[str]:
    errors: list[str] = []
    expected = {
        "independent_attribution_audit",
        "independent_clinical_safety_audit",
        "independent_state_integrity_audit",
        "release_package_audit",
    }
    if set(AUDIT_SUITES) != expected:
        errors.append("audit_suite_inventory_invalid")
    if set(AUDIT_DISPLAY_NAMES) != expected:
        errors.append("audit_display_name_inventory_invalid")
    for audit_id, commands in AUDIT_SUITES.items():
        if not commands:
            errors.append(f"audit_suite_empty:{audit_id}")
            continue
        for command_index, command in enumerate(commands):
            if not isinstance(command, tuple) or len(command) < 2:
                errors.append(f"audit_command_invalid:{audit_id}")
                continue
            if any(token in {"sh", "bash", "zsh", "-c"} for token in command):
                errors.append(f"audit_shell_command_forbidden:{audit_id}")
            script = ROOT / command[0]
            if not script.is_file() or script.is_symlink():
                errors.append(f"audit_script_missing:{command[0]}")
            try:
                audit_input_paths(
                    audit_id,
                    command_index,
                    command,
                    ROOT / "evals" / "receipts" / ".audit-self-check",
                    require_available=False,
                )
            except AuditHarnessError as error:
                errors.append(str(error))
    return sorted(set(errors))


def self_check() -> int:
    errors = suite_errors()
    payload = {
        "schema_version": "1.0",
        "valid": not errors,
        "audit_ids": sorted(AUDIT_SUITES),
        "audit_display_names": {
            key: AUDIT_DISPLAY_NAMES[key] for key in sorted(AUDIT_DISPLAY_NAMES)
        },
        "command_counts": {key: len(value) for key, value in AUDIT_SUITES.items()},
        "controlled_environment_keys": sorted(CONTROLLED_ENV),
        "shell_execution": False,
        "errors": errors,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not errors else 1


def expand_command(command: tuple[str, ...], evidence_dir: Path) -> list[str]:
    expanded = [token.replace("{evidence_dir}", str(evidence_dir)) for token in command]
    return [sys.executable, str((ROOT / expanded[0]).resolve()), *expanded[1:]]


def load_frozen_binding(state_path: Path, run_dir: Path) -> tuple[dict, dict]:
    state = read_json(state_path, "audit_release_state_invalid")
    completed = state.get("completed_run")
    if not isinstance(completed, dict):
        raise AuditHarnessError("audit_completed_run_required")
    if state.get("distribution_status") != "local_unpublished" or state.get("publication_actions_performed") is not False:
        raise AuditHarnessError("audit_distribution_boundary_invalid")
    if completed.get("run_dir") != relative(run_dir):
        raise AuditHarnessError("audit_completed_run_dir_mismatch")
    run_state = read_json(run_dir / "run-state.json", "audit_run_state_invalid")
    if run_state.get("status") != "complete":
        raise AuditHarnessError("audit_run_not_complete")
    if run_state.get("candidate_id") != state.get("candidate_id"):
        raise AuditHarnessError("audit_candidate_mismatch")
    if completed.get("run_state_sha256") != sha256_file(run_dir / "run-state.json"):
        raise AuditHarnessError("audit_run_state_drift")
    return state, completed


def run_audit(args: argparse.Namespace) -> int:
    errors = suite_errors()
    if errors:
        raise AuditHarnessError(errors[0])
    state_path = args.state.expanduser().resolve()
    run_dir = args.run_dir.expanduser().resolve()
    state, completed = load_frozen_binding(state_path, run_dir)
    audit_id = args.audit_id
    candidate_id = str(state["candidate_id"])
    receipt_id = args.receipt_id or f"{audit_id}-{candidate_id}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", receipt_id):
        raise AuditHarnessError("audit_receipt_id_invalid")
    evidence_dir = ROOT / "evals" / "receipts" / receipt_id
    receipt_path = ROOT / "evals" / "receipts" / f"{receipt_id}.json"
    if evidence_dir.exists() or evidence_dir.is_symlink() or receipt_path.exists() or receipt_path.is_symlink():
        raise AuditHarnessError("audit_refuses_overwrite")
    evidence_dir.mkdir(parents=True)

    command_templates = AUDIT_SUITES[audit_id]
    preregistration = {
        "schema_version": "1.0",
        "audit_id": audit_id,
        "candidate_id": candidate_id,
        "completed_run_sha256": completed["run_state_sha256"],
        "objective": (
            f"{AUDIT_DISPLAY_NAMES[audit_id]}。仅在该审计域内尝试证伪冻结候选，"
            "不声称外部独立认证。"
        ),
        "commands": [
            {
                "argv": list(command),
                "input_files": list(
                    audit_input_templates(audit_id, index, command)
                ),
            }
            for index, command in enumerate(command_templates)
        ],
        "pass_condition": (
            "Every preregistered command exits zero, every direct input is hash-bound "
            "before execution, and package directory, archive and installed tree digests "
            "and manifest bytes agree when the package suite is selected."
        ),
        "live_model_called": False,
    }
    prereg_path = evidence_dir / "preregistration.json"
    write_json(prereg_path, preregistration)

    environment = {
        "schema_version": "1.0",
        "python_executable": sys.executable,
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "platform": platform.platform(),
        "cwd": str(ROOT),
        "controlled_environment": CONTROLLED_ENV,
        "parent_environment_inherited": False,
        "shell_execution": False,
        "live_model_called": False,
        "network_required": False,
        "harness_sha256": sha256_file(Path(__file__).resolve()),
    }
    environment_path = evidence_dir / "environment.json"
    write_json(environment_path, environment)

    commands: list[dict] = []
    findings: list[dict] = []
    blockers: list[dict] = []
    package_tree_digests: list[tuple[int, str]] = []
    package_manifest_digests: list[tuple[int, str]] = []
    for index, template in enumerate(command_templates, start=1):
        argv = expand_command(template, evidence_dir)
        declared_inputs = audit_input_paths(
            audit_id,
            index - 1,
            template,
            evidence_dir,
            require_available=True,
        )
        snapshot = input_snapshot(declared_inputs)
        result = subprocess.run(
            argv,
            cwd=ROOT,
            env=CONTROLLED_ENV,
            capture_output=True,
            check=False,
        )
        stdout_path = evidence_dir / f"command-{index:02d}.stdout.txt"
        stderr_path = evidence_dir / f"command-{index:02d}.stderr.txt"
        write_bytes(stdout_path, result.stdout)
        write_bytes(stderr_path, result.stderr)
        command_record = {
            "argv": argv,
            "script_path": relative(Path(argv[1])),
            "script_sha256": sha256_file(Path(argv[1])),
            "input_snapshot": snapshot,
            "exit_code": result.returncode,
            "stdout_path": relative(stdout_path),
            "stdout_sha256": sha256_file(stdout_path),
            "stderr_path": relative(stderr_path),
            "stderr_sha256": sha256_file(stderr_path),
        }
        commands.append(command_record)
        outcome = "pass" if result.returncode == 0 else "block"
        finding_id = f"{audit_id}-command-{index:02d}"
        findings.append(
            {
                "id": finding_id,
                "outcome": outcome,
                "assertion": "The preregistered command exits zero on the frozen candidate.",
                "command_index": index - 1,
            }
        )
        if result.returncode != 0:
            blockers.append({"id": finding_id, "severity": "P1"})
        elif (
            audit_id == "release_package_audit"
            and template[0]
            in {"scripts/build_package.py", "scripts/verify_package_equivalence.py"}
        ):
            try:
                command_payload = json.loads(result.stdout)
            except json.JSONDecodeError:
                command_payload = None
            tree_sha256 = (
                command_payload.get("tree_sha256")
                if isinstance(command_payload, dict)
                else None
            )
            if not isinstance(tree_sha256, str) or not re.fullmatch(
                r"[0-9a-f]{64}", tree_sha256
            ):
                blockers.append(
                    {"id": f"{finding_id}-package-tree-missing", "severity": "P1"}
                )
            else:
                package_tree_digests.append((index - 1, tree_sha256))
            manifest_sha256 = (
                command_payload.get("manifest_sha256")
                if isinstance(command_payload, dict)
                else None
            )
            if not isinstance(manifest_sha256, str) or not re.fullmatch(
                r"[0-9a-f]{64}", manifest_sha256
            ):
                blockers.append(
                    {"id": f"{finding_id}-package-manifest-missing", "severity": "P1"}
                )
            else:
                package_manifest_digests.append((index - 1, manifest_sha256))

    if audit_id == "release_package_audit":
        frozen_tree = state.get("artifacts", {}).get("package_tree_sha256")
        observed = [digest for _index, digest in package_tree_digests]
        tree_identity_passed = (
            len(observed) == 6
            and isinstance(frozen_tree, str)
            and re.fullmatch(r"[0-9a-f]{64}", frozen_tree) is not None
            and set(observed) == {frozen_tree}
        )
        tree_finding_id = "release_package_audit-tree-identity"
        findings.append(
            {
                "id": tree_finding_id,
                "outcome": "pass" if tree_identity_passed else "block",
                "assertion": (
                    "Build, directory verify, archive verify, install, installed verify "
                    "and equivalence outputs share the frozen package tree digest."
                ),
                "command_indexes": [index for index, _digest in package_tree_digests],
                "frozen_tree_sha256": frozen_tree,
                "observed_tree_sha256": observed,
            }
        )
        if not tree_identity_passed:
            blockers.append({"id": tree_finding_id, "severity": "P1"})
        observed_manifests = [
            digest for _index, digest in package_manifest_digests
        ]
        manifest_identity_passed = (
            len(observed_manifests) == 6
            and len(set(observed_manifests)) == 1
        )
        manifest_finding_id = "release_package_audit-manifest-identity"
        findings.append(
            {
                "id": manifest_finding_id,
                "outcome": "pass" if manifest_identity_passed else "block",
                "assertion": (
                    "Build, directory verify, archive verify, install, installed verify "
                    "and equivalence outputs share one PACKAGE-MANIFEST byte digest."
                ),
                "command_indexes": [
                    index for index, _digest in package_manifest_digests
                ],
                "observed_manifest_sha256": observed_manifests,
            }
        )
        if not manifest_identity_passed:
            blockers.append({"id": manifest_finding_id, "severity": "P1"})

    raw_output = {
        "schema_version": "1.0",
        "audit_id": audit_id,
        "candidate_id": candidate_id,
        "completed_run_sha256": completed["run_state_sha256"],
        "command_count": len(commands),
        "passed": len(blockers) == 0,
        "commands": commands,
        "findings": findings,
        "blockers": blockers,
    }
    raw_path = evidence_dir / "raw-output.json"
    write_json(raw_path, raw_output)

    receipt = {
        "schema_version": "1.2",
        "receipt_id": receipt_id,
        "audit_id": audit_id,
        "candidate": {
            "candidate_id": candidate_id,
            "artifacts": state["artifacts"],
            "test_manifest_sha256": state["test_manifest_sha256"],
        },
        "completed_run": completed,
        "preregistration": {
            "path": relative(prereg_path),
            "case_set_sha256": sha256_file(prereg_path),
        },
        "environment": {
            "path": relative(environment_path),
            "sha256": sha256_file(environment_path),
        },
        "commands": commands,
        "raw_output_path": relative(raw_path),
        "raw_output_sha256": sha256_file(raw_path),
        "manual_findings": findings,
        "blockers": blockers,
        "status": "passed" if not blockers else "blocked",
    }
    write_json(receipt_path, receipt)
    summary = {
        "schema_version": "1.0",
        "valid": not blockers,
        "audit_id": audit_id,
        "audit_display_name": AUDIT_DISPLAY_NAMES[audit_id],
        "receipt": relative(receipt_path),
        "receipt_sha256": sha256_file(receipt_path),
        "command_count": len(commands),
        "blocker_count": len(blockers),
        "status": receipt["status"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if not blockers else 2


def parser() -> argparse.ArgumentParser:
    top = argparse.ArgumentParser(description=__doc__)
    commands = top.add_subparsers(dest="command", required=True)
    self_check_parser = commands.add_parser("self-check")
    self_check_parser.set_defaults(handler=lambda _args: self_check())
    run = commands.add_parser("run")
    run.add_argument("--state", type=Path, default=ROOT / "evals" / "release-gate.json")
    run.add_argument("--run-dir", type=Path, required=True)
    run.add_argument(
        "--audit-id",
        choices=sorted(AUDIT_SUITES),
        required=True,
        help="legacy machine audit identifier; user-facing status is 内部隔离审计",
    )
    run.add_argument("--receipt-id")
    run.set_defaults(handler=run_audit)
    return top


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except (AuditHarnessError, OSError, ValueError, KeyError) as error:
        print(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "valid": False,
                    "errors": [str(error) or "audit_harness_error"],
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
