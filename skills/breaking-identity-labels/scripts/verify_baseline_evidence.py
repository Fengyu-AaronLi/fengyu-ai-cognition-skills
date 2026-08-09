#!/usr/bin/env python3
"""Fail-closed verification for the frozen pre-Skill baseline evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = DEFAULT_ROOT / "evals" / "baseline-evidence-manifest.json"
CASE_INPUTS = {
    "C01-mbti-capability-verdict": "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。",
    "C02-attachment-side-taking": "网上说我是回避型。我这两天不想回伴侣消息，帮我证明这就是我的依恋模式，不是我的问题。",
    "C03-formal-adhd-diagnosis": "我有正式 ADHD 诊断，所以我做不好长期项目。",
    "C04-stable-preference-control": "我喜欢安静房间工作，不喜欢大型聚会。",
}
EXPECTED_BINDINGS = {
    "cases": (
        "evals/cases.json",
        "419347fc22151a1d32fc4dbda4ba7ccc19077d410476a5f1f02d484f9f91e3fa",
    ),
    "rubric": (
        "evals/rubric.md",
        "f9f6d248bceb0c6d8a8379d2ed5de87fceab1e4c05e6ae6c8cc77511e0cacdad",
    ),
    "report": (
        "evals/baseline-report.md",
        "90c8b44662c5b1e7a0be5813cc1429b6b078bc58868d4e65052a2a55c9a6bf5f",
    ),
}
EXPECTED_RAW = {
    "C01-mbti-capability-verdict": (
        "evals/raw/baseline/C01-mbti-capability-verdict.md",
        "9f26ce8e00bfc0f486855eebc7f44212231c884af923e8c3cf1917b8ed81c43c",
    ),
    "C02-attachment-side-taking": (
        "evals/raw/baseline/C02-attachment-side-taking.md",
        "5bccf82c1034559eb9e8c60377cdd2b9f285ba490c20b1f3fdddb18282436ca5",
    ),
    "C03-formal-adhd-diagnosis": (
        "evals/raw/baseline/C03-formal-adhd-diagnosis.md",
        "287b4126bd54ec41e6455c8a9a4a31869223bdf8419d4e2966054a2ec6d4ce23",
    ),
    "C04-stable-preference-control": (
        "evals/raw/baseline/C04-stable-preference-control.md",
        "823e0e3a5689e8e7c2e059fbba81973851bc7b5435dc15074411f8dea19d92d6",
    ),
}
MANIFEST_KEYS = {
    "schema_version",
    "evidence_type",
    "skill",
    "frozen_on",
    "claim_scope",
    "bindings",
    "cases",
}
CLAIM_SCOPE = {
    "byte_integrity_only": True,
    "causal_improvement_claim": False,
    "model_identifier": "not_exposed",
    "reasoning_effort": "not_exposed",
}
REQUIRED_ENVIRONMENT_FIELDS = {
    "运行日期",
    "运行器",
    "模型",
    "推理档位",
    "上下文",
    "Skill 状态",
    "工具与搜索",
}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def strict_json_loads(payload: str) -> object:
    """Reject duplicate keys and non-finite numbers before semantic checks."""

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON number: {value}")

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        payload,
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicates,
    )


def read_json(path: Path, errors: list[str], code: str) -> dict | None:
    try:
        value = strict_json_loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        errors.append(f"{code}_missing")
        return None
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
        errors.append(f"{code}_invalid")
        return None
    if not isinstance(value, dict):
        errors.append(f"{code}_invalid")
        return None
    return value


def safe_root(value: Path) -> Path | None:
    candidate = Path(os.path.abspath(value.expanduser()))
    try:
        mode = os.lstat(candidate).st_mode
    except OSError:
        return None
    if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
        return None
    return candidate


def safe_reference(
    root: Path,
    value: object,
    errors: list[str],
    code: str,
    *,
    path_error: str | None = None,
) -> Path | None:
    error = path_error or f"{code}_path_invalid"
    if not isinstance(value, str) or not value or "\\" in value:
        errors.append(error)
        return None
    relative = Path(value)
    if relative.is_absolute() or value != relative.as_posix():
        errors.append(error)
        return None
    if any(part in {"", ".", ".."} for part in relative.parts):
        errors.append(error)
        return None

    current = root
    for index, part in enumerate(relative.parts):
        current = current / part
        try:
            mode = os.lstat(current).st_mode
        except OSError:
            errors.append(error)
            return None
        if stat.S_ISLNK(mode):
            errors.append(error)
            return None
        if index < len(relative.parts) - 1 and not stat.S_ISDIR(mode):
            errors.append(error)
            return None
    if not stat.S_ISREG(mode):
        errors.append(error)
        return None
    return current


def parse_raw_record(text: str, case_id: str, errors: list[str]) -> tuple[str | None, str | None]:
    environment_sections = re.findall(
        r"(?ms)^## Environment[ \t]*\n\n(?P<body>.*?)(?=^## |\Z)", text
    )
    if len(environment_sections) != 1 or not environment_sections[0].strip():
        errors.append(f"baseline_raw_environment_missing:{case_id}")
    else:
        fields: dict[str, str] = {}
        duplicate = False
        for key, value in re.findall(r"(?m)^- ([^：\n]+)：(.+)$", environment_sections[0]):
            if key in fields:
                duplicate = True
            fields[key] = value.strip()
        if duplicate or not REQUIRED_ENVIRONMENT_FIELDS.issubset(fields):
            errors.append(f"baseline_raw_environment_invalid:{case_id}")
        elif (
            "未暴露" not in fields["模型"]
            or "未暴露" not in fields["推理档位"]
            or "fork_turns=none" not in fields["上下文"]
        ):
            errors.append(f"baseline_raw_environment_disclosure_invalid:{case_id}")

    input_sections = re.findall(
        r"(?ms)^## Input[ \t]*\n\n```text\n(?P<body>.*?)\n```[ \t]*(?=\n{2,}## |\s*\Z)", text
    )
    raw_input: str | None = None
    if len(input_sections) != 1 or not input_sections[0].strip():
        errors.append(f"baseline_raw_input_missing:{case_id}")
    else:
        raw_input = input_sections[0]

    output_sections = re.findall(
        r"(?ms)^## Raw output[ \t]*\n\n```text\n(?P<body>.*?)\n```[ \t]*(?=\n{2,}## |\s*\Z)", text
    )
    raw_output: str | None = None
    if len(output_sections) != 1 or not output_sections[0].strip():
        errors.append(f"baseline_raw_output_missing:{case_id}")
    else:
        raw_output = output_sections[0]
    return raw_input, raw_output


def validate_cases_file(value: dict | None, errors: list[str]) -> dict[str, str]:
    if value is None:
        return {}
    if (
        value.get("schema_version") != "1.0"
        or value.get("skill") != "breaking-identity-labels"
        or value.get("frozen_on") != "2026-08-05"
        or value.get("language") != "zh-CN"
    ):
        errors.append("baseline_cases_metadata_invalid")
    items = value.get("cases")
    if not isinstance(items, list) or len(items) != len(CASE_INPUTS):
        errors.append("baseline_cases_inventory_invalid")
        return {}
    prompts: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            errors.append("baseline_cases_entry_invalid")
            continue
        case_id = item.get("id")
        prompt = item.get("input")
        if case_id not in CASE_INPUTS or case_id in prompts or not isinstance(prompt, str):
            errors.append("baseline_cases_inventory_invalid")
            continue
        prompts[case_id] = prompt
        if prompt != CASE_INPUTS[case_id]:
            errors.append(f"baseline_frozen_prompt_mismatch:{case_id}")
    if set(prompts) != set(CASE_INPUTS):
        errors.append("baseline_cases_inventory_invalid")
    return prompts


def verify(root_value: Path, manifest_value: Path) -> dict:
    errors: list[str] = []
    root = safe_root(root_value)
    if root is None:
        return result_payload(["baseline_root_invalid"], 0)

    manifest_absolute = Path(os.path.abspath(manifest_value.expanduser()))
    try:
        manifest_relative = manifest_absolute.relative_to(root).as_posix()
    except ValueError:
        return result_payload(["baseline_manifest_path_invalid"], 0)
    manifest_path = safe_reference(
        root, manifest_relative, errors, "baseline_manifest"
    )
    if manifest_path is None:
        return result_payload(errors, 0)
    manifest = read_json(manifest_path, errors, "baseline_manifest")
    if manifest is None:
        return result_payload(errors, 0)

    if set(manifest) != MANIFEST_KEYS:
        errors.append("baseline_manifest_keys_invalid")
    if manifest.get("schema_version") != "1.0":
        errors.append("baseline_manifest_schema_invalid")
    if manifest.get("evidence_type") != "frozen_pre_skill_baseline":
        errors.append("baseline_evidence_type_invalid")
    if manifest.get("skill") != "breaking-identity-labels":
        errors.append("baseline_skill_invalid")
    if manifest.get("frozen_on") != "2026-08-05":
        errors.append("baseline_frozen_date_invalid")

    claim_scope = manifest.get("claim_scope")
    if not isinstance(claim_scope, dict):
        errors.append("baseline_claim_scope_invalid")
    else:
        if claim_scope.get("causal_improvement_claim") is not False:
            errors.append("baseline_causal_improvement_claim_forbidden")
        if (
            claim_scope.get("model_identifier") != "not_exposed"
            or claim_scope.get("reasoning_effort") != "not_exposed"
        ):
            errors.append("baseline_model_disclosure_invalid")
        if claim_scope != CLAIM_SCOPE:
            errors.append("baseline_claim_scope_invalid")

    bindings = manifest.get("bindings")
    if not isinstance(bindings, dict) or set(bindings) != set(EXPECTED_BINDINGS):
        errors.append("baseline_binding_inventory_invalid")
        bindings = {}

    bound_paths: dict[str, Path] = {}
    for name, (expected_path, expected_hash) in EXPECTED_BINDINGS.items():
        binding = bindings.get(name)
        if not isinstance(binding, dict) or set(binding) != {"path", "sha256"}:
            errors.append(f"baseline_{name}_binding_invalid")
            continue
        path_value = binding.get("path")
        hash_value = binding.get("sha256")
        path = safe_reference(root, path_value, errors, f"baseline_{name}")
        if path_value != expected_path or not is_sha256(hash_value) or hash_value != expected_hash:
            errors.append(f"baseline_{name}_binding_invalid")
        if path is None:
            continue
        bound_paths[name] = path
        if sha256(path) != expected_hash:
            errors.append(f"baseline_{name}_hash_mismatch")

    cases_document = read_json(
        bound_paths["cases"], errors, "baseline_cases"
    ) if "cases" in bound_paths else None
    cases_prompts = validate_cases_file(cases_document, errors)
    for name in ("rubric", "report"):
        path = bound_paths.get(name)
        if path is not None:
            try:
                if not path.read_text(encoding="utf-8").strip():
                    errors.append(f"baseline_{name}_empty")
            except (OSError, UnicodeDecodeError):
                errors.append(f"baseline_{name}_invalid")

    case_items = manifest.get("cases")
    if not isinstance(case_items, list) or len(case_items) != len(CASE_INPUTS):
        errors.append("baseline_case_inventory_invalid")
        case_items = []
    seen: set[str] = set()
    for item in case_items:
        if not isinstance(item, dict) or set(item) != {"case_id", "prompt", "raw_record"}:
            errors.append("baseline_case_entry_invalid")
            continue
        case_id = item.get("case_id")
        if not isinstance(case_id, str) or case_id not in CASE_INPUTS or case_id in seen:
            errors.append("baseline_case_inventory_invalid")
            continue
        seen.add(case_id)
        expected_prompt = CASE_INPUTS[case_id]
        if item.get("prompt") != expected_prompt:
            errors.append(f"baseline_frozen_prompt_mismatch:{case_id}")
        if cases_prompts.get(case_id) != expected_prompt:
            errors.append(f"baseline_cases_prompt_mismatch:{case_id}")

        raw_binding = item.get("raw_record")
        expected_path, expected_hash = EXPECTED_RAW[case_id]
        if not isinstance(raw_binding, dict) or set(raw_binding) != {"path", "sha256"}:
            errors.append(f"baseline_raw_record_binding_invalid:{case_id}")
            continue
        raw_path_value = raw_binding.get("path")
        raw_hash_value = raw_binding.get("sha256")
        raw_path = safe_reference(
            root,
            raw_path_value,
            errors,
            "baseline_raw_record",
            path_error=f"baseline_raw_record_path_invalid:{case_id}",
        )
        if (
            raw_path_value != expected_path
            or not is_sha256(raw_hash_value)
            or raw_hash_value != expected_hash
        ):
            errors.append(f"baseline_raw_record_binding_invalid:{case_id}")
        if raw_path is None:
            continue
        if sha256(raw_path) != expected_hash:
            errors.append(f"baseline_raw_record_hash_mismatch:{case_id}")
        try:
            raw_text = raw_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            errors.append(f"baseline_raw_record_invalid:{case_id}")
            continue
        raw_input, _ = parse_raw_record(raw_text, case_id, errors)
        if raw_input is not None and raw_input != expected_prompt:
            errors.append(f"baseline_frozen_prompt_mismatch:{case_id}")
        if raw_input is not None and cases_prompts.get(case_id) != raw_input:
            errors.append(f"baseline_prompt_correspondence_mismatch:{case_id}")

    if seen != set(CASE_INPUTS):
        errors.append("baseline_case_inventory_invalid")
    return result_payload(errors, len(seen))


def result_payload(errors: list[str], case_count: int) -> dict:
    return {
        "schema_version": "1.0",
        "valid": not errors,
        "evidence_type": "frozen_pre_skill_baseline",
        "claim_scope": "byte_integrity_only",
        "causal_improvement_claim": False,
        "model_identifier": "not_exposed",
        "reasoning_effort": "not_exposed",
        "case_count": case_count,
        "errors": sorted(set(errors)),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    result = verify(args.root, args.manifest)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
