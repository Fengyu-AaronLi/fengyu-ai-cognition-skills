#!/usr/bin/env python3
"""Stateful orchestration and bounded repair loop for the casefile runtime."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import casefile


WORKFLOW_VERSION = "3.1.0"
DEFAULT_MAX_ATTEMPTS = 2
STATE_FILE = "state.json"
INPUT_FILE = "input.txt"
CASEFILE_FILE = "casefile.json"
RESPONSE_FILE = "response.md"
SAFETY_RESPONSE_FILE = "safety-response.md"
PASSTHROUGH_VALIDATION_FILE = "passthrough-validation.json"
LOCK_FILE = ".workflow.lock"

SAFETY_RESPONSE_ORDER = (
    "medical_emergency",
    "self_harm_risk",
    "third_party_self_harm_risk",
    "harm_to_others_risk",
    "explicit_threat",
    "prior_violence_or_damage",
    "access_or_location_exposure",
    "other_immediate_risk",
    "urgent_legal_risk",
)
SAFETY_RESPONSE_CATALOG = {
    "medical_emergency": "现在请立即联系当地急救或前往急诊。",
    "self_harm_risk": "现在请立即联系当地急救、危机热线或可信任的人，并避免独处。",
    "third_party_self_harm_risk": "现在请立即联系当事人所在地的紧急服务或能到场的可信任人员，帮助确认当事人安全。",
    "harm_to_others_risk": "现在请立即联系当地警方或紧急服务，并与可能受伤害的人保持距离。",
    "explicit_threat": "现在请立即前往有人值守的安全地点，并联系当地警方或紧急服务。",
    "prior_violence_or_damage": "现在请立即前往有人值守的安全地点，并联系当地警方或紧急服务。",
    "access_or_location_exposure": "现在请立即前往有人值守的安全地点，并联系当地警方或紧急服务。",
    "other_immediate_risk": "现在请立即联系当地紧急服务或可信任的人，并前往有人值守的安全地点。",
    "urgent_legal_risk": "现在请尽快联系当地合格律师或法律援助，确认法定期限。",
}

PHASE_NEXT_ACTION = {
    "awaiting_authoring": "fill_casefile",
    "repair_required": "repair_casefile",
    "ready_to_finalize": "finalize",
    "passthrough_required": "complete_original_task",
    "safety_action_required": "respond_with_real_world_safety_action",
    "completed": "none",
    "blocked": "start_new_workspace_after_review",
}

ALLOWED_EVENT_TRANSITIONS = {
    "start": {(None, "awaiting_authoring"), (None, "passthrough_required"), (None, "safety_action_required")},
    "start-update": {(None, "awaiting_authoring"), (None, "safety_action_required")},
    "check": {
        ("awaiting_authoring", "repair_required"),
        ("awaiting_authoring", "ready_to_finalize"),
        ("repair_required", "repair_required"),
        ("repair_required", "ready_to_finalize"),
        ("awaiting_authoring", "blocked"),
        ("repair_required", "blocked"),
    },
    "finalize": {("ready_to_finalize", "completed")},
    "complete-passthrough": {("passthrough_required", "completed")},
    "acknowledge-safety": {("safety_action_required", "awaiting_authoring")},
}


class WorkflowError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    return casefile.sha256_bytes(path.read_bytes())


def state_path(workspace: Path) -> Path:
    return workspace / STATE_FILE


def resolve_internal_path(workspace: Path, value: Any) -> Path | None:
    if not isinstance(value, str) or not value or Path(value).is_absolute():
        return None
    candidate = (workspace / value).resolve()
    try:
        candidate.relative_to(workspace.resolve())
    except ValueError:
        return None
    return candidate


def internal_path_text(workspace: Path, value: Any) -> str | None:
    path = resolve_internal_path(workspace, value)
    return str(path) if path is not None else None


def event(
    state: dict[str, Any], action: str, old_phase: str | None, new_phase: str
) -> None:
    events = state.setdefault("events", [])
    previous_hash = events[-1]["event_sha256"] if events else None
    item = {
        "sequence": len(events) + 1,
        "at": now(),
        "action": action,
        "from": old_phase,
        "to": new_phase,
        "attempt_count": state.get("attempt_count", 0),
        "previous_event_sha256": previous_hash,
    }
    if old_phase is None and action in {"start", "start-update"}:
        item["max_attempts"] = state.get("max_attempts")
        item["configuration"] = {
            "case_id": state.get("case_id"),
            "mode": state.get("mode"),
            "max_attempts": state.get("max_attempts"),
            "input_path": state.get("input_path"),
            "input_sha256": state.get("input_sha256"),
            "casefile_path": state.get("casefile_path"),
            "passthrough_kind": state.get("passthrough_kind"),
            "manual_safety_signal_types": state.get(
                "manual_safety_signal_types", []
            ),
            "history": state.get("history", []),
        }
    if action == "check":
        receipt_paths = state.get("receipt_paths", [])
        receipt_hashes = state.get("receipt_sha256s", [])
        item["receipt_path"] = receipt_paths[-1] if receipt_paths else None
        item["receipt_sha256"] = receipt_hashes[-1] if receipt_hashes else None
    if action == "complete-passthrough":
        item["passthrough_validation_path"] = state.get(
            "passthrough_validation_path"
        )
        item["passthrough_validation_sha256"] = state.get(
            "passthrough_validation_sha256"
        )
    if action in {"finalize", "complete-passthrough"}:
        item["response_path"] = state.get("response_path")
        item["response_sha256"] = state.get("response_sha256")
    if action == "acknowledge-safety":
        item["safety_response_path"] = state.get("safety_response_path")
        item["safety_response_sha256"] = state.get("safety_response_sha256")
    item["event_sha256"] = casefile.canonical_sha256(item)
    events.append(item)


def event_chain_errors(state: dict[str, Any]) -> list[dict[str, str]]:
    events = state.get("events")
    if not isinstance(events, list) or not events:
        return [
            casefile.error(
                "STATE_EVENT_CHAIN_INVALID", "/events", "event chain is missing"
            )
        ]
    errors: list[dict[str, str]] = []
    previous_hash: str | None = None
    for index, item in enumerate(events):
        path = f"/events/{index}"
        if not isinstance(item, dict):
            errors.append(
                casefile.error("STATE_EVENT_CHAIN_INVALID", path, "event must be an object")
            )
            continue
        declared_hash = item.get("event_sha256")
        unsigned = {key: value for key, value in item.items() if key != "event_sha256"}
        if (
            item.get("sequence") != index + 1
            or item.get("previous_event_sha256") != previous_hash
            or declared_hash != casefile.canonical_sha256(unsigned)
            or (item.get("from"), item.get("to"))
            not in ALLOWED_EVENT_TRANSITIONS.get(str(item.get("action")), set())
        ):
            errors.append(
                casefile.error(
                    "STATE_EVENT_CHAIN_INVALID",
                    path,
                    "event order, hash, or transition is invalid",
                )
            )
        previous_hash = declared_hash if isinstance(declared_hash, str) else None
    if isinstance(events[-1], dict) and events[-1].get("to") != state.get("phase"):
        errors.append(
            casefile.error(
                "STATE_EVENT_CHAIN_INVALID",
                "/phase",
                "state phase must equal the final event",
            )
        )
    check_count = sum(
        1
        for item in events
        if isinstance(item, dict) and item.get("action") == "check"
    )
    receipt_paths = state.get("receipt_paths", [])
    receipt_hashes = state.get("receipt_sha256s", [])
    if (
        check_count != state.get("attempt_count")
        or not isinstance(receipt_paths, list)
        or not isinstance(receipt_hashes, list)
        or check_count != len(receipt_paths)
        or check_count != len(receipt_hashes)
    ):
        errors.append(
            casefile.error(
                "STATE_EVENT_CHAIN_INVALID",
                "/attempt_count",
                "attempt count and receipt count must equal check events",
            )
        )
    check_events = [
        item
        for item in events
        if isinstance(item, dict) and item.get("action") == "check"
    ]
    if isinstance(receipt_paths, list) and isinstance(receipt_hashes, list):
        for index, check_event in enumerate(check_events):
            if (
                index >= len(receipt_paths)
                or index >= len(receipt_hashes)
                or check_event.get("receipt_path") != receipt_paths[index]
                or check_event.get("receipt_sha256") != receipt_hashes[index]
            ):
                errors.append(
                    casefile.error(
                        "STATE_EVENT_CHAIN_INVALID",
                        f"/events/{index}",
                        "check event must bind its receipt path and hash",
                    )
                )
    if state.get("phase") in {"ready_to_finalize", "completed"} and state.get(
        "mode"
    ) != "passthrough":
        last_validation = state.get("last_validation")
        if (
            not isinstance(last_validation, dict)
            or last_validation.get("valid") is not True
            or not isinstance(state.get("validated_artifact_sha256"), str)
        ):
            errors.append(
                casefile.error(
                    "STATE_EVENT_CHAIN_INVALID",
                    "/last_validation",
                    "finalizable states require a passing bound validation",
                )
            )
    passthrough_events = [
        item
        for item in events
        if isinstance(item, dict) and item.get("action") == "complete-passthrough"
    ]
    if passthrough_events:
        final_passthrough = passthrough_events[-1]
        if (
            final_passthrough.get("passthrough_validation_path")
            != state.get("passthrough_validation_path")
            or final_passthrough.get("passthrough_validation_sha256")
            != state.get("passthrough_validation_sha256")
        ):
            errors.append(
                casefile.error(
                    "STATE_EVENT_CHAIN_INVALID",
                    "/passthrough_validation_path",
                    "passthrough completion event must bind its task validation receipt",
                )
            )
    completion_events = [
        item
        for item in events
        if isinstance(item, dict)
        and item.get("action") in {"finalize", "complete-passthrough"}
    ]
    if state.get("phase") == "completed":
        final_completion = completion_events[-1] if completion_events else None
        if (
            not isinstance(final_completion, dict)
            or final_completion.get("response_path") != state.get("response_path")
            or final_completion.get("response_sha256")
            != state.get("response_sha256")
        ):
            errors.append(
                casefile.error(
                    "STATE_EVENT_CHAIN_INVALID",
                    "/response_path",
                    "completion event must bind the final response path and hash",
                )
            )
    safety_events = [
        item
        for item in events
        if isinstance(item, dict) and item.get("action") == "acknowledge-safety"
    ]
    if safety_events:
        final_safety = safety_events[-1]
        if (
            final_safety.get("safety_response_path")
            != state.get("safety_response_path")
            or final_safety.get("safety_response_sha256")
            != state.get("safety_response_sha256")
        ):
            errors.append(
                casefile.error(
                    "STATE_EVENT_CHAIN_INVALID",
                    "/safety_response_path",
                    "safety acknowledgement event must bind the visible response path and hash",
                )
            )
    return errors


def save_state(workspace: Path, state: dict[str, Any]) -> None:
    state["updated_at"] = now()
    casefile.atomic_write_json(state_path(workspace), state)


def load_state(workspace: Path) -> dict[str, Any]:
    path = state_path(workspace)
    if not path.is_file() or path.is_symlink():
        raise WorkflowError("STATE_MISSING", f"missing {path}")
    try:
        state = casefile.read_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        raise WorkflowError("STATE_INVALID", str(exc)) from exc
    if not isinstance(state, dict):
        raise WorkflowError("STATE_INVALID", "state must be a JSON object")
    return state


@contextmanager
def workspace_lock(workspace: Path, *, shared: bool = False):
    """Serialize state transitions and give status a consistent snapshot."""
    if not workspace.is_dir() or workspace.is_symlink():
        raise WorkflowError("WORKSPACE_INVALID", str(workspace))
    lock_path = workspace / LOCK_FILE
    with lock_path.open("a+", encoding="utf-8") as handle:
        lock_path.chmod(0o600)
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH if shared else fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def public_state(workspace: Path, state: dict[str, Any]) -> dict[str, Any]:
    result = {
        "skill": state.get("skill"),
        "workflow_version": state.get("workflow_version"),
        "case_id": state.get("case_id"),
        "mode": state.get("mode"),
        "phase": state.get("phase"),
        "next_action": PHASE_NEXT_ACTION.get(state.get("phase"), "inspect_state"),
        "attempt_count": state.get("attempt_count"),
        "max_attempts": state.get("max_attempts"),
        "workspace": str(workspace.resolve()),
        "input_path": internal_path_text(workspace, state.get("input_path")),
        "casefile_path": internal_path_text(workspace, state.get("casefile_path")),
        "receipt_paths": list(state.get("receipt_paths", [])),
        "response_path": (
            internal_path_text(workspace, state.get("response_path"))
        ),
        "safety_response_path": (
            internal_path_text(workspace, state.get("safety_response_path"))
        ),
        "passthrough_kind": state.get("passthrough_kind"),
        "manual_safety_signal_types": list(
            state.get("manual_safety_signal_types", [])
        ),
        "passthrough_validation_path": internal_path_text(
            workspace, state.get("passthrough_validation_path")
        ),
    }
    if isinstance(state.get("last_validation"), dict):
        result.update(
            {
                "valid": state["last_validation"].get("valid"),
                "error_count": state["last_validation"].get("error_count"),
                "errors": state["last_validation"].get("errors", []),
            }
        )
    return result


def base_state(
    case_id: str,
    mode: str,
    phase: str,
    input_text: str,
    *,
    casefile_path: str | None,
    max_attempts: int,
    history: list[dict[str, str]] | None = None,
    start_action: str = "start",
    passthrough_kind: str | None = None,
    manual_safety_signal_types: list[str] | None = None,
) -> dict[str, Any]:
    created = now()
    state: dict[str, Any] = {
        "skill": casefile.SKILL_NAME,
        "workflow_version": WORKFLOW_VERSION,
        "skill_version": casefile.SKILL_VERSION,
        "schema_version": casefile.SCHEMA_VERSION,
        "validator_version": casefile.VALIDATOR_VERSION,
        "case_id": case_id,
        "mode": mode,
        "phase": phase,
        "attempt_count": 0,
        "max_attempts": max_attempts,
        "input_path": INPUT_FILE,
        "input_sha256": casefile.sha256_text(input_text),
        "casefile_path": casefile_path,
        "passthrough_kind": passthrough_kind,
        "manual_safety_signal_types": sorted(
            set(manual_safety_signal_types or [])
        ),
        "history": history or [],
        "receipt_paths": [],
        "receipt_sha256s": [],
        "validated_artifact_sha256": None,
        "response_path": None,
        "response_sha256": None,
        "safety_response_path": None,
        "safety_response_sha256": None,
        "passthrough_validation_path": None,
        "passthrough_validation_sha256": None,
        "last_validation": None,
        "created_at": created,
        "updated_at": created,
        "events": [],
    }
    event(state, start_action, None, phase)
    return state


def prepare_workspace(workspace: Path) -> None:
    if workspace.exists():
        raise WorkflowError("WORKSPACE_EXISTS", str(workspace.resolve()))
    workspace.mkdir(parents=True, mode=0o700)
    workspace.chmod(0o700)


def initialize_workspace_transaction(
    workspace: Path,
    initializer: Callable[[Path], dict[str, Any]],
) -> dict[str, Any]:
    """Build a complete initial workspace before publishing its final path.

    Failed staging directories are intentionally retained as forensic evidence.
    The final path remains absent, so an identical request can be retried.
    """
    if workspace.exists():
        raise WorkflowError("WORKSPACE_EXISTS", str(workspace.resolve()))
    workspace.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{workspace.name}.init-",
            dir=str(workspace.parent),
        )
    )
    staging.chmod(0o700)
    try:
        state = initializer(staging)
        errors = integrity_errors(staging, state)
        if errors:
            raise WorkflowError(
                "WORKSPACE_INIT_INTEGRITY_FAILED",
                json.dumps(errors, ensure_ascii=False, sort_keys=True),
            )
        if workspace.exists():
            raise WorkflowError("WORKSPACE_EXISTS", str(workspace.resolve()))
        os.rename(staging, workspace)
    except Exception as exc:
        detail = exc.message if isinstance(exc, WorkflowError) else str(exc)
        raise WorkflowError(
            "WORKSPACE_INIT_INCOMPLETE",
            f"initialization failed; staging preserved at {staging}: {detail}",
        ) from exc
    return state


def _passthrough_instruction_segment(text: str) -> str:
    stripped = text.strip()
    positions = [
        position
        for marker in ("：", ":", "“", '"')
        for position in [stripped.find(marker)]
        if position >= 0
    ]
    return stripped[: min(positions)] if positions else stripped


def _first_transform_payload(text: str) -> tuple[str, str]:
    """Return structurally owned transform operands and the unowned suffix."""
    return casefile.transform_payload_and_tail(text)


NEGATED_ANALYSIS_DIRECTIVE_PATTERN = re.compile(
    r"(?:不要|无需|不必|禁止|请勿|别|不做|不再|不|未|无需再)\s*"
    r"(?:再|做|进行)?\s*(?:帮我)?\s*"
    r"(?:分析|判断|解释|诊断|建议|评价|评估|解读|推测|推断|推理|说明|"
    r"总结|归纳|提炼|找出|识别|指出|比较|给出|形成|下|制定|提出|推荐)"
    r"(?:(?!(?:但|可是|然而|不过|却|而是|并且|而且|同时|另外|"
    r"另问|补问|再问|告诉我|请(?:告诉|判断|分析|解释|解读|推断)))."
    r"){0,40}"
)


def _mask_negated_analysis_directives(text: str) -> str:
    """Remove bounded prohibitions before positive mixed-intent matching.

    The source text is not changed.  Masking is local to routing and ends at a
    clause boundary, so a later affirmative task such as ``但请判断态度`` is
    still visible to the ordinary mixed-intent veto.
    """
    return NEGATED_ANALYSIS_DIRECTIVE_PATTERN.sub(" ", text)


def _quotes_are_sourced_timeline_cells(
    text: str, quote_ranges: list[tuple[int, int]]
) -> bool:
    """Return whether every quote is an owned field in a sourced record.

    Stable ``[T1]`` row keys are one valid layout, but ordinary source exports
    also use ``来源 / 日期 / 原文`` fields.  A quote is owned only when it is a
    keyed row cell or is introduced as an original-text field inside a nearby
    source-labelled record.  Merely placing an unrelated quote somewhere in a
    request does not grant passthrough ownership.
    """
    if not quote_ranges:
        return False
    row_ranges: list[tuple[int, int]] = []
    offset = 0
    for line in text.splitlines(keepends=True):
        content_end = offset + len(line.rstrip("\r\n"))
        if re.match(r"\s*\[(?:T|E|S)\d+\]\s*", line, re.IGNORECASE):
            row_ranges.append((offset, content_end))
        offset += len(line)
    for quote_start, quote_end in quote_ranges:
        if any(
            row_start <= quote_start and quote_end <= row_end
            for row_start, row_end in row_ranges
        ):
            continue
        line_start = text.rfind("\n", 0, quote_start) + 1
        same_line_prefix = text[line_start:quote_start]
        nearby_context = text[max(0, quote_start - 320) : quote_start]
        original_field = re.search(
            r"(?:原文|原话|引文|内容|记录)\s*[：:]\s*[“‘\"「『']?\s*$",
            same_line_prefix,
        )
        source_field = re.search(
            r"(?:已明确标注来源|来源\s*[：:]|source\s*[:])",
            nearby_context,
            re.IGNORECASE,
        )
        if original_field is None or source_field is None:
            return False
    return True


SOURCED_TIMELINE_OPERATION_PATTERN = re.compile(
    r"(?:整理(?:成|为)?|排成|转换成|转成|编排成|汇总成)\s*(?:一份)?\s*时间线|"
    r"(?:输出|生成|制作)\s*(?:一份)?\s*(?:有来源|带来源|已标来源)?\s*时间线|"
    r"(?:按|依照)\s*时间线\s*(?:整理|排序|排列)|"
    r"(?:给我|提供)(?:一份)?\s*时间线",
    re.IGNORECASE,
)
NEGATED_TIMELINE_OPERATION_PATTERN = re.compile(
    r"(?:不要|别|禁止|请勿|无需|不必|不是要|并非要)"
    r"[^，,。！？；;\n]{0,48}"
    r"(?:整理|排成|转换成|转成|编排成|汇总成|输出|生成|制作)"
    r"[^，,。！？；;\n]{0,12}时间线|"
    r"(?:不要|别|禁止|请勿|无需|不必|不是要|并非要)"
    r"[^，,。！？；;\n]{0,24}(?:按|依照)\s*时间线\s*(?:整理|排序|排列)",
    re.IGNORECASE,
)


def _sourced_timeline_routing_text(text: str) -> str:
    """Keep request syntax visible while masking source-owned quotations."""
    characters = list(text)
    for start, end in casefile._actual_quote_ranges(text):
        characters[start:end] = " " * (end - start)
    return "".join(characters)


def passthrough_has_mixed_intent(text: str) -> bool:
    if casefile.parse_pure_transform_task(text) is not None:
        return False
    # Typed safety routing is a global passthrough veto after casefile scope
    # filtering.  This keeps quoted benign operands eligible while preventing
    # any positively detected real-world risk from taking the bypass path.
    if casefile.expected_safety_signal_types(text):
        return True
    if casefile.disowned_transform_payload_ranges(text):
        return True
    candidate_kind = passthrough_candidate_kind(text)
    instruction_source = (
        _sourced_timeline_routing_text(text)
        if candidate_kind == "sourced_timeline"
        else _passthrough_instruction_segment(text)
    )
    instruction = _mask_negated_analysis_directives(instruction_source)
    mixed_pattern = (
            r"并(?:且)?(?:告诉|分析|判断|解释|诊断|建议|评价|评估|解读|推测|推断|推理|说明)|"
            r"同时(?:告诉|分析|判断|解释|诊断|建议|评价|评估|解读|推测|推断|推理|说明)|"
            r"(?:给出|形成|下)(?:一个|明确|最终)?(?:结论|判断)|"
            r"(?:总结|归纳|提炼)(?:其中|双方|这些|事件中|时间线中)?(?:的)?(?:规律|模式|趋势|含义|结论)|"
            r"(?:找出|识别|指出)(?:双方|其中|这些|说法中|时间线中)?(?:说法|陈述|记录)?(?:的)?(?:矛盾|冲突|疑点|漏洞|不一致)|"
            r"(?:比较|评估|判断)(?:双方|各方|这些)?(?:说法|来源|证据)?(?:谁|哪一方|哪个)?(?:更)?(?:可信|可靠|真实)|"
            r"(?:据此|基于(?:这|此|上述|时间线))?(?:给我|为我)?(?:一个|具体)?(?:行动方案|处理方案|下一步建议)|"
            r"(?:制定|提出|推荐)(?:一个|具体)?(?:行动方案|处理方案|下一步)|"
            r"(?:顺便|另外|再|还)\s*[，,]?\s*(?:请)?(?:帮我)?(?:说说|讲讲|告诉|分析|判断|解释|诊断|建议|评价|评估|解读|推测|推断|推理|说明)|"
            r"(?:之后|然后|随后|接着)\s*[，,]?\s*(?:请)?(?:帮我)?(?:回答|告诉|分析|判断|解释|诊断|建议|评价|评估|解读|推测|推断|推理|说明)|"
            r"时间线\s*(?:和|以及|并(?:且)?)\s*(?:行动建议|行动方案|处理方案|下一步建议|结论|判断)|"
            r"(?:另问|补问|再问|另外问|还有一个问题)\s*[：:]?|"
            r"(?:翻译|转换|整理|排版)(?:完成|完|之后|以后|后).{0,8}"
            r"(?:告诉|分析|判断|解释|诊断|建议|评价|评估|解读|推测|推断|推理|说明)|"
            r"(?:告诉我|分析|判断|解释|诊断|评价|评估|解读|推测|推断|推理|说明).{0,18}(?:是不是|是否|代表|意味着|证明|动机|心理|人格|NPD|"
            r"回避型|爱不爱|厌恶|讨厌|会不会|该不该|应该)|"
            r"(?:看懂|判断|分析|解读|琢磨|推断|猜测|解释).{0,20}"
            r"(?:态度|心里(?:怎么|怎样)?想|内心|想法|真实动机|心理|爱不爱|"
            r"在不在乎|关系(?:状态|走向|变化))|"
            r"背后的心理|"
            r"(?:是不是|是否)(?:NPD|回避型|人格障碍)|"
            r"为何|为什么|真实动机|替我决定|给我建议|"
            r"\b(?:and|also|then)\s+(?:tell|explain|analy[sz]e|judge|diagnose|advise|say|infer|evaluate|assess|interpret)\b|"
            r"\b(?:tell|explain|infer|evaluate|assess|interpret)\s+(?:me\s+)?(?:why|what(?:\s+it)?\s+means?|what to do)|"
            r"\b(?:why did|why does|what should i do|real motive|true motive|"
            r"avoidant|narcissist|personality disorder)\b"
    )
    if candidate_kind == "sourced_timeline":
        timeline_analysis_pattern = re.compile(
            r"(?:^|[。！？；;\n，,])\s*(?:请|请你|帮我|麻烦你)?\s*"
            r"(?:分析|解释|判断|评估|评价|解读|推测|推断|回答)\s*"
            r"(?:这|该|以下|上述|这些|双方|各方|来源|材料|记录|事件|内容)?|"
            r"(?:按|依照)\s*时间线\s*(?:分析|解释|判断|评估|评价|解读|推断)|"
            r"(?:时间线|来源|材料|记录).{0,12}(?:和|以及|并(?:且)?)"
            r".{0,8}(?:行动建议|行动方案|处理方案|下一步建议)",
            re.IGNORECASE,
        )
        if timeline_analysis_pattern.search(instruction):
            return True
    if re.search(mixed_pattern, instruction, re.IGNORECASE):
        return True
    # A transform can own several quotes only when the finite parser sees them
    # as directly coordinated operands.  Every other quote and any typed risk
    # after the owned payload stays outside passthrough scope.
    quote_ranges = casefile._actual_quote_ranges(text)
    if quote_ranges:
        payload_ranges = casefile.transform_payload_ranges(text)
        sourced_timeline_cells = bool(
            candidate_kind in {"formatting", "sourced_timeline"}
            and _quotes_are_sourced_timeline_cells(text, quote_ranges)
        )
        if (
            not payload_ranges
            and not sourced_timeline_cells
        ) or (
            payload_ranges
            and any(item not in payload_ranges for item in quote_ranges)
            and not sourced_timeline_cells
        ):
            return True
        _, tail = _first_transform_payload(text)
        return bool(
            re.search(
                mixed_pattern,
                _mask_negated_analysis_directives(tail),
                re.IGNORECASE,
            )
            or casefile.expected_safety_signal_types(tail)
        )
    # Without quotes the transform operand has no reliable end boundary.
    # Treat an explicit second-task connector as mixed instead of silently
    # routing the whole request through passthrough.
    _, tail = _first_transform_payload(text)
    return bool(
        re.search(
            mixed_pattern,
            _mask_negated_analysis_directives(tail),
            re.IGNORECASE,
        )
        or casefile.expected_safety_signal_types(text)
    )


def passthrough_candidate_kind(text: str) -> str | None:
    stripped = text.strip()
    sourced_timeline = bool(
        SOURCED_TIMELINE_OPERATION_PATTERN.search(stripped)
        and not NEGATED_TIMELINE_OPERATION_PATTERN.search(stripped)
        and re.search(
            r"(?:已明确标注来源|以下来源|根据来源|有来源|带来源|已标来源|"
            r"来源\s*[：:]|\[(?:T|E|S)\d+|(?:邮件|短信|消息|记录)\s*[：:])",
            stripped,
            re.IGNORECASE,
        )
    )
    if sourced_timeline:
        return "sourced_timeline"
    parsed_transform = casefile.parse_pure_transform_task(stripped)
    if parsed_transform is not None:
        return parsed_transform["kind"]
    translation = bool(
        casefile.is_pure_translation_task(stripped)
        or re.search(r"^\s*(?:translate|translation\s*:)", stripped, re.IGNORECASE)
        or re.search(r"^\s*翻译(?:成|为)?(?:英文|英语|中文)?\s*[:：]", stripped)
        or re.search(r"(?:请|帮我|把|将).{0,18}翻译(?:成|为|一下)?", stripped)
        or re.search(r"(?:请|帮我|把|将).{0,18}译为(?:英文|英语|中文)", stripped)
    )
    formatting = bool(
        re.search(
            r"(?:请|帮我|把|将).{0,24}(?:改成|转换成|整理成|排成).{0,14}(?:格式|表格|JSON|Markdown|时间线)",
            stripped,
            re.IGNORECASE,
        )
    )
    if translation:
        return "translation"
    if formatting:
        return "formatting"
    return None


def classify_passthrough_request(text: str) -> str | None:
    candidate = passthrough_candidate_kind(text)
    if candidate is None or passthrough_has_mixed_intent(text):
        return None
    return candidate


def is_passthrough_request(text: str) -> bool:
    return classify_passthrough_request(text) is not None


def history_data_and_errors(
    state: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any] | None,
    list[dict[str, str]],
]:
    history_data: list[dict[str, Any]] = []
    bound_legacy_receipt: dict[str, Any] | None = None
    errors: list[dict[str, str]] = []
    previous: dict[str, Any] | None = None
    for index, item in enumerate(state.get("history", [])):
        path_value = item.get("path") if isinstance(item, dict) else None
        path = Path(path_value) if isinstance(path_value, str) else None
        if path is None or not path.is_file() or path.is_symlink():
            errors.append(
                casefile.error(
                    "HISTORY_MISSING", f"/history/{index}", "history artifact is missing"
                )
            )
            continue
        try:
            data = casefile.read_json(path)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(
                casefile.error("HISTORY_INVALID", f"/history/{index}", str(exc))
            )
            continue
        receipt: dict[str, Any] | None = None
        receipt_path_value = item.get("legacy_receipt_path")
        receipt_hash = item.get("legacy_receipt_sha256")
        if isinstance(receipt_path_value, str):
            receipt_path = Path(receipt_path_value)
            if not receipt_path.is_file() or receipt_path.is_symlink():
                errors.append(
                    casefile.error(
                        "LEGACY_RECEIPT_MISSING",
                        f"/history/{index}/legacy_receipt_path",
                        "bound legacy receipt is missing",
                    )
                )
            elif receipt_hash != sha256_file(receipt_path):
                errors.append(
                    casefile.error(
                        "LEGACY_RECEIPT_HASH_MISMATCH",
                        f"/history/{index}/legacy_receipt_sha256",
                        "bound legacy receipt bytes changed after workflow start",
                    )
                )
            else:
                try:
                    receipt = casefile.read_json(receipt_path)
                    bound_legacy_receipt = receipt
                except (OSError, json.JSONDecodeError) as exc:
                    errors.append(
                        casefile.error(
                            "LEGACY_RECEIPT_INVALID",
                            f"/history/{index}/legacy_receipt_path",
                            str(exc),
                        )
                    )
        if (
            item.get("artifact_sha256") != sha256_file(path)
            or item.get("casefile_sha256") != casefile.canonical_sha256(data)
        ):
            errors.append(
                casefile.error(
                    "HISTORY_HASH_MISMATCH",
                    f"/history/{index}",
                    "history bytes changed after workflow start",
                )
            )
        needs_receipt = (
            casefile._casefile_version_pair(data)
            in casefile.MIGRATABLE_VERSION_PAIRS
            or casefile._casefile_version_pair(previous)
            in casefile.MIGRATABLE_VERSION_PAIRS
        )
        validation_errors = casefile.validate_casefile(
            data,
            previous=previous,
            legacy_receipt=receipt if needs_receipt else None,
        )
        if validation_errors:
            errors.append(
                casefile.error(
                    "HISTORY_INVALID",
                    f"/history/{index}",
                    f"prior revision failed with {validation_errors[0]['code']}",
                )
            )
        previous = data
        history_data.append(data)
    return history_data, bound_legacy_receipt, errors


def manual_safety_binding_errors(
    state: dict[str, Any], data: dict[str, Any]
) -> list[dict[str, str]]:
    bound_types = set(state.get("manual_safety_signal_types", []))
    current_input_id = data.get("current_input_id")
    signals = (
        data.get("safety", {}).get("risk_signals", [])
        if isinstance(data.get("safety"), dict)
        else []
    )
    current_signals = [
        item
        for item in signals
        if isinstance(item, dict) and item.get("input_id") == current_input_id
    ]
    present_types = {
        item.get("signal_type")
        for item in current_signals
        if item.get("signal_type") in casefile.SIGNAL_TYPES
    }
    current_human_types = {
        item.get("signal_type")
        for item in current_signals
        if item.get("routing_basis") == "human_semantic_review"
    }
    missing = sorted(bound_types - current_human_types)
    unbound_human = sorted(current_human_types - bound_types)
    if not missing and not unbound_human:
        return []
    return [
        casefile.error(
            "MANUAL_SAFETY_SIGNAL_MISSING",
            "/safety/risk_signals",
            f"manual safety binding mismatch; missing={missing}, unbound_human={unbound_human}",
        )
    ]


def integrity_errors(workspace: Path, state: dict[str, Any]) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = event_chain_errors(state)
    casefile_data: dict[str, Any] | None = None
    expected_identity = {
        "skill": casefile.SKILL_NAME,
        "workflow_version": WORKFLOW_VERSION,
        "skill_version": casefile.SKILL_VERSION,
        "schema_version": casefile.SCHEMA_VERSION,
        "validator_version": casefile.VALIDATOR_VERSION,
    }
    for key, expected in expected_identity.items():
        if state.get(key) != expected:
            errors.append(
                casefile.error(
                    "STATE_VERSION_MISMATCH", f"/{key}", f"expected {expected}"
                )
            )

    events = state.get("events", [])
    first_event = events[0] if isinstance(events, list) and events else None
    current_configuration = {
        "case_id": state.get("case_id"),
        "mode": state.get("mode"),
        "max_attempts": state.get("max_attempts"),
        "input_path": state.get("input_path"),
        "input_sha256": state.get("input_sha256"),
        "casefile_path": state.get("casefile_path"),
        "passthrough_kind": state.get("passthrough_kind"),
        "manual_safety_signal_types": state.get(
            "manual_safety_signal_types", []
        ),
        "history": state.get("history", []),
    }
    if (
        not isinstance(first_event, dict)
        or first_event.get("max_attempts") != state.get("max_attempts")
        or first_event.get("configuration") != current_configuration
        or state.get("max_attempts") not in {1, 2}
    ):
        errors.append(
            casefile.error(
                "STATE_CONFIG_MUTATED",
                "/max_attempts",
                "workflow configuration must remain bound to the start event",
            )
        )
    manual_safety_signal_types = state.get("manual_safety_signal_types")
    if (
        not isinstance(manual_safety_signal_types, list)
        or len(manual_safety_signal_types) != len(set(manual_safety_signal_types))
        or any(
            item not in casefile.SIGNAL_TYPES
            for item in manual_safety_signal_types
        )
        or (manual_safety_signal_types and state.get("mode") != "safety")
    ):
        errors.append(
            casefile.error(
                "STATE_CONFIG_MUTATED",
                "/manual_safety_signal_types",
                "manual safety types must be a unique supported list on a safety workflow",
            )
        )

    receipt_paths = state.get("receipt_paths")
    receipt_hashes = state.get("receipt_sha256s")
    if isinstance(receipt_paths, list) and isinstance(receipt_hashes, list):
        for index, relative in enumerate(receipt_paths):
            receipt = resolve_internal_path(workspace, relative)
            if receipt is None:
                errors.append(
                    casefile.error(
                        "STATE_PATH_OUTSIDE_WORKSPACE",
                        f"/receipt_paths/{index}",
                        "receipt paths must stay inside the workspace",
                    )
                )
                continue
            if not receipt.is_file() or receipt.is_symlink():
                errors.append(
                    casefile.error(
                        "RECEIPT_MISSING",
                        f"/receipt_paths/{index}",
                        "declared validation receipt is missing",
                    )
                )
                continue
            expected_receipt_hash = (
                receipt_hashes[index] if index < len(receipt_hashes) else None
            )
            if sha256_file(receipt) != expected_receipt_hash:
                errors.append(
                    casefile.error(
                        "RECEIPT_HASH_MISMATCH",
                        f"/receipt_paths/{index}",
                        "validation receipt changed after it was recorded",
                    )
                )
        if receipt_paths:
            latest = resolve_internal_path(workspace, receipt_paths[-1])
            if latest is not None and latest.is_file() and not latest.is_symlink():
                try:
                    latest_data = casefile.read_json(latest)
                except (OSError, json.JSONDecodeError):
                    latest_data = None
                if latest_data != state.get("last_validation"):
                    errors.append(
                        casefile.error(
                            "RECEIPT_HASH_MISMATCH",
                            "/last_validation",
                            "last_validation must equal the latest bound receipt",
                        )
                    )
        receipts_dir = workspace / "receipts"
        actual_receipts = {
            str(path.relative_to(workspace))
            for path in receipts_dir.glob("attempt-*.json")
            if path.is_file() or path.is_symlink()
        } if receipts_dir.is_dir() else set()
        undeclared_receipts = sorted(actual_receipts - set(receipt_paths))
        for relative in undeclared_receipts:
            errors.append(
                casefile.error(
                    "RECOVERY_REQUIRED",
                    f"/{relative}",
                    "a receipt exists without its corresponding durable state transition",
                )
            )

    input_path = resolve_internal_path(workspace, state.get("input_path"))
    if input_path is None:
        errors.append(
            casefile.error(
                "STATE_PATH_OUTSIDE_WORKSPACE",
                "/input_path",
                "state-managed paths must stay inside the workspace",
            )
        )
        input_text = None
    elif not input_path.is_file() or input_path.is_symlink():
        errors.append(casefile.error("INPUT_MISSING", "/input_path", "input is missing"))
        input_text = None
    else:
        input_text = input_path.read_text(encoding="utf-8")
        if casefile.sha256_text(input_text) != state.get("input_sha256"):
            errors.append(
                casefile.error(
                    "INPUT_HASH_MISMATCH", "/input_sha256", "input bytes changed"
                )
            )

    history, _, history_errors = history_data_and_errors(state)
    errors.extend(history_errors)
    casefile_value = state.get("casefile_path")
    if isinstance(casefile_value, str):
        artifact = resolve_internal_path(workspace, casefile_value)
        if artifact is None:
            errors.append(
                casefile.error(
                    "STATE_PATH_OUTSIDE_WORKSPACE",
                    "/casefile_path",
                    "state-managed paths must stay inside the workspace",
                )
            )
        elif not artifact.is_file() or artifact.is_symlink():
            errors.append(
                casefile.error("CASEFILE_MISSING", "/casefile_path", "casefile is missing")
            )
        else:
            try:
                data = casefile.read_json(artifact)
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(
                    casefile.error("CASEFILE_READ_ERROR", "/casefile_path", str(exc))
                )
            else:
                casefile_data = data
                if data.get("mode") != state.get("mode"):
                    errors.append(
                        casefile.error(
                            "CASEFILE_MODE_MISMATCH",
                            "/mode",
                            "casefile mode must equal the mode bound by the start event",
                        )
                    )
                if data.get("case_id") != state.get("case_id"):
                    errors.append(
                        casefile.error(
                            "CASE_ID_MISMATCH", "/case_id", "casefile identity changed"
                        )
                    )
                current_id = data.get("current_input_id")
                current_input = next(
                    (
                        item
                        for item in data.get("inputs", [])
                        if isinstance(item, dict) and item.get("id") == current_id
                    ),
                    None,
                )
                if (
                    input_text is not None
                    and (
                        not isinstance(current_input, dict)
                        or current_input.get("text") != input_text
                        or current_input.get("sha256") != state.get("input_sha256")
                        or data.get("input_sha256") != state.get("input_sha256")
                    )
                ):
                    errors.append(
                        casefile.error(
                            "CASEFILE_INPUT_MISMATCH",
                            "/inputs",
                            "current casefile input must equal the saved workflow input",
                        )
                    )
                if history and data.get("revision") != len(history) + 1:
                    errors.append(
                        casefile.error(
                            "HISTORY_LENGTH_MISMATCH",
                            "/revision",
                            "history must contain every prior revision",
                        )
                    )
                validated = state.get("validated_artifact_sha256")
                if isinstance(validated, str) and sha256_file(artifact) != validated:
                    errors.append(
                        casefile.error(
                            "VALIDATED_ARTIFACT_CHANGED",
                            "/validated_artifact_sha256",
                            "casefile bytes changed after the passing check",
                        )
                    )
                if (
                    state.get("phase") in {"ready_to_finalize", "completed"}
                    and isinstance(manual_safety_signal_types, list)
                ):
                    errors.extend(
                        manual_safety_binding_errors(state, data)
                    )

    response_value = state.get("response_path")
    response_hash = state.get("response_sha256")
    default_response = workspace / RESPONSE_FILE
    if not isinstance(response_value, str) and (
        default_response.is_file() or default_response.is_symlink()
    ):
        errors.append(
            casefile.error(
                "RECOVERY_REQUIRED",
                f"/{RESPONSE_FILE}",
                "a response exists without its corresponding durable state transition",
            )
        )
    if state.get("phase") == "completed" and (
        not isinstance(response_value, str) or not isinstance(response_hash, str)
    ):
        errors.append(
            casefile.error(
                "RESPONSE_BINDING_MISSING",
                "/response_path",
                "completed state requires a hash-bound response",
            )
        )
    if isinstance(response_value, str) and isinstance(response_hash, str):
        response = resolve_internal_path(workspace, response_value)
        if response is None:
            errors.append(
                casefile.error(
                    "STATE_PATH_OUTSIDE_WORKSPACE",
                    "/response_path",
                    "state-managed paths must stay inside the workspace",
                )
            )
        elif (
            not response.is_file()
            or response.is_symlink()
            or sha256_file(response) != response_hash
        ):
            errors.append(
                casefile.error(
                    "RESPONSE_HASH_MISMATCH",
                    "/response_path",
                    "completed response changed",
                )
            )
        elif (
            state.get("phase") == "completed"
            and state.get("mode") != "passthrough"
            and isinstance(casefile_data, dict)
            and response.read_text(encoding="utf-8")
            != casefile.render_markdown(casefile_data)
        ):
            errors.append(
                casefile.error(
                    "RESPONSE_RENDER_MISMATCH",
                    "/response_path",
                    "completed standard response must equal the deterministic renderer",
                )
            )
    passthrough_validation_value = state.get("passthrough_validation_path")
    passthrough_validation_hash = state.get("passthrough_validation_sha256")
    default_passthrough_validation = workspace / PASSTHROUGH_VALIDATION_FILE
    if not isinstance(passthrough_validation_value, str) and (
        default_passthrough_validation.is_file()
        or default_passthrough_validation.is_symlink()
    ):
        errors.append(
            casefile.error(
                "RECOVERY_REQUIRED",
                f"/{PASSTHROUGH_VALIDATION_FILE}",
                "a passthrough validation receipt exists without a durable transition",
            )
        )
    if state.get("phase") == "completed" and state.get("mode") == "passthrough":
        if (
            not isinstance(passthrough_validation_value, str)
            or not isinstance(passthrough_validation_hash, str)
        ):
            errors.append(
                casefile.error(
                    "PASSTHROUGH_VALIDATION_MISSING",
                    "/passthrough_validation_path",
                    "completed passthrough requires a hash-bound task validation receipt",
                )
            )
    if isinstance(passthrough_validation_value, str) and isinstance(
        passthrough_validation_hash, str
    ):
        validation_path = resolve_internal_path(
            workspace, passthrough_validation_value
        )
        if validation_path is None:
            errors.append(
                casefile.error(
                    "STATE_PATH_OUTSIDE_WORKSPACE",
                    "/passthrough_validation_path",
                    "state-managed paths must stay inside the workspace",
                )
            )
        elif (
            not validation_path.is_file()
            or validation_path.is_symlink()
            or sha256_file(validation_path) != passthrough_validation_hash
        ):
            errors.append(
                casefile.error(
                    "PASSTHROUGH_VALIDATION_HASH_MISMATCH",
                    "/passthrough_validation_path",
                    "passthrough task validation receipt changed",
                )
            )
        else:
            try:
                validation_data = casefile.read_json(validation_path)
            except (OSError, json.JSONDecodeError):
                validation_data = None
            if (
                not isinstance(validation_data, dict)
                or validation_data.get("valid") is not True
                or validation_data.get("kind") != state.get("passthrough_kind")
                or validation_data.get("input_sha256") != state.get("input_sha256")
                or validation_data.get("response_sha256") != state.get("response_sha256")
            ):
                errors.append(
                    casefile.error(
                        "PASSTHROUGH_VALIDATION_INVALID",
                        "/passthrough_validation_path",
                        "passthrough receipt does not bind the current task and response",
                    )
                )
    safety_response_value = state.get("safety_response_path")
    safety_response_hash = state.get("safety_response_sha256")
    default_safety_response = workspace / SAFETY_RESPONSE_FILE
    if not isinstance(safety_response_value, str) and (
        default_safety_response.is_file() or default_safety_response.is_symlink()
    ):
        errors.append(
            casefile.error(
                "RECOVERY_REQUIRED",
                f"/{SAFETY_RESPONSE_FILE}",
                "a safety response exists without its corresponding durable state transition",
            )
        )
    safety_acknowledged = any(
        isinstance(item, dict) and item.get("action") == "acknowledge-safety"
        for item in state.get("events", [])
    )
    if safety_acknowledged and (
        not isinstance(safety_response_value, str)
        or not isinstance(safety_response_hash, str)
    ):
        errors.append(
            casefile.error(
                "SAFETY_RESPONSE_BINDING_MISSING",
                "/safety_response_path",
                "acknowledged safety response must remain hash-bound",
            )
        )
    if isinstance(safety_response_value, str) and isinstance(
        safety_response_hash, str
    ):
        response = resolve_internal_path(workspace, safety_response_value)
        if response is None:
            errors.append(
                casefile.error(
                    "STATE_PATH_OUTSIDE_WORKSPACE",
                    "/safety_response_path",
                    "state-managed paths must stay inside the workspace",
                )
            )
        elif (
            not response.is_file()
            or response.is_symlink()
            or sha256_file(response) != safety_response_hash
        ):
            errors.append(
                casefile.error(
                    "SAFETY_RESPONSE_HASH_MISMATCH",
                    "/safety_response_path",
                    "the recorded visible safety response changed",
                )
            )
    return errors


def workflow_validation_receipt(
    artifact: Path, data: Any, errors: list[dict[str, str]]
) -> dict[str, Any]:
    artifact_available = artifact.is_file() and not artifact.is_symlink()
    return {
        "valid": not errors,
        "error_count": len(errors),
        "validated_at": now(),
        "artifact_path": str(artifact.resolve()),
        "artifact_sha256": sha256_file(artifact) if artifact_available else None,
        "casefile_sha256": (
            casefile.canonical_sha256(data) if isinstance(data, dict) else None
        ),
        "schema_version": casefile.SCHEMA_VERSION,
        "validator_version": casefile.VALIDATOR_VERSION,
        "errors": errors,
    }


def require_phase(state: dict[str, Any], allowed: set[str], code: str) -> None:
    if state.get("phase") not in allowed:
        raise WorkflowError(code, f"current phase is {state.get('phase')}")


def without_expected_recovery(
    errors: list[dict[str, str]], relative: str
) -> list[dict[str, str]]:
    pointer = f"/{relative}"
    return [
        item
        for item in errors
        if not (item.get("code") == "RECOVERY_REQUIRED" and item.get("path") == pointer)
    ]


def receipt_without_timestamp(receipt: object) -> object:
    if not isinstance(receipt, dict):
        return receipt
    return {key: value for key, value in receipt.items() if key != "validated_at"}


def command_start(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.is_file() or input_path.is_symlink():
        raise WorkflowError("INPUT_INVALID", str(input_path))
    text = input_path.read_text(encoding="utf-8")
    detected_signal_types = casefile.expected_safety_signal_types(text)
    immediate_risk = bool(detected_signal_types)
    manual_safety_signal_types = sorted(set(args.safety_signal_type or []))
    redundant_signal_types = sorted(
        set(manual_safety_signal_types) & set(detected_signal_types)
    )
    if redundant_signal_types:
        raise WorkflowError(
            "MANUAL_SAFETY_TYPE_REDUNDANT",
            "manual signal types duplicate deterministic detections: "
            + ", ".join(redundant_signal_types),
        )
    if manual_safety_signal_types and args.mode != "safety":
        raise WorkflowError(
            "MANUAL_SAFETY_TYPE_NOT_ALLOWED",
            "--safety-signal-type requires explicit --mode safety",
        )
    if args.mode == "safety" and not immediate_risk and not manual_safety_signal_types:
        raise WorkflowError(
            "MANUAL_SAFETY_TYPE_REQUIRED",
            "detector-unmatched safety routing must bind an explicit signal type",
        )
    passthrough_kind = classify_passthrough_request(text)
    passthrough_eligible = passthrough_kind is not None
    if args.mode == "passthrough":
        if immediate_risk:
            raise WorkflowError(
                "SAFETY_MODE_REQUIRED",
                "immediate risk cannot be bypassed with passthrough mode",
            )
        if not passthrough_eligible:
            if (
                passthrough_candidate_kind(text) is not None
                and passthrough_has_mixed_intent(text)
            ):
                raise WorkflowError(
                    "PASSTHROUGH_MIXED_INTENT",
                    "a transform request with an analysis or decision task must enter standard mode",
                )
            raise WorkflowError(
                "PASSTHROUGH_NOT_ELIGIBLE",
                "passthrough requires an explicit translation, formatting, or sourced-timeline task",
            )
        resolved_mode = "passthrough"
    elif args.mode == "auto":
        if immediate_risk:
            resolved_mode = "safety"
        elif passthrough_eligible:
            resolved_mode = "passthrough"
        else:
            resolved_mode = "standard"
    elif args.mode == "standard" and passthrough_eligible and not immediate_risk:
        raise WorkflowError(
            "PASSTHROUGH_MODE_REQUIRED",
            "a clear translation, formatting, or sourced-timeline task must not enter analysis",
        )
    else:
        resolved_mode = args.mode

    def initialize(staging: Path) -> dict[str, Any]:
        casefile.atomic_write(staging / INPUT_FILE, text)
        if resolved_mode == "passthrough":
            mode = "passthrough"
            phase = "passthrough_required"
            artifact_relative = None
        else:
            draft = casefile.make_draft(text, args.case_id, resolved_mode)
            mode = draft["mode"]
            phase = (
                "safety_action_required"
                if mode == "safety"
                else "awaiting_authoring"
            )
            artifact_relative = CASEFILE_FILE
            casefile.atomic_write_json(staging / CASEFILE_FILE, draft)
        state = base_state(
            args.case_id,
            mode,
            phase,
            text,
            casefile_path=artifact_relative,
            max_attempts=args.max_attempts,
            passthrough_kind=(
                passthrough_kind if mode == "passthrough" else None
            ),
            manual_safety_signal_types=(
                manual_safety_signal_types if mode == "safety" else []
            ),
        )
        save_state(staging, state)
        return state

    state = initialize_workspace_transaction(workspace, initialize)
    print(json.dumps(public_state(workspace, state), ensure_ascii=False, indent=2))
    return 0


def command_start_update(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    input_path = Path(args.input).expanduser().resolve()
    history_paths = [Path(item).expanduser().resolve() for item in args.history]
    if not input_path.is_file() or input_path.is_symlink():
        raise WorkflowError("INPUT_INVALID", str(input_path))
    if not history_paths:
        raise WorkflowError("FULL_HISTORY_REQUIRED", "history cannot be empty")
    legacy_receipt_path = (
        Path(args.legacy_receipt).expanduser().resolve()
        if getattr(args, "legacy_receipt", None)
        else None
    )
    legacy_receipt: dict[str, Any] | None = None
    legacy_receipt_hash: str | None = None
    if legacy_receipt_path is not None:
        if not legacy_receipt_path.is_file() or legacy_receipt_path.is_symlink():
            raise WorkflowError("LEGACY_RECEIPT_INVALID", str(legacy_receipt_path))
        legacy_receipt = casefile.read_json(legacy_receipt_path)
        legacy_receipt_hash = sha256_file(legacy_receipt_path)

    history_state: list[dict[str, str]] = []
    previous: dict[str, Any] | None = None
    for index, path in enumerate(history_paths):
        if not path.is_file() or path.is_symlink():
            raise WorkflowError("HISTORY_MISSING", str(path))
        data = casefile.read_json(path)
        needs_receipt = (
            casefile._casefile_version_pair(data)
            in casefile.MIGRATABLE_VERSION_PAIRS
            or casefile._casefile_version_pair(previous)
            in casefile.MIGRATABLE_VERSION_PAIRS
        )
        errors = casefile.validate_casefile(
            data,
            previous=previous,
            legacy_receipt=legacy_receipt if needs_receipt else None,
        )
        if errors:
            raise WorkflowError(
                "HISTORY_INVALID", f"revision {index + 1}: {errors[0]['code']}"
            )
        history_entry = {
            "path": str(path),
            "artifact_sha256": sha256_file(path),
            "casefile_sha256": casefile.canonical_sha256(data),
        }
        if needs_receipt and legacy_receipt_path is not None:
            history_entry["legacy_receipt_path"] = str(legacy_receipt_path)
            history_entry["legacy_receipt_sha256"] = str(legacy_receipt_hash)
        history_state.append(history_entry)
        previous = data
    assert previous is not None
    if previous.get("revision") != len(history_paths):
        raise WorkflowError(
            "FULL_HISTORY_REQUIRED", "history must start at revision 1 and contain no gaps"
        )

    text = input_path.read_text(encoding="utf-8")
    detected_signal_types = casefile.expected_safety_signal_types(text)
    manual_safety_signal_types = sorted(set(args.safety_signal_type or []))
    redundant_signal_types = sorted(
        set(manual_safety_signal_types) & set(detected_signal_types)
    )
    if redundant_signal_types:
        raise WorkflowError(
            "MANUAL_SAFETY_TYPE_REDUNDANT",
            "manual signal types duplicate deterministic detections: "
            + ", ".join(redundant_signal_types),
        )
    if manual_safety_signal_types and args.mode != "safety":
        raise WorkflowError(
            "MANUAL_SAFETY_TYPE_NOT_ALLOWED",
            "--safety-signal-type requires explicit --mode safety",
        )
    if (
        args.mode == "safety"
        and not detected_signal_types
        and not manual_safety_signal_types
    ):
        raise WorkflowError(
            "MANUAL_SAFETY_TYPE_REQUIRED",
            "detector-unmatched safety routing must bind an explicit signal type",
        )
    def initialize(staging: Path) -> dict[str, Any]:
        casefile.atomic_write(staging / INPUT_FILE, text)
        draft = casefile.start_update(
            previous,
            text,
            mode=args.mode,
            legacy_receipt=(
                legacy_receipt
                if casefile._casefile_version_pair(previous)
                in casefile.MIGRATABLE_VERSION_PAIRS
                else None
            ),
        )
        casefile.atomic_write_json(staging / CASEFILE_FILE, draft)
        phase = (
            "safety_action_required"
            if draft.get("mode") == "safety"
            else "awaiting_authoring"
        )
        state = base_state(
            str(previous.get("case_id")),
            str(draft.get("mode")),
            phase,
            text,
            casefile_path=CASEFILE_FILE,
            max_attempts=args.max_attempts,
            history=history_state,
            start_action="start-update",
            manual_safety_signal_types=(
                manual_safety_signal_types
                if draft.get("mode") == "safety"
                else []
            ),
        )
        save_state(staging, state)
        return state

    state = initialize_workspace_transaction(workspace, initialize)
    print(json.dumps(public_state(workspace, state), ensure_ascii=False, indent=2))
    return 0


def command_check(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    state = load_state(workspace)
    if state.get("phase") == "safety_action_required":
        raise WorkflowError(
            "SAFETY_RESPONSE_REQUIRED", "record the visible safety response first"
        )
    require_phase(
        state,
        {"awaiting_authoring", "repair_required"},
        "PHASE_NOT_CHECKABLE",
    )
    artifact = resolve_internal_path(workspace, state.get("casefile_path"))
    if artifact is None:
        artifact = workspace / CASEFILE_FILE
    integrity = integrity_errors(workspace, state)
    next_attempt = int(state.get("attempt_count", 0)) + 1
    receipt_relative = f"receipts/attempt-{next_attempt}.json"
    receipt_path = workspace / receipt_relative
    recovering_receipt = receipt_path.exists()
    if recovering_receipt:
        integrity = without_expected_recovery(integrity, receipt_relative)
    try:
        data = casefile.read_json(artifact)
    except (OSError, json.JSONDecodeError) as exc:
        data = None
        validation_errors = [
            casefile.error("JSON_READ_ERROR", "", str(exc)), *integrity
        ]
    else:
        history, legacy_receipt, history_errors = history_data_and_errors(state)
        previous = history[-1] if history else None
        transition_receipt = (
            legacy_receipt
            if casefile._casefile_version_pair(previous)
            in casefile.MIGRATABLE_VERSION_PAIRS
            else None
        )
        validation_errors = [
            *integrity,
            *history_errors,
            *casefile.validate_casefile(
                data,
                previous=previous,
                legacy_receipt=transition_receipt,
            ),
            *manual_safety_binding_errors(state, data),
        ]
    deduplicated: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in validation_errors:
        key = (item.get("code", ""), item.get("path", ""), item.get("message", ""))
        if key not in seen:
            seen.add(key)
            deduplicated.append(item)
    validation_errors = deduplicated

    state["attempt_count"] = next_attempt
    receipt = workflow_validation_receipt(artifact, data, validation_errors)
    if recovering_receipt:
        if receipt_path.is_symlink() or not receipt_path.is_file():
            raise WorkflowError("RECOVERY_CONFLICT", str(receipt_path))
        try:
            recovered_receipt = casefile.read_json(receipt_path)
        except (OSError, json.JSONDecodeError) as exc:
            raise WorkflowError("RECOVERY_CONFLICT", str(exc)) from exc
        if (
            not isinstance(recovered_receipt, dict)
            or not isinstance(recovered_receipt.get("validated_at"), str)
            or receipt_without_timestamp(recovered_receipt)
            != receipt_without_timestamp(receipt)
        ):
            raise WorkflowError(
                "RECOVERY_CONFLICT",
                "orphan receipt does not match the deterministic validation result",
            )
        receipt = recovered_receipt
    else:
        casefile.atomic_write_json(receipt_path, receipt)
    state.setdefault("receipt_paths", []).append(receipt_relative)
    state.setdefault("receipt_sha256s", []).append(sha256_file(receipt_path))
    state["last_validation"] = receipt
    old_phase = str(state.get("phase"))
    if not validation_errors:
        state["phase"] = "ready_to_finalize"
        state["validated_artifact_sha256"] = sha256_file(artifact)
    elif state["attempt_count"] >= int(state.get("max_attempts", 0)):
        state["phase"] = "blocked"
    else:
        state["phase"] = "repair_required"
    event(state, "check", old_phase, state["phase"])
    save_state(workspace, state)
    print(json.dumps(public_state(workspace, state), ensure_ascii=False, indent=2))
    return 0 if not validation_errors else 1


def command_finalize(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    state = load_state(workspace)
    require_phase(state, {"ready_to_finalize"}, "PHASE_NOT_FINALIZABLE")
    output = (
        Path(args.output).expanduser().resolve()
        if args.output
        else workspace / RESPONSE_FILE
    )
    try:
        output.relative_to(workspace)
    except ValueError as exc:
        raise WorkflowError(
            "OUTPUT_OUTSIDE_WORKSPACE", "final output must stay inside the workflow workspace"
        ) from exc
    errors = integrity_errors(workspace, state)
    if output.exists():
        errors = without_expected_recovery(
            errors, str(output.relative_to(workspace))
        )
    if errors:
        first = errors[0]
        raise WorkflowError(first["code"], first["message"])
    artifact = workspace / str(state["casefile_path"])
    data = casefile.read_json(artifact)
    history, legacy_receipt, history_errors = history_data_and_errors(state)
    previous = history[-1] if history else None
    transition_receipt = (
        legacy_receipt
        if casefile._casefile_version_pair(previous)
        in casefile.MIGRATABLE_VERSION_PAIRS
        else None
    )
    validation_errors = history_errors or casefile.validate_casefile(
        data,
        previous=previous,
        legacy_receipt=transition_receipt,
    )
    if validation_errors:
        raise WorkflowError(
            "FINAL_VALIDATION_FAILED", validation_errors[0]["code"]
        )
    if state.get("mode") == "safety":
        safety_response = resolve_internal_path(
            workspace, state.get("safety_response_path")
        )
        if (
            safety_response is None
            or not safety_response.is_file()
            or safety_response.is_symlink()
        ):
            raise WorkflowError(
                "SAFETY_RESPONSE_REQUIRED",
                "the acknowledged safety response is the only user-visible terminal output",
            )
        rendered = safety_response.read_text(encoding="utf-8")
    else:
        rendered = casefile.render_markdown(data)
    if output.exists():
        if output.is_symlink() or not output.is_file() or output.read_text(encoding="utf-8") != rendered:
            raise WorkflowError(
                "RECOVERY_CONFLICT",
                "orphan response does not match the deterministic renderer",
            )
    else:
        casefile.atomic_write(output, rendered)
    relative_output = str(output.relative_to(workspace))
    old_phase = str(state["phase"])
    state["phase"] = "completed"
    state["response_path"] = relative_output
    state["response_sha256"] = sha256_file(output)
    event(state, "finalize", old_phase, "completed")
    save_state(workspace, state)
    print(json.dumps(public_state(workspace, state), ensure_ascii=False, indent=2))
    return 0


def _safety_response_has_unsafe_direction(text: str) -> bool:
    if re.search(
        r"(?:立即|马上|现在|然后|接着|之后|先)?\s*"
        r"(?:自杀|轻生|跳楼|割腕|上吊|"
        r"吞下?.{0,8}(?:一整瓶|整瓶|大量)药|"
        r"杀(?:了|死)?(?:他|她|人|对方)|"
        r"捅(?:他|她|人|对方)|砍(?:他|她|人|对方)|"
        r"拿刀.{0,8}(?:去找|算账|报复|对质))",
        text,
    ):
        return True
    if re.search(
        r"(?:不要|别|无需|不必).{0,8}(?:报警|联系警方|联系警察|急救|"
        r"去安全地点|前往安全地点|联系可信任|去急诊)",
        text,
    ):
        return True
    for segment in re.split(r"[。！？；，,\n]+", text):
        value = segment.strip()
        if not value:
            continue
        protective = bool(
            re.search(
                r"(?:不要|别|避免|切勿)\s*(?:立即|马上|现在|再)?\s*"
                r"(?:开门|联系对方|见面|"
                r"单独见面|对质|报复|前往对方住处)",
                value,
            )
        )
        unsafe = bool(
            re.search(
                r"(?:独自|单独).{0,12}(?:去见|见面|接近|联系|当面对质)|"
                r"(?:当面|面对面).{0,8}(?:对质|质问)|"
                r"(?:实施|进行|马上|立即)?报复|围堵|堵门|"
                r"开门让.{0,8}(?:他|她|对方).{0,6}(?:进|进入)|"
                r"(?:去|前往).{0,12}(?:对方|前任|威胁者).{0,8}(?:家|住处)",
                value,
            )
        )
        if unsafe and not protective:
            return True
    return False


def validate_safety_response(
    text: str,
    signal_types: set[str] | None = None,
    input_text: str = "",
) -> bool:
    if signal_types is not None:
        try:
            expected = render_safety_response(signal_types, input_text)
        except ValueError:
            return False
        return text.strip().replace("\r\n", "\n") == expected
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return False
    first = re.sub(r"^\s*(?:#{1,6}|[-*])\s*", "", lines[0])
    positive_action = re.search(
        r"^(?:现在|立即|马上|先|请|此刻)?\s*"
        r"(?:先|立即|马上)?\s*"
        r"(?:"
        r"报警|"
        r"(?:联系|拨打|求助(?:于)?)[^，,。；;]{0,12}"
        r"(?:警方|警察|000|急救|紧急服务|可信任(?:的人|家人|朋友)?|"
        r"医生|急诊|医疗支持|律师|法律支持|法律援助|危机热线|当地支持)|"
        r"(?:前往|去|离开|待在)[^，,。；;]{0,12}"
        r"(?:安全地点|有人值守|急诊|医院)|"
        r"让[^，,。；;]{0,8}(?:可信任的人|家人|朋友)[^，,。；;]{0,6}陪同"
        r")",
        first,
    )
    protective_action = re.search(
        r"^(?:现在|立即|马上|先|请)?\s*"
        r"(?:不要|别|避免|切勿)\s*"
        r"(?:开门|单独见面|当面对质|接触对方)",
        first,
    )
    action_first = bool(positive_action or protective_action)
    real_world = bool(
        re.search(
            r"报警|警方|警察|000|急救|紧急服务|安全地点|有人值守|"
            r"可信任(?:的人|家人|朋友)?|医生|急诊|医疗支持|律师|法律支持|"
            r"危机热线|当地支持",
            first,
        )
    )
    unsafe_direction = _safety_response_has_unsafe_direction(text)
    rejected_support = bool(
        re.search(
            r"(?:没必要|没有必要|无需|不用|不必|不要|别|不应当|不应该)"
            r".{0,8}(?:报警|联系警方|联系警察|联系紧急服务|叫急救|去急诊|就医|寻求帮助)",
            text,
        )
    )
    defeatist_or_harmful_frame = bool(
        re.search(
            r"(?:警方|警察|急救|紧急服务).{0,8}(?:不会来|帮不了|没用)|"
            r"(?:让|叫)(?:警方|警察|急救|紧急服务).{0,6}(?:别管|不要管|不用管)|"
            r"(?:报警|求助|就医).{0,8}(?:只会|反而).{0,10}(?:更糟|恶化)|"
            r"(?:报警|联系(?:警方|警察|急救|紧急服务|可信任的人)|"
            r"去安全地点|前往安全地点).{0,14}"
            r"(?:错误|不可取|假建议|最危险|不安全|不应该|不建议|不值得|没用|无用)|"
            r"(?:报警|求助|就医).{0,12}(?:我不建议|不建议这样做)|"
            r"(?:自己扛|自己处理|别求助)",
            text,
        )
    )
    dangerous_added_instruction = bool(
        casefile.expected_safety_signal_types(text)
        & {"self_harm_risk", "harm_to_others_risk", "explicit_threat"}
    ) or bool(
        re.search(
            r"(?:然后|接着|随后|再|并且|同时|不要等).{0,16}"
            r"(?:开枪|枪击|射杀|打死|杀死|捅|砍|揍|殴打|撞|烧死|放火|"
            r"服下|吞下|冲过去|报复|算账)",
            text,
        )
    )
    forbidden = (
        "可观察事实",
        "用户当前的解释",
        "尚未验证的动机推断",
        "真实动机",
        "他只是",
    )
    if not (
        action_first
        and real_world
        and not unsafe_direction
        and not rejected_support
        and not defeatist_or_harmful_frame
        and not dangerous_added_instruction
        and not any(item in text for item in forbidden)
    ):
        return False
    signal_types = signal_types or set()
    support_patterns = {
        "medical_emergency": r"急救|急诊|医生|医疗支持|医院|000",
        "urgent_legal_risk": r"律师|法律支持|法律援助|法定期限",
        "self_harm_risk": r"急救|紧急服务|医生|医疗支持|危机热线|可信任|000",
        "third_party_self_harm_risk": r"当事人所在地|紧急服务|可信任人员|000",
        "explicit_threat": r"报警|警方|警察|紧急服务|安全地点|有人值守|可信任|000",
        "harm_to_others_risk": r"报警|警方|警察|紧急服务|000",
        "prior_violence_or_damage": r"报警|警方|警察|紧急服务|安全地点|有人值守|000",
        "access_or_location_exposure": r"报警|警方|警察|紧急服务|安全地点|有人值守|000",
        "other_immediate_risk": r"报警|警方|警察|急救|紧急服务|安全地点|医生|医疗支持|可信任|000",
    }
    return all(
        re.search(support_patterns.get(signal_type, r"紧急服务|当地支持"), text)
        for signal_type in signal_types
    )


def _australia_emergency_context(input_text: str) -> bool:
    """Return whether the latest explicit user-location event binds Australia.

    Jurisdiction is state, not keyword presence.  A past location, a negated
    location, or a later correction must not cause an Australia-only number to
    be emitted.  When the latest named place is not recognisable as Australia,
    fail closed to the generic local-emergency wording.
    """

    def is_australian_place(place: str) -> bool:
        return bool(
            re.search(
                r"悉尼|澳大利亚|澳洲|\bSydney\b|\bAustralia\b",
                place,
                re.IGNORECASE,
            )
        ) and not bool(
            re.search(r"不在|并不在|未在|not\s+in", place, re.IGNORECASE)
        )

    # Quoted records, examples, and messages do not establish the user's
    # current jurisdiction.  Preserve offsets while removing their contents.
    location_chars = list(input_text)
    for start, end in casefile._actual_quote_ranges(input_text):
        left = max(0, start - 1)
        right = min(len(location_chars), end + 1)
        location_chars[left:right] = " " * (right - left)
    location_text = "".join(location_chars)

    place_value = r"[A-Za-z][A-Za-z .'-]{1,40}|[一-鿿]{1,18}"
    events: list[tuple[int, bool]] = []

    labelled = re.compile(
        rf"(?:所在地|位置|location)\s*[：:]\s*(?P<place>{place_value})",
        re.IGNORECASE,
    )
    current_user = re.compile(
        rf"(?:我|本人)\s*"
        rf"(?:(?:其实|实际|现在|目前|当前|如今|现已|已经)\s*)*"
        rf"(?:人\s*)?(?:在|位于|身处|到了|抵达(?:了)?)\s*"
        rf"(?P<place>{place_value})",
        re.IGNORECASE,
    )
    implicit_current_user = re.compile(
        rf"(?:但|而|不过|然而|更正[：:]?)?\s*"
        rf"(?:现在|目前|当前|如今|现已|已经)\s*"
        rf"(?:我|本人)?\s*(?:人\s*)?"
        rf"(?:在|位于|身处|到了|抵达(?:了)?)\s*"
        rf"(?P<place>{place_value})",
        re.IGNORECASE,
    )
    current_user_en = re.compile(
        rf"\b(?:I\s+am|I'm)\s+(?:currently\s+|now\s+)?"
        rf"(?:in|located\s+in)\s+(?P<place>{place_value})",
        re.IGNORECASE,
    )
    past_to_current = re.compile(
        rf"(?:我|本人).{{0,8}}(?:之前|以前|曾经|过去|当时|先前)"
        rf".{{0,8}}(?:悉尼|澳大利亚|澳洲|Sydney|Australia)"
        rf".{{0,16}}(?:现在|目前|当前|如今)(?:已经|现已)?"
        rf"(?:在|位于|身处|到了|抵达(?:了)?)\s*"
        rf"(?P<place>{place_value})",
        re.IGNORECASE,
    )
    explicit_denial = re.compile(
        r"(?:我|本人)?\s*(?:并|也)?(?:不在|并不在|没有在|未在|不位于|"
        r"不是在|并非在|不是位于|并非位于)\s*"
        r"(?:悉尼|澳大利亚|澳洲|Sydney|Australia)|"
        r"\bI\s+(?:am\s+not|I'm\s+not|was\s+not|wasn't)\s+in\s+"
        r"(?:Sydney|Australia)\b",
        re.IGNORECASE,
    )
    double_negated_presence = re.compile(
        r"(?:我|本人)?\s*(?:不是|并非)\s*(?:不在|并不在|未在|不位于)\s*"
        r"(?:悉尼|澳大利亚|澳洲|Sydney|Australia)|"
        r"\bI\s+(?:am\s+)?not\s+not\s+in\s+(?:Sydney|Australia)\b",
        re.IGNORECASE,
    )
    double_negated_ranges = [
        (match.start(), match.end())
        for match in double_negated_presence.finditer(location_text)
    ]

    for pattern in (
        labelled,
        current_user,
        implicit_current_user,
        current_user_en,
        past_to_current,
    ):
        for match in pattern.finditer(location_text):
            place = match.group("place").strip()
            clause_start = max(
                (
                    location_text.rfind(mark, 0, match.start())
                    for mark in "。！？；\n"
                ),
                default=-1,
            ) + 1
            attribution_context = location_text[clause_start:match.start()]
            if re.search(
                r"(?:病历|记录|档案|示例|样例|假设|虚构).{0,12}"
                r"(?:错误|有误|误写|误记|错写|写成|记成)|"
                r"(?:错误|有误|误写|误记|错写|记录错误).{0,12}"
                r"(?:病历|记录|档案|位置|所在地)",
                attribution_context,
            ):
                continue
            # "在" can introduce an activity rather than a location.  Ignore
            # those common progressive-verb starts instead of treating them as
            # a jurisdiction correction.
            if re.match(
                r"(?:考虑|想|准备|打算|做|看|写|等|工作|学习|处理)",
                place,
            ):
                continue
            events.append((match.end(), is_australian_place(place)))
    for start, end in double_negated_ranges:
        events.append((end, True))
    for match in explicit_denial.finditer(location_text):
        if any(start <= match.start() and match.end() <= end for start, end in double_negated_ranges):
            continue
        events.append((match.end(), False))

    if not events:
        return False
    events.sort(key=lambda item: item[0])
    return events[-1][1]


def render_safety_response(signal_types: set[str], input_text: str = "") -> str:
    normalized = set(signal_types)
    if not normalized or not normalized <= set(SAFETY_RESPONSE_CATALOG):
        raise ValueError("safety response requires one or more known signal types")
    lines: list[str] = []
    if _australia_emergency_context(input_text) and normalized & {
        "medical_emergency",
        "self_harm_risk",
        "harm_to_others_risk",
        "explicit_threat",
        "prior_violence_or_damage",
        "access_or_location_exposure",
        "other_immediate_risk",
    }:
        lines.append("现在请立即拨打 000（澳大利亚紧急服务）。")
    for signal_type in SAFETY_RESPONSE_ORDER:
        if signal_type not in normalized:
            continue
        line = SAFETY_RESPONSE_CATALOG[signal_type]
        if line not in lines:
            lines.append(line)
    return "\n".join(lines)


def validate_passthrough_response(
    kind: str, request_text: str, response_text: str
) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if kind not in {"translation", "formatting", "sourced_timeline"}:
        errors.append("kind_invalid")
    if passthrough_has_mixed_intent(request_text):
        errors.append("mixed_intent_present")
    if classify_passthrough_request(request_text) != kind:
        errors.append("request_kind_mismatch")
    if not response_text.strip():
        errors.append("response_empty")
    if any(
        item in response_text
        for item in ("可观察事实", "用户当前的解释", "尚未验证的动机推断")
    ):
        errors.append("analysis_scaffold_added")
    payload, _ = _first_transform_payload(request_text)
    if kind == "translation":
        def statement_count(value: str) -> int:
            normalized = re.sub(r"\b(?:a\.?m\.?|p\.?m\.?)", "TIME", value, flags=re.IGNORECASE)
            parts = [
                item
                for item in re.split(r"[。！？!?]+|(?<=[A-Za-z0-9\"'])\.(?=\s|$)", normalized)
                if item.strip(" \t\r\n\"'“”‘’")
            ]
            return max(1, len(parts)) if value.strip() else 0

        if statement_count(response_text) > statement_count(payload):
            errors.append("translation_scope_expanded")
    directive_pattern = re.compile(
        r"(?:所以|因此|你|你们).{0,10}(?:应该|必须|需要|最好|立刻|马上).{0,8}"
        r"(?:分手|辞职|离开|报复|对质|报警)|"
        r"(?:我建议|建议|我的建议是).{0,8}(?:你|你们)?(?:立刻|马上)?"
        r"(?:分手|辞职|离开|报复|对质|报警)|"
        r"(?:^|[。！？!?\n]\s*)(?:立刻|马上)?(?:分手|辞职|离开|报复|对质|报警)(?:吧|。|！|!|$)|"
        r"(?:^|[.!?\n]\s*)(?:please\s+)?(?:quit|resign|leave|retaliate|confront|"
        r"report|call\s+the\s+police|break\s+up)(?:\s+(?:your|the|this|that|his|her|"
        r"job|partner|boss|relationship|situation|person|him|her|them))*"
        r"(?:\s+immediately|\s+now)?[.!]?\s*$|"
        r"\b(?:i\s+recommend(?:\s+that)?|my\s+advice\s+is\s+to)\s+"
        r"(?:you\s+)?(?:break\s+up|quit|resign|leave|retaliate|confront|report)\b|"
        r"\byou\s+(?:should|must|need\s+to|had\s+better)\s+"
        r"(?:break\s+up|quit|resign|leave|retaliate|confront|report)\b",
        re.IGNORECASE,
    )
    motive_story_pattern = re.compile(
        r"(?:想|为了|意图|打算|试图).{0,8}(?:羞辱|惩罚|控制|操纵|伤害|报复)|"
        r"(?:因为|由于).{0,16}(?:恨|厌恶|讨厌|想).{0,8}(?:你|我|他|她)?|"
        r"(?:他|她|对方|老板).{0,30}(?:是)?为了.{0,12}(?:羞辱|惩罚|控制|操纵|伤害|报复)|"
        r"(?:他|她|对方|老板).{0,20}(?:取消|拒绝|不回|离开|这样做).{0,12}"
        r"(?:就是想|目的是|意在)(?:羞辱|惩罚|控制|操纵|伤害|报复)|"
        r"(?:因为|这说明|这意味着).{0,20}(?:他|她|对方|老板).{0,12}"
        r"(?:想|意图|打算|试图)(?:羞辱|惩罚|控制|操纵|伤害|报复)|"
        r"\b(?:he|she|they|your\s+boss|the\s+other\s+person)\b.{0,48}"
        r"\bto\s+(?:humiliate|punish|control|manipulate|hurt|retaliate\s+against)\b|"
        r"\b(?:because|so\s+that|in\s+order\s+to)\b.{0,36}"
        r"(?:humiliate|punish|control|manipulate|hurt|retaliate\s+against|hates?)\b",
        re.IGNORECASE,
    )
    request_scope = payload if kind in {"translation", "formatting"} else request_text
    added_directive = bool(directive_pattern.search(response_text)) and not bool(
        directive_pattern.search(request_scope)
    )
    added_motive_story = bool(motive_story_pattern.search(response_text)) and not bool(
        motive_story_pattern.search(request_scope)
    )
    if kind == "formatting":
        # Formatting is a fidelity transform.  Even when the request parser
        # has accepted one closed operand, the response may not append a new
        # truth, provenance, meaning, or motive conclusion.  This is a second
        # defense independent of routing so a future parser gap cannot turn a
        # formatting path into an unvalidated analysis channel.
        epistemic_assertion_pattern = re.compile(
            r"(?:这(?:句|段)?话|该(?:内容|消息|说法)|消息|说法|来源)"
            r".{0,12}(?:可信|可靠|靠谱|属实|真实|不可信|不可靠|不靠谱|不属实|"
            r"(?:八成|大概|可能|显然|明显)(?:是)?真(?:的)?)|"
            r"(?:这说明|这意味着|由此可见|可以确定|足以证明)"
            r".{0,20}(?:他|她|对方|老板|经理|同事|朋友)"
            r".{0,12}(?:想|要|会|打算|准备|意在|目的)"
            r".{0,16}(?:吓唬|欺骗|控制|操纵|惩罚|报复|伤害|羞辱|"
            r"喜欢|不喜欢|讨厌|恨|开除|架空|排挤|利用|试探)|"
            r"(?:他|她|对方|老板|经理|同事|朋友|这(?:句|段)?话)"
            r".{0,16}(?:显然|明显|肯定|确定|其实|就是|是在|是想|想要|意在|目的)"
            r".{0,16}(?:吓唬|欺骗|控制|操纵|惩罚|报复|伤害|羞辱|"
            r"喜欢|不喜欢|讨厌|恨|开除|架空|排挤|利用|试探)|"
            r"(?:这么说|这样说|这样做|这(?:句|段)?话)"
            r".{0,12}(?:是)?(?:想|为了|意在|目的(?:是|在于)?)"
            r".{0,16}(?:吓唬|欺骗|控制|操纵|惩罚|报复|伤害|羞辱|"
            r"试探|开除|架空|排挤|利用)|"
            r"\b(?:the|this|that)\s+(?:claim|statement|message|source|story)\s+"
            r"(?:is|seems|appears)\s+(?:credible|reliable|true|accurate|authentic|"
            r"trustworthy|real|false|unreliable|inaccurate|inauthentic)\b",
            re.IGNORECASE,
        )
        response_added_epistemic_content = bool(
            epistemic_assertion_pattern.search(response_text)
        ) and not bool(epistemic_assertion_pattern.search(request_scope))
        if response_added_epistemic_content:
            errors.append("epistemic_content_added")
    if kind == "sourced_timeline":
        inference_connector = re.compile(
            r"(?:所以|因此|由此|可见|这(?:就)?(?:说明|表明|意味着)|"
            r"结论(?:是|为)?|可以得出)"
        )
        response_added_inference = bool(
            inference_connector.search(response_text)
        ) and not bool(inference_connector.search(request_text))

        def story_signatures(value: str) -> list[tuple[str, str]]:
            signatures: list[tuple[str, str]] = []
            for span in casefile.generate_source_spans("timeline", value):
                kind_value = casefile.derive_claim_kind_for_span(
                    str(span.get("text", "")), span, value
                )
                if kind_value not in {
                    "interpretation",
                    "motive_inference",
                    "identity_claim",
                    "prediction",
                }:
                    continue
                normalized = re.sub(
                    r"[^一-鿿A-Za-z0-9]+",
                    "",
                    str(span.get("text", "")),
                )
                normalized = re.sub(
                    r"^(?:T|E|S)\d+", "", normalized, flags=re.IGNORECASE
                )
                if normalized:
                    signatures.append((kind_value, normalized))
            return signatures

        request_stories = story_signatures(request_text)
        response_stories = story_signatures(response_text)
        response_added_story = any(
            not any(
                response_kind == request_kind
                and (
                    response_text_value in request_text_value
                    or request_text_value in response_text_value
                )
                for request_kind, request_text_value in request_stories
            )
            for response_kind, response_text_value in response_stories
        )
        timeline_date_pattern = re.compile(
            r"(?:19|20)\d{2}(?:年|[-/.])\s*\d{1,2}"
            r"(?:月|[-/.])(?:\s*\d{1,2}日?)?"
        )
        request_dates = set(timeline_date_pattern.findall(request_text))
        response_dates = set(timeline_date_pattern.findall(response_text))
        response_added_date = not response_dates.issubset(request_dates)

        def canonical_date_token(value: str) -> str:
            return re.sub(r"\D+", "", value)

        def canonical_source_value(value: str) -> str:
            normalized = re.sub(r"[*_`]+", "", value).strip()
            normalized = normalized.strip("[]（）()：:，,。；;| ")
            return re.sub(r"\s+", "", normalized).lower()

        def timeline_source_bindings(
            value: str,
        ) -> tuple[dict[str, set[str]], set[str]]:
            """Bind explicit source fields to dated entries when possible.

            Sourced-timeline passthrough is a fidelity transform, so a source
            may move from a suffix into a table column or prefix label, but it
            may not be rewritten, fabricated, or attached to another dated
            event.  Only explicit source fields are parsed; free prose that
            happens to mention an email is not treated as provenance.
            """
            bindings: dict[str, set[str]] = {}
            all_sources: set[str] = set()
            source_column: int | None = None
            last_dates: list[str] = []
            explicit_source = re.compile(
                r"(?:来源|source)\s*[：:]\s*"
                r"(?P<source>[^|，,。；;\r\n）)\]]{1,64})",
                re.IGNORECASE,
            )
            prefix_source = re.compile(
                r"^\s*\[\s*(?P<source>[^\]\r\n：:]{1,40})"
                r"\s*[：:]\s*\]"
            )

            for line in value.splitlines():
                cells = (
                    [cell.strip() for cell in line.strip().strip("|").split("|")]
                    if "|" in line
                    else []
                )
                if cells and any(cell == "来源" for cell in cells) and any(
                    cell in {"日期", "时间"} for cell in cells
                ):
                    source_column = next(
                        index for index, cell in enumerate(cells) if cell == "来源"
                    )
                    continue

                dates = [
                    canonical_date_token(match.group())
                    for match in timeline_date_pattern.finditer(line)
                ]
                sources = [
                    canonical_source_value(match.group("source"))
                    for match in explicit_source.finditer(line)
                ]
                prefix_match = prefix_source.search(line)
                if prefix_match is not None:
                    sources.append(
                        canonical_source_value(prefix_match.group("source"))
                    )
                if (
                    cells
                    and source_column is not None
                    and source_column < len(cells)
                    and dates
                    and not re.fullmatch(r"[-: ]+", cells[source_column])
                ):
                    sources.append(
                        canonical_source_value(cells[source_column])
                    )
                sources = sorted({source for source in sources if source})
                all_sources.update(sources)
                if dates:
                    last_dates = dates
                target_dates = dates or last_dates
                if sources and target_dates:
                    for date in target_dates:
                        bindings.setdefault(date, set()).update(sources)
            return bindings, all_sources

        request_source_bindings, request_source_values = (
            timeline_source_bindings(request_text)
        )
        response_source_bindings, response_source_values = (
            timeline_source_bindings(response_text)
        )
        response_date_tokens = {
            canonical_date_token(value) for value in response_dates
        }
        source_values_changed = (
            response_source_values != request_source_values
        )
        source_event_binding_changed = any(
            date in response_date_tokens
            and response_source_bindings.get(date) != request_sources
            for date, request_sources in request_source_bindings.items()
        )
        timeline_source_changed = (
            source_values_changed or source_event_binding_changed
        )

        timeline_event_surface = re.compile(
            r"会议|约会|邮件|消息|通知|权限|职责|岗位|项目|活动|"
            r"取消|改期|参加|缺席|迟到|发送|收到|回复|完成|删除|"
            r"移除|离开|到达|开除|解雇|辞退|撤掉|取走|拿走|锁上"
        )

        def canonical_timeline_atom(value: str) -> str:
            normalized = timeline_date_pattern.sub("", value)
            # Source annotations may legally move around an unchanged event
            # during formatting.  Strip the structured annotation as one
            # field before comparing event cores; otherwise ``[邮件：] 事件``
            # and ``事件（来源：邮件）`` look like different event sequences.
            # Free prose mentioning an email remains untouched.
            normalized = re.sub(
                r"^\s*\[[^\]\r\n：:]{1,40}\s*[：:]\s*\]\s*",
                "",
                normalized,
            )
            normalized = re.sub(
                r"[（(]\s*来源\s*[：:]\s*[^）)\r\n]{1,40}\s*[）)]",
                "",
                normalized,
            )
            normalized = re.sub(
                r"\[(?:T|E|S)\d+\]", "", normalized, flags=re.IGNORECASE
            )
            normalized = re.sub(
                r"(?:来源|日期|时间|事件|原文|时间线|年月日|时分秒)",
                "",
                normalized,
            )
            normalized = re.sub(r"[^一-鿿]+", "", normalized)
            return re.sub(r"[了把将于]", "", normalized)

        def timeline_event_atoms(value: str) -> list[str]:
            atoms: list[str] = []
            for clause in re.split(r"[。！？；;\n]+", value):
                if not timeline_event_surface.search(clause):
                    continue
                atom = canonical_timeline_atom(clause)
                if atom:
                    atoms.append(atom)
            return atoms

        def is_subsequence(needle: str, haystack: str) -> bool:
            cursor = iter(haystack)
            return all(any(character == item for item in cursor) for character in needle)

        request_event_atoms = timeline_event_atoms(request_text)
        response_added_event = any(
            not any(
                atom == source_atom
                or atom in source_atom
                or source_atom in atom
                or is_subsequence(atom, source_atom)
                for source_atom in request_event_atoms
            )
            for atom in timeline_event_atoms(response_text)
        )
        if (
            response_added_inference
            or response_added_story
            or response_added_date
            or response_added_event
            or timeline_source_changed
        ):
            errors.append("timeline_scope_expanded")
            if timeline_source_changed:
                errors.append("timeline_source_changed")
            added_motive_story = True
    if re.search(
        r"(?:^|\n).{0,12}(?:表格结论|结论|诊断|人格判断|真实动机|行动建议)[：:]|"
        r"(?:他|她|对方|老板).{0,8}(?:就是|肯定是|一定是).{0,10}"
        r"(?:NPD|回避型|人格障碍|精神疾病)|"
        r"(?:故意惩罚|永远不会改变)|"
        r"(?:所以|因此).{0,10}(?:应该|必须).{0,8}(?:分手|辞职|报复)|"
        r"\b(?:he|she|they|your boss|the other person)\s+"
        r"(?:probably|definitely|certainly|clearly|obviously)\s+"
        r"(?:wanted|wants|intends|is|was|will)|"
        r"\b(?:he|she|they)\s+(?:wanted|wants|intends)\s+to\s+"
        r"(?:punish|control|manipulate|hurt)\b|"
        r"\b(?:he|she|they)\s+will\s+(?:keep|always|never)\b|"
        r"\bthis\s+(?:proves|shows|means|indicates|suggests)\b|"
        r"\b(?:therefore|thus|which means|must mean)\b|"
        r"\b(?:he|she|they)\s+(?:despises?|hates?|detests?)\b|"
        r"\byou\s+(?:should|must)\s+(?:break up|quit|retaliate|confront)\b",
        response_text,
        re.IGNORECASE,
    ) or added_directive or added_motive_story:
        errors.append("free_analysis_added")
    return (not errors, errors)


def record_response(
    workspace: Path,
    state: dict[str, Any],
    source: Path,
    destination_name: str,
    action: str,
) -> None:
    if not source.is_file() or source.is_symlink():
        raise WorkflowError("RESPONSE_INVALID", str(source))
    destination = workspace / destination_name
    text = source.read_text(encoding="utf-8")
    if destination.exists():
        if (
            destination.is_symlink()
            or not destination.is_file()
            or destination.read_text(encoding="utf-8") != text
        ):
            raise WorkflowError(
                "RECOVERY_CONFLICT",
                "orphan response does not match the supplied response",
            )
    else:
        casefile.atomic_write(destination, text)
    if action == "complete-passthrough":
        state["response_path"] = destination_name
        state["response_sha256"] = sha256_file(destination)
    else:
        state["safety_response_path"] = destination_name
        state["safety_response_sha256"] = sha256_file(destination)
    old_phase = str(state["phase"])
    state["phase"] = "completed" if action == "complete-passthrough" else "awaiting_authoring"
    event(state, action, old_phase, state["phase"])
    save_state(workspace, state)


def command_complete_passthrough(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    state = load_state(workspace)
    require_phase(state, {"passthrough_required"}, "PHASE_NOT_PASSTHROUGH")
    state_errors = integrity_errors(workspace, state)
    if (workspace / RESPONSE_FILE).exists():
        state_errors = without_expected_recovery(state_errors, RESPONSE_FILE)
    if (workspace / PASSTHROUGH_VALIDATION_FILE).exists():
        state_errors = without_expected_recovery(
            state_errors, PASSTHROUGH_VALIDATION_FILE
        )
    if state_errors:
        raise WorkflowError(state_errors[0]["code"], state_errors[0]["message"])
    response = Path(args.response).expanduser().resolve()
    if not response.is_file() or not response.read_text(encoding="utf-8").strip():
        raise WorkflowError("RESPONSE_INVALID", "passthrough response must be non-empty")
    text = response.read_text(encoding="utf-8")
    input_path = resolve_internal_path(workspace, state.get("input_path"))
    request_text = (
        input_path.read_text(encoding="utf-8")
        if input_path is not None and input_path.is_file()
        else ""
    )
    kind = state.get("passthrough_kind")
    valid, validation_errors = validate_passthrough_response(
        str(kind), request_text, text
    )
    if not valid:
        raise WorkflowError(
            "PASSTHROUGH_SCOPE_VIOLATION",
            f"passthrough output exceeded the original task: {validation_errors}",
        )
    validation_path = workspace / PASSTHROUGH_VALIDATION_FILE
    validation = {
        "valid": True,
        "kind": kind,
        "input_sha256": state.get("input_sha256"),
        "response_sha256": sha256_file(response),
        "workflow_version": WORKFLOW_VERSION,
        "validator_version": casefile.VALIDATOR_VERSION,
        "checks": {
            "mixed_intent_absent": not passthrough_has_mixed_intent(request_text),
            "response_nonempty": bool(text.strip()),
            "free_analysis_absent": True,
        },
    }
    if validation_path.exists():
        if (
            validation_path.is_symlink()
            or not validation_path.is_file()
            or casefile.read_json(validation_path) != validation
        ):
            raise WorkflowError(
                "RECOVERY_CONFLICT",
                "orphan passthrough validation does not match this task",
            )
    else:
        casefile.atomic_write_json(validation_path, validation)
    state["passthrough_validation_path"] = PASSTHROUGH_VALIDATION_FILE
    state["passthrough_validation_sha256"] = sha256_file(validation_path)
    record_response(
        workspace, state, response, RESPONSE_FILE, "complete-passthrough"
    )
    print(json.dumps(public_state(workspace, state), ensure_ascii=False, indent=2))
    return 0


def routed_safety_signal_types(
    workspace: Path, state: dict[str, Any]
) -> set[str]:
    input_path = resolve_internal_path(workspace, state.get("input_path"))
    input_text = (
        input_path.read_text(encoding="utf-8")
        if input_path is not None and input_path.is_file()
        else ""
    )
    signal_types = casefile.expected_safety_signal_types(input_text)
    manual_signal_types = state.get("manual_safety_signal_types", [])
    if isinstance(manual_signal_types, list):
        signal_types.update(
            item
            for item in manual_signal_types
            if item in casefile.SIGNAL_TYPES
        )
    # Safety mode is deliberately sticky across revisions.  A follow-up that
    # reports improvement must not create an impossible phase with no bound
    # template type.  Preserve the typed, hash-bound safety history until a
    # future contract supports an explicit reviewed de-escalation transition.
    artifact_path = resolve_internal_path(workspace, state.get("casefile_path"))
    if artifact_path is not None and artifact_path.is_file():
        artifact = casefile.read_json(artifact_path)
        safety = artifact.get("safety", {}) if isinstance(artifact, dict) else {}
        for item in safety.get("risk_signals", []) if isinstance(safety, dict) else []:
            if (
                isinstance(item, dict)
                and item.get("signal_type") in casefile.SIGNAL_TYPES
            ):
                signal_types.add(item["signal_type"])
    return signal_types


def command_safety_template(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    state = load_state(workspace)
    require_phase(state, {"safety_action_required"}, "PHASE_NOT_SAFETY")
    state_errors = integrity_errors(workspace, state)
    if state_errors:
        raise WorkflowError(state_errors[0]["code"], state_errors[0]["message"])
    try:
        input_path = resolve_internal_path(workspace, state.get("input_path"))
        input_text = (
            input_path.read_text(encoding="utf-8")
            if input_path is not None and input_path.is_file()
            else ""
        )
        response = render_safety_response(
            routed_safety_signal_types(workspace, state), input_text
        )
    except ValueError as exc:
        raise WorkflowError("SAFETY_TYPE_BINDING_INVALID", str(exc)) from exc
    print(response)
    return 0


def command_acknowledge_safety(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    state = load_state(workspace)
    require_phase(state, {"safety_action_required"}, "PHASE_NOT_SAFETY")
    state_errors = integrity_errors(workspace, state)
    if (workspace / SAFETY_RESPONSE_FILE).exists():
        state_errors = without_expected_recovery(
            state_errors, SAFETY_RESPONSE_FILE
        )
    if state_errors:
        raise WorkflowError(state_errors[0]["code"], state_errors[0]["message"])
    response = Path(args.response).expanduser().resolve()
    text = response.read_text(encoding="utf-8") if response.is_file() else ""
    signal_types = routed_safety_signal_types(workspace, state)
    input_path = resolve_internal_path(workspace, state.get("input_path"))
    input_text = (
        input_path.read_text(encoding="utf-8")
        if input_path is not None and input_path.is_file()
        else ""
    )
    if not validate_safety_response(text, signal_types, input_text):
        raise WorkflowError(
            "SAFETY_RESPONSE_INVALID",
            "response must exactly match the deterministic safety template for the bound signal types",
        )
    record_response(
        workspace, state, response, SAFETY_RESPONSE_FILE, "acknowledge-safety"
    )
    print(json.dumps(public_state(workspace, state), ensure_ascii=False, indent=2))
    return 0


def command_status(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).expanduser().resolve()
    state = load_state(workspace)
    errors = integrity_errors(workspace, state)
    result = public_state(workspace, state)
    result["integrity_valid"] = not errors
    result["integrity_errors"] = errors
    result["event_count"] = len(state.get("events", []))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the bounded fact-story separation workflow."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start")
    start.add_argument("--input", required=True)
    start.add_argument("--workspace", required=True)
    start.add_argument("--case-id", required=True)
    start.add_argument(
        "--mode", choices=["auto", "standard", "safety", "passthrough"], default="auto"
    )
    start.add_argument(
        "--safety-signal-type",
        choices=sorted(casefile.SIGNAL_TYPES),
        action="append",
    )
    start.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    start.set_defaults(func=command_start)

    update = subparsers.add_parser("start-update")
    update.add_argument("--history", nargs="+", required=True)
    update.add_argument("--input", required=True)
    update.add_argument("--workspace", required=True)
    update.add_argument("--mode", choices=["auto", "safety"], default="auto")
    update.add_argument(
        "--legacy-receipt",
        help="hash-bound validation receipt required when history starts on a legacy profile",
    )
    update.add_argument(
        "--safety-signal-type",
        choices=sorted(casefile.SIGNAL_TYPES),
        action="append",
    )
    update.add_argument("--max-attempts", type=int, default=DEFAULT_MAX_ATTEMPTS)
    update.set_defaults(func=command_start_update)

    check = subparsers.add_parser("check")
    check.add_argument("--workspace", required=True)
    check.set_defaults(func=command_check)

    finalize = subparsers.add_parser("finalize")
    finalize.add_argument("--workspace", required=True)
    finalize.add_argument("--output")
    finalize.set_defaults(func=command_finalize)

    passthrough = subparsers.add_parser("complete-passthrough")
    passthrough.add_argument("--workspace", required=True)
    passthrough.add_argument("--response", required=True)
    passthrough.set_defaults(func=command_complete_passthrough)

    safety_template = subparsers.add_parser("safety-template")
    safety_template.add_argument("--workspace", required=True)
    safety_template.set_defaults(func=command_safety_template)

    safety = subparsers.add_parser("acknowledge-safety")
    safety.add_argument("--workspace", required=True)
    safety.add_argument("--response", required=True)
    safety.set_defaults(func=command_acknowledge_safety)

    status = subparsers.add_parser("status")
    status.add_argument("--workspace", required=True)
    status.set_defaults(func=command_status)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if getattr(args, "max_attempts", DEFAULT_MAX_ATTEMPTS) not in {1, 2}:
        print("MAX_ATTEMPTS_INVALID", file=sys.stderr)
        return 2
    try:
        if args.command in {
            "check",
            "finalize",
            "complete-passthrough",
            "safety-template",
            "acknowledge-safety",
            "status",
        }:
            workspace = Path(args.workspace).expanduser().resolve()
            with workspace_lock(
                workspace, shared=args.command in {"status", "safety-template"}
            ):
                return args.func(args)
        return args.func(args)
    except WorkflowError as exc:
        print(f"{exc.code}: {exc.message}", file=sys.stderr)
        return 2
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        print(f"WORKFLOW_RUNTIME_ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
