#!/usr/bin/env python3
"""Verify one deterministic demo against the current Skill and runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
SKILL = ROOT / "SKILL.md"
VERSION = ROOT / "VERSION"
SOURCE_DIR = ROOT / "examples" / "real-run"
ARTIFACTS = (
    ".case.lock",
    "case.json",
    "events.jsonl",
    "events.head.json",
    "report.md",
)
CONTROLLED_ENV = {"PYTHONHASHSEED": "0"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(path: Path, errors: list[str], code: str) -> dict | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"{code}_missing")
        return None
    except (OSError, json.JSONDecodeError):
        errors.append(f"{code}_invalid")
        return None
    if not isinstance(value, dict):
        errors.append(f"{code}_invalid")
        return None
    return value


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        env=CONTROLLED_ENV,
        text=True,
        capture_output=True,
        check=False,
    )


def verify(demo_dir: Path) -> dict:
    errors: list[str] = []
    try:
        demo_dir = demo_dir.expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return {"schema_version": "1.0", "valid": False, "errors": ["demo_dir_invalid"]}
    if not demo_dir.is_dir() or demo_dir.is_symlink():
        return {"schema_version": "1.0", "valid": False, "errors": ["demo_dir_invalid"]}

    manifest = read_json(demo_dir / "run-manifest.json", errors, "demo_manifest")
    if manifest is None:
        return {"schema_version": "1.0", "valid": False, "errors": sorted(set(errors))}

    if manifest.get("schema_version") != "2.0":
        errors.append("demo_manifest_schema_version")
    if manifest.get("run_type") != "deterministic_runtime_demo" or manifest.get("model") is not None:
        errors.append("demo_scope_disclosure_invalid")
    if manifest.get("package_version") != VERSION.read_text(encoding="utf-8").strip():
        errors.append("demo_package_version_mismatch")
    if manifest.get("skill_sha256") != sha256(SKILL):
        errors.append("demo_skill_hash_mismatch")
    if manifest.get("runtime_sha256") != sha256(CLI):
        errors.append("demo_runtime_hash_mismatch")
    if manifest.get("input_sha256") != sha256(SOURCE_DIR / "demo-input.txt"):
        errors.append("demo_input_hash_mismatch")
    if manifest.get("analysis_sha256") != sha256(SOURCE_DIR / "analysis.json"):
        errors.append("demo_analysis_hash_mismatch")

    artifact_hashes = manifest.get("artifacts")
    if not isinstance(artifact_hashes, dict) or set(artifact_hashes) != set(ARTIFACTS):
        errors.append("demo_artifact_manifest_invalid")
        artifact_hashes = {}
    for name in ARTIFACTS:
        path = demo_dir / name
        if not path.is_file() or path.is_symlink():
            errors.append(f"demo_artifact_missing:{name}")
        elif artifact_hashes.get(name) != sha256(path):
            errors.append(f"demo_artifact_hash_mismatch:{name}")

    validation: dict = {"valid": False}
    replay: dict = {"valid": False}
    case_path = demo_dir / "case.json"
    if case_path.is_file() and not case_path.is_symlink():
        validate_result = run_cli("validate", str(case_path))
        try:
            validation = json.loads(validate_result.stdout)
        except json.JSONDecodeError:
            errors.append("demo_runtime_validation_output_invalid")
        if validate_result.returncode != 0 or validation.get("valid") is not True:
            errors.append("demo_runtime_validation_failed")

        replay_result = run_cli("replay", "--case-dir", str(demo_dir))
        try:
            replay = json.loads(replay_result.stdout)
        except json.JSONDecodeError:
            errors.append("demo_runtime_replay_output_invalid")
        if replay_result.returncode != 0 or replay.get("valid") is not True:
            errors.append("demo_runtime_replay_failed")

    if manifest.get("validation") != validation:
        errors.append("demo_validation_receipt_mismatch")
    if manifest.get("replay") != replay:
        errors.append("demo_replay_receipt_mismatch")
    if manifest.get("final_status") != replay.get("latest_status") or replay.get("event_count") != 5:
        errors.append("demo_lifecycle_mismatch")

    return {
        "schema_version": "1.0",
        "valid": not errors,
        "demo_dir": str(demo_dir),
        "validation": validation,
        "replay": replay,
        "errors": sorted(set(errors)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-dir", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.demo_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
