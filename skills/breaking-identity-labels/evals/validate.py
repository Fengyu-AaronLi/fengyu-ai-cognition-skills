#!/usr/bin/env python3
"""Validate the complete local V78 Skill candidate without third-party modules."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
CLI = ROOT / "scripts" / "identity_label_case.py"
PACKAGE_BUILDER = ROOT / "scripts" / "build_package.py"
EVOLUTION_CONTROLLER = ROOT / "scripts" / "run_evolution.py"
DEMO_VERIFIER = ROOT / "scripts" / "verify_demo.py"
BASELINE_EVIDENCE_VERIFIER = ROOT / "scripts" / "verify_baseline_evidence.py"
LIVE_E2E_VERIFIER = ROOT / "scripts" / "verify_live_e2e.py"

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument(
    "--results",
    type=Path,
    default=EVALS / "v2-results.json",
    help="offline evaluation result to validate against the current runtime, evaluator and datasets",
)
parser.add_argument(
    "--include-release-state",
    action="store_true",
    help="also compare mutable release-gate state with the evolution controller",
)
parser.add_argument(
    "--release-state",
    type=Path,
    default=EVALS / "release-gate.json",
    help="release state used only when --include-release-state is present",
)
ARGS = parser.parse_args()


def fail(message: str) -> None:
    print(f"FAIL: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_json(relative: str) -> dict:
    try:
        return json.loads((ROOT / relative).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot read valid JSON from {relative}: {error}")


def read_json_path(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.expanduser().resolve().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        fail(f"cannot read valid JSON from {label}: {error}")
    if not isinstance(value, dict):
        fail(f"JSON root is not an object: {label}")
    return value


required_files = [
    "SKILL.md",
    "VERSION",
    "SOURCE_OF_TRUTH.md",
    "agents/openai.yaml",
    "README.md",
    "problem-spec.md",
    "PROVENANCE.md",
    "zero-threshold-prompt.md",
    "LICENSE",
    "NOTICE.md",
    "Makefile",
    "schemas/case.schema.json",
    "schemas/analysis.schema.json",
    "schemas/event.schema.json",
    "schemas/event-head.schema.json",
    "schemas/workflow-next.schema.json",
    "schemas/release-gate.schema.json",
    "schemas/audit-receipt.schema.json",
    "schemas/evolution-workflow.schema.json",
    "schemas/evolution-run-state.schema.json",
    "schemas/evolution-command-receipt.schema.json",
    "schemas/evolution-external-receipt.schema.json",
    "schemas/test-migration-receipt.schema.json",
    "schemas/test-generation-manifest.schema.json",
    "schemas/blocker-resolution-receipt.schema.json",
    "templates/analysis.json",
    "references/evidence-classes.md",
    "references/policy-rules.md",
    "references/safety-boundaries.md",
    "docs/quickstart.md",
    "docs/acceptance.md",
    "docs/evolution.md",
    "scripts/identity_label_case.py",
    "scripts/build_demo.py",
    "scripts/build_package.py",
    "scripts/run_evolution.py",
    "scripts/run_regressions.py",
    "scripts/run_blindspot_discovery.py",
    "scripts/sync_regression_dependencies.py",
    "scripts/verify_red_evidence.py",
    "scripts/verify_red_evidence_manifest.py",
    "scripts/verify_demo.py",
    "scripts/verify_baseline_evidence.py",
    "scripts/verify_live_e2e.py",
    # Historical V61 verifier retained for evidence replay, not current validation.
    "scripts/verify_live_retest.py",
    "scripts/verify_evaluation.py",
    "scripts/verify_package_equivalence.py",
    "scripts/run_release_audits.py",
    "evals/red-evidence-manifest.json",
    "evals/schemas/red-evidence-manifest.schema.json",
    "tests/test_identity_label_case.py",
    "tests/test_v2_acceptance.py",
    "tests/test_refinement_regressions.py",
    "tests/test_final_forward_regressions.py",
    "tests/test_workflow_loop.py",
    "tests/test_v6_adversarial_regressions.py",
    "tests/test_v7_audit_regressions.py",
    "tests/test_v7_release_matrix.py",
    "tests/test_v8_semantic_regressions.py",
    "tests/test_v8_time_integrity.py",
    "tests/test_v9_attribution_events.py",
    "tests/test_v9_audit_exact_regressions.py",
    "tests/test_v9_clinical_safety_events.py",
    "tests/test_v10_attribution_blind_regressions.py",
    "tests/test_v10_attribution_event_integrity.py",
    "tests/test_v10_clinical_audit_regressions.py",
    "tests/test_v10_clinical_p2_regressions.py",
    "tests/test_v10_state_transaction_regressions.py",
    "tests/test_v11_blind_semantic_regressions.py",
    "tests/test_v11_state_recovery_regressions.py",
    "tests/test_v11_evolution_controller.py",
    "tests/test_release_loop_contract.py",
    "tests/test_release_package.py",
    "tests/test_v49_evaluation_freshness_contract.py",
    "tests/test_v50_demo_verifier.py",
    "tests/test_v51_release_audit_harness.py",
    "tests/test_v54_release_evidence_closure.py",
    "tests/test_v55_audit_receipt_input_integrity.py",
    "tests/test_v57_release_proof_fail_closed.py",
    "tests/test_v58_safe_cli_ingress.py",
    "tests/test_v59_current_live_retest.py",
    "tests/test_v60_blocker_resolution_current_receipt.py",
    "tests/test_v61_unreported_message_content.py",
    "tests/test_v62_validation_release_separation.py",
    "tests/test_v63_adversarial_runtime.py",
    "tests/test_v64_live_e2e_behavior.py",
    "tests/test_v65_baseline_evidence.py",
    "evals/cases.json",
    "evals/upgrade-cases.json",
    "evals/heldout-cases.json",
    "evals/boundary-cases.json",
    "evals/run_v2_evals.py",
    "evals/v2-results.json",
    "evals/test-generation-manifest.json",
    "evals/schemas/baseline-evidence-manifest.schema.json",
    "evals/schemas/live-e2e-manifest.schema.json",
    "evals/schemas/live-e2e-run.schema.json",
    "evals/baseline-evidence-manifest.json",
    "evals/live-e2e-manifest.json",
    "evals/fresh-candidate-e2e-manifest.json",
    "evals/regression-dependency-manifest.json",
    # Historical V61 manifest retained for evidence replay, not current validation.
    "evals/live-retest-manifest.json",
    "evals/architecture-red.md",
    "evals/rubric.md",
    "evals/baseline-report.md",
    "examples/real-run/demo-input.txt",
    "examples/real-run/analysis.json",
    "examples/real-run/case.json",
    "examples/real-run/events.jsonl",
    "examples/real-run/events.head.json",
    "examples/real-run/report.md",
    "examples/real-run/run-manifest.json",
    "launch/video-brief.md",
    "workflows/v2-evolution.yaml",
    "workflows/v15-evolution.json",
    # V51 and V65 are historical; V68 is a compatibility predecessor; V78 is current.
    "workflows/v51-final-release.json",
    "workflows/v65-final-release.json",
    "workflows/v68-final-release.json",
    "workflows/v78-final-release.json",
    "workflows/roles/runtime-engineer.md",
    "workflows/roles/adversarial-tester.md",
    "workflows/roles/clinical-boundary-reviewer.md",
    "workflows/roles/release-auditor.md",
]
if ARGS.include_release_state:
    required_files.append("evals/release-gate.json")

current_live_e2e_root = "evals/raw/current-live-e2e-r64"
current_live_e2e_case_files = {
    "C01-mbti-capability-verdict": (
        "input.txt",
        "scaffold.json",
        "model-analysis.raw.json",
        "case.json",
        "validate.json",
        "report.md",
        "delivered-output.md",
        "run.json",
    ),
    "C02-attachment-side-taking": (
        "input.txt",
        "scaffold.json",
        "model-analysis.raw.json",
        "case.json",
        "validate.json",
        "report.md",
        "delivered-output.md",
        "run.json",
    ),
    "C03-formal-adhd-diagnosis": (
        "input.txt",
        "scaffold.json",
        "model-analysis.raw.json",
        "case.json",
        "validate.json",
        "report.md",
        "delivered-output.md",
        "run.json",
    ),
    "C04-stable-preference-control": (
        "input.txt",
        "scaffold.json",
        "validate.json",
        "report.md",
        "delivered-output.md",
        "run.json",
    ),
}
required_files.append(f"{current_live_e2e_root}/review.json")
for case_id, names in current_live_e2e_case_files.items():
    required_files.extend(
        f"{current_live_e2e_root}/{case_id}/{name}" for name in names
    )

fresh_live_e2e_root = "evals/raw/fresh-candidate-e2e-r76"
fresh_live_e2e_case_files = {
    case_id: names + ("agent-request.json", "agent-response.json")
    for case_id, names in current_live_e2e_case_files.items()
}
required_files.append(f"{fresh_live_e2e_root}/review.json")
for case_id, names in fresh_live_e2e_case_files.items():
    required_files.extend(
        f"{fresh_live_e2e_root}/{case_id}/{name}" for name in names
    )
missing = [relative for relative in required_files if not (ROOT / relative).is_file()]
if missing:
    fail(f"missing required V78 candidate files: {', '.join(missing)}")

version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
if not re.fullmatch(r"2\.0\.0-alpha\.[1-9][0-9]*", version):
    fail(f"VERSION is not a supported V2 alpha release: {version}")

skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
skill_lines = skill.splitlines()
if not skill_lines or skill_lines[0] != "---":
    fail("SKILL.md must start with YAML frontmatter")
try:
    frontmatter_end = skill_lines.index("---", 1)
except ValueError:
    fail("SKILL.md frontmatter is not closed")
frontmatter = {}
for line in skill_lines[1:frontmatter_end]:
    if ":" in line:
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip()
if set(frontmatter) != {"name", "description"}:
    fail("SKILL.md frontmatter must contain only name and description")
if frontmatter.get("name") != "breaking-identity-labels":
    fail("SKILL.md name is incorrect")
if not re.fullmatch(r"[a-z0-9-]+", frontmatter["name"]):
    fail("SKILL.md name must use lowercase letters, digits and hyphens")
description = frontmatter.get("description", "")
if not description.startswith("Use when") or len(description) > 1024:
    fail("SKILL.md description must be a valid Use when trigger")
if len(skill_lines) >= 220:
    fail(f"SKILL.md orchestration layer is too long: {len(skill_lines)} lines")

runtime_commands = (
    "identity_label_case.py scaffold",
    "identity_label_case.py compile",
    "identity_label_case.py validate",
    "identity_label_case.py render",
    "identity_label_case.py init",
    "identity_label_case.py plan",
    "identity_label_case.py start",
    "identity_label_case.py record",
    "identity_label_case.py review",
    "identity_label_case.py replay",
    "identity_label_case.py doctor",
    "identity_label_case.py recover",
    "identity_label_case.py next",
)
for command in runtime_commands:
    if command not in skill:
        fail(f"SKILL.md does not orchestrate runtime command: {command}")
if "portable fallback" not in skill.lower():
    fail("SKILL.md does not distinguish the portable prompt fallback")

openai_yaml = (ROOT / "agents" / "openai.yaml").read_text(encoding="utf-8")
for expected in (
    'display_name: "身份标签拆解"',
    'short_description: "用结构化证据链和可回放实验拆解身份标签判决"',
    "$breaking-identity-labels",
    "运行本地审计器",
):
    if expected not in openai_yaml:
        fail(f"agents/openai.yaml missing interface value: {expected}")

for relative in (
    "schemas/case.schema.json",
    "schemas/analysis.schema.json",
    "schemas/event.schema.json",
    "schemas/event-head.schema.json",
    "schemas/workflow-next.schema.json",
    "schemas/release-gate.schema.json",
    "schemas/audit-receipt.schema.json",
    "schemas/evolution-workflow.schema.json",
    "schemas/evolution-run-state.schema.json",
    "schemas/evolution-command-receipt.schema.json",
    "schemas/evolution-external-receipt.schema.json",
    "schemas/test-migration-receipt.schema.json",
    "templates/analysis.json",
    "examples/real-run/analysis.json",
    "examples/real-run/case.json",
    "examples/real-run/run-manifest.json",
    "evals/heldout-cases.json",
    "evals/boundary-cases.json",
    "evals/v2-results.json",
    "evals/test-generation-manifest.json",
    "evals/schemas/baseline-evidence-manifest.schema.json",
    "evals/schemas/live-e2e-manifest.schema.json",
    "evals/schemas/live-e2e-run.schema.json",
    "evals/baseline-evidence-manifest.json",
    "evals/live-e2e-manifest.json",
):
    read_json(relative)

cases = read_json("evals/cases.json").get("cases", [])
upgrades = read_json("evals/upgrade-cases.json").get("cases", [])
heldout = read_json("evals/heldout-cases.json").get("cases", [])
boundaries = read_json("evals/boundary-cases.json").get("cases", [])
if len(cases) != 4 or len(upgrades) != 2:
    fail("original four cases or two upgrade cases changed count")
if len(heldout) < 30:
    fail(f"held-out route set too small: {len(heldout)}")
if len(boundaries) < 12:
    fail(f"clinical boundary set too small: {len(boundaries)}")
frozen_text = {case["input"] for case in cases + upgrades}
heldout_text = {case["text"] for case in heldout}
if len(heldout_text) != len(heldout) or not heldout_text.isdisjoint(frozen_text):
    fail("held-out cases contain duplicates or frozen-case copies")

results = read_json_path(ARGS.results, str(ARGS.results))
if not results.get("valid"):
    fail("offline evaluation result is not valid")
if results.get("live_model_called") is not False:
    fail("offline evaluation must disclose that no live model was called")
if results.get("schema_version") != "2.1":
    fail("offline evaluation schema version is stale")
expected_eval_bindings = {
    "runtime_sha256": hashlib.sha256(CLI.read_bytes()).hexdigest(),
    "evaluator_sha256": hashlib.sha256((EVALS / "run_v2_evals.py").read_bytes()).hexdigest(),
    "datasets": {
        relative: hashlib.sha256((ROOT / relative).read_bytes()).hexdigest()
        for relative in (
            "evals/heldout-cases.json",
            "evals/boundary-cases.json",
            "evals/cases.json",
            "evals/upgrade-cases.json",
        )
    },
}
if results.get("artifact_bindings") != expected_eval_bindings:
    fail("offline evaluation bindings do not match the current candidate")
heldout_result = results.get("heldout", {})
if heldout_result.get("trigger_macro_f1", 0) < 0.90 or heldout_result.get("mode_accuracy", 0) < 0.90:
    fail("V2 held-out thresholds were not met")
if results.get("regression", {}).get("count") != results.get("regression", {}).get("passed"):
    fail("V2 original-case regression has failures")
if results.get("boundary", {}).get("count") != results.get("boundary", {}).get("passed"):
    fail("V2 clinical boundary regression has failures")
if results.get("boundary", {}).get("count", 0) < 12:
    fail("V2 clinical boundary result count is too small")
if results.get("policy", {}).get("critical_injections") != results.get("policy", {}).get("blocked"):
    fail("V2 critical policy injection was not blocked")
if results.get("policy", {}).get("critical_injections", 0) < 12:
    fail("V2 critical policy injection count is too small")

help_result = subprocess.run(
    [sys.executable, str(CLI), "--help"],
    cwd=ROOT,
    text=True,
    capture_output=True,
    check=False,
)
if help_result.returncode != 0:
    fail(f"runtime CLI --help failed: {help_result.stderr}")

demo_case = ROOT / "examples" / "real-run" / "case.json"
validate_result = subprocess.run(
    [sys.executable, str(CLI), "validate", str(demo_case)],
    cwd=ROOT,
    text=True,
    capture_output=True,
    check=False,
)
if validate_result.returncode != 0 or not json.loads(validate_result.stdout).get("valid"):
    fail(f"generated demo does not validate: {validate_result.stdout} {validate_result.stderr}")

replay_result = subprocess.run(
    [sys.executable, str(CLI), "replay", "--case-dir", str(demo_case.parent)],
    cwd=ROOT,
    text=True,
    capture_output=True,
    check=False,
)
if replay_result.returncode != 0 or not json.loads(replay_result.stdout).get("valid"):
    fail(f"generated demo does not replay: {replay_result.stdout} {replay_result.stderr}")

manifest = read_json("examples/real-run/run-manifest.json")
current_skill_hash = hashlib.sha256((ROOT / "SKILL.md").read_bytes()).hexdigest()
current_runtime_hash = hashlib.sha256(CLI.read_bytes()).hexdigest()
if manifest.get("skill_sha256") != current_skill_hash:
    fail("demo manifest does not match current SKILL.md")
if manifest.get("runtime_sha256") != current_runtime_hash:
    fail("demo manifest does not match current runtime")
if manifest.get("model") is not None or manifest.get("run_type") != "deterministic_runtime_demo":
    fail("demo manifest does not disclose its deterministic non-model scope")
if manifest.get("package_version") != version:
    fail("demo manifest package version is stale")
if manifest.get("final_status") != "reviewed":
    fail("demo does not complete the experiment review lifecycle")
if manifest.get("replay", {}).get("event_count") != 5:
    fail("demo does not preserve the five-event lifecycle")
for name in ("case.json", "events.jsonl", "events.head.json", "report.md"):
    expected_hash = manifest.get("artifacts", {}).get(name)
    actual_hash = hashlib.sha256((demo_case.parent / name).read_bytes()).hexdigest()
    if expected_hash != actual_hash:
        fail(f"demo manifest artifact hash is stale: {name}")

demo_verify_result = subprocess.run(
    [sys.executable, str(DEMO_VERIFIER), "--demo-dir", str(demo_case.parent)],
    cwd=ROOT,
    text=True,
    capture_output=True,
    check=False,
)
if demo_verify_result.returncode != 0:
    fail(f"independent demo verification failed: {demo_verify_result.stdout} {demo_verify_result.stderr}")

baseline_evidence_result = subprocess.run(
    [
        sys.executable,
        str(BASELINE_EVIDENCE_VERIFIER),
        "--root",
        str(ROOT),
        "--manifest",
        str(EVALS / "baseline-evidence-manifest.json"),
    ],
    cwd=ROOT,
    text=True,
    capture_output=True,
    check=False,
)
try:
    baseline_evidence_summary = json.loads(baseline_evidence_result.stdout)
except json.JSONDecodeError as error:
    fail(f"frozen baseline verifier did not return JSON: {error}")
if (
    baseline_evidence_result.returncode != 0
    or baseline_evidence_summary.get("valid") is not True
    or baseline_evidence_summary.get("case_count") != 4
    or baseline_evidence_summary.get("claim_scope") != "byte_integrity_only"
    or baseline_evidence_summary.get("causal_improvement_claim") is not False
    or baseline_evidence_summary.get("model_identifier") != "not_exposed"
    or baseline_evidence_summary.get("reasoning_effort") != "not_exposed"
):
    fail(
        "frozen baseline byte-integrity verification failed: "
        f"{baseline_evidence_result.stdout} {baseline_evidence_result.stderr}"
    )

live_e2e_result = subprocess.run(
    [
        sys.executable,
        str(LIVE_E2E_VERIFIER),
        "--root",
        str(ROOT),
        "--manifest",
        str(EVALS / "live-e2e-manifest.json"),
    ],
    cwd=ROOT,
    text=True,
    capture_output=True,
    check=False,
)
try:
    live_e2e_summary = json.loads(live_e2e_result.stdout)
except json.JSONDecodeError as error:
    fail(f"live model/runtime composition verifier did not return JSON: {error}")
if (
    live_e2e_result.returncode != 0
    or live_e2e_summary.get("valid") is not True
    or live_e2e_summary.get("evidence_level")
    != "historical_analysis_replay_sample"
    or live_e2e_summary.get("case_count") != 4
    or live_e2e_summary.get("replayed_case_count") != 4
    or live_e2e_summary.get("reviewed_case_count") != 4
):
    fail(
        "historical analysis/runtime replay verification failed: "
        f"{live_e2e_result.stdout} {live_e2e_result.stderr}"
    )

fresh_live_e2e_result = subprocess.run(
    [
        sys.executable,
        str(LIVE_E2E_VERIFIER),
        "--root",
        str(ROOT),
        "--manifest",
        str(EVALS / "fresh-candidate-e2e-manifest.json"),
    ],
    cwd=ROOT,
    text=True,
    capture_output=True,
    check=False,
)
try:
    fresh_live_e2e_summary = json.loads(fresh_live_e2e_result.stdout)
except json.JSONDecodeError as error:
    fail(f"fresh candidate model/runtime verifier did not return JSON: {error}")
if (
    fresh_live_e2e_result.returncode != 0
    or fresh_live_e2e_summary.get("valid") is not True
    or fresh_live_e2e_summary.get("evidence_level")
    != "fresh_candidate_model_runtime_sample"
    or fresh_live_e2e_summary.get("case_count") != 4
    or fresh_live_e2e_summary.get("replayed_case_count") != 4
    or fresh_live_e2e_summary.get("reviewed_case_count") != 4
):
    fail(
        "fresh candidate model/runtime composition verification failed: "
        f"{fresh_live_e2e_result.stdout} {fresh_live_e2e_result.stderr}"
    )

workflow = (ROOT / "workflows" / "v2-evolution.yaml").read_text(encoding="utf-8")
for marker in (
    "round_1_runtime",
    "round_2_boundary_attack",
    "round_3_refine_forward_release",
    "freeze_candidate",
    "state_integrity_retest",
    "policy_mutation_retest",
    "release_audit",
    "loop_controller:",
    "no_fixed_iteration_limit",
    "independent_attribution_audit",
    "independent_clinical_safety_audit",
    "independent_state_integrity_audit",
    "release_package_audit",
    "zero_blocker_exit",
    "next_iteration",
    "executable_controller:",
    "scripts/run_evolution.py",
    "test_generation_manifest",
):
    if marker not in workflow:
        fail(f"evolution workflow is missing DAG marker: {marker}")

current_workflow = read_json("workflows/v78-final-release.json")
if current_workflow.get("workflow_id") != "breaking-identity-labels-v78-final-release":
    fail("current executable workflow id is invalid")
expected_steps = {
    "historical_red_evidence_verify",
    "red_evidence_ledger_verify",
    "baseline_evidence_verify",
    "audit_harness_selfcheck",
    "blindspot_discovery",
    "full_regression",
    "offline_eval",
    "offline_eval_verify",
    "demo_build",
    "demo_verify",
    "live_e2e_verify",
    "fresh_candidate_live_e2e_verify",
    "package_build",
    "package_verify_directory",
    "package_verify_archive",
    "package_install",
    "package_verify_installed",
    "package_equivalence",
}
actual_steps = {
    step.get("id")
    for step in current_workflow.get("steps", [])
    if isinstance(step, dict)
}
if actual_steps != expected_steps:
    fail("current executable workflow step inventory is incomplete")

makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
if "forward-loop:" not in makefile or "test_final_forward_regressions.py" not in makefile:
    fail("Makefile does not expose the final forward regression loop")
if "WORKFLOW_PATH ?= workflows/v78-final-release.json" not in makefile:
    fail("Makefile does not default to the current V78 workflow")
for marker in (
    "v7-loop:",
    "v8-loop:",
    "v9-loop:",
    "baseline-evidence-verify:",
    "live-e2e-verify:",
    "historical-live-retest-verify:",
    "evolution-gate:",
    "release-gate:",
    "release-package:",
    "release-package-check:",
):
    if marker not in makefile:
        fail(f"Makefile does not expose release loop marker: {marker}")
verify_line = next(
    (line for line in makefile.splitlines() if line.startswith("verify:")),
    "",
)
if (
    "baseline-evidence-verify" not in verify_line
    or "live-e2e-verify" not in verify_line
    or "historical-live-retest-verify" in verify_line
):
    fail("Makefile verify target does not use the current V78 evidence gates")

provenance = (ROOT / "PROVENANCE.md").read_text(encoding="utf-8")
for value in (
    "dontbesilent2025/dbskill",
    "8282f010964601070334dd7350973386abff6d2b",
    "CC BY-NC 4.0",
    "clean-room",
    "scripts/identity_label_case.py",
):
    if value not in provenance:
        fail(f"PROVENANCE.md missing: {value}")

repo_provenance = (ROOT.parents[1] / "provenance.yml").read_text(encoding="utf-8")
repo_notice = (ROOT.parents[1] / "NOTICE.md").read_text(encoding="utf-8")
for value in ("breaking-identity-labels", "8282f010964601070334dd7350973386abff6d2b"):
    if value not in repo_provenance or value not in repo_notice:
        fail(f"repository-level attribution is missing: {value}")

repo_license = (ROOT.parents[1] / "LICENSE").read_text(encoding="utf-8")
if "Attribution-NonCommercial 4.0 International" not in repo_license:
    fail("repository license is not the audited CC BY-NC 4.0 text")

gate_currency = "not_evaluated"
gate_summary = {"effective_decision": "not_evaluated"}
if ARGS.include_release_state:
    release_state = read_json_path(ARGS.release_state, "release state")
    gate_result = subprocess.run(
        [
            sys.executable,
            str(EVOLUTION_CONTROLLER),
            "check",
            "--state",
            str(ARGS.release_state),
            "--allow-blocked",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    try:
        gate_summary = json.loads(gate_result.stdout)
    except json.JSONDecodeError as error:
        fail(f"executable evolution gate did not return JSON: {error}")
    if release_state.get("distribution_status") != "local_unpublished":
        fail("stored release state changed the unpublished distribution boundary")
    if release_state.get("publication_actions_performed") is not False:
        fail("stored release state claims an external publication action")
    if gate_result.returncode == 0:
        gate_currency = "current"
        if gate_summary.get("distribution_status") != "local_unpublished":
            fail("executable evolution gate changed the unpublished distribution boundary")
        if gate_summary.get("publication_actions_performed") is not False:
            fail("executable evolution gate claims an external publication action")
        if gate_summary.get("release_eligible") and gate_summary.get("blocker_count") != 0:
            fail("executable evolution gate released with blockers")
    else:
        gate_currency = "non_current"
        if (
            gate_summary.get("effective_decision") != "invalid_run"
            or gate_summary.get("release_eligible") is not False
            or not isinstance(gate_summary.get("errors"), list)
            or not gate_summary["errors"]
        ):
            fail(
                "non-current evolution gate did not fail closed: "
                f"{gate_result.stdout} {gate_result.stderr}"
            )

with tempfile.TemporaryDirectory(prefix="breaking-identity-labels-package-check-") as temp:
    temp_root = Path(temp)
    package_dir = temp_root / "breaking-identity-labels"
    archive = temp_root / "breaking-identity-labels.zip"
    skills_dir = temp_root / "skills"
    build_result = subprocess.run(
        [
            sys.executable,
            str(PACKAGE_BUILDER),
            "build",
            "--out",
            str(package_dir),
            "--archive",
            str(archive),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if build_result.returncode != 0:
        fail(f"allowlist package build failed: {build_result.stdout} {build_result.stderr}")
    build_summary = json.loads(build_result.stdout)

    archive_verify = subprocess.run(
        [sys.executable, str(PACKAGE_BUILDER), "verify", "--package", str(archive)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if archive_verify.returncode != 0:
        fail(f"candidate archive verification failed: {archive_verify.stdout} {archive_verify.stderr}")
    archive_summary = json.loads(archive_verify.stdout)

    install_result = subprocess.run(
        [
            sys.executable,
            str(PACKAGE_BUILDER),
            "install",
            "--package",
            str(archive),
            "--skills-dir",
            str(skills_dir),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    if install_result.returncode != 0:
        fail(f"candidate archive install failed: {install_result.stdout} {install_result.stderr}")
    install_summary = json.loads(install_result.stdout)
    if not (
        build_summary.get("tree_sha256")
        == archive_summary.get("tree_sha256")
        == install_summary.get("tree_sha256")
    ):
        fail("source package, archive and installed package tree digests differ")

schema_count = sum(
    1
    for directory in (ROOT / "schemas", EVALS / "schemas")
    for path in directory.glob("*.schema.json")
    if path.is_file()
)
gate_text = (
    "release gate not evaluated (source-only)"
    if gate_currency == "not_evaluated"
    else f"release gate {gate_currency} ({gate_summary.get('effective_decision')})"
)
print(
    f"PASS: V78 candidate {version}, V2 runtime, {schema_count} machine schemas, workflow next, {gate_text}, "
    f"{len(heldout)} held-out cases, "
    f"{len(boundaries)} clinical boundaries, {results.get('regression', {}).get('count')} "
    f"original regressions, {results.get('policy', {}).get('critical_injections')} policy injections, "
    "frozen four-case baseline byte integrity, four-case historical analysis replay, "
    "four-case fresh candidate model/runtime composition, "
    "separate semantic review, reviewed demo, provenance, allowlist archive and non-overwriting install"
)
