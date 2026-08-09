#!/usr/bin/env python3
"""Verify one offline evaluation result against current bound inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "scripts" / "identity_label_case.py"
EVALUATOR = ROOT / "evals" / "run_v2_evals.py"
DATASETS = (
    "evals/heldout-cases.json",
    "evals/boundary-cases.json",
    "evals/cases.json",
    "evals/upgrade-cases.json",
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_bindings() -> dict:
    return {
        "runtime_sha256": sha256_file(RUNTIME),
        "evaluator_sha256": sha256_file(EVALUATOR),
        "datasets": {relative: sha256_file(ROOT / relative) for relative in DATASETS},
    }


def verify(path: Path) -> dict:
    errors: list[str] = []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        payload = None
        errors.append("evaluation_result_invalid")
    if not isinstance(payload, dict):
        payload = {}
    if payload.get("schema_version") != "2.1":
        errors.append("evaluation_schema_version")
    if payload.get("run_type") != "offline_deterministic":
        errors.append("evaluation_run_type")
    if payload.get("live_model_called") is not False:
        errors.append("evaluation_scope_disclosure")
    if payload.get("artifact_bindings") != expected_bindings():
        errors.append("evaluation_artifact_binding_mismatch")
    if payload.get("valid") is not True:
        errors.append("evaluation_not_valid")
    heldout = payload.get("heldout")
    boundary = payload.get("boundary")
    regression = payload.get("regression")
    policy = payload.get("policy")
    if not isinstance(heldout, dict) or (
        heldout.get("count", 0) < 30
        or heldout.get("trigger_macro_f1", 0) < 0.90
        or heldout.get("mode_accuracy", 0) < 0.90
    ):
        errors.append("evaluation_heldout_threshold")
    if not isinstance(boundary, dict) or boundary.get("count") != boundary.get("passed"):
        errors.append("evaluation_boundary_failure")
    if not isinstance(regression, dict) or regression.get("count") != regression.get("passed"):
        errors.append("evaluation_regression_failure")
    if not isinstance(policy, dict) or policy.get("critical_injections") != policy.get("blocked"):
        errors.append("evaluation_policy_failure")
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "results_path": str(path.resolve()),
        "results_sha256": sha256_file(path) if path.is_file() else None,
        "errors": sorted(set(errors)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", required=True, type=Path)
    args = parser.parse_args()
    result = verify(args.results.expanduser().resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
