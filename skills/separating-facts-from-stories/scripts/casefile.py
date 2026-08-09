#!/usr/bin/env python3
"""Build, validate, version, compare, and render epistemic casefiles."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SKILL_NAME = "separating-facts-from-stories"
SCHEMA_VERSION = "3.2.0"
SKILL_VERSION = "4.4.0"
VALIDATOR_VERSION = "4.4.0"
TRUSTED_LEGACY_CORPUS_PATH = (
    Path(__file__).resolve().parents[1]
    / "evals"
    / "legacy-migration-corpus.json"
)

CURRENT_VERSION_PAIR = (SCHEMA_VERSION, SKILL_VERSION)
MIGRATABLE_VERSION_PAIRS = {
    ("3.0.0", "4.0.0"),
    ("3.0.0", "4.0.1"),
}
SUPPORTED_VERSION_PAIRS = {CURRENT_VERSION_PAIR, *MIGRATABLE_VERSION_PAIRS}
PRE_ATTRIBUTED_STATEMENT_VERSION_PAIRS = {
    ("3.0.0", "4.0.0"),
    ("3.0.0", "4.0.1"),
}
VERSION_PAIR_RANK = {
    ("3.0.0", "4.0.0"): 0,
    ("3.0.0", "4.0.1"): 1,
    CURRENT_VERSION_PAIR: 2,
}
VERSION_PROFILE_BY_PAIR = {
    ("3.0.0", "4.0.0"): "legacy-v400",
    ("3.0.0", "4.0.1"): "legacy-v401",
    CURRENT_VERSION_PAIR: "current",
}
VERSION_MIGRATION_EDGES = {
    (previous_pair, current_pair)
    for previous_pair, previous_rank in VERSION_PAIR_RANK.items()
    for current_pair, current_rank in VERSION_PAIR_RANK.items()
    if current_rank >= previous_rank
}


def _casefile_version_pair(data: Any) -> tuple[str, str] | None:
    if not isinstance(data, dict):
        return None
    schema_version = data.get("schema_version")
    skill_version = data.get("skill_version")
    if not isinstance(schema_version, str) or not isinstance(skill_version, str):
        return None
    return (schema_version, skill_version)


def _validation_profile_for_pair(pair: tuple[str, str] | None) -> str | None:
    if pair is None:
        return None
    return VERSION_PROFILE_BY_PAIR.get(pair)

MODES = {"standard", "safety", "passthrough"}
CLAIM_KINDS = {
    "observable_fact",
    "explicit_feeling",
    "stated_position",
    "attributed_statement",
    "interpretation",
    "motive_inference",
    "identity_claim",
    "prediction",
}
DIRECTLY_ATTRIBUTED_KINDS = {"stated_position", "attributed_statement"}
OBSERVATION_TYPES = {
    "negative_report_event",
    "communication_event",
    "participation_or_schedule_event",
    "task_or_action_event",
    "artifact_or_system_state",
}
SOURCE_TYPES = {
    "user_report",
    "user_direct_observation",
    "explicit_self_report",
    "direct_quote",
    "secondhand",
    "unverified_artifact",
}
EPISTEMIC_STATUSES = {
    "reported",
    "directly_stated",
    "unverified",
    "weakly_supported",
    "strongly_supported",
    "conflicted",
    "contradicted",
    "verified",
    "superseded",
    "retracted",
}
RELATIONS = {"supports", "conflicts", "does_not_establish"}
STRENGTHS = {"none", "weak", "direct"}
EFFECTS = {"strengthens", "weakens", "keeps_unknown"}
RISKS = {"low", "medium", "high"}
TIMINGS = {"immediate", "next"}
SIGNAL_TYPES = {
    "explicit_threat",
    "prior_violence_or_damage",
    "access_or_location_exposure",
    "self_harm_risk",
    "third_party_self_harm_risk",
    "harm_to_others_risk",
    "medical_emergency",
    "urgent_legal_risk",
    "other_immediate_risk",
}
SAFETY_ROUTING_BASES = {
    "deterministic_backstop",
    "human_semantic_review",
}
LIMITATION_CODES = {
    "single_party_report",
    "secondhand",
    "missing_context",
    "missing_timestamp",
    "artifact_not_verified",
    "not_independent",
    "limited_sample",
    "time_scope_limited",
}
LIMITATION_HUMAN_TEXT = {
    "single_party_report": "来自单方陈述",
    "secondhand": "来自转述",
    "missing_context": "材料上下文不完整",
    "missing_timestamp": "时间尚未核对",
    "artifact_not_verified": "材料真实性尚未核验",
    "not_independent": "来源之间并不独立",
    "limited_sample": "当前样本有限",
    "time_scope_limited": "只反映当前时点",
}
REASON_CODES = {
    "anchor_matches_report",
    "behavior_is_compatible_but_not_diagnostic",
    "direct_current_statement_only",
    "source_scope_limit",
    "counter_signal_with_limited_scope",
    "artifact_scope_limited",
}

ROOT_KEYS = {
    "schema_version",
    "skill_version",
    "case_id",
    "revision",
    "previous_case_sha256",
    "mode",
    "current_input_id",
    "input_sha256",
    "inputs",
    "source_spans",
    "unclassified_observation_candidates",
    "candidate_resolutions",
    "claims",
    "evidence",
    "evidence_links",
    "unknowns",
    "hypotheses",
    "hypothesis_request",
    "discriminator",
    "actions",
    "user_decisions",
    "safety",
    "change_log",
    "legacy_epoch",
}
REQUIRED_ROOT_KEYS = ROOT_KEYS - {"hypothesis_request", "legacy_epoch"}
LEGACY_EPOCH_KEYS = {
    "through_revision",
    "source_version_pair",
    "input_ids",
    "source_span_ids",
    "claim_ids",
    "evidence_ids",
}
LEGACY_EPOCH_VERSION_KEYS = {"schema_version", "skill_version"}
INPUT_KEYS = {"id", "text", "sha256"}
SOURCE_SPAN_KEYS = {
    "id",
    "input_id",
    "source_ref",
    "source_label",
    "start",
    "end",
    "text",
    "quoted",
    "sha256",
}
UNCLASSIFIED_OBSERVATION_CANDIDATE_KEYS = {
    "id",
    "input_id",
    "source_span_id",
    "source_ref",
    "exact_quote",
    "status",
    "reason",
}
CANDIDATE_RESOLUTION_KEYS = {
    "id",
    "candidate_id",
    "resolution_type",
    "input_id",
    "source_span_id",
    "source_ref",
    "exact_quote",
}
CANDIDATE_RESOLUTION_TYPES = {"user_rejected", "user_confirmed"}
CLAIM_KEYS = {
    "id",
    "kind",
    "observation_type",
    "text",
    "input_id",
    "source_span_id",
    "source_ref",
    "source_type",
    "exact_quote",
    "epistemic_status",
    "diagnostic_boundary",
}
EVIDENCE_KEYS = {
    "id",
    "input_id",
    "source_span_id",
    "source_ref",
    "source_type",
    "exact_quote",
    "can_establish",
    "cannot_establish",
    "limitations",
}
EVIDENCE_LINK_KEYS = {
    "proposition_id",
    "evidence_ref",
    "relation",
    "strength",
    "reason",
}
UNKNOWN_KEYS = {"id", "unknown_type", "text", "status", "resolved_by_evidence_refs"}
HYPOTHESIS_KEYS = {
    "id",
    "hypothesis_type",
    "text",
    "confidence",
    "support_signals",
    "weakening_signals",
    "exit_condition",
}
HYPOTHESIS_REQUEST_KEYS = {
    "input_id",
    "source_span_id",
    "source_ref",
    "exact_quote",
    "requested_count",
}
DISCRIMINATOR_KEYS = {
    "question",
    "distinguishes",
    "branches",
    "risk",
    "reversible",
}
BRANCH_KEYS = {"answer_type", "observable_answer", "updates"}
UPDATE_KEYS = {"target_id", "effect"}
ACTION_KEYS = {
    "id",
    "action_type",
    "text",
    "timing",
    "risk",
    "reversible",
    "motive_independent",
    "produces_new_evidence",
}
SAFETY_KEYS = {"risk_signals"}
RISK_SIGNAL_KEYS = {
    "input_id",
    "source_span_id",
    "source_ref",
    "exact_quote",
    "signal_type",
    "routing_basis",
}
CHANGE_KEYS = {
    "target_id",
    "from_status",
    "to_status",
    "reason_evidence_refs",
    "superseded_by_claim_id",
}

DISCRIMINATOR_QUESTION_TYPES = {
    "formal_role_or_authority_check": "我目前的正式职责、决策参与范围或审批权限是否发生变化？",
    "stated_boundary_check": "对方当前明确表达的安排或边界是什么？",
    "pattern_over_time_check": "这个行为是否在相同条件下持续重复？",
    "artifact_provenance_check": "这份材料的发送人、时间和完整上下文能否核对？",
    "plan_barrier_check": "最先阻断本轮计划执行的可观察环节是什么？",
    "schedule_or_availability_check": "这次变化是否有可核对的时间或安排原因？",
}
DISCRIMINATOR_KEYS.add("question_type")

HYPOTHESIS_CATALOG = {
    "temporary_scope_or_situational_constraint": "当前变化可能来自临时范围或情境约束",
    "substantive_role_or_boundary_change": "当前变化可能反映职责、边界或优先级的实质调整",
    "communication_or_process_gap": "当前信息缺口可能来自沟通或流程未对齐",
    "plan_design_mismatch": "计划未完成可能与任务设计或执行条件不匹配有关",
    "capacity_or_resource_constraint": "当前结果可能与时间、精力或资源约束有关",
    "repeated_behavior_pattern": "当前事件可能属于需要继续观察的重复行为模式",
}
HYPOTHESIS_SIGNAL_TEXT = {
    "formal_scope_unchanged": "正式职责或权限保持不变",
    "formal_scope_changed": "正式职责或权限发生变化",
    "behavior_does_not_repeat": "相同条件下行为没有继续重复",
    "behavior_repeats": "相同条件下行为继续重复",
    "explicit_boundary_unchanged": "对方明确表达的当前边界没有变化",
    "explicit_boundary_changed": "对方明确表达的当前边界发生变化",
    "source_context_verified": "材料来源、时间和完整上下文得到核对",
    "source_context_not_verified": "材料来源、时间或上下文仍无法核对",
    "small_experiment_improves": "小实验后可观察结果改善",
    "small_experiment_no_improvement": "小实验后可观察结果没有改善",
    "capacity_constraint_observed": "出现可观察的时间、精力或资源约束",
    "capacity_constraint_not_observed": "未发现可观察的时间、精力或资源约束",
}
DECISION_CATALOG = {
    "relationship_boundary": "关系边界设到什么程度",
    "relationship_continuation": "是否继续这段关系",
    "employment_continuation": "是否继续留任或开始评估其他职业选择",
    "communication_boundary": "是否沟通以及采用什么沟通边界",
    "plan_adjustment": "是否调整计划、目标或执行方式",
    "evidence_threshold": "需要多少现实证据才足以改变当前判断",
    "professional_support": "是否寻求现实中的合格专业支持",
    "other_major_choice": "其他重大价值取舍",
}

UNKNOWN_CATALOG = {
    "other_party_motive_or_feeling": "对方的真实动机或感受当前是否有可核对的直接信息",
    "relationship_status_or_intention": "对方当前明确表达的关系安排或边界是什么",
    "formal_role_or_authority_change": "正式职责、参与范围或审批权限是否发生变化",
    "future_behavior_or_outcome": "后续行为或结果是否会按当前推断发生",
    "source_provenance_or_context": "材料的来源、时间和完整上下文能否核对",
    "event_cause_or_context": "当前事件的具体原因或上下文是什么",
    "plan_barrier_or_capacity": "最先阻断计划执行的环节及现实约束是什么",
    "pattern_over_time": "该行为是否会在相同条件下持续重复",
}

ACTION_CATALOG: dict[str, dict[str, Any]] = {
    "record_pattern": {
        "modes": {"standard"},
        "text": "记录后续发生的具体行为、时间和结果",
        "timing": "next",
        "risk": "low",
        "reversible": True,
        "motive_independent": True,
        "produces_new_evidence": True,
    },
    "neutral_check": {
        "modes": {"standard"},
        "text": "围绕具体安排、职责、边界或时间做一次中性核对",
        "timing": "next",
        "risk": "low",
        "reversible": True,
        "motive_independent": True,
        "produces_new_evidence": True,
    },
    "small_experiment": {
        "modes": {"standard"},
        "text": "把下一步缩小为一次可观察、可撤回的小实验",
        "timing": "next",
        "risk": "low",
        "reversible": True,
        "motive_independent": True,
        "produces_new_evidence": True,
    },
    "pause_major_decision": {
        "modes": {"standard"},
        "text": "暂不依据当前动机猜测做重大决定，先补充可观察信息",
        "timing": "next",
        "risk": "low",
        "reversible": True,
        "motive_independent": True,
        "produces_new_evidence": False,
    },
    "move_to_safe_place": {
        "modes": {"safety"},
        "text": "立即前往有其他人在场或有人值守的安全地点",
        "timing": "immediate",
        "risk": "low",
        "reversible": True,
        "motive_independent": True,
        "produces_new_evidence": False,
    },
    "contact_emergency_services": {
        "modes": {"safety"},
        "text": "立即联系当地紧急服务，并说明明确威胁、时间和可达性",
        "timing": "immediate",
        "risk": "low",
        "reversible": True,
        "motive_independent": True,
        "produces_new_evidence": False,
    },
    "contact_trusted_person": {
        "modes": {"safety"},
        "text": "立即联系可信任的人，告知当前位置并保持联系",
        "timing": "immediate",
        "risk": "low",
        "reversible": True,
        "motive_independent": True,
        "produces_new_evidence": False,
    },
    "avoid_contact_or_confrontation": {
        "modes": {"safety"},
        "text": "不要开门、单独见面或当面对质",
        "timing": "immediate",
        "risk": "low",
        "reversible": True,
        "motive_independent": True,
        "produces_new_evidence": False,
    },
    "preserve_evidence_if_safe": {
        "modes": {"safety"},
        "text": "只在不增加风险的前提下保存威胁原文、时间和记录",
        "timing": "next",
        "risk": "low",
        "reversible": True,
        "motive_independent": True,
        "produces_new_evidence": True,
    },
    "seek_medical_support": {
        "modes": {"safety"},
        "text": "立即联系当地急救或合格医疗支持",
        "timing": "immediate",
        "risk": "low",
        "reversible": True,
        "motive_independent": True,
        "produces_new_evidence": False,
    },
    "seek_legal_support": {
        "modes": {"safety"},
        "text": "尽快联系当地合格法律支持，避免错过紧迫期限",
        "timing": "immediate",
        "risk": "low",
        "reversible": True,
        "motive_independent": True,
        "produces_new_evidence": False,
    },
}

SELF_HARM_OUTCOME_PATTERN = r"(?:去死|寻短见|一死了之|了结自己|结束(?:自己的)?生命)"
SELF_HARM_VARIANT_PATTERN = (
    rf"(?:我|自己).{{0,6}}(?:想|要|准备|打算).{{0,6}}{SELF_HARM_OUTCOME_PATTERN}"
)
DIRECT_SELF_HARM_INTENT_PATTERN = (
    r"(?:我|本人)(?:现在|当前|目前|此刻)?.{0,6}"
    r"(?:想|要|会|准备|打算|决定).{0,6}"
    r"(?:自伤|自杀|轻生|伤害自己|结束自己的生命)"
)
WEAPON_VARIANT_PATTERN = r"(?:拿|带|持|握|攥)(?:着|了)?(?:一把)?(?:菜刀|刀)"
MEDICAL_VARIANT_PATTERN = (
    r"(?:胸(?:口|部)?.{0,3}(?:剧痛|疼痛|痛)|喘(?:不|没).{0,2}(?:上|过).{0,2}气)"
)
MEDICATION_EMERGENCY_PATTERN = (
    r"吞(?:了)?.{0,12}(?:一整板|一板|整板|一整瓶|整瓶|很多|大量)?"
    r"(?:安眠药|药片|药物)"
)
ROOFTOP_SELF_HARM_PATTERN = (
    r"(?:从|往).{0,4}(?:天台|楼顶|窗台|桥上|桥面|大桥).{0,4}"
    r"(?:跨出去|迈出去|跳下去|跳下)"
)
COLLOQUIAL_THREAT_PATTERN = (
    r"(?:要|想|准备|打算|会).{0,5}(?:废了|做掉|弄残)(?:我|你|他|她|对方)"
)
ENGLISH_HARM_TARGET_PATTERN = (
    r"(?:you|him|her|them|someone|somebody|that\s+person|"
    r"(?:(?:my|a|the)\s+)?(?:roommate|coworker|colleague|partner|friend|"
    r"family\s+member))"
)
HARM_TO_OTHERS_INTENT_PATTERN = (
    r"(?:"
    r"(?:我|本人).{0,8}(?:要|想|会|准备|打算).{0,8}"
    r"(?:杀(?:死)?|弄死|伤害|捅(?:伤|死)?|砍(?:伤|死)?|打死).{0,8}"
    r"(?:人|某人|你|他|她|别人|他们|她们|对方|室友)|"
    r"(?:我|本人).{0,8}(?:要|想|会|准备|打算).{0,8}"
    r"把(?:人|某人|你|他|她|别人|对方|室友).{0,6}"
    r"(?:捅|砍|打|杀).{0,6}|"
    r"\bI\s+(?:(?:am|'m)\s+going\s+to|want\s+to|plan\s+to|"
    r"intend\s+to|will|(?:am|'m)\s+planning\s+to)\s+"
    r"(?:kill|hurt|stab|shoot)\s+"
    rf"{ENGLISH_HARM_TARGET_PATTERN}\b"
    r")"
)
SELF_DIRECTED_HARM_PATTERN = (
    r"(?:我|本人).{0,8}(?:要|想|会|准备|打算|决定).{0,8}"
    r"(?:杀(?:死|了)?|弄死|伤害)(?:我自己|自己|本人)|"
    r"\bI\s+(?:(?:am|'m)\s+going\s+to|want\s+to|plan\s+to|"
    r"intend\s+to|will|(?:am|'m)\s+planning\s+to)\s+"
    r"(?:kill|hurt)\s+myself\b"
)
OTHER_HARM_OUTCOME_PATTERN = (
    r"(?:杀(?:死|了)?|弄死|捅(?:伤|死)?|砍(?:伤|死)?|打死)"
    r"(?:人|某人|我|你|他|她|别人|他们|她们|对方)"
)
REPORTED_THREAT_PATTERN = (
    r"(?:他|她|对方|前任|陌生人).{0,24}"
    r"(?:说|发消息说|发来消息说|威胁|扬言).{0,10}"
    r"(?:今晚|今天|明天|现在|稍后)?.{0,4}"
    r"(?:要|会|准备|打算)?(?:杀(?:死|了)?|弄死|捅死|砍死|打死)"
    r"(?:我|你|他|她|对方)"
)
NEGATABLE_RISK_TERM_PATTERN = (
    rf"(?:胸痛|呼吸困难|失去意识|昏迷|严重出血|"
    rf"持刀|拿刀|带刀|有枪|武器|跟踪|尾随|打我|伤害我|"
    rf"自伤|自杀|轻生|跳楼|跳下去|跳下|伤害自己|伤害他人|伤害别人|"
    rf"伤害(?:我的|你的|他的|她的)?(?:室友|同事|朋友|伴侣|家人)|"
    rf"结束自己的生命|"
    rf"{OTHER_HARM_OUTCOME_PATTERN}|{SELF_HARM_OUTCOME_PATTERN}|"
    rf"{WEAPON_VARIANT_PATTERN}|{MEDICAL_VARIANT_PATTERN})"
)

SAFETY_TEXT_PATTERN = re.compile(
    r"堵你|堵我|砸过.{0,8}(门|东西)|杀了|杀死|弄死|打死|捅伤|捅死|砍伤|砍死|"
    r"掐死|收拾我|打我|强奸|自杀|不想活|跳楼|割腕|上吊|吞药|过量服药|服药过量|"
    r"伤害自己|伤害他人|结束自己的生命|(?:我|自己).{0,6}(?:想|要|准备).{0,6}结束这一切|"
    r"轻生|拿刀|带刀|持刀|有枪|斧头|锤子|棍子|武器|炸弹|门锁密码|"
    r"扬言|威胁.{0,12}让我消失|见不到明天|强行.{0,6}(进|来|到访)|闯进|跟踪|尾随|胸痛|呼吸困难|失去意识|昏迷|严重出血|"
    r"上诉最后期限|申诉最后期限|法定期限|紧迫期限|今天截止|明天截止|"
    r"\b(kill|stab|shoot|gun|knife|axe|weapon|break in|waiting outside|overdose|suicide|"
    rf"can(?:'|’|‘)t breathe|cannot breathe|chest pain)\b|(?:{SELF_HARM_VARIANT_PATTERN})|"
    rf"(?:{WEAPON_VARIANT_PATTERN})|(?:{MEDICAL_VARIANT_PATTERN})|"
    rf"(?:{MEDICATION_EMERGENCY_PATTERN})|(?:{ROOFTOP_SELF_HARM_PATTERN})|"
    rf"(?:{COLLOQUIAL_THREAT_PATTERN})",
    re.IGNORECASE,
)

STORY_MARKERS = re.compile(
    r"我认为|我觉得|说明|意味着|肯定|注定|回避型|NPD|人格|没自制力|"
    r"精神疾病|精神病|障碍|综合征|依恋|双相|躁郁|抑郁症|躁狂症|型人格|"
    r"(?:患有?|确诊(?:为)?|被诊断(?:为)?|诊断为)\s*(?:[A-Za-z][A-Za-z0-9-]{1,12}|[一-鿿]{1,10}(?:症|障碍|综合征))|"
    r"(?:是|像|简直是)(?:个|一个)?.{0,6}[一-鿿]{1,5}狂|"
    r"出轨|不爱|爱我|故意|真实动机|操纵|报复|蓄意|恶意|羞辱|本质上|责任心|"
    r"存心|成心|明摆着|摆明|迟早|早晚|终将|势必|必然|"
    r"准备.{0,6}(开掉|踢出)|"
    r"架空我|边缘化|没把.{0,8}当回事|惩罚我|瞧不起|冷暴力|排挤我|针对我|吊着我|"
    r"失败者|不配被爱|没用|废物|无能|嫌我|控制欲|永远|绝不会|"
    r"不在乎|在乎我|看不起|备胎|成不了事|削弱我|踢出核心圈|"
    r"讨厌我|恨我|真心|内心|利用我|背叛我|不尊重我|孤立我"
)
REPORT_QUALIFIER_PATTERN = r"(?:亲口|亲耳|当面|明确|真正|确实|实际|真的)*"
REPORT_VERB_PATTERN = r"(?:说|讲|表示|提到|提|声称)"
NEGATED_REPORT_MARKERS = re.compile(
    rf"(?:(?:并)?没有(?:任何)?人|无人|没人|谁也没|从来没|从未|不曾)"
    rf"{REPORT_QUALIFIER_PATTERN}{REPORT_VERB_PATTERN}(?:过)?|"
    rf"(?:我|本人)(?:没有|没|从未|不曾)(?:亲耳)?(?:听见|听到|听)"
    rf"(?:他|她|对方|前任|老板|同事|朋友){REPORT_QUALIFIER_PATTERN}"
    rf"{REPORT_VERB_PATTERN}(?:过)?|"
    rf"(?:并)?(?:没有|没|未){REPORT_QUALIFIER_PATTERN}{REPORT_VERB_PATTERN}(?:过)?|"
    rf"从来(?:没有|没|未){REPORT_QUALIFIER_PATTERN}{REPORT_VERB_PATTERN}(?:过)?|"
    rf"(?:从未|不曾|未曾|何曾|哪里|哪有){REPORT_QUALIFIER_PATTERN}"
    rf"{REPORT_VERB_PATTERN}(?:过)?|"
    r"否认|没有解释|没解释|未解释"
)
SECONDHAND_CONTEXT_MARKERS = re.compile(
    r"(?:同事|朋友|同学|室友|别人|有人|中间人|领导|经理|主管|上司|"
    r"HR|人事|秘书|家人|父亲|母亲|爸爸|妈妈|爸|妈|客户|老师|医生|律师|"
    r"小[一-鿿A-Za-z0-9]{1,3})"
    r".{0,12}(?:说|讲|告诉|转告|转述|转达|传话|提到|提过|回忆|声称|表示|透露|告知|称)|"
    r"我从.{1,12}(?:那里|那儿|处)(?:得知|获悉|听说|听到|了解到|听来(?:的)?)|"
    r"据.{0,8}(?:回忆|说|转述)|(?:听说|据说|转述)|"
    r"我听.{0,8}(?:说|提过)|听(?:人|别人|同事|朋友)?讲|据我所知|"
    r"(?:群里(?:传来)?消息|消息).{0,8}(?:说|称|提到)|"
    r"(?:我)?(?:是)?通过.{1,12}(?:得知|获悉|听说|了解到)"
)

# Provenance is derived from a small set of typed carrier structures rather
# than from complete-sentence examples.  A hearsay frame has an attribution
# cue, an optional source owner, and a reporting predicate.  An artifact frame
# has a non-human carrier and a content-bearing predicate.  The same ontology
# is reused by source-span generation, quote ownership, and label validation.
HEARSAY_SOURCE_OWNER_PATTERN = (
    r"(?:他|她|对方|前任|有人|别人|传闻|消息|同事|朋友|同学|室友|领导|经理|主管|上司|"
    r"HR|人事|秘书|中间人|传话人|家人|客户|老师|医生|律师|熟人|知情人|内部人士|消息人士|"
    r"人家|大家|外界|圈内|群里|内部渠道|小[一-鿿A-Za-z0-9]{1,4}|"
    r"[一-鿿]{1,4}(?:先生|女士|老师|医生|律师|经理|主管|总监|教授))"
)
HEARSAY_REPORTING_PREDICATE_PATTERN = (
    r"(?:说(?!明|法)|讲|称(?!为|作|号|谓)|表示|声称|提到|提过|聊到|转告|转述|转达|传话|"
    r"代为带话|带话|捎话|代传|转了一道|透露|告知|爆料|回忆|提供消息|提(?:了)?(?:一)?(?:嘴|句)|"
    r"念叨(?:过)?|放话|(?:都在)?传|流传|盛传|传出)"
)
HEARSAY_ATTRIBUTION_PATTERN = re.compile(
    rf"(?:据传|据说|据称|传闻|传言|听闻|听说)(?:称|说|显示|指出)?|"
    r"(?:网传|网上流传|网络传言)|"
    r"据[^，,。！？；!?;]{0,12}(?:消息|说法|来源|渠道)[，,：:]?|"
    rf"{HEARSAY_SOURCE_OWNER_PATTERN}.{{0,10}}{HEARSAY_REPORTING_PREDICATE_PATTERN}|"
    r"(?:我|本人)(?:接到|收到|听到|获悉|得知|了解到).{0,8}"
    r"(?:消息|说法|爆料|传闻|通知)|"
    r"(?:群里|群聊里|消息里).{0,8}(?:传来|写着|说|称|提到)|"
    r"(?:有|听到?)?风声.{0,4}(?:说|称|传出)|"
    r"(?:听|听到)(?:人|熟人|朋友|同事)?.{0,6}念叨(?:过)?|"
    r"(?:我|本人)(?:从|经由|通过).{0,16}"
    r"(?:渠道|来源|人士|朋友|熟人|同事).{0,4}(?:得知|获悉|了解到|听说)|"
    r"(?:我|本人)被(?:告知|通知|转告)|"
    r"(?:群聊|群里|圈内|网上|网络).{0,8}(?:传出|流传|传来).{0,6}"
    r"(?:风声|消息|说法)"
)

ARTIFACT_CARRIER_PATTERN = (
    r"(?:截图|截屏|屏幕截图|图片|照片|微信记录|聊天记录|系统记录|记录|"
    r"录音(?!通话)|语音(?!通话)|视频(?!通话)|新闻报道|报道|会议纪要|"
    r"邮件(?:原文)?|短信|消息原文|文档|文件|附件|培训材料|教学材料|"
    r"白皮书|备忘录|电子表格|数据表|工作表|"
    r"(?i:[A-Za-z][A-Za-z0-9._-]{1,20})表|"
    r"(?:工作|项目|系统|操作|值班|会议|沟通|维护|运行|实验|研究)日志|"
    r"年度报告|报告|简报|"
    r"幻灯片|演示文稿|(?i:PPT)|讲义|提案|清单|表格|报表|"
    r"(?i:PDF)|网页(?:内容)?|网站页面|页面|屏幕|公告|通知|"
    r"天气预报|气象预报|研究论文|学术论文|研究报告|说明书|操作手册|"
    r"合同|协议|档案|维修单|书面(?:职责)?确认|AI|模型|机器人|系统|程序|"
    r"测评结果|评估结果|检测结果|测试结果)"
)
ARTIFACT_REPORTING_PREDICATE_PATTERN = (
    r"(?:写(?:着|明|道)?|显示|记录|注明|说|表示|称|告诉我|回复|"
    r"生成|输出|内容(?:是|为)|原文(?:是|为))"
)
ARTIFACT_ATTRIBUTION_PATTERN = re.compile(
    rf"{ARTIFACT_CARRIER_PATTERN}"
    rf"(?:(?:里|中|上|内|里面|当中)\s*)?.{{0,8}}"
    rf"{ARTIFACT_REPORTING_PREDICATE_PATTERN}",
    re.IGNORECASE,
)
UNKNOWN_FRAME_MARKERS = re.compile(
    r"是否|能否|什么|为何|为什么|如何|原因|动机|情况|变化|程度|"
    r"未知|未明确|未核验|尚不清楚|仍不清楚"
)
UNKNOWN_UNSAFE_MARKERS = re.compile(
    r"(?:^|\n)\s*#{1,6}\s|[<>]|```|立即|立刻|报复|曝光|围堵|大闹|"
    r"逼迫|当面对质|必须(?:辞职|分手)|应该(?:辞职|分手)"
)
FEELING_MARKERS = re.compile(
    r"害怕|恐惧|担心|焦虑|难过|伤心|生气|愤怒|委屈|丢脸|羞耻|挫败|失望|"
    r"开心|高兴|安心|难受|心慌|胸闷|无助|孤独|痛苦|烦|紧张|尴尬|"
    r"心里一沉|受够了|疲惫|累|崩溃|不安|压抑|害羞|内疚|"
    r"胸口发紧|胸口紧|胸部发紧|手心出汗"
)
ATOMIC_INFERENCE_CONNECTOR_PATTERN = re.compile(
    r"就是|是在|是要|是想|是因为|是有意|是故意|意在|目的是|目的在于|为了|好让|从而|"
    r"(?:以|来|出于|借此|借机)(?=.{0,8}(?:报复|操纵|控制|惩罚|排挤|架空|伤害|恶意|羞辱))|"
    r"意味着|所以|因此|可见|换句话说|根本|肯定|注定|"
    r"但是|但|可是|然而|不过|却|"
    r"可(?=(?:我|你|他|她|老板))|"
    r"(?<!岗位)(?:证明|说明|表明)(?=(?:我|你|他|她|老板|公司|自己|这|未来|一辈子|这辈子))"
)
POLAR_STORY_QUESTION_PREFIX_PATTERN = re.compile(
    r"^\s*(?:(?:我|你|他|她|对方|老板|公司|自己)\s*)?"
    r"(?:到底\s*)?(?:是否|是不是|会不会|有没有)\s*$"
)
LEADING_CONTRAST_PATTERN = re.compile(
    r"(?:但是|但|可是|然而|不过|却|可(?=(?:我|你|他|她|老板)))"
)
LEADING_SEQUENCE_PATTERN = re.compile(r"(?:随后|后来|之后|接着|然后|同时)")
ATOMIC_STORY_COORDINATION_PATTERN = re.compile(
    r"(?:而且|并且|以及|且|又|也|还|甚至|外加|、)"
)
LEADING_SCOPE_RESET_PATTERN = re.compile(
    r"(?:但是|但|可是|然而|不过|却|而是|随后|后来|之后|接着|然后|同时|"
    r"可(?=(?:我|你|他|她|老板)))"
)
POST_QUOTE_DENIAL_PATTERN = re.compile(
    r"(?:并)?不是.{0,8}(?:说|讲|表示|原话)|并非.{0,8}(?:说|讲|表示|原话)|"
    r"(?:否认|澄清).{0,8}(?:说过|讲过|原话)|"
    r"(?:但|可是|然而)?(?:没有|没|未)说出口"
)
SEMANTIC_QUOTE_DENIAL_PATTERN = re.compile(
    r"(?:否定|驳斥|拒绝承认|不承认|撤回|收回).{0,12}"
    r"(?:这句(?:话)?|该说法|这种说法|原话|是自己的话)|"
    r"(?:这句(?:话)?|该说法|这种说法|原话).{0,12}"
    r"(?:被否定|被驳斥|并不成立|不属实)"
)
SEMANTIC_QUOTE_SUPERSEDED_PATTERN = re.compile(
    r"(?:但|可是|然而|不过|随后|后来|马上|立刻|紧接着|又).{0,16}"
    r"(?:改口|撤回|收回|更正|否认)|"
    r"(?:接着|随后|后来|马上|立刻|紧接着)?.{0,16}"
    r"(?:这句(?:话)?|该说法|这种说法|原话).{0,12}"
    r"(?:不作数|不能算|不算数|作废|无效|撤回|收回)|"
    r"(?:前面|前边|刚才|之前)(?:的)?(?:话|说法|表述).{0,8}"
    r"(?:不作数|不能算|不算数|作废|无效)"
)
QUOTE_QUESTION_PREFIX_PATTERN = re.compile(
    r"(?:问|询问|追问|反问|问道|问我|问你|问他|问她|"
    r"问(?:了)?(?:一|这|那)?句(?:话)?)\s*[:：]?\s*[“‘\"']?\s*$"
)
QUOTE_INTERNAL_POLAR_QUESTION_PATTERN = re.compile(
    r"(?:是否|是不是|有没有|会不会|能不能|要不要)"
)
QUOTE_DECLARATIVE_UNCERTAINTY_PATTERN = re.compile(
    r"(?:不知道|不清楚|不确定|无法判断|尚不清楚|尚未确认|"
    r"需要确认|有待确认|想知道).{0,28}"
    r"(?:是否|是不是|有没有|会不会|能不能|要不要)"
)
QUOTE_CHINESE_TERMINAL_TAG_PATTERN = re.compile(
    r"(?:对吧|是吧|没错吧|好吗|行吗|可以吗|是不是)\s*[。.!！]?$"
)
QUOTE_ENGLISH_INTERROGATIVE_AUX_PATTERN = re.compile(
    r"^\s*(?:am|is|are|was|were|do|does|did|has|have|had|"
    r"can|could|will|would|shall|should|may|might|must)\b",
    re.IGNORECASE,
)
PRE_QUOTE_NONASSERTION_PATTERN = re.compile(
    r"希望|假设|想象|脑补|如果|要是|倘若|假若|假使|即使|一旦|"
    r"(?:等|待)(?=.{0,24}(?:之后|以后|后)?[，,].{0,16}(?:会|将|可能)?(?:说|讲|表示|回复|回答))|"
    r"若(?=.{0,20}(?:会|将|可能)?(?:说|讲|表示|回复|回答))|"
    r"但愿|梦到|假装|举例|假如|"
    r"本来想|打算|准备.{0,4}说|好像|似乎|仿佛|大概|可能.{0,4}说|"
    r"或许|也许|没准|未必|依稀(?:记得)?|印象中|记不清|不确定|"
    r"记得.{0,8}(?:好像|似乎)|担心.{0,8}(?:会|可能)?说|预计.{0,8}说|预期.{0,8}说|"
    r"猜测|推测|猜想|臆测|假定|"
    r"(?:我|本人)(?:猜|估计|怀疑|预测|觉得|认为).{0,24}(?:会|可能)?(?:说|讲|表示|回复|回答)"
)
NEGATED_QUOTE_PREFIX_PATTERN = re.compile(
    r"(?:说|讲|表示|写|回答)?(?:的)?(?:并)?(?:不是|并非)"
    r"\s*[“‘\"']?\s*$|(?:而非)"
    r"\s*[“‘\"']?\s*$"
)
PAST_TIME_SCOPE_FRAGMENT = (
    r"(?:去年|前年|上个月|上周|昨天|前天|过去|曾经|曾|之前|当时|那时|"
    r"上次|上回|那次|那回|那天|前些天|早些时候|"
    r"当年|昔日|从前|早年|"
    r"此前|本月初|上(?:个)?季度|"
    r"去世前|生前|临终前|离职前|辞职前|毕业前|分手前|搬走前|出国前|"
    r"(?:19|20)\d{2}\s*(?:年|[-/.]\s*\d{1,2}(?:\s*[-/.]\s*\d{1,2})?)|"
    r"[〇零一二三四五六七八九]{4}\s*年|"
    r"(?:\d+|[一二三四五六七八九十两]+)(?:天|周|个月|月|年)(?:半|多)?前)"
)
PAST_QUOTE_SCOPE_PATTERN = re.compile(PAST_TIME_SCOPE_FRAGMENT)
HUMAN_OTHER_SPEAKER_PATTERN = (
    r"(?:老板|经理|主管|同事|朋友|家人|医生|老师|律师|"
    r"妈妈|母亲|爸爸|父亲|爸|妈|姐姐|妹妹|哥哥|弟弟|"
    r"丈夫|妻子|老公|老婆|伴侣|男友|女友|他|她|对方|前任|陌生人|"
    r"小[一-鿿A-Za-z0-9]{1,3}|"
    r"[一-鿿]{1,4}(?:先生|女士|老师|医生|律师|经理|主管|总监|教授)|"
    r"[一-鿿]{2,4})"
)
CHINESE_DIRECT_SPEECH_VERB_PATTERN = (
    r"(?:说|讲|表示|称|承诺|保证|告诉|告知|回复|回答|答复|"
    r"发来原话|发消息说|写道|解释(?:道)?|回应|补充|宣布|澄清|"
    r"答道|反驳|承认|强调|确认)"
)
ENGLISH_DIRECT_SPEECH_VERB_PATTERN = (
    r"(?:said|told|wrote|replied|texted|forwarded|explained|responded|"
    r"added|announced|clarified|stated|answered|confirmed|emphasized)"
)
USER_SPEECH_RECIPIENT_PATTERN = (
    r"(?:你|您|老板|经理|主管|同事|朋友|家人|医生|老师|律师|"
    r"妈妈|母亲|爸爸|父亲|爸|妈|姐姐|妹妹|哥哥|弟弟|"
    r"丈夫|妻子|老公|老婆|伴侣|男友|女友|他|她|对方|前任|陌生人|"
    r"小[一-鿿A-Za-z0-9]{1,3}|"
    r"[一-鿿]{1,4}(?:先生|女士|老师|医生|律师|经理|主管|总监|教授))"
)
NONHUMAN_OR_ARTIFACT_QUOTE_OWNER_PATTERN = re.compile(
    rf"(?:{ARTIFACT_CARRIER_PATTERN}|岗位说明|职位说明|职责说明|"
    r"文章|标题|小说|童话|漫画|剧本|语音助手|智能助手|"
    r"客服自动回复|自动回复|海报|墓碑|碑文|牌位|"
    r"虚拟角色|虚拟人物|虚拟人|数字人|动画角色|游戏角色|NPC|假人|"
    r"谣言|传闻|传言|风声)"
    r".{0,24}(?:写道|写着|写明|写|显示|回答|回复|生成|输出|说|表示|称|告诉我|"
    r"发来(?:消息)?|发送(?:消息)?)"
    r"\s*[：:]?\s*[“‘\"']?\s*$",
    re.IGNORECASE,
)
NONREAL_QUOTE_CONTEXT_PATTERN = re.compile(
    r"(?:梦里|梦中|梦境|梦见|梦到|想象|脑补|幻觉|虚构|"
    r"电影|小说|童话|漫画|剧本|游戏|歌词|台词|例句|案例(?:中|里)?|"
    r"示例(?:中|里)?|语法分析|句法分析|文本分析|访谈模拟|角色扮演|模拟(?:访谈|对话|回答)|"
    r"测试(?:文本|输入|用例)?)"
    r".{0,36}(?:说|讲|表示|称|回答|回复|写道)\s*[：:]?\s*[“‘\"']?\s*$",
    re.IGNORECASE,
)
GENERIC_PAST_QUOTE_PREFIX_PATTERN = re.compile(
    r"(?:当年|昔日|从前|早年|回忆中|记忆中|往事中).{0,32}"
    r"(?:说|讲|表示|称|回答|回复|写道|提到)\s*[：:]?\s*[“‘\"']?\s*$|"
    r"(?:在)?[^，,。！？；\n“”]{1,20}(?:时|的时候|期间).{0,8}"
    r"(?:说|讲|表示|称|回答|回复|写道|提到)\s*[：:]?\s*[“‘\"']?\s*$"
)
POST_QUOTE_PAST_SCOPE_PATTERN = re.compile(
    r"^[”’\"']?\s*[，,。！？；]?\s*(?:"
    r"那(?:句(?:话)?|个说法)?(?:是|发生在)\s*"
    rf"{PAST_TIME_SCOPE_FRAGMENT}"
    r"|这(?:句(?:话)?|个说法)?(?:是)?(?:他|她|对方|前任|老板|同事|朋友)?\s*"
    rf"{PAST_TIME_SCOPE_FRAGMENT}\s*"
    r"(?:说|讲|表示|提到)(?:的)?|"
    r"这(?:句(?:话)?|个说法)?(?:是|属于)?\s*"
    rf"{PAST_TIME_SCOPE_FRAGMENT}\s*(?:的)?(?:原话|表态|说法|发言))"
)
PROXY_QUOTE_CONTEXT_PATTERN = re.compile(
    r"(?:读出|念出|引用|转述|复述|播放).{0,16}"
    r"(?:别人|他人|前任|同事|朋友|客户|家人|原作者)?(?:的)?"
    r"(?:原话|文字|内容|录音|留言)\s*[:：]?\s*[“‘\"「『']?\s*$|"
    r"(?:我|本人)(?:帮|替|代替|代|代表|冒充|假扮|模仿).{0,16}"
    r"(?:说|讲|回复|回答|答复|发来原话|发(?:送)?(?:了)?消息|"
    r"代发(?:消息)?(?:说)?|传达)\s*[:：]?\s*[“‘\"「『']?\s*$|"
    r"(?:我|本人)(?:(?:以|用).{1,16}(?:名义|身份|口吻)|"
    r"作为.{1,16}(?:代表|代理人)|受.{1,16}委托).{0,12}"
    r"(?:说|讲|回复|回答|答复|发来原话|发(?:送)?(?:了)?消息|"
    r"代发(?:消息)?(?:说)?|传达)\s*[:：]?\s*[“‘\"「『']?\s*$|"
    r"(?:我|本人)(?:登录|使用|用|借用|借|冒用|以|顶着).{0,20}"
    r"(?:账号|账户|身份|名义|口吻).{0,10}"
    r"(?:说|讲|回复|回答|答复)\s*[:：]?\s*[“‘\"「『']?\s*$|"
    r"(?:我|本人)(?:按|按照|照|照着|依照|遵照|根据).{0,20}"
    r"(?:意思|指示|要求|口径|话术|答案|原话|原文|内容).{0,10}"
    r"(?:说|讲|回复|回答|答复|发来原话|发(?:送)?(?:了)?消息|"
    r"代发(?:消息)?(?:说)?|传达)\s*[:：]?\s*[“‘\"「『']?\s*$|"
    r"(?:我|本人)(?:受托于.{1,12}|受.{1,12}委托).{0,10}"
    r"(?:说|讲|回复|回答|答复|发来原话|发(?:送)?(?:了)?消息|"
    r"代发(?:消息)?(?:说)?|传达)\s*[:：]?\s*[“‘\"「『']?\s*$|"
    r"(?:我|本人)(?:复制|照抄|粘贴).{0,16}(?:答案|原话|内容|回复).{0,10}"
    r"(?:说|讲|回复|回答|答复|发来原话|发(?:送)?(?:了)?消息|"
    r"代发(?:消息)?(?:说)?|传达)\s*[:：]?\s*[“‘\"「『']?\s*$|"
    r"(?:我|本人)把.{0,16}(?:答案|原话|内容)当作(?:我的)?"
    r"(?:回复|回答|答复)\s*[:：]?\s*[“‘\"「『']?\s*$|"
    r"(?:秘书|助理|代理人|中间人|传话人)(?:代|替|代表).{1,16}"
    r"(?:对|跟|向)?(?:我|你|他|她|对方)?\s*(?:说|讲|表示|回复|回答|答复)"
    r"\s*[:：]?\s*[“‘\"「『']?\s*$|"
    r"(?:秘书|助理|代理人|中间人|传话人)(?:受.{1,16}委托|按.{1,16}要求)"
    r".{0,12}(?:对|跟|向)?(?:我|你|他|她|对方)?\s*"
    r"(?:说|讲|表示|回复|回答|答复)\s*[:：]?\s*[“‘\"「『']?\s*$|"
    rf"(?:我|本人|{HUMAN_OTHER_SPEAKER_PATTERN})\s*"
    r"(?:帮|替|代替|代表|代|冒充|假扮|模仿).{0,16}"
    r"(?:说|讲|表示|回复|回答|答复|发消息|代发|传达)"
    r"\s*[:：]?\s*[“‘\"「『']?\s*$|"
    r"(?:他|她|对方|老板|经理|主管|客户|本人).{0,8}授权"
    r"(?:秘书|助理|代理人|中间人|传话人).{0,12}"
    r"(?:说|讲|表示|回复|回答|答复|发消息|代发|传达)"
    r"\s*[:：]?\s*[“‘\"「『']?\s*$|"
    r"(?:秘书|助理|代理人|中间人|传话人)"
    r"(?:(?:以|用).{1,12}(?:名义|身份|口吻)|代表.{1,12}).{0,10}"
    r"(?:说|讲|表示|回复|回答|答复|发消息|代发|传达)"
    r"\s*[:：]?\s*[“‘\"「『']?\s*$"
)

# A quote-shaped string is not necessarily a directly heard utterance.  These
# bounded carrier grammars identify explicit hearsay, artifact mediation, and
# nested reporting before a nearby ``他说`` can overwrite the outer source.
EXPLICIT_HEARSAY_QUOTE_PREFIX_PATTERN = re.compile(
    r"(?:据|根据)\s*[^，,。！？；\n]{0,20}"
    r"(?:说|转述|回忆|说法|消息|来源|渠道).{0,48}$|"
    r"(?:听说|据说|据传|据称|传闻|传言|网传).{0,64}$|"
    r"经(?:由)?(?:朋友|同事|同学|室友|别人|中间人|秘书|助理|家人)"
    r".{0,12}(?:确认|转述|转告|告知).{0,48}$|"
    r"(?:没|没有|未)(?:亲耳)?(?:听见|听到).{0,24}"
    r"(?:朋友|同事|同学|室友|别人|中间人|秘书|助理|家人)"
    r".{0,16}(?:告诉|告知|转述|转告).{0,48}$|"
    r"(?:朋友|同事|同学|室友|别人|中间人|秘书|助理|家人)"
    r".{0,12}(?:告诉|告知|跟我说|对我说|给我说|跟我讲)"
    r"(?:我)?(?:老板|经理|主管|他|她|对方|本人)?.{0,12}"
    r"(?:说|讲|表示|称|回复|回答|原话(?:是|为)).{0,24}$"
)
ARTIFACT_MEDIATED_QUOTE_PREFIX_PATTERN = re.compile(
    rf"{ARTIFACT_CARRIER_PATTERN}.{{0,28}}(?:"
    r"写着|写明|显示|记录|注明|内容(?:是|为)|"
    r"这是.{0,12}(?:原话|回复|说法)|称这是.{0,12}(?:原话|回复|说法))"
    r".{0,20}(?:说|讲|表示|称|回复|回答)?"
    r"\s*[:：]?\s*[“‘\"「『']?\s*$",
    re.IGNORECASE,
)
NESTED_QUOTE_REPORTING_PATTERN = re.compile(
    rf"(?:{HUMAN_OTHER_SPEAKER_PATTERN}|我|本人).{{0,12}}"
    r"(?:说|讲|表示|称|声称|回复|回答).{0,24}"
    rf"{HEARSAY_SOURCE_OWNER_PATTERN}.{{0,12}}"
    r"(?:告诉|告知|转告|转述|转达|说|讲|表示|称|回复|回答)"
    r".{0,20}\s*[:：]?\s*[“‘\"「『']?\s*$"
)
DIRECT_SOURCE_RESET_PATTERN = re.compile(
    rf"(?:但|不过|然而|可是|后来|随后|接着|然后)"
    rf"[^，,。！？；!?;\n]{{0,32}}(?:当面|亲口|直接)"
    r"[^，,。！？；!?;\n]{0,12}(?:"
    r"(?:告诉|告知)(?:了)?\s*(?:我|本人)|"
    r"(?:说|讲|表示|称|承诺|保证|回复|回答|答复|"
    r"发来原话|发消息说|写道|解释(?:道)?|回应|补充|宣布|澄清|"
    r"答道|反驳|承认|强调|确认))",
    re.IGNORECASE,
)

NONVERBATIM_OR_UNCONFIRMED_QUOTE_CONTEXT_PATTERN = re.compile(
    r"(?:^|[。！？；!?;，,\n]\s*)"
    r"(?:\[[^\]\n]{0,12}(?:非原话|意译|大意|摘要|摘录|概述|要点|待确认|未核实|未确认|未经核实)[^\]\n]{0,12}\]\s*|"
    r"(?:我|本人)(?:用|以)(?:我|自己|本人)?(?:的)?话"
    r"(?:概括|转述|复述|总结|改写)[，,：:]?\s*|"
    r"(?:按|依照)(?:我|本人)(?:的)?(?:理解|记忆|印象)(?:来)?"
    r"(?:概括|转述|复述|总结|改写)[，,：:]?\s*)",
    re.IGNORECASE,
)
SECONDHAND_SCOPE_HEADER_PATTERN = re.compile(
    r"(?:^|[：:]\s*)(?:下面|以下|后面|这段|这条|这个|这些)?(?:内容|消息|原话|材料)?"
    r".{0,12}(?:来自|来源于|属于|是|为)?\s*"
    r"(?:同事|朋友|同学|室友|别人|中间人|秘书|助理|家人|客户|老师|医生|律师)?"
    r".{0,8}(?:转述|转告|转达|传话|二手|间接来源)(?:的|内容|材料)?\s*$"
)
ARTIFACT_SCOPE_HEADER_PATTERN = re.compile(
    rf"(?:^|[：:]\s*)(?:下面|以下|后面|这段|这条|这个|这些)?(?:内容|消息|材料)?"
    rf".{{0,12}}(?:来自|来源于|属于|是|为)?\s*(?:{ARTIFACT_CARRIER_PATTERN})\s*$",
    re.IGNORECASE,
)
NONREAL_SCOPE_HEADER_PATTERN = re.compile(
    r"(?:^|[：:]\s*)(?:下面|以下|后面|这段|这条|这个|这些|这是(?:一个)?)?"
    r".{0,12}(?:虚构|模拟|假设|示例|例句|测试|角色扮演|梦境)"
    r"(?:案例|场景|内容|材料|文本|对话|访谈|回答)?\s*$",
    re.IGNORECASE,
)
PRE_QUOTE_COMMUNICATION_EVENT_PATTERN = re.compile(
    r"(?P<event>"
    r"(?:我|本人|他|她|对方|前任|老板|经理|主管|同事|朋友|家人|"
    r"客户|老师|医生|律师|[一-鿿]{2,8})"
    r"(?:今天|刚刚|刚才|随后|后来)?"
    r"(?:发来(?:一条|一封)?(?:消息|邮件)|发(?:了)?消息|"
    r"回复(?:了)?|回信(?:了)?|来电(?:了)?|发送(?:了)?(?:消息|邮件))"
    r")"
    r"(?:说|称|表示|写道|回复道)\s*$"
)
UNQUOTED_REPORTING_CONTEXT_PATTERN = re.compile(
    r"[^，,。！？；\n]{1,28}"
    r"(?:告诉我|转告我|告知我|对我说|跟我说|向我表示|声称|转述|透露|"
    r"(?:跟我)?提过|从.{1,12}(?:那里|那儿|处)听来(?:的)?)"
    r"\s*[，,:：]?\s*$|"
    r"(?:他|她|对方|前任|老板|经理|同事|朋友|家人|客户|老师|医生|律师)"
    r"(?:曾经|刚刚|明确)?(?:说|讲|表示|声称|提到|提过|称)"
    r"\s*[，,:：]\s*$|"
    r"(?:群里(?:传来)?消息|消息).{0,8}(?:说|称|提到)\s*[，,:：]\s*$|"
    r"我从.{1,12}(?:那里|那儿|处)听来(?:的)?\s*[，,:：]\s*$"
)
SECOND_PERSON_REPORT_REQUEST_PATTERN = re.compile(
    r"(?:^|[，,；;])\s*(?:(?:请|麻烦)(?:你)?|你)?\s*"
    r"(?:直接|现在|明确|如实|先|就|赶紧|马上|只需|只要)?(?:来)?"
    r"(?:告诉我|转告我|告知我|对我说|跟我说)\s*[，,:：]?\s*$"
)
SECOND_PERSON_REPORT_REQUEST_SCOPE_PATTERN = re.compile(
    r"(?:^|[，,；;])\s*(?:(?:请|麻烦)(?:你)?|你)\s*"
    r"(?:直接|现在|明确|如实|先|就|赶紧|马上|只需|只要)?(?:来)?"
    r"(?:告诉我|转告我|告知我|对我说|跟我说)\s*[，,:：]"
)
COMMUNICATION_EVENT_MARKERS = re.compile(
    r"发来|发送|发了|回复|没回|没有回复|未回复|已读|收到|通知|告诉|邮件|消息"
)
PARTICIPATION_OR_SCHEDULE_MARKERS = re.compile(
    r"参加|邀请|会议|约会|日历|安排|取消|迟到|到场|改到|改期"
)
TASK_OR_ACTION_MARKERS = re.compile(
    r"完成|删除|删了|拉黑|屏蔽|搬走|搬了|交接|维修|拿回来|砸过|砸了|"
    r"打开|看了|登录|离开|到了|带来|推了|打了|关了|开了|扔了|摔了"
)
ARTIFACT_OR_SYSTEM_MARKERS = re.compile(
    r"系统|权限|审批|截图|维修单|文档|日历|岗位说明|写着|显示|失效|允许|保留|没有看到|未看到|发现"
)
OUT_OF_SCOPE_CONTEXT_MARKERS = re.compile(
    r"另一家公司|其他公司|别家公司|另一个人|别人的|无关案例|新闻中|新闻截图|"
    r"(?:^|\W)[A-ZＡ-Ｚ]公司|(?:19|20)\d{2}年|去年|前年|旧案例|历史案例|外部案例"
)
EPISTEMIC_QUALIFIER_PATTERN = (
    r"(?:据说|听说|据传|据称|传闻|传言|可能|也许|或许|大概|恐怕|"
    r"未必|好像|似乎|看起来)"
)
EPISTEMIC_TRUTH_LINK_PATTERN = (
    r"(?:(?:并)?不是|并非|不算|还是|属于|纯属|算是|是|为)"
)
EPISTEMIC_TRUTH_PREDICATE_PATTERN = (
    r"(?:事实|真的|真|假的|假|谣言|传言|假消息|假新闻|误传|"
    r"属实|不属实|并不属实|不实|可靠|不可靠|准确|不准确)"
)
EPISTEMIC_EVENT_NEGATION_PATTERN = (
    r"(?:(?:并)?没有发生|并未发生|没发生|未发生)"
)
EPISTEMIC_SCOPE_TAIL_PATTERN = re.compile(
    rf"(?:[，,]\s*)?(?:"
    rf"[?？]|(?:吗|么|呢|对吗|是否|是不是|是真的吗|属实吗)|"
    rf"(?:(?:这|此|该)(?:件事|消息|说法|情况)?\s*)?"
    rf"(?:{EPISTEMIC_QUALIFIER_PATTERN}\s*)?"
    rf"(?:{EPISTEMIC_TRUTH_LINK_PATTERN}\s*)?"
    rf"(?:{EPISTEMIC_TRUTH_PREDICATE_PATTERN}|"
    rf"{EPISTEMIC_EVENT_NEGATION_PATTERN}))"
)
EVENT_TRUTH_ANAPHOR_PATTERN = (
    r"(?:(?:这|此|该)(?:事|件事|个事件|条消息|个说法|种说法|个情况)|"
    r"(?:上述|前述)(?:事件|消息|说法|情况))"
)
POSTFIX_EVENT_DISAVOWAL_PATTERN = re.compile(
    r"^\s*[，,]?\s*(?:(?:但|可是|不过|然而)\s*)?"
    r"(?:(?:其实|实际上|事实上|原来)\s*)?"
    r"(?:(?:我|本人)(?:后来|随后|之后)?(?:发现|确认|核实(?:后)?|查明)\s*)?"
    r"(?:"
    rf"{EVENT_TRUTH_ANAPHOR_PATTERN}\s*(?:"
    r"(?:是|属于)?\s*(?:我|本人)(?:瞎)?"
    r"(?:编|编造|杜撰|捏造|虚构)(?:出来)?的|"
    r"纯属(?:杜撰|捏造|虚构)|"
    r"(?:后来|随后|之后)?(?:被)?辟谣"
    r")|"
    r"(?:经|经过)(?:后来|随后|之后)?(?:核实|查证|调查|确认)(?:后)?"
    r"(?:发现|确认)?\s*(?:(?:并)?(?:没有|没|未)发生|(?:并)?不属实)|"
    r"(?:醒来|梦醒)(?:后)?才(?:知道|发现|意识到)"
    r"(?:(?:这|这事|这一切)\s*)?(?:原来)?是(?:一场)?梦|"
    rf"(?:后来|随后|之后)\s*{EVENT_TRUTH_ANAPHOR_PATTERN}\s*(?:被)?辟谣|"
    r"(?:只是|不过是|原来是|是)?\s*(?:我|本人)"
    r"(?:编|编造|杜撰|捏造|虚构|想象|脑补)(?:出来)?的|"
    r"(?:只是|不过是|原来是|是)?\s*(?:个|一个|一场|一则)?\s*(?:"
    r"假消息|假新闻|谣言|误传|不实消息|"
    r"虚构(?:的)?(?:内容|情节|事件)?|"
    r"梦里(?:的)?(?:内容|情节|事件)|梦境|"
    r"想象(?:出来)?的(?:内容|情节|事件)?|"
    r"脑补(?:出来)?的(?:内容|情节|事件)?|玩笑"
    r")|"
    r"(?:(?:这|此|该)(?:件事|消息|说法|情况)?\s*)?"
    r"(?:(?:并)?(?:没有|没|未)发生|(?:并)?不是真的|(?:并)?不属实)"
    r")"
)
TRANSFORM_OPERATION_PATTERN = re.compile(
    r"(?:逐字翻译|翻译(?:成|为)?|翻成|translate|"
    r"(?:English|Chinese)\s+translation(?=\s*[:：])|"
    r"translation\s+(?:into|to)\s+(?:English|Chinese)(?=\s*[:：])|"
    r"改成|改写为|转换成|转成|整理成|排成|加粗|断成|压缩成|纠正.{0,8}标点|"
    r"put.{0,24}(?:blockquote|markdown)|convert\s+to\s+csv|"
    r"alphabetize|uppercase|lowercase|title\s+case|proofread|"
    r"remove\s+punctuation|rewrite\s+as|turn\s+into|return\s+valid\s+json|"
    r"分析(?:这|以下|上面)?(?:句|段)?(?:台词|例句|文本|文字)|"
    r"(?:检查|测试|验证).{0,16}(?:正则|regex|模式|是否匹配)|"
    r"(?:正则|regex|模式).{0,12}(?:匹配|命中))",
    re.IGNORECASE,
)
NEGATED_TRANSLATION_INTENT_PATTERN = re.compile(
    r"(?:不是|并非|不算|不要|无需|不需要)\s*(?:在做|做|进行)?\s*翻译|"
    r"翻译\s*(?:不是|并非)\s*(?:任务|目的|要求)",
    re.IGNORECASE,
)
AFFIRMATIVE_TRANSLATION_OPERATION_PATTERN = re.compile(
    r"(?:(?:英文|英语|中文)\s*翻译|"
    r"(?:English|Chinese)\s+translation(?=\s*[:：])|"
    r"translation\s+(?:into|to)\s+(?:English|Chinese)(?=\s*[:：])|"
    r"(?:逐字翻译|翻译(?:成|为)?|翻成)(?:英文|英语|中文)?|"
    r"译(?:成|为)(?:英文|英语|中文)|"
    r"translate(?:\s+this)?(?:\s+(?:into|to)\s+(?:English|Chinese))?)",
    re.IGNORECASE,
)

PURE_TRANSFORM_MIXED_TAIL_PATTERN = re.compile(
    r"(?:翻译|转换|整理|排版|格式化)(?:完成|完|之后|以后|后).{0,12}"
    r"(?:告诉|分析|判断|解释|诊断|建议|评价|评估|解读|推测|推断|说明)|"
    r"(?:再|同时|并且|另外|还要|然后)(?:帮我)?"
    r"(?:告诉|分析|判断|解释|诊断|建议|评价|评估|解读|推测|推断|说明)|"
    r"(?:另问|补问|再问|另外问|还有一个问题)\s*[：:]?|"
    r"(?:请|请你|麻烦你|帮我|请帮我|再)?\s*"
    r"(?:核实|验证|查证)(?:一下)?\s*"
    r"(?:这|该|其|信息|内容|说法|消息|来源|出处|真伪|真实性)?|"
    r"(?:请|请你|麻烦你|帮我|请帮我|再)?\s*"
    r"(?:判断|辨别|判定)(?:一下)?\s*"
    r"(?:这|该|其|内容|说法|消息)?(?:真假|真伪|是否属实|是否真实)|"
    r"(?:请|请你|麻烦你|帮我|请帮我|再)?\s*"
    r"(?:解释|解读)(?:一下)?\s*"
    r"(?:这|该|其|内容|说法|消息|句子)?(?:的)?(?:含义|意思|意味着什么)|"
    r"(?:[；;。.!！？?\n]|[，,])\s*"
    r"(?:请|请你|麻烦你|帮我|请帮我|再)?\s*"
    r"(?:看看|看一看|确认(?:一下)?|查(?:一下)?|核对(?:一下)?|"
    r"告诉我|分析(?:一下)?|判断(?:一下)?|核实(?:一下)?|验证(?:一下)?|"
    r"查证(?:一下)?|评估(?:一下)?|解读(?:一下)?)"
    r".{0,28}(?:是不是实话|是否属实|是否真实|真不真实|是真是假|"
    r"靠不靠谱|可不可靠|是否可信|能不能信|值不值得信|"
    r"来源|出处|来路|可信度|真实性|真伪|"
    r"到底想干嘛|为什么这么做|真实动机|动机|目的)|"
    r"(?:[；;。.!！？?\n]|[，,])\s*"
    r"(?:顺便|顺带|另外|同时|然后|再)?\s*"
    r"(?:(?:说说|看看|看一看|确认(?:一下)?|查(?:一下)?|核对(?:一下)?|"
    r"告诉我|分析(?:一下)?|判断(?:一下)?|评判(?:一下)?|评估(?:一下)?|"
    r"核实(?:一下)?|验证(?:一下)?|查证(?:一下)?|解读(?:一下)?)"
    r".{0,28}(?:真不真|是不是真的|是不是实话|是否属实|是否真实|"
    r"真假|真伪|靠不靠谱|可不可靠|是否可靠|是否可信|能不能信|"
    r"可信程度|可信度|真实性|是否经得起推敲|经不经得起推敲|"
    r"来源|出处|来路|意图|用意|真实动机|动机|目的)|"
    r"(?:这|该)?(?:句|段)?(?:话|内容|消息|说法)"
    r".{0,8}(?:靠谱吗|可靠吗|可信吗|是真的吗|属实吗|能信吗))|"
    r"(?:[;；.!?\n]\s*)(?:please\s+)?(?:also\s+|then\s+)?"
    r"(?:assess|evaluate|judge|determine|analy[sz]e|verify|check)\s+"
    r"(?:whether|if)\s+(?:the|this|that)?\s*"
    r"(?:claim|statement|message|source|story)\s+(?:is\s+)?"
    r"(?:credible|reliable|true|accurate|authentic|trustworthy|real)\b|"
    r"\b(?:and|also|then)\s+(?:help\s+me\s+)?(?:tell|explain|analy[sz]e|judge|"
    r"diagnose|advise|infer|evaluate|assess|interpret|decide)\b|"
    r"\b(?:in\s+real\s+life|in\s+reality|actually|not\s+fictional|"
    r"this\s+is\s+not\s+an?\s+example|this\s+is\s+real)\b|"
    r"\b(?:outside\s+the\s+(?:quote|script|example)|unquoted\s+update|"
    r"reality\s+update|separate\s+issue|this\s+is\s+not\s+hypothetical)\b|"
    r"\btraining\s+scenario\s+complete\s*[.;:]?\s*now\b|"
    r"(?:现实中|现实里|回到现实|说回现实|真实求救|现实求救|"
    r"正在发生|这不是例句|不是例句|并非例句)|"
    r"(?:另外|顺便说|顺便补充)[，,]?\s*"
    r"(?:我|本人|他|她|前任|对方|有人|孩子).{0,20}"
    r"(?:现在|正在|正|刚|吞了|吞下|拿刀|持刀|被困|意识模糊)|"
    r"\blater\s*[;；]\s*first\b",
    re.IGNORECASE,
)

PURE_FORMATTING_PATTERNS = (
    re.compile(
        r"^\s*(?:请|请你|麻烦你|帮我|请帮我)?\s*"
        r"(?:整理(?:一下)?(?:他|她|对方|老板|同事|朋友)说的|"
        r"给这句(?:已经|已)?标注来源的话改(?:一下)?格式|"
        r"按时间线整理这条(?:已经|已)?有来源的事件)\s*[:：]\s*"
        r"(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*只(?:整理格式|改格式|排版)\s*[，,]\s*"
        r"(?:不|不要|不做|不需要|无需)分析(?:内容)?\s*[。.!！]\s*"
        r"(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:请|请你|麻烦你|帮我|请帮我)?\s*"
        r"(?:只\s*)?(?:重新)?(?:改(?:一下)?格式|整理|格式化|排版)(?:一下)?\s*"
        r"(?:这句(?:话)?|原文|文本|内容)?\s*[:：]\s*"
        r"(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:请|请你|麻烦你|帮我|请帮我)?\s*(?:把|将)\s*"
        r"(?:这(?:一)?句(?:话)?|原文|文本|内容)?\s*"
        r"(?P<payload>[“‘\"「『].+?[”’\"」』])\s*"
        r"(?:加粗|分成两行|断成两行|改成项目符号(?:列表)?|"
        r"整理|格式化|(?:重新)?排版)(?:一下)?[。！？!?]?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:请|请你|麻烦你|帮我|请帮我)?\s*把\s*"
        r"(?:这句(?:话)?|原文|文本|内容)\s*"
        r"(?P<payload>[“‘\"「『].+?[”’\"」』])\s*"
        r"(?:整理|格式化|排版)(?:一下)?[。！？!?]?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:请|请你|麻烦你|帮我|请帮我)?\s*把\s*"
        r"(?:下面|以下)?\s*(?:这(?:一)?句(?:话)?|这段(?:话)?|"
        r"急救手册标题|电影字幕|法律案例摘要|这句法律案例摘要|下面三项)\s*"
        r"(?:加粗|改成项目符号|改成三级标题|断成两行|"
        r"整理成表格|改成被动句)"
        r"\s*(?:[，,]\s*(?:不要分析|只改格式))?\s*[:：]\s*"
        r"(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:请|请你|麻烦你|帮我|请帮我)?\s*把\s*"
        r"(?:下面|以下)(?:三项|内容|文字|文本)?\s*"
        r"(?:整理成|转换成|改成|排成)\s*"
        r"(?:表格|Markdown(?:\s+格式)?|JSON|CSV|时间线)\s*[:：]\s*"
        r"(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:请|请你|麻烦你|帮我|请帮我)?\s*"
        r"(?:只\s*)?纠正\s*(?:这(?:一)?句)?(?:法律案例摘要)?(?:的)?标点\s*[:：]\s*"
        r"(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*Put\s+(?:this|the following)\s+(?:sentence|text)\s+in\s+"
        r"(?:a\s+)?Markdown\s+blockquote\s*:\s*(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*Convert\s+to\s+CSV(?:\s+with\s+one\s+item\s+per\s+row)?"
        r"\s*:\s*(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*Alphabetize\s+(?:these|the following)\s+labels\s+only"
        r"\s*:\s*(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*Change\s+(?:this|the following)\s+screenplay\s+direction\s+to\s+uppercase"
        r"\s*:\s*(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*Proofread\s+(?:this|the following)\s+sentence\s+from\s+(?:a|the)\s+novel"
        r"\s*:\s*(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*Return\s+valid\s+JSON\s+with\s+one\s+field\s+named\s+"
        r"[A-Za-z_][A-Za-z0-9_]*\s*:\s*(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:请|请你|麻烦你|帮我|请帮我)?\s*(?:把|将)\s*"
        r"(?P<payload>[“‘\"']?.+?[”’\"']?)\s*"
        r"(?:改成项目符号(?:列表)?|改写为问句|压缩成(?:十|\d+)个字以内|"
        r"转成繁体中文|转换成繁体中文|整理成两列表格|改成两列表格)"
        r"\s*[。.!！]?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:Convert\s+to\s+title\s+case|Rewrite\s+as\s+JSON\s+keys\s+only|"
        r"Remove\s+punctuation|"
        r"Make\s+lowercase|Turn\s+into\s+a\s+two-column\s+table)"
        r"\s*:\s*(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*Convert\s+(?P<payload>.+?)\s+to\s+ISO\s+date\s+format"
        r"\s*[.!]?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:请|请你|麻烦你|帮我|请帮我)?\s*(?:把|将)\s*"
        r"(?:这(?:一)?句(?:话)?|下面内容|以下内容)\s*"
        r"(?:转成|转换成)\s*繁体中文\s*[:：]\s*(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:把|将)(?:下面|以下)?(?:内容)?\s*"
        r"(?:转成|转换成|改成|整理成)\s*(?:YAML|JSON)\s*[:：]\s*"
        r"(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:原文(?:如下)?\s*[:：]\s*)?"
        r"(?P<payload>[“‘\"「『].+?[”’\"」』])\s*[，,]\s*"
        r"(?:请|请你|麻烦你|帮我|请帮我)?\s*(?:只\s*)?"
        r"(?:改(?:一下)?格式|重新排版|排版(?:一下)?|格式化(?:一下)?|加粗)"
        r"[。！？!?]?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:请|请你|麻烦你|帮我|请帮我)?\s*"
        r"(?:给|把|将)\s*(?:这(?:一)?句(?:话)?|这段(?:话)?|原文|文本|内容)?\s*"
        r"(?P<payload>[“‘\"「『].+?[”’\"」』])\s*"
        r"(?:加粗|拆成两行|分成两行|断成两行|重新排版|排版(?:一下)?|"
        r"改(?:一下)?格式|格式化(?:一下)?)"
        r"[。！？!?]?\s*$",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:请|请你|麻烦你|帮我|请帮我)?\s*"
        r"(?:做(?:一下)?|进行(?:一下)?)\s*(?:重新)?(?:排版|格式化)\s*"
        r"[:：]\s*(?P<payload>.+?)\s*$",
        re.IGNORECASE,
    ),
)


def _affirmative_translation_operations(text: str) -> list[re.Match[str]]:
    """Return translation operations that are not locally negated."""
    matches: list[re.Match[str]] = []
    for match in AFFIRMATIVE_TRANSLATION_OPERATION_PATTERN.finditer(text):
        prefix = text[max(0, match.start() - 16) : match.start()]
        local = prefix + match.group(0)
        if NEGATED_TRANSLATION_INTENT_PATTERN.search(local):
            continue
        matches.append(match)
    return matches


def _translation_payload_is_pure(
    payload: str, *, allow_embedded_quote: bool = False
) -> bool:
    """Reject material outside one translation operand or operand group."""
    value = payload.strip()
    if not value:
        return False
    if PURE_TRANSFORM_MIXED_TAIL_PATTERN.search(value):
        return False
    quote_ranges = _actual_quote_ranges(value)
    if quote_ranges:
        for left, right in zip(quote_ranges, quote_ranges[1:]):
            if not _connected_transform_quote_gap(
                value, left[1], right[0]
            ):
                return False
        if not allow_embedded_quote:
            suffix = value[quote_ranges[-1][1] + 1 :]
            if not re.fullmatch(
                r"\s*(?:都|一并|分别)?\s*[。.!！]?\s*", suffix
            ):
                return False
        else:
            suffix = value[quote_ranges[-1][1] + 1 :]
            suffix = re.sub(
                r"^\s*(?:into|to)\s+(?:English|Chinese)\s*",
                "",
                suffix,
                flags=re.IGNORECASE,
            )
            if re.match(r"^\s*[，,；;。.!！？]\s*\S", suffix):
                return False
    return True


def pure_translation_payload(text: str) -> str | None:
    """Return the sole payload of an affirmative, pure translation request.

    This recognizes intent and ownership structurally.  It does not infer
    purity merely because a request contains the word ``翻译``: unrelated
    reality clauses, analysis tasks, and negated translation intentions stay
    outside the owned payload and therefore remain visible to safety routing.
    """
    value = text.strip()
    value = re.sub(
        r"^\s*(?:现实中|现实里|实际情况中)?\s*"
        r"(?:没有|不存在)(?:任何)?(?:现实)?(?:危险|风险)\s*[；;]\s*",
        "",
        value,
        count=1,
    )
    if not value or NEGATED_TRANSLATION_INTENT_PATTERN.search(value):
        return None
    operations = _affirmative_translation_operations(value)
    if len(operations) != 1:
        return None
    operation = operations[0]

    prefix = re.fullmatch(
        r"\s*(?:请|请你|麻烦你|帮我|请帮我|please)?\s*(?:只\s*)?"
        r"(?:(?:英文|英语|中文)\s*翻译|"
        r"(?:English|Chinese)\s+translation(?=\s*[:：])|"
        r"translation\s+(?:into|to)\s+(?:English|Chinese)(?=\s*[:：])|"
        r"(?:逐字翻译|翻译(?:成|为)?)(?:英文|英语|中文)?|"
        r"译(?:成|为)(?:英文|英语|中文)|"
        r"translate(?:\s+this)?(?:\s+(?:into|to)\s+(?:English|Chinese))?)"
        r"\s*[:：]?\s*(?P<payload>.+?)\s*",
        value,
        re.IGNORECASE,
    )
    if prefix is not None:
        payload = prefix.group("payload").strip().strip("。")
        return (
            payload
            if _translation_payload_is_pure(payload, allow_embedded_quote=True)
            else None
        )

    described_prefix = re.fullmatch(
        r"\s*(?:请|请你|麻烦你|帮我|请帮我)?\s*(?:把|将)\s*"
        r"(?:下面|以下)?\s*(?:这(?:一)?句(?:话)?|(?:以下)?虚构台词|小说台词|电影字幕|"
        r"剧本台词|例句|标题|文本|文字)\s*"
        r"(?:逐字翻译|翻译(?:成|为)?|翻成|译(?:成|为))(?:英文|英语|中文)?"
        r"\s*[:：]\s*(?P<payload>.+?)\s*",
        value,
        re.IGNORECASE,
    )
    if described_prefix is not None:
        payload = described_prefix.group("payload").strip().strip("。")
        return (
            payload
            if _translation_payload_is_pure(payload, allow_embedded_quote=True)
            else None
        )

    deictic_prefix = re.fullmatch(
        r"\s*(?:请|请你|麻烦你)?\s*(?:把|将)\s*这句\s*"
        r"(?:翻译(?:成|为)?|译(?:成|为))"
        r"(?:英文|英语|中文)\s*[:：]?\s*(?P<payload>.+?)\s*",
        value,
        re.IGNORECASE,
    )
    if deictic_prefix is not None:
        payload = deictic_prefix.group("payload").strip().strip("。")
        return payload if _translation_payload_is_pure(payload) else None

    object_first = re.fullmatch(
        r"\s*(?:请|请你|麻烦你)?\s*(?:把|将)\s*"
        r"(?P<payload>.+?)\s*"
        r"(?:翻译(?:成|为)?(?:英文|英语|中文)?|翻成(?:英文|英语|中文)?|"
        r"译(?:成|为)(?:英文|英语|中文)|"
        r"translate(?:\s+this)?(?:\s+(?:into|to)\s+(?:English|Chinese))?)"
        r"\s*[。.!！]?\s*",
        value,
        re.IGNORECASE,
    )
    if object_first is not None:
        payload = object_first.group("payload").strip()
        return payload if _translation_payload_is_pure(payload) else None

    postfix = re.fullmatch(
        r"\s*(?P<payload>.+?)\s*(?:[，,。.!！]|\n)\s*"
        r"(?:请|请你|麻烦你|帮我|请帮我)?\s*"
        r"(?:翻译(?:成|为)?(?:英文|英语|中文)?|"
        r"译(?:成|为)(?:英文|英语|中文)|"
        r"translate(?:\s+this)?(?:\s+(?:into|to)\s+(?:English|Chinese))?)"
        r"\s*[。.!！]?\s*",
        value,
        re.IGNORECASE,
    )
    if postfix is not None:
        payload = postfix.group("payload").strip()
        return payload if _translation_payload_is_pure(payload) else None

    # A bare prefix request such as “请翻译‘你好’” has no colon but still
    # owns exactly the suffix following the operation.
    if operation.start() <= 8:
        leading = value[: operation.start()]
        if re.fullmatch(r"\s*(?:请|请你|麻烦你|帮我|请帮我)?\s*", leading):
            payload = value[operation.end() :].strip().strip("。")
            if payload and _translation_payload_is_pure(payload):
                return payload
    return None


def is_pure_translation_task(text: str) -> bool:
    return pure_translation_payload(text) is not None


def pure_formatting_payload(text: str) -> str | None:
    """Return the sole operand of a finite formatting-only request."""
    value = text.strip()
    if not value or PURE_TRANSFORM_MIXED_TAIL_PATTERN.search(value):
        return None
    for pattern in PURE_FORMATTING_PATTERNS:
        match = pattern.fullmatch(value)
        if match is None:
            continue
        payload = match.group("payload").strip()
        if payload and not PURE_TRANSFORM_MIXED_TAIL_PATTERN.search(payload):
            return payload
    return None


def parse_pure_transform_task(text: str) -> dict[str, str] | None:
    """Parse one closed transform instruction and its fully owned operand.

    The returned finite ``kind`` is the routing decision.  A request with an
    unowned second task, a reality override, or a scheduling connector is not
    a pure transform and remains visible to ordinary and safety routing.
    """
    translation = pure_translation_payload(text)
    if translation is not None:
        return {"kind": "translation", "payload": translation}
    formatting = pure_formatting_payload(text)
    if formatting is not None:
        return {"kind": "formatting", "payload": formatting}
    return None
REALITY_SCOPE_RESET_PATTERN = re.compile(
    r"^\s*(?:(?:但|可是|不过|然而)\s*)?"
    r"(?:(?:顺便说一句|另外补充(?:一句)?|补充一句|回到正题)\s*[，,：:]?\s*)?"
    r"(?:回到现实|说回现实|现实(?:中|里|世界|生活中)|"
    r"实际情况(?:是|为)|现实情况(?:是|为)|实际上)"
)
NONFICTION_SCOPE_RESET_PATTERN = re.compile(
    r"^\s*(?:(?:但|可是|不过|然而)\s*)?"
    r"(?:(?:顺便说一句|另外补充(?:一句)?|补充一句|回到正题)\s*[，,：:]?\s*)?"
    r"(?:(?:这|这段|以下|下面|上面|前文|该内容|这个内容)\s*)?"
    r"(?:(?:不是|并非)(?:一部|在拍|在演|来自)?"
    r"(?:电影|小说|剧本|游戏|桌游|角色扮演|歌词|例句|翻译素材|正则测试)|"
    r"(?:别|不要|不能)当成(?:一部)?"
    r"(?:电影|小说|剧本|游戏|桌游|角色扮演|歌词|例句|翻译素材|正则测试))",
    re.IGNORECASE,
)
NONREAL_SCOPE_END_PATTERN = re.compile(
    r"^\s*(?:(?:以上|前述|这段|该段)\s*)?"
    r"(?:电影|小说|故事|剧本|游戏|歌词|台词|例句|翻译素材|"
    r"正则测试|regex|测试字符串|测试用例|测试文本|测试输入|测试样例)"
    r"(?:部分|片段|内容|段落)?(?:到这里|在此|已经|现已)?"
    r"(?:结束|结束了|完毕|完结)\s*[。！？；，,：:]?\s*",
    re.IGNORECASE,
)
NONREAL_CONTINUATION_PATTERN = re.compile(
    r"^\s*(?:后记|番外|尾声)\s*[：:]?\s*"
    r"(?:角色|主人公|人物|男主|女主|他|她)?",
)
POSTFIX_SECONDHAND_ATTRIBUTION_PATTERN = re.compile(
    r"(?:这|这一点|这个消息|消息|信息|来源).{0,10}"
    r"(?:同事|朋友|同学|室友|别人|有人|领导|经理|主管|上司|HR|人事|"
    r"秘书|家人|客户|老师|医生|律师|小[一-鿿A-Za-z0-9]{1,3}).{0,10}"
    r"(?:转告|转述|转达(?:给我)?|传话(?:给我)?|透露(?:给我)?|告诉|所述|提供|说|讲|来自)|"
    r"(?:我)?(?:是|只是)?(?:听|从).{0,12}"
    r"(?:同事|朋友|同学|室友|别人|有人|领导|经理|主管|上司|HR|人事|"
    r"秘书|家人|客户|老师|医生|律师|小[一-鿿A-Za-z0-9]{1,3}).{0,12}"
    r"(?:才)?(?:知道|得知|获悉|听说|听到|了解到)|"
    r"(?:这一点|这件事|这个消息)?.{0,8}(?:没有|没|未)亲眼(?:看到|看见).{0,16}"
    r"(?:转告|转述|告诉|说|讲)|"
    r"(?:我)?(?:是)?从(?:同事|朋友|同学|室友|别人|有人|领导|经理|主管|上司|"
    r"HR|人事|秘书|家人|客户|老师|医生|律师|小[一-鿿A-Za-z0-9]{1,3})"
    r"(?:那里|那儿|处)?(?:听来|听到|得知|获悉)(?:的|来的)?|"
    r"(?:这个)?消息(?:是)?来自(?:同事|朋友|同学|室友|别人|有人|领导|经理|主管|上司|"
    r"HR|人事|秘书|家人|客户|老师|医生|律师|小[一-鿿A-Za-z0-9]{1,3})|"
    r"(?:我)?(?:是)?通过(?:同事|朋友|同学|室友|别人|有人|领导|经理|主管|上司|"
    r"HR|人事|秘书|家人|客户|老师|医生|律师|小[一-鿿A-Za-z0-9]{1,3})"
    r"(?:才)?(?:知道|得知|获悉|听说|了解到)(?:的|来的)?|"
    r"(?:消息)?来源\s*(?:是|为|来自)\s*"
    r"(?:同事|朋友|同学|室友|别人|有人|领导|经理|主管|上司|HR|人事|"
    r"秘书|家人|客户|老师|医生|律师|小[一-鿿A-Za-z0-9]{1,3})|"
    r"(?:这|这是|这句(?:话)?|这段(?:话|原话)?|上述原话|前述原话)?.{0,10}"
    r"(?:邮件|短信|消息|群聊|聊天记录|录音|语音|文档|附件).{0,12}"
    r"(?:转告|转述|转达|传话|代传|间接传来|所述)"
)
CROSS_SENTENCE_QUOTE_SECONDHAND_PATTERN = re.compile(
    r"^[”’\"']?\s*[。！？；]\s*"
    r"(?:这句(?:话)?|该引语|上述原话|前述原话|这段(?:话|原话))"
    r".{0,16}(?:是|来自|由|属于)?\s*"
    r"(?:同事|朋友|同学|室友|别人|有人|领导|经理|主管|上司|HR|人事|"
    r"秘书|家人|客户|老师|医生|律师|小[一-鿿A-Za-z0-9]{1,3})"
    r".{0,12}(?:转告|转述|转达|传话|透露|告诉|提供|说|讲)",
)
NESTED_REPORTING_CHAIN_PATTERN = re.compile(
    r"[一-鿿A-Za-z0-9_]{1,18}(?:告诉|转告|转述|告知)我[，,:：\s]+"
    r"[一-鿿A-Za-z0-9_]{1,18}(?:说|表示|称|回复|回答)\s*[:：]?\s*[“‘\"「『']?|"
    r"(?:我听)?[一-鿿A-Za-z0-9_]{1,18}(?:提过|回忆|转述|说过)[，,:：\s]+"
    r"[一-鿿A-Za-z0-9_]{1,18}(?:说|表示|称|回复|回答)\s*[:：]?\s*[“‘\"「『']?|"
    r"(?:群里(?:传来)?消息|消息).{0,8}(?:说|称)[，,:：\s]+"
    r"[一-鿿A-Za-z0-9_]{1,18}(?:说|表示|称|回复|回答)\s*[:：]?\s*[“‘\"「『']?|"
    r"(?:中间人|传话人|秘书).{0,12}(?:代为带话|带话|捎话|传话|转告|转述|转达)[，,:：\s]+"
    r"[一-鿿A-Za-z0-9_]{1,18}(?:说|表示|称|回复|回答)\s*[:：]?\s*[“‘\"「『']?|"
    r"(?:从|经由|通过).{0,8}(?:秘书|中间人|传话人).{0,8}"
    r"(?:口中)?(?:转了一道|带话|捎话|传话|转告|转述|转达)[，,:：\s]+"
    r"[一-鿿A-Za-z0-9_]{1,18}(?:说|表示|称|回复|回答)\s*[:：]?\s*[“‘\"「『']?"
)
PREFIX_ARTIFACT_ATTRIBUTION_PATTERN = ARTIFACT_ATTRIBUTION_PATTERN
POSTFIX_ARTIFACT_ATTRIBUTION_PATTERN = re.compile(
    r"(?:这|这是|这个消息|消息|信息|来源)?.{0,20}"
    r"(?:群消息|群聊消息|项目群公告|群公告|系统消息|聊天记录|短信|邮件|通知|公告)"
    r".{0,16}(?:告诉|显示|写明|注明|通知|发送|发出|发布)"
)

# A recognized event may still be followed by a non-observational predicate.
# This pattern describes the grammatical boundary, not the story conclusion:
# intentions, purposes, character assessments, and diagnostic attributions
# must remain outside observable_fact even when an event verb appears first.
NON_OBSERVATIONAL_PREDICATE_PATTERN = re.compile(
    r"(?:图谋|企图|意图|意欲|打算|谋求|旨在|目的在于|奔着|冲着).{1,24}|"
    r"(?:呈现|显露|暴露出|反映|体现|表现出|足见).{1,24}"
)

# Observable facts are parsed with finite surface grammars.  A marker appearing
# somewhere in a sentence is not enough: one rule must consume the complete
# non-punctuation text.  This prevents an open-ended story predicate after a
# real event from inheriting the event's fact label.
_OBSERVATION_PERSON = (
    r"(?:我|你|他|她|对方|老板|经理|同事|前任|公司|HR|人事|"
    r"财务系统|审批系统|系统)"
)
_OBSERVATION_DURATION = (
    r"(?:[0-9一二三四五六七八九十两半]+)(?:分钟|个?小时|天|周|个月)"
)
_OBSERVATION_TIME = (
    rf"(?:今天|昨天|刚才|刚刚|最近|本月|这周|本周|"
    rf"周[一二三四五六日天](?:\s*[0-9]{{1,2}}:[0-9]{{2}})?|"
    rf"{_OBSERVATION_DURATION}|连续[0-9一二三四五六七八九十两]+次)"
)
_OBSERVATION_SEQUENCE = (
    r"(?:随后|后来|之后|接着|然后|同时|而且|并且|另外|、|临时|连续|接连|先后|总共|累计|"
    r"曾经|曾|又|仍|已经|先|刚|并)"
)
_OBSERVATION_PREFIX = (
    rf"(?:(?:第[0-9一二三四五六七八九十]+轮[:：])?\s*)?"
    rf"(?:(?:{_OBSERVATION_TIME}|{_OBSERVATION_SEQUENCE})\s*)*"
    rf"(?:{_OBSERVATION_PERSON}\s*)?"
    rf"(?:(?:{_OBSERVATION_TIME}|{_OBSERVATION_SEQUENCE})\s*)*"
)
_OBSERVATION_EVENT = (
    r"(?:会议|约会|项目会|决策会|例会|周会|活动|见面|汇报|讨论)"
)
_OBSERVATION_EVENT_DAY = (
    r"(?:(?:今天|明天|后天|本周|这周|下周|"
    r"周[一二三四五六日天])的?)?"
)
_OBSERVATION_DESCRIBED_EVENT = (
    rf"(?:岗位说明中写明[“‘][^”’\n]{{1,48}}[”’]的)?{_OBSERVATION_EVENT}"
)
_OBSERVATION_QUOTE = r"(?:[“‘][^”’\n]{1,80}[”’])"
_OBSERVATION_REPLY_ABSENCE = r"(?:没有回复|未回复|没回复|没有回|没回)"
_OBSERVATION_MESSAGE_OBJECT = (
    r"(?:(?:我的|你的|他的|她的|对方的)?(?:消息|邮件)|我|你|他|她|对方)?"
)
_OBSERVATION_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "negative_report_event",
        re.compile(
            rf"^{_OBSERVATION_PREFIX}(?:"
            rf"(?:(?:从来)?(?:没有|没|未)|从未|不曾|未曾)"
            rf"(?:亲口|当面|明确|真的|实际)?(?:说|讲|表示|提)(?:过)?"
            rf"(?:要(?:开除|辞退|撤掉|换掉)(?:我|你|他|她|对方)|"
            rf"(?:自己)?(?:现在)?是什么感受|任何新信息|{_OBSERVATION_QUOTE})|"
            rf"(?:没有|没|未)解释(?:具体)?原因"
            rf")"
        ),
    ),
    (
        "communication_event",
        re.compile(
            rf"^{_OBSERVATION_PREFIX}(?:"
            rf"(?:(?:看了?|已读)(?:我发的)?(?:消息|邮件)(?:后)?"
            rf"(?:{_OBSERVATION_DURATION})?(?:还|一直)?{_OBSERVATION_REPLY_ABSENCE}"
            rf"{_OBSERVATION_MESSAGE_OBJECT})|"
            rf"(?:(?:{_OBSERVATION_DURATION})?(?:还|一直)?{_OBSERVATION_REPLY_ABSENCE}"
            rf"{_OBSERVATION_MESSAGE_OBJECT})|"
            rf"(?:发(?:来|了)?邮件通知(?:我|你|他|她|对方)?"
            rf"(?:会议|约会|项目会|决策会)(?:取消|改期))|"
            rf"(?:(?:给(?:我|你|他|她|对方))?"
            rf"(?:打了|打过|拨打了)(?:一通)?电话)|"
            rf"(?:(?:给(?:我|你|他|她|对方))?"
            rf"(?:(?:发来|发送|发了|回复|收到|通知|告诉)(?:了)?"
            rf"(?:我|你|他|她|对方|一封(?:节日)?(?:放假|升职|会议|项目)?(?:通知|邮件)|"
            rf"一条(?:消息|回复)|一张(?:截图|照片)|当天维修单|维修单|"
            rf"(?:节日)?放假通知|升职邮件|会议通知|项目通知|消息|邮件|通知|回复|原话)?|"
            rf"发(?:了)?(?:一封(?:通知|邮件)|一条(?:消息|回复)|一张(?:截图|照片)|"
            rf"(?:放假|升职|会议|项目)?(?:通知|邮件)|消息|邮件|通知|回复|原话)))"
            rf")"
        ),
    ),
    (
        "participation_or_schedule_event",
        re.compile(
            rf"^{_OBSERVATION_PREFIX}(?:"
            rf"(?:(?:没有|没|未)(?:被)?(?:让|邀请)?(?:我|你|他|她|对方)?参加"
            rf"{_OBSERVATION_DESCRIBED_EVENT})|"
            rf"(?:取消(?:了)?{_OBSERVATION_EVENT_DAY}"
            rf"(?:我的|你的|他的|她的|对方的)?{_OBSERVATION_EVENT})|"
            rf"(?:(?:[0-9一二三四五六七八九十两]+次(?:都)?)?"
            rf"取消(?:了|过)?(?:[0-9一二三四五六七八九十两]+次)?"
            rf"(?:我的|你的|他的|她的|对方的)?{_OBSERVATION_EVENT})|"
            rf"(?:(?:把)?(?:我的|你的|他的|她的|对方的)?{_OBSERVATION_EVENT}"
            rf"取消(?:了|过)?[0-9一二三四五六七八九十两]+次)|"
            rf"(?:(?:我的|你的|他的|她的|对方的)?{_OBSERVATION_EVENT}"
            rf"被(?:我|你|他|她|对方|老板|经理|同事|前任)"
            rf"取消(?:了|过)?(?:[0-9一二三四五六七八九十两]+次)?)|"
            rf"(?:[0-9一二三四五六七八九十两]+次"
            rf"(?:我的|你的|他的|她的|对方的)?{_OBSERVATION_EVENT}"
            rf"(?:均|都)?被(?:我|你|他|她|对方|老板|经理|同事|前任)"
            rf"取消(?:了|过)?)|"
            rf"(?:(?:把)?[0-9一二三四五六七八九十两]+次"
            rf"(?:我的|你的|他的|她的|对方的)?{_OBSERVATION_EVENT}"
            rf"(?:我|你|他|她|对方)?(?:都)?取消(?:了|过)?)|"
            rf"(?:参加(?:了|过)(?:我的|你的|他的|她的|对方的)?"
            rf"{_OBSERVATION_DESCRIBED_EVENT})|"
            rf"(?:参加了)|"
            rf"(?:(?:把)?(?:我|你|他|她|对方)(?:移出|移除|排除在)(?:了)?"
            rf"(?:我的|你的|他的|她的|对方的)?{_OBSERVATION_EVENT}(?:之外)?)|"
            rf"(?:迟到(?:了)?)|"
            rf"(?:(?:把)?(?:会议|约会|项目会|决策会|例会|周会)(?:改到|改期到?)"
            rf"(?:(?:今天|明天|后天)|(?:(?:本|这|下)?周[一二三四五六日天]))?"
            rf"(?:上午|下午|晚上|中午)?"
            rf"[0-9一二三四五六七八九十两]+点(?:半|[0-9一二三四五六七八九十]+分)?)"
            rf")"
        ),
    ),
    (
        "participation_or_schedule_event",
        re.compile(
            rf"^{_OBSERVATION_PREFIX}"
            rf"(?:会议|约会|项目会|决策会|例会|周会)(?:已)?定在"
            rf"(?:(?:今天|明天|后天)|(?:(?:本|这|下)?周[一二三四五六日天]))"
            rf"(?:上午|下午|晚上|中午)?"
            rf"[0-9一二三四五六七八九十两]+点(?:半|[0-9一二三四五六七八九十]+分)?"
        ),
    ),
    (
        "task_or_action_event",
        re.compile(
            rf"^{_OBSERVATION_PREFIX}(?:"
            rf"(?:(?:没有|没|未)?(?:完成|做完)(?:了)?"
            rf"(?:任何一项|一项|这次|本轮|今天|本周|当前)?"
            rf"(?:计划|任务|目标|工作))|"
            rf"(?:(?:把)?(?:我的|你的|他的|她的|对方的)?(?:工位|文档|文件|消息|记录)"
            rf"(?:删除|删掉|删了|搬走|搬了)(?:了)?)|"
            rf"(?:(?:删除|删掉|删了|拉黑|屏蔽)(?:了)?"
            rf"(?:我|你|他|她|对方|文档|文件|消息|记录))|"
            rf"(?:(?:把)?(?:我|你|他|她|对方)从(?:好友列表|通讯录|群聊)"
            rf"(?:删除|删掉|移除)(?:了)?)|"
            rf"(?:亲眼(?:看到|看见)(?:了)?(?:他|她|对方|老板|同事)"
            rf"(?:(?:把)?(?:我的|你的|他的|她的|对方的)?(?:文档|文件|消息|记录)"
            rf"(?:删除|删掉|删了)(?:了)?|"
            rf"(?:删除|删掉|删了)(?:了)?(?:文档|文件|消息|记录)))|"
            rf"(?:(?:手机|电脑|设备)?(?:送修|拿回来))|"
            rf"(?:(?:砸过|砸了|打了|关了|开了|扔了|摔了)(?:我的|你的|他的|她的)?"
            rf"(?:门|东西|文件|设备))|"
            rf"(?:(?:离开|到了|带来|推了)(?:公司|家|现场)?)"
            rf")"
        ),
    ),
    (
        "artifact_or_system_state",
        re.compile(
            rf"^{_OBSERVATION_PREFIX}(?:"
            rf"(?:打开(?:了)?(?:项目)?日历)|"
            rf"(?:(?:登录(?:了)?(?:项目|财务)?系统(?:时)?)?(?:发现)?"
            rf"(?:审批|访问)?权限(?:已经|仍然|当前)?(?:失效|有效|保留|取消))|"
            rf"(?:显示(?:我的|你的|他的|她的|对方的)?(?:审批|访问)?权限"
            rf"(?:已被|已经|仍然|当前)?(?:失效|有效|保留|取消))|"
            rf"(?:显示(?:我的|你的|他的|她的|对方的)?(?:审批|审核)"
            rf"(?:已经|已)?(?:通过|拒绝|驳回))|"
            rf"(?:(?:没有看到|未看到)(?:自己的|我的|你的|他的|她的)?"
            rf"(?:名字|姓名|权限|记录|安排))|"
            rf"(?:(?:项目)?日历里(?:没有|没)(?:自己的|我的|你的|他的|她的)?"
            rf"(?:名字|姓名|安排))|"
            rf"(?:允许(?:我|你|他|她|对方)审批(?:该|这个|本次|当前)?项目预算)|"
            rf"(?:(?:我的|你的|他的|她的)?(?:职责和)?权限(?:没有变化|保持不变))|"
            rf"(?:给我的书面职责确认(?:仍)?写着{_OBSERVATION_QUOTE})|"
            rf"(?:保留(?:预算)?审批职责)"
            rf")"
        ),
    ),
)
_OBSERVATION_TRAILING_PUNCTUATION = re.compile(r"[\s。！；，,:：]*")


def parse_observation_prefix(value: str) -> tuple[str, int] | None:
    """Return the longest finite observation prefix without accepting a tail."""
    candidates: list[tuple[str, int]] = []
    for observation_type, pattern in _OBSERVATION_RULES:
        match = pattern.match(value)
        if match is not None:
            candidates.append((observation_type, match.end()))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[1])


def _observation_parse_consumes_full_value(value: str, end: int) -> bool:
    # A question is not converted into an observed event merely because its
    # proposition happens to match the finite observation grammar.
    if "?" in value[end:] or "？" in value[end:]:
        return False
    return bool(_OBSERVATION_TRAILING_PUNCTUATION.fullmatch(value[end:]))


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_bytes(data: Any) -> bytes:
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def canonical_sha256(data: Any) -> str:
    return sha256_bytes(canonical_bytes(data))


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_write_json(path: Path, data: Any) -> None:
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def error(code: str, path: str, message: str) -> dict[str, str]:
    return {"code": code, "path": path, "message": message}


def _trusted_legacy_attestations() -> tuple[dict[str, set[str]], str | None]:
    """Load the release-bound allowlist for legacy artifacts and receipts."""
    try:
        corpus = read_json(TRUSTED_LEGACY_CORPUS_PATH)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return {}, f"cannot load trusted legacy corpus: {exc}"
    if (
        not isinstance(corpus, dict)
        or corpus.get("schema_version") != "1.0.0"
        or not isinstance(corpus.get("entries"), list)
    ):
        return {}, "trusted legacy corpus has an invalid top-level contract"

    attestations: dict[str, set[str]] = {}
    for index, entry in enumerate(corpus["entries"]):
        if not isinstance(entry, dict):
            return {}, f"trusted legacy corpus entry {index} is not an object"
        artifact_hash = entry.get("casefile_sha256")
        receipt_hash = entry.get("receipt_canonical_sha256")
        if not isinstance(artifact_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", artifact_hash
        ):
            return {}, f"trusted legacy corpus entry {index} has an invalid casefile hash"
        if not isinstance(receipt_hash, str) or not re.fullmatch(
            r"[0-9a-f]{64}", receipt_hash
        ):
            return {}, f"trusted legacy corpus entry {index} has an invalid receipt hash"
        attestations.setdefault(artifact_hash, set()).add(receipt_hash)
    if not attestations:
        return {}, "trusted legacy corpus is empty"
    return attestations, None


def _legacy_receipt_validation_errors(
    data: dict[str, Any], receipt: Any
) -> list[dict[str, str]]:
    """Verify an operator-supplied receipt before enabling a legacy profile.

    Version strings inside a casefile are compatibility metadata, not proof
    that an older validator accepted the artifact.  The current runtime only
    enables relaxed legacy semantics when the caller supplies a receipt bound
    to the exact canonical casefile and the declared historical validator.
    """
    if receipt is None:
        return [
            error(
                "LEGACY_RECEIPT_REQUIRED",
                "/legacy_receipt",
                "legacy validation or migration requires an external hash-bound receipt",
            )
        ]
    if not isinstance(receipt, dict):
        return [
            error(
                "LEGACY_RECEIPT_INVALID",
                "/legacy_receipt",
                "legacy receipt must be an object",
            )
        ]

    errors: list[dict[str, str]] = []
    pair = _casefile_version_pair(data)
    if (
        receipt.get("valid") is not True
        or receipt.get("error_count") != 0
        or receipt.get("errors") != []
    ):
        errors.append(
            error(
                "LEGACY_RECEIPT_INVALID",
                "/legacy_receipt/valid",
                "legacy receipt must record a zero-error successful validation",
            )
        )
    artifact_hash = canonical_sha256(data)
    if receipt.get("casefile_sha256") != artifact_hash:
        errors.append(
            error(
                "LEGACY_RECEIPT_HASH_MISMATCH",
                "/legacy_receipt/casefile_sha256",
                "legacy receipt is not bound to this exact canonical casefile",
            )
        )
    if pair is None or (
        receipt.get("schema_version") != pair[0]
        or receipt.get("validator_version") != pair[1]
    ):
        errors.append(
            error(
                "LEGACY_RECEIPT_VERSION_MISMATCH",
                "/legacy_receipt/validator_version",
                "legacy receipt does not match the artifact schema and historical validator pair",
            )
        )
    attestations, registry_error = _trusted_legacy_attestations()
    if registry_error is not None:
        errors.append(
            error(
                "LEGACY_TRUST_REGISTRY_UNAVAILABLE",
                "/legacy_receipt",
                registry_error,
            )
        )
    elif artifact_hash not in attestations:
        errors.append(
            error(
                "LEGACY_ARTIFACT_NOT_ATTESTED",
                "/legacy_receipt/casefile_sha256",
                "legacy artifact is not present in the release-bound migration corpus",
            )
        )
    elif canonical_sha256(receipt) not in attestations[artifact_hash]:
        errors.append(
            error(
                "LEGACY_RECEIPT_NOT_ATTESTED",
                "/legacy_receipt",
                "legacy receipt does not match an attested receipt fingerprint for this artifact",
            )
        )
    return errors


def _legacy_epoch_ids(data: dict[str, Any], field: str) -> set[str]:
    epoch = data.get("legacy_epoch")
    values = epoch.get(field) if isinstance(epoch, dict) else None
    if not isinstance(values, list):
        return set()
    return {value for value in values if isinstance(value, str)}


def _add_unknown_keys(
    errors: list[dict[str, str]], item: Any, allowed: set[str], path: str
) -> None:
    if not isinstance(item, dict):
        errors.append(error("TYPE_ERROR", path, "must be an object"))
        return
    for key in sorted(set(item) - allowed):
        errors.append(
            error("UNKNOWN_FIELD", f"{path}/{key}", "field is not in the contract")
        )


def _require_string(
    errors: list[dict[str, str]], item: dict[str, Any], key: str, path: str
) -> str | None:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        errors.append(error("REQUIRED_STRING", f"{path}/{key}", "must be a non-empty string"))
        return None
    return value


def _require_bool(
    errors: list[dict[str, str]], item: dict[str, Any], key: str, path: str
) -> bool | None:
    value = item.get(key)
    if not isinstance(value, bool):
        errors.append(error("REQUIRED_BOOLEAN", f"{path}/{key}", "must be a boolean"))
        return None
    return value


def _require_list(
    errors: list[dict[str, str]], item: dict[str, Any], key: str, path: str
) -> list[Any] | None:
    value = item.get(key)
    if not isinstance(value, list):
        errors.append(error("REQUIRED_ARRAY", f"{path}/{key}", "must be an array"))
        return None
    return value


def _check_string_list(
    errors: list[dict[str, str]],
    value: Any,
    path: str,
    nonempty: bool = False,
    unique: bool = False,
) -> None:
    if not isinstance(value, list):
        errors.append(error("REQUIRED_ARRAY", path, "must be an array"))
        return
    if nonempty and not value:
        errors.append(error("EMPTY_ARRAY", path, "must contain at least one item"))
    if (
        unique
        and all(isinstance(item, str) for item in value)
        and len(value) != len(set(value))
    ):
        errors.append(
            error(
                "DUPLICATE_LIST_ITEM",
                path,
                "array items must be unique",
            )
        )
    for index, entry in enumerate(value):
        if not isinstance(entry, str) or not entry.strip():
            errors.append(
                error("REQUIRED_STRING", f"{path}/{index}", "must be a non-empty string")
            )


def _index_by_id(
    errors: list[dict[str, str]], items: Any, path: str
) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    if not isinstance(items, list):
        errors.append(error("REQUIRED_ARRAY", path, "must be an array"))
        return index
    for position, item in enumerate(items):
        item_path = f"{path}/{position}"
        if not isinstance(item, dict):
            errors.append(error("TYPE_ERROR", item_path, "must be an object"))
            continue
        item_id = item.get("id")
        if not isinstance(item_id, str) or not item_id.strip():
            errors.append(error("REQUIRED_STRING", f"{item_path}/id", "must be a non-empty string"))
            continue
        if item_id in index:
            errors.append(error("DUPLICATE_ID", f"{item_path}/id", f"duplicate id {item_id}"))
            continue
        index[item_id] = item
    return index


def _input_text(inputs: dict[str, dict[str, Any]], input_id: Any) -> str | None:
    if not isinstance(input_id, str):
        return None
    item = inputs.get(input_id)
    if not isinstance(item, dict):
        return None
    text = item.get("text")
    return text if isinstance(text, str) else None


def _actual_quote_ranges(text: str) -> list[tuple[int, int]]:
    opening = {"“": "”", "‘": "’", "「": "」", "『": "』"}
    symmetric = {'"', "'"}
    stack: list[tuple[str, int]] = []
    ranges: list[tuple[int, int]] = []
    for index, character in enumerate(text):
        if character in opening:
            stack.append((opening[character], index))
            continue
        if character in symmetric:
            if (
                character == "'"
                and index > 0
                and index + 1 < len(text)
                and text[index - 1].isalnum()
                and text[index + 1].isalnum()
            ):
                # English contractions and possessives are not quotations.
                continue
            if stack and stack[-1][0] == character:
                _, start = stack.pop()
                if start + 1 < index:
                    ranges.append((start + 1, index))
            else:
                stack.append((character, index))
            continue
        if stack and character == stack[-1][0]:
            _, start = stack.pop()
            if start + 1 < index:
                ranges.append((start + 1, index))
    return sorted(ranges)


def _quote_range_containing(
    text: str, start: int, end: int
) -> tuple[int, int] | None:
    containing = [
        (left, right)
        for left, right in _actual_quote_ranges(text)
        if left <= start and end <= right
    ]
    return min(containing, key=lambda item: item[1] - item[0]) if containing else None


def _direct_source_scoped_prefix(prefix: str) -> tuple[str, bool]:
    """Return the active provenance suffix and whether a direct event reset it."""
    if re.match(r"^\s*\[[^\]]+\]\s*", prefix):
        return prefix, False
    matches = list(DIRECT_SOURCE_RESET_PATTERN.finditer(prefix))
    if not matches:
        return prefix, False
    return prefix[matches[-1].start() :], True


def _quoted_speaker_role(
    text: str, quote_start: int, quote_end: int
) -> str:
    """Return user, other, or unknown for the speaker owning one quote."""
    clause_start = max(
        (text.rfind(mark, 0, quote_start) for mark in "。！？；\n"),
        default=-1,
    ) + 1
    prefix = text[clause_start:quote_start]
    prefix, _ = _direct_source_scoped_prefix(prefix)
    prefix = re.sub(r"^\s*\[[^\]]+\]\s*", "", prefix, count=1)
    # Text-bearing artifacts and generated systems can contain a first-person
    # sentence without there being a human speaker whose current position is
    # established.  Keep those provenance classes explicit and fail closed.
    if (
        NONHUMAN_OR_ARTIFACT_QUOTE_OWNER_PATTERN.search(prefix)
        or PROXY_QUOTE_CONTEXT_PATTERN.search(prefix)
    ):
        return "unknown"
    # In ``我对老板说`` the named person is the recipient, not the speaker.
    # Resolve this bounded subject-recipient frame before the generic named-
    # speaker branch below.  Proxy speech was already rejected above, so this
    # cannot upgrade ``我替他对老板说`` into the user's own position.
    if re.search(
        r"(?:^|[，,]\s*)(?:我|本人)"
        r"(?:(?:今天|现在|此刻|刚刚|刚才|随后|后来|明确|郑重|正式|亲口|当面|已经|也|又|自己)\s*)*"
        rf"(?:对|跟|向){USER_SPEECH_RECIPIENT_PATTERN}\s*"
        rf"{CHINESE_DIRECT_SPEECH_VERB_PATTERN}"
        r"\s*[：:]?\s*[“‘\"「『']?\s*$",
        prefix,
    ):
        return "user"
    if re.search(
        r"(?:^|[，,]\s*)(?:我|本人)"
        r"(?:(?:今天|现在|此刻|刚刚|刚才|随后|后来|明确|郑重|正式|"
        r"亲口|当面|已经|也|又|自己|笑着|哭着|认真地|直接)\s*)*"
        r"(?:告诉|告知|回复|回答|答复)\s*"
        rf"{USER_SPEECH_RECIPIENT_PATTERN}"
        r"\s*[：:]?\s*[“‘\"「『']?\s*$",
        prefix,
    ):
        return "user"
    if re.search(
        r"(?:^|[，,]\s*)(?:我|本人)"
        r"(?:(?:今天|现在|刚刚|刚才|随后|后来|明确|郑重|正式|亲口|当面|已经|也|又|自己)\s*)*"
        r"(?:改口|更正|修正).{0,32}(?:改为|改成|更正为)\s*[“‘\"']?\s*$",
        prefix,
    ):
        return "user"
    if re.search(
        rf"{HUMAN_OTHER_SPEAKER_PATTERN}.{{0,48}}"
        r"(?:改口|更正|修正).{0,32}(?:改为|改成|更正为)\s*[“‘\"']?\s*$",
        prefix,
    ):
        return "other"
    # The nearest bounded first-person speech frame wins over an earlier
    # named participant: ``老板问我，我回答`` is the user's utterance.  Proxy
    # frames were rejected above, and possessive subjects such as ``我爸`` do
    # not satisfy this finite subject grammar.
    if re.search(
        rf"(?:^|[，,]\s*)(?:我|本人)"
        r"(?:(?:今天|现在|刚刚|刚才|随后|后来|明确|郑重|正式|亲口|当面|已经|也|又|自己|笑着|哭着|认真地|直接)\s*|"
        rf"(?:(?:对|跟|向){USER_SPEECH_RECIPIENT_PATTERN})\s*)*"
        rf"{CHINESE_DIRECT_SPEECH_VERB_PATTERN}"
        r"\s*[：:]?\s*[“‘\"「『']?\s*$|"
        rf"\bI\s+{ENGLISH_DIRECT_SPEECH_VERB_PATTERN}\b.{{0,24}}$",
        prefix,
        re.IGNORECASE,
    ):
        return "user"
    # With no bounded first-person frame, a named human speech act remains a
    # third-party utterance.
    if re.search(
        rf"{HUMAN_OTHER_SPEAKER_PATTERN}.{{0,16}}"
        rf"(?:{CHINESE_DIRECT_SPEECH_VERB_PATTERN}|"
        r"发来(?:一条|一封)?(?:消息|短信|邮件)|转发|转述)"
        r".{0,12}[：:]?\s*[“‘\"「『']?\s*$|"
        r"\b(?:he|she|they|my\s+friend|my\s+boss|the\s+person)\s+"
        rf"{ENGLISH_DIRECT_SPEECH_VERB_PATTERN}\b.{{0,24}}$",
        prefix,
        re.IGNORECASE,
    ):
        return "other"
    return "unknown"


def _has_direct_human_speech_frame(
    text: str, quote_start: int, quote_end: int
) -> bool:
    """Return whether a visible quote is owned by a direct human speech act.

    A human-looking name inside a carrier is not enough.  Artifact and
    non-real ownership is rejected first, and proxy verbs remain secondhand
    even when the quoted source is a named person.
    """
    clause_start = max(
        (text.rfind(mark, 0, quote_start) for mark in "。！？；\n"),
        default=-1,
    ) + 1
    prefix = text[clause_start:quote_start]
    prefix, _ = _direct_source_scoped_prefix(prefix)
    prefix = re.sub(r"^\s*\[[^\]]+\]\s*", "", prefix, count=1)
    if (
        NONHUMAN_OR_ARTIFACT_QUOTE_OWNER_PATTERN.search(prefix)
        or PROXY_QUOTE_CONTEXT_PATTERN.search(prefix)
    ):
        return False
    if re.search(r"(?:引用|转发|转述|复述|代为传达|播放)", prefix[-64:]):
        return False
    if re.search(
        r"(?:据|根据).{0,16}(?:回忆|转述|说法|消息)|"
        r"(?:听说|据说)|我记得.{0,16}(?:好像|似乎)",
        prefix[-80:],
    ):
        return False
    return _quoted_speaker_role(text, quote_start, quote_end) in {"user", "other"}


def _connected_transform_quote_gap(text: str, left_end: int, right_start: int) -> bool:
    """Return whether two quotes are coordinated operands of one transform."""
    gap_end = max(left_end + 1, right_start - 1)
    gap = text[left_end + 1 : gap_end]
    return bool(
        re.fullmatch(
            r"\s*(?:(?:[，,、/]\s*)?(?:和|与|及|以及|或|或者)\s*|"
            r"[，,、/]\s*)?(?:这两(?:句|段)|二者|两者|都|一并|分别)?\s*",
            gap,
        )
    )


def _prefix_transform_gap_owns_operand(gap: str) -> bool:
    """Require a direct syntactic bridge from a prefix operation to a quote."""
    return bool(
        re.fullmatch(
            r"\s*(?:(?:this|the\s+following)(?:\s+fictional)?"
            r"(?:\s+(?:line|sentence|text|quote|dialogue))?\s*)?"
            r"(?:only\s*)?"
            r"(?:(?:into|to)\s+(?:English|Chinese)\s*)?"
            r"(?:英文|英语|中文)?\s*(?:是否匹配|是否命中)?\s*"
            r"[:：]?\s*[“‘\"']?\s*",
            gap,
            re.IGNORECASE,
        )
    )


def transform_payload_ranges(text: str) -> list[tuple[int, int]]:
    """Return quoted operands structurally owned by the first transform task.

    Prefix forms such as ``翻译“a”和“b”`` and object-first forms such as
    ``把“a”和“b”都翻译`` are supported.  A narrative gap, a reporting verb,
    or a second-task connector ends the operand list, so a later real-world
    quotation cannot be hidden inside transform scope.
    """
    quote_ranges = _actual_quote_ranges(text)
    operation = TRANSFORM_OPERATION_PATTERN.search(text)
    if not quote_ranges or operation is None:
        return []

    object_intro_matches = [
        match
        for match in re.finditer(r"(?:把|将)", text[: operation.start()])
        if operation.start() - match.end() <= 96
    ]
    candidates: list[tuple[int, int]]
    if object_intro_matches:
        object_start = object_intro_matches[-1].end()
        candidates = [
            item
            for item in quote_ranges
            if item[0] > object_start and item[1] <= operation.start()
        ]
    else:
        candidates = [item for item in quote_ranges if item[0] >= operation.end()]
        if candidates and not _prefix_transform_gap_owns_operand(
            text[operation.end() : candidates[0][0]]
        ):
            candidates = []
        if not candidates:
            # Postfix translation requests own the nearest preceding quote
            # when only punctuation and a bounded politeness marker connect
            # it to the operation.  The narrow gap grammar prevents an
            # unrelated earlier quotation from being captured as payload.
            preceding = [item for item in quote_ranges if item[1] <= operation.start()]
            if preceding:
                nearest = preceding[-1]
                gap = text[nearest[1] + 1 : operation.start()]
                if re.fullmatch(r"\s*[，,。；;：:]?\s*(?:请|帮我|请帮我)?\s*", gap):
                    candidates = [nearest]
    if not candidates:
        return []

    selected = [candidates[0]]
    for candidate in candidates[1:]:
        if not _connected_transform_quote_gap(
            text, selected[-1][1], candidate[0]
        ):
            break
        selected.append(candidate)
    return selected


_TRANSFORM_PAYLOAD_INDEX = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
TRANSFORM_PAYLOAD_DISAVOWAL_PATTERN = re.compile(
    r"第(?P<index>[1-9]|10|[一二两三四五六七八九十])(?:句|段|项)"
    r".{0,8}(?:不是|并非)(?:单纯的?)?"
    r"(?:翻译|改写|格式|整理|分析|测试)?(?:素材|文本|例句|台词|内容)"
    r".{0,28}(?:而是|是)(?:我|本人|现实|真实|实际|现在|当前)"
)
TRANSFORM_PAYLOAD_RELATIVE_DISAVOWAL_PATTERN = re.compile(
    r"(?P<selector>前(?:一)?(?:句|段|项)|后(?:一)?(?:句|段|项)|"
    r"最后(?:一)?(?:句|段|项)|这(?:一)?(?:句|段|项)|该(?:句|段|项))"
    r".{0,12}(?:(?:不是|并非)(?:单纯的?)?"
    r"(?:翻译|改写|格式|整理|分析|测试)?(?:素材|文本|例句|台词|内容)"
    r".{0,16}(?:而是|是)|(?:就是|是))"
    r".{0,12}(?:我|本人).{0,12}(?:现在|当前|现实|真实|实际)"
    r".{0,12}(?:计划|打算|意图|情况|表达|意思|想法|念头)"
)
TRANSFORM_PAYLOAD_SINGLETON_DISAVOWAL_PATTERN = re.compile(
    r"(?:^|[。！？；\n])\s*这"
    r".{0,8}(?:不是|并非)(?:单纯的?)?"
    r"(?:翻译|改写|格式|整理|分析|测试)?(?:素材|文本|例句|台词|内容)"
    r".{0,16}(?:而是|是).{0,12}(?:我|本人)"
    r".{0,12}(?:现在|当前|现实|真实|实际)"
    r".{0,12}(?:计划|打算|意图|情况|表达|意思|想法|念头)"
)
TRANSFORM_PAYLOAD_ANAPHORIC_REALITY_PATTERN = re.compile(
    r"(?:"
    r"(?:现实(?:中|里|生活中)|实际(?:上|情况)?|真实(?:情况)?)"
    r".{0,20}(?:这|这也|这句话|上述(?:内容|话)|前述(?:内容|话))"
    r".{0,24}(?:我|本人).{0,12}(?:现在|当前|此刻)"
    r".{0,12}(?:计划|打算|意图|意思|想法|念头)|"
    r"(?:这|这也|这句话|上述(?:内容|话)|前述(?:内容|话))"
    r".{0,16}(?:不只是|并非只是|不是单纯的?)"
    r".{0,12}(?:翻译|改写|格式|整理)?(?:素材|文本|例句|台词|内容)?"
    r".{0,16}(?:而是|就是|正是).{0,12}(?:我|本人)"
    r".{0,12}(?:现在|当前|此刻|真实|实际)"
    r".{0,12}(?:计划|打算|意图|意思|想法|念头)|"
    r"(?:这|这句|这句话|上述(?:内容|话)|前述(?:内容|话))"
    r".{0,8}(?:不是|并非)(?:单纯的?)?"
    r"(?:翻译素材|测试文本|例句|台词|虚构内容|故事)"
    r".{0,28}(?:现实(?:中|里)|实际(?:上|情况)?|真实(?:情况)?)"
    r".{0,24}(?:我|本人|他|她|对方|前任)"
    r".{0,16}(?:现在|当前|此刻|正在|就在)|"
    r"\b(?:in\s+real\s+life|in\s+reality|actually)\b"
    r".{0,32}\bthis\b.{0,40}\b(?:I\s+)?(?:intend|plan|want)"
    r"(?:\s+to\s+do)?\b.{0,20}\bnow\b"
    r")",
    re.IGNORECASE,
)


def disowned_transform_payload_ranges(text: str) -> list[tuple[int, int]]:
    """Return transform operands later identified as real current content.

    A transform instruction normally owns its quoted operands.  That ownership
    is revoked when the same request explicitly identifies an indexed operand
    as the user's real, current content.  The bounded ordinal grammar keeps the
    exception auditable and prevents an unquoted afterthought from silently
    changing every operand's scope.
    """
    payload_ranges = transform_payload_ranges(text)
    if not payload_ranges:
        return []
    selected: list[tuple[int, int]] = []
    for match in TRANSFORM_PAYLOAD_DISAVOWAL_PATTERN.finditer(text):
        raw_index = match.group("index")
        index = int(raw_index) if raw_index.isdigit() else _TRANSFORM_PAYLOAD_INDEX.get(raw_index)
        if index is not None and 1 <= index <= len(payload_ranges):
            selected.append(payload_ranges[index - 1])
    for match in TRANSFORM_PAYLOAD_RELATIVE_DISAVOWAL_PATTERN.finditer(text):
        selector = match.group("selector")
        if selector.startswith("前"):
            selected.append(payload_ranges[0])
        elif selector.startswith(("后", "最后")):
            selected.append(payload_ranges[-1])
        elif len(payload_ranges) == 1:
            selected.append(payload_ranges[0])
        else:
            # A real-current declaration with an ambiguous demonstrative must
            # fail closed.  Revoking all transform operands prevents a harmful
            # one from remaining hidden behind passthrough ownership.
            selected.extend(payload_ranges)
    if (
        len(payload_ranges) == 1
        and TRANSFORM_PAYLOAD_SINGLETON_DISAVOWAL_PATTERN.search(text)
    ):
        selected.append(payload_ranges[0])
    if TRANSFORM_PAYLOAD_ANAPHORIC_REALITY_PATTERN.search(text):
        # A current-real anaphor revokes transform ownership.  With one
        # operand the referent is exact; with several operands ambiguity is a
        # safety reason to expose all of them rather than silently hide one.
        selected.extend(payload_ranges)
    return sorted(set(selected))


def transform_payload_and_tail(text: str) -> tuple[str, str]:
    """Return all owned quoted operands and the unowned suffix."""
    ranges = transform_payload_ranges(text)
    if ranges:
        payload = "\n".join(text[left:right] for left, right in ranges)
        return payload, text[ranges[-1][1] + 1 :]
    delimiter_positions = [
        position
        for marker in ("：", ":")
        for position in [text.find(marker)]
        if position >= 0
    ]
    if delimiter_positions:
        delimiter = min(delimiter_positions)
        return text[delimiter + 1 :], text[delimiter + 1 :]
    return text, text


def _reality_scope_reset_match(text: str) -> re.Match[str] | None:
    """Match only an affirmative, clause-initial return to real context."""
    return NONFICTION_SCOPE_RESET_PATTERN.match(
        text
    ) or REALITY_SCOPE_RESET_PATTERN.match(text)


def _trim_range(text: str, start: int, end: int) -> tuple[int, int] | None:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return (start, end) if start < end else None


EPISTEMIC_SCOPE_RESIDUAL_PATTERN = re.compile(
    rf"^\s*(?:(?:{EPISTEMIC_TRUTH_PREDICATE_PATTERN}|"
    rf"{EPISTEMIC_EVENT_NEGATION_PATTERN}|"
    r"(?:(?:确有|真的|确实|实际|的确)?发生(?:过)?))\s*)?"
    r"(?:(?:吗|么|呢|对吗)|[?？])?\s*[。！？!?；;，,]*\s*$"
)


def _is_pure_epistemic_scope_tail(value: str) -> bool:
    """Return true only when a comma tail qualifies the prior proposition.

    ``EPISTEMIC_SCOPE_TAIL_PATTERN`` intentionally matches prefixes, but a
    prefix such as ``是不是`` can also begin a new motive or identity question.
    Requiring the unmatched suffix to contain only truth-status vocabulary and
    punctuation keeps real qualifications bound while allowing a new story
    proposition to become its own source span.
    """
    match = EPISTEMIC_SCOPE_TAIL_PATTERN.match(value)
    if match and EPISTEMIC_SCOPE_RESIDUAL_PATTERN.fullmatch(
        value[match.end() :]
    ):
        return True
    normalized = re.sub(r"^[\s，,]+|[\s。！？!?；;，,]+$", "", value)
    if not re.match(r"^(?:是否|是不是)", normalized):
        return False
    # When a finite event is followed by a yes/no question whose vocabulary is
    # not a recognized story, keep the question bound to the event. This is a
    # deliberate fail-closed default: an unfamiliar restatement must not expose
    # the preceding event as a positive fact. Known motive, identity and
    # prediction stories still split into their own auditable span.
    known_story = bool(
        USER_STORY_CONTENT_PATTERN.search(normalized)
        or IDENTITY_CLAIM_PATTERN.search(normalized)
        or MOTIVE_OR_INNER_STATE_CLAIM_PATTERN.search(normalized)
        or PREDICTION_CLAIM_PATTERN.search(normalized)
        or _is_claimable_user_story_span(normalized)
    )
    return not known_story


def _clause_ranges(
    text: str, start: int, end: int, quote_ranges: list[tuple[int, int]]
) -> list[tuple[int, int]]:
    separators = set("。！？；，,\n")
    ranges: list[tuple[int, int]] = []
    segment_start = start
    quote_index = 0
    while quote_index < len(quote_ranges) and quote_ranges[quote_index][1] <= start:
        quote_index += 1
    index = start
    while index < end:
        while quote_index < len(quote_ranges) and quote_ranges[quote_index][1] <= index:
            quote_index += 1
        inside_quote = (
            quote_index < len(quote_ranges)
            and quote_ranges[quote_index][0] <= index < quote_ranges[quote_index][1]
        )
        if not inside_quote and text[index] in separators:
            # A comma can introduce a truth-status qualification of the
            # proposition immediately before it.  Keeping both sides in one
            # span prevents a denied or rumoured event from being exposed as
            # an independent positive fact.
            if text[index] in "，," and (
                _is_pure_epistemic_scope_tail(text[index:end])
                or POSTFIX_EVENT_DISAVOWAL_PATTERN.match(text[index:end])
            ):
                index += 1
                continue
            trimmed = _trim_range(text, segment_start, index + 1)
            if trimmed:
                ranges.append(trimmed)
            segment_start = index + 1
        index += 1
    trimmed = _trim_range(text, segment_start, end)
    if trimmed:
        ranges.append(trimmed)
    return ranges


def _inside_quote(index: int, quote_ranges: list[tuple[int, int]]) -> bool:
    return any(start <= index < end for start, end in quote_ranges)


def _atomic_ranges(
    text: str,
    start: int,
    end: int,
    quote_ranges: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Split a clause at explicit inference/coordination boundaries.

    The boundary token belongs to the following story span. This allows the
    observable event before it to be anchored without letting the conclusion
    after it inherit the same fact label. Quoted text is never split here.
    """
    def strip_leading_contrast(
        candidate: tuple[int, int] | None,
    ) -> tuple[int, int] | None:
        if not candidate:
            return None
        left, right = candidate
        reset = LEADING_CONTRAST_PATTERN.match(text[left:right])
        if reset:
            return _trim_range(text, left + reset.end(), right)
        return candidate

    def complete_epistemic_prefix(left: int, right: int) -> bool:
        """Return whether a boundary would leave a complete layer on its left.

        Chinese adverbs such as ``肯定`` and ``后来`` can look like discourse
        connectors even when they are still inside the predicate.  A boundary
        is licensed only after a complete observation, named feeling, or user
        story.  This keeps ``老板肯定在架空我`` intact while still splitting
        ``他没回所以他不爱我`` after the observed event.
        """
        candidate = strip_leading_contrast(_trim_range(text, left, right))
        if not candidate:
            return False
        value = text[candidate[0] : candidate[1]].strip()
        observation = parse_observation_prefix(value)
        recognized_story = any(
            pattern.search(value)
            for pattern in (
                IDENTITY_CLAIM_PATTERN,
                MOTIVE_OR_INNER_STATE_CLAIM_PATTERN,
                PREDICTION_CLAIM_PATTERN,
            )
        ) or _is_claimable_user_story_span(value)
        unclassified_observation = bool(
            UNCLASSIFIED_OBSERVATION_SURFACE_PATTERN.search(value)
            and not UNCLASSIFIED_OBSERVATION_NONREAL_PATTERN.search(value)
            and not UNCLASSIFIED_OBSERVATION_NONASSERTED_PATTERN.search(value)
            and not re.search(r"[?？]", value)
        )
        return bool(
            (
                observation is not None
                and _observation_parse_consumes_full_value(value, observation[1])
            )
            or is_explicit_feeling(value)
            or recognized_story
            or derive_stated_position_type(value) is not None
            or unclassified_observation
        )

    initial = strip_leading_contrast(_trim_range(text, start, end))
    if not initial:
        return []
    start, end = initial
    scoped_value = text[start:end]
    parsed_observation = parse_observation_prefix(scoped_value)
    event_disavowal_scope_end: int | None = None
    if parsed_observation is not None:
        _, parsed_end = parsed_observation
        disavowal = POSTFIX_EVENT_DISAVOWAL_PATTERN.match(
            scoped_value[parsed_end:]
        )
        if disavowal is not None:
            event_disavowal_scope_end = start + parsed_end + disavowal.end()
    boundaries: list[int] = []
    for match in ATOMIC_INFERENCE_CONNECTOR_PATTERN.finditer(text, start, end):
        position = match.start()
        if position <= start or _inside_quote(position, quote_ranges):
            continue
        # An insufficiency or withheld-judgment operator governs its following
        # proof predicate.  Cutting at ``证明`` would invert
        # ``单凭 X 不足以证明 Y`` into an asserted standalone ``证明 Y``.
        if NONASSERTED_STORY_SCOPE_PATTERN.search(text[start : match.end()]):
            # A contrast after a complete nonasserted proposition opens a new
            # polarity scope even without a comma.  Keep the denied left side
            # nonasserted while allowing ``但我认为 Y`` to be classified on
            # its own.  Other connectors inside the governing operator remain
            # unsplittable, preserving ``不足以证明 Y`` as one scope.
            if (
                match.group() in {"但是", "但", "可是", "然而", "不过", "却"}
                and NONASSERTED_STORY_SCOPE_PATTERN.search(text[start:position])
                and USER_STORY_CONTENT_PATTERN.search(text[start:position])
            ):
                boundaries.append(position)
            continue
        if not complete_epistemic_prefix(start, position):
            continue
        if POLAR_STORY_QUESTION_PREFIX_PATTERN.fullmatch(text[start:position]):
            # The modifier belongs inside the A-not-A question. Cutting at
            # ``根本``/``肯定``/``注定`` would turn a question into an apparent
            # declarative story and change its polarity.
            continue
        if match.group().startswith("是") and text[position - 1 : position] == "不":
            # ``是不是故意`` and ``不是故意`` contain the token ``是故意``
            # without introducing a new proposition at the second copula.
            # Splitting there creates a meaningless ``是不`` or ``他不`` span.
            continue
        if match.group() == "为了":
            # Chinese has no whitespace word boundary.  “为了” is a purpose
            # connector only when the material before it is already a complete
            # finite event; otherwise its characters may be internal to a verb
            # such as “认为了”.  This semantic boundary gate generalizes beyond
            # matching one full sentence while preserving real event→purpose
            # splits.
            prefix_value = text[start:position].strip()
            prefix_observation = parse_observation_prefix(prefix_value)
            if (
                prefix_observation is None
                or not _observation_parse_consumes_full_value(
                    prefix_value, prefix_observation[1]
                )
            ):
                continue
        boundaries.append(position)
    # ``不是说 X 而是说 Y`` creates a polarity reset even without a comma.
    # The denied left proposition stays nonasserted, while the affirmative
    # replacement must remain independently visible.  Restrict the cut to an
    # explicit first-person speech/judgment denial so ordinary occurrences of
    # ``而是`` do not become generic atom boundaries.
    for match in re.compile(r"而是").finditer(text, start, end):
        position = match.start()
        if position <= start or _inside_quote(position, quote_ranges):
            continue
        left = text[start:position]
        right = text[match.end() : end]
        if (
            re.search(
                r"(?:我|本人).{0,8}(?:不是|并非|没有|没|未)"
                r".{0,8}(?:说|讲|表示|认为|觉得|判断|推断)",
                left,
            )
            and USER_STORY_CONTENT_PATTERN.search(right)
        ):
            boundaries.append(position)
    for match in LEADING_SEQUENCE_PATTERN.finditer(text, start, end):
        position = match.start()
        if (
            position > start
            and not _inside_quote(position, quote_ranges)
            and complete_epistemic_prefix(start, position)
        ):
            boundaries.append(position)
    # Keep a named feeling separate from the proposition that follows it.
    # "我害怕他是NPD" contains a real feeling and an unverified
    # third-party diagnosis; neither may inherit the other's claim type.
    third_party_predicate = re.compile(
        r"(?:他|她|对方|老板|同事|朋友)"
        r"(?=.{0,4}(?:是|有|会|要|在|没|不|想|很|非常|特别|"
        r"取消|回复|回消息|参加|离开|到达|迟到|缺席|删除|移除|"
        + FEELING_MARKERS.pattern
        + r"))"
    )
    for match in third_party_predicate.finditer(text, start, end):
        position = match.start()
        prefix = text[start:position]
        if (
            position > start
            and "我" in prefix
            and FEELING_MARKERS.search(prefix)
            and not re.search(
                rf"(?:{ATOMIC_INFERENCE_CONNECTOR_PATTERN.pattern}|"
                rf"{LEADING_SEQUENCE_PATTERN.pattern})\s*$",
                prefix,
            )
            and not _inside_quote(position, quote_ranges)
        ):
            boundaries.append(position)
    # Coordinated conclusions can carry different epistemic kinds.  Leaving
    # them in one span lets precedence silently erase one layer, for example
    # motive + identity in ``他不爱我而且是回避型``.  Split only when both
    # sides are themselves story-bearing and their kind sets differ.
    for match in ATOMIC_STORY_COORDINATION_PATTERN.finditer(text, start, end):
        position = match.start()
        if position <= start or _inside_quote(position, quote_ranges):
            continue
        prefix_kinds = _story_kind_candidates(text[start:position])
        # Keep the coordinator on the right operand.  Chinese commonly omits
        # a repeated subject in ``他不爱我，还准备离开``; the coordinator is
        # the structural evidence that the future modal belongs to a second
        # proposition rather than to the first motive clause.
        suffix_kinds = _story_kind_candidates(text[position:end])
        prefix_feeling = is_explicit_feeling(text[start:position])
        suffix_feeling = is_explicit_feeling(text[position:end])
        if (
            (prefix_feeling and suffix_kinds)
            or (prefix_kinds and suffix_feeling)
            or (
                prefix_kinds
                and suffix_kinds
                and prefix_kinds != suffix_kinds
            )
        ):
            boundaries.append(position)
    # When a story proposition is coordinated with an observable action, keep
    # the action available as a separate span and never expose the combination
    # as one fact candidate.
    for match in re.compile(r"并(?:且)?").finditer(text, start, end):
        position = match.start()
        prefix = text[start:position]
        suffix = text[match.end():end]
        if (
            position > start
            and STORY_MARKERS.search(prefix)
            and any(
                pattern.search(suffix)
                for pattern in (
                    COMMUNICATION_EVENT_MARKERS,
                    PARTICIPATION_OR_SCHEDULE_MARKERS,
                    TASK_OR_ACTION_MARKERS,
                    ARTIFACT_OR_SYSTEM_MARKERS,
                )
            )
            and not _inside_quote(position, quote_ranges)
        ):
            boundaries.append(match.end())
    # A copula after an already observable event is an epistemic boundary even
    # when the following motive adjective is new. This is structural rather
    # than a growing synonym list: "observable event + 是 + conclusion" is
    # never accepted as one fact span.
    for match in re.compile(r"是").finditer(text, start, end):
        position = match.start()
        if position <= start or _inside_quote(position, quote_ranges):
            continue
        if any(
            connector.start() < position < connector.end()
            for connector in ATOMIC_INFERENCE_CONNECTOR_PATTERN.finditer(
                text, start, end
            )
        ):
            # ``就是`` is one connector.  Its internal copula cannot create a
            # second boundary that leaves an orphan ``就`` span.
            continue
        prefix = text[start:position]
        suffix = text[position + 1:end]
        if not re.search(r"我|你|他|她|老板|公司|自己|对方", suffix):
            continue
        if any(
            pattern.search(prefix)
            for pattern in (
                COMMUNICATION_EVENT_MARKERS,
                PARTICIPATION_OR_SCHEDULE_MARKERS,
                TASK_OR_ACTION_MARKERS,
                ARTIFACT_OR_SYSTEM_MARKERS,
            )
        ):
            boundaries.append(position)
    # A finite event parser can identify a complete observable prefix even
    # when the following story uses language the runtime has never seen.  Keep
    # that event as its own span and leave every unconsumed non-punctuation
    # suffix outside the fact layer.
    if parsed_observation is not None:
        _, parsed_end = parsed_observation
        raw_remainder = scoped_value[parsed_end:]
        remainder = raw_remainder.lstrip()
        reporting_continuation = bool(
            re.match(r"(?:说|讲|称|表示|告诉)|[:：][“‘\"']", remainder)
        )
        syntactic_continuation = bool(
            re.match(r"(?:的|地|得|们|本人|自己)", remainder)
        )
        epistemic_scope_continuation = bool(
            _is_pure_epistemic_scope_tail(remainder)
        )
        # Preserve the proposition when the apparent event suffix is actually
        # part of its grammar.  In an A-not-A question, the negative form
        # determines whether the event happened; in a relative object phrase,
        # the pronoun consumed by the finite parser is the subject of the
        # following modifier.  Neither structure licenses a positive fact
        # prefix merely because the parser recognizes an earlier substring.
        question_continuation = bool(
            re.fullmatch(r"(?:没有|没|未)(?:吗|么|呢)?[?？]", remainder)
        )
        relative_object_continuation = bool(
            re.search(r"(?:我|你|他|她|对方)$", scoped_value[:parsed_end])
            and re.fullmatch(
                r"(?:没有|没|未).{1,24}的(?:消息|邮件|回复|问题|内容|"
                r"请求|文件|记录|评论)[\s。！；，,]*",
                remainder,
            )
        )
        if (
            not _observation_parse_consumes_full_value(scoped_value, parsed_end)
            and not reporting_continuation
            and not syntactic_continuation
            and not epistemic_scope_continuation
            and not question_continuation
            and not relative_object_continuation
            and event_disavowal_scope_end is None
        ):
            boundaries.append(start + parsed_end)
    if event_disavowal_scope_end is not None:
        # The postfix explicitly revokes the proposition before it.  Every
        # connector inside that tail belongs to the same truth-status scope;
        # splitting earlier would resurrect the revoked prefix as a fact.
        boundaries = [
            boundary
            for boundary in boundaries
            if boundary >= event_disavowal_scope_end
        ]
        trailing = text[event_disavowal_scope_end:end]
        if trailing and not _OBSERVATION_TRAILING_PUNCTUATION.fullmatch(trailing):
            boundaries.append(event_disavowal_scope_end)
    if not boundaries:
        trimmed = strip_leading_contrast(_trim_range(text, start, end))
        return [trimmed] if trimmed else []
    # Multiple detectors may nominate overlapping cuts.  Accepting both can
    # strand a connector or bare subject between them (``我担心`` / ``他`` /
    # ``根本不爱我``).  After the first licensed boundary, each further cut
    # must leave another complete epistemic layer since the last accepted cut.
    accepted_boundaries: list[int] = []
    for boundary in sorted(set(boundaries)):
        if accepted_boundaries and not complete_epistemic_prefix(
            accepted_boundaries[-1], boundary
        ):
            continue
        accepted_boundaries.append(boundary)

    ranges: list[tuple[int, int]] = []
    cursor = start
    for boundary in accepted_boundaries:
        trimmed = strip_leading_contrast(_trim_range(text, cursor, boundary))
        if trimmed:
            ranges.append(trimmed)
        cursor = boundary
    trimmed = strip_leading_contrast(_trim_range(text, cursor, end))
    if trimmed:
        ranges.append(trimmed)
    return ranges


def _preceding_clause_context(text: str, content_start: int, span_start: int) -> str:
    if span_start <= content_start:
        return ""
    boundary = max(
        (text.rfind(character, content_start, span_start) for character in "。！？；\n"),
        default=-1,
    )
    context_start = max(content_start, boundary + 1)
    return text[context_start:span_start]


INTERNAL_SOURCE_CONTEXT_TOKENS = {
    "inferred_secondhand_context",
    "inferred_artifact_context",
    "inferred_nonfactive_context",
    "inferred_nonasserted_context",
    "aggregate_safety_context",
    "aggregate_candidate_resolution_context",
}


def _sanitize_external_source_label(source_label: str) -> str:
    """Keep user-authored labels out of the internal marker namespace."""
    parts = re.split(r"([｜|])", source_label)
    sanitized: list[str] = []
    for part in parts:
        if part.strip() in INTERNAL_SOURCE_CONTEXT_TOKENS:
            sanitized.append(f"user_literal:{part.strip()}")
        else:
            sanitized.append(part)
    return "".join(sanitized)


SOURCE_LABEL_NEGATION_PATTERN = re.compile(
    r"(?:不是|并非|没有|没|未|无)(?:任何|我的|该|这个|这种)?\s*$"
)
FIRST_PERSON_EPISTEMIC_OWNER_PATTERN = re.compile(
    r"^\s*(?:(?:但是|但|可是|然而|不过|却|可|而是|反而|而且|并且|而)\s*)?"
    r"(?:(?:随后|后来|之后|接着|然后|同时)\s*)?(?:"
    r"(?:在)?我(?:个人)?看来|依我看|就我而言|"
    r"(?:我的|我个人的|我本人的|我自己的)(?:判断|看法|观点|理解|推断)"
    r"(?:是|为)?|"
    r"(?:这|这是|这就是)?(?:我|本人)(?:自己|个人)?的(?:判断|看法|观点|理解|推断)"
    r"(?:是|为)?|"
    r"(?:我|本人)(?:自己|个人|本人)?(?:由此|据此|因此|于是)?(?:倾向于)?"
    r"(?:认为|觉得|判断|推断|猜测|估计|认定|确认|断定|确信)|"
    r"(?:我|本人)(?:将|把)(?:这|这个|该|上述|前述)?"
    r"(?:事件|行为|信号|情况|做法|变化)?"
    r"(?:解读为|理解为|视为|看作|看成|当成)|"
    r"(?:这|这是|这就是)?(?:我|本人)(?:自己|个人)?(?:得出|作出|下)的?"
    r"(?:判断|结论|认定)(?:是|为)?"
    r")"
)
FIRST_PERSON_EPISTEMIC_COMPLEMENT_CONTEXT_PATTERN = re.compile(
    r"(?:^|[，,；;]|但是|但|可是|然而|不过|却|而是|反而|而且|并且|而)\s*"
    r"(?:(?:随后|后来|之后|接着|然后|同时)\s*)?(?:"
    r"(?:在)?我(?:个人)?看来|依我看|就我而言|"
    r"(?:我|本人)(?:自己|个人|本人)?(?:由此|据此|因此|于是)?(?:倾向于)?"
    r"(?:认为|觉得|判断|推断|猜测|估计|认定|确认|断定|确信)|"
    r"(?:我|本人)(?:将|把)(?:这|这个|该|上述|前述)?"
    r"(?:事件|行为|信号|情况|做法|变化)?"
    r"(?:解读为|理解为|视为|看作|看成|当成)"
    r")\s*[，,：:]\s*$"
)
FIRST_PERSON_REACTION_EXPERIENCE_FRAGMENT = (
    r"(?:听完|看完|读完|听到(?:后|以后|之后)?|看到(?:后|以后|之后)?|"
    r"得知(?:后|以后|之后)?|知道(?:后|以后|之后)?|"
    r"收到(?:消息|邮件|通知)(?:后|以后|之后))"
)
FIRST_PERSON_EXPERIENCE_OWNER_PATTERN = re.compile(
    r"^\s*(?:(?:但是|但|可是|然而|不过|却|可|而是|反而|而且|并且|而)\s*)?"
    r"(?:(?:随后|后来|之后|接着|然后|同时)\s*)?"
    r"(?:我|本人)(?:自己|本人)?"
    rf"(?:(?:{FIRST_PERSON_REACTION_EXPERIENCE_FRAGMENT})\s*)?"
    r"(?:(?:今天|现在|此刻|目前|当下|眼下|刚刚|刚才|最近|"
    r"一直|总是|始终|仍然|仍|还|反而|最|更|尤其|格外|非常|特别|有点|十分|很)\s*)*"
    rf"(?:感觉|感到|觉得)?\s*(?:{FEELING_MARKERS.pattern})"
)
FIRST_PERSON_PREDICTION_OWNER_PATTERN = re.compile(
    r"^\s*(?:(?:但是|但|可是|然而|不过|却|可|而是|反而|而且|并且|而)\s*)?"
    r"(?:(?:随后|后来|之后|接着|然后|同时)\s*)?"
    r"(?:我|本人)(?:自己|本人)?\s*(?:"
    r"注定|迟早|早晚|终将|势必|必然|"
    r"永远(?:都)?(?:不|不会|无法)|绝不会|"
    r"(?:(?:今天|明天|以后|未来|接下来)\s*)?"
    r"(?:会|不会|将|将会|将要|准备|打算|计划)"
    r")"
)
CONDITIONAL_ANTECEDENT_CONTEXT_PATTERN = re.compile(
    r"^\s*(?:如果|假如|假设|倘若|要是|若|只要|一旦)(?:说)?"
    r"[^。！？；\n]{1,120}[，,]\s*$"
)
ONLY_IF_ANTECEDENT_CONTEXT_PATTERN = re.compile(
    r"^\s*只有[^。！？；\n]{1,120}[，,]\s*$"
)
ONLY_IF_CONSEQUENT_PATTERN = re.compile(
    r"^\s*(?:(?:但是|但|可是|然而|不过|却)\s*)?"
    r"(?:(?:我|你|他|她|对方|老板|公司|本人)\s*)?才"
)
FIRST_PERSON_NONFACTIVE_ATTITUDE_PATTERN = re.compile(
    r"(?:^|[，,：:]\s)(?:(?:我|本人)(?:所)?"
    r"(?:(?:一直|总是|始终|仍然|仍|还|最|更|尤其|格外|非常|特别|有点|十分|很)\s*)*"
    r"(?:担心|害怕|恐惧|忧虑|焦虑|怕|怀疑|希望)(?:的(?:事情|情况)?是)?|"
    r"让我(?:(?:一直|总是|始终|最|更|尤其|格外|非常|特别|十分|很)\s*)*"
    r"(?:担心|害怕|恐惧|忧虑|焦虑|不安)(?:的(?:事情|情况)?是))\s*$"
)


def _label_has_affirmed_cue(source_label: str, cue_pattern: str) -> bool:
    """Return whether an external label positively asserts one source cue.

    Internal inference tokens are handled separately.  For user-authored
    labels, a lexical cue is not affirmative when its immediately governing
    phrase negates it, such as ``不是转述`` or ``并非我的观察``.
    """
    for part in re.split(r"[｜|]", source_label):
        value = part.strip()
        if (
            not value
            or value in INTERNAL_SOURCE_CONTEXT_TOKENS
            or value.startswith("user_literal:")
        ):
            continue
        for match in re.finditer(cue_pattern, value, re.IGNORECASE):
            prefix = value[: match.start()].rstrip()
            if SOURCE_LABEL_NEGATION_PATTERN.search(prefix[-12:]):
                continue
            return True
    return False


def _external_source_label_type(
    source_label: str, *, quoted: bool = False
) -> str | None:
    """Map an affirmative user label into the finite source ontology."""
    # Composite labels are resolved conservatively.  A carrier can preserve
    # wording, but an explicit secondhand cue still means the proposition was
    # not directly observed or heard by the user.  The single source enum must
    # therefore retain the least-direct link rather than let ``邮件`` or
    # ``原话`` upgrade ``二手``.
    if _label_has_affirmed_cue(
        source_label,
        rf"(?:同事转述|二手|间接来源|据说|据传|据称|传闻|传言|"
        rf"{HEARSAY_REPORTING_PREDICATE_PATTERN})",
    ):
        return "secondhand"
    if _label_has_affirmed_cue(source_label, ARTIFACT_CARRIER_PATTERN):
        return "unverified_artifact"
    if quoted and _label_has_affirmed_cue(
        source_label,
        r"(?:原文|原话|逐字引语|当面原话|亲耳原话)",
    ):
        return "direct_quote"
    if _label_has_affirmed_cue(source_label, r"(?:我的感受|感受)"):
        return "explicit_self_report"
    if _label_has_affirmed_cue(source_label, r"(?:我的观察|直接观察)"):
        return "user_direct_observation"
    if _label_has_affirmed_cue(source_label, r"(?:我的判断|判断)"):
        return "user_report"
    return None


def _quoted_context_source_tokens(
    text: str, span_start: int, span_end: int
) -> tuple[str, ...]:
    """Return fail-closed provenance tokens for one visible quotation.

    The nearest speech verb is not allowed to erase an outer carrier.  A quote
    inside hearsay, an artifact, a proxy utterance, or non-real/meta material
    therefore keeps that outer scope on its exact source span.
    """
    clause_start = max(
        (text.rfind(mark, 0, span_start) for mark in "。！？；\n"),
        default=-1,
    ) + 1
    prefix = text[clause_start:span_start]
    label_match = re.match(r"^\s*\[([^\]]+)\]\s*", prefix)
    label_type = (
        _external_source_label_type(label_match.group(1), quoted=True)
        if label_match is not None
        else None
    )
    # A new, explicitly direct encounter can reset an earlier source inside
    # the same sentence (for example, hearsay followed by the boss speaking to
    # the user in person).  A bracketed carrier remains authoritative for the
    # whole block and therefore cannot be reset by words inside that carrier.
    prefix, direct_source_reset = _direct_source_scoped_prefix(prefix)
    if direct_source_reset:
        preceding_header = ""
    else:
        before = text[:clause_start].rstrip()
        before = re.sub(r"[。！？；!?;：:\s]+$", "", before)
        previous_start = max(
            (before.rfind(mark) for mark in "。！？；!?;\n"),
            default=-1,
        ) + 1
        preceding_header = before[previous_start:].strip()
    scope_text = (
        f"{preceding_header}\n{prefix}" if preceding_header else prefix
    )
    # Markdown list markers are presentation syntax, not provenance
    # boundaries.  Normalize only the bounded context copy so a header such
    # as ``同事告诉我：`` still governs the immediately following list item.
    normalized_scope_text = re.sub(
        r"\n\s*(?:[-*+>]|\d+[.)])\s+", " ", scope_text
    )
    tokens: list[str] = []
    if (
        NONREAL_QUOTE_CONTEXT_PATTERN.search(normalized_scope_text[-192:])
        or NONREAL_SCOPE_HEADER_PATTERN.search(preceding_header)
        or bool(
            label_match
            and NONREAL_SCOPE_HEADER_PATTERN.search(label_match.group(1).strip())
        )
        or re.search(
            r"(?:案例|示例|例句|语法分析|句法分析|文本分析|访谈模拟|"
            r"角色扮演|梦见|梦到|梦里|梦中|梦境|虚构|想象|脑补).{0,96}$",
            normalized_scope_text[-224:],
            re.IGNORECASE,
        )
        or NONVERBATIM_OR_UNCONFIRMED_QUOTE_CONTEXT_PATTERN.search(
            normalized_scope_text[-224:]
        )
    ):
        tokens.append("inferred_nonasserted_context")
    if (
        label_type == "secondhand"
        or SECONDHAND_SCOPE_HEADER_PATTERN.search(preceding_header)
        or EXPLICIT_HEARSAY_QUOTE_PREFIX_PATTERN.search(
            normalized_scope_text[-224:]
        )
        or NESTED_REPORTING_CHAIN_PATTERN.search(normalized_scope_text[-224:])
        or NESTED_QUOTE_REPORTING_PATTERN.search(normalized_scope_text[-224:])
        or PROXY_QUOTE_CONTEXT_PATTERN.search(normalized_scope_text[-192:])
    ):
        tokens.append("inferred_secondhand_context")
    if (
        label_type == "unverified_artifact"
        or ARTIFACT_SCOPE_HEADER_PATTERN.search(preceding_header)
        or ARTIFACT_MEDIATED_QUOTE_PREFIX_PATTERN.search(
            normalized_scope_text[-224:]
        )
        or NONHUMAN_OR_ARTIFACT_QUOTE_OWNER_PATTERN.search(
            normalized_scope_text[-224:]
        )
    ):
        tokens.append("inferred_artifact_context")
    return tuple(dict.fromkeys(tokens))


def _contextual_source_label(
    text: str,
    content_start: int,
    span_start: int,
    span_end: int,
    source_label: str,
    quoted: bool = False,
) -> str:
    source_label = _sanitize_external_source_label(source_label)
    context = _preceding_clause_context(text, content_start, span_start)
    current_and_context = context[-80:] + text[span_start:span_end]
    current_value = text[span_start:span_end].lstrip()
    explicit_label_type = _external_source_label_type(
        source_label, quoted=quoted
    )
    if quoted:
        context_tokens = _quoted_context_source_tokens(
            text, span_start, span_end
        )
        if context_tokens:
            existing_tokens = {
                part.strip() for part in re.split(r"[｜|]", source_label)
            }
            for token in context_tokens:
                if token not in existing_tokens:
                    source_label = f"{source_label}｜{token}"
            return source_label
        clause_start = max(
            (text.rfind(mark, 0, span_start) for mark in "。！？；\n"),
            default=-1,
        ) + 1
        _, direct_source_reset = _direct_source_scoped_prefix(
            text[clause_start:span_start]
        )
        if direct_source_reset:
            return source_label
    # A comma separates the consequent syntactically, but it does not release
    # that proposition from an opening condition.  Carry a typed internal
    # scope token so neither fact nor story coverage can promote a hypothetical
    # consequent into a current assertion.
    if (
        not quoted
        and (
            CONDITIONAL_ANTECEDENT_CONTEXT_PATTERN.match(context)
            or (
                ONLY_IF_ANTECEDENT_CONTEXT_PATTERN.match(context)
                and ONLY_IF_CONSEQUENT_PATTERN.match(current_value)
            )
        )
        and "inferred_nonasserted_context" not in {
            part.strip() for part in re.split(r"[｜|]", source_label)
        }
    ):
        source_label = f"{source_label}｜inferred_nonasserted_context"
    # Non-factive attitudes introduce a proposition without asserting that it
    # happened.  Preserve that scope on the proposition span so neither the
    # fact parser nor the story parser can promote a feared or hoped-for event.
    if (
        not quoted
        and FIRST_PERSON_NONFACTIVE_ATTITUDE_PATTERN.search(context[-48:])
        and re.match(r"(?:他|她|对方|老板|同事|朋友|公司)", current_value)
        and "inferred_nonfactive_context" not in {
            part.strip() for part in re.split(r"[｜|]", source_label)
        }
    ):
        source_label = f"{source_label}｜inferred_nonfactive_context"
    # A new first-person ownership clause resets provenance inherited through
    # an earlier comma-separated report.  An explicit section label still
    # wins, but ordinary ``同事说…，但我认为…`` must not convert the user's
    # own judgment into secondhand speech.
    if (
        not quoted
        and explicit_label_type not in {"secondhand", "unverified_artifact"}
        and (
            FIRST_PERSON_EPISTEMIC_OWNER_PATTERN.match(current_value)
            or FIRST_PERSON_EPISTEMIC_COMPLEMENT_CONTEXT_PATTERN.search(
                context[-96:]
            )
            or (
                (
                    FIRST_PERSON_EXPERIENCE_OWNER_PATTERN.match(current_value)
                    or FIRST_PERSON_PREDICTION_OWNER_PATTERN.match(current_value)
                )
                and UNQUOTED_REPORTING_CONTEXT_PATTERN.search(context[-48:])
                is None
            )
        )
    ):
        return source_label
    # Textual provenance is stronger than a user-supplied outer label.  A
    # label such as "我的观察" cannot upgrade "据秘书转述" into direct
    # observation.  We preserve the original label while appending the
    # deterministic scope marker used by the validator.
    if quoted and PROXY_QUOTE_CONTEXT_PATTERN.search(context[-64:]):
        return (
            source_label
            if explicit_label_type == "secondhand"
            else f"{source_label}｜inferred_secondhand_context"
        )
    direct_human_speech = quoted and _has_direct_human_speech_frame(
        text, span_start, span_end
    )
    contained_quote_ranges = [
        (quote_start, quote_end)
        for quote_start, quote_end in _actual_quote_ranges(text)
        if span_start <= quote_start and quote_end <= span_end
    ]
    contains_simple_direct_quote = bool(
        contained_quote_ranges
        and not NESTED_REPORTING_CHAIN_PATTERN.search(current_and_context)
        and any(
            _has_direct_human_speech_frame(text, quote_start, quote_end)
            for quote_start, quote_end in contained_quote_ranges
        )
    )
    second_person_answer_request = bool(
        SECOND_PERSON_REPORT_REQUEST_PATTERN.search(context[-96:])
        or SECOND_PERSON_REPORT_REQUEST_SCOPE_PATTERN.search(context[-128:])
    )
    nested_reporting_match = NESTED_REPORTING_CHAIN_PATTERN.search(
        current_and_context
    )
    unquoted_reporting_match = (
        UNQUOTED_REPORTING_CONTEXT_PATTERN.search(context[-80:])
        if not second_person_answer_request
        else None
    )
    hearsay_starts = [
        match.start()
        for match in (
            nested_reporting_match,
            SECONDHAND_CONTEXT_MARKERS.search(current_and_context),
            (
                HEARSAY_ATTRIBUTION_PATTERN.search(current_and_context)
                if not second_person_answer_request
                else None
            ),
            unquoted_reporting_match,
        )
        if match is not None
    ]
    hearsay_start = (
        min(hearsay_starts)
        if hearsay_starts
        and (nested_reporting_match is not None or not direct_human_speech)
        and not contains_simple_direct_quote
        else None
    )
    artifact_match = (
        PREFIX_ARTIFACT_ATTRIBUTION_PATTERN.search(current_and_context)
        if not quoted
        else None
    )
    # When two sources are nested, the first visible attribution owns the
    # proposition: ``录音里他说...`` is artifact-borne, while
    # ``他说，系统显示...`` remains a secondhand report.  This preserves the
    # provenance chain without selecting a globally stronger-looking token.
    if hearsay_start is not None and (
        artifact_match is None or hearsay_start < artifact_match.start()
    ):
        return (
            source_label
            if explicit_label_type == "secondhand"
            else f"{source_label}｜inferred_secondhand_context"
        )
    if artifact_match is not None:
        return (
            source_label
            if explicit_label_type == "unverified_artifact"
            else f"{source_label}｜inferred_artifact_context"
        )
    if hearsay_start is not None:
        return (
            source_label
            if explicit_label_type == "secondhand"
            else f"{source_label}｜inferred_secondhand_context"
        )
    # Source qualifications commonly follow the proposition they qualify:
    # “X happened, which a colleague later told me.”  Look only to the end of
    # the same sentence, and only accept explicit provenance constructions, so
    # an unrelated later sentence cannot rewrite the earlier source.
    sentence_end_candidates = [
        position
        for mark in "。！？；\n"
        for position in [text.find(mark, span_end)]
        if position >= 0
    ]
    sentence_end = min(sentence_end_candidates, default=len(text))
    postfix_context = text[span_end:sentence_end]
    if POSTFIX_ARTIFACT_ATTRIBUTION_PATTERN.search(postfix_context[:128]):
        return (
            source_label
            if explicit_label_type == "unverified_artifact"
            else f"{source_label}｜inferred_artifact_context"
        )
    if POSTFIX_SECONDHAND_ATTRIBUTION_PATTERN.search(postfix_context[:96]):
        return (
            source_label
            if explicit_label_type == "secondhand"
            else f"{source_label}｜inferred_secondhand_context"
        )
    cross_sentence_context = text[span_end : min(len(text), span_end + 160)]
    if quoted and CROSS_SENTENCE_QUOTE_SECONDHAND_PATTERN.search(
        cross_sentence_context
    ):
        return (
            source_label
            if explicit_label_type == "secondhand"
            else f"{source_label}｜inferred_secondhand_context"
        )
    return source_label


def _negated_report_scope_active(context: str) -> bool:
    negations = list(NEGATED_REPORT_MARKERS.finditer(context))
    if not negations:
        return False
    contrasts = list(LEADING_SCOPE_RESET_PATTERN.finditer(context))
    return not contrasts or contrasts[-1].start() < negations[-1].start()


def generate_source_spans(
    input_id: str, text: str, start_counter: int = 1
) -> list[dict[str, Any]]:
    quote_ranges = _actual_quote_ranges(text)
    spans: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str, bool]] = set()
    counter = start_counter
    line_start = 0
    for line in text.splitlines(keepends=True) or [text]:
        line_end = line_start + len(line.rstrip("\r\n"))
        raw_line = text[line_start:line_end]
        label_match = re.match(r"\s*\[([^\]]+)\]\s*", raw_line)
        source_ref = "input"
        source_label = "input"
        content_start = line_start
        if label_match:
            source_label = label_match.group(1).strip()
            source_ref = re.split(r"[｜|]", source_label, maxsplit=1)[0].strip() or "input"
            content_start = line_start + label_match.end()
        line_quotes = [item for item in quote_ranges if content_start <= item[0] and item[1] <= line_end]
        clauses = _clause_ranges(text, content_start, line_end, line_quotes)
        atomic_clauses = [
            atomic
            for clause_start, clause_end in clauses
            for atomic in _atomic_ranges(
                text, clause_start, clause_end, line_quotes
            )
        ]
        candidates: list[tuple[int, int, bool]] = [
            (start, end, False) for start, end in atomic_clauses
        ]
        # A reaction clause can contain both an observable communication event
        # and the user's named experience.  The finite event parser keeps the
        # event atom (``我收到消息``), while this overlapping source anchor
        # preserves the complete experience (``我收到消息后很难过``).  Source
        # spans already support bounded overlap for quotations; no paraphrase
        # or synthetic text is introduced here.
        for clause_start, clause_end in clauses:
            clause_value = text[clause_start:clause_end]
            if (
                re.match(
                    r"\s*(?:我|本人)(?:自己|本人)?\s*"
                    r"收到(?:消息|邮件|通知)(?:后|以后|之后)",
                    clause_value,
                )
                and is_explicit_feeling(clause_value)
            ):
                candidates.append((clause_start, clause_end, False))
        for quote_start, quote_end in line_quotes:
            containing = next(
                ((start, end) for start, end in atomic_clauses if start <= quote_start and quote_end <= end),
                (content_start, line_end),
            )
            prefix = text[containing[0]:quote_start]
            suffix = text[quote_end:containing[1]]
            opening_position = quote_start - 1
            prefix_without_opening = text[
                containing[0] : opening_position
                if opening_position >= containing[0]
                and text[opening_position] in "“‘\"'"
                else quote_start
            ]
            communication_match = PRE_QUOTE_COMMUNICATION_EVENT_PATTERN.search(
                prefix_without_opening
            )
            if communication_match is not None:
                event_start = containing[0] + communication_match.start("event")
                event_end = containing[0] + communication_match.end("event")
                event_range = _trim_range(text, event_start, event_end)
                if event_range:
                    candidates.append((event_range[0], event_range[1], False))
            if (
                NEGATED_REPORT_MARKERS.search(prefix[-24:])
                or PRE_QUOTE_NONASSERTION_PATTERN.search(prefix[-32:])
                or POST_QUOTE_DENIAL_PATTERN.search(suffix[:32])
            ):
                continue
            trimmed = _trim_range(text, quote_start, quote_end)
            if trimmed:
                candidates.append((trimmed[0], trimmed[1], True))
            internal_clauses = _clause_ranges(
                text, quote_start, quote_end, []
            )
            for internal_start, internal_end in internal_clauses:
                for atomic_start, atomic_end in _atomic_ranges(
                    text, internal_start, internal_end, []
                ):
                    candidates.append((atomic_start, atomic_end, True))
        for start, end, quoted in sorted(candidates, key=lambda item: (item[0], item[1], item[2])):
            value = text[start:end]
            if not value or all(character in "。！？；，,:：" for character in value):
                continue
            preceding_context = _preceding_clause_context(text, content_start, start)
            preceding_observation = derive_observation_type(
                preceding_context.strip()
            )
            if (
                _negated_report_scope_active(preceding_context[-48:])
                and preceding_observation != "negative_report_event"
                and not LEADING_SCOPE_RESET_PATTERN.match(value)
                and derive_observation_type(value) is None
            ):
                continue
            span_source_label = _contextual_source_label(
                text, content_start, start, end, source_label, quoted=quoted
            )
            signature = (start, end, source_ref, quoted)
            if signature in seen:
                continue
            seen.add(signature)
            spans.append(
                {
                    "id": f"SP{counter}",
                    "input_id": input_id,
                    "source_ref": source_ref,
                    "source_label": span_source_label,
                    "start": start,
                    "end": end,
                    "text": value,
                    "quoted": quoted,
                    "sha256": sha256_text(value),
                }
            )
            counter += 1
        line_start += len(line)
    if not spans and text:
        trimmed = _trim_range(text, 0, len(text))
        if trimmed:
            value = text[trimmed[0]:trimmed[1]]
            spans.append(
                {
                    "id": f"SP{counter}",
                    "input_id": input_id,
                    "source_ref": "input",
                    "source_label": "input",
                    "start": trimmed[0],
                    "end": trimmed[1],
                    "text": value,
                    "quoted": False,
                    "sha256": sha256_text(value),
                }
            )
            counter += 1
    # Safety meaning depends on full-input context: a quote may be fictional,
    # translated, negated, historical, or followed by a reality override.
    # Deterministic backstop signals therefore bind to one exact full-context
    # span rather than reclassifying isolated child spans after scope has been
    # removed.
    full_signal_types = expected_safety_signal_types(text) if text else set()
    if full_signal_types:
        trimmed = _trim_range(text, 0, len(text))
        if trimmed:
            start, end = trimmed
            existing_full_context = next(
                (
                    item
                    for item in spans
                    if item.get("start") == start
                    and item.get("end") == end
                    and item.get("quoted") is False
                ),
                None,
            )
            if existing_full_context is None:
                value = text[start:end]
                spans.append(
                    {
                        "id": f"SP{counter}",
                        "input_id": input_id,
                        "source_ref": "input",
                        "source_label": "input｜aggregate_safety_context",
                        "start": start,
                        "end": end,
                        "text": value,
                        "quoted": False,
                        "sha256": sha256_text(value),
                    }
                )
                counter += 1
    # A resolution may be split by ordinary clause segmentation, for example
    # “我确认上一句是虚构测试，不是现实事件”。  Preserve one full-context
    # anchor so the ledger never records a conclusion from a semantically
    # incomplete fragment.
    if text and _candidate_resolution_type(text) is not None:
        trimmed = _trim_range(text, 0, len(text))
        if trimmed:
            start, end = trimmed
            existing_full_context = next(
                (
                    item
                    for item in spans
                    if item.get("start") == start
                    and item.get("end") == end
                    and item.get("quoted") is False
                ),
                None,
            )
            if existing_full_context is None:
                value = text[start:end]
                spans.append(
                    {
                        "id": f"SP{counter}",
                        "input_id": input_id,
                        "source_ref": "input",
                        "source_label": "input｜aggregate_candidate_resolution_context",
                        "start": start,
                        "end": end,
                        "text": value,
                        "quoted": False,
                        "sha256": sha256_text(value),
                    }
                )
    return spans


def _quote_is_bounded(text: str, exact_quote: str) -> bool:
    start = 0
    ranges = _actual_quote_ranges(text)
    while True:
        position = text.find(exact_quote, start)
        if position < 0:
            return False
        end = position + len(exact_quote)
        if any(left <= position and end <= right for left, right in ranges):
            return True
        start = position + 1


def _quote_is_interrogative_speech_act(quote_text: str) -> bool:
    """Distinguish a question from a declarative report of uncertainty."""
    value = quote_text.strip()
    if not value:
        return False
    if value.endswith(("?", "？")):
        return True
    if QUOTE_CHINESE_TERMINAL_TAG_PATTERN.search(value):
        return True
    if QUOTE_ENGLISH_INTERROGATIVE_AUX_PATTERN.search(value):
        return True
    if re.search(r"(?:吗|呢|么)\s*[。.!！]?$", value):
        return True
    polar = QUOTE_INTERNAL_POLAR_QUESTION_PATTERN.search(value)
    if polar is None:
        return False
    # ``我不知道手机有没有送修`` states uncertainty.  The embedded polar
    # complement is not itself a request for an answer.
    return QUOTE_DECLARATIVE_UNCERTAINTY_PATTERN.search(value) is None


def _direct_quote_scope_error(
    input_text: str,
    span: dict[str, Any],
    *,
    allow_past_attribution: bool = False,
) -> tuple[str, str] | None:
    """Return a fail-closed reason when a quoted span is not an assertion.

    Atomic subspans remain useful for classifying material inside a long quote,
    but a stated position must preserve the complete visible quotation. The
    surrounding clause must also assert the quote rather than wish, imagine,
    condition, or later deny it.
    """
    start = span.get("start")
    end = span.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return ("DIRECT_QUOTE_NOT_BOUNDED", "direct quote range is invalid")
    containing = [
        (left, right)
        for left, right in _actual_quote_ranges(input_text)
        if left <= start and end <= right
    ]
    if not containing:
        return (
            "DIRECT_QUOTE_NOT_BOUNDED",
            "direct_quote must be inside one visible quotation",
        )
    quote_start, quote_end = min(containing, key=lambda item: item[1] - item[0])
    if (start, end) != (quote_start, quote_end):
        return (
            "DIRECT_QUOTE_SCOPE_TRUNCATED",
            "stated positions must preserve the complete visible quotation, including qualifications",
        )
    clause_start = max(
        (input_text.rfind(mark, 0, quote_start) for mark in "。！？；\n"),
        default=-1,
    ) + 1
    clause_end_candidates = [
        position
        for mark in "。！？；\n"
        for position in [input_text.find(mark, quote_end)]
        if position >= 0
    ]
    clause_end = min(clause_end_candidates, default=len(input_text))
    prefix = input_text[clause_start:quote_start]
    prefix, _ = _direct_source_scoped_prefix(prefix)
    suffix = input_text[quote_end:clause_end]
    followup = input_text[quote_end : min(len(input_text), quote_end + 96)]
    quote_text = input_text[quote_start:quote_end].strip()
    quote_context_tokens = set(
        _quoted_context_source_tokens(input_text, quote_start, quote_end)
    )
    # A corrective contrast starts a new assertion scope inside the same
    # sentence.  Earlier negation still governs the denied quote, but must not
    # swallow the affirmative replacement in ``没有说 X，而是说 Y``.
    quote_scope_prefix = prefix
    scope_resets = list(LEADING_SCOPE_RESET_PATTERN.finditer(prefix))
    if scope_resets:
        quote_scope_prefix = prefix[scope_resets[-1].start() :]
    owned_transform_ranges = set(transform_payload_ranges(input_text)) - set(
        disowned_transform_payload_ranges(input_text)
    )
    if (quote_start, quote_end) in owned_transform_ranges:
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "content owned by a transform task is not a current real-world assertion",
        )
    resolution_scope = _candidate_resolution_scope(input_text)
    if (
        _candidate_resolution_type(input_text) is not None
        and quote_end <= len(resolution_scope)
    ):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "a quoted candidate-resolution target identifies a prior observation; it is not a current speech act",
        )
    if re.search(
        r"(?:不要|别|不能|禁止|请勿|无需|不必).{0,80}"
        r"(?:回答成|统一回答成|写成|改成|表述为|说成|概括成)"
        r"\s*[“‘\"「『']?\s*$",
        prefix[-112:],
    ):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "a quoted answer example inside an instruction is not a current speech act",
        )
    if "inferred_nonasserted_context" in quote_context_tokens:
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "non-real, example, or meta material is not a current real-world assertion",
        )
    if "inferred_secondhand_context" in quote_context_tokens:
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "a secondhand or proxy carrier cannot establish a direct quotation",
        )
    if "inferred_artifact_context" in quote_context_tokens:
        return (
            "DIRECT_QUOTE_PROVENANCE_UNKNOWN",
            "an unverified artifact does not establish a human speaker for a direct quotation",
        )
    if re.search(
        r"(?:电影|小说|剧本|游戏|歌词|台词|例句|虚构|测试(?:文本|输入|用例)?)"
        r".{0,20}[：:]?\s*$",
        prefix[-64:],
        re.IGNORECASE,
    ):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "fictional, example, or test material is not a current real-world assertion",
        )
    if NONREAL_QUOTE_CONTEXT_PATTERN.search(prefix[-96:]):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "non-real narrative material is not a current real-world assertion",
        )
    if re.search(
        r"(?:等|待).{0,24}(?:之后|以后|后)?[，,].{0,16}"
        r"(?:将会|会|将|可能|预计|打算|准备)?(?:说|讲|表示|写|回复)"
        r"\s*[：:]?\s*[“‘\"']?\s*$",
        prefix[-80:],
    ):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "a pending condition does not establish a completed speech act",
        )
    if re.search(
        r"(?:明天|后天|过(?:一|二|两|三|四|五|六|七|八|九|十|几|\d+)"
        r"(?:天|日|周|个月|月|年)|"
        r"(?:一|二|两|三|四|五|六|七|八|九|十|几|\d+)"
        r"(?:天|日|周|个月|月|年)后|到时(?:候)?|"
        r"下周|下个月|下季度|明年|将来|未来|以后|届时).{0,24}"
        r"(?:将会|会|可能|预计|打算|准备)?(?:说|讲|表示|写|回复)"
        r"\s*[：:]?\s*[“‘\"']?\s*$",
        prefix[-64:],
    ):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "a future or hypothetical utterance is not a current assertion",
        )
    if re.search(
        r"(?:只是|仅仅|仅)?(?:引用|转发|转述|复述)|"
        r"转发(?:了)?(?:同事|朋友|别人|他人).{0,12}(?:话|内容|消息)",
        prefix[-64:],
    ):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "forwarded or merely quoted material is not the user's current assertion",
        )
    if re.search(
        r"^[”’\"']?\s*(?:并)?(?:不是|并非)(?:我|本人)的"
        r"(?:判断|看法|观点|结论|感受)|"
        r"^[”’\"']?.{0,24}不代表(?:我|本人).{0,12}"
        r"(?:认为|觉得|判断|同意|认可)",
        suffix[:64],
    ):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "explicitly disowned quoted material is not the user's current assertion",
        )
    if (
        _quote_is_interrogative_speech_act(quote_text)
        or QUOTE_QUESTION_PREFIX_PATTERN.search(prefix[-48:])
    ):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "an interrogative quote is not the speaker's stated position",
        )
    if (
        re.search(
            r"(?:改口|更正|撤回|收回).{0,20}从\s*[“‘\"']?\s*$",
            prefix,
        )
        and re.match(r"^[”’\"']?\s*改(?:为|成)", suffix)
    ):
        return (
            "DIRECT_QUOTE_SUPERSEDED",
            "the source side of an explicit correction is historical, not current",
        )
    if SEMANTIC_QUOTE_SUPERSEDED_PATTERN.search(followup):
        return (
            "DIRECT_QUOTE_SUPERSEDED",
            "a visibly retracted or corrected quote is not a current stated position",
        )
    if NEGATED_QUOTE_PREFIX_PATTERN.search(quote_scope_prefix[-48:]):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "a contrastively denied quote is not the speaker's stated position",
        )
    if PROXY_QUOTE_CONTEXT_PATTERN.search(prefix[-64:]):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "a quoted third-party utterance cannot be reassigned to the person reading it",
        )
    if (
        CROSS_SENTENCE_QUOTE_SECONDHAND_PATTERN.search(followup)
        or POSTFIX_SECONDHAND_ATTRIBUTION_PATTERN.search(followup)
    ):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "a quote explicitly attributed as secondhand cannot be treated as a direct current position",
        )
    if SEMANTIC_QUOTE_DENIAL_PATTERN.search(
        quote_scope_prefix[-64:] + suffix[:64]
    ):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "a semantically denied or disowned quote is not another person's stated position",
        )
    if PRE_QUOTE_NONASSERTION_PATTERN.search(quote_scope_prefix[-48:]):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "a wished, imagined, conditional, or example quote is not another person's stated position",
        )
    if (
        re.match(
            r"^\s*(?:(?:但是|但|可是|然而|不过|却)\s*)?只有",
            quote_scope_prefix,
        )
        and re.search(r"^[”’\"']?\s*[，,]?[^。！？；\n]{0,48}才", suffix)
    ):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "a quote inside a 只有…才 condition is not a current speech act",
        )
    if (
        NEGATED_REPORT_MARKERS.search(quote_scope_prefix[-32:])
        or POST_QUOTE_DENIAL_PATTERN.search(suffix[:48])
    ):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "a negated or denied quote is not another person's stated position",
        )
    if re.search(
        r"(?:想|希望|打算|准备|计划|考虑|可能|也许|或许|假设)"
        r".{0,8}(?:说|讲|表示|回复|写)\s*[：:]?\s*[“‘\"']?\s*$",
        prefix[-64:],
    ):
        return (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "an intended or hypothetical utterance is not a current speech act",
        )
    if _quoted_speaker_role(input_text, quote_start, quote_end) == "unknown":
        return (
            "DIRECT_QUOTE_PROVENANCE_UNKNOWN",
            "a stated position requires a current speech act and an identifiable speaker",
        )
    if (
        _direct_quote_has_past_scope(input_text, span)
        and not allow_past_attribution
    ):
        return (
            "DIRECT_QUOTE_NOT_CURRENT",
            "a past utterance is not a current stated position",
        )
    return None


def _nested_quote_is_reported_proposition(
    input_text: str,
    span_start: int,
    quote_start: int,
) -> bool:
    """Distinguish a reported proposition from an embedded artifact label."""
    prefix = input_text[span_start:quote_start]
    if re.search(
        r"(?:没有|没|未|并未|从未|不曾).{0,8}"
        r"(?:说|讲|表示|称|告诉|回复|写)(?:过)?\s*$",
        prefix,
    ):
        return False
    return bool(
        TRANSFORM_OPERATION_PATTERN.search(prefix)
        or PROXY_QUOTE_CONTEXT_PATTERN.search(prefix[-96:])
        or re.search(
            r"(?:电影|小说|剧本|游戏|歌词|台词|例句|虚构|测试(?:文本|输入|用例)?)"
            r".{0,20}[：:]?\s*[“‘\"「『']?\s*$",
            prefix,
            re.IGNORECASE,
        )
        or re.search(
            r"(?:引用|转发|转述|复述)|"
            r"(?:说|讲|表示|称|告诉|告知|回复|回答|发来原话|写道)"
            r"\s*[：:]?\s*[“‘\"「『']?\s*$",
            prefix,
        )
    )


def _span_contains_reported_quote(
    input_text: str, span: dict[str, Any]
) -> bool:
    if span.get("quoted") is True:
        return False
    start = span.get("start")
    end = span.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return False
    return any(
        start <= quote_start
        and quote_end <= end
        and _nested_quote_is_reported_proposition(input_text, start, quote_start)
        for quote_start, quote_end in _actual_quote_ranges(input_text)
    )


def _semantic_text_for_span(
    input_text: str, span: dict[str, Any], exact_quote: str | None = None
) -> str:
    """Return the span text with nested quoted propositions masked.

    A reporting clause and the proposition it quotes are distinct semantic
    objects.  Non-quoted parent spans therefore retain only their own words;
    quoted child spans retain their complete visible content.  Offsets are
    preserved while masking so all downstream anchors remain auditable.
    """
    value = exact_quote if isinstance(exact_quote, str) else str(span.get("text", ""))
    if span.get("quoted") is True:
        return value.strip()
    start = span.get("start")
    end = span.get("end")
    if not isinstance(start, int) or not isinstance(end, int) or end < start:
        return value.strip()
    if input_text[start:end] != value:
        return value.strip()
    characters = list(value)
    span_has_transform_operation = bool(
        TRANSFORM_OPERATION_PATTERN.search(input_text[start:end])
    )
    for quote_start, quote_end in _actual_quote_ranges(input_text):
        if quote_end <= start or quote_start >= end:
            continue
        if not span_has_transform_operation and not _nested_quote_is_reported_proposition(
            input_text, start, quote_start
        ):
            continue
        mask_start = max(start, quote_start - 1) - start
        mask_end = min(end, quote_end + 1) - start
        characters[mask_start:mask_end] = " " * (mask_end - mask_start)
    return "".join(characters).strip()


def _direct_quote_has_past_scope(
    input_text: str, span: dict[str, Any]
) -> bool:
    """Return whether the surrounding clause explicitly dates a quote in the past."""
    start = span.get("start")
    end = span.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return True
    clause_start = max(
        (input_text.rfind(mark, 0, start) for mark in "。！？；\n"),
        default=-1,
    ) + 1
    digit_translation = str.maketrans("０１２３４５６７８９", "0123456789")
    prefix = input_text[clause_start:start].translate(digit_translation)
    today = datetime.now().astimezone().date()
    explicit_today = re.compile(
        rf"(?:今天|今日)\s*[（(]\s*{today.year}\s*年\s*"
        rf"0?{today.month}\s*月\s*0?{today.day}\s*日\s*[）)]"
    )
    prefix = explicit_today.sub("今天", prefix)
    if PAST_QUOTE_SCOPE_PATTERN.search(prefix):
        return True
    if GENERIC_PAST_QUOTE_PREFIX_PATTERN.search(prefix):
        return True
    if re.search(
        r"(?:已经|早已|曾经|曾).{0,16}"
        r"(?:说|讲|表示|称|回答|回复|写道|提到).{0,8}过?\s*[“‘\"']?\s*$|"
        r"(?:说|讲|表示|称|回答|回复|写道|提到)过\s*[“‘\"']?\s*$",
        prefix,
    ):
        return True
    # A quote can be dated immediately after it.  Accept only deictic
    # constructions that point back to the quote, rather than treating any
    # unrelated later mention of the past as scope for the quotation.
    followup = input_text[end : min(len(input_text), end + 96)].translate(
        digit_translation
    )
    return bool(POST_QUOTE_PAST_SCOPE_PATTERN.search(followup))


def derive_stated_position_type(exact_quote: str) -> str | None:
    """Classify only bounded current speech acts as stated positions.

    A visible quotation proves that words were presented, not that every
    proposition inside the quotation is a fact or the speaker's current
    commitment. Third-party claims, motives, predictions, and speculation must
    keep their own epistemic kind.
    """
    value = exact_quote.strip().rstrip("。！？；!?; ")
    if not value or len(value) > 56:
        return None
    if STORY_MARKERS.search(value):
        return None
    if re.search(
        r"(?:老板|公司|他|她|对方).{0,16}"
        r"(?:下周|明天|以后|未来|一定|肯定|必然|注定|会|将|要)",
        value,
    ):
        return None
    if re.fullmatch(
        r"(?:这次|本次)?(?:你|你们)(?:先)?(?:不用|无需|不需要|不要)"
        r"参加(?:这次|本次|周五|周六)?(?:的)?(?:会议|汇报|见面|活动)?"
        r"(?:，(?:我|我们).{0,16}(?:把|核对|处理|完成|确认).{0,18})?",
        value,
    ):
        return "decision_or_boundary"
    if re.fullmatch(
        r"(?:我)?不想再继续约会"
        r"(?:，(?:我)?也不会参加(?:周[一二三四五六日天]|这周|本周)?(?:的)?见面)?",
        value,
    ):
        return "decision_or_boundary"
    if re.fullmatch(
        r"(?:我|我们)?(?:会|不会|愿意|不愿意|决定|选择|打算|计划|准备)?"
        r"(?:留下|离开|参加(?:会议|活动)?|不参加(?:会议|活动)?|"
        r"回复|不回复|完成(?:任务|工作|交接)?|继续(?:合作|联系)?|"
        r"停止(?:合作|联系)?|保持(?:距离|联系)|不再联系|搬走|交接)",
        value,
    ):
        return "commitment_or_plan"
    if re.fullmatch(
        r"(?:我|我们)?(?:已经|已)?决定(?:要)?(?:留下|离开|走(?:了)?)",
        value,
    ):
        return "commitment_or_plan"
    if re.fullmatch(
        r"(?:我|我们)?(?:同意|不同意|接受|拒绝|需要时间|希望暂停|"
        r"要求停止|不接受|不愿继续)",
        value,
    ):
        return "decision_or_boundary"
    if re.fullmatch(
        r"我的(?:岗位)?职责和审批权限(?:仍|依然)?保持不变",
        value,
    ):
        return "current_role_statement"
    return None


def derive_attributed_statement_type(exact_quote: str) -> str | None:
    """Recognize a bounded declarative utterance without endorsing its content.

    This layer records only that the user supplied words as a named speaker's
    direct statement.  The proposition inside the quotation remains outside the
    observable-fact layer and may still be false, mistaken, strategic, or stale.
    Scope, speaker, secondhand, fiction, denial, and proxy checks are enforced by
    ``_direct_quote_scope_error`` and ``derive_claim_kind_for_span``.
    """
    value = exact_quote.strip().rstrip("。！；!; ")
    if not value or len(value) > 160:
        return None
    if re.search(r"[?？]", value):
        return None
    if not re.search(r"[A-Za-z0-9一-鿿]", value):
        return None
    return "reported_utterance"


def derive_observation_type(
    exact_quote: str, span: dict[str, Any] | None = None
) -> str | None:
    """Return a finite atomic observation type or fail closed.

    This is deliberately narrower than general language understanding. It
    accepts source-anchored events and states that the runtime can recognize,
    while rejecting clauses that still contain an interpretation boundary.
    """
    value = exact_quote.strip()
    if not value:
        return None
    if isinstance(span, dict):
        internal_context = {
            part.strip()
            for part in re.split(r"[｜|]", str(span.get("source_label", "")))
        }
        if internal_context & {
            "inferred_nonfactive_context",
            "inferred_nonasserted_context",
        }:
            return None
    parsed = parse_observation_prefix(value)
    if parsed is None:
        return None
    observation_type, end = parsed
    if not _observation_parse_consumes_full_value(value, end):
        return None
    return observation_type


def _direct_user_feeling_prefix(prefix: str) -> bool:
    """Accept only bounded discourse material before the experiencer ``我``.

    The presence of ``我`` somewhere before a feeling word is insufficient:
    in ``他以为我很难过`` the main assertion belongs to another subject.  A
    direct self-report either starts with the experiencer or follows a bounded
    temporal, reflective, causal, contrastive, or causative frame.
    """
    value = prefix.strip()
    if not value:
        return True
    if re.fullmatch(
        r"(?:今天|今日|昨天|昨晚|最近|现在|此刻|当时|那时|刚才|刚刚|"
        r"目前|一直以来|说实话|坦白说|老实说|对我来说)",
        value,
    ):
        return True
    if re.fullmatch(
        r"(?:一)?想到.{1,40}|(?:每当|当).{1,36}(?:时|的时候)|"
        r"在.{1,32}(?:时|的时候)|"
        r"(?:每次|每回).{1,32}(?:前|后|时|的时候)|"
        r"(?:回到|到达|离开|结束|完成|收到|看到|听到).{1,32}"
        r"(?:后|以后|之后)|"
        r"(?:面对|碰到|遇到|见到).{1,32}(?:时|的时候)",
        value,
    ):
        return True
    return bool(
        re.search(
            r"(?:所以|因此|因而|于是|但|可是|不过|然而|却|让|使|令)\s*$",
            value,
        )
    )


def is_explicit_feeling(exact_quote: str) -> bool:
    value = exact_quote.strip()
    for feeling in FEELING_MARKERS.finditer(value):
        clause_start = max(
            (value.rfind(mark, 0, feeling.start()) for mark in "，,。！？；\n"),
            default=-1,
        ) + 1
        if clause_start > 0 and EXTERNAL_FEELING_ATTRIBUTION_PATTERN.fullmatch(
            value[:clause_start]
        ):
            continue
        clause_prefix = value[clause_start:feeling.start()]
        self_positions = [match.start() for match in re.finditer(r"我", clause_prefix)]
        for position in reversed(self_positions):
            # Treat “我” as the experiencer only when the material between it
            # and the feeling is a bounded first-person modifier.  This
            # grammatical gate rejects every possessive noun phrase such as
            # “我女儿/我的邻居”, without maintaining an endless person list.
            bridge = clause_prefix[position + 1 :].strip()
            simple_bridge = re.fullmatch(
                r"(?:(?:自己|本人|现在|最近|今天|此刻|一直|仍然|仍|还|也|都|反而|"
                r"有点|有些|很|非常|特别|十分|挺|太|比较|相当|越来越|"
                r"真的|确实|明确|突然|莫名|感到|感觉|觉得|心里|内心|"
                rf"的感受是|{FIRST_PERSON_REACTION_EXPERIENCE_FRAGMENT})\s*)*",
                bridge,
            )
            prepositional_bridge = re.fullmatch(
                r"(?P<prep>对|为|因为|因|由于)"
                r"(?P<body>.{1,20}?)"
                r"(?P<tail>(?:(?:感到|感觉|觉得|心里|内心)"
                r"(?:有点|有些|很|非常|特别|十分|挺|太|比较|相当)?)|"
                r"(?:有点|有些|很|非常|特别|十分|挺|太|比较|相当))",
                bridge,
            )
            if prepositional_bridge is not None:
                body = prepositional_bridge.group("body")
                if (
                    re.search(r"说|讲|表示|声称|回答|回复|告诉|告知|转述", body)
                    or body.endswith("的")
                    or (
                        prepositional_bridge.group("prep") in {"因为", "因", "由于"}
                        and re.fullmatch(
                            r"(?:他|她|对方|老板|同事|朋友|家人|前任|伴侣|"
                            r"妻子|丈夫|女儿|儿子|姐姐|妹妹|哥哥|弟弟|邻居)",
                            body,
                        )
                    )
                ):
                    prepositional_bridge = None
            if simple_bridge is None and prepositional_bridge is None:
                continue
            attribution = clause_prefix[:position]
            if not _direct_user_feeling_prefix(attribution):
                continue
            if re.search(
                r"(?:他|她|对方|老板|同事|朋友|医生|老师|家人|亲属|"
                r"前任|伴侣|妻子|丈夫|女儿|儿子|姐姐|妹妹|哥哥|弟弟|邻居)"
                r"(?:对|向|冲着|因|因为)\s*$",
                attribution,
            ):
                continue
            if re.search(
                r"(?:假装|装作|佯装|故作|演得|表现得)\s*$",
                attribution,
            ):
                continue
            if re.search(
                r"(?:说|讲|认为|觉得|判断|声称|表示|称|告诉|告知)\s*$",
                attribution,
            ) and not re.search(
                r"(?:^|[，,])\s*我.{0,6}(?:说|讲|表示|称)\s*$",
                attribution,
            ):
                continue
            return True
    return False


EXTERNAL_FEELING_ATTRIBUTION_PATTERN = re.compile(
    r"^\s*(?:"
    r"(?:据|根据|按照).{1,24}(?:观察|判断|结论|说法|报告)|"
    r"(?:他|她|对方|老板|经理|同事|朋友|医生|老师|家人|亲属|前任|伴侣|"
    r"妈妈|母亲|爸爸|父亲|姐姐|妹妹|哥哥|弟弟|我姐|我妹|我妈|我爸)"
    r".{0,12}(?:说|表示|声称|断言|认为|觉得|判断|观察|发现|看出)"
    r"(?:\s*[，,]\s*(?:至少)?在.{1,16}看来)?|"
    r"(?:报告|测评|量表|筛查|截图|系统|模型|算法|结果)"
    r".{0,12}(?:写道|写着|显示|判定|判断|认为|提示|标注)"
    r")\s*[，,:：]\s*$"
)


def _feeling_preceding_sentence_context(
    input_text: str, span: dict[str, Any]
) -> str:
    """Return the same-sentence material before a feeling span.

    Source spans are deliberately atomic, but experiencer attribution often
    lives in the comma-delimited material immediately before the atomic span.
    Sentence punctuation, rather than commas, therefore bounds this context.
    """
    start = span.get("start")
    if not isinstance(start, int) or start <= 0:
        return ""
    sentence_start = max(
        (input_text.rfind(mark, 0, start) for mark in "。！？；\n"),
        default=-1,
    ) + 1
    return input_text[sentence_start:start]


def _is_current_user_explicit_feeling(
    exact_quote: str,
    span: dict[str, Any],
    input_text: str,
) -> bool:
    """Bind a named feeling to the current user's own asserted experience."""
    if _expected_source_type_for_span(span) in {
        "secondhand",
        "unverified_artifact",
    }:
        return False
    preceding_context = _feeling_preceding_sentence_context(input_text, span)
    if EXTERNAL_FEELING_ATTRIBUTION_PATTERN.fullmatch(preceding_context):
        return False
    value = _semantic_text_for_span(input_text, span, exact_quote)
    if not value or not is_explicit_feeling(value):
        return False
    if span.get("quoted") is True:
        start = span.get("start")
        end = span.get("end")
        if not isinstance(start, int) or not isinstance(end, int):
            return False
        containing = _quote_range_containing(input_text, start, end)
        if containing is None or _direct_quote_scope_error(input_text, span) is not None:
            return False
        return _quoted_speaker_role(input_text, *containing) == "user"
    if re.search(
        r"(?:测评|量表|筛查|报告|截图|系统|模型|算法|结果)"
        r".{0,20}(?:显示|判定|判断|认为|提示|写着|标注).{0,16}我",
        value,
    ):
        return False
    if re.search(
        r"(?:他|她|对方|老板|经理|同事|朋友|医生|老师|家人|亲属|前任|伴侣)"
        r".{0,12}(?:观察到|观察|发现|看出|认为|觉得|判断|声称|表示|说)"
        r".{0,12}我",
        value,
    ):
        return False
    return True


def detect_immediate_risk(text: str) -> bool:
    # Routing and artifact validation deliberately consume the same typed
    # extractor.  A second detector inevitably drifts and creates safety
    # cases that can route but cannot be anchored, or vice versa.
    return bool(expected_safety_signal_types(text))


HISTORICAL_TIME_PATTERN = (
    r"(?:昨天|前天|上周|去年|前年|十年前|多年前|很多年前|过去|曾经|以前|之前|"
    r"(?:\d+|[一二三四五六七八九十两]+)年前)"
)

HISTORICAL_EXTERNAL_THREAT_RESOLUTION_PATTERN = re.compile(
    rf"(?:{HISTORICAL_TIME_PATTERN}).{{0,96}}"
    r"(?:杀(?:了|死)?(?:我|你)|弄死(?:我|你)|伤害(?:我|你)|威胁).{0,96}?"
    r"(?:"
    r"(?:现在|如今|目前).{0,12}(?:没有|没|并无|不存在)(?:任何)?威胁|"
    r"警方(?:已经|已)?(?:处理|处置|介入).{0,20}"
    r"(?:现在|如今|目前).{0,8}(?:我|本人)?(?:很|已经|已)?安全|"
    r"警方(?:已经|已)?到场.{0,20}(?:危险|风险)(?:已经|已)?解除|"
    r"案件(?:已经|已)?结案(?:.{0,20}(?:现在|如今|目前)"
    r"(?:没有|没|并无|不存在)(?:任何)?(?:现实)?风险)?|"
    r"(?:当事人|对方|他|她)(?:已经|已)?去世.{0,12}(?:且|并且|也)?"
    r"(?:已经|已)?不可能(?:再)?(?:接近|靠近|找到|联系)"
    r")"
)

CURRENT_EXTERNAL_THREAT_RECURRENCE_PATTERN = re.compile(
    r"(?:但|可是|不过|然而)?(?:他|她|对方|前任|当事人)?"
    r"(?:现在|今晚|今天|当前|此刻).{0,16}"
    r"(?:又|再次|重新).{0,10}"
    r"(?:在(?:我家|我住处|家)?门外|发来|发消息|威胁|扬言|"
    r"堵我|跟踪|尾随|持刀|拿刀|带刀|有枪)"
)


def _strip_resolved_historical_external_threat(text: str) -> str:
    """Remove only a bounded past threat whose current resolution is explicit.

    A later recurrence remains outside the matched range and is still routed
    by the ordinary safety detector.  This is intentionally not a general
    "safe now" escape hatch.
    """
    return HISTORICAL_EXTERNAL_THREAT_RESOLUTION_PATTERN.sub("", text)


def _mask_resolved_noncurrent_risk_quotes(text: str) -> str:
    """Mask only quotes explicitly bound to old news or an ended chat.

    The surrounding non-current statement remains visible.  A later current
    recurrence outside the quote therefore continues through normal safety
    routing instead of inheriting the historical scope.
    """
    characters = list(text)
    for start, end in _actual_quote_ranges(text):
        prefix = text[max(0, start - 48) : start]
        suffix = text[end : min(len(text), end + 96)]
        local = prefix + suffix
        old_context = re.search(
            r"旧新闻|旧聊天|已经结束的.{0,6}聊天|转述.{0,6}旧新闻",
            local,
        )
        resolved = re.search(
            r"(?:不是|并非)(?:对我的)?现实威胁|"
            r"(?:当前|现在|目前)(?:并)?不存在(?:任何)?(?:现实)?风险|"
            r"对方(?:已经|已)?去世(?:多|很)?年",
            local,
        )
        recurrence = re.search(
            r"(?:现在|当前|今晚|今天|此刻).{0,16}"
            r"(?:又|再次|重新|发来|威胁|扬言)",
            prefix[-40:],
        )
        if old_context is not None and resolved is not None and recurrence is None:
            characters[start:end] = " " * (end - start)
    return "".join(characters)


def _is_affirmatively_resolved_historical_self_harm(clause: str) -> bool:
    """Accept only a direct, affirmative current recovery assertion."""
    return bool(
        re.fullmatch(
            rf"\s*(?:我|他|她)?(?:在)?{HISTORICAL_TIME_PATTERN}"
            rf"(?:我|他|她)?(?:曾经|当时)?\s*"
            r"(?:(?:想|要|准备)(?:去)?(?:死|自杀|轻生)|自杀|轻生|不想活)"
            r"\s*[，,]\s*"
            r"(?:现在|如今|目前)\s*(?:我|他|她)?\s*"
            r"(?:生活很好|状态很好|(?:已经|已|现已)(?:恢复|康复|好了)|"
            r"(?:很|目前)安全)"
            r"(?:\s*(?:[，,]|且|并且|而且|也)\s*(?:很|已经|已)?安全)?"
            r"[。！？；]?\s*",
            clause,
        )
    )


def _is_affirmatively_resolved_historical_medical(clause: str) -> bool:
    """Accept only an explicit clinician or hospital resolution statement."""
    return bool(
        re.fullmatch(
            rf"\s*(?:我|他|她)?(?:在)?{HISTORICAL_TIME_PATTERN}"
            r"(?:我|他|她)?(?:曾经|当时)?\s*"
            r"(?:胸痛|胸口(?:痛|疼)|呼吸困难)\s*[，,]\s*"
            r"(?:但\s*)?(?:(?:现在|如今|目前)\s*)?"
            r"(?:医生|医院)\s*(?:明确)?(?:确认|表示|说)\s*"
            r"(?:已经|已|现已)?(?:好了|恢复|康复|无碍|没事(?:了)?)"
            r"[。！？；]?\s*",
            clause,
        )
    )


RESOLVED_HISTORICAL_SELF_HARM_SEQUENCE_PATTERN = re.compile(
    rf"\s*(?:我|他|她)?(?:在)?{HISTORICAL_TIME_PATTERN}"
    rf"(?:我|他|她)?(?:曾经|当时)?\s*"
    r"(?:(?:想|要|准备)(?:去)?(?:死|自杀|轻生)|自杀|轻生|不想活)"
    r"\s*[。！？；]\s*"
    r"(?:现在|如今|目前)\s*(?:我|他|她)?\s*"
    r"(?:生活(?:很|挺)?好|状态(?:很|挺)?好|(?:已经|已|现已)(?:恢复|康复|好了))"
    r"(?:\s*(?:[，,]|且|并且|而且|也)\s*(?:很|已经|已)?安全)?"
    r"[。！？；]?\s*"
)
RESOLVED_HISTORICAL_MEDICAL_SEQUENCE_PATTERN = re.compile(
    rf"\s*(?:我|他|她)?(?:在)?{HISTORICAL_TIME_PATTERN}"
    r"(?:我|他|她)?(?:曾经|当时)?\s*"
    r"(?:胸痛|胸口(?:痛|疼)|呼吸困难)\s*[。！？；]\s*"
    r"(?:现在|如今|目前)?\s*(?:医生|医院)\s*(?:明确)?(?:确认|表示|说)\s*"
    r"(?:已经|已|现已)?(?:好了|恢复|康复|无碍|没事(?:了)?)"
    r"[。！？；]?\s*"
)
CURRENT_MEDICAL_RECURRENCE_PATTERN = re.compile(
    rf"{HISTORICAL_TIME_PATTERN}.{{0,36}}"
    r"(?:胸痛|胸口(?:痛|疼)|呼吸困难).{0,36}"
    r"(?:医生|医院).{0,12}(?:确认|表示|说).{0,8}"
    r"(?:好了|恢复|康复|无碍|没事(?:了)?).{0,24}"
    r"(?:现在|如今|目前).{0,12}(?:同样的痛|相同的痛|同样症状|相同症状)"
    r".{0,16}(?:又出现|再次出现|复发|越来越重|加重)"
)
CURRENT_SELF_HARM_PRONOUN_RECURRENCE_PATTERN = re.compile(
    r"(?:今晚|今天|现在|如今|目前|当前).{0,16}"
    r"(?:那个|这种|自伤|轻生|想死的?)?(?:念头|想法)"
    r".{0,12}(?:又回来了|再次出现|重新出现|复发|回来了)"
    r".{0,24}(?:我|本人)?.{0,8}(?:打算|准备|决定|会|要)"
    r".{0,8}(?:行动|执行|实施|去做)"
)
CURRENT_MEDICAL_PRONOUN_RECURRENCE_PATTERN = re.compile(
    r"(?:今晚|今天|现在|如今|目前|当前).{0,12}"
    r"(?:它|疼痛|症状|同样的痛|相同的痛)"
    r".{0,12}(?:又来了|又出现|再次出现|重新出现|复发)"
    r".{0,16}(?:越来越重|加重|恶化|很重|严重)"
)
RESOLVED_HISTORICAL_SELF_HARM_DENIAL_SEQUENCE_PATTERN = re.compile(
    rf"\s*(?:我|他|她)?(?:在)?{HISTORICAL_TIME_PATTERN}"
    rf"(?:我|他|她)?(?:曾经|当时)?\s*"
    r"(?:(?:想|要|准备)(?:去)?(?:死|自杀|轻生)|自杀|轻生|不想活)"
    r"\s*[。！？；]\s*"
    r"(?:现在|如今|目前)\s*(?:我|他|她)?\s*"
    r"(?:很|目前)?安全\s*(?:[，,]|且|并且|而且|也)+\s*"
    r"(?:没有|没|并无|不存在)(?:任何)?"
    r"(?:自伤|自杀|轻生|伤害自己)(?:的)?(?:想法|念头|计划|打算|意图|冲动)"
    r"[。！？；]?\s*"
)
RESOLVED_HISTORICAL_MEDICAL_CLEARANCE_SEQUENCE_PATTERN = re.compile(
    rf"\s*(?:我|他|她)?(?:在)?{HISTORICAL_TIME_PATTERN}"
    r"(?:我|他|她)?(?:曾经|当时)?\s*"
    r"(?:胸痛|胸口(?:痛|疼)|呼吸困难)\s*[。！？；]\s*"
    r"(?:今天|现在|如今|目前)?\s*(?:医生|医院)"
    r".{0,8}(?:复查)?(?:明确)?(?:确认|表示|说)"
    r".{0,8}(?:好了|恢复|康复|无碍|没事(?:了)?)"
    r".{0,12}(?:现在|如今|目前)\s*"
    r"(?:我|他|她)?\s*(?:没有|没|并无)(?:任何)?症状"
    r"[。！？；]?\s*"
)


def _historical_self_harm_resolution_actor_mismatch(text: str) -> bool:
    """Reject a recovery clause whose explicit subject differs from history."""
    patterns = (
        re.compile(
            rf"(?P<history>我|本人|他|她)\s*(?:在)?{HISTORICAL_TIME_PATTERN}"
            r".{0,20}(?:自杀|轻生|想死|去死|不想活)"
            r"\s*[。！？；]\s*(?:现在|如今|目前)\s*"
            r"(?P<current>我|本人|他|她)\s*"
            r"(?:生活(?:很|挺)?好|状态(?:很|挺)?好|"
            r"(?:已经|已|现已)?(?:恢复|康复|好了)|(?:很|目前)?安全)"
        ),
        re.compile(
            rf"{HISTORICAL_TIME_PATTERN}\s*(?P<history>我|本人|他|她)"
            r".{0,20}(?:自杀|轻生|想死|去死|不想活)"
            r"\s*[。！？；]\s*(?:现在|如今|目前)\s*"
            r"(?P<current>我|本人|他|她)\s*"
            r"(?:生活(?:很|挺)?好|状态(?:很|挺)?好|"
            r"(?:已经|已|现已)?(?:恢复|康复|好了)|(?:很|目前)?安全)"
        ),
    )
    for pattern in patterns:
        for match in pattern.finditer(text):
            history = "我" if match.group("history") == "本人" else match.group("history")
            current = "我" if match.group("current") == "本人" else match.group("current")
            if history != current:
                return True
    return False
DOUBLE_NEGATED_SELF_HARM_PATTERN = re.compile(
    r"(?:我|本人)\s*(?:并)?(?:不是|并非)\s*(?:"
    r"(?:不会|不想|不打算|不准备|没想|没有想)"
    r"(?P<post_term>自伤|自杀|轻生|伤害自己|结束自己的生命|想死|去死)|"
    r"(?:没有|没|并无)(?:任何)?"
    r"(?P<pre_term>自伤|自杀|轻生|伤害自己|结束自己的生命|想死|去死)"
    r"(?:打算|计划|想法|念头|意图|冲动))"
)
COMPOSED_DOUBLE_NEGATED_SELF_HARM_PATTERN = re.compile(
    r"(?:我|本人)\s*(?:没有|没|并非|不是|并不是)\s*"
    r"不(?:想|打算|准备|计划|会)?\s*"
    r"(?:自杀|轻生|伤害自己|结束自己的生命|想死|去死)|"
    r"\bI\s+(?:do\s+not|don't|did\s+not|didn't)\s+not\s+"
    r"(?:want|plan|intend)?(?:\s+to)?\s*"
    r"(?:kill\s+myself|hurt\s+myself|commit\s+suicide)\b",
    re.IGNORECASE,
)
DOUBLE_NEGATED_SELF_HARM_PLAN_PATTERN = re.compile(
    r"(?:我|本人).{0,12}(?:不是|并非)没有.{0,8}"
    r"(?:自杀|自伤|轻生)(?:计划|打算|念头)",
    re.IGNORECASE,
)
COMPOSED_DOUBLE_NEGATED_EXTERNAL_THREAT_PATTERN = re.compile(
    r"(?:他|她|对方|前任|陌生人)\s*(?:并非|不是|并不是|没有)\s*"
    r"不(?:会|想|打算|准备|计划)?\s*"
    r"(?:杀(?:死)?|弄死|伤害|捅(?:伤|死)?|砍(?:伤|死)?|打死)\s*"
    r"(?:我|你)|"
    r"\b(?:he|she|they|the\s+person)\s+"
    r"(?:is\s+not|isn't|does\s+not|doesn't)\s+not\s+"
    r"(?:going\s+to\s+|plan(?:ning)?\s+to\s+|intend(?:s)?\s+to\s+)?"
    r"(?:kill|hurt|stab|shoot)\s+(?:me|you)\b",
    re.IGNORECASE,
)
COMPOSED_DOUBLE_NEGATED_HARM_TO_OTHERS_PATTERN = re.compile(
    r"(?:我|本人)\s*(?:并非|不是|并不是|没有)\s*"
    r"不(?:会|想|打算|准备|计划)?\s*"
    r"(?:杀(?:死)?|弄死|伤害|捅(?:伤|死)?|砍(?:伤|死)?|打死)\s*"
    r"(?:人|某人|你|他|她|别人|他们|她们|对方)|"
    r"\bI\s+(?:am\s+not|I'm\s+not|do\s+not|don't)\s+not\s+"
    r"(?:going\s+to\s+|plan(?:ning)?\s+to\s+|intend\s+to\s+)?"
    r"(?:kill|hurt|stab|shoot)\s+"
    r"(?:you|him|her|them|someone|somebody)\b",
    re.IGNORECASE,
)
NESTED_NEGATION_SELF_HARM_PATTERN_ZH = re.compile(
    r"(?:我|本人)?\s*(?:不能|无法|很难)\s*(?:说|声称|表示)?"
    r".{0,20}(?:没有|没|不想|不打算|不会).{0,12}"
    r"(?:自杀|轻生|伤害自己|结束自己的生命|想死|去死)"
    r"(?P<reset>.{0,80})",
)
NESTED_NEGATION_SELF_HARM_PATTERN_EN = re.compile(
    r"\b(?:I\s+)?(?:can(?:'|’|‘)?t|cannot|can\s+not|"
    r"couldn(?:'|’|‘)?t|could\s+not)\s+(?:say|claim|state)"
    r".{0,40}(?:don(?:'|’|‘)?t|do\s+not|have\s+no|not)"
    r".{0,20}(?:kill\s+myself|hurt\s+myself|suicid(?:e|al))"
    r"(?P<reset>.{0,100})",
    re.IGNORECASE,
)


def _nested_negation_affirms_self_harm(text: str) -> bool:
    """Recognise an outer disclaimer that is explicitly reversed afterward."""
    for match in NESTED_NEGATION_SELF_HARM_PATTERN_ZH.finditer(text):
        reset = match.group("reset")
        if (
            re.search(r"(?:相反|反而|其实|事实上|实际(?:上)?)", reset)
            and re.search(
                r"(?:我|本人)\s*(?:就是|确实|真的)?\s*"
                r"(?:有(?=\s*(?:[，,。；;]|而且|并且|且|$))|"
                r"会|要|打算|准备|决定)",
                reset,
            )
            and not re.search(
                r"(?:我|本人)\s*(?:就是|确实|真的)?\s*"
                r"(?:没有|没|不会|不要|不打算|不准备|不决定)",
                reset,
            )
            and re.search(
                r"(?<!不)(?<!没)(?:会|要|打算|准备|决定).{0,8}"
                r"(?:行动|执行|实施|去做|自杀|轻生|伤害自己)|"
                r"(?:自杀|轻生|伤害自己|结束自己的生命)",
                reset,
            )
            and not re.search(
                r"(?:不会|不要|不打算|不准备|没打算|未决定).{0,8}"
                r"(?:行动|执行|实施|去做|自杀|轻生|伤害自己)|"
                r"(?:行动|执行|实施|去做).{0,6}(?:帮助|保护|阻止|救助)他人",
                reset,
            )
        ):
            return True
    for match in NESTED_NEGATION_SELF_HARM_PATTERN_EN.finditer(text):
        reset = match.group("reset")
        if (
            re.search(r"\b(?:in\s+fact|actually|on\s+the\s+contrary)\b", reset, re.IGNORECASE)
            and re.search(
                r"\bI\s+do\b(?!\s+not\b)(?=\s*(?:[,;]|and\b|$))",
                reset,
                re.IGNORECASE,
            )
            and re.search(
                r"\b(?:I\s+will\s+act|I(?:'|’)m\s+going\s+to\s+act|"
                r"I\s+(?:plan|intend)\s+to\s+act|tonight)\b",
                reset,
                re.IGNORECASE,
            )
            and not re.search(
                r"\bI\s+(?:do\s+not|don(?:'|’)t|will\s+not|won(?:'|’)t)\b|"
                r"\bact\s+(?:responsibly|to\s+help|to\s+protect|to\s+stop)\b",
                reset,
                re.IGNORECASE,
            )
        ):
            return True
    return False


def _has_current_self_harm_recurrence(text: str) -> bool:
    """Bind a current recurrence and action inside one clause, in either order."""
    historical = re.search(
        rf"(?:"
        rf"(?:我|本人)\s*(?:在)?\s*{HISTORICAL_TIME_PATTERN}|"
        rf"{HISTORICAL_TIME_PATTERN}\s*(?:我|本人))"
        r".{0,16}(?:想死|自杀|轻生|不想活|伤害自己)",
        text,
    )
    if historical is None:
        return False
    for clause in re.split(r"[。！？；\n]+", text):
        if not re.search(r"(?:今晚|今天|现在|如今|目前|当前)", clause):
            continue
        if not re.search(
            r"(?:(?:那个|这种)(?:(?:自伤|轻生|想死)(?:的)?)?"
            r"(?:念头|想法)|(?:自伤|轻生|想死)(?:的)?(?:念头|想法))"
            r".{0,12}(?:又回来了|再次出现|重新出现|复发|回来了)|"
            r"(?:又回来了|再次出现|重新出现|复发|回来了)"
            r".{0,12}(?:(?:那个|这种)(?:(?:自伤|轻生|想死)(?:的)?)?"
            r"(?:念头|想法)|(?:自伤|轻生|想死)(?:的)?(?:念头|想法))",
            clause,
        ):
            continue
        if re.search(
            r"(?:我|本人).{0,8}(?:打算|准备|决定|会|要)"
            r"(?!\s*(?:不|没|未|取消|放弃|停止)).{0,10}"
            r"(?:行动|执行|实施|去做|自杀|轻生|伤害自己)",
            clause,
        ):
            return True
    return False


UNQUOTED_TRANSFORM_REALITY_PATTERN = re.compile(
    r"(?:真实求救|现实求救|真实情况|实际情况|正在发生|"
    r"(?:这|以下|下面|上面|该内容)?(?:不是|并非)"
    r"(?:例句|素材|台词|虚构|小说|电影|测试(?:文本|输入|用例)?)|"
    r"\b(?:real\s+emergency|real\s+plea|real\s+situation|"
    r"actually\s+happening|this\s+is\s+real|not\s+an?\s+example|"
    r"not\s+fiction(?:al)?)\b)",
    re.IGNORECASE,
)


def unquoted_transform_payload_is_current_real_risk(text: str) -> bool:
    """Fail closed when an unquoted transform payload declares real danger."""
    operation = TRANSFORM_OPERATION_PATTERN.search(text)
    if operation is None:
        return False
    delimiter_positions = [
        position
        for marker in ("：", ":")
        for position in [text.find(marker, operation.end())]
        if position >= 0
    ]
    if not delimiter_positions:
        return False
    delimiter = min(delimiter_positions)
    payload = text[delimiter + 1 :]
    if any(start >= delimiter for start, _ in _actual_quote_ranges(text)):
        return False
    if not (
        SAFETY_TEXT_PATTERN.search(payload)
        or re.search(SELF_DIRECTED_HARM_PATTERN, payload, re.IGNORECASE)
        or re.search(HARM_TO_OTHERS_INTENT_PATTERN, payload, re.IGNORECASE)
    ):
        return False
    return bool(
        UNQUOTED_TRANSFORM_REALITY_PATTERN.search(text[:delimiter])
        or UNQUOTED_TRANSFORM_REALITY_PATTERN.search(payload)
    )


def _scope_visible_risk_text(text: str) -> str:
    """Remove content owned by transform or declared non-real scopes first."""
    if parse_pure_transform_task(text) is not None:
        return ""
    pieces: list[str] = []
    persistent_nonreal_scope = False
    for match in re.finditer(r"[^。！？；\n]+[。！？；]?|\n", text):
        clause = match.group(0)
        if re.match(
            r"^\s*(?:the|a)\s+(?:novel|screenplay|fictional\s+story|"
            r"first-aid\s+manual|training\s+manual|fire\s+drill|"
            r"historical\s+report)\b.{0,32}"
            r"(?:describes?|says?|states?|uses?|reports?)\b",
            clause,
            re.IGNORECASE,
        ):
            continue
        reality_override = _reality_scope_reset_match(clause)
        nonreal_scope_end = NONREAL_SCOPE_END_PATTERN.match(clause)
        nonreal_scope_intro = re.search(
            r"^\s*(?:这|这段|以下|下面|上面|前文|该内容|这个内容).{0,10}"
            r"(?:是|只是|属于|来自).{0,8}"
            r"(?:电影|小说|剧本|游戏|桌游|角色扮演|歌词|台词|例句|翻译素材|"
            r"正则测试|regex|测试字符串|测试用例|测试文本|测试输入|测试样例)",
            clause,
            re.IGNORECASE,
        )
        if reality_override is not None:
            persistent_nonreal_scope = False
            clause = clause[reality_override.start() :]
        elif nonreal_scope_end is not None:
            persistent_nonreal_scope = False
            suffix = clause[nonreal_scope_end.end() :]
            suffix_reality = _reality_scope_reset_match(suffix)
            if suffix_reality is not None:
                clause = suffix[suffix_reality.start() :]
            elif re.match(r"\s*(?:我|本人)(?:现在|当前|现实|实际|真的)", suffix):
                clause = suffix
            else:
                continue
        elif NONREAL_CONTINUATION_PATTERN.match(clause):
            persistent_nonreal_scope = True
            continue
        elif persistent_nonreal_scope:
            continue
        elif nonreal_scope_intro is not None:
            persistent_nonreal_scope = True
            continue

        transform_instruction = re.search(
            r"^\s*(?:(?:请|帮我|请帮我|把|将)\s*)?.{0,24}"
            r"(?:翻译(?:成|为)?|翻成|译成|translate|改成|转换成|整理成|排成|"
            r"分析(?:这|以下|上面)?(?:句|段)?(?:台词|例句|文本|文字))",
            clause,
            re.IGNORECASE,
        )
        if transform_instruction and NEGATED_TRANSLATION_INTENT_PATTERN.search(
            clause[: transform_instruction.end()]
        ):
            transform_instruction = None
        if not transform_instruction and re.search(
            r"^\s*(?:请|帮我|请帮我)?.{0,24}"
            r"(?:检查|测试|验证).{0,16}(?:正则|regex|模式|是否匹配)|"
            r"^\s*(?:请|帮我|请帮我)?.{0,24}"
            r"(?:正则|regex|模式).{0,12}(?:匹配|命中)",
            clause,
            re.IGNORECASE,
        ):
            transform_instruction = True
        if transform_instruction:
            payload_ranges = transform_payload_ranges(clause)
            if payload_ranges:
                clause = clause[payload_ranges[-1][1] + 1 :]
                if not clause.strip(" ，,。！？；"):
                    continue
            elif re.search(r"[:：]", clause):
                if unquoted_transform_payload_is_current_real_risk(clause):
                    delimiter = min(
                        position
                        for marker in ("：", ":")
                        for position in [clause.find(marker)]
                        if position >= 0
                    )
                    clause = clause[delimiter + 1 :]
                else:
                    secondary = re.search(
                        r"(?:同时|并且|另外|还要)\s*"
                        r"(?:告诉|分析|判断|解释|诊断|建议)|"
                        r"\b(?:and|also|then)\s+"
                        r"(?:tell|explain|analy[sz]e|judge|diagnose|advise)\b",
                        clause,
                        re.IGNORECASE,
                    )
                    if secondary is None:
                        continue
                    clause = clause[secondary.start() :]

        clause_pieces: list[str] = []
        fiction_scope = False
        for segment in re.split(r"(?<=[，,])", clause):
            fictional = re.search(
                r"电影|小说|剧本|游戏|桌游|角色扮演|歌词|例句|翻译素材", segment
            )
            reality_override = _reality_scope_reset_match(segment)
            personal_media_context = re.search(
                r"(?:我|我们).{0,10}(?:在玩|玩了|看了|在看|读了|在读|听了|在听)"
                r".{0,8}(?:电影|小说|剧本|游戏|歌词)",
                segment,
            )
            if reality_override:
                fiction_scope = False
                clause_pieces.append(segment)
                continue
            if fictional:
                if personal_media_context:
                    continue
                fiction_scope = True
                continue
            if fiction_scope:
                continue
            clause_pieces.append(segment)
        pieces.extend(clause_pieces)
    return "".join(pieces)


def _has_current_risk_after_history(clause: str) -> bool:
    """Keep a current recurrence visible even when the same clause has history."""
    if re.search(
        r"(?:现在|当前|目前|此刻|今天|今晚).{0,12}"
        r"(?:菜刀|刀).{0,4}(?:又|再次|重新)?(?:就|还)?在(?:我)?手边",
        clause,
    ):
        return True
    return bool(
        re.search(
            r"(?:^|[，,；;]|但|可是|不过|然而|可)\s*"
            r"(?:我|本人|他|她|对方|前任|朋友)?\s*"
            r"(?:现在|当前|目前|此刻|今天|今晚).{0,16}"
            r"(?:又|再次|重新|正在|刚|仍|依然).{0,24}"
            r"(?:自伤|自杀|轻生|想死|伤害自己|伤害室友|伤害他人|"
            r"持刀|拿刀|带刀|有刀|堵门|撞门|砸门|砸窗|威胁|"
            r"在(?:你|我)?门口|在门外|胸痛|呼吸困难)",
            clause,
        )
    )


HISTORICAL_RISK_SCOPE_PATTERN = re.compile(
    rf"旧新闻|旧聊天|历史(?:消息|记录|事件)|{HISTORICAL_TIME_PATTERN}"
)
RISK_FAMILY_MENTION_PATTERN = re.compile(
    r"自伤|自杀|轻生|想死|伤害自己|持刀|拿刀|带刀|"
    r"(?:菜刀|刀).{0,4}在(?:我)?手边|"
    r"威胁|杀(?:了|死)?|弄死|胸痛|呼吸困难|法律期限|"
    r"法院.{0,12}期限"
)
RISK_RESOLUTION_PATTERN = re.compile(
    r"(?:事件|那次威胁|威胁|期限|症状|念头|想法)"
    r".{0,12}(?:已经|已|早已)?(?:结束|过去|过了|解除)|"
    r"(?:已经|已|早已)(?:结束|过去|过了|解除)|"
    r"(?:现在|当前|目前).{0,10}(?:已经|已)?(?:没有了|无症状|安全)|"
    r"(?:后来|之后).{0,12}(?:已经|已)?接受(?:了)?帮助"
    r".{0,16}(?:现在|当前|目前).{0,6}安全|"
    r"检查后.{0,12}(?:已经|已)?结束.{0,12}(?:现在|当前|目前)?无症状|"
    r"(?:现在|当前|目前|后来|之后)?.{0,8}(?:菜刀|刀)?"
    r".{0,4}(?:已经|已)?收走.{0,12}(?:没有|不存在)(?:任何)?"
    r"(?:现实)?(?:危险|风险)|"
    r"(?:现在|当前|目前).{0,12}(?:没有|不存在)(?:任何)?"
    r"(?:紧迫|现实|当前)?(?:风险|威胁)"
)
CURRENT_RISK_CUE_PATTERN = re.compile(
    r"(?:现在|当前|目前|此刻|今天|今晚).{0,28}(?:"
    r"自伤|自杀|轻生|想死|伤害自己|吞药|胸痛|呼吸困难|"
    r"持刀|拿刀|带刀|有刀|堵门|堵着|堵住|撞门|砸门|砸窗|"
    r"威胁|闯入|门口|门外|提交|失去上诉权)|"
    r"法院.{0,20}(?:今天|今日|明天|两小时内|\d+\s*(?:小时|分钟)内)"
)
CURRENT_SELF_HARM_ANAPHORIC_AFFIRMATION_PATTERN = re.compile(
    r"(?:[，,；;]|但|可是|不过|然而)\s*"
    r"(?:我|本人)?\s*(?:现在|当前|目前|此刻)\s*"
    r"(?:确实|真的|就是|仍然|依然)?\s*有(?:了)?"
    r"\s*(?:[。！？；;]|$)"
)


def _has_current_self_harm_anaphoric_affirmation(text: str) -> bool:
    """Resolve a bounded current ``有`` only to an earlier self-harm noun.

    The end boundary matters: ``现在有朋友陪伴`` must not inherit the risk
    noun merely because it appears earlier in the same sentence.
    """
    for match in CURRENT_SELF_HARM_ANAPHORIC_AFFIRMATION_PATTERN.finditer(text):
        antecedent = text[max(0, match.start() - 64) : match.start()]
        if re.search(
            r"自伤|自杀|轻生|伤害自己|结束自己的生命|想死|去死",
            antecedent,
        ):
            return True
    return False


def _post_resolution_current_remainder(clause: str) -> tuple[str, bool] | None:
    """Return only a current event stated after a historical resolution.

    A resolution is lifecycle metadata for one earlier event, not permission
    to erase the rest of the sentence.  The boolean records the narrow case
    where the retained event is current proximity by the same previously
    threatening person, so downstream routing can preserve that context
    without inventing a new threat or motive.
    """
    resolutions = list(RISK_RESOLUTION_PATTERN.finditer(clause))
    if not resolutions:
        return None
    resolution = resolutions[-1]
    suffix = clause[resolution.end() :]
    boundary = re.search(
        r"^[\s，,：:；;]*(?:但|可是|不过|然而|可|随后|然后)\s*(?P<event>.+)$",
        suffix,
    )
    if boundary is not None:
        event = boundary.group("event").strip()
    else:
        event = suffix.lstrip(" \t，,：:；;")
        if not event or not CURRENT_RISK_CUE_PATTERN.search(event):
            return None
    if not CURRENT_RISK_CUE_PATTERN.search(event):
        return None
    prefix = clause[: resolution.end()]
    inherited_prior_threat = bool(
        re.search(r"威胁过?(?:我|你)|(?:持刀|拿刀|带刀).{0,8}威胁", prefix)
        and re.search(
            r"(?:他|她|对方|前任|当事人)?(?:现在|当前|目前|此刻|今天|今晚)"
            r".{0,12}(?:在)?(?:我家|我住处|家)?门(?:口|外)",
            event,
        )
    )
    return event, inherited_prior_threat


def _is_resolved_historical_risk_clause(clause: str) -> bool:
    """Recognize bounded historical risk plus an affirmative current resolution."""
    return bool(
        HISTORICAL_RISK_SCOPE_PATTERN.search(clause)
        and RISK_FAMILY_MENTION_PATTERN.search(clause)
        and RISK_RESOLUTION_PATTERN.search(clause)
    )


LEGAL_AUTHORITY_PATTERN = re.compile(
    r"法院|法庭|仲裁庭|移民局|警方|检察院|监管机构"
)
URGENT_LEGAL_TIME_PATTERN = re.compile(
    r"今天|今日|明天|两小时内|\d+\s*(?:小时|分钟)内"
)
LEGAL_REQUIRED_ACTION_PATTERN = re.compile(
    r"提交|递交|回应|答复|出庭|到庭|申请|补交"
)
MATERIAL_LEGAL_CONSEQUENCE_PATTERN = re.compile(
    r"(?:失去|丧失).{0,8}(?:上诉|申诉|抗辩|申请)权|"
    r"缺席判决|拘留|驱逐|遣返"
)
LEGAL_RESOLUTION_PATTERN = re.compile(
    r"(?:期限|截止).{0,16}(?:已经|已|早已)?(?:结束|过去|过了)|"
    r"(?:我|本人)?(?:已经|已)\s*(?:提交|递交|回应|答复|补交)(?:完成|完毕|成功)?|"
    r"(?:材料|文件|申请)(?:已经|已)(?:提交|递交|补交)(?:完成|完毕|成功)?"
)


def _urgent_legal_event_span(clause: str) -> tuple[int, int] | None:
    """Return a same-clause official deadline event with material stakes."""
    authority = LEGAL_AUTHORITY_PATTERN.search(clause)
    timing = URGENT_LEGAL_TIME_PATTERN.search(clause)
    action = LEGAL_REQUIRED_ACTION_PATTERN.search(clause)
    consequence = MATERIAL_LEGAL_CONSEQUENCE_PATTERN.search(clause)
    if not all((authority, timing, action, consequence)):
        return None
    assert authority is not None
    assert timing is not None
    assert action is not None
    assert consequence is not None
    start = min(authority.start(), timing.start(), action.start(), consequence.start())
    end = max(authority.end(), timing.end(), action.end(), consequence.end())
    if end - start > 96:
        return None
    return start, end


def _has_urgent_legal_risk(text: str) -> bool:
    """Require urgency evidence to remain inside one asserted event clause."""
    for clause in re.split(r"[。！？；\n]+", text):
        if not clause.strip():
            continue
        if _urgent_legal_event_span(clause) is not None:
            return True
        if re.search(
            r"(?:当前|现在|目前|此刻)?(?:确实|明确)?(?:有|存在)"
            r".{0,4}紧迫法律风险",
            clause,
        ):
            return True
        authority = LEGAL_AUTHORITY_PATTERN.search(clause)
        timing = URGENT_LEGAL_TIME_PATTERN.search(clause)
        deadline = re.search(
            r"(?:上诉|申诉|法定|法律).{0,4}(?:最后)?期限|"
            r"(?:上诉|申诉)最后期限|紧迫期限|今天截止|明天截止",
            clause,
        )
        if authority is not None and timing is not None and deadline is not None:
            span_start = min(authority.start(), timing.start(), deadline.start())
            span_end = max(authority.end(), timing.end(), deadline.end())
            if span_end - span_start <= 72:
                return True
    return False


def _is_clearly_nonurgent_legal_clause(clause: str) -> bool:
    """Exclude resolved deadlines and non-assertive legal-risk questions."""
    if not re.search(r"法院|上诉|申诉|法律|法定|期限", clause):
        return False
    urgent_span = _urgent_legal_event_span(clause)
    resolutions = list(LEGAL_RESOLUTION_PATTERN.finditer(clause))
    if urgent_span is not None:
        # A lifecycle update suppresses only an earlier deadline.  A later
        # official demand remains current and must still route to support.
        return bool(resolutions and resolutions[-1].start() >= urgent_span[1])
    imminent = re.search(
        r"(?:今天|今日|明天|两小时内|\d+\s*(?:小时|分钟)内)"
        r".{0,24}(?:提交|截止|最后期限|失去上诉权)|"
        r"(?:提交|截止|最后期限).{0,24}"
        r"(?:今天|今日|明天|两小时内|\d+\s*(?:小时|分钟)内)",
        clause,
    )
    if imminent:
        return False
    if re.search(
        r"(?:期限|截止).{0,16}(?:已经|已|早已)?(?:结束|过去|过了)|"
        rf"(?:期限|截止).{{0,16}}{HISTORICAL_TIME_PATTERN}"
        r".{0,12}(?:已经|已|早已)?(?:结束|过去|过了)",
        clause,
    ):
        return True
    if re.search(
        r"(?:现在|当前|目前)?\s*(?:没有|不存在)(?:任何)?"
        r"(?:紧迫)?法律风险",
        clause,
    ):
        return True
    if re.search(r"(?:是否|会否|有没有).{0,8}紧迫法律风险", clause):
        return True
    return bool(
        re.search(r"(?:担心|可能).{0,8}法律风险", clause)
        and re.search(
            r"(?:没有|不存在)(?:任何)?(?:现在|当前|目前)?(?:的)?期限",
            clause,
        )
    )


NONCURRENT_HISTORY_CUE_PATTERN = re.compile(
    rf"{HISTORICAL_TIME_PATTERN}|上个月|上周|昨晚|旧(?:消息|记录|日记|聊天)|"
    r"\b(?:yesterday|last\s+(?:week|month|year)|years?\s+ago|"
    r"from\s+(?:19|20)\d{2}|in\s+the\s+past|old)\b",
    re.IGNORECASE,
)
SELF_HARM_FAMILY_PATTERN = re.compile(
    r"自伤|自杀|轻生|想死|不想活|伤害自己|结束自己的生命|"
    r"\b(?:suicid(?:e|al)|kill\s+(?:my|her|him|them)self|"
    r"harm\s+(?:my|her|him|them)self|end\s+(?:my|her|his|their)\s+life)\b",
    re.IGNORECASE,
)
MEDICAL_FAMILY_PATTERN = re.compile(
    r"胸痛|胸口痛|呼吸困难|严重出血|"
    r"\b(?:chest\s+pain|trouble\s+breathing|severe\s+bleeding)\b",
    re.IGNORECASE,
)
EXTERNAL_SAFETY_FAMILY_PATTERN = re.compile(
    r"持刀|拿刀|带刀|威胁|砸过?门|泄露.{0,8}(?:住址|地址)|"
    r"跟踪|尾随|杀我|伤害我|"
    r"\b(?:threaten(?:ed|ing)?|knife\s+threat|leak(?:ed)?\s+(?:my\s+)?address|"
    r"damaged?\s+(?:my\s+)?door)\b",
    re.IGNORECASE,
)
SELF_HARM_RESOLUTION_PATTERN = re.compile(
    r"(?:持续|完成|接受).{0,12}(?:治疗|帮助).{0,48}"
    r"(?:现在|当前|目前|今天).{0,20}(?:没有|无).{0,12}"
    r"(?:自伤|自杀|轻生|伤害自己|这种)(?:的)?(?:念头|想法|计划)|"
    r"(?:现在|当前|目前).{0,16}安全.{0,20}"
    r"(?:没有|无).{0,12}(?:这种|自伤|自杀)(?:想法|念头|计划)|"
    r"\b(?:completed|continued|received)\s+treatment\b.{0,80}"
    r"\b(?:now|today|currently)\b.{0,32}\bno\s+(?:thoughts?|plan)\b|"
    r"\b(?:now|today|currently)\b.{0,24}\bno\s+thoughts?\s+or\s+plan\b|"
    r"(?:已经|已).{0,16}(?:年|个月|月|周).{0,12}"
    r"(?:没有|没)(?:这种|自伤|自杀|轻生|伤害自己)?(?:的)?(?:想法|念头)"
    r".{0,32}(?:今天|现在|当前|目前).{0,16}(?:没有|没)(?:任何)?"
    r"(?:计划|打算|意图|冲动)",
    re.IGNORECASE,
)
MEDICAL_RESOLUTION_PATTERN = re.compile(
    r"(?:急救人员|医生|医院).{0,24}(?:检查|评估|处理)过?.{0,40}"
    r"(?:现在|当前|目前).{0,12}(?:无症状|没有症状)|"
    r"\b(?:evaluated|checked)\b.{0,32}\b(?:ER|emergency)\b.{0,48}"
    r"\bdischarged\b.{0,32}\bno\s+symptoms?\s+now\b|"
    r"\b(?:tests?|exam|workup)\b.{0,20}"
    r"\b(?:was|were|came\s+back)\s+normal\b.{0,48}"
    r"\b(?:I\s+have\s+)?no\s+symptoms?\s+now\b",
    re.IGNORECASE,
)
EXTERNAL_SAFETY_RESOLUTION_PATTERN = re.compile(
    r"警方.{0,16}(?:已|已经)?处理.{0,32}(?:拘留|羁押).{0,40}"
    r"(?:现在|当前|目前).{0,12}安全.{0,24}(?:没有|无).{0,12}(?:新(?:的)?接触|联系)|"
    r"(?:已经|已)搬家.{0,24}(?:更换|换了?)门锁.{0,40}"
    r"(?:没有|无人).{0,12}(?:跟踪|联系)|"
    r"(?:今天|现在|当前|目前).{0,12}(?:没有|没)(?:再)?(?:来|出现)"
    r".{0,24}(?:没有|没)(?:再)?联系",
    re.IGNORECASE,
)
CURRENT_ASSERTED_RISK_PATTERN = re.compile(
    r"(?:现在|当前|目前|此刻|今晚|今天|刚才|刚|正在|又|再次).{0,40}"
    r"(?:自伤|自杀|轻生|想死|伤害自己|胸痛|呼吸困难|出血|"
    r"持刀|拿刀|有枪|威胁|杀我|跟踪|尾随|堵门|撞门|砸门|砸窗|闯入)|"
    r"\b(?:now|right\s+now|tonight|currently|just)\b.{0,48}"
    r"\b(?:suicid|die|kill|hurt|shoot|stab|gun|knife|bleed|"
    r"chest\s+pain|pound|kick|break|follow|chase|strangl)\w*\b",
    re.IGNORECASE,
)


def _risk_statement_is_wholly_noncurrent(text: str) -> bool:
    """Return whether every mentioned risk is explicitly non-current.

    A historical cue and a family-matched resolution must both be present.
    Any later affirmative current event prevents suppression.
    """
    value = text.strip()
    if re.fullmatch(
        r"\s*(?:假设|假如|如果).{0,48}[“‘\"'].{0,48}[”’\"']"
        r".{0,48}(?:如何|怎么|应该如何).{0,24}(?:区分|判断|识别)"
        r".{0,24}[？?]\s*",
        value,
    ):
        return True
    if re.fullmatch(
        r"\s*(?:他|她|对方|前任|陌生人)?(?:刚才|刚刚|今天)?\s*"
        r"(?:没有|没|并未)说.{0,12}(?:杀|伤害)(?:我|你)"
        r".{0,20}(?:也)?(?:不在|没有在).{0,8}(?:我|你)?附近[。.!！]?\s*",
        value,
    ):
        return True
    if re.fullmatch(
        r"\s*(?:没有|没|无人|没人)(?:任何)?(?:陌生人|人)?"
        r".{0,8}(?:知道|掌握|拿到).{0,8}(?:我的|你的)?(?:住址|地址)"
        r".{0,20}(?:也)?(?:没有|没|无人|没人).{0,8}(?:跟踪|尾随)"
        r"(?:我|你)?[。.!！]?\s*",
        value,
    ):
        return True
    if not NONCURRENT_HISTORY_CUE_PATTERN.search(value):
        return False

    present: list[tuple[re.Pattern[str], re.Pattern[str]]] = []
    for family, resolution in (
        (SELF_HARM_FAMILY_PATTERN, SELF_HARM_RESOLUTION_PATTERN),
        (MEDICAL_FAMILY_PATTERN, MEDICAL_RESOLUTION_PATTERN),
        (EXTERNAL_SAFETY_FAMILY_PATTERN, EXTERNAL_SAFETY_RESOLUTION_PATTERN),
    ):
        if family.search(value):
            present.append((family, resolution))
    if not present:
        return False
    resolution_matches: list[re.Match[str]] = []
    for _, resolution in present:
        match = resolution.search(value)
        if match is None:
            return False
        resolution_matches.append(match)
    last_resolution_end = max(match.end() for match in resolution_matches)
    if CURRENT_ASSERTED_RISK_PATTERN.search(value[last_resolution_end:]):
        return False
    return True


def _strip_resolved_noncurrent_prefix(text: str) -> str:
    """Remove only a bounded historical event through its current resolution.

    Later text is preserved even when it belongs to a newly added risk family.
    This avoids the unsafe whole-input suppression that previously required a
    second, drifting list of every possible current emergency.
    """
    history = NONCURRENT_HISTORY_CUE_PATTERN.search(text)
    if history is None:
        return text
    resolution_ends: list[int] = []
    family_starts: list[int] = []
    for family, resolution in (
        (SELF_HARM_FAMILY_PATTERN, SELF_HARM_RESOLUTION_PATTERN),
        (MEDICAL_FAMILY_PATTERN, MEDICAL_RESOLUTION_PATTERN),
        (EXTERNAL_SAFETY_FAMILY_PATTERN, EXTERNAL_SAFETY_RESOLUTION_PATTERN),
    ):
        family_match = family.search(text)
        if family_match is None:
            continue
        resolution_match = resolution.search(
            text,
            max(family_match.end(), history.end()),
        )
        if resolution_match is None:
            return text
        family_starts.append(family_match.start())
        resolution_ends.append(resolution_match.end())
    if not resolution_ends:
        return text
    end = max(resolution_ends)
    suffix = text[end:]
    reset = re.search(
        r"(?:^|[\s,，;；])(?:but|however|yet|separate\s+issue|"
        r"reality\s+update|但|可是|不过|然而|现实情况|实际情况)\b",
        suffix,
        re.IGNORECASE,
    )
    boundary_positions = [
        position
        for marker in ("。", "！", "？", ";", "；", "\n", ".")
        for position in [suffix.find(marker)]
        if position >= 0
    ]
    boundary = min(boundary_positions) + 1 if boundary_positions else len(suffix)
    if reset is not None and reset.start() < boundary:
        end += reset.start()
    else:
        end += boundary
    event_anchor = min([history.start(), *family_starts])
    prior_boundaries = [
        text.rfind(marker, 0, event_anchor)
        for marker in ("。", "！", "？", ";", "；", "\n", ".")
    ]
    start = max(prior_boundaries, default=-1) + 1
    return text[:start] + text[end:]


META_LANGUAGE_SCOPE_PATTERN = re.compile(
    r"句法|语言学|元语言|被引用的(?:宾语|主语|成分)|"
    r"祈使语气|可验证(?:主张|命题)|"
    r"\b(?:syntax|linguistic|metalinguistic|quoted\s+object)\b",
    re.IGNORECASE,
)
META_REALITY_DISAVOWAL_PATTERN = re.compile(
    r"(?:不是|并非)现实(?:陈述|主张|事件)|"
    r"(?:我|本人)?(?:没有|没|并未)(?:说|声称|表示|断言)(?:过)?"
    r"现实中.{0,24}|"
    r"现实中(?:没有|没|不存在)(?:任何)?.{0,24}",
    re.IGNORECASE,
)
INTRUSIVE_THOUGHT_SCOPE_PATTERN = re.compile(
    r"(?:脑中|脑海|脑子里).{0,12}(?:闪过|冒出|出现).{0,12}"
    r"(?:这句|一句|这句话|念头)?",
)
INTRUSIVE_THOUGHT_RESOLUTION_PATTERN = re.compile(
    r"(?:我|本人).{0,12}(?:不想|没有想|没想)(?:去)?死"
    r".{0,24}(?:没有|没)(?:任何)?(?:计划|打算|意图|冲动)"
    r".{0,24}(?:现在|当前|目前).{0,8}安全",
)


def _mask_nonassertive_risk_quotes(text: str) -> str:
    """Mask bounded quotes explicitly framed as language or intrusive content.

    The quote alone is removed; any later reality update stays visible.  This
    prevents a cited sentence from becoming an event while preserving a real
    event stated outside the citation.
    """
    characters = list(text)
    for start, end in _actual_quote_ranges(text):
        clause_start = max(
            (text.rfind(marker, 0, start) for marker in "。！？；;\n"),
            default=-1,
        ) + 1
        prefix = text[clause_start:start]
        suffix = text[end : min(len(text), end + 176)]
        local = prefix + suffix
        meta_disowned = bool(
            META_LANGUAGE_SCOPE_PATTERN.search(local)
            and META_REALITY_DISAVOWAL_PATTERN.search(suffix)
        )
        intrusive_resolved = bool(
            INTRUSIVE_THOUGHT_SCOPE_PATTERN.search(prefix)
            and INTRUSIVE_THOUGHT_RESOLUTION_PATTERN.search(suffix)
        )
        if meta_disowned or intrusive_resolved:
            characters[start:end] = " " * (end - start)
    return "".join(characters)


def _positive_risk_text(text: str) -> str:
    if re.fullmatch(
        r"\s*(?:假设|假如|如果).{0,64}[“‘\"'].{0,64}[”’\"']"
        r".{0,64}(?:如何|怎么|应该如何).{0,32}(?:区分|判断|识别)"
        r".{0,32}[？?]?\s*",
        text,
    ):
        return ""
    # A later, indexed scope correction can revoke transform ownership.  Keep
    # only those explicitly disowned operands visible to the safety detector.
    restored_transform_payloads = [
        text[start:end]
        for start, end in disowned_transform_payload_ranges(text)
    ]
    text = _strip_resolved_noncurrent_prefix(text)
    text = _mask_resolved_noncurrent_risk_quotes(text)
    text = _mask_nonassertive_risk_quotes(text)
    if (
        INTRUSIVE_THOUGHT_SCOPE_PATTERN.search(text)
        and INTRUSIVE_THOUGHT_RESOLUTION_PATTERN.search(text)
    ):
        text = re.sub(
            r"(?:我|本人)\s*(?:不想|没有想|没想)(?:去)?死",
            "",
            text,
        )
    text = _scope_visible_risk_text(text) + "".join(restored_transform_payloads)
    # Double negation is affirmative risk.  Preserve the bounded first-person
    # term outside the broad negation scrubber used later in this function.
    def owned_by_other_speaker(match: re.Match[str]) -> bool:
        quote_range = _quote_range_containing(
            text, match.start(), match.end()
        )
        return bool(
            quote_range is not None
            and _quoted_speaker_role(text, *quote_range) == "other"
        )

    forced_positive_terms = []
    for match in DOUBLE_NEGATED_SELF_HARM_PATTERN.finditer(text):
        if owned_by_other_speaker(match):
            continue
        term = match.group("post_term") or match.group("pre_term")
        forced_positive_terms.append("自杀" if term == "自伤" else term)
    for match in COMPOSED_DOUBLE_NEGATED_SELF_HARM_PATTERN.finditer(text):
        if not owned_by_other_speaker(match):
            forced_positive_terms.append("我准备自杀")
    for match in DOUBLE_NEGATED_SELF_HARM_PLAN_PATTERN.finditer(text):
        if not owned_by_other_speaker(match):
            forced_positive_terms.append("我有自杀计划")
    if COMPOSED_DOUBLE_NEGATED_EXTERNAL_THREAT_PATTERN.search(text):
        forced_positive_terms.append("他要杀我")
    if COMPOSED_DOUBLE_NEGATED_HARM_TO_OTHERS_PATTERN.search(text):
        forced_positive_terms.append("我打算杀他")
    if _historical_self_harm_resolution_actor_mismatch(text):
        forced_positive_terms.append("自杀")
    if _nested_negation_affirms_self_harm(text):
        forced_positive_terms.append("自杀")
    if _has_current_self_harm_anaphoric_affirmation(text):
        forced_positive_terms.append("我现在有自伤想法")
    if CURRENT_MEDICAL_RECURRENCE_PATTERN.search(text):
        forced_positive_terms.append("胸痛")
    if CURRENT_EXTERNAL_THREAT_RECURRENCE_PATTERN.search(text):
        forced_positive_terms.append("他威胁要杀我")
    if _has_current_self_harm_recurrence(text):
        forced_positive_terms.append("自杀")
    if (
        re.search(
            rf"{HISTORICAL_TIME_PATTERN}.{{0,20}}"
            r"(?:胸痛|胸口(?:痛|疼)|呼吸困难)",
            text,
        )
        and CURRENT_MEDICAL_PRONOUN_RECURRENCE_PATTERN.search(text)
    ):
        forced_positive_terms.append("胸痛")
    text = _strip_resolved_historical_external_threat(text)
    text = RESOLVED_HISTORICAL_SELF_HARM_DENIAL_SEQUENCE_PATTERN.sub("", text)
    text = RESOLVED_HISTORICAL_MEDICAL_CLEARANCE_SEQUENCE_PATTERN.sub("", text)
    text = RESOLVED_HISTORICAL_SELF_HARM_SEQUENCE_PATTERN.sub("", text)
    text = RESOLVED_HISTORICAL_MEDICAL_SEQUENCE_PATTERN.sub("", text)
    pieces: list[str] = []
    for clause in _iter_event_clauses(text):
        if _risk_statement_is_wholly_noncurrent(clause):
            continue
        if (
            META_LANGUAGE_SCOPE_PATTERN.search(text)
            and re.fullmatch(
                r"\s*(?:(?:我|本人)?(?:没有|没|并未)"
                r"(?:说|声称|表示|断言)(?:过)?现实中.{0,32}|"
                r"现实中(?:没有|没|不存在)(?:任何)?.{0,32})"
                r"[。！？；]?\s*",
                clause,
            )
        ):
            continue
        if _is_resolved_historical_risk_clause(clause):
            current_remainder = _post_resolution_current_remainder(clause)
            if current_remainder is None:
                continue
            clause, inherited_prior_threat = current_remainder
            if inherited_prior_threat:
                clause += "。曾威胁我的人此刻在我门口。"
        if _is_clearly_nonurgent_legal_clause(clause):
            continue
        if _is_affirmatively_resolved_historical_self_harm(clause):
            continue
        if _is_affirmatively_resolved_historical_medical(clause):
            continue
        if re.fullmatch(
            r"\s*(?:法院|上诉|申诉|法律|法定).{0,12}(?:期限|截止)"
            r".{0,8}(?:昨天|前天|上周|之前)(?:已经|早已)?(?:过了|过去|结束)"
            r"[。！？；]?\s*",
            clause,
        ):
            continue
        if re.fullmatch(
            rf"\s*(?:法律|法定)?期限.{{0,8}}{HISTORICAL_TIME_PATTERN}"
            r"(?:已经|早已|已)?(?:结束|过去|过了).{0,16}"
            r"(?:现在|如今|目前)(?:没有|没|并无|不存在)"
            r"(?:任何)?(?:紧迫)?法律风险[。！？；]?\s*",
            clause,
        ):
            continue
        if re.fullmatch(
            r"\s*(?:我|本人)(?:并)?(?:不是|并非)说"
            r"(?:我|本人)?(?:要|想|会|准备|打算)?"
            r"(?:自杀|轻生|伤害自己|结束自己的生命|想死|去死)"
            r"[。！？；]?\s*",
            clause,
        ):
            continue
        if re.fullmatch(
            r"\s*(?:他|她|对方|前任|陌生人)?(?:从来|从未|并未|没有|没|未)"
            r"(?:曾经)?(?:威胁|扬言|说过要|说要).{0,8}"
            r"(?:杀|杀死|弄死|伤害)(?:我|你)"
            r"(?:\s*[，,].{0,24}(?:翻译|译为).*)?[。！？；]?\s*",
            clause,
        ):
            continue
        if re.fullmatch(
            r"\s*(?:我|他|她|对方)?(?:笑|笑得|大笑|笑到).{0,6}"
            r"(?:喘不过气|喘不上气)[。！？；]?\s*",
            clause,
        ):
            continue
        if re.fullmatch(
            r"\s*(?:我|他|她|对方)?(?:在|正在)?(?:拿|握|用)(?:着)?"
            r"(?:一把)?(?:菜刀|刀)(?:来|去)?(?:切菜|切水果|做饭|做菜|削水果)"
            r"[。！？；]?\s*",
            clause,
        ):
            continue
        if re.fullmatch(
            r"\s*(?:我|我的|他|他的|她|她的|对方|对方的)?"
            r"(?:胸|胸口|胸部).{0,3}(?:不|没|没有)(?:痛|疼|疼痛)"
            r"[。！？；]?\s*",
            clause,
        ):
            continue
        if re.fullmatch(
            r"\s*(?:前任|对方|陌生人|他|她).{0,4}(?:没有|没|并未|不再有)"
            r"(?:我家|我住处|住处|家门)(?:的)?(?:钥匙|门卡)"
            r"[。！？；]?\s*",
            clause,
        ):
            continue
        if re.fullmatch(
            r"\s*(?:我|自己)(?:现在|目前|真的|确实|绝对|根本|完全|也|都|\s)*"
            r"(?:不想|不会|没想|没有想|并不想)(?:去)?死[。！？；]?\s*",
            clause,
        ):
            continue
        if re.fullmatch(
            r"\s*(?:我|本人)\s*(?:"
            r"(?:从来|从未|不曾)?\s*(?:没有|没|并未)(?:想过|打算过|计划过)?|"
            r"(?:从来|从未|不曾)(?:想过|打算过|计划过))\s*"
            r"(?:伤害|杀(?:死)?|弄死|捅|砍|打)\s*"
            r"(?:我的|你的|他的|她的)?(?:室友|同事|朋友|伴侣|家人|"
            r"别人|他人|任何人|人)[。！？；]?\s*",
            clause,
        ):
            continue
        broadly_negated = re.fullmatch(
            rf"\s*(?:我|他|她|对方)?"
            rf"(?:现在|目前|绝对|从来|一直|真的|确实|也|都|完全|根本|\s)*"
            rf"(?:没有|没|并未|未|不会|不想|并不想|不打算|不准备|无|从没|从未|不曾)"
            rf"(?:任何|过)?(?:想要|要|去|打算|准备|计划|说过要|说要|表示要|扬言要|\s)*"
            rf"{NEGATABLE_RISK_TERM_PATTERN}"
            rf"(?:(?:和|或|、|以及|也没有|也没|并且没有)"
            rf"(?:想要|要|去|\s)*{NEGATABLE_RISK_TERM_PATTERN})*"
            rf"(?:的)?(?:想法|念头|计划|打算|意图|冲动)?[。！？；]?\s*",
            clause,
            re.IGNORECASE,
        )
        if broadly_negated:
            continue
        fully_negated = re.fullmatch(
            rf"\s*(?:我|他|她|对方)?"
            rf"(?:没有|没|并未|未|不会|不想|并不想|不打算|不准备|无)"
            rf"(?:任何|过)?{NEGATABLE_RISK_TERM_PATTERN}"
            rf"(?:(?:和|或|、|以及|也没有|也没|并且没有)"
            rf"{NEGATABLE_RISK_TERM_PATTERN})*"
            rf"(?:的)?(?:想法|念头|计划|打算|意图|冲动)?[。！？；]?\s*",
            clause,
            re.IGNORECASE,
        )
        if fully_negated:
            continue
        pieces.append(clause + "。")
    value = "".join(pieces)
    negated_signal = re.compile(
        r"(?<!并非)(?<!不是)(?<!并不是)"
        r"(?:不想|并不想|不打算|不准备|不会)"
        r"(?:去|从|往)?(?:跳楼|跳下去|跳下)"
        r"|"
        rf"(?:我|他|她|对方)?(?:的)?(?:胸|胸口|胸部).{{0,3}}"
        rf"(?:不|没有|没|并未|未)(?:痛|疼|疼痛)"
        rf"|(?:也)?(?:我|他|她|对方)?(?:没有|没|并未|未|不会|不想|并不想|不打算|不准备|无|否认有)"
        rf"(?:任何|过)?(?:胸痛|呼吸困难|失去意识|昏迷|严重出血|持刀|拿刀|带刀|有枪|武器|跟踪|尾随|打我|伤害我|{OTHER_HARM_OUTCOME_PATTERN}|{WEAPON_VARIANT_PATTERN}|{MEDICAL_VARIANT_PATTERN})"
        rf"|(?:我|他|她|对方)?(?:没有|没|并未|未|不会|不想|并不想|不打算|不准备)"
        rf"(?:自伤|自杀|轻生|伤害自己|结束自己的生命|伤害他人|伤害别人|{SELF_HARM_OUTCOME_PATTERN})"
        r"(?:的)?(?:想法|念头|计划|打算|意图|冲动)?"
        rf"|(?:我|他|她|对方)?(?:从没|从未|不曾)(?:想过|有过|考虑过)?.{{0,4}}{SELF_HARM_OUTCOME_PATTERN}"
        r"|(?:他|她|对方|前任|陌生人)?(?:也)?(?:不|没|没有|并未|从未|不知道)"
        r".{0,8}(?:知道|掌握|拿到|获得).{0,8}(?:我的|你的|他的|她的)?(?:住址|地址|门锁密码)"
        rf"|(?:我|他|她|对方)?(?:没有|没|并未|未|不会|不想|并不想|不打算|不准备).{{0,8}}(?:{ROOFTOP_SELF_HARM_PATTERN}|{MEDICATION_EMERGENCY_PATTERN}|{COLLOQUIAL_THREAT_PATTERN})"
        rf"|(?:他|她|对方|前任|陌生人).{{0,24}}"
        rf"(?:说|发消息说|发来消息说|威胁|扬言).{{0,10}}"
        rf"(?:不会|不想|并不想|没打算|不打算|不准备|否认会)"
        rf"(?:{OTHER_HARM_OUTCOME_PATTERN})"
        r"|(?:也)?(?:没有|没|并未|未|无)(?:任何)?(?:伤害自己|伤害他人|伤害别人)"
        r"(?:的)?(?:想法|念头|计划|打算|意图|冲动)"
        r"|\b(?:do not|don't|did not|didn't|never|no)\s+(?:want to\s+)?"
        r"(?:kill myself|hurt myself|hurt anyone|commit suicide|overdose)\b"
        r"|\b(?:he|she|they|the person)\s+"
        r"(?:isn't|is not|wasn't|was not|won't|will not|isn't going to|is not going to)\s+"
        r"(?:kill|stab|shoot|hurt)\s+(?:me|you|him|her|them)\b"
        r"|\bI\s+(?:don't|do not|didn't|did not)\s+have\s+"
        r"(?:chest pain|trouble breathing)\b"
        r"|\bI\s+(?:(?:am|'m)\s+not\s+going\s+to|"
        r"do\s+not\s+want\s+to|don't\s+want\s+to|will\s+not|won't)\s+"
        r"(?:kill|hurt|stab|shoot)\s+"
        rf"{ENGLISH_HARM_TARGET_PATTERN}\b",
        re.IGNORECASE,
    )
    return (
        negated_signal.sub("", value)
        + "".join(forced_positive_terms)
    )


def _direct_user_harm_to_others_ranges(text: str) -> list[tuple[int, int]]:
    """Return first-person harm spans whose speaker is the current user."""
    ranges: list[tuple[int, int]] = []
    for match in re.finditer(
        r"(?<![A-Za-z0-9_一-鿿])(?:可|但|不过|然而)?(?:我|本人).{0,8}"
        r"(?:要|想|会|准备|打算).{0,8}"
        r"(?:杀(?:死)?|弄死|伤害|捅(?:伤|死)?|砍(?:伤|死)?|打死)"
        r".{0,8}(?:人|某人|你|他|她|别人|他们|她们|对方|室友)|"
        r"(?<![A-Za-z0-9_一-鿿])(?:可|但|不过|然而)?(?:我|本人).{0,8}"
        r"(?:要|想|会|准备|打算).{0,8}把"
        r"(?:人|某人|你|他|她|别人|对方|室友).{0,6}"
        r"(?:捅|砍|打|杀).{0,6}|"
        r"\bI\s+(?:(?:am|'m)\s+going\s+to|want\s+to|plan\s+to|"
        r"intend\s+to|will|(?:am|'m)\s+planning\s+to)\s+"
        r"(?:kill|hurt|stab|shoot)\s+"
        rf"{ENGLISH_HARM_TARGET_PATTERN}\b",
        text,
        re.IGNORECASE,
    ):
        quote_range = _quote_range_containing(text, match.start(), match.end())
        if quote_range is not None:
            role = _quoted_speaker_role(text, *quote_range)
            if role != "user":
                continue
        ranges.append((match.start(), match.end()))
    return ranges


def _third_party_self_harm_ranges(text: str) -> list[tuple[int, int]]:
    """Return current self-harm reports bound to an explicitly other person."""
    ranges: list[tuple[int, int]] = []
    for quote_start, quote_end in _actual_quote_ranges(text):
        if _quoted_speaker_role(text, quote_start, quote_end) != "other":
            continue
        quote = text[quote_start:quote_end]
        if re.search(
            r"(?:我|本人).{0,10}(?:想|要|会|准备|打算|决定).{0,8}"
            r"(?:自杀|轻生|想死|去死|跳楼|跳下去|跳下|伤害自己|结束自己的生命)|"
            r"(?:我|本人)(?:(?:现在|当前|目前|此刻|真的|已经|仍然|仍|还|也)\s*)*"
            r"不想活(?:了)?|"
            r"\bI\s+(?:(?:am|'m)\s+going\s+to|want\s+to|plan\s+to|"
            r"intend\s+to|will|(?:am|'m)\s+planning\s+to)\s+"
            r"(?:kill|hurt)\s+myself\b|\bI\s+am\s+suicidal\b",
            quote,
            re.IGNORECASE,
        ):
            ranges.append((quote_start, quote_end))
    for match in re.finditer(
        r"(?:朋友|同事|室友|伴侣|家人|亲属|他|她|对方)"
        r".{0,8}(?:现在|当前|目前|此刻|今天|今晚).{0,8}"
        r"(?:说|表示|告诉我|发消息说|发来消息(?:说)?|声称)"
        r"\s*[，,:：]?\s*(?:(?:他|她|对方|自己|本人)\s*)?"
        r"(?:马上|现在|当前|此刻|今晚|今天)?(?:要|想|准备|打算|会)?"
        r"(?:马上|现在|当前|此刻|今晚|今天)?"
        r"(?:自杀|轻生|去死|想死|跳楼|跳下去|跳下|伤害自己|结束自己的生命)|"
        r"(?:朋友|同事|室友|伴侣|家人|亲属|他|她|对方)"
        r".{0,8}(?:说|表示|告诉我|发消息说|发来消息(?:说)?|声称)"
        r"\s*[，,:：]?\s*(?:(?:他|她|对方|自己|本人)\s*)?"
        r"(?:马上|现在|当前|此刻|今晚|今天)(?:要|想|准备|打算|会)?"
        r"(?:马上|现在|当前|此刻|今晚|今天)?"
        r"(?:自杀|轻生|去死|想死|跳楼|跳下去|跳下|伤害自己|结束自己的生命)",
        text,
    ):
        if _quote_range_containing(text, match.start(), match.end()) is None:
            ranges.append((match.start(), match.end()))
    for pattern in (
        re.compile(
            r"\b(?:my\s+)?(?:friend|sister|brother|partner|roommate|"
            r"coworker|colleague)\b.{0,48}\b(?:texted|messaged|told|said)\b"
            r".{0,40}\b(?:she|he|they)\s+will\s+"
            r"(?:die|end\s+(?:her|his|their)\s+life)\s+tonight\b",
            re.IGNORECASE | re.DOTALL,
        ),
        re.compile(
            r"\b[A-Z][a-z]{1,24}\b.{0,24}\b(?:texted|messaged)\s+me\b"
            r".{0,32}\b(?:she|he|they)\s+will\s+"
            r"(?:die|end\s+(?:her|his|their)\s+life)\s+tonight\b",
            re.DOTALL,
        ),
        re.compile(
            r"\bmy\s+(?:friend|sister|brother|partner|roommate)\b"
            r".{0,96}\b(?:she|he|they)\s+said\b.{0,24}"
            r"\b(?:she|he|they)\s+will\s+"
            r"(?:die|end\s+(?:her|his|their)\s+life)\s+tonight\b",
            re.IGNORECASE | re.DOTALL,
        ),
    ):
        for match in pattern.finditer(text):
            ranges.append((match.start(), match.end()))
    return ranges


def _third_party_double_negated_self_harm_present(text: str) -> bool:
    """Keep an affirmative double negation bound to its quoted speaker."""
    for quote_start, quote_end in _actual_quote_ranges(text):
        if _quoted_speaker_role(text, quote_start, quote_end) != "other":
            continue
        quote = text[quote_start:quote_end]
        if (
            DOUBLE_NEGATED_SELF_HARM_PATTERN.search(quote)
            or COMPOSED_DOUBLE_NEGATED_SELF_HARM_PATTERN.search(quote)
            or DOUBLE_NEGATED_SELF_HARM_PLAN_PATTERN.search(quote)
        ):
            return True
    return False


def _remove_text_ranges(
    text: str, ranges: list[tuple[int, int]]
) -> str:
    if not ranges:
        return text
    pieces: list[str] = []
    cursor = 0
    for start, end in sorted(ranges):
        if start < cursor:
            continue
        pieces.append(text[cursor:start])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)


ACUTE_MEDICAL_COMPOSITE_EVENT_PATTERN = re.compile(
    r"\b(?:swallowed|took|ingested)\s+(?:a\s+)?(?:whole\s+)?"
    r"(?:bottle|handful|many|several)(?:\s+of)?\s+"
    r"(?:pills?|tablets?|medication)\b.{0,72}"
    r"\b(?:sleepy|drowsy|confused|hardly\s+stay\s+awake|"
    r"cannot\s+stay\s+awake|can(?:'|’)t\s+stay\s+awake)\b|"
    r"\b(?:my\s+)?(?:face|lips?|tongue|throat)\s+"
    r"(?:is\s+|are\s+)?swelling\b.{0,80}"
    r"\b(?:(?:can\s+barely|cannot|can(?:'|’)t|having\s+trouble)\s+breathe|"
    r"breathing\s+is\s+difficult|difficulty\s+breathing)\b|"
    r"\bcut\s+(?:my|his|her|their)\s+wrist\b.{0,64}"
    r"\b(?:the\s+)?bleeding\s+(?:will\s+not|won(?:'|’)t|"
    r"does\s+not|doesn(?:'|’)t)\s+stop\b|"
    r"(?:半边脸|嘴角).{0,10}(?:下垂|歪斜).{0,28}"
    r"(?:说话含糊|讲话不清|口齿不清).{0,32}"
    r"(?:左手|右手|手|胳膊|手臂).{0,12}(?:抬不起来|无法抬起|没有力气|无力)|"
    r"\b(?:baby|infant|toddler|child)\b.{0,24}"
    r"\b(?:is\s+)?(?:blue|turning\s+blue)\b.{0,32}"
    r"\b(?:not\s+breathing(?:\s+normally)?|only\s+gasping|gasping)\b|"
    r"\b(?:my|the)\s+(?:child|son|daughter|baby|toddler)\s+is\s+"
    r"(?:unconscious|unresponsive)\b.{0,40}\bafter\s+(?:a\s+)?fall\b|"
    r"\b(?:a\s+|the\s+)?(?:person|trainee|adult|child)\b.{0,20}"
    r"\b(?:has\s+)?collapsed\b.{0,32}\bunresponsive\b.{0,40}"
    r"\bnot\s+breathing(?:\s+normally)?\b|"
    r"\b(?:cannot|can(?:'|’)t)\s+move\s+(?:my\s+)?(?:left|right|one)\s+side\b"
    r".{0,48}\b(?:my\s+)?speech\s+is\s+slurred\b",
    re.IGNORECASE | re.DOTALL,
)
SELF_HARM_PREPARATION_EVENT_PATTERN = re.compile(
    r"(?:站在|坐在|到了|就在).{0,8}(?:阳台|天台|楼顶|窗台|桥)"
    r"(?:的)?(?:边缘|边沿|栏杆边)?.{0,24}"
    r"(?:想|要|准备|打算|可能).{0,8}(?:跳下去|跳楼|跳下)|"
    r"(?:遗书).{0,12}(?:写好|写完|准备好).{0,32}"
    r"(?:跳下去|跳楼|轻生)|"
    r"(?:绳子|绳索).{0,16}(?:挂好|挂上|系好).{0,32}"
    r"(?:撑不住|坚持不了|不确定.{0,8}(?:撑|坚持))|"
    r"\b(?:on|at)\s+(?:the\s+)?(?:roof|rooftop|balcony|bridge)\s+edge\b"
    r".{0,48}\b(?:may|might|want\s+to|plan\s+to|intend\s+to|"
    r"(?:am|'m)\s+going\s+to)\s+jump\b|"
    r"\b(?:bought|loaded|have)\s+(?:a\s+)?(?:gun|firearm)\b.{0,64}"
    r"\b(?:plan|intend|going)\s+to\s+use\s+it\s+on\s+myself\b",
    re.IGNORECASE | re.DOTALL,
)
ACTIVE_FIRE_GAS_OR_ENTRAPMENT_EVENT_PATTERN = re.compile(
    r"(?:厨房|房间|屋里|家里).{0,12}(?:着火|起火).{0,32}"
    r"(?:烧到|烧着|点燃).{0,12}(?:窗帘|家具|墙)|"
    r"(?:黑烟|浓烟).{0,28}(?:门把手|把手).{0,12}(?:很烫|发烫|烫手)"
    r".{0,32}(?:被困|困在|出不去)|"
    r"(?:煤气|燃气|天然气).{0,8}(?:味|气味).{0,32}"
    r"(?:嘶嘶声|漏气声|阀门.{0,8}(?:坏|破损|失灵))|"
    r"(?:爆炸).{0,16}(?:刚发生|发生了).{0,36}"
    r"(?:天花板|屋顶).{0,12}(?:掉|坠落|塌).{0,32}"
    r"(?:腿|手臂|身体).{0,12}(?:被压|压住|困住)|"
    r"\b(?:strong\s+)?gas\s+smell\b.{0,64}"
    r"\b(?:hissing(?:\s+sound)?|stove\s+valve\s+is\s+broken|broken\s+valve)\b|"
    r"\bsmell\s+gas\b.{0,64}\b(?:stove\s+)?valve\b.{0,16}"
    r"\b(?:is\s+)?broken\b|"
    r"\bsmoke\s+(?:is\s+)?(?:pouring|coming|entering)\s+"
    r"(?:from\s+)?under\s+(?:my|the)?\s*door\b|"
    r"\b(?:my\s+)?curtains?\s+(?:are|is)\s+burning\b|"
    r"\b(?:my\s+)?car\s+is\s+filling\s+with\s+smoke\b.{0,48}"
    r"\b(?:the\s+)?doors?\s+(?:will\s+not|won(?:'|’)t|"
    r"do\s+not|don(?:'|’)t)\s+open\b|"
    r"\bsmoke\s+is\s+(?:coming|pouring|entering).{0,32}\bdoor\b"
    r".{0,32}\bhandle\s+is\s+hot\b|"
    r"\bsmoke\s+is\s+(?:coming|pouring|entering)\s+"
    r"(?:into\s+)?(?:my|our)\s+(?:room|home|apartment|car)\b"
    r".{0,24}\b(?:now|right\s+now)\b|"
    r"\b(?:my\s+)?partner\s+is\s+(?:choking|strangling)\s+me\b"
    r".{0,48}\b(?:cannot|can(?:'|’)t)\s+(?:reach|get\s+to)\s+(?:the\s+)?door\b",
    re.IGNORECASE | re.DOTALL,
)
ACTIVE_ASSAULT_OR_INTRUSION_EVENT_PATTERN = re.compile(
    r"(?:前任|对方|陌生人|同事).{0,24}(?:发来消息|发消息|发来|发给我)"
    r".{0,20}[“‘\"']?(?:我)?(?:现在|今晚|今天).{0,12}"
    r"(?:(?:带|拿|持)(?:着)?枪.{0,16}(?:到|在)(?:你|我)?门口|"
    r"(?:杀|弄死|伤害)(?:你|我))|"
    r"(?=[^.!?。！？]{0,180}\b(?:someone|a\s+person|a\s+man|"
    r"a\s+stranger|my\s+ex)\b)"
    r"(?=[^.!?。！？]{0,180}\b(?:break(?:ing)?\s+down|"
    r"forc(?:e|ing))\b[^.!?。！？]{0,32}\bdoor\b)"
    r"(?=[^.!?。！？]{0,180}\b(?:gun|firearm)\b)|"
    r"(?=[^.!?。！？]{0,180}\b(?:a\s+)?(?:man|person|stranger)\b)"
    r"(?=[^.!?。！？]{0,180}\b(?:knife)\b)"
    r"(?=[^.!?。！？]{0,180}\bblock(?:ing|s|ed)\b[^.!?。！？]{0,24}\bexit\b)"
    r"(?=[^.!?。！？]{0,180}\bfollow(?:ed|ing|s)?\b)|"
    r"\b(?:someone|a\s+person|a\s+man|my\s+ex)\b.{0,40}"
    r"\b(?:break(?:ing)?\s+down|forc(?:e|ing)\s+open)\s+"
    r"(?:my\s+|the\s+)?(?:front\s+)?door\b.{0,56}\b(?:gun|firearm)\b|"
    r"\b(?:a\s+)?(?:man|person|stranger)\b.{0,28}\bfollowed\s+me\b"
    r".{0,56}\bblock(?:ing|s|ed)\s+(?:the\s+)?(?:only\s+)?exit\b"
    r".{0,32}\b(?:with\s+)?(?:a\s+)?knife\b|"
    r"(?:那个人|有人|陌生人).{0,28}(?:楼下|门外).{0,24}"
    r"(?:举着|拿着|持有)(?:一把)?枪.{0,24}(?:喊|叫).{0,12}(?:我的)?名字|"
    r"(?:听见|听到).{0,12}(?:玻璃|窗户).{0,8}(?:碎|破).{0,28}"
    r"(?:陌生人|有人).{0,20}(?:从|正从).{0,8}(?:窗户|窗口).{0,8}(?:爬进|翻进)|"
    r"\b(?:glass|window)\b.{0,12}\b(?:broke|breaking|shattered)\b"
    r".{0,48}\b(?:stranger|intruder|person)\b.{0,24}"
    r"\b(?:climbing|coming)\s+(?:in|inside|through)\b",
    re.IGNORECASE | re.DOTALL,
)
ACTIVE_PUBLIC_VIOLENCE_EVENT_PATTERN = re.compile(
    r"(?:有人|那个人|对方).{0,24}(?:正在)?(?:学校|校园|走廊).{0,16}"
    r"(?:开枪|射击)|"
    r"(?:发消息|消息).{0,24}(?:十|\d+)分钟后.{0,20}"
    r"(?:带枪|拿枪|持枪).{0,20}(?:学校|校园).{0,32}"
    r"(?:已经)?(?:在路上|出发|赶来)|"
    r"\b(?:someone|a\s+person|a\s+gunman)\b.{0,32}"
    r"\b(?:is\s+)?(?:firing\s+(?:a\s+)?gun|shooting)\b.{0,48}"
    r"\b(?:school|campus|hallway|corridor|classroom)\b",
    re.IGNORECASE | re.DOTALL,
)
ACTIVE_CUSTODY_OR_REMOVAL_EVENT_PATTERN = re.compile(
    r"(?:警察|警方|移民官员|边境官员).{0,28}(?:锁|关)在(?:车里|车辆里)"
    r".{0,40}(?:拘留|羁押).{0,40}(?:无法|不能).{0,12}(?:联系|找到)律师|"
    r"\b(?:immigration|border)\s+(?:officers?|agents?)\b.{0,72}"
    r"\b(?:removal\s+warrant|took|taken)\b.{0,40}"
    r"\b(?:passport|leave\s+immediately|cannot\s+leave|can(?:'|’)t\s+leave)\b|"
    r"\bpolice\b.{0,40}\blocked\s+me\s+in\s+(?:a\s+)?(?:car|vehicle)\b"
    r".{0,56}\b(?:detained|detention|being\s+detained)\b",
    re.IGNORECASE | re.DOTALL,
)


MEDICAL_EMERGENCY_EVENT_PATTERN = re.compile(
    r"\b(?:losing|spilling)\s+blood\s+(?:very\s+)?quickly\b.{0,24}"
    r"\b(?:now|right\s+now)\b|"
    r"(?:血|鲜血).{0,8}(?:喷|涌)(?:出来|出).{0,32}"
    r"(?:止不住|没有止住|仍在流).{0,24}(?:头晕|眩晕|要晕)|"
    r"(?:叫不醒|无法唤醒|失去反应).{0,24}(?:呼吸很慢|呼吸缓慢)"
    r".{0,24}(?:嘴唇|口唇).{0,6}(?:发紫|青紫)|"
    r"\b(?:unresponsive|cannot\s+be\s+woken)\b.{0,32}"
    r"\b(?:slow\s+breathing|blue\s+lips|turning\s+blue)\b",
    re.IGNORECASE | re.DOTALL,
)
SELF_HARM_CURRENT_EVENT_PATTERN = re.compile(
    r"\bI\s+(?:cannot|can(?:'|’)t)\s+promise\s+that\s+I\s+"
    r"won(?:'|’)t\s+hurt\s+myself\b|"
    r"\bI\s+(?:want|plan|intend)\s+to\s+die\s+(?:now|tonight)\b|"
    r"(?:我|本人).{0,12}(?:不是|并非)没有.{0,8}"
    r"(?:自杀|自伤|轻生)(?:计划|打算|念头)",
    re.IGNORECASE | re.DOTALL,
)
HARM_TO_OTHERS_EVENT_PATTERN = re.compile(
    r"\bI\s+(?:have\s+)?planted\s+(?:a\s+)?bomb\b.{0,48}"
    r"\b(?:timer|detonator)\b.{0,20}\b(?:running|active|counting)\b|"
    r"\bmy\s+(?:brother|sister|friend|partner|roommate|coworker)\b"
    r".{0,32}\b(?:says|said|texted)\b.{0,48}"
    r"\b(?:driving|going|heading)\b.{0,48}\b(?:shoot|kill|stab)\b"
    r".{0,48}\b(?:rifle|gun|knife|weapon)\b",
    re.IGNORECASE | re.DOTALL,
)
ACCESS_OR_LOCATION_EVENT_PATTERN = re.compile(
    r"(?:陌生人|前任|对方|同一个人).{0,28}(?:发来|发送).{0,24}"
    r"(?:门牌|家门口|新家门口).{0,12}(?:照片|实时照片).{0,36}"
    r"(?:到门口|在门口|家门口)|"
    r"(?:陌生人|前任|对方|同一个人|泄露住址的人).{0,28}"
    r"(?:发来|发送).{0,24}(?:新家|我家)?门口.{0,12}(?:实时)?照片|"
    r"(?:正在|一直).{0,8}(?:跟着|跟踪|尾随).{0,16}(?:走到|回到)?家门口|"
    r"(?:前任|对方).{0,24}(?:刚发来|发来|发消息).{0,16}"
    r"[“‘\"']?.{0,8}(?:现在|已经).{0,8}(?:你|我)?门外|"
    r"\b(?:stranger|intruder)\b.{0,32}\b(?:copied|stolen)\s+key\b"
    r".{0,40}\b(?:enter(?:ed)?|inside)\b.{0,48}\b(?:apartment|home|house)\b|"
    r"\b(?:entered|is\s+inside)\s+(?:my|our)\s+(?:apartment|home|house)\b"
    r".{0,48}\b(?:hide|hiding|locked)\b|"
    r"\b(?:stranger|my\s+ex|the\s+person)\b.{0,24}"
    r"\b(?:following|tracking|chasing)\s+me\b.{0,32}"
    r"\b(?:front\s+)?door\b.{0,16}\b(?:now|right\s+now)\b",
    re.IGNORECASE | re.DOTALL,
)
EXPLICIT_THREAT_EVENT_PATTERN = re.compile(
    r"\b(?:pointing|aiming)\s+(?:a\s+)?gun\s+at\s+me\b|"
    r"\boutside\s+(?:my|our)\s+door\b.{0,40}\bknife\b"
    r".{0,40}\b(?:kill|stab|hurt)\b|"
    r"\b(?:pounding|kicking|banging)\s+(?:on\s+)?(?:my|our|the|a)?\s*"
    r"(?:[a-z]+\s+){0,2}door\b|"
    r"\b(?:someone|a\s+person|a\s+man|a\s+stranger)\b.{0,36}"
    r"\b(?:is\s+)?trying\s+to\s+break\s+down\s+"
    r"(?:my|our|the)?\s*(?:front\s+)?door\b.{0,20}"
    r"\b(?:now|right\s+now)\b|"
    r"\bforcing\s+(?:my|our|the)?\s*door\s+open\b|"
    r"\b(?:broken|breaking|smashed|smashing)\s+(?:my|our|the)?\s*window\b"
    r".{0,40}\b(?:get|come|break)\s+inside\b|"
    r"\bchasing\s+me\b.{0,24}\b(?:with\s+)?(?:a\s+)?knife\b|"
    r"\bthreatened\s+me\b.{0,48}\b(?:following|chasing)\s+me\b|"
    r"\bthreatening\s+voicemail\b.{0,96}\bcaller\s+is\s+outside\s+now\b|"
    r"(?:同事|朋友|前任|对方|陌生人).{0,20}(?:刚|现在|当前)?"
    r"(?:说|发消息说|威胁|扬言).{0,16}(?:杀|弄死|伤害)我"
    r".{0,32}(?:枪|刀|武器)|"
    r"(?:破窗|砸窗|打破.{0,6}窗).{0,20}(?:闯入|进来|进去)",
    re.IGNORECASE | re.DOTALL,
)
OTHER_IMMEDIATE_EVENT_PATTERN = re.compile(
    r"(?:浓烟|烟雾).{0,24}(?:火焰|大火|火势).{0,24}(?:蔓延|扩散)|"
    r"(?:被人|有人把.{0,8})(?:锁|困)在(?:车里|房间|仓库).{0,40}"
    r"(?:实时位置|定位)|"
    r"(?:我|本人)?(?:现在|当前|此刻)?(?:真的)?(?:被人)?绑在(?:仓库|房间|车里)|"
    r"\b(?:partner|person|someone|he|she)\s+is\s+strangling\s+me\s+now\b|"
    r"\b(?:locked|trapped|tied|restrained)\s+(?:me|inside)\b.{0,40}"
    r"\b(?:car|vehicle|warehouse|room)\b",
    re.IGNORECASE | re.DOTALL,
)
URGENT_LEGAL_EVENT_PATTERN = re.compile(
    r"(?:执法人员|法警|移民官员|移民执法人员).{0,32}"
    r"(?:十|\d+)分钟后?.{0,16}(?:强制驱逐|强制搬离|遣返|拘留)|"
    r"\b(?:bailiff|enforcement\s+officers?)\b.{0,48}"
    r"\b(?:leave|evict(?:ed|ion)?)\b.{0,20}\b(?:ten|\d+)\s+minutes?\b|"
    r"\bimmigration\s+officers?\b.{0,48}\bdetain(?:ing|ed)?\b"
    r".{0,48}\b(?:removed?|deported?)\b.{0,16}\btonight\b",
    re.IGNORECASE | re.DOTALL,
)
CROSS_CLAUSE_THREAT_RECURRENCE_PATTERN = re.compile(
    r"\bthreatening\s+voicemail\b.{0,64}\b(?:19|20)\d{2}\b"
    r"\s*\.\s*(?:a|the)\s+new\s+(?:one|voicemail)\b.{0,48}"
    r"\b(?:one|\d+)\s+minutes?\s+ago\b.{0,40}"
    r"\bcaller\s+is\s+outside\s+now\b",
    re.IGNORECASE | re.DOTALL,
)
NEGATED_MEDICAL_EVENT_PATTERN = re.compile(
    r"\b(?:no\s+one|nobody)\s+is\s+(?:losing|spilling)\s+blood\b|"
    r"\b(?:is\s+not|isn(?:'|’)t|was\s+not|wasn(?:'|’)t)\s+"
    r"(?:bleeding|losing\s+blood)\b",
    re.IGNORECASE,
)
NEGATED_EXPLICIT_THREAT_EVENT_PATTERN = re.compile(
    r"\b(?:is\s+not|isn(?:'|’)t|was\s+not|wasn(?:'|’)t)\s+"
    r"(?:pointing|aiming)\s+(?:a\s+)?gun\s+at\s+me\b|"
    r"\b(?:is\s+not|isn(?:'|’)t)\s+(?:forcing|pounding|kicking|chasing)\b",
    re.IGNORECASE,
)
NEGATED_URGENT_LEGAL_EVENT_PATTERN = re.compile(
    r"\b(?:do\s+not|don(?:'|’)t|does\s+not|doesn(?:'|’)t)\s+"
    r"have\s+to\s+leave\b|"
    r"\b(?:will\s+not|won(?:'|’)t)\s+(?:evict|remove|deport|detain)\b",
    re.IGNORECASE,
)


def _clause_around(text: str, start: int, end: int) -> str:
    """Return the bounded event clause containing a pattern match."""
    left = max(
        (text.rfind(marker, 0, start) for marker in ("。", "！", "？", ";", "；", "\n", ".")),
        default=-1,
    )
    right_candidates = [
        position
        for marker in ("。", "！", "？", ";", "；", "\n", ".")
        for position in [text.find(marker, end)]
        if position >= 0
    ]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    return text[left + 1 : right]


def _iter_event_clauses(text: str) -> list[str]:
    """Split independent assertions before filling any risk-family slots."""
    return [
        clause.strip()
        for clause in re.split(
            r"[。！？；;\n]+|(?<!\d)\.(?=\s|$)",
            text,
        )
        if clause.strip()
    ]


def _has_asserted_family_event(
    text: str,
    positive: re.Pattern[str],
    locally_negated: re.Pattern[str] | None = None,
) -> bool:
    """Match a family predicate only when its own event is affirmative."""
    for clause in _iter_event_clauses(text):
        for match in positive.finditer(clause):
            if locally_negated is not None and locally_negated.search(clause):
                continue
            return True
    return False


def expected_safety_signal_types(text: str) -> set[str]:
    third_party_double_negated_self_harm = (
        _third_party_double_negated_self_harm_present(text)
    )
    text = _positive_risk_text(text)
    expected: set[str] = set()
    if _has_asserted_family_event(
        text,
        MEDICAL_EMERGENCY_EVENT_PATTERN,
        NEGATED_MEDICAL_EVENT_PATTERN,
    ) or _has_asserted_family_event(
        text,
        ACUTE_MEDICAL_COMPOSITE_EVENT_PATTERN,
    ) or re.search(
        r"胸痛|呼吸困难|失去意识|昏迷|严重出血|"
        r"胸口.{0,8}(?:像|仿佛|好像)?(?:被)?.{0,8}(?:压住|压着|重压|巨石)|"
        r"吞(?:了)?.{0,8}(?:瓶|把|很多)?药|"
        rf"吞药|过量服药|服药过量|{MEDICAL_VARIANT_PATTERN}|{MEDICATION_EMERGENCY_PATTERN}|overdose|can(?:'|’|‘)t breathe|cannot breathe|chest pain",
        text,
        re.IGNORECASE,
    ):
        expected.add("medical_emergency")
    third_party_self_harm_ranges = _third_party_self_harm_ranges(text)
    if third_party_self_harm_ranges:
        expected.add("third_party_self_harm_risk")
    if third_party_double_negated_self_harm:
        expected.add("third_party_self_harm_risk")
    self_harm_text = _remove_text_ranges(text, third_party_self_harm_ranges)
    if _has_asserted_family_event(
        self_harm_text,
        SELF_HARM_CURRENT_EVENT_PATTERN,
    ) or _has_asserted_family_event(
        self_harm_text,
        SELF_HARM_PREPARATION_EVENT_PATTERN,
    ) or re.search(
        rf"{SELF_DIRECTED_HARM_PATTERN}|{DIRECT_SELF_HARM_INTENT_PATTERN}|"
        r"(?:我|本人)(?:现在|当前|目前|此刻)?.{0,6}"
        r"(?:有|出现|又有).{0,4}自伤(?:的)?(?:想法|念头|计划|冲动)|"
        rf"自杀|不想活|(?:我|自己).{{0,10}}(?:想死|要死|准备去死)|"
        rf"(?:我|本人).{{0,8}}(?:想|要|会|准备|打算).{{0,8}}"
        rf"(?:杀(?:死|了)?|弄死|伤害)(?:我自己|自己|本人)|"
        rf"跳楼|割腕|上吊|吞药|过量服药|服药过量|伤害自己|结束自己的生命|"
        rf"(?:我|自己).{{0,6}}(?:想|要|准备).{{0,6}}结束这一切|轻生|"
        rf"{SELF_HARM_VARIANT_PATTERN}|{ROOFTOP_SELF_HARM_PATTERN}|overdose|suicide",
        self_harm_text,
        re.IGNORECASE,
    ):
        expected.add("self_harm_risk")
    if re.search(
        r"(?:以前|去年|曾经|之前).{0,16}(?:"
        r"砸(?:过|坏|毁)?(?:我|你|他|她)?(?:的)?(?:门|东西|物品)|"
        r"打(?:过|伤)?(?:我|你|他|她|别人|人)|"
        r"伤害(?:过)?(?:我|你|他|她|别人|人)|"
        r"破坏(?:过)?(?:门|东西|物品|财物))",
        text,
    ):
        expected.add("prior_violence_or_damage")
    if re.search(
        r"(?:他|她|对方|前任|陌生人).{0,16}"
        r"(?:知道|拿到|获得|掌握|有)(?:了)?(?:我的|你的|他的|她的)?"
        r"(?:门锁密码|住址|地址)|"
        r"知道.{0,8}(?:门锁密码|我住哪|你住哪)|"
        r"(?:我的|你的)?(?:门锁密码|住址).{0,10}(?:泄露|被知道|被拿到)|"
        r"(?:前任|对方|陌生人|他|她).{0,12}(?:有|拿着|拿到)"
        r"(?:了)?(?:我家|我住处|住处|家门)(?:的)?(?:钥匙|门卡)|"
        r"(?:knows?|has|got).{0,16}(?:my|our).{0,8}"
        r"(?:address|door code|location)",
        text,
        re.IGNORECASE,
    ):
        expected.add("access_or_location_exposure")
    if _has_asserted_family_event(text, ACCESS_OR_LOCATION_EVENT_PATTERN):
        expected.add("access_or_location_exposure")
    direct_harm_ranges = _direct_user_harm_to_others_ranges(text)
    if direct_harm_ranges or _has_asserted_family_event(
        text,
        HARM_TO_OTHERS_EVENT_PATTERN,
    ) or _has_asserted_family_event(
        text,
        ACTIVE_PUBLIC_VIOLENCE_EVENT_PATTERN,
    ):
        expected.add("harm_to_others_risk")
    external_threat_text = _remove_text_ranges(text, direct_harm_ranges)
    external_threat_text = re.sub(
        SELF_DIRECTED_HARM_PATTERN,
        "",
        external_threat_text,
        flags=re.IGNORECASE,
    )
    if _has_asserted_family_event(
        external_threat_text,
        EXPLICIT_THREAT_EVENT_PATTERN,
        NEGATED_EXPLICIT_THREAT_EVENT_PATTERN,
    ) or _has_asserted_family_event(
        external_threat_text,
        ACTIVE_ASSAULT_OR_INTRUSION_EVENT_PATTERN,
    ) or re.search(
        r"堵你|堵我|(?:他|她|对方|前任|陌生人).{0,6}"
        r"(?:(?:现在|当前|此刻|今晚|今天).{0,4}(?:又|再次|重新|正在)?|"
        r"(?:又|再次|重新|正在)).{0,6}(?:在|把)?"
        r"(?:(?:堵(?:着|住)?)(?:卧室|房间|我家|我们家|我住处|家)?(?:的)?门|"
        r"(?:卧室|房间|我家|我们家|我住处|家)?(?:的)?门堵(?:着|住)?|"
        r"(?:撞|砸)(?:卧室|房间|我家|我们家|我住处|家)?(?:的)?门)|"
        r"(?:他|她|对方|前任|陌生人).{0,16}堵在"
        r"(?:我家|我住处|家)?门外|杀了|杀死|弄死|打死|捅伤|捅死|砍伤|砍死|掐死|"
        rf"收拾我|打我|强奸|拿刀|带刀|持刀|{WEAPON_VARIANT_PATTERN}|有枪|斧头|锤子|棍子|武器|炸弹|扬言|威胁.{{0,12}}让我消失|见不到明天|"
        r"强行.{0,6}(?:进|来|到访)|闯进|跟踪|尾随|"
        rf"{COLLOQUIAL_THREAT_PATTERN}|{REPORTED_THREAT_PATTERN}|"
        r"(?:他|她|对方|前任|陌生人).{0,16}"
        r"(?:要|会|准备|打算).{0,6}(?:杀|弄死|捅|砍|打死).{0,6}"
        r"(?:我|你|他|她|对方)|"
        r"(?:他|她|对方|前任|陌生人).{0,20}(?:门口|门外)"
        r".{0,20}(?:手里)?(?:有|拿|带|持)(?:着)?(?:一把)?刀"
        r".{0,20}(?:威胁|试图|要|想).{0,8}(?:进来|闯入|进去)|"
        r"(?:他|她|对方|前任|陌生人).{0,12}"
        r"(?:(?:现在|当前|此刻|今晚|今天).{0,8}(?:正在)?|正在)"
        r"砸(?:公寓|我家|我们家|住处)?(?:的)?窗(?:户)?"
        r".{0,12}(?:试图|想|要).{0,8}(?:进来|闯入|进去)|"
        rf"{HISTORICAL_TIME_PATTERN}.{{0,24}}威胁过(?:我|你)"
        r".{0,40}(?:今天|今晚|现在|当前|此刻).{0,12}"
        r"(?:刚)?(?:发来|发消息|说).{0,16}"
        r"(?:我在你门口|在你门口|在门口|(?:他|她|对方)?在(?:我家|你家|住处)?门口)|"
        r"(?:曾威胁我的人|威胁过我的人|(?:他|她|对方).{0,8}威胁过我)"
        r".{0,24}(?:现在|当前|目前|此刻|今天|今晚).{0,12}"
        r"(?:就在|正在|在)(?:我|我家|我住处|家)?门(?:口|外)|"
        r"\b(?:(?:will|going to|threatened to|said.{0,12}(?:will|would))"
        r".{0,12}(?:(?:kill|stab|shoot)\s+(?:me|you|him|her|them|someone)|"
        r"shoot\s+at\s+(?:me|you|him|her|them|someone))|"
        r"break in|waiting outside)\b",
        external_threat_text,
        re.IGNORECASE,
    ) or CROSS_CLAUSE_THREAT_RECURRENCE_PATTERN.search(external_threat_text):
        expected.add("explicit_threat")
    if _has_urgent_legal_risk(text) or _has_asserted_family_event(
        text,
        URGENT_LEGAL_EVENT_PATTERN,
        NEGATED_URGENT_LEGAL_EVENT_PATTERN,
    ) or _has_asserted_family_event(
        text,
        ACTIVE_CUSTODY_OR_REMOVAL_EVENT_PATTERN,
    ):
        expected.add("urgent_legal_risk")
    if re.search(r"立即危险|现实危险|生命危险|紧急风险", text):
        expected.add("other_immediate_risk")
    if re.search(r"(?:菜刀|刀)(?:就|还)?在(?:我)?手边", text) and not re.search(
        r"切菜|切水果|削水果|做饭|做菜|切面包", text
    ):
        expected.add("other_immediate_risk")
    if _has_asserted_family_event(text, OTHER_IMMEDIATE_EVENT_PATTERN):
        expected.add("other_immediate_risk")
    if _has_asserted_family_event(
        text,
        ACTIVE_FIRE_GAS_OR_ENTRAPMENT_EVENT_PATTERN,
    ):
        expected.add("other_immediate_risk")
    return expected


def _derived_claim_status(
    claim: dict[str, Any],
    links: list[dict[str, Any]],
    superseded_claim_ids: set[str] | None = None,
    retracted_claim_ids: set[str] | None = None,
) -> str:
    kind = claim.get("kind")
    if claim.get("id") in (retracted_claim_ids or set()):
        return "retracted"
    if kind in {"observable_fact", "explicit_feeling"}:
        return "reported"
    if kind in DIRECTLY_ATTRIBUTED_KINDS:
        return (
            "superseded"
            if claim.get("id") in (superseded_claim_ids or set())
            else "directly_stated"
        )
    relations = {link.get("relation") for link in links}
    supports = "supports" in relations
    conflicts = "conflicts" in relations
    if supports and conflicts:
        return "conflicted"
    if conflicts:
        return "conflicted"
    if supports:
        return "weakly_supported"
    return "unverified"


ROLE_EVIDENCE_UNCERTAINTY_PATTERN = re.compile(
    r"听说|据说|据称|据传|转述|听来|听到|从.{0,12}(?:那里|那儿|处).{0,6}"
    r"(?:得知|获悉|听说|听到|了解)|"
    r"听(?:人|别人|同事|朋友)?讲|据我所知|"
    r"(?:我)?(?:是)?通过.{1,12}(?:得知|获悉|听说|了解到)|"
    r"我猜|猜测|推测|可能|也许|或许|大概|恐怕|似乎|好像|看起来"
)
ROLE_EVIDENCE_PAST_PATTERN = re.compile(
    rf"{PAST_TIME_SCOPE_FRAGMENT}"
)
ROLE_EVIDENCE_NEGATED_CHANGE_PATTERN = re.compile(
    r"(?:不是|并非|没有|没|未|并未|不曾).{0,8}"
    r"(?:削减|取消|失效|移交|发生变化|实质调整)|"
    r"(?:削减|取消|失效|移交|发生变化|实质调整).{0,6}"
    r"(?:并非|不是真的|不属实|没有发生|未发生)|"
    r"(?:不能|无法|不可)(?:说|认为|断定|认定).{0,16}"
    r"(?:削减|取消|失效|移交|发生变化|实质调整)"
)
ROLE_EVIDENCE_NEGATED_PRESERVATION_PATTERN = re.compile(
    r"(?:不是|并非|没有|没|未|并未|不曾).{0,8}"
    r"(?:保持不变|没有变化|仍写着|仍然保留|继续保留)|"
    r"(?:保持不变|没有变化|仍写着|仍然保留|继续保留).{0,6}"
    r"(?:并非|不是真的|不属实|没有|未)",
)
CURRENT_USER_ROLE_SCOPE_PATTERN = re.compile(
    r"我的|本人的|我们(?:的)?|自己的|给我的|允许我|邀请我|没让我|"
    r"没有让我|未让我|我.{0,18}没有被邀请|我.{0,18}没被邀请|"
    r"我.{0,18}(?:登录|查看|发现|收到|确认).{0,12}(?:自己|本人|我的)|"
    r"我.{0,18}(?:登录|查看|发现).{0,12}(?:职责|岗位|权限|审批)"
)
OTHER_PERSON_ROLE_SCOPE_PATTERN = re.compile(
    r"(?:他|她|对方|老板|经理|同事|朋友|前任|"
    r"小[一-鿿A-Za-z0-9]{1,3}|(?:李|王|张|刘|陈|杨|赵|黄|周|吴)[一-鿿]{0,2})的"
    r"(?:职责|岗位|权限|审批)|"
    r"我的(?:同事|朋友|下属|主管|经理|老板)"
    r"(?:小[一-鿿A-Za-z0-9]{1,3}|[一-鿿]{2,4})?"
    r"(?:的)?(?:职责|岗位|权限|审批)"
)


def _role_claim_is_current_user(text: str) -> bool:
    return bool(
        re.search(
            r"(?:架空|边缘化|排挤|踢出(?:项目|核心圈)|削弱|针对)(?:了)?我|"
            r"我.{0,16}(?:被|遭到|正在|已经)?(?:架空|边缘化|排挤|踢出|削弱|针对)|"
            r"(?:我的|本人的|自己的)(?:职责|岗位|权限|审批).{0,16}"
            r"(?:削减|取消|失效|移交|实质调整|发生变化)",
            text,
        )
    )


def _organization_entities(text: str) -> set[str]:
    """Extract explicitly named organizations and organizational units."""
    entities = {
        f"{match.group(1)}公司"
        for match in re.finditer(
            r"([甲乙丙丁戊己庚辛壬癸A-ZＡ-Ｚ])\s*公司", text
        )
    }
    for match in re.finditer(
        r"(?:在|于|来自|关于|针对|就|对)\s*"
        r"(?P<entity>[一-鿿A-Za-z0-9]{2,12}公司)",
        text,
    ):
        entities.add(match.group("entity"))
    for match in re.finditer(
        r"(?P<entity>(?:第?[一二三四五六七八九十0-9]+)"
        r"(?:事业部|业务部|部门|团队|项目组|分公司|分部))",
        text,
    ):
        entities.add(match.group("entity"))
    return entities


def _evidence_signals(
    text: str,
    *,
    source_label: str = "",
    source_type: str = "",
    source_context: str = "",
) -> set[str]:
    digit_translation = str.maketrans("０１２３４５６７８９", "0123456789")
    text = text.translate(digit_translation)
    source_label = source_label.translate(digit_translation)
    scoped_parts = [part for part in (source_label, source_context, text) if part]
    scoped_text = "\n".join(scoped_parts)
    epistemic_negation = re.search(
        r"(?:不能|无法|不足以|未能|并不能|并不)(?:直接)?(?:证明|说明|表明|支持|确认|佐证|证实)|"
        r"(?:没有|无|未|并未).{0,3}(?:证明|说明|表明|支持|确认|佐证|证实)|"
        r"(?:没有|无|缺少).{0,4}(?:证据|材料).{0,8}(?:证明|说明|表明|支持|确认|佐证|证实)",
        scoped_text,
    )
    if (
        epistemic_negation
        or source_type == "secondhand"
        or source_type == "direct_quote"
        or re.search(r"转述|二手|间接来源", source_label)
        or ROLE_EVIDENCE_UNCERTAINTY_PATTERN.search(scoped_text)
        or ROLE_EVIDENCE_PAST_PATTERN.search(scoped_text)
        or ROLE_EVIDENCE_NEGATED_CHANGE_PATTERN.search(scoped_text)
        or ROLE_EVIDENCE_NEGATED_PRESERVATION_PATTERN.search(scoped_text)
        or OUT_OF_SCOPE_CONTEXT_MARKERS.search(scoped_text)
        or OTHER_PERSON_ROLE_SCOPE_PATTERN.search(scoped_text)
        or not CURRENT_USER_ROLE_SCOPE_PATTERN.search(scoped_text)
    ):
        return set()

    signals: set[str] = set()
    if re.search(r"(?:连续|三次|两次|多次).{0,24}(?:没有被邀请|没让我参加|未参加).{0,24}(?:决策会|项目会|会议)", text):
        signals.add("role_participation_reduced")
    if re.search(r"(?:职责|岗位).{0,20}(?:保持不变|仍写着|没有变化)|保留.{0,12}(?:审批|权限)", text):
        signals.add("formal_role_preserved")
    formal_reduced = re.search(
        r"(?:职责|岗位|权限|审批).{0,20}(?:削减|取消|失效|移交|发生变化)",
        text,
    )
    if formal_reduced and not re.search(
        r"(?:没有|没|未|并未|不).{0,3}(?:削减|取消|失效|移交|发生变化)",
        formal_reduced.group(0),
    ):
        signals.add("formal_role_reduced")
    if re.search(r"仍允许.{0,16}(?:审批|访问)|(?:审批|访问).{0,12}(?:仍可|保留)", text):
        signals.add("system_authority_present")
    system_removed = re.search(
        r"(?:系统|审批|访问).{0,20}(?:失效|取消|无法|不能)", text
    )
    if system_removed and not re.search(
        r"(?:没有|没|未|并未|不).{0,3}(?:失效|取消|无法|不能)",
        system_removed.group(0),
    ):
        signals.add("system_authority_removed")
    return signals


def _is_self_scoped_role_text(text: str) -> bool:
    """Return whether a role proposition has the current user as its target."""
    return _role_claim_is_current_user(text)


def _allowed_relation_for_claim_evidence(
    claim: dict[str, Any], evidence: dict[str, Any]
) -> set[str]:
    kind = claim.get("kind")
    same_anchor = (
        claim.get("input_id") == evidence.get("input_id")
        and claim.get("source_span_id") == evidence.get("source_span_id")
        and claim.get("exact_quote") == evidence.get("exact_quote")
    )
    if kind in {"observable_fact", "explicit_feeling"} | DIRECTLY_ATTRIBUTED_KINDS:
        return {"supports"} if same_anchor else {"does_not_establish"}
    if kind in {"motive_inference", "identity_claim", "prediction"}:
        return {"does_not_establish"}
    if kind == "interpretation":
        # A labelled proposition may be tested against labelled, finite role
        # and authority signals.  The relation stays weak and can only produce
        # weakly_supported/conflicted, never a verified fact.  Unlabelled or
        # semantically unrelated prose remains fail closed.
        claim_ref = str(claim.get("source_ref", ""))
        evidence_ref = str(evidence.get("source_ref", ""))
        claim_text = str(claim.get("exact_quote", ""))
        evidence_text = str(evidence.get("exact_quote", ""))
        evidence_scope = (
            f"{str(evidence.get('source_label', ''))}\n{evidence_text}"
        )
        claim_entities = _organization_entities(claim_text)
        evidence_entities = _organization_entities(evidence_scope)
        if (
            re.fullmatch(r"P\d+", claim_ref)
            and re.fullmatch(r"E\d+", evidence_ref)
            and _role_claim_is_current_user(claim_text)
            and not OUT_OF_SCOPE_CONTEXT_MARKERS.search(evidence_scope)
            and not (
                claim_entities
                and evidence_entities
                and claim_entities.isdisjoint(evidence_entities)
            )
            and re.search(
                r"架空|边缘化|踢出(?:项目|核心圈)|"
                r"(?:职责|岗位|权限|审批).{0,12}(?:削减|取消|失效|移交|实质调整|发生变化)",
                claim_text,
            )
        ):
            signals = _evidence_signals(
                evidence_text,
                source_label=str(evidence.get("source_label", "")),
                source_type=str(evidence.get("source_type", "")),
                source_context=str(evidence.get("source_context", "")),
            )
            negative = {
                "role_participation_reduced",
                "formal_role_reduced",
                "system_authority_removed",
            }
            positive = {
                "formal_role_preserved",
                "system_authority_present",
            }
            has_negative = bool(signals & negative)
            has_positive = bool(signals & positive)
            if evidence.get("strict_role_relation") is True:
                if has_negative and not has_positive:
                    return {"supports"}
                if has_positive and not has_negative:
                    return {"conflicts"}
                return {"does_not_establish"}
            allowed = {"does_not_establish"}
            if has_negative:
                allowed.add("supports")
            if has_positive:
                allowed.add("conflicts")
            return allowed
        return {"does_not_establish"}
    return {"does_not_establish"}


def _allowed_relation_for_hypothesis_evidence(
    hypothesis: dict[str, Any], evidence: dict[str, Any]
) -> set[str]:
    """Derive bounded compatibility links for catalogued work hypotheses.

    These links never change a hypothesis into a fact. They are available only
    for explicitly labelled evidence spans and fail closed on visible context
    shifts such as another company or an unrelated example.
    """
    exact_quote = str(evidence.get("exact_quote", ""))
    source_ref = str(evidence.get("source_ref", ""))
    source_label = str(evidence.get("source_label", ""))
    scoped_text = f"{source_label}\n{exact_quote}"
    if (
        not re.fullmatch(r"E\d+", source_ref)
        or OUT_OF_SCOPE_CONTEXT_MARKERS.search(scoped_text)
    ):
        return {"does_not_establish"}
    signals = _evidence_signals(
        exact_quote,
        source_label=source_label,
        source_type=str(evidence.get("source_type", "")),
        source_context=str(evidence.get("source_context", "")),
    )
    hypothesis_type = hypothesis.get("hypothesis_type")
    positive = {"formal_role_preserved", "system_authority_present"}
    negative = {
        "role_participation_reduced",
        "formal_role_reduced",
        "system_authority_removed",
    }
    allowed = {"does_not_establish"}
    if hypothesis_type == "substantive_role_or_boundary_change":
        if signals & negative:
            allowed.add("supports")
        if signals & positive:
            allowed.add("conflicts")
    elif hypothesis_type == "temporary_scope_or_situational_constraint":
        if signals & positive:
            allowed.add("supports")
        if signals & negative:
            allowed.add("conflicts")
    return allowed


def _expected_link_strength(
    claim: dict[str, Any], evidence: dict[str, Any], relation: str
) -> str:
    if relation == "does_not_establish":
        return "none"
    same_anchor = (
        claim.get("input_id") == evidence.get("input_id")
        and claim.get("source_ref") == evidence.get("source_ref")
        and claim.get("exact_quote") == evidence.get("exact_quote")
    )
    if (
        relation == "supports"
        and same_anchor
        and claim.get("kind")
        in ({"observable_fact", "explicit_feeling"} | DIRECTLY_ATTRIBUTED_KINDS)
    ):
        return "direct"
    return "weak"


def _validate_anchor(
    errors: list[dict[str, str]],
    item: dict[str, Any],
    path: str,
    inputs: dict[str, dict[str, Any]],
    source_spans: dict[str, dict[str, Any]],
) -> None:
    input_id = item.get("input_id")
    span_id = item.get("source_span_id")
    exact_quote = item.get("exact_quote")
    input_text = _input_text(inputs, input_id)
    if input_text is None:
        errors.append(error("INPUT_REFERENCE_NOT_FOUND", f"{path}/input_id", "input_id does not exist"))
        return
    if not isinstance(exact_quote, str) or not exact_quote:
        errors.append(error("REQUIRED_STRING", f"{path}/exact_quote", "must be a non-empty string"))
    elif exact_quote not in input_text:
        errors.append(error("ANCHOR_NOT_FOUND", f"{path}/exact_quote", "anchor is absent from the referenced input"))
    if not isinstance(span_id, str) or not span_id:
        errors.append(error("SOURCE_SPAN_REQUIRED", f"{path}/source_span_id", "must reference a generated source span"))
        return
    span = source_spans.get(span_id)
    if span is None:
        errors.append(error("SOURCE_SPAN_NOT_FOUND", f"{path}/source_span_id", f"unknown source span {span_id}"))
        return
    if item.get("input_id") != span.get("input_id"):
        errors.append(error("SOURCE_SPAN_MISMATCH", f"{path}/input_id", "must equal the source span input_id"))
    if item.get("source_ref") != span.get("source_ref"):
        errors.append(error("SOURCE_SPAN_MISMATCH", f"{path}/source_ref", "must equal the source span source_ref"))
    if exact_quote != span.get("text"):
        errors.append(
            error(
                "SOURCE_SPAN_MISMATCH",
                f"{path}/exact_quote",
                "exact_quote must equal the complete generated source span",
            )
        )


def _expected_source_type_for_span(span: dict[str, Any]) -> str | None:
    source_label = str(span.get("source_label", ""))
    internal_tokens = {
        part.strip() for part in re.split(r"[｜|]", source_label)
    }
    if "inferred_secondhand_context" in internal_tokens:
        return "secondhand"
    if "inferred_artifact_context" in internal_tokens:
        return "unverified_artifact"
    return _external_source_label_type(
        source_label, quoted=span.get("quoted") is True
    )


def _expected_source_type_for_claim_span(
    span: dict[str, Any], claim_kind: str | None
) -> str | None:
    explicit = _expected_source_type_for_span(span)
    if explicit is not None:
        return explicit
    if span.get("quoted") is not True and claim_kind in {
        "interpretation",
        "motive_inference",
        "identity_claim",
        "prediction",
    }:
        return "user_report"
    if span.get("quoted") is not True and claim_kind == "observable_fact":
        return "user_direct_observation"
    return None


def _validate_inputs(
    errors: list[dict[str, str]], data: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    inputs = _index_by_id(errors, data.get("inputs"), "/inputs")
    for position, item in enumerate(data.get("inputs", []) if isinstance(data.get("inputs"), list) else []):
        path = f"/inputs/{position}"
        if not isinstance(item, dict):
            continue
        _add_unknown_keys(errors, item, INPUT_KEYS, path)
        text = _require_string(errors, item, "text", path)
        digest = _require_string(errors, item, "sha256", path)
        if text is not None and digest is not None and sha256_text(text) != digest:
            errors.append(error("INPUT_HASH_MISMATCH", f"{path}/sha256", "sha256 does not match input text"))
    current_id = data.get("current_input_id")
    if current_id not in inputs:
        errors.append(error("INPUT_REFERENCE_NOT_FOUND", "/current_input_id", "current_input_id does not exist"))
    else:
        expected = inputs[current_id].get("sha256")
        if data.get("input_sha256") != expected:
            errors.append(error("INPUT_HASH_MISMATCH", "/input_sha256", "must match the current input sha256"))
    return inputs


def _validate_source_spans(
    errors: list[dict[str, str]],
    data: dict[str, Any],
    inputs: dict[str, dict[str, Any]],
    *,
    previous: dict[str, Any] | None = None,
    validation_profile: str | None = None,
) -> dict[str, dict[str, Any]]:
    spans = _index_by_id(errors, data.get("source_spans"), "/source_spans")
    source_span_items = (
        data.get("source_spans", [])
        if isinstance(data.get("source_spans"), list)
        else []
    )
    input_items = (
        data.get("inputs", []) if isinstance(data.get("inputs"), list) else []
    )
    if previous is not None:
        prior_spans = (
            previous.get("source_spans", [])
            if isinstance(previous.get("source_spans"), list)
            else []
        )
        prior_input_ids = {
            item.get("id")
            for item in previous.get("inputs", [])
            if isinstance(item, dict)
        }
        expected = copy.deepcopy(prior_spans)
        counter = len(prior_spans) + 1
        for input_item in input_items:
            if (
                not isinstance(input_item, dict)
                or input_item.get("id") in prior_input_ids
            ):
                continue
            generated = generate_source_spans(
                str(input_item.get("id", "")),
                str(input_item.get("text", "")),
                counter,
            )
            expected.extend(generated)
            counter += len(generated)
        if source_span_items != expected:
            errors.append(
                error(
                    "CURRENT_SOURCE_SPAN_SET_MISMATCH",
                    "/source_spans",
                    "historical spans must remain unchanged and current-input spans must equal the current deterministic parser output",
                )
            )
            # Retain the stable aggregate code consumed by earlier runtimes and
            # receipts while exposing the more precise migration error above.
            errors.append(
                error(
                    "SOURCE_SPAN_SET_MISMATCH",
                    "/source_spans",
                    "source spans do not match the version-aware deterministic set",
                )
            )
    elif validation_profile == "current":
        expected: list[dict[str, Any]] = []
        counter = 1
        for input_item in input_items:
            if not isinstance(input_item, dict):
                continue
            generated = generate_source_spans(
                str(input_item.get("id", "")),
                str(input_item.get("text", "")),
                counter,
            )
            expected.extend(generated)
            counter += len(generated)
        if source_span_items != expected:
            errors.append(
                error(
                    "SOURCE_SPAN_SET_MISMATCH",
                    "/source_spans",
                    "source spans must equal the deterministic spans generated from all inputs",
                )
            )
    for position, item in enumerate(data.get("source_spans", []) if isinstance(data.get("source_spans"), list) else []):
        path = f"/source_spans/{position}"
        if not isinstance(item, dict):
            continue
        _add_unknown_keys(errors, item, SOURCE_SPAN_KEYS, path)
        for key in ("id", "input_id", "source_ref", "source_label", "text", "sha256"):
            _require_string(errors, item, key, path)
        if item.get("input_id") not in inputs:
            errors.append(error("INPUT_REFERENCE_NOT_FOUND", f"{path}/input_id", "input_id does not exist"))
        if not isinstance(item.get("start"), int) or not isinstance(item.get("end"), int):
            errors.append(error("SOURCE_SPAN_RANGE_INVALID", path, "start and end must be integers"))
        else:
            input_item = inputs.get(item.get("input_id"))
            input_text = (
                input_item.get("text") if isinstance(input_item, dict) else None
            )
            start = item.get("start")
            end = item.get("end")
            if (
                not isinstance(input_text, str)
                or start < 0
                or end <= start
                or end > len(input_text)
            ):
                errors.append(
                    error(
                        "SOURCE_SPAN_RANGE_INVALID",
                        path,
                        "span range must identify a non-empty slice of its input",
                    )
                )
            elif item.get("text") != input_text[start:end]:
                errors.append(
                    error(
                        "SOURCE_SPAN_TEXT_MISMATCH",
                        f"{path}/text",
                        "span text must equal the exact input slice at start:end",
                    )
                )
        if not isinstance(item.get("quoted"), bool):
            errors.append(error("REQUIRED_BOOLEAN", f"{path}/quoted", "must be a boolean"))
        if isinstance(item.get("text"), str) and item.get("sha256") != sha256_text(item["text"]):
            errors.append(error("SOURCE_SPAN_HASH_MISMATCH", f"{path}/sha256", "span hash does not match text"))
    return spans


def _validate_unclassified_observation_candidates(
    errors: list[dict[str, str]],
    data: dict[str, Any],
    inputs: dict[str, dict[str, Any]],
    source_spans: dict[str, dict[str, Any]],
    *,
    previous: dict[str, Any] | None = None,
    validation_profile: str | None = None,
) -> dict[str, dict[str, Any]]:
    field = data.get("unclassified_observation_candidates")
    candidates = _index_by_id(
        errors, field, "/unclassified_observation_candidates"
    )
    for position, item in enumerate(field if isinstance(field, list) else []):
        path = f"/unclassified_observation_candidates/{position}"
        if not isinstance(item, dict):
            continue
        _add_unknown_keys(
            errors, item, UNCLASSIFIED_OBSERVATION_CANDIDATE_KEYS, path
        )
        for key in (
            "id",
            "input_id",
            "source_span_id",
            "source_ref",
            "exact_quote",
            "status",
            "reason",
        ):
            _require_string(errors, item, key, path)
        if item.get("status") != "pending_confirmation":
            errors.append(
                error(
                    "ENUM_ERROR",
                    f"{path}/status",
                    "unclassified observation status must be pending_confirmation",
                )
            )
        if item.get("reason") != "finite_observation_grammar_no_match":
            errors.append(
                error(
                    "ENUM_ERROR",
                    f"{path}/reason",
                    "unclassified observation reason must record the finite grammar miss",
                )
            )
        _validate_anchor(errors, item, path, inputs, source_spans)
        span = source_spans.get(item.get("source_span_id"))
        input_text = _input_text(inputs, item.get("input_id")) or ""
        previous_candidates = {
            prior.get("id"): prior
            for prior in (
                previous.get("unclassified_observation_candidates", [])
                if isinstance(previous, dict)
                else []
            )
            if isinstance(prior, dict)
        }
        inherited_legacy_item = bool(
            item.get("input_id") in _legacy_epoch_ids(data, "input_ids")
            and previous_candidates.get(item.get("id")) == item
        )
        legacy_root_item = previous is None and validation_profile not in {
            None,
            "current",
        }
        if (
            isinstance(span, dict)
            and not inherited_legacy_item
            and not legacy_root_item
            and not _is_unclassified_observation_candidate(input_text, span)
        ):
            errors.append(
                error(
                    "OBSERVATION_CANDIDATE_NOT_DERIVED",
                    path,
                    "candidate is not a pending observation outside the finite fact grammar",
                )
            )

    if data.get("mode") == "standard" and not (
        previous is None and validation_profile not in {None, "current"}
    ):
        prior_items = (
            previous.get("unclassified_observation_candidates", [])
            if isinstance(previous, dict)
            and isinstance(previous.get("unclassified_observation_candidates"), list)
            else []
        )
        expected: list[dict[str, Any]] = copy.deepcopy(prior_items)
        counter = len(expected) + 1
        prior_input_ids = {
            item.get("id")
            for item in (
                previous.get("inputs", [])
                if isinstance(previous, dict)
                and isinstance(previous.get("inputs"), list)
                else []
            )
            if isinstance(item, dict)
        }
        ordered_spans = [
            item
            for item in data.get("source_spans", [])
            if isinstance(item, dict)
        ]
        for input_item in data.get("inputs", []):
            if not isinstance(input_item, dict):
                continue
            input_id = str(input_item.get("id", ""))
            if input_id in prior_input_ids:
                continue
            generated = generate_unclassified_observation_candidates(
                input_id,
                str(input_item.get("text", "")),
                ordered_spans,
                counter,
            )
            expected.extend(generated)
            counter += len(generated)
        if field != expected:
            errors.append(
                error(
                    "OBSERVATION_CANDIDATE_SET_MISMATCH",
                    "/unclassified_observation_candidates",
                    "pending candidates must equal deterministic unclassified observation spans",
                )
            )
    return candidates


USER_STORY_CONTENT_PATTERN = re.compile(
    r"回避型|NPD|人格|精神疾病|精神病|障碍|综合征|依恋|双相|躁郁|"
    r"抑郁症|躁狂症|出轨|不爱|爱我|故意|操纵|报复|蓄意|恶意|羞辱|"
    r"架空|边缘化|排挤|针对|冷暴力|惩罚|瞧不起|看不起|讨厌|恨我|嫌我|"
    r"不在乎|备胎|利用我|背叛我|没自制力|失败者|不配被爱|没用|"
    r"废物|无能|注定|永远|绝不会|迟早|早晚|终将|势必|必然|"
    r"成不了事|做不成事|开掉我|踢出核心圈|削弱我|撒谎|"
    r"(?:关系|感情|亲密关系).{0,8}(?:降级|恶化|破裂|结束)|"
    r"(?:把|将).{0,10}(?:我|你).{0,10}(?:放在|置于).{0,8}"
    r"(?:次要|不重要|低优先级)(?:位置)?"
)
PURE_ANALYSIS_REQUEST_PATTERN = re.compile(
    r"^\s*(?:请|请你|帮我|请帮我|麻烦你|你(?:直接)?)?.{0,8}"
    r"(?:分析|判断|解释|告诉我|说说|讲讲).{0,10}"
    r"(?:真实动机|原因|背后的心理|这意味着什么|怎么回事)[。！？!?]?\s*$"
)
NON_CLAIM_DIRECTIVE_PATTERN = re.compile(
    r"^\s*(?:也)?(?:不要|别|不能|请勿|禁止|无需|不必).{0,80}"
    r"(?:把|给|只|统一|倒灌|扩大|分析|判断|解释|证明|故事|事实|人格|动机)"
)


def _is_claimable_user_story_span(text: str) -> bool:
    value = text.strip()
    if (
        not value
        or _candidate_resolution_type(value) is not None
        or PURE_ANALYSIS_REQUEST_PATTERN.fullmatch(value)
        or NON_CLAIM_DIRECTIVE_PATTERN.match(value)
        or NONASSERTED_STORY_SCOPE_PATTERN.search(value)
        or _first_person_story_retraction_clauses(value)
    ):
        return False
    if USER_STORY_CONTENT_PATTERN.search(value):
        return True
    owner_match = FIRST_PERSON_EPISTEMIC_OWNER_PATTERN.match(value)
    if owner_match is not None:
        complement = value[owner_match.end() :].strip(" ，,：:；;。！？!?")
        # A bare grammatical subject is not yet a proposition.  Treating
        # ``我认为老板`` as complete would split the actual predicate at
        # ``是在`` and make provenance leak across the two fragments.
        if complement and not re.fullmatch(
            r"(?:我|你|他|她|对方|前任|老板|领导|经理|同事|朋友|公司|团队|部门|自己)",
            complement,
        ):
            return True
    return bool(
        re.search(
            r"(?:说明|意味着|所以|因此|可见|换句话说).{0,4}"
            r"(?:我|你|他|她|老板|公司|自己).{2,}",
            value,
        )
        and not re.search(r"(?:说明|意味着).{0,4}(?:什么|啥)[呢吗？?]?", value)
    )


IDENTITY_CLAIM_PATTERN = re.compile(
    r"回避型|NPD|人格障碍|精神疾病|精神病|双相|躁郁|抑郁症|躁狂症|"
    r"(?:是|就是|像|属于)(?:个|一个)?"
    r"(?:没自制力|失败者|废物|无能|没用|骗子|坏人|自私|冷漠|虚伪|"
    r"卑鄙|恶毒|不负责任|没担当|控制狂|渣男|渣女)(?:的)?(?:人)?|"
    r"我(?:就是|天生)?(?:没自制力|失败者|废物|无能|没用|不配被爱)"
)
PREDICTION_CLAIM_PATTERN = re.compile(
    r"永远(?:都)?不会|绝不会|注定|迟早|早晚|终将|势必|必然|"
    r"这辈子(?:都)?(?:回不来|不会回来|不再回来)|"
    r"未来.{0,12}(?:会|不会)|(?:会|将要|准备).{0,12}(?:开掉我|踢出核心圈)|"
    r"(?:他|她|对方|老板|公司)(?:肯定|一定|大概|可能)?"
    r"(?:会|将|将要|准备|打算|计划).{0,12}"
    r"(?:离开我?|回来|回头|复合|开掉我|踢出核心圈)|"
    r"(?:他|她|对方|老板|公司)"
    r"(?:(?:肯定|一定|大概|可能|恐怕|迟早|早晚|马上|很快|以后|未来)\s*)*"
    r"(?:会|不会|将|将会|将要|准备|打算|计划)\s*"
    r"(?:再?回来|不再回来|离开我?|跟我分手|和我分手|辞退我|开除我|"
    r"解雇我|撤掉我|换掉我|踢出核心圈|复合|回头)|"
    r"(?:他|她|对方|前任|老板|公司|男朋友|女朋友|伴侣|同事|朋友|"
    r"小[一-鿿A-Za-z0-9]{1,4}|[一-鿿A-Za-z0-9]{1,8}(?:公司|团队|部门))"
    r"(?:(?:肯定|一定|大概|可能|恐怕|迟早|早晚|马上|很快|以后|未来)\s*)*"
    r"(?:不会|会(?!不会)|将|将会|将要|准备|打算|计划)\s*"
    r"[^，,。！？；!?;]{1,20}|"
    r"^\s*(?:还|也|甚至|外加)\s*"
    r"(?:不会|会(?!不会)|将|将会|将要|准备|打算|计划)\s*"
    r"[^，,。！？；!?;]{1,20}|"
    r"(?:他|她|对方|前任|老板|公司|男朋友|女朋友|伴侣|同事|朋友|"
    r"小[一-鿿A-Za-z0-9]{1,4}|[一-鿿A-Za-z0-9]{1,8}(?:公司|团队|部门))"
    r"(?:明天|后天|下周|下个月|下季度|明年|未来)\s*"
    r"[^，,。！？；!?;]{1,20}"
)
MOTIVE_OR_INNER_STATE_CLAIM_PATTERN = re.compile(
    r"不爱我|爱(?:过)?我|在乎我|不在乎我|讨厌我|恨我|看不起我|瞧不起我|"
    r"故意|存心|成心|蓄意|恶意|为了.{0,12}(?:羞辱|惩罚|控制|操纵|伤害|报复)|"
    r"真实动机|内心.{0,12}(?:想|觉得|认为)|利用我|背叛我|"
    r"(?:存着|怀着|抱着).{0,8}(?:害|伤害|报复|算计).{0,8}(?:心|心思|念头)"
)
STORY_DISAVOWAL_PATTERN = re.compile(
    r"(?:我|本人)?(?:(?:暂时|现阶段|目前|现在|仍然|仍|还)\s*)?"
    r"(?:并)?(?:不|非|不是|并非|没有|没|未|并未|从未)"
    r".{0,8}(?:说|讲|表示|声称|认为|觉得|判断|推断|认定|确认|断定)|"
    r"(?:不是|并非)(?:我|本人)的(?:判断|看法|观点|结论)|"
    r"不代表(?:我|本人).{0,12}(?:认为|觉得|判断|同意|认可)|"
    r"(?:我|本人)?(?:只是|仅仅|仅)?(?:引用|转发|转述|复述)"
)
NONASSERTED_STORY_SCOPE_PATTERN = re.compile(
    r"^\s*(?:"
    r"(?:先|暂且|姑且)?(?:假设|假定|假如|倘若|如果|若|要是)(?:说)?|"
    r"(?:即使|即便|哪怕|纵使|纵然|就算|除非)|"
    r"(?:这|那|此|该)(?:件事|个情况|一情况|事实|行为|信号)?"
    r"(?:并)?(?:不等于|不能等同于|不代表)|"
    r"(?:谁能|谁敢|谁可以|凭什么)(?:就)?(?:说|断定|认定|判断|证明|认为)|"
    r"(?:我|本人)(?:所)?(?:希望|但愿|期望|期待)(?:的(?:事情|情况)?是)?|"
    rf"(?:不是|并非)(?:由)?{ARTIFACT_CARRIER_PATTERN}.{{0,8}}"
    rf"{ARTIFACT_REPORTING_PREDICATE_PATTERN}|"
    r"(?:我|本人)(?:并非|不是|并不|没有|没|未)"
    r".{0,8}(?:认为|觉得|判断|推断|主张)|"
    r"(?:这|那|此|该)?"
    r"(?:(?:现有|已有|当前|目前|这些|上述)(?:证据|依据|信息|材料)?(?:尚|还|仍)?|"
    r"单凭[^，,。！？；!?;]{1,28})?"
    r"(?:并)?(?:尚|还|仍)?(?:不足以|不能|无法|不(?:能)?)"
    r"(?:说明|意味着|证明|表明)|"
    r"(?:我|本人)(?:目前|现在|尚|还|仍)?(?:不能|无法|不敢)"
    r"(?:断定|确认|认定|判定)|"
    r"(?:没有|没|无|缺乏).{0,8}(?:证据|依据).{0,12}"
    r"(?:说明|意味着|证明|表明|支持)|"
    r"(?:并)?不是因为"
    r")"
)


def _story_kind_candidates(value: str) -> set[str]:
    text = value.strip()
    if (
        not text
        or STORY_DISAVOWAL_PATTERN.search(text)
        or NONASSERTED_STORY_SCOPE_PATTERN.search(text)
        or _first_person_story_retraction_clauses(text)
    ):
        return set()
    kinds: set[str] = set()
    if IDENTITY_CLAIM_PATTERN.search(text):
        kinds.add("identity_claim")
    if PREDICTION_CLAIM_PATTERN.search(text):
        kinds.add("prediction")
    if MOTIVE_OR_INNER_STATE_CLAIM_PATTERN.search(text):
        kinds.add("motive_inference")
    if _is_claimable_user_story_span(text) and not kinds:
        kinds.add("interpretation")
    elif (
        _is_claimable_user_story_span(text)
        and not {"identity_claim", "prediction", "motive_inference"}.intersection(kinds)
    ):
        kinds.add("interpretation")
    return kinds
STORY_RETRACTION_REFERENCE_PATTERN = re.compile(
    r"(?:上一轮|上一版|上一次|上次|之前|此前|刚才|先前|原先|原来)"
    r".{0,24}(?:解释|判断|看法|观点|结论|推断)|"
    r"(?:关于|对)(?P<topic>[^，,。！？；\n]{1,20}?)(?:的)?"
    r"(?:解释|判断|看法|观点|结论|推断)"
)
FIRST_PERSON_STORY_RETRACTION_PATTERN = re.compile(
    r"^\s*(?:"
    r"(?:我|本人)(?:明确|现在|郑重)?(?:撤回|收回).{0,56}"
    r"(?:解释|判断|看法|观点|结论|推断)|"
    r"(?:我|本人)(?:现在)?不再(?:认为|觉得|判断|推断).{1,56}|"
    r"(?:上一轮|上一版|上一次|上次|之前|此前|刚才|先前|原先|原来)"
    r".{0,32}(?:解释|判断|看法|观点|结论|推断)"
    r".{0,16}(?:不是|并非)(?:我|本人)的"
    r"(?:解释|判断|看法|观点|结论|推断)"
    r")\s*[。！？!?]?$"
)
RETRACTABLE_STORY_KINDS = {
    "interpretation",
    "motive_inference",
    "identity_claim",
    "prediction",
}


def _is_affirmative_completed_story_retraction_clause(clause: str) -> bool:
    """Accept only an affirmative, completed first-person withdrawal act."""
    value = clause.strip()
    if not FIRST_PERSON_STORY_RETRACTION_PATTERN.fullmatch(value):
        return False
    if value.endswith(("?", "？")):
        return False
    if re.search(
        r"(?:撤回|收回)(?:不了|不掉|不能|无法|未能|没能|失败|不成)|"
        r"(?:无法|不能|未能|没能|没有成功|并未成功).{0,8}(?:撤回|收回)",
        value,
    ):
        return False
    return not bool(
        re.search(
            r"(?:不|并不|没有|没|未|并未)(?:是要|打算|准备)?"
            r"(?:撤回|收回)",
            value,
        )
    )


def _first_person_story_retraction_clauses(text: str) -> list[str]:
    return [
        clause.strip()
        for clause in re.split(r"(?<=[。！？；!?])|\n", text)
        if clause.strip()
        and _is_affirmative_completed_story_retraction_clause(clause.strip())
    ]


NEGATED_EMBEDDED_STORY_EVALUATION_PATTERN = re.compile(
    r"^\s*(?:是|为)?\s*(?:不可能|不成立|不属实|假的|错的|错误的|"
    r"不对的|没有发生|未发生)"
)


def _non_embedded_story_match_spans(
    clause: str, story: dict[str, Any]
) -> set[tuple[int, int]]:
    """Return story mentions that are not inside a negated evaluation.

    A shorter story may be a prefix of a longer story.  Returning concrete
    spans lets the caller prefer the enclosing, more specific mention without
    guessing from string length alone.
    """
    old_quote = str(story.get("exact_quote", "")).strip("。！？；!?; ，,")
    old_core = re.sub(
        r"^(?:我|本人)(?:认为|觉得|判断|推断|猜测)",
        "",
        old_quote,
    ).strip()
    spans: set[tuple[int, int]] = set()
    for needle in {old_quote, old_core}:
        if not needle:
            continue
        start = 0
        while True:
            position = clause.find(needle, start)
            if position < 0:
                break
            end = position + len(needle)
            suffix = clause[end:]
            if not NEGATED_EMBEDDED_STORY_EVALUATION_PATTERN.match(suffix):
                spans.add((position, end))
            start = position + 1
    return spans


def _story_retraction_is_explicit(
    current_text: str,
    old_claim: dict[str, Any],
    active_prior_stories: list[dict[str, Any]],
) -> bool:
    """Bind an explicit current disavowal to one prior user story.

    A generic disagreement is not enough.  The current input must use a
    first-person disavowal and either name the old topic, repeat the old story,
    or unambiguously point to the only active story in the previous revision.
    """
    return old_claim.get("id") in _story_retraction_targets(
        current_text, active_prior_stories
    )


def _story_retraction_targets(
    current_text: str,
    active_prior_stories: list[dict[str, Any]],
) -> set[str]:
    """Bind each explicit retraction clause to at most one owned story.

    Retraction is a state transition, so broad substring matching is unsafe.
    A clause that targets several active stories, negates the embedded
    complement, or explicitly excludes the user's own interpretation remains
    unbound and requires clarification.
    """
    stories = [
        item
        for item in active_prior_stories
        if isinstance(item.get("id"), str) and item.get("id")
    ]
    targets: set[str] = set()
    for clause in _first_person_story_retraction_clauses(current_text):
        if re.search(
            r"而不是(?:我|本人)(?:自己)?的(?:解释|判断|看法|观点|结论|推断)|"
            r"(?:撤回|收回).{0,32}(?:转述|引用|复述).{0,16}"
            r"(?:他|她|对方|别人|他人)的(?:解释|判断|看法|观点|结论|推断)",
            clause,
        ):
            continue
        candidates: set[str] = set()
        direct_match_spans: dict[str, set[tuple[int, int]]] = {}
        for story in stories:
            story_id = str(story["id"])
            spans = _non_embedded_story_match_spans(clause, story)
            if spans:
                direct_match_spans[story_id] = spans

        # Remove only matches wholly contained in a more specific story
        # mention. Distinct mentions remain ambiguous even when one story text
        # happens to be longer than another.
        for story_id, spans in direct_match_spans.items():
            has_maximal_span = any(
                not any(
                    other_id != story_id
                    and other_start <= start
                    and end <= other_end
                    and (other_start, other_end) != (start, end)
                    for other_id, other_spans in direct_match_spans.items()
                    for other_start, other_end in other_spans
                )
                for start, end in spans
            )
            if has_maximal_span:
                candidates.add(story_id)

        if not candidates:
            for match in STORY_RETRACTION_REFERENCE_PATTERN.finditer(clause):
                topic = match.groupdict().get("topic")
                if not topic:
                    continue
                normalized_topic = re.sub(
                    r"(?:这个|这件事|相关|所谓)$", "", topic
                ).strip()
                if not normalized_topic:
                    continue
                for story in stories:
                    if normalized_topic in str(story.get("exact_quote", "")):
                        candidates.add(str(story["id"]))

        if not candidates and len(stories) == 1 and re.search(
            r"(?:上一轮|上一版|上一次|上次|之前|此前|刚才|先前|原先|原来)",
            clause,
        ):
            candidates.add(str(stories[0]["id"]))
        if len(candidates) == 1:
            targets.update(candidates)
    return targets

CANDIDATE_RESOLUTION_GENERIC_REFERENCE_PATTERN = re.compile(
    r"(?:上一句|上一条|上句话|上一条记录|前一句|前一条|刚才那句|刚才那条|"
    r"之前那句|此前那句|前面那句|那个观察|那条观察|刚才那个观察)"
)
CANDIDATE_RESOLUTION_USER_ASSERTION_PATTERN = re.compile(
    rf"^\s*(?:(?:我|本人)(?:已|已经|现在|后来)?"
    rf"(?:确认|核实|查明|澄清|更正)|"
    rf"{CANDIDATE_RESOLUTION_GENERIC_REFERENCE_PATTERN.pattern})"
)
CANDIDATE_RESOLUTION_REJECTION_PATTERN = re.compile(
    r"(?:"
    r"(?<!不)(?:是|属于|只是)(?:我)?(?:虚构(?:测试|内容|情节)?|"
    r"测试(?:输入|文本|用例)?|假的?|假消息|误传|谣言)|"
    r"(?:是)?我(?:编的|编造的)|"
    r"不(?:是|属于)(?:真实(?:事件)?|现实(?:事件)?)|"
    r"不属实|"
    r"(?:没有|没|未)(?:真实)?发生"
    r")"
)
CANDIDATE_RESOLUTION_CONFIRMATION_PATTERN = re.compile(
    r"(?:"
    r"(?:确实|真的|实际)(?:是)?(?:已经|曾经)?(?:发生|出现|存在)(?:了|过)?|"
    r"(?:确认|核实|查明).{0,20}(?:(?<!不)属实|真实|是真的|确实发生|真的发生)|"
    r"(?:是|为)(?:真实(?:事件)?|属实)|"
    r"是真的发生(?:了)?"
    r")"
)
CANDIDATE_RESOLUTION_DOUBLE_NEGATION_PATTERN = re.compile(
    r"(?:并非|不是)(?:没有|没|未)(?:真实)?发生"
)
CANDIDATE_RESOLUTION_HYPOTHETICAL_PATTERN = re.compile(
    r"(?:如果|假如|假设|倘若).{0,48}(?:发生|属实|真实)"
)
CANDIDATE_RESOLUTION_REPORTING_VERB_PATTERN = re.compile(
    r"(?:声称|表示|说|称|告诉|转述|提到)\s*[：:]?\s*[“‘\"']?\s*$"
)


def _candidate_resolution_scope(text: str) -> str:
    """Keep resolution polarity inside the target's own atomic clause."""
    anchor_end = 0
    quote_ranges = _actual_quote_ranges(text)
    if quote_ranges:
        anchor_end = quote_ranges[0][1]
    else:
        reference = CANDIDATE_RESOLUTION_GENERIC_REFERENCE_PATTERN.search(text)
        if reference is not None:
            anchor_end = reference.end()
    if anchor_end <= 0:
        return text
    clause_ends = [
        position
        for mark in "，,；;。！？!?\n"
        for position in [text.find(mark, anchor_end)]
        if position >= 0
    ]
    if not clause_ends:
        return text
    return text[: min(clause_ends) + 1]


def _candidate_resolution_type(text: str) -> str | None:
    """Derive an explicit user resolution without guessing truth from context."""
    value = text.strip()
    user_assertion = CANDIDATE_RESOLUTION_USER_ASSERTION_PATTERN.search(value)
    if not value or user_assertion is None:
        return None
    target_starts = [
        match.start()
        for match in CANDIDATE_RESOLUTION_GENERIC_REFERENCE_PATTERN.finditer(value)
    ]
    target_starts.extend(start for start, _ in _actual_quote_ranges(value))
    if target_starts:
        reporting_prefix = value[user_assertion.end() : min(target_starts)]
        reporting_match = CANDIDATE_RESOLUTION_REPORTING_VERB_PATTERN.search(
            reporting_prefix
        )
        if reporting_match is not None:
            reporter = reporting_prefix[: reporting_match.start()].strip(
                " ，,：:；;"
            )
            if reporter and reporter not in {"我", "本人", "并且我", "然后我"}:
                return None
    scope = _candidate_resolution_scope(value)
    if re.search(r"[?？]", scope) or CANDIDATE_RESOLUTION_HYPOTHETICAL_PATTERN.search(scope):
        return None
    if CANDIDATE_RESOLUTION_DOUBLE_NEGATION_PATTERN.search(scope):
        return "user_confirmed"
    if CANDIDATE_RESOLUTION_REJECTION_PATTERN.search(scope):
        return "user_rejected"
    if CANDIDATE_RESOLUTION_CONFIRMATION_PATTERN.search(scope):
        return "user_confirmed"
    return None


def _normalized_candidate_target(text: str) -> str:
    return re.sub(r"[。！？!?；;，,\s]+$", "", text.strip())


UNCLASSIFIED_OBSERVATION_SURFACE_PATTERN = re.compile(
    r"(?:"
    r"(?:我|本人)(?:亲眼)?(?:看到|看见|听到|收到)|"
    r"(?:把|将).{1,48}(?:了|给了|交给|撤下|移走|拿走|摔碎|放到)|"
    r"(?:没有|没|未).{0,28}(?:来|去|回|参加|出现|上班|到场|完成|回复)|"
    r"连续[0-9一二三四五六七八九十两]+(?:天|周|次).{1,36}"
    r"(?:回家|离开|出现|到达|迟到|缺席)|"
    r"(?:系统|页面|主页|名单|记录)(?:里|上|中)?.{0,36}"
    r"(?:不见|消失|撤下|移除|变成|显示)|"
    r"(?:我的|他的|她的|对方的|老板的)?[^，,。！？；!?;]{1,24}"
    r"被(?:剪|撕|折|砸|摔|划|涂|拆|换|移|锁|弄).{0,18}|"
    r"(?:门口|桌上|桌面|工位|办公室|会议室|页面|名单|记录里?)"
    r".{0,16}(?:多了|出现了?|放着|挂着|贴着|新增了?).{1,24}|"
    r"(?:我|本人|他|她|对方|老板|经理|主管|同事|朋友|公司|团队|部门)"
    r"(?:今天|刚刚|随后|后来)?"
    r"(?:锁上|锁住|关上|关掉|取走|拿走|带走|搬走|移走)了?"
    r"[^，,。！？；!?;]{1,32}(?:门|钥匙|文件|物品|设备|电脑|手机|工牌)"
    r")"
)
UNCLASSIFIED_OBSERVATION_NONREAL_PATTERN = re.compile(
    r"(?:电影|小说|剧本|游戏|歌词|台词|例句|虚构|梦到|梦见|梦里|梦中|想象|脑补|幻觉|"
    r"翻译素材|正则测试|regex|测试字符串|测试用例|测试文本|测试输入|测试样例)",
    re.IGNORECASE,
)
UNCLASSIFIED_OBSERVATION_NONASSERTED_PATTERN = re.compile(
    r"(?:"
    r"^\s*>|"
    r"^\s*(?:请|请你|帮我|麻烦你).{0,12}(?:记录|整理|改写|翻译|转换)|"
    r"^\s*(?:我(?:猜|推测|假设|怀疑|不确定|猜想|臆测|估计|希望)|"
    r"假设|如果|假如|倘若|也许|或许|大概|希望|估计)|"
    r"(?:可能|也许|或许|大概|好像|似乎).{0,36}"
    r"(?:看到|看见|听到|收到|把|将|没有|没|未|连续|系统|页面|主页|名单|记录)|"
    r"(?:吗|么|是否|是不是)[。！？!?]?\s*$|"
    r"^\s*我(?:很|非常|特别|有点|十分)?"
    r"(?:震惊|惊讶|害怕|难过|生气|焦虑|担心|失望|委屈)"
    r")"
)


def derive_claim_kind_for_span(
    exact_quote: str,
    span: dict[str, Any],
    input_text: str,
) -> str | None:
    """Derive the one bounded epistemic layer a span is allowed to occupy."""
    expected_quote_source = _expected_source_type_for_span(span)
    if (
        span.get("quoted") is True
        and expected_quote_source in {None, "direct_quote"}
    ):
        if (
            _direct_quote_scope_error(input_text, span) is None
            and not _direct_quote_has_past_scope(input_text, span)
            and derive_stated_position_type(exact_quote) is not None
        ):
            return "stated_position"
        if (
            _direct_quote_scope_error(
                input_text, span, allow_past_attribution=True
            )
            is None
            and derive_attributed_statement_type(exact_quote) is not None
        ):
            return "attributed_statement"
    # A visible quotation proves only that words were presented.  Unless it is
    # a bounded, asserted position above, its proposition cannot silently
    # become the user's own fact, feeling, motive story, diagnosis, or forecast.
    if span.get("quoted") is True:
        return None
    if "inferred_nonasserted_context" in {
        part.strip()
        for part in re.split(r"[｜|]", str(span.get("source_label", "")))
    }:
        return None
    if _span_contains_reported_quote(input_text, span):
        return (
            "interpretation"
            if _expected_source_type_for_span(span) == "secondhand"
            else None
        )
    if pure_formatting_payload(input_text) is not None:
        span_start = span.get("start")
        span_end = span.get("end")
        if isinstance(span_start, int) and isinstance(span_end, int) and any(
            span_start <= quote_start and quote_end <= span_end
            for quote_start, quote_end in _actual_quote_ranges(input_text)
        ):
            # The non-quoted carrier owns only the requested transformation;
            # the quoted operand is not a user belief or motive assertion.
            return None
    value = _semantic_text_for_span(input_text, span, exact_quote)
    if (
        PURE_ANALYSIS_REQUEST_PATTERN.fullmatch(value)
        or NON_CLAIM_DIRECTIVE_PATTERN.match(value)
        or STORY_DISAVOWAL_PATTERN.search(value)
        or NONASSERTED_STORY_SCOPE_PATTERN.search(value)
        or _first_person_story_retraction_clauses(value)
    ):
        return None
    if (
        _expected_source_type_for_span(span) == "secondhand"
        and _span_contains_reported_quote(input_text, span)
        and re.search(
            r"(?:感觉|认为|觉得|猜|推测|可能|也许|或许|好像|似乎|"
            r"故意|动机|人格|NPD|回避型|注定|永远)",
            exact_quote,
        )
    ):
        return "interpretation"
    # A directly named first-person feeling is already a complete epistemic
    # layer.  Verbs such as “觉得” can introduce either an experience or a
    # proposition; the experiencer predicate wins when a feeling is actually
    # named, preventing the same span from being required again as a story.
    if _is_current_user_explicit_feeling(exact_quote, span, input_text):
        return None
    story_kinds = _story_kind_candidates(value)
    if "identity_claim" in story_kinds:
        return "identity_claim"
    if "prediction" in story_kinds:
        return "prediction"
    if "motive_inference" in story_kinds:
        return "motive_inference"
    if "interpretation" in story_kinds:
        return "interpretation"
    return None


def _is_unclassified_observation_candidate(
    input_text: str, span: dict[str, Any]
) -> bool:
    """Keep plausible observations visible without upgrading them to facts.

    The finite fact grammar remains the only route into ``observable_fact``.
    This broader gate merely creates a pending, source-bound candidate when a
    short declarative span looks event-shaped but the finite grammar cannot
    classify it.  Story, feeling, quotation, transform, and safety scopes are
    excluded before the broader surface check is applied.
    """
    if span.get("quoted") is True:
        return False
    span_text = str(span.get("text", ""))
    value = _semantic_text_for_span(input_text, span, span_text).strip()
    if not value or len(value) > 120 or re.search(r"[?？]", value):
        return False
    if _span_contains_reported_quote(input_text, span):
        return False
    if _expected_source_type_for_span(span) == "secondhand":
        return False
    if (
        derive_observation_type(value, span) is not None
        and not _has_unconsumed_decisive_observation_correction(
            input_text, span
        )
    ):
        return False
    if _is_current_user_explicit_feeling(span_text, span, input_text):
        return False
    if derive_claim_kind_for_span(span_text, span, input_text) is not None:
        return False
    if (
        TRANSFORM_OPERATION_PATTERN.search(value)
        or _candidate_resolution_type(value) is not None
        or _candidate_resolution_type(input_text) is not None
        or UNCLASSIFIED_OBSERVATION_NONREAL_PATTERN.search(value)
        or UNCLASSIFIED_OBSERVATION_NONASSERTED_PATTERN.search(value)
        or PURE_ANALYSIS_REQUEST_PATTERN.fullmatch(value)
        or NON_CLAIM_DIRECTIVE_PATTERN.match(value)
        or STORY_DISAVOWAL_PATTERN.search(value)
        or _first_person_story_retraction_clauses(value)
        or USER_STORY_CONTENT_PATTERN.search(value)
        or detect_immediate_risk(value)
    ):
        return False
    return bool(UNCLASSIFIED_OBSERVATION_SURFACE_PATTERN.search(value))


def generate_unclassified_observation_candidates(
    input_id: str,
    input_text: str,
    source_spans: list[dict[str, Any]],
    start_counter: int = 1,
) -> list[dict[str, Any]]:
    """Generate deterministic pending candidates anchored to source spans."""
    candidates: list[dict[str, Any]] = []
    counter = start_counter
    for span in source_spans:
        if span.get("input_id") != input_id:
            continue
        if not _is_unclassified_observation_candidate(input_text, span):
            continue
        candidates.append(
            {
                "id": f"OC{counter}",
                "input_id": input_id,
                "source_span_id": span.get("id"),
                "source_ref": span.get("source_ref"),
                "exact_quote": span.get("text"),
                "status": "pending_confirmation",
                "reason": "finite_observation_grammar_no_match",
            }
        )
        counter += 1
    return candidates


def generate_candidate_resolutions(
    input_id: str,
    input_text: str,
    source_spans: list[dict[str, Any]],
    prior_candidates: list[dict[str, Any]],
    prior_resolutions: list[dict[str, Any]],
    start_counter: int = 1,
) -> list[dict[str, Any]]:
    """Resolve exactly one prior candidate from an explicit current user report.

    A generic backward reference is accepted only when one unresolved candidate
    exists. A quoted target may select one candidate from several, but its
    normalized quote must match uniquely. Confirmation records what the user
    confirmed; it does not create an observable-fact claim.
    """
    resolution_type = _candidate_resolution_type(input_text)
    if resolution_type is None:
        return []
    resolved_ids = {
        item.get("candidate_id")
        for item in prior_resolutions
        if isinstance(item, dict)
    }
    unresolved = [
        item
        for item in prior_candidates
        if isinstance(item, dict)
        and isinstance(item.get("id"), str)
        and item.get("id") not in resolved_ids
    ]
    if not unresolved:
        return []

    quoted_targets = [
        _normalized_candidate_target(input_text[start:end])
        for start, end in _actual_quote_ranges(input_text)
        if _normalized_candidate_target(input_text[start:end])
    ]
    target_matches: list[dict[str, Any]] = []
    if quoted_targets:
        target_matches = [
            item
            for item in unresolved
            if _normalized_candidate_target(str(item.get("exact_quote", "")))
            in quoted_targets
        ]
    elif CANDIDATE_RESOLUTION_GENERIC_REFERENCE_PATTERN.search(input_text):
        target_matches = unresolved
    if len(target_matches) != 1:
        return []

    trimmed = _trim_range(input_text, 0, len(input_text))
    anchor = None
    if trimmed:
        anchor = next(
            (
                item
                for item in source_spans
                if item.get("input_id") == input_id
                and item.get("quoted") is False
                and item.get("start") == trimmed[0]
                and item.get("end") == trimmed[1]
            ),
            None,
        )
    if anchor is None:
        anchor = next(
            (
                item
                for item in source_spans
                if item.get("input_id") == input_id
                and item.get("quoted") is False
                and _candidate_resolution_type(str(item.get("text", "")))
                == resolution_type
            ),
            None,
        )
    if anchor is None:
        return []
    target = target_matches[0]
    return [
        {
            "id": f"OCR{start_counter}",
            "candidate_id": target["id"],
            "resolution_type": resolution_type,
            "input_id": input_id,
            "source_span_id": anchor.get("id"),
            "source_ref": anchor.get("source_ref"),
            "exact_quote": anchor.get("text"),
        }
    ]


def _validate_candidate_resolutions(
    errors: list[dict[str, str]],
    data: dict[str, Any],
    inputs: dict[str, dict[str, Any]],
    source_spans: dict[str, dict[str, Any]],
    candidates: dict[str, dict[str, Any]],
    *,
    previous: dict[str, Any] | None = None,
    validation_profile: str | None = None,
) -> dict[str, dict[str, Any]]:
    # Schema 3 requires the ledger. Keep the defensive default so malformed
    # input produces structured validation errors instead of a runtime crash.
    field = data.get("candidate_resolutions", [])
    resolutions = _index_by_id(errors, field, "/candidate_resolutions")
    input_order = {
        item.get("id"): position
        for position, item in enumerate(data.get("inputs", []))
        if isinstance(item, dict)
    }
    resolved_candidates: set[str] = set()
    for position, item in enumerate(field if isinstance(field, list) else []):
        path = f"/candidate_resolutions/{position}"
        if not isinstance(item, dict):
            continue
        _add_unknown_keys(errors, item, CANDIDATE_RESOLUTION_KEYS, path)
        for key in CANDIDATE_RESOLUTION_KEYS:
            _require_string(errors, item, key, path)
        if not re.fullmatch(r"OCR[1-9][0-9]*", str(item.get("id", ""))):
            errors.append(
                error(
                    "CANDIDATE_RESOLUTION_ID_INVALID",
                    f"{path}/id",
                    "candidate resolution id must use OCR followed by a positive integer",
                )
            )
        if item.get("resolution_type") not in CANDIDATE_RESOLUTION_TYPES:
            errors.append(
                error(
                    "ENUM_ERROR",
                    f"{path}/resolution_type",
                    "unsupported candidate resolution type",
                )
            )
        _validate_anchor(errors, item, path, inputs, source_spans)
        candidate_id = item.get("candidate_id")
        candidate = candidates.get(candidate_id)
        if candidate is None:
            errors.append(
                error(
                    "CANDIDATE_REFERENCE_NOT_FOUND",
                    f"{path}/candidate_id",
                    "candidate_id does not exist",
                )
            )
        else:
            candidate_position = input_order.get(candidate.get("input_id"), -1)
            resolution_position = input_order.get(item.get("input_id"), -1)
            if candidate_position < 0 or resolution_position <= candidate_position:
                errors.append(
                    error(
                        "CANDIDATE_RESOLUTION_ORDER_INVALID",
                        path,
                        "a resolution must be anchored to a later input than its candidate",
                    )
                )
        if candidate_id in resolved_candidates:
            errors.append(
                error(
                    "CANDIDATE_ALREADY_RESOLVED",
                    f"{path}/candidate_id",
                    "one candidate may be resolved only once",
                )
            )
        elif isinstance(candidate_id, str):
            resolved_candidates.add(candidate_id)

    if data.get("mode") in {"standard", "safety"} and not (
        previous is None and validation_profile not in {None, "current"}
    ):
        prior_resolutions = (
            previous.get("candidate_resolutions", [])
            if isinstance(previous, dict)
            and isinstance(previous.get("candidate_resolutions"), list)
            else []
        )
        expected: list[dict[str, Any]] = copy.deepcopy(prior_resolutions)
        prior_input_ids = {
            item.get("id")
            for item in (
                previous.get("inputs", [])
                if isinstance(previous, dict)
                and isinstance(previous.get("inputs"), list)
                else []
            )
            if isinstance(item, dict)
        }
        ordered_candidates = [
            item
            for item in data.get("unclassified_observation_candidates", [])
            if isinstance(item, dict)
        ]
        ordered_spans = [
            item for item in data.get("source_spans", []) if isinstance(item, dict)
        ]
        ordered_inputs = [
            item for item in data.get("inputs", []) if isinstance(item, dict)
        ]
        for input_position, input_item in enumerate(ordered_inputs):
            input_id = str(input_item.get("id", ""))
            if input_id in prior_input_ids:
                continue
            if (
                data.get("mode") == "safety"
                and input_id == data.get("current_input_id")
            ):
                continue
            prior_candidates = [
                item
                for item in ordered_candidates
                if input_order.get(item.get("input_id"), input_position)
                < input_position
            ]
            generated = generate_candidate_resolutions(
                input_id,
                str(input_item.get("text", "")),
                ordered_spans,
                prior_candidates,
                expected,
                len(expected) + 1,
            )
            expected.extend(generated)
        if field != expected:
            errors.append(
                error(
                    "CANDIDATE_RESOLUTION_SET_MISMATCH",
                    "/candidate_resolutions",
                    "candidate resolutions must equal deterministic source-bound user resolutions",
                )
            )
    return resolutions


def _validate_current_claim_coverage(
    errors: list[dict[str, str]],
    data: dict[str, Any],
    inputs: dict[str, dict[str, Any]],
    source_spans: dict[str, dict[str, Any]],
    claims: dict[str, dict[str, Any]],
    *,
    validation_profile: str | None = None,
) -> None:
    """Require the current standard case to retain every recognized layer."""
    if data.get("mode") != "standard" or validation_profile not in {
        None,
        "current",
    }:
        return
    current_input_id = data.get("current_input_id")
    claims_by_span: dict[str, list[dict[str, Any]]] = {}
    for claim in claims.values():
        if claim.get("input_id") != current_input_id:
            continue
        span_id = claim.get("source_span_id")
        if isinstance(span_id, str):
            claims_by_span.setdefault(span_id, []).append(claim)

    for span_id, span in source_spans.items():
        if span.get("input_id") != current_input_id:
            continue
        span_text = str(span.get("text", ""))
        anchored_claims = claims_by_span.get(span_id, [])
        input_text = _input_text(inputs, current_input_id) or ""
        semantic_text = _semantic_text_for_span(input_text, span, span_text)
        expected_source_type = _expected_source_type_for_span(span)
        observation_type = (
            None
            if span.get("quoted") is True
            or _span_contains_reported_quote(input_text, span)
            or _has_unconsumed_decisive_observation_correction(
                input_text, span
            )
            else derive_observation_type(semantic_text, span)
        )
        observable_source = expected_source_type in {
            None,
            "user_direct_observation",
            "unverified_artifact",
        }
        if observation_type is not None and observable_source:
            if not any(
                item.get("kind") == "observable_fact"
                and item.get("observation_type") == observation_type
                and item.get("source_type")
                in {"user_direct_observation", "unverified_artifact"}
                for item in anchored_claims
            ):
                errors.append(
                    error(
                        "OBSERVABLE_FACT_CLAIM_MISSING",
                        "/claims",
                        f"recognized current observation span was omitted: {span_id}",
                    )
                )
            continue
        if (
            _is_current_user_explicit_feeling(span_text, span, input_text)
            and not any(
                item.get("kind") == "explicit_feeling"
                and item.get("source_type") == "explicit_self_report"
                for item in anchored_claims
            )
        ):
            errors.append(
                error(
                    "EXPLICIT_FEELING_CLAIM_MISSING",
                    "/claims",
                    f"recognized current self-reported feeling was omitted: {span_id}",
                )
            )
            continue
        expected_kind = derive_claim_kind_for_span(span_text, span, input_text)
        if expected_kind in DIRECTLY_ATTRIBUTED_KINDS and not any(
            item.get("kind") == expected_kind for item in anchored_claims
        ):
            errors.append(
                error(
                    (
                        "STATED_POSITION_CLAIM_MISSING"
                        if expected_kind == "stated_position"
                        else "ATTRIBUTED_STATEMENT_CLAIM_MISSING"
                    ),
                    "/claims",
                    f"recognized direct statement was omitted: {span_id}",
                )
            )
        elif expected_kind in {
            "interpretation",
            "motive_inference",
            "identity_claim",
            "prediction",
        } and not re.search(r"[?？]", semantic_text) and expected_source_type != "secondhand" and not any(
            item.get("kind") == expected_kind for item in anchored_claims
        ):
            errors.append(
                error(
                    "USER_STORY_CLAIM_MISSING",
                    "/claims",
                    f"recognized current {expected_kind} was omitted: {span_id}",
                )
            )


DECISIVE_OBSERVATION_CORRECTION_PATTERN = re.compile(
    r"^\s*[，,]?\s*(?:但|可是|不过|然而)?\s*"
    r"(?:后来|随后|之后)?\s*(?:我|本人)?\s*"
    r"(?:发现|确认|核实(?:后)?|查明)\s*"
    r"(?:那|这|该)(?:个|一)?(?:事件|情况|画面|内容|东西)?\s*"
    r"(?:只是|不过是|原来(?:只)?是|并不是|并非)"
)
EXPLICIT_PARTICIPATION_CORRECTION_PATTERN = re.compile(
    r"^\s*(?:纠正|更正)(?:一下)?\s*[，,:：]\s*"
    r"(?P<actor>我|你|他|她|对方|老板|经理|同事|前任)\s*参加了"
    r"(?:会议|约会|项目会|决策会|例会|周会|活动|见面|汇报|讨论)?"
    r"[。！？；]?\s*$"
)


def _has_unconsumed_decisive_observation_correction(
    input_text: str, span: dict[str, Any]
) -> bool:
    """Return whether the same sentence immediately reclassifies an event.

    The validator fails closed because the current schema has no dedicated
    correction relation for an observation.  Ordinary later events do not
    match the anaphoric reclassification grammar.
    """
    end = span.get("end")
    if not isinstance(end, int) or end < 0 or end > len(input_text):
        return False
    sentence_end = min(
        (
            position
            for marker in "。！？；\n"
            for position in [input_text.find(marker, end)]
            if position >= 0
        ),
        default=len(input_text),
    )
    tail = input_text[end:sentence_end]
    if DECISIVE_OBSERVATION_CORRECTION_PATTERN.match(tail):
        return True
    correction = EXPLICIT_PARTICIPATION_CORRECTION_PATTERN.match(tail)
    if correction is None:
        return False
    old_text = str(span.get("text", ""))
    actor = correction.group("actor")
    return bool(
        re.fullmatch(
            rf"\s*{re.escape(actor)}\s*(?:没有|没|未)参加"
            r"(?:会议|约会|项目会|决策会|例会|周会|活动|见面|汇报|讨论)"
            r"[。！？；]?\s*",
            old_text,
        )
    )


def _validate_claims(
    errors: list[dict[str, str]],
    data: dict[str, Any],
    inputs: dict[str, dict[str, Any]],
    source_spans: dict[str, dict[str, Any]],
    *,
    previous: dict[str, Any] | None = None,
    validation_profile: str | None = None,
) -> dict[str, dict[str, Any]]:
    claims = _index_by_id(errors, data.get("claims"), "/claims")
    previous_claims = {
        item.get("id"): item
        for item in (
            previous.get("claims", [])
            if isinstance(previous, dict) and isinstance(previous.get("claims"), list)
            else []
        )
        if isinstance(item, dict)
    }
    legacy_root = previous is None and validation_profile not in {None, "current"}
    legacy_claim_ids = _legacy_epoch_ids(data, "claim_ids")
    for position, item in enumerate(data.get("claims", []) if isinstance(data.get("claims"), list) else []):
        path = f"/claims/{position}"
        if not isinstance(item, dict):
            continue
        _add_unknown_keys(errors, item, CLAIM_KEYS, path)
        for key in ("id", "text", "input_id", "source_span_id", "source_ref", "exact_quote"):
            _require_string(errors, item, key, path)
        kind = item.get("kind")
        observation_type = item.get("observation_type")
        source_type = item.get("source_type")
        status = item.get("epistemic_status")
        boundary = _require_bool(errors, item, "diagnostic_boundary", path)
        if kind not in CLAIM_KINDS:
            errors.append(error("ENUM_ERROR", f"{path}/kind", "unsupported claim kind"))
        if source_type not in SOURCE_TYPES:
            errors.append(error("ENUM_ERROR", f"{path}/source_type", "unsupported source type"))
        if status not in EPISTEMIC_STATUSES:
            errors.append(error("ENUM_ERROR", f"{path}/epistemic_status", "unsupported epistemic status"))
        _validate_anchor(errors, item, path, inputs, source_spans)

        input_text = _input_text(inputs, item.get("input_id")) or ""
        exact_quote = item.get("exact_quote") if isinstance(item.get("exact_quote"), str) else ""
        claim_text = item.get("text") if isinstance(item.get("text"), str) else ""
        if claim_text and exact_quote and claim_text != exact_quote:
            errors.append(
                error(
                    "CLAIM_TEXT_NOT_ANCHOR",
                    f"{path}/text",
                    "claim text must equal its exact source anchor; free paraphrases are not trusted",
                )
            )
        if source_type in {"verified_artifact", "external_verified"}:
            errors.append(
                error(
                    "SOURCE_ATTESTATION_UNSUPPORTED",
                    f"{path}/source_type",
                    "this local runtime cannot attest verified sources from a self-declared label",
                )
            )
        span = source_spans.get(item.get("source_span_id"), {})
        prior_claim = previous_claims.get(item.get("id"))
        inherited_legacy_claim = bool(
            item.get("id") in legacy_claim_ids
            and isinstance(prior_claim, dict)
            and all(
                item.get(key) == prior_claim.get(key)
                for key in set(item) | set(prior_claim)
                if key != "epistemic_status"
            )
        )
        legacy_semantics = legacy_root or inherited_legacy_claim
        expected_claim_kind = (
            kind
            if legacy_semantics
            else derive_claim_kind_for_span(exact_quote, span, input_text)
        )
        derived_story_kinds = {
            "interpretation",
            "motive_inference",
            "identity_claim",
            "prediction",
            "stated_position",
            "attributed_statement",
        }
        if (
            not legacy_semantics
            and
            kind in derived_story_kinds
            and kind != expected_claim_kind
        ):
            errors.append(
                error(
                    "CLAIM_KIND_NOT_DERIVED",
                    f"{path}/kind",
                    (
                        f"anchored text requires claim kind {expected_claim_kind}"
                        if expected_claim_kind is not None
                        else "anchored text is not an asserted current story or stated position"
                    ),
                )
            )
        if source_type == "direct_quote" and span.get("quoted") is not True:
            errors.append(
                error(
                    "DIRECT_QUOTE_NOT_BOUNDED",
                    f"{path}/exact_quote",
                    "direct_quote must be inside the actual quotation span that contains this anchor",
                )
            )
            errors.append(
                error(
                    "SOURCE_TYPE_MISMATCH",
                    f"{path}/source_type",
                    "direct_quote requires an anchor inside a visible quotation span",
                )
            )
        elif source_type == "direct_quote" and not legacy_semantics:
            quote_scope_error = _direct_quote_scope_error(
                input_text,
                span,
                allow_past_attribution=kind == "attributed_statement",
            )
            if quote_scope_error is not None:
                code, message = quote_scope_error
                errors.append(error(code, f"{path}/exact_quote", message))
        source_semantic_kind = (
            "observable_fact" if kind == "observable_fact" else expected_claim_kind
        )
        expected_source_type = (
            None
            if legacy_semantics
            else _expected_source_type_for_claim_span(span, source_semantic_kind)
        )
        if expected_source_type and source_type != expected_source_type:
            errors.append(
                error(
                    "SOURCE_TYPE_MISMATCH",
                    f"{path}/source_type",
                    f"source context requires {expected_source_type}",
                )
            )
        if kind == "explicit_feeling" and source_type != "explicit_self_report":
            errors.append(
                error(
                    "SOURCE_TYPE_MISMATCH",
                    f"{path}/source_type",
                    "explicit feelings require explicit_self_report",
                )
            )
        if source_type == "explicit_self_report" and kind != "explicit_feeling":
            errors.append(
                error(
                    "SOURCE_TYPE_MISMATCH",
                    f"{path}/source_type",
                    "explicit_self_report is reserved for feelings the user actually named",
                )
            )
        if kind in DIRECTLY_ATTRIBUTED_KINDS and source_type != "direct_quote":
            errors.append(
                error(
                    "SOURCE_TYPE_MISMATCH",
                    f"{path}/source_type",
                    "directly attributed claims require a direct quote",
                )
            )
        if (
            not legacy_semantics
            and
            kind == "attributed_statement"
            and derive_attributed_statement_type(exact_quote) is None
        ):
            errors.append(
                error(
                    "ATTRIBUTED_STATEMENT_TYPE_UNSUPPORTED",
                    f"{path}/exact_quote",
                    "quoted content is not a bounded declarative utterance",
                )
            )
        if (
            not legacy_semantics
            and
            kind == "stated_position"
            and derive_stated_position_type(exact_quote) is None
        ):
            errors.append(
                error(
                    "STATED_POSITION_TYPE_UNSUPPORTED",
                    f"{path}/exact_quote",
                    "quoted content is not a bounded current decision, boundary, role statement, or commitment",
                )
            )
        if (
            not legacy_semantics
            and
            kind == "stated_position"
            and span.get("quoted") is True
            and _direct_quote_has_past_scope(input_text, span)
        ):
            errors.append(
                error(
                    "STATED_POSITION_NOT_CURRENT",
                    f"{path}/exact_quote",
                    "a past-scoped quotation cannot be represented as the speaker's current position",
                )
            )
        if status == "verified":
            errors.append(
                error(
                    "CONCLUSION_EXCEEDS_EVIDENCE",
                    f"{path}/epistemic_status",
                    "this runtime cannot derive verified status from user-supplied material alone",
                )
            )
        if kind in {"motive_inference", "identity_claim", "prediction"} and status in {
            "verified",
            "strongly_supported",
        }:
            errors.append(
                error(
                    "CONCLUSION_EXCEEDS_EVIDENCE",
                    f"{path}/epistemic_status",
                    "motive, identity, and future claims cannot be marked certain here",
                )
            )
        if kind == "interpretation" and status == "verified":
            errors.append(
                error(
                    "CONCLUSION_EXCEEDS_EVIDENCE",
                    f"{path}/epistemic_status",
                    "an interpretation may be supported but cannot be relabeled as a directly verified fact",
                )
            )
        if kind == "identity_claim" and boundary is not True:
            errors.append(
                error(
                    "DIAGNOSTIC_BOUNDARY_REQUIRED",
                    f"{path}/diagnostic_boundary",
                    "identity or diagnosis claims must retain an explicit diagnostic boundary",
                )
            )
        if kind == "observable_fact" and source_type not in {
            "user_direct_observation",
            "unverified_artifact",
        }:
            errors.append(
                error(
                    "FACT_SOURCE_NOT_OBSERVABLE",
                    f"{path}/source_type",
                    "observable_fact requires a direct observation or bounded artifact source",
                )
            )
        if kind == "observable_fact" and legacy_semantics:
            if (
                USER_STORY_CONTENT_PATTERN.search(exact_quote)
                or ATOMIC_INFERENCE_CONNECTOR_PATTERN.search(exact_quote)
                or NON_OBSERVATIONAL_PREDICATE_PATTERN.search(exact_quote)
            ):
                errors.append(
                    error(
                        "LEGACY_FACT_STORY_LEAK",
                        f"{path}/kind",
                        "a legacy fact anchor still cannot contain story, motive, identity, or future language",
                    )
                )
        elif kind == "observable_fact":
            if observation_type not in OBSERVATION_TYPES:
                errors.append(
                    error(
                        "OBSERVATION_TYPE_REQUIRED",
                        f"{path}/observation_type",
                        "observable_fact must use the finite observation type catalog",
                    )
                )
            semantic_observation_text = _semantic_text_for_span(
                input_text, span, exact_quote
            )
            if _has_unconsumed_decisive_observation_correction(
                input_text, span
            ):
                errors.append(
                    error(
                        "OBSERVATION_CORRECTION_UNCONSUMED",
                        f"{path}/exact_quote",
                        "a same-sentence correction reclassifies this apparent observation",
                    )
                )
            derived_observation_type = (
                None
                if span.get("quoted") is True
                or _span_contains_reported_quote(input_text, span)
                else derive_observation_type(semantic_observation_text, span)
            )
            has_non_observational_predicate = bool(
                NON_OBSERVATIONAL_PREDICATE_PATTERN.search(exact_quote)
            )
            if derived_observation_type is None or has_non_observational_predicate:
                errors.append(
                    error(
                        "FACT_TYPE_UNSUPPORTED",
                        f"{path}/exact_quote",
                        "the full atomic span is not a supported observation and may contain a story conclusion",
                    )
                )
                if (
                    STORY_MARKERS.search(exact_quote)
                    or ATOMIC_INFERENCE_CONNECTOR_PATTERN.search(exact_quote)
                    or has_non_observational_predicate
                ):
                    errors.append(
                        error(
                            "CLAIM_KIND_MISMATCH",
                            f"{path}/kind",
                            "story, motive, identity, or future language cannot enter observable_fact",
                        )
                    )
            elif observation_type in OBSERVATION_TYPES and observation_type != derived_observation_type:
                errors.append(
                    error(
                        "OBSERVATION_TYPE_MISMATCH",
                        f"{path}/observation_type",
                        f"expected {derived_observation_type} for this atomic source span",
                    )
                )
        elif observation_type is not None:
            errors.append(
                error(
                    "OBSERVATION_TYPE_FOR_FACT_ONLY",
                    f"{path}/observation_type",
                    "observation_type is only valid for observable_fact claims",
                )
            )
        if (
            not legacy_semantics
            and kind == "explicit_feeling"
            and not _is_current_user_explicit_feeling(
            exact_quote, span, input_text
            )
        ):
            errors.append(
                error(
                    "CLAIM_KIND_MISMATCH",
                    f"{path}/kind",
                    "explicit_feeling requires the current user's own asserted feeling or bodily experience",
                )
            )
    return claims


def _validate_evidence(
    errors: list[dict[str, str]],
    data: dict[str, Any],
    inputs: dict[str, dict[str, Any]],
    source_spans: dict[str, dict[str, Any]],
    proposition_ids: set[str],
    *,
    previous: dict[str, Any] | None = None,
    validation_profile: str | None = None,
) -> dict[str, dict[str, Any]]:
    evidence = _index_by_id(errors, data.get("evidence"), "/evidence")
    previous_evidence = {
        item.get("id"): item
        for item in (
            previous.get("evidence", [])
            if isinstance(previous, dict)
            and isinstance(previous.get("evidence"), list)
            else []
        )
        if isinstance(item, dict)
    }
    legacy_root = previous is None and validation_profile not in {None, "current"}
    legacy_evidence_ids = _legacy_epoch_ids(data, "evidence_ids")
    for position, item in enumerate(data.get("evidence", []) if isinstance(data.get("evidence"), list) else []):
        path = f"/evidence/{position}"
        if not isinstance(item, dict):
            continue
        _add_unknown_keys(errors, item, EVIDENCE_KEYS, path)
        for key in ("id", "input_id", "source_span_id", "source_ref", "exact_quote"):
            _require_string(errors, item, key, path)
        source_type = item.get("source_type")
        if source_type not in SOURCE_TYPES:
            errors.append(error("ENUM_ERROR", f"{path}/source_type", "unsupported source type"))
        _validate_anchor(errors, item, path, inputs, source_spans)
        exact_quote = item.get("exact_quote") if isinstance(item.get("exact_quote"), str) else ""
        input_text = _input_text(inputs, item.get("input_id")) or ""
        if source_type in {"verified_artifact", "external_verified"}:
            errors.append(
                error(
                    "SOURCE_ATTESTATION_UNSUPPORTED",
                    f"{path}/source_type",
                    "this local runtime cannot attest verified sources from a self-declared label",
                )
            )
        span = source_spans.get(item.get("source_span_id"), {})
        inherited_legacy_evidence = bool(
            item.get("id") in legacy_evidence_ids
            and previous_evidence.get(item.get("id")) == item
        )
        legacy_semantics = legacy_root or inherited_legacy_evidence
        expected_evidence_claim_kind = (
            None
            if legacy_semantics
            else derive_claim_kind_for_span(exact_quote, span, input_text)
        )
        if source_type == "direct_quote" and span.get("quoted") is not True:
            errors.append(
                error(
                    "DIRECT_QUOTE_NOT_BOUNDED",
                    f"{path}/exact_quote",
                    "direct_quote must be inside the actual quotation span that contains this anchor",
                )
            )
            errors.append(
                error(
                    "SOURCE_TYPE_MISMATCH",
                    f"{path}/source_type",
                    "direct_quote requires an anchor inside a visible quotation span",
                )
            )
        elif source_type == "direct_quote" and not legacy_semantics:
            quote_scope_error = _direct_quote_scope_error(
                input_text,
                span,
                allow_past_attribution=(
                    expected_evidence_claim_kind == "attributed_statement"
                ),
            )
            if quote_scope_error is not None:
                code, message = quote_scope_error
                errors.append(error(code, f"{path}/exact_quote", message))
        if (
            expected_evidence_claim_kind is None
            and span.get("quoted") is not True
            and derive_observation_type(
                _semantic_text_for_span(input_text, span, exact_quote), span
            )
            is not None
        ):
            expected_evidence_claim_kind = "observable_fact"
        expected_source_type = (
            None
            if legacy_semantics
            else _expected_source_type_for_claim_span(
                span, expected_evidence_claim_kind
            )
        )
        if expected_source_type and source_type != expected_source_type:
            errors.append(
                error(
                    "SOURCE_TYPE_MISMATCH",
                    f"{path}/source_type",
                    f"source context requires {expected_source_type}",
                )
            )
        for field in ("can_establish", "cannot_establish"):
            refs = item.get(field)
            _check_string_list(errors, refs, f"{path}/{field}", unique=True)
            if isinstance(refs, list):
                for index, ref in enumerate(refs):
                    if isinstance(ref, str) and ref not in proposition_ids:
                        errors.append(
                            error(
                                "REFERENCE_NOT_FOUND",
                                f"{path}/{field}/{index}",
                                f"unknown claim id {ref}",
                            )
                        )
        limitations = item.get("limitations")
        _check_string_list(
            errors,
            limitations,
            f"{path}/limitations",
            nonempty=True,
            unique=True,
        )
        if isinstance(limitations, list):
            for index, limitation in enumerate(limitations):
                if limitation not in LIMITATION_CODES:
                    errors.append(
                        error(
                            "ENUM_ERROR",
                            f"{path}/limitations/{index}",
                            "unsupported evidence limitation code",
                        )
                    )
            if source_type == "secondhand" and "secondhand" not in limitations:
                errors.append(
                    error(
                        "SECONDHAND_LIMITATION_REQUIRED",
                        f"{path}/limitations",
                        "secondhand evidence must preserve the secondhand limitation",
                    )
                )
            if (
                source_type == "unverified_artifact"
                and "artifact_not_verified" not in limitations
            ):
                errors.append(
                    error(
                        "ARTIFACT_LIMITATION_REQUIRED",
                        f"{path}/limitations",
                        "unverified artifact evidence must state that the artifact has not been verified",
                    )
                )
    return evidence


def _validate_unknowns(
    errors: list[dict[str, str]], data: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    unknowns = _index_by_id(errors, data.get("unknowns"), "/unknowns")
    for position, item in enumerate(data.get("unknowns", []) if isinstance(data.get("unknowns"), list) else []):
        path = f"/unknowns/{position}"
        if not isinstance(item, dict):
            continue
        _add_unknown_keys(errors, item, UNKNOWN_KEYS, path)
        _require_string(errors, item, "id", path)
        unknown_type = _require_string(errors, item, "unknown_type", path)
        unknown_text = _require_string(errors, item, "text", path)
        canonical_text = UNKNOWN_CATALOG.get(unknown_type or "")
        if canonical_text is None:
            errors.append(
                error(
                    "UNKNOWN_TYPE_REQUIRED",
                    f"{path}/unknown_type",
                    "unknown_type must come from the finite uncertainty catalog",
                )
            )
        elif unknown_text != canonical_text:
            errors.append(
                error(
                    "UNKNOWN_TEXT_NOT_CANONICAL",
                    f"{path}/text",
                    "unknown text is derived from unknown_type and cannot be freely written",
                )
            )
        status = _require_string(errors, item, "status", path)
        if status != "open":
            errors.append(
                error(
                    "UNKNOWN_RESOLUTION_UNSUPPORTED",
                    f"{path}/status",
                    "version 2 preserves unknowns as open instead of auto-claiming resolution",
                )
            )
        refs = _require_list(errors, item, "resolved_by_evidence_refs", path)
        if isinstance(refs, list) and any(not isinstance(ref, str) for ref in refs):
            errors.append(error("TYPE_ERROR", f"{path}/resolved_by_evidence_refs", "must be an array of ids"))
        elif isinstance(refs, list) and refs:
            errors.append(
                error(
                    "UNKNOWN_RESOLUTION_UNSUPPORTED",
                    f"{path}/resolved_by_evidence_refs",
                    "open unknowns cannot contain resolution references",
                )
            )
    return unknowns


def _validate_hypotheses(
    errors: list[dict[str, str]], data: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    hypotheses = _index_by_id(errors, data.get("hypotheses"), "/hypotheses")
    values = data.get("hypotheses")
    if isinstance(values, list) and len(values) > 2:
        errors.append(error("TOO_MANY_HYPOTHESES", "/hypotheses", "at most two working hypotheses are allowed"))
    for position, item in enumerate(values if isinstance(values, list) else []):
        path = f"/hypotheses/{position}"
        if not isinstance(item, dict):
            continue
        _add_unknown_keys(errors, item, HYPOTHESIS_KEYS, path)
        for key in ("id", "hypothesis_type", "text", "exit_condition"):
            _require_string(errors, item, key, path)
        hypothesis_type = item.get("hypothesis_type")
        canonical_text = HYPOTHESIS_CATALOG.get(hypothesis_type)
        if canonical_text is None:
            errors.append(
                error(
                    "HYPOTHESIS_TYPE_REQUIRED",
                    f"{path}/hypothesis_type",
                    "hypothesis_type must come from the bounded non-diagnostic catalog",
                )
            )
        elif item.get("text") != canonical_text:
            errors.append(
                error(
                    "HYPOTHESIS_TEXT_NOT_CANONICAL",
                    f"{path}/text",
                    "hypothesis text is derived from hypothesis_type",
                )
            )
        if item.get("confidence") not in {"low", "medium"}:
            errors.append(error("ENUM_ERROR", f"{path}/confidence", "must be low or medium"))
        support = item.get("support_signals")
        weakening = item.get("weakening_signals")
        _check_string_list(errors, support, f"{path}/support_signals", nonempty=True)
        _check_string_list(errors, weakening, f"{path}/weakening_signals", nonempty=True)
        for field, signals in (("support_signals", support), ("weakening_signals", weakening)):
            if isinstance(signals, list):
                for signal_index, signal in enumerate(signals):
                    if signal not in HYPOTHESIS_SIGNAL_TEXT:
                        errors.append(
                            error(
                                "HYPOTHESIS_SIGNAL_INVALID",
                                f"{path}/{field}/{signal_index}",
                                "signal must come from the observable signal catalog",
                            )
                        )
        if isinstance(support, list) and isinstance(weakening, list) and set(support) & set(weakening):
            errors.append(
                error(
                    "HYPOTHESIS_SIGNALS_OVERLAP",
                    path,
                    "a signal cannot both support and weaken the same hypothesis",
                )
            )
        exit_condition = item.get("exit_condition")
        if exit_condition not in HYPOTHESIS_SIGNAL_TEXT:
            errors.append(
                error(
                    "HYPOTHESIS_SIGNAL_INVALID",
                    f"{path}/exit_condition",
                    "exit condition must be an observable signal type",
                )
            )
        elif isinstance(weakening, list) and exit_condition not in weakening:
            errors.append(
                error(
                    "HYPOTHESIS_EXIT_NOT_WEAKENING",
                    f"{path}/exit_condition",
                    "exit condition must be one of this hypothesis's weakening signals",
                )
            )
        if not support or not weakening:
            errors.append(
                error(
                    "HYPOTHESIS_NOT_FALSIFIABLE",
                    path,
                    "a working hypothesis needs both supporting and weakening signals",
                )
            )
    return hypotheses


def _validate_hypothesis_request(
    errors: list[dict[str, str]],
    data: dict[str, Any],
    inputs: dict[str, dict[str, Any]],
    source_spans: dict[str, dict[str, Any]],
    hypotheses: dict[str, dict[str, Any]],
) -> None:
    request = data.get("hypothesis_request")
    if not hypotheses:
        if request is not None:
            errors.append(
                error(
                    "UNUSED_HYPOTHESIS_REQUEST",
                    "/hypothesis_request",
                    "remove the request object when no hypotheses are generated",
                )
            )
        return
    if not isinstance(request, dict):
        errors.append(
            error(
                "HYPOTHESIS_NOT_REQUESTED",
                "/hypothesis_request",
                "hypotheses require an anchored, explicit user request",
            )
        )
        return
    _add_unknown_keys(errors, request, HYPOTHESIS_REQUEST_KEYS, "/hypothesis_request")
    _require_string(errors, request, "input_id", "/hypothesis_request")
    _require_string(errors, request, "source_span_id", "/hypothesis_request")
    quote = _require_string(errors, request, "exact_quote", "/hypothesis_request")
    _validate_anchor(errors, request, "/hypothesis_request", inputs, source_spans)
    count = request.get("requested_count")
    if not isinstance(count, int) or isinstance(count, bool) or count not in {1, 2}:
        errors.append(
            error(
                "HYPOTHESIS_REQUEST_COUNT_INVALID",
                "/hypothesis_request/requested_count",
                "requested_count must be 1 or 2",
            )
        )
    elif count != len(hypotheses):
        errors.append(
            error(
                "HYPOTHESIS_REQUEST_COUNT_INVALID",
                "/hypothesis_request/requested_count",
                "requested_count must equal the number of hypotheses",
            )
        )
    if quote:
        span = source_spans.get(request.get("source_span_id"), {})
        request_context = str(span.get("text", quote))
        stated_counts: set[int] = set()
        if re.search(r"(?:一个|1\s*个|一条|1\s*条|一个待核对)", request_context):
            stated_counts.add(1)
        if re.search(r"(?:两个|2\s*个|两个待核对|两条|2\s*条)", request_context):
            stated_counts.add(2)
        if len(stated_counts) == 1 and count not in stated_counts:
            errors.append(
                error(
                    "HYPOTHESIS_REQUEST_COUNT_MISMATCH",
                    "/hypothesis_request/requested_count",
                    "requested_count must match the number explicitly requested in the anchored source span",
                )
            )
        elif len(stated_counts) > 1:
            errors.append(
                error(
                    "HYPOTHESIS_REQUEST_COUNT_MISMATCH",
                    "/hypothesis_request/exact_quote",
                    "the anchored request contains conflicting explicit counts",
                )
            )
        positive_topic = re.search(r"假设|解释|可能性|候选|命题", request_context)
        positive_request = re.search(
            r"请|给|列|比较|区分|待核对|我要|"
            r"要(?:给|列|比较|区分|一个|两个|一条|两条)",
            request_context,
        )
        negative_request = re.search(
            r"不要.{0,20}(假设|解释|可能性|候选|命题|故事)|"
            r"别.{0,20}(假设|解释|可能性|候选|命题|故事)|"
            r"不需要.{0,20}(假设|解释|可能性|候选|命题)|"
            r"(?:不必|用不着|没必要|不考虑).{0,20}(假设|解释|可能性|候选|命题|故事)|"
            r"(?:不许|禁止|拒绝|无需).{0,20}(假设|解释|可能性|候选|命题|故事)|"
            r"(?:没|没有|未|并未)(?:让|要|要求|请|叫).{0,20}(假设|解释|可能性|候选|命题|故事)|"
            r"不是要.{0,20}(假设|解释|可能性|候选|命题|故事)|"
            r"不是.{0,8}(?:让|叫|要).{0,8}(?:你)?(?:给|列|提).{0,8}(假设|解释|可能性|候选|命题|故事)|"
            r"(?:不包含|不带|去掉|删掉|排除).{0,12}(假设|解释|可能性|候选|命题|故事)|"
            r"(?:假设|解释|可能性|候选|命题|故事).{0,8}(?:是)?(?:不可以|不行|不允许|禁止|拒绝)|"
            r"(?:假设|解释|可能性|候选|命题|故事).{0,12}(?:并)?不是.{0,12}(?:我)?(?:所)?(?:要|需要|想要)|"
            r"(?:假设|解释|可能性|候选|命题|故事).{0,12}(?:一个也|一条也|一个都|一条都)?.{0,6}(?:别给|不要给|不用给|无需给|拒绝给)|"
            r"(?:别给|不要给|不用给|无需给|拒绝给).{0,12}(?:假设|解释|可能性|候选|命题|故事)",
            request_context,
        )
        if not positive_topic or not positive_request or negative_request:
            errors.append(
                error(
                    "HYPOTHESIS_NOT_REQUESTED",
                    "/hypothesis_request/exact_quote",
                    "anchor must be a positive user request for hypotheses or alternatives",
                )
            )


def _validate_evidence_links(
    errors: list[dict[str, str]],
    data: dict[str, Any],
    claims: dict[str, dict[str, Any]],
    hypotheses: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
    source_spans: dict[str, dict[str, Any]],
    previous: dict[str, Any] | None,
) -> None:
    links = data.get("evidence_links")
    if not isinstance(links, list):
        errors.append(error("REQUIRED_ARRAY", "/evidence_links", "must be an array"))
        return
    proposition_ids = set(claims) | set(hypotheses)
    evidence_ids = set(evidence)
    seen: set[tuple[str, str]] = set()
    links_by_proposition: dict[str, list[dict[str, Any]]] = {}
    links_by_evidence: dict[str, list[dict[str, Any]]] = {}
    evidence_context_by_source: dict[tuple[str, str], str] = {}
    evidence_context_parts: dict[tuple[str, str], list[str]] = {}
    for evidence_item in evidence.values():
        context_key = (
            str(evidence_item.get("input_id", "")),
            str(evidence_item.get("source_ref", "")),
        )
        quote = evidence_item.get("exact_quote")
        if isinstance(quote, str) and quote:
            evidence_context_parts.setdefault(context_key, []).append(quote)
    evidence_context_by_source = {
        key: "\n".join(parts) for key, parts in evidence_context_parts.items()
    }
    previous_evidence = {
        item.get("id"): item
        for item in (
            previous.get("evidence", [])
            if isinstance(previous, dict)
            and isinstance(previous.get("evidence"), list)
            else []
        )
        if isinstance(item, dict)
    }
    legacy_evidence_ids = _legacy_epoch_ids(data, "evidence_ids")

    def strict_role_relation_for(evidence_item: dict[str, Any]) -> bool:
        inherited_legacy = bool(
            evidence_item.get("id") in legacy_evidence_ids
            and previous_evidence.get(evidence_item.get("id")) == evidence_item
        )
        return (
            _casefile_version_pair(data) == CURRENT_VERSION_PAIR
            and not inherited_legacy
        )
    superseded_claim_ids = {
        item.get("target_id")
        for item in data.get("change_log", [])
        if isinstance(item, dict)
        and item.get("to_status") == "superseded"
        and isinstance(item.get("superseded_by_claim_id"), str)
    }
    superseded_claim_ids.update(
        item.get("id")
        for item in (previous or {}).get("claims", [])
        if isinstance(item, dict)
        and item.get("epistemic_status") == "superseded"
    )
    retracted_claim_ids = {
        item.get("target_id")
        for item in data.get("change_log", [])
        if isinstance(item, dict)
        and item.get("to_status") == "retracted"
    }
    retracted_claim_ids.update(
        item.get("id")
        for item in (previous or {}).get("claims", [])
        if isinstance(item, dict)
        and item.get("epistemic_status") == "retracted"
    )
    for position, item in enumerate(links):
        path = f"/evidence_links/{position}"
        if not isinstance(item, dict):
            errors.append(error("TYPE_ERROR", path, "must be an object"))
            continue
        _add_unknown_keys(errors, item, EVIDENCE_LINK_KEYS, path)
        proposition_id = _require_string(errors, item, "proposition_id", path)
        evidence_ref = _require_string(errors, item, "evidence_ref", path)
        relation = item.get("relation")
        strength = item.get("strength")
        reason = _require_string(errors, item, "reason", path)
        if proposition_id and proposition_id not in proposition_ids:
            errors.append(error("REFERENCE_NOT_FOUND", f"{path}/proposition_id", f"unknown proposition {proposition_id}"))
        if evidence_ref and evidence_ref not in evidence_ids:
            errors.append(error("REFERENCE_NOT_FOUND", f"{path}/evidence_ref", f"unknown evidence {evidence_ref}"))
        if relation not in RELATIONS:
            errors.append(error("ENUM_ERROR", f"{path}/relation", "unsupported evidence relation"))
        if strength not in STRENGTHS:
            errors.append(error("ENUM_ERROR", f"{path}/strength", "unsupported evidence strength"))
        if reason and reason not in REASON_CODES:
            errors.append(error("ENUM_ERROR", f"{path}/reason", "unsupported evidence reason code"))
        if proposition_id and evidence_ref and relation:
            signature = (proposition_id, evidence_ref)
            if signature in seen:
                errors.append(error("DUPLICATE_LINK_TARGET", path, "one evidence-target pair may have only one relation"))
                continue
            seen.add(signature)
            links_by_proposition.setdefault(proposition_id, []).append(item)
            links_by_evidence.setdefault(evidence_ref, []).append(item)
            claim = claims.get(proposition_id)
            hypothesis = hypotheses.get(proposition_id)
            evidence_item = evidence.get(evidence_ref)
            if claim is not None and evidence_item is not None and relation in RELATIONS:
                if (
                    claim.get("source_span_id")
                    == evidence_item.get("source_span_id")
                    and claim.get("input_id") == evidence_item.get("input_id")
                    and claim.get("exact_quote") == evidence_item.get("exact_quote")
                    and claim.get("source_type") != evidence_item.get("source_type")
                ):
                    errors.append(
                        error(
                            "CLAIM_EVIDENCE_SOURCE_MISMATCH",
                            f"{path}/evidence_ref",
                            "a same-anchor claim and evidence object must preserve the same source type",
                        )
                    )
                scoped_evidence = dict(evidence_item)
                evidence_span = source_spans.get(
                    evidence_item.get("source_span_id"), {}
                )
                scoped_evidence["source_label"] = evidence_span.get(
                    "source_label", ""
                )
                scoped_evidence["source_context"] = evidence_context_by_source.get(
                    (
                        str(evidence_item.get("input_id", "")),
                        str(evidence_item.get("source_ref", "")),
                    ),
                    "",
                )
                scoped_evidence["strict_role_relation"] = (
                    strict_role_relation_for(evidence_item)
                )
                allowed_relations = _allowed_relation_for_claim_evidence(
                    claim, scoped_evidence
                )
                if relation not in allowed_relations:
                    errors.append(
                        error(
                            "RELATION_SEMANTICALLY_UNSUPPORTED",
                            f"{path}/relation",
                            f"this runtime only permits {sorted(allowed_relations)} for the anchored claim and evidence",
                        )
                    )
                expected_strength = _expected_link_strength(claim, evidence_item, relation)
                if strength != expected_strength:
                    errors.append(
                        error(
                            "LINK_STRENGTH_NOT_DERIVED",
                            f"{path}/strength",
                            f"expected {expected_strength} for this anchored relation",
                        )
                    )
            elif hypothesis is not None and evidence_item is not None and relation in RELATIONS:
                scoped_evidence = dict(evidence_item)
                evidence_span = source_spans.get(evidence_item.get("source_span_id"), {})
                scoped_evidence["source_label"] = evidence_span.get(
                    "source_label", ""
                )
                scoped_evidence["source_context"] = evidence_context_by_source.get(
                    (
                        str(evidence_item.get("input_id", "")),
                        str(evidence_item.get("source_ref", "")),
                    ),
                    "",
                )
                scoped_evidence["strict_role_relation"] = (
                    strict_role_relation_for(evidence_item)
                )
                allowed_relations = _allowed_relation_for_hypothesis_evidence(
                    hypothesis, scoped_evidence
                )
                if relation not in allowed_relations:
                    errors.append(
                        error(
                            "RELATION_SEMANTICALLY_UNSUPPORTED",
                            f"{path}/relation",
                            f"this bounded hypothesis permits only {sorted(allowed_relations)} for this evidence span",
                        )
                    )
                expected_strength = "none" if relation == "does_not_establish" else "weak"
                if strength != expected_strength:
                    errors.append(
                        error(
                            "LINK_STRENGTH_NOT_DERIVED",
                            f"{path}/strength",
                            f"expected {expected_strength} for a working-hypothesis relation",
                        )
                    )

    for claim_id, claim in claims.items():
        claim_links = links_by_proposition.get(claim_id, [])
        if not claim_links:
            errors.append(
                error(
                    "CLAIM_EVIDENCE_REQUIRED",
                    f"/claims/{claim_id}",
                    "every claim requires at least one scoped evidence relation",
                )
            )
            continue
        expected_status = _derived_claim_status(
            claim,
            claim_links,
            superseded_claim_ids,
            retracted_claim_ids,
        )
        if claim.get("epistemic_status") != expected_status:
            errors.append(
                error(
                    "STATUS_NOT_DERIVED",
                    f"/claims/{claim_id}/epistemic_status",
                    f"expected {expected_status} from claim kind and evidence relations",
                )
            )
        if claim.get("kind") in (
            {"observable_fact", "explicit_feeling"} | DIRECTLY_ATTRIBUTED_KINDS
        ) and not any(
            link.get("relation") == "supports" and link.get("strength") == "direct"
            for link in claim_links
        ):
            errors.append(
                error(
                    "FACT_SUPPORT_REQUIRED",
                    f"/claims/{claim_id}",
                    "fact, feeling, and directly attributed layers require a direct same-span supports link",
                )
            )

    for evidence_id, evidence_item in evidence.items():
        evidence_links = links_by_evidence.get(evidence_id, [])
        if not evidence_links:
            errors.append(
                error(
                    "EVIDENCE_LINK_REQUIRED",
                    f"/evidence/{evidence_id}",
                    "every evidence object must be connected to at least one claim",
                )
            )
            continue
        relation_by_target = {
            link.get("proposition_id"): link.get("relation") for link in evidence_links
        }
        can_establish = set(evidence_item.get("can_establish", []))
        cannot_establish = set(evidence_item.get("cannot_establish", []))
        for target, relation in relation_by_target.items():
            if relation == "supports" and target not in can_establish:
                errors.append(
                    error(
                        "EVIDENCE_LINK_SCOPE_UNDECLARED",
                        f"/evidence/{evidence_id}/can_establish",
                        f"supports link to {target} must be declared in can_establish",
                    )
                )
            if relation in {"conflicts", "does_not_establish"} and target not in cannot_establish:
                errors.append(
                    error(
                        "EVIDENCE_LINK_SCOPE_UNDECLARED",
                        f"/evidence/{evidence_id}/cannot_establish",
                        f"{relation} link to {target} must be declared in cannot_establish",
                    )
                )
        for target in evidence_item.get("can_establish", []):
            if relation_by_target.get(target) != "supports":
                errors.append(
                    error(
                        "EVIDENCE_SCOPE_LINK_MISMATCH",
                        f"/evidence/{evidence_id}/can_establish",
                        f"{target} must have a supports link from this evidence",
                    )
                )
        for target in evidence_item.get("cannot_establish", []):
            if relation_by_target.get(target) not in {"does_not_establish", "conflicts"}:
                errors.append(
                    error(
                        "EVIDENCE_SCOPE_LINK_MISMATCH",
                        f"/evidence/{evidence_id}/cannot_establish",
                        f"{target} must have a does_not_establish or conflicts link",
                    )
                )


def _validate_discriminator(
    errors: list[dict[str, str]],
    data: dict[str, Any],
    target_ids: set[str],
    hypotheses: dict[str, dict[str, Any]],
) -> None:
    item = data.get("discriminator")
    if item is None:
        return
    path = "/discriminator"
    if not isinstance(item, dict):
        errors.append(error("TYPE_ERROR", path, "must be an object or null"))
        return
    _add_unknown_keys(errors, item, DISCRIMINATOR_KEYS, path)
    question = _require_string(errors, item, "question", path)
    question_type = _require_string(errors, item, "question_type", path)
    canonical_question = DISCRIMINATOR_QUESTION_TYPES.get(question_type or "")
    if canonical_question is None:
        errors.append(
            error(
                "DISCRIMINATOR_TYPE_REQUIRED",
                f"{path}/question_type",
                "question_type must be selected from the finite low-risk catalog",
            )
        )
    elif question != canonical_question:
        errors.append(
            error(
                "DISCRIMINATOR_QUESTION_NOT_CANONICAL",
                f"{path}/question",
                "question text is derived from question_type and cannot be freely rewritten",
            )
        )
    distinguishes = item.get("distinguishes")
    if not isinstance(distinguishes, list) or len(distinguishes) < 2 or any(not isinstance(value, str) for value in distinguishes):
        errors.append(error("DISCRIMINATOR_TARGETS_INVALID", f"{path}/distinguishes", "must reference at least two targets"))
        distinguishes = []
    elif len(set(distinguishes)) != len(distinguishes):
        errors.append(error("DISCRIMINATOR_TARGETS_INVALID", f"{path}/distinguishes", "targets must be unique"))
    for target in distinguishes:
        if target not in target_ids:
            errors.append(error("REFERENCE_NOT_FOUND", f"{path}/distinguishes", f"unknown target {target}"))
    if question is not None and question.count("?") + question.count("？") != 1:
        errors.append(error("DISCRIMINATOR_NOT_SINGLE", f"{path}/question", "must contain exactly one question"))
    if item.get("risk") != "low" or item.get("reversible") is not True:
        errors.append(error("DISCRIMINATOR_NOT_LOW_RISK", path, "must be low risk and reversible"))
    branches = item.get("branches")
    if not isinstance(branches, list) or len(branches) < 2:
        errors.append(error("DISCRIMINATOR_BRANCHES_MISSING", f"{path}/branches", "at least two observable answer branches are required"))
        return
    answer_types: list[str] = []
    effect_signatures: list[tuple[tuple[str, str], ...]] = []
    for position, branch in enumerate(branches):
        branch_path = f"{path}/branches/{position}"
        if not isinstance(branch, dict):
            errors.append(error("TYPE_ERROR", branch_path, "must be an object"))
            continue
        _add_unknown_keys(errors, branch, BRANCH_KEYS, branch_path)
        answer_type = _require_string(errors, branch, "answer_type", branch_path)
        observable_answer = _require_string(errors, branch, "observable_answer", branch_path)
        canonical_answer = HYPOTHESIS_SIGNAL_TEXT.get(answer_type or "")
        if canonical_answer is None:
            errors.append(error("DISCRIMINATOR_ANSWER_TYPE_INVALID", f"{branch_path}/answer_type", "must use an observable signal type"))
        elif observable_answer != canonical_answer:
            errors.append(error("DISCRIMINATOR_ANSWER_NOT_CANONICAL", f"{branch_path}/observable_answer", "answer text is derived from answer_type"))
        if answer_type:
            answer_types.append(answer_type)
        updates = branch.get("updates")
        if not isinstance(updates, list) or not updates:
            errors.append(error("EMPTY_ARRAY", f"{branch_path}/updates", "must update at least one target"))
            continue
        updated_targets: list[str] = []
        effects_for_branch: list[tuple[str, str]] = []
        for update_index, update in enumerate(updates):
            update_path = f"{branch_path}/updates/{update_index}"
            if not isinstance(update, dict):
                errors.append(error("TYPE_ERROR", update_path, "must be an object"))
                continue
            _add_unknown_keys(errors, update, UPDATE_KEYS, update_path)
            target = _require_string(errors, update, "target_id", update_path)
            if target and target not in distinguishes:
                errors.append(error("REFERENCE_NOT_FOUND", f"{update_path}/target_id", "target must be listed in distinguishes"))
            if update.get("effect") not in EFFECTS:
                errors.append(error("ENUM_ERROR", f"{update_path}/effect", "unsupported update effect"))
            if target:
                updated_targets.append(target)
                effects_for_branch.append((target, str(update.get("effect"))))
        if len(updated_targets) != len(set(updated_targets)):
            errors.append(error("DISCRIMINATOR_UPDATE_DUPLICATE", f"{branch_path}/updates", "each target may be updated once per branch"))
        if distinguishes:
            missing = set(distinguishes) - set(updated_targets)
            if missing:
                errors.append(
                    error(
                        "HYPOTHESIS_BRANCH_INCOMPLETE",
                        f"{branch_path}/updates",
                        "each observable branch must update every compared hypothesis",
                    )
                )
        effect_signatures.append(tuple(sorted(effects_for_branch)))
        effects_by_target = dict(effects_for_branch)
        if answer_type in HYPOTHESIS_SIGNAL_TEXT:
            for hypothesis_id, hypothesis in hypotheses.items():
                if hypothesis_id not in distinguishes:
                    continue
                if answer_type in hypothesis.get("support_signals", []):
                    expected_effect = "strengthens"
                elif answer_type in hypothesis.get("weakening_signals", []):
                    expected_effect = "weakens"
                else:
                    expected_effect = "keeps_unknown"
                if effects_by_target.get(hypothesis_id) != expected_effect:
                    errors.append(
                        error(
                            "DISCRIMINATOR_EFFECT_CONTRADICTS_HYPOTHESIS",
                            f"{branch_path}/updates",
                            f"{answer_type} must {expected_effect} {hypothesis_id}",
                        )
                    )
    if len(answer_types) != len(set(answer_types)) or len(set(effect_signatures)) < 2:
        errors.append(
            error(
                "DISCRIMINATOR_BRANCHES_NOT_DISTINCT",
                f"{path}/branches",
                "branches need unique observable answers and different update effects",
            )
        )


def _validate_actions(errors: list[dict[str, str]], data: dict[str, Any]) -> None:
    actions = data.get("actions")
    if not isinstance(actions, list):
        errors.append(error("REQUIRED_ARRAY", "/actions", "must be an array"))
        return
    mode = data.get("mode")
    if mode in {"standard", "safety"} and not actions:
        errors.append(error("ACTION_REQUIRED", "/actions", "this mode requires at least one action"))
    seen: set[str] = set()
    for position, item in enumerate(actions):
        path = f"/actions/{position}"
        if not isinstance(item, dict):
            errors.append(error("TYPE_ERROR", path, "must be an object"))
            continue
        _add_unknown_keys(errors, item, ACTION_KEYS, path)
        action_id = _require_string(errors, item, "id", path)
        action_type = _require_string(errors, item, "action_type", path)
        _require_string(errors, item, "text", path)
        _require_bool(errors, item, "reversible", path)
        _require_bool(errors, item, "motive_independent", path)
        _require_bool(errors, item, "produces_new_evidence", path)
        if action_id:
            if action_id in seen:
                errors.append(error("DUPLICATE_ID", f"{path}/id", f"duplicate id {action_id}"))
            seen.add(action_id)
        specification = ACTION_CATALOG.get(action_type or "")
        if (specification is None or item.get("text") != specification["text"]) and any(
            word in str(item.get("text", ""))
            for word in ("辞职", "分手", "报复", "大闹", "围堵", "逼", "对质", "曝光")
        ):
            errors.append(
                error(
                    "ACTION_REVERSIBILITY_FALSE",
                    f"{path}/text",
                    "free-form escalatory actions are not permitted",
                )
            )
        if specification is None:
            errors.append(
                error(
                    "ACTION_TYPE_REQUIRED",
                    f"{path}/action_type",
                    "action_type must be selected from the finite safe action catalog",
                )
            )
            continue
        if mode not in specification["modes"]:
            errors.append(
                error(
                    "SAFE_ACTION_CONSTRAINT",
                    f"{path}/action_type",
                    f"{action_type} is not permitted in {mode} mode",
                )
            )
        for key in (
            "text",
            "timing",
            "risk",
            "reversible",
            "motive_independent",
            "produces_new_evidence",
        ):
            if item.get(key) != specification[key]:
                code = "ACTION_TEXT_NOT_CANONICAL" if key == "text" else "SAFE_ACTION_CONSTRAINT"
                errors.append(
                    error(
                        code,
                        f"{path}/{key}",
                        f"field is derived from action_type and must equal {specification[key]!r}",
                    )
                )
    if mode == "safety" and (
        not actions
        or actions[0].get("timing") != "immediate"
        or actions[0].get("action_type") not in {
            "move_to_safe_place",
            "contact_emergency_services",
            "contact_trusted_person",
            "seek_medical_support",
            "seek_legal_support",
        }
    ):
        errors.append(error("SAFETY_ACTION_NOT_FIRST", "/actions/0/timing", "the first safety action must be immediate"))


def _required_safety_span_types(
    source_spans: dict[str, dict[str, Any]],
    inputs: dict[str, dict[str, Any]],
    input_id: Any,
) -> set[tuple[str, str]]:
    input_text = _input_text(inputs, input_id) or ""
    signal_types = expected_safety_signal_types(input_text)
    if not signal_types:
        return set()
    trimmed = _trim_range(input_text, 0, len(input_text))
    if trimmed is None:
        return set()
    start, end = trimmed
    context_span = next(
        (
            span
            for span in source_spans.values()
            if span.get("input_id") == input_id
            and span.get("start") == start
            and span.get("end") == end
            and span.get("quoted") is False
            and isinstance(span.get("id"), str)
        ),
        None,
    )
    if context_span is None:
        return set()
    return {(context_span["id"], signal_type) for signal_type in signal_types}


def _validate_safety(
    errors: list[dict[str, str]],
    data: dict[str, Any],
    inputs: dict[str, dict[str, Any]],
    source_spans: dict[str, dict[str, Any]],
    previous: dict[str, Any] | None,
) -> None:
    safety = data.get("safety")
    if not isinstance(safety, dict):
        errors.append(error("TYPE_ERROR", "/safety", "must be an object"))
        return
    _add_unknown_keys(errors, safety, SAFETY_KEYS, "/safety")
    signals = safety.get("risk_signals")
    if not isinstance(signals, list):
        errors.append(error("REQUIRED_ARRAY", "/safety/risk_signals", "must be an array"))
        return
    valid_signal_coverage: set[tuple[str, str]] = set()
    for position, item in enumerate(signals):
        path = f"/safety/risk_signals/{position}"
        if not isinstance(item, dict):
            errors.append(error("TYPE_ERROR", path, "must be an object"))
            continue
        _add_unknown_keys(errors, item, RISK_SIGNAL_KEYS, path)
        for key in (
            "input_id",
            "source_span_id",
            "source_ref",
            "exact_quote",
            "routing_basis",
        ):
            _require_string(errors, item, key, path)
        if item.get("signal_type") not in SIGNAL_TYPES:
            errors.append(error("ENUM_ERROR", f"{path}/signal_type", "unsupported safety signal"))
        routing_basis = item.get("routing_basis")
        if routing_basis not in SAFETY_ROUTING_BASES:
            errors.append(
                error(
                    "ENUM_ERROR",
                    f"{path}/routing_basis",
                    "unsupported safety routing basis",
                )
            )
        input_id = item.get("input_id")
        source_span_id = item.get("source_span_id")
        contextual_required = _required_safety_span_types(
            source_spans, inputs, input_id
        )
        expected_signal_types = {
            signal_type
            for span_id, signal_type in contextual_required
            if span_id == source_span_id
        }
        if (
            routing_basis == "human_semantic_review"
            and item.get("signal_type") in expected_signal_types
        ):
            errors.append(
                error(
                    "SAFETY_ROUTING_BASIS_MISMATCH",
                    f"{path}/routing_basis",
                    "a deterministic signal must use deterministic_backstop and its detected type",
                )
            )
        elif routing_basis == "human_semantic_review":
            # Human review is an explicit escape hatch for urgent semantics the
            # bounded regex backstop does not recognize. The source still has
            # to be an exact input anchor; the validator never fabricates one.
            pass
        elif not expected_signal_types:
            errors.append(
                error(
                    "SAFETY_SIGNAL_NOT_PRESENT",
                    f"{path}/exact_quote",
                    "the anchored span does not contain a deterministic immediate-risk signal",
                )
            )
        elif item.get("signal_type") not in expected_signal_types:
            errors.append(
                error(
                    "SAFETY_SIGNAL_TYPE_MISMATCH",
                    f"{path}/signal_type",
                    f"anchored text requires one of {sorted(expected_signal_types)}",
                )
            )
        elif isinstance(source_span_id, str):
            valid_signal_coverage.add(
                (source_span_id, item["signal_type"])
            )
        _validate_anchor(errors, item, path, inputs, source_spans)
    mode = data.get("mode")
    if mode == "safety":
        if not signals:
            errors.append(error("SAFETY_SIGNAL_REQUIRED", "/safety/risk_signals", "safety mode requires anchored risk signals"))
        current_input_id = data.get("current_input_id")
        current_text = _input_text(inputs, current_input_id) or ""
        required_coverage = _required_safety_span_types(
            source_spans, inputs, current_input_id
        )
        current_coverage = {
            pair
            for pair in valid_signal_coverage
            if source_spans.get(pair[0], {}).get("input_id") == current_input_id
        }
        missing_coverage = sorted(required_coverage - current_coverage)
        if missing_coverage:
            errors.append(
                error(
                    "SAFETY_SIGNAL_COVERAGE_MISSING",
                    "/safety/risk_signals",
                    f"missing current risk anchors {missing_coverage}",
                )
            )
        safety_started_for_current_input = (
            previous is None or previous.get("mode") != "safety"
        )
        if (
            (detect_immediate_risk(current_text) or safety_started_for_current_input)
            and not any(
                item.get("input_id") == current_input_id
                for item in signals
                if isinstance(item, dict)
            )
        ):
            errors.append(
                error(
                    "CURRENT_SAFETY_SIGNAL_REQUIRED",
                    "/safety/risk_signals",
                    "a current immediate-risk input requires at least one current-input signal",
                )
            )
        signal_types = {
            item.get("signal_type") for item in signals if isinstance(item, dict)
        }
        detected_signal_types = set().union(
            *(
                expected_safety_signal_types(str(item.get("text", "")))
                for item in inputs.values()
                if isinstance(item, dict)
            )
        )
        effective_signal_types = signal_types | detected_signal_types
        action_types = {
            item.get("action_type")
            for item in data.get("actions", [])
            if isinstance(item, dict)
        }
        if "medical_emergency" in effective_signal_types and "seek_medical_support" not in action_types:
            errors.append(
                error(
                    "SAFETY_SUPPORT_MISMATCH",
                    "/actions",
                    "medical emergency signals require the medical-support action",
                )
            )
        if "urgent_legal_risk" in effective_signal_types and "seek_legal_support" not in action_types:
            errors.append(
                error(
                    "SAFETY_SUPPORT_MISMATCH",
                    "/actions",
                    "urgent legal signals require the legal-support action",
                )
            )
        if "explicit_threat" in effective_signal_types and not action_types & {
            "contact_emergency_services",
            "move_to_safe_place",
        }:
            errors.append(
                error(
                    "SAFETY_SUPPORT_MISMATCH",
                    "/actions",
                    "threat or harm-to-others signals require emergency or safe-place action",
                )
            )
        if (
            "harm_to_others_risk" in effective_signal_types
            and "contact_emergency_services" not in action_types
        ):
            errors.append(
                error(
                    "SAFETY_SUPPORT_MISMATCH",
                    "/actions",
                    "harm-to-others signals require immediate emergency support",
                )
            )
        if "self_harm_risk" in effective_signal_types and not action_types & {
            "contact_emergency_services",
            "seek_medical_support",
        }:
            errors.append(
                error(
                    "SAFETY_SUPPORT_MISMATCH",
                    "/actions",
                    "self-harm signals require emergency or medical support",
                )
            )
        if (
            "third_party_self_harm_risk" in effective_signal_types
            and "contact_emergency_services" not in action_types
        ):
            errors.append(
                error(
                    "SAFETY_SUPPORT_MISMATCH",
                    "/actions",
                    "reported third-party self-harm requires immediate emergency support",
                )
            )
        if effective_signal_types & {
            "prior_violence_or_damage",
            "access_or_location_exposure",
        } and not action_types & {
            "contact_emergency_services",
            "move_to_safe_place",
        }:
            errors.append(
                error(
                    "SAFETY_SUPPORT_MISMATCH",
                    "/actions",
                    "violence history or location exposure requires emergency or safe-place action",
                )
            )
        analysis_fields = (
            "unclassified_observation_candidates",
            "candidate_resolutions",
            "claims",
            "evidence",
            "evidence_links",
            "unknowns",
            "hypotheses",
            "hypothesis_request",
            "discriminator",
        )
        if previous is None:
            for field in analysis_fields:
                empty_value = None if field in {"hypothesis_request", "discriminator"} else []
                actual_value = (
                    data.get(field, [])
                    if field == "candidate_resolutions"
                    else data.get(field)
                )
                if actual_value != empty_value:
                    errors.append(
                        error(
                            "SAFETY_ANALYSIS_NOT_ALLOWED",
                            f"/{field}",
                            "revision 1 safety mode cannot contain ordinary analysis",
                        )
                    )
        else:
            for field in analysis_fields:
                current_value = (
                    data.get(field, [])
                    if field == "candidate_resolutions"
                    else data.get(field)
                )
                previous_value = (
                    previous.get(field, [])
                    if field == "candidate_resolutions"
                    else previous.get(field)
                )
                if current_value != previous_value:
                    errors.append(
                        error(
                            "SAFETY_ANALYSIS_NOT_ALLOWED",
                            f"/{field}",
                            "safety mode may preserve prior analysis but cannot add or mutate it",
                        )
                    )
    elif signals:
        errors.append(error("SAFETY_MODE_REQUIRED", "/mode", "anchored immediate risk signals require safety mode"))


def _validate_mode_contract(errors: list[dict[str, str]], data: dict[str, Any]) -> None:
    mode = data.get("mode")
    inputs = {
        item.get("id"): item
        for item in data.get("inputs", [])
        if isinstance(item, dict)
    }
    current = inputs.get(data.get("current_input_id"), {})
    current_text = current.get("text") if isinstance(current, dict) else ""
    if isinstance(current_text, str) and detect_immediate_risk(current_text) and mode != "safety":
        errors.append(
            error(
                "SAFETY_MODE_REQUIRED",
                "/mode",
                "the current input contains a deterministic immediate-risk signal",
            )
        )
    if mode == "standard":
        pending_candidates = data.get("unclassified_observation_candidates")
        candidate_resolutions = data.get("candidate_resolutions")
        current_input_id = data.get("current_input_id")
        current_candidates = [
            item
            for item in pending_candidates
            if isinstance(item, dict)
            and item.get("input_id") == current_input_id
            and item.get("status") == "pending_confirmation"
        ] if isinstance(pending_candidates, list) else []
        current_claims = [
            item
            for item in data.get("claims", [])
            if isinstance(item, dict) and item.get("input_id") == current_input_id
        ]
        current_evidence = [
            item
            for item in data.get("evidence", [])
            if isinstance(item, dict) and item.get("input_id") == current_input_id
        ]
        current_resolutions = [
            item
            for item in candidate_resolutions
            if isinstance(item, dict)
            and item.get("input_id") == current_input_id
        ] if isinstance(candidate_resolutions, list) else []
        candidate_only = (
            bool(current_candidates or current_resolutions)
            and not current_claims
            and not current_evidence
        )
        if not data.get("claims") and not candidate_only:
            errors.append(error("CLAIM_REQUIRED", "/claims", "standard mode requires at least one anchored claim"))
        if not data.get("evidence") and not candidate_only:
            errors.append(error("EVIDENCE_REQUIRED", "/evidence", "standard mode requires at least one bounded evidence object"))
        if not data.get("unknowns"):
            errors.append(error("UNKNOWN_REQUIRED", "/unknowns", "standard mode must preserve at least one current unknown"))
        decisions = data.get("user_decisions")
        _check_string_list(errors, decisions, "/user_decisions", nonempty=True)
    elif mode == "safety":
        _check_string_list(errors, data.get("user_decisions"), "/user_decisions")
    elif mode == "passthrough":
        for field in (
            "unclassified_observation_candidates",
            "candidate_resolutions",
            "claims",
            "evidence",
            "evidence_links",
            "unknowns",
            "hypotheses",
            "actions",
            "user_decisions",
        ):
            if data.get(field):
                errors.append(error("PASSTHROUGH_ANALYSIS_NOT_ALLOWED", f"/{field}", "passthrough mode cannot contain analysis"))
        if data.get("discriminator") is not None:
            errors.append(error("PASSTHROUGH_ANALYSIS_NOT_ALLOWED", "/discriminator", "passthrough mode cannot contain a discriminator"))
    decisions = data.get("user_decisions")
    if isinstance(decisions, list):
        for index, decision in enumerate(decisions):
            if decision not in DECISION_CATALOG:
                errors.append(
                    error(
                        "DECISION_SCOPE_REQUIRED",
                        f"/user_decisions/{index}",
                        "decision must come from the finite non-action decision catalog",
                    )
                )


def _validate_change_log(
    errors: list[dict[str, str]],
    data: dict[str, Any],
    claims: dict[str, dict[str, Any]],
    evidence: dict[str, dict[str, Any]],
    previous: dict[str, Any] | None,
) -> None:
    changes = data.get("change_log")
    if not isinstance(changes, list):
        errors.append(error("REQUIRED_ARRAY", "/change_log", "must be an array"))
        return
    evidence_ids = set(evidence)
    previous_evidence_ids = {
        item.get("id")
        for item in (previous or {}).get("evidence", [])
        if isinstance(item, dict)
    }
    new_evidence_ids = evidence_ids - previous_evidence_ids
    previous_claims = {
        item.get("id"): item
        for item in (previous or {}).get("claims", [])
        if isinstance(item, dict)
    }
    previous_claim_ids = set(previous_claims)
    source_spans = {
        item.get("id"): item
        for item in data.get("source_spans", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    inputs = {
        item.get("id"): item
        for item in data.get("inputs", [])
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    link_relation_by_pair = {
        (item.get("proposition_id"), item.get("evidence_ref")): item.get("relation")
        for item in data.get("evidence_links", [])
        if isinstance(item, dict)
    }
    link_by_pair = {
        (item.get("proposition_id"), item.get("evidence_ref")): item
        for item in data.get("evidence_links", [])
        if isinstance(item, dict)
    }

    def anchored_speaker(item: dict[str, Any]) -> str | None:
        span = source_spans.get(item.get("source_span_id"), {})
        input_item = inputs.get(item.get("input_id"), {})
        text = str(input_item.get("text", ""))
        start = span.get("start")
        if not isinstance(start, int):
            return None
        clause_start = max(
            (text.rfind(mark, 0, start) for mark in "。！？；\n"),
            default=-1,
        ) + 1
        context = text[clause_start:start]
        matches = list(
            re.finditer(
                r"(?P<speaker>(?:[一-鿿A-Za-z0-9]{1,12}"
                r"(?:公司|事业部|部门|团队|分部|中心)(?:的)?)?"
                r"(?:老板|经理|主管|上司)|前任|同事|朋友|对方|他|她|我|"
                r"小[一-鿿A-Za-z0-9]{1,3}|[一-鿿]{2,4}?)"
                r"(?:现在|刚刚|明确|随后|后来)?"
                r"(?:说|表示|回答|改口|更正|撤回|收回)",
                context,
            )
        )
        return matches[-1].group("speaker") if matches else None

    def validate_supersession(
        change: dict[str, Any], path: str, target_id: str | None
    ) -> None:
        replacement_id = change.get("superseded_by_claim_id")
        replacement = claims.get(replacement_id)
        old_claim = previous_claims.get(target_id)
        replacement_valid = bool(
            isinstance(replacement_id, str)
            and replacement_id not in previous_claim_ids
            and isinstance(replacement, dict)
            and replacement.get("kind") == "stated_position"
            and replacement.get("input_id") == data.get("current_input_id")
            and replacement.get("source_type") == "direct_quote"
            and replacement.get("epistemic_status") == "directly_stated"
        )
        if not replacement_valid:
            errors.append(
                error(
                    "SUPERSESSION_REPLACEMENT_INVALID",
                    f"{path}/superseded_by_claim_id",
                    "replacement must be a new current directly stated position",
                )
            )
            return
        assert isinstance(replacement, dict)
        current_input = inputs.get(data.get("current_input_id"), {})
        current_text = str(current_input.get("text", ""))
        old_quote = str((old_claim or {}).get("exact_quote", ""))
        new_quote = str(replacement.get("exact_quote", ""))
        explicit_frame = bool(
            re.search(
                r"(?:明确)?(?:改口|更正|撤回|收回).{0,64}"
                r"(?:改为|改成|现在(?:说|表示)|当前原话|新原话)",
                current_text,
            )
            or re.search(r"从.{0,40}改(?:为|成).{0,40}", current_text)
        )
        replacement_span = source_spans.get(replacement.get("source_span_id"), {})
        source_disqualified = bool(
            ROLE_EVIDENCE_UNCERTAINTY_PATTERN.search(current_text)
            or re.search(r"转述|转达|传话|透露|代为传达", current_text)
            or _expected_source_type_for_span(replacement_span) == "secondhand"
            or _direct_quote_has_past_scope(current_text, replacement_span)
        )
        old_speaker = anchored_speaker(old_claim or {})
        new_speaker = anchored_speaker(replacement)
        same_speaker = bool(old_speaker and new_speaker and old_speaker == new_speaker)
        if (
            not explicit_frame
            or source_disqualified
            or not old_quote
            or not new_quote
            or old_quote not in current_text
            or new_quote not in current_text
            or not same_speaker
        ):
            errors.append(
                error(
                    "SUPERSESSION_NOT_EXPLICIT",
                    path,
                    "supersession requires a same-speaker current direct correction containing both old and replacement quotes",
                )
            )
        refs = change.get("reason_evidence_refs")
        if isinstance(refs, list):
            for ref in refs:
                evidence_item = evidence.get(ref)
                link = link_by_pair.get((replacement_id, ref))
                if not (
                    isinstance(evidence_item, dict)
                    and evidence_item.get("input_id") == data.get("current_input_id")
                    and evidence_item.get("source_span_id")
                    == replacement.get("source_span_id")
                    and evidence_item.get("exact_quote") == new_quote
                    and isinstance(link, dict)
                    and link.get("relation") == "supports"
                    and link.get("strength") == "direct"
                ):
                    errors.append(
                        error(
                            "CHANGE_REASON_NOT_CAUSAL",
                            f"{path}/reason_evidence_refs",
                            f"{ref} must directly support replacement claim {replacement_id}",
                        )
                    )

    def validate_retraction(
        change: dict[str, Any], path: str, target_id: str | None
    ) -> None:
        old_claim = previous_claims.get(target_id)
        active_prior_stories = [
            item
            for item in previous_claims.values()
            if item.get("kind") in RETRACTABLE_STORY_KINDS
            and item.get("epistemic_status") not in {"retracted", "superseded"}
        ]
        if not (
            isinstance(old_claim, dict)
            and old_claim.get("kind") in RETRACTABLE_STORY_KINDS
        ):
            errors.append(
                error(
                    "RETRACTION_TRANSITION_INVALID",
                    path,
                    "only a prior interpretation, motive inference, identity claim, or prediction may be retracted",
                )
            )
            return
        refs = change.get("reason_evidence_refs")
        explicit_refs = []
        if isinstance(refs, list):
            for ref in refs:
                evidence_item = evidence.get(ref)
                if not isinstance(evidence_item, dict):
                    continue
                anchored_current = (
                    evidence_item.get("input_id") == data.get("current_input_id")
                    and isinstance(evidence_item.get("exact_quote"), str)
                )
                relation = link_relation_by_pair.get((target_id, ref))
                if (
                    anchored_current
                    and relation == "does_not_establish"
                    and _story_retraction_is_explicit(
                        str(evidence_item.get("exact_quote", "")),
                        old_claim,
                        active_prior_stories,
                    )
                ):
                    explicit_refs.append(ref)
        if not explicit_refs:
            errors.append(
                error(
                    "RETRACTION_NOT_EXPLICIT",
                    path,
                    "story retraction requires current source-bound first-person disavowal evidence linked with does_not_establish",
                )
            )
    seen_targets: set[str] = set()
    for position, item in enumerate(changes):
        path = f"/change_log/{position}"
        if not isinstance(item, dict):
            errors.append(error("TYPE_ERROR", path, "must be an object"))
            continue
        _add_unknown_keys(errors, item, CHANGE_KEYS, path)
        target_id = _require_string(errors, item, "target_id", path)
        if item.get("from_status") not in EPISTEMIC_STATUSES:
            errors.append(error("ENUM_ERROR", f"{path}/from_status", "unsupported prior status"))
        if item.get("to_status") not in EPISTEMIC_STATUSES:
            errors.append(error("ENUM_ERROR", f"{path}/to_status", "unsupported new status"))
        if item.get("to_status") == "superseded":
            validate_supersession(item, path, target_id)
        elif item.get("to_status") == "retracted":
            validate_retraction(item, path, target_id)
        elif "superseded_by_claim_id" in item:
            errors.append(
                error(
                    "SUPERSESSION_FIELD_UNEXPECTED",
                    f"{path}/superseded_by_claim_id",
                    "replacement claim is only valid for a superseded transition",
                )
            )
        refs = item.get("reason_evidence_refs")
        if not isinstance(refs, list) or not refs:
            errors.append(error("CHANGE_WITHOUT_EVIDENCE", f"{path}/reason_evidence_refs", "status changes require evidence"))
        else:
            for ref in refs:
                if ref not in evidence_ids:
                    errors.append(error("REFERENCE_NOT_FOUND", f"{path}/reason_evidence_refs", f"unknown evidence id {ref}"))
                elif ref not in new_evidence_ids:
                    errors.append(
                        error(
                            "CHANGE_REQUIRES_NEW_EVIDENCE",
                            f"{path}/reason_evidence_refs",
                            f"{ref} is not evidence added in this revision",
                        )
                    )
                elif evidence[ref].get("input_id") != data.get("current_input_id"):
                    errors.append(
                        error(
                            "CHANGE_REQUIRES_NEW_EVIDENCE",
                            f"{path}/reason_evidence_refs",
                            f"{ref} is not anchored to the current input",
                        )
                    )
                elif target_id and item.get("to_status") != "superseded":
                    relation = link_relation_by_pair.get((target_id, ref))
                    required_relation = {
                        "weakly_supported": "supports",
                        "conflicted": "conflicts",
                        "unverified": "does_not_establish",
                        "retracted": "does_not_establish",
                    }.get(item.get("to_status"))
                    if relation is None or (
                        required_relation is not None and relation != required_relation
                    ):
                        errors.append(
                            error(
                                "CHANGE_REASON_NOT_CAUSAL",
                                f"{path}/reason_evidence_refs",
                                f"{ref} does not have the {required_relation or 'relevant'} link to {target_id}",
                            )
                        )
                    else:
                        evidence_item = evidence.get(ref, {})
                        scoped_evidence = dict(evidence_item)
                        evidence_span = source_spans.get(
                            evidence_item.get("source_span_id"), {}
                        )
                        scoped_evidence["source_label"] = evidence_span.get(
                            "source_label", ""
                        )
                        claim = claims.get(target_id, {})
                        if relation not in _allowed_relation_for_claim_evidence(
                            claim, scoped_evidence
                        ):
                            errors.append(
                                error(
                                    "CHANGE_REASON_NOT_CAUSAL",
                                    f"{path}/reason_evidence_refs",
                                    f"{ref} is not semantically valid evidence for {target_id}",
                                )
                            )
        if target_id:
            if target_id in seen_targets:
                errors.append(error("DUPLICATE_CHANGE", f"{path}/target_id", "each target may change once per revision"))
            seen_targets.add(target_id)
            old_claim = previous_claims.get(target_id)
            new_claim = claims.get(target_id)
            if old_claim is None or new_claim is None:
                errors.append(error("CHANGE_TARGET_NOT_FOUND", f"{path}/target_id", "target must exist in both revisions"))
            else:
                actual_from = old_claim.get("epistemic_status")
                actual_to = new_claim.get("epistemic_status")
                if item.get("to_status") == "superseded" and not (
                    old_claim.get("kind") == "stated_position"
                    and actual_from == "directly_stated"
                    and actual_to == "superseded"
                ):
                    errors.append(
                        error(
                            "SUPERSESSION_TRANSITION_INVALID",
                            path,
                            "only directly_stated positions may transition to superseded",
                        )
                    )
                if item.get("to_status") == "retracted" and not (
                    old_claim.get("kind") in RETRACTABLE_STORY_KINDS
                    and actual_from not in {"retracted", "superseded"}
                    and actual_to == "retracted"
                ):
                    errors.append(
                        error(
                            "RETRACTION_TRANSITION_INVALID",
                            path,
                            "only an active prior story may transition to retracted",
                        )
                    )
                if item.get("from_status") != actual_from or item.get("to_status") != actual_to:
                    errors.append(
                        error(
                            "CHANGE_TRANSITION_MISMATCH",
                            path,
                            f"expected actual transition {actual_from} to {actual_to}",
                        )
                    )
                if actual_from == actual_to:
                    errors.append(error("CHANGE_WITHOUT_TRANSITION", path, "change_log target status did not change"))


def _is_required_current_observation_span(item: dict[str, Any]) -> bool:
    """Require only directly asserted, non-hearsay observation spans in updates."""
    return (
        isinstance(item.get("id"), str)
        and item.get("quoted") is not True
        and derive_observation_type(str(item.get("text", "")), item) is not None
        and _expected_source_type_for_span(item) != "secondhand"
    )


def _legacy_epoch_from_previous(previous: dict[str, Any]) -> dict[str, Any] | None:
    existing = previous.get("legacy_epoch")
    if isinstance(existing, dict):
        return copy.deepcopy(existing)
    previous_pair = _casefile_version_pair(previous)
    if _validation_profile_for_pair(previous_pair) in {None, "current"}:
        return None
    return {
        "through_revision": previous.get("revision"),
        "source_version_pair": {
            "schema_version": previous_pair[0],
            "skill_version": previous_pair[1],
        },
        "input_ids": [
            item.get("id")
            for item in previous.get("inputs", [])
            if isinstance(item, dict)
        ],
        "source_span_ids": [
            item.get("id")
            for item in previous.get("source_spans", [])
            if isinstance(item, dict)
        ],
        "claim_ids": [
            item.get("id")
            for item in previous.get("claims", [])
            if isinstance(item, dict)
        ],
        "evidence_ids": [
            item.get("id")
            for item in previous.get("evidence", [])
            if isinstance(item, dict)
        ],
    }


def _validate_legacy_epoch(
    errors: list[dict[str, str]],
    data: dict[str, Any],
    previous: dict[str, Any] | None,
) -> None:
    epoch = data.get("legacy_epoch")
    expected = (
        _legacy_epoch_from_previous(previous)
        if isinstance(previous, dict)
        else None
    )
    if expected is not None and epoch is None:
        errors.append(
            error(
                "LEGACY_EPOCH_REQUIRED",
                "/legacy_epoch",
                "a current revision migrated from a legacy profile must record the immutable epoch boundary",
            )
        )
        return
    if expected is not None and epoch != expected:
        code = (
            "LEGACY_EPOCH_MUTATED"
            if isinstance(previous.get("legacy_epoch"), dict)
            else "LEGACY_EPOCH_MISMATCH"
        )
        errors.append(
            error(
                code,
                "/legacy_epoch",
                "legacy epoch metadata must exactly preserve the validated historical boundary",
            )
        )
    if expected is None and epoch is not None:
        errors.append(
            error(
                "LEGACY_EPOCH_UNEXPECTED",
                "/legacy_epoch",
                "a legacy epoch cannot appear unless it is derived from the adjacent validated history",
            )
        )
    if epoch is None:
        return
    if not isinstance(epoch, dict):
        errors.append(error("TYPE_ERROR", "/legacy_epoch", "must be an object"))
        return
    _add_unknown_keys(errors, epoch, LEGACY_EPOCH_KEYS, "/legacy_epoch")
    for key in LEGACY_EPOCH_KEYS:
        if key not in epoch:
            errors.append(
                error("REQUIRED_FIELD", f"/legacy_epoch/{key}", "field is required")
            )
    through_revision = epoch.get("through_revision")
    if (
        not isinstance(through_revision, int)
        or isinstance(through_revision, bool)
        or through_revision < 1
        or (
            isinstance(data.get("revision"), int)
            and through_revision >= data.get("revision")
        )
    ):
        errors.append(
            error(
                "LEGACY_EPOCH_REVISION_INVALID",
                "/legacy_epoch/through_revision",
                "through_revision must be a positive revision before the current revision",
            )
        )
    source_pair = epoch.get("source_version_pair")
    if not isinstance(source_pair, dict):
        errors.append(
            error(
                "TYPE_ERROR",
                "/legacy_epoch/source_version_pair",
                "must be an object",
            )
        )
    else:
        _add_unknown_keys(
            errors,
            source_pair,
            LEGACY_EPOCH_VERSION_KEYS,
            "/legacy_epoch/source_version_pair",
        )
        pair = (
            source_pair.get("schema_version"),
            source_pair.get("skill_version"),
        )
        if pair not in MIGRATABLE_VERSION_PAIRS:
            errors.append(
                error(
                    "LEGACY_EPOCH_VERSION_INVALID",
                    "/legacy_epoch/source_version_pair",
                    "source version pair must name a registered legacy profile",
                )
            )
    collections = {
        "input_ids": {item.get("id") for item in data.get("inputs", []) if isinstance(item, dict)},
        "source_span_ids": {item.get("id") for item in data.get("source_spans", []) if isinstance(item, dict)},
        "claim_ids": {item.get("id") for item in data.get("claims", []) if isinstance(item, dict)},
        "evidence_ids": {item.get("id") for item in data.get("evidence", []) if isinstance(item, dict)},
    }
    for key, known_ids in collections.items():
        values = epoch.get(key)
        _check_string_list(errors, values, f"/legacy_epoch/{key}", unique=True)
        if isinstance(values, list):
            missing = [value for value in values if value not in known_ids]
            if missing:
                errors.append(
                    error(
                        "LEGACY_EPOCH_REFERENCE_NOT_FOUND",
                        f"/legacy_epoch/{key}",
                        f"unknown historical ids: {missing}",
                    )
                )


def _validate_history(
    errors: list[dict[str, str]],
    current: dict[str, Any],
    previous: dict[str, Any] | None,
) -> None:
    revision = current.get("revision")
    if previous is None:
        if revision == 1:
            if current.get("previous_case_sha256") is not None:
                errors.append(error("UNEXPECTED_PREVIOUS_HASH", "/previous_case_sha256", "revision 1 must not have a previous hash"))
        elif isinstance(revision, int) and revision > 1:
            prior_hash = current.get("previous_case_sha256")
            if not isinstance(prior_hash, str) or not re.fullmatch(r"[0-9a-f]{64}", prior_hash):
                errors.append(error("PREVIOUS_HASH_INVALID", "/previous_case_sha256", "must be a lowercase sha256 digest"))
            else:
                errors.append(error("PREVIOUS_REQUIRED", "/previous_case_sha256", "previous casefile is required to validate this revision"))
        return

    previous_version_pair = _casefile_version_pair(previous)
    current_version_pair = _casefile_version_pair(current)
    previous_rank = VERSION_PAIR_RANK.get(previous_version_pair)
    current_rank = VERSION_PAIR_RANK.get(current_version_pair)
    if previous_rank is None:
        errors.append(
            error(
                "PREVIOUS_VERSION_PAIR_UNSUPPORTED",
                "/previous_case_sha256",
                "the previous revision uses an unsupported schema/skill pair",
            )
        )
    elif _validation_profile_for_pair(previous_version_pair) is None:
        errors.append(
            error(
                "PREVIOUS_VERSION_PROFILE_UNAVAILABLE",
                "/previous_case_sha256",
                "the previous revision has no registered validation profile",
            )
        )
    elif current_rank is not None and current_rank < previous_rank:
        errors.append(
            error(
                "VERSION_MIGRATION_DIRECTION_INVALID",
                "/skill_version",
                "casefile history may keep the same version pair or migrate forward, never downgrade",
            )
        )
    elif (
        current_rank is not None
        and (previous_version_pair, current_version_pair)
        not in VERSION_MIGRATION_EDGES
    ):
        errors.append(
            error(
                "VERSION_MIGRATION_EDGE_UNSUPPORTED",
                "/skill_version",
                "this forward migration edge is not registered",
            )
        )

    if current.get("case_id") != previous.get("case_id"):
        errors.append(error("CASE_ID_CHANGED", "/case_id", "case_id must remain stable across revisions"))
    if current.get("revision") != previous.get("revision", 0) + 1:
        errors.append(error("REVISION_SEQUENCE_INVALID", "/revision", "revision must increment by one"))
    expected_hash = canonical_sha256(previous)
    if current.get("previous_case_sha256") != expected_hash:
        errors.append(error("PREVIOUS_HASH_MISMATCH", "/previous_case_sha256", "hash chain does not match the prior casefile"))

    def preserve_scalar(field: str) -> None:
        if field not in current:
            errors.append(
                error(
                    "HISTORY_ITEM_REMOVED",
                    f"/{field}",
                    f"prior field {field} was removed",
                )
            )
        elif current.get(field) != previous.get(field):
            errors.append(
                error(
                    "HISTORY_ITEM_MUTATED",
                    f"/{field}",
                    f"prior field {field} changed",
                )
            )

    def preserve_prefix(
        prior_items: Any,
        current_items: Any,
        path: str,
    ) -> None:
        if not isinstance(prior_items, list):
            return
        if not isinstance(current_items, list) or len(current_items) < len(prior_items):
            errors.append(
                error(
                    "HISTORY_ITEM_REMOVED",
                    path,
                    "prior ordered history was shortened or removed",
                )
            )
            return
        if current_items[: len(prior_items)] != prior_items:
            errors.append(
                error(
                    "HISTORY_ITEM_MUTATED",
                    path,
                    "prior ordered history was rewritten or reordered",
                )
            )

    previous_mode = previous.get("mode")
    current_mode = current.get("mode")
    current_input_text = ""
    for input_item in current.get("inputs", []):
        if (
            isinstance(input_item, dict)
            and input_item.get("id") == current.get("current_input_id")
            and isinstance(input_item.get("text"), str)
        ):
            current_input_text = input_item["text"]
            break
    if current.get("mode") == "standard" and current_input_text:
        active_prior_stories = [
            item
            for item in previous.get("claims", [])
            if isinstance(item, dict)
            and item.get("kind") in RETRACTABLE_STORY_KINDS
            and item.get("epistemic_status") not in {"retracted", "superseded"}
        ]
        current_claims_by_id = {
            item.get("id"): item
            for item in current.get("claims", [])
            if isinstance(item, dict)
        }
        for prior_story in active_prior_stories:
            if not _story_retraction_is_explicit(
                current_input_text,
                prior_story,
                active_prior_stories,
            ):
                continue
            current_story = current_claims_by_id.get(prior_story.get("id"), {})
            if current_story.get("epistemic_status") != "retracted":
                errors.append(
                    error(
                        "RETRACTED_STORY_STATUS_NOT_UPDATED",
                        f"/claims/{prior_story.get('id')}/epistemic_status",
                        "the user explicitly withdrew this prior story; mark it retracted with current source-bound evidence",
                    )
                )
    current_risk_signals = (
        current.get("safety", {}).get("risk_signals", [])
        if isinstance(current.get("safety"), dict)
        else []
    )
    has_current_anchored_risk = any(
        isinstance(item, dict)
        and item.get("input_id") == current.get("current_input_id")
        and item.get("routing_basis") in SAFETY_ROUTING_BASES
        and item.get("signal_type") in SIGNAL_TYPES
        for item in current_risk_signals
    )
    legal_safety_escalation = (
        previous_mode in {"standard", "passthrough"}
        and current_mode == "safety"
        and (
            detect_immediate_risk(current_input_text)
            or has_current_anchored_risk
        )
    )
    if "mode" not in current:
        errors.append(
            error("HISTORY_ITEM_REMOVED", "/mode", "prior mode was removed")
        )
    elif current_mode != previous_mode and not legal_safety_escalation:
        errors.append(
            error(
                "HISTORY_ITEM_MUTATED",
                "/mode",
                "mode may only escalate to safety when the current input contains immediate risk",
            )
        )

    preserve_scalar("discriminator")
    preserve_prefix(
        previous.get("user_decisions"),
        current.get("user_decisions"),
        "/user_decisions",
    )
    # A safety escalation must put an immediate action first, so replacing a
    # prior standard action list is the one deliberate exception. All other
    # action history is prefix-immutable and append-only.
    if not legal_safety_escalation:
        preserve_prefix(previous.get("actions"), current.get("actions"), "/actions")

    previous_safety = previous.get("safety")
    current_safety = current.get("safety")
    if isinstance(previous_safety, dict):
        if not isinstance(current_safety, dict) or "risk_signals" not in current_safety:
            errors.append(
                error(
                    "HISTORY_ITEM_REMOVED",
                    "/safety/risk_signals",
                    "prior safety signal history was removed",
                )
            )
        else:
            preserve_prefix(
                previous_safety.get("risk_signals"),
                current_safety.get("risk_signals"),
                "/safety/risk_signals",
            )

    previous_request = previous.get("hypothesis_request")
    current_request = current.get("hypothesis_request")
    if previous_request is not None and current_request != previous_request:
        errors.append(
            error(
                "HISTORY_ITEM_MUTATED",
                "/hypothesis_request",
                "a prior hypothesis request is immutable; a later revision cannot enlarge or rewrite it",
            )
        )
    elif (
        previous_request is None
        and isinstance(current_request, dict)
        and current_request.get("input_id") != current.get("current_input_id")
    ):
        errors.append(
            error(
                "HISTORY_ITEM_MUTATED",
                "/hypothesis_request/input_id",
                "a newly introduced hypothesis request must be anchored in the current revision input",
            )
        )

    prior_input_ids = {
        item.get("id") for item in previous.get("inputs", []) if isinstance(item, dict)
    }
    current_input_ids = {
        item.get("id") for item in current.get("inputs", []) if isinstance(item, dict)
    }
    added_input_ids = current_input_ids - prior_input_ids
    if added_input_ids != {current.get("current_input_id")}:
        errors.append(
            error(
                "REVISION_INPUT_INVALID",
                "/inputs",
                "each revision must append exactly one new current input",
            )
        )
    if current_mode == "standard":
        current_input_id = current.get("current_input_id")
        prior_claim_ids = {
            item.get("id")
            for item in previous.get("claims", [])
            if isinstance(item, dict)
        }
        prior_evidence_ids = {
            item.get("id")
            for item in previous.get("evidence", [])
            if isinstance(item, dict)
        }
        current_claims = [
            item
            for item in current.get("claims", [])
            if isinstance(item, dict)
            and item.get("id") not in prior_claim_ids
            and item.get("input_id") == current_input_id
        ]
        current_evidence = [
            item
            for item in current.get("evidence", [])
            if isinstance(item, dict)
            and item.get("id") not in prior_evidence_ids
            and item.get("input_id") == current_input_id
        ]
        current_candidates = [
            item
            for item in current.get("unclassified_observation_candidates", [])
            if isinstance(item, dict)
            and item.get("input_id") == current_input_id
            and item.get("status") == "pending_confirmation"
        ]
        current_resolutions = [
            item
            for item in current.get("candidate_resolutions", [])
            if isinstance(item, dict)
            and item.get("input_id") == current_input_id
        ]
        candidate_only_update = bool(
            current_candidates or current_resolutions
        ) and not current_claims and not current_evidence
        retraction_only_update = bool(current.get("change_log")) and all(
            isinstance(item, dict)
            and item.get("to_status") == "retracted"
            and item.get("target_id") in prior_claim_ids
            for item in current.get("change_log", [])
        )
        if (
            not current_claims
            and not candidate_only_update
            and not retraction_only_update
        ):
            errors.append(
                error(
                    "CURRENT_INPUT_CLAIM_REQUIRED",
                    "/claims",
                    "a standard revision must add at least one claim anchored to the current input",
                )
            )
        if not current_evidence and not candidate_only_update:
            errors.append(
                error(
                    "CURRENT_INPUT_EVIDENCE_REQUIRED",
                    "/evidence",
                    "a standard revision must add at least one evidence object anchored to the current input",
                )
            )
        current_spans = [
            item
            for item in current.get("source_spans", [])
            if isinstance(item, dict) and item.get("input_id") == current_input_id
        ]
        current_spans_by_id = {
            item.get("id"): item
            for item in current_spans
            if isinstance(item.get("id"), str)
        }
        required_observation_span_ids = {
            item.get("id")
            for item in current_spans
            if _is_required_current_observation_span(item)
        }
        claimed_span_ids = {
            item.get("source_span_id")
            for item in current_claims
            if item.get("kind") == "observable_fact"
            and item.get("source_type")
            in {"user_direct_observation", "unverified_artifact"}
            and (
                span := current_spans_by_id.get(item.get("source_span_id"))
            )
            is not None
            and item.get("observation_type")
            == derive_observation_type(str(span.get("text", "")), span)
            and (
                _expected_source_type_for_span(span) is None
                or item.get("source_type") == _expected_source_type_for_span(span)
            )
        }
        evidenced_span_ids = {
            item.get("source_span_id")
            for item in current_evidence
            if item.get("source_type")
            in {"user_direct_observation", "unverified_artifact"}
            and (
                span := current_spans_by_id.get(item.get("source_span_id"))
            )
            is not None
            and (
                _expected_source_type_for_span(span) is None
                or item.get("source_type") == _expected_source_type_for_span(span)
            )
        }
        missing_claim_spans = sorted(
            required_observation_span_ids - claimed_span_ids
        )
        missing_evidence_spans = sorted(
            required_observation_span_ids - evidenced_span_ids
        )
        if missing_claim_spans:
            errors.append(
                error(
                    "CURRENT_OBSERVATION_CLAIM_MISSING",
                    "/claims",
                    f"current observable spans were not consumed: {missing_claim_spans}",
                )
            )
        if missing_evidence_spans:
            errors.append(
                error(
                    "CURRENT_OBSERVATION_EVIDENCE_MISSING",
                    "/evidence",
                    f"current observable spans lack evidence objects: {missing_evidence_spans}",
                )
            )

    current_changes = {
        (item.get("target_id"), item.get("from_status"), item.get("to_status"))
        for item in current.get("change_log", [])
        if isinstance(item, dict)
    }
    for field in (
        "inputs",
        "source_spans",
        "unclassified_observation_candidates",
        "candidate_resolutions",
        "claims",
        "evidence",
        "unknowns",
        "hypotheses",
    ):
        prior_order = [
            item.get("id")
            for item in previous.get(field, [])
            if isinstance(item, dict)
        ]
        current_order = [
            item.get("id")
            for item in current.get(field, [])
            if isinstance(item, dict)
        ]
        if current_order[: len(prior_order)] != prior_order:
            errors.append(
                error(
                    "HISTORY_ITEM_MUTATED",
                    f"/{field}",
                    "prior items must retain their original order before new items are appended",
                )
            )
        prior_items = {item.get("id"): item for item in previous.get(field, []) if isinstance(item, dict)}
        current_items = {item.get("id"): item for item in current.get(field, []) if isinstance(item, dict)}
        for item_id, prior_item in prior_items.items():
            if item_id not in current_items:
                errors.append(error("HISTORY_ITEM_REMOVED", f"/{field}", f"prior item {item_id} was removed"))
                continue
            current_item = current_items[item_id]
            if field == "claims":
                prior_static = {key: value for key, value in prior_item.items() if key != "epistemic_status"}
                current_static = {key: value for key, value in current_item.items() if key != "epistemic_status"}
                if prior_static != current_static:
                    errors.append(error("HISTORY_ITEM_MUTATED", f"/{field}/{item_id}", "prior claim content changed"))
                prior_status = prior_item.get("epistemic_status")
                current_status = current_item.get("epistemic_status")
                if prior_status == "superseded" and current_status != "superseded":
                    errors.append(
                        error(
                            "SUPERSEDED_STATUS_TERMINAL",
                            f"/{field}/{item_id}/epistemic_status",
                            "a superseded position remains historical in later revisions",
                        )
                    )
                if prior_status == "retracted" and current_status != "retracted":
                    errors.append(
                        error(
                            "RETRACTED_STATUS_TERMINAL",
                            f"/{field}/{item_id}/epistemic_status",
                            "a retracted story remains historical in later revisions",
                        )
                    )
                if prior_status != current_status and (item_id, prior_status, current_status) not in current_changes:
                    errors.append(error("STATUS_CHANGE_NOT_LOGGED", f"/{field}/{item_id}/epistemic_status", "status change needs change_log"))
            elif field == "unknowns":
                if prior_item != current_item:
                    errors.append(
                        error(
                            "HISTORY_ITEM_MUTATED",
                            f"/{field}/{item_id}",
                            "version 2 unknowns stay open and immutable; add a new claim and evidence instead",
                        )
                    )
            elif prior_item != current_item:
                errors.append(error("HISTORY_ITEM_MUTATED", f"/{field}/{item_id}", "prior item changed instead of being appended"))

    preserve_prefix(
        previous.get("evidence_links"),
        current.get("evidence_links"),
        "/evidence_links",
    )
    prior_links = {canonical_sha256(item) for item in previous.get("evidence_links", [])}
    current_links = {canonical_sha256(item) for item in current.get("evidence_links", [])}
    if not prior_links.issubset(current_links):
        errors.append(error("HISTORY_ITEM_REMOVED", "/evidence_links", "a prior evidence link was removed"))


def validate_casefile(
    data: Any,
    previous: dict[str, Any] | None = None,
    *,
    legacy_receipt: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    errors: list[dict[str, str]] = []
    if not isinstance(data, dict):
        return [error("TYPE_ERROR", "", "casefile root must be an object")]

    _add_unknown_keys(errors, data, ROOT_KEYS, "")
    for key in sorted(REQUIRED_ROOT_KEYS):
        if key not in data:
            errors.append(error("REQUIRED_FIELD", f"/{key}", "field is required"))
    version_pair = _casefile_version_pair(data)
    validation_profile = _validation_profile_for_pair(version_pair)
    previous_pair = _casefile_version_pair(previous)
    if version_pair not in SUPPORTED_VERSION_PAIRS:
        supported = ", ".join(
            f"{schema}/{skill}"
            for schema, skill in sorted(SUPPORTED_VERSION_PAIRS)
        )
        errors.append(
            error(
                "VERSION_PAIR_UNSUPPORTED",
                "/schema_version",
                f"unsupported schema/skill pair; supported pairs: {supported}",
            )
        )
    elif validation_profile is None:
        errors.append(
            error(
                "VERSION_PROFILE_UNAVAILABLE",
                "/schema_version",
                "no validation profile is registered for this schema/skill pair",
            )
        )
    elif (
        version_pair in PRE_ATTRIBUTED_STATEMENT_VERSION_PAIRS
        and isinstance(data.get("claims"), list)
        and any(
            isinstance(item, dict)
            and item.get("kind") == "attributed_statement"
            for item in data["claims"]
        )
    ):
        errors.append(
            error(
                "LEGACY_CLAIM_KIND_UNSUPPORTED",
                "/claims",
                "attributed_statement was not part of this legacy version pair",
            )
        )
    legacy_receipt_target: dict[str, Any] | None = None
    if version_pair in MIGRATABLE_VERSION_PAIRS:
        legacy_receipt_target = data
    elif previous_pair in MIGRATABLE_VERSION_PAIRS and isinstance(previous, dict):
        legacy_receipt_target = previous
    if legacy_receipt_target is not None:
        errors.extend(
            _legacy_receipt_validation_errors(
                legacy_receipt_target, legacy_receipt
            )
        )
    elif legacy_receipt is not None:
        errors.append(
            error(
                "LEGACY_RECEIPT_UNEXPECTED",
                "/legacy_receipt",
                "no legacy root or legacy-to-current transition requires this receipt",
            )
        )
    if not isinstance(data.get("case_id"), str) or not data.get("case_id", "").strip():
        errors.append(error("REQUIRED_STRING", "/case_id", "must be a non-empty string"))
    if not isinstance(data.get("revision"), int) or isinstance(data.get("revision"), bool) or data.get("revision", 0) < 1:
        errors.append(error("REVISION_INVALID", "/revision", "must be an integer of at least 1"))
    if data.get("mode") not in MODES:
        errors.append(error("ENUM_ERROR", "/mode", "unsupported mode"))
    if not isinstance(data.get("input_sha256"), str):
        errors.append(error("REQUIRED_STRING", "/input_sha256", "must be a sha256 string"))

    inputs = _validate_inputs(errors, data)
    source_spans = _validate_source_spans(
        errors,
        data,
        inputs,
        previous=previous,
        validation_profile=validation_profile,
    )
    observation_candidates = _validate_unclassified_observation_candidates(
        errors,
        data,
        inputs,
        source_spans,
        previous=previous,
        validation_profile=validation_profile,
    )
    _validate_candidate_resolutions(
        errors,
        data,
        inputs,
        source_spans,
        observation_candidates,
        previous=previous,
        validation_profile=validation_profile,
    )
    hypotheses = _validate_hypotheses(errors, data)
    claims = _validate_claims(
        errors,
        data,
        inputs,
        source_spans,
        previous=previous,
        validation_profile=validation_profile,
    )
    _validate_current_claim_coverage(
        errors,
        data,
        inputs,
        source_spans,
        claims,
        validation_profile=validation_profile,
    )
    evidence = _validate_evidence(
        errors,
        data,
        inputs,
        source_spans,
        set(claims) | set(hypotheses),
        previous=previous,
        validation_profile=validation_profile,
    )
    unknowns = _validate_unknowns(errors, data)
    target_collections = {
        "claims": set(claims),
        "hypotheses": set(hypotheses),
        "unknowns": set(unknowns),
    }
    target_names = list(target_collections)
    for first_index, first_name in enumerate(target_names):
        for second_name in target_names[first_index + 1:]:
            for duplicate in sorted(target_collections[first_name] & target_collections[second_name]):
                errors.append(
                    error(
                        "GLOBAL_ID_COLLISION",
                        f"/{second_name}/{duplicate}",
                        f"target id also exists in {first_name}",
                    )
                )
    _validate_hypothesis_request(errors, data, inputs, source_spans, hypotheses)
    _validate_evidence_links(
        errors, data, claims, hypotheses, evidence, source_spans, previous
    )
    _validate_discriminator(
        errors,
        data,
        set(claims) | set(hypotheses) | set(unknowns),
        hypotheses,
    )
    _validate_actions(errors, data)
    _validate_safety(errors, data, inputs, source_spans, previous)
    _validate_mode_contract(errors, data)
    _validate_change_log(errors, data, claims, evidence, previous)
    _validate_legacy_epoch(errors, data, previous)
    _validate_history(errors, data, previous)

    return errors


def _bullet(items: list[str], empty: str) -> str:
    if not items:
        return empty
    return "\n".join(f"- {item}" for item in items)


def _direct_quote_render_context(
    data: dict[str, Any], claim: dict[str, Any]
) -> str:
    inputs = {
        item.get("id"): item
        for item in data.get("inputs", [])
        if isinstance(item, dict)
    }
    spans = {
        item.get("id"): item
        for item in data.get("source_spans", [])
        if isinstance(item, dict)
    }
    input_item = inputs.get(claim.get("input_id"), {})
    span = spans.get(claim.get("source_span_id"), {})
    input_text = str(input_item.get("text", ""))
    start = span.get("start")
    if not isinstance(start, int) or not input_text:
        return "原文未提供可绑定的说话人或时间语境"
    clause_start = max(
        (input_text.rfind(mark, 0, start) for mark in "。！？；\n"),
        default=-1,
    ) + 1
    context = input_text[clause_start:start].strip()
    context = re.sub(r"^\[[^\]]+\]\s*", "", context)
    context = re.sub(r"[“‘\"'].*?[”’\"']", "[先前表态]", context)
    context = context.rstrip("：: “‘\"'").strip()
    if not context:
        return "原文未提供明确说话人或时间"
    return context[-64:]


def _claim_lines(
    data: dict[str, Any],
    kinds: set[str],
    *,
    only_superseded: bool = False,
    only_retracted: bool = False,
    only_legacy: bool = False,
    kind_labels: dict[str, str] | None = None,
    include_quote_context: bool = False,
) -> list[str]:
    lines = []
    legacy_epoch = data.get("legacy_epoch")
    legacy_claim_ids = (
        set(legacy_epoch.get("claim_ids", []))
        if isinstance(legacy_epoch, dict)
        and isinstance(legacy_epoch.get("claim_ids"), list)
        else set()
    )
    for claim in data.get("claims", []):
        is_legacy_claim = claim.get("id") in legacy_claim_ids
        status = claim.get("epistemic_status", "unverified")
        if only_legacy:
            status_matches = is_legacy_claim
        elif is_legacy_claim:
            status_matches = False
        elif only_superseded:
            status_matches = status == "superseded"
        elif only_retracted:
            status_matches = status == "retracted"
        else:
            status_matches = status not in {"superseded", "retracted"}
        if claim.get("kind") in kinds and status_matches:
            exact_quote = claim.get("exact_quote", "")
            kind = str(claim.get("kind", ""))
            label = (
                f"[{kind_labels[kind]}] "
                if kind_labels and kind in kind_labels
                else ""
            )
            context = ""
            if (
                include_quote_context
                and kind in DIRECTLY_ATTRIBUTED_KINDS
                and is_legacy_claim
            ):
                context = (
                    "（历史版本保留：原文锚点和旧版分类已保存；"
                    "当前版本未重新认定来源类型，也不把引语内容升级为事件事实）"
                )
            elif include_quote_context and kind in DIRECTLY_ATTRIBUTED_KINDS:
                context = (
                    f"（引语语境：{_direct_quote_render_context(data, claim)}；"
                    "只证明这句话被直接表述（依据用户提供的具名直接引语），"
                    "不证明引语内容为事件事实）"
                )
            elif only_superseded:
                context = "（这条历史表态已被后续明确更正）"
            elif only_retracted:
                context = "（这条解释已被用户明确撤回，仅保留审计记录）"
            elif is_legacy_claim:
                context = "（历史版本保留；当前版本未按新规则重新分类）"
            lines.append(f"{label}“{exact_quote}”{context}")
    return lines


def render_markdown(data: dict[str, Any]) -> str:
    mode = data.get("mode")
    if mode == "passthrough":
        raise ValueError("passthrough mode must complete the original task directly")
    if mode == "safety":
        action_lines = [
            ACTION_CATALOG.get(action.get("action_type"), {}).get("text", "")
            for action in data.get("actions", [])
        ]
        safety_signal_labels = {
            "medical_emergency": "医疗紧急情况",
            "self_harm_risk": "本人可能面临自伤风险",
            "third_party_self_harm_risk": "他人可能面临自伤风险",
            "harm_to_others_risk": "可能伤害他人的风险",
            "explicit_threat": "明确威胁",
            "prior_violence_or_damage": "既往暴力或破坏行为",
            "access_or_location_exposure": "位置或接触风险",
            "other_immediate_risk": "其他即时风险",
            "urgent_legal_risk": "紧迫法律风险",
        }
        signals = [
            f"“{item.get('exact_quote', '')}”（"
            f"{safety_signal_labels.get(item.get('signal_type'), '需要立即核对的风险')}）"
            for item in data.get("safety", {}).get("risk_signals", [])
        ]
        return (
            "# 先处理现实安全\n\n"
            + _bullet(action_lines, "立即联系当地紧急或专业支持。")
            + "\n\n## 已保存的风险信号\n\n"
            + _bullet(signals, "未记录风险原句。")
            + "\n\n现有风险信号足以先采取安全行动，不需要先猜中对方动机。\n"
        )

    facts = _claim_lines(data, {"observable_fact"})
    direct_statements = _claim_lines(
        data,
        DIRECTLY_ATTRIBUTED_KINDS,
        kind_labels={
            "stated_position": "当前意愿、决定或边界",
            "attributed_statement": "归属于说话者的陈述",
        },
        include_quote_context=True,
    )
    legacy_claims = _claim_lines(
        data,
        CLAIM_KINDS,
        only_legacy=True,
        include_quote_context=True,
        kind_labels={
            "observable_fact": "历史版本保留的可观察事实分类",
            "explicit_feeling": "历史版本保留的感受分类",
            "stated_position": "历史版本保留的意愿、决定或边界分类",
            "attributed_statement": "历史版本保留的说话者陈述分类",
            "interpretation": "历史版本保留的事件解释分类",
            "motive_inference": "历史版本保留的动机推断分类",
            "identity_claim": "历史版本保留的身份定性分类",
            "prediction": "历史版本保留的未来预测分类",
        },
    )
    superseded_positions = _claim_lines(
        data, {"stated_position"}, only_superseded=True
    )
    retracted_stories = _claim_lines(
        data,
        RETRACTABLE_STORY_KINDS,
        only_retracted=True,
        kind_labels={
            "interpretation": "事件解释",
            "motive_inference": "动机推断",
            "identity_claim": "身份定性",
            "prediction": "未来预测",
        },
    )
    feelings = _claim_lines(data, {"explicit_feeling"})
    interpretations = _claim_lines(
        data,
        {"interpretation", "identity_claim", "prediction"},
        kind_labels={
            "interpretation": "事件解释",
            "identity_claim": "身份定性",
            "prediction": "未来预测",
        },
    )
    motives = _claim_lines(data, {"motive_inference"})
    candidates_by_id = {
        item.get("id"): item
        for item in data.get("unclassified_observation_candidates", [])
        if isinstance(item, dict)
    }
    resolved_candidate_ids = {
        item.get("candidate_id")
        for item in data.get("candidate_resolutions", [])
        if isinstance(item, dict)
    }
    pending_observations = [
        (
            f"“{item.get('exact_quote', '')}”"
            "（看起来像可观察事件，但当前规则不能可靠分类；"
            "人工确认前不进入事实层。）"
        )
        for item in data.get("unclassified_observation_candidates", [])
        if isinstance(item, dict)
        and item.get("status") == "pending_confirmation"
        and item.get("input_id") == data.get("current_input_id")
        and item.get("id") not in resolved_candidate_ids
    ]
    resolved_observations: list[str] = []
    for resolution in data.get("candidate_resolutions", []):
        if not isinstance(resolution, dict):
            continue
        candidate = candidates_by_id.get(resolution.get("candidate_id"), {})
        candidate_quote = str(candidate.get("exact_quote", ""))
        resolution_quote = str(resolution.get("exact_quote", ""))
        if resolution.get("resolution_type") == "user_rejected":
            resolved_observations.append(
                f"“{candidate_quote}”后来被用户明确否认；依据："
                f"“{resolution_quote}”。原候选保留用于审计，未进入事实层。"
            )
        elif resolution.get("resolution_type") == "user_confirmed":
            resolved_observations.append(
                f"“{candidate_quote}”后来被用户明确确认；依据："
                f"“{resolution_quote}”。这只记录用户的后续确认，"
                "仍未自动进入事实层。"
            )
    unknowns = [item.get("text", "") for item in data.get("unknowns", []) if item.get("status", "open") == "open"]

    evidence_lines: list[str] = []
    evidence_by_id = {item.get("id"): item for item in data.get("evidence", [])}
    claims_by_id = {item.get("id"): item for item in data.get("claims", [])}
    legacy_evidence_ids = _legacy_epoch_ids(data, "evidence_ids")
    legacy_claim_ids = _legacy_epoch_ids(data, "claim_ids")
    linked_evidence_ids: set[str] = set()
    limitations_rendered: set[str] = set()
    for link in data.get("evidence_links", []):
        evidence_item = evidence_by_id.get(link.get("evidence_ref"), {})
        claim = claims_by_id.get(link.get("proposition_id"), {})
        evidence_quote = str(evidence_item.get("exact_quote", ""))
        claim_quote = str(claim.get("exact_quote", ""))
        if not evidence_quote or not claim_quote:
            continue
        evidence_ref = link.get("evidence_ref")
        if isinstance(evidence_ref, str):
            linked_evidence_ids.add(evidence_ref)
        limitation_texts = [
            LIMITATION_HUMAN_TEXT[item]
            for item in evidence_item.get("limitations", [])
            if item in LIMITATION_HUMAN_TEXT
        ]
        limitation_suffix = ""
        if (
            isinstance(evidence_ref, str)
            and evidence_ref not in limitations_rendered
            and limitation_texts
        ):
            limitation_suffix = "（限制：" + "；".join(limitation_texts) + "）"
            limitations_rendered.add(evidence_ref)
        relation = link.get("relation")
        is_legacy_link = (
            evidence_ref in legacy_evidence_ids
            or link.get("proposition_id") in legacy_claim_ids
        )
        if is_legacy_link and relation == "supports" and evidence_quote == claim_quote:
            evidence_lines.append(
                f"“{evidence_quote}”保留为历史版本记录；"
                f"当前版本未重新验证其来源分类或事件真值。{limitation_suffix}"
            )
        elif is_legacy_link and relation == "does_not_establish":
            evidence_lines.append(
                f"历史版本记录中的“{evidence_quote}”未建立“{claim_quote}”。"
                f"{limitation_suffix}"
            )
        elif is_legacy_link and relation == "conflicts":
            evidence_lines.append(
                f"历史版本记录中的“{evidence_quote}”与“{claim_quote}”不一致；"
                f"当前版本未重新核验支持力度。{limitation_suffix}"
            )
        elif is_legacy_link and relation == "supports":
            evidence_lines.append(
                f"历史版本曾把“{evidence_quote}”记录为与“{claim_quote}”一致；"
                f"当前版本未重新核验支持力度。{limitation_suffix}"
            )
        elif relation == "does_not_establish":
            evidence_lines.append(
                f"“{evidence_quote}”本身不能证明“{claim_quote}”。{limitation_suffix}"
            )
        elif relation == "conflicts":
            evidence_lines.append(
                f"“{evidence_quote}”与“{claim_quote}”不一致，会削弱这个解释。{limitation_suffix}"
            )
        elif relation == "supports" and evidence_quote == claim_quote:
            evidence_lines.append(
                f"“{evidence_quote}”支持把这句话保留为当前报告中的记录。{limitation_suffix}"
            )
        elif relation == "supports":
            evidence_lines.append(
                f"“{evidence_quote}”与“{claim_quote}”一致，但仍需结合来源和上下文判断支持力度。{limitation_suffix}"
            )
    for evidence_item in data.get("evidence", []):
        if evidence_item.get("id") in linked_evidence_ids:
            continue
        quote = str(evidence_item.get("exact_quote", ""))
        if quote:
            limitation_texts = [
                LIMITATION_HUMAN_TEXT[item]
                for item in evidence_item.get("limitations", [])
                if item in LIMITATION_HUMAN_TEXT
            ]
            limitation_suffix = (
                "（限制：" + "；".join(limitation_texts) + "）"
                if limitation_texts
                else ""
            )
            if evidence_item.get("id") in legacy_evidence_ids:
                evidence_lines.append(
                    f"“{quote}”是历史版本保留材料；当前版本未重新核验来源分类。"
                    f"{limitation_suffix}"
                )
            else:
                evidence_lines.append(
                    f"“{quote}”可作为待核对材料；来源和完整上下文仍需确认。{limitation_suffix}"
                )
    for hypothesis in data.get("hypotheses", []):
        confidence_label = {
            "low": "低",
            "medium": "中等",
        }.get(hypothesis.get("confidence"), "未确定")
        evidence_lines.append(
            f"工作假设（仅因用户明确要求，当前置信度{confidence_label}）："
            f"{hypothesis.get('text')}。支持信号："
            f"{'; '.join(HYPOTHESIS_SIGNAL_TEXT.get(item, item) for item in hypothesis.get('support_signals', []))}。"
            f"削弱信号："
            f"{'; '.join(HYPOTHESIS_SIGNAL_TEXT.get(item, item) for item in hypothesis.get('weakening_signals', []))}。"
            f"退出条件：{HYPOTHESIS_SIGNAL_TEXT.get(hypothesis.get('exit_condition'), hypothesis.get('exit_condition'))}。"
        )
    discriminator = data.get("discriminator")
    if isinstance(discriminator, dict):
        evidence_lines.append(f"优先核对：{discriminator.get('question', '')}")

    actions = [
        ACTION_CATALOG.get(item.get("action_type"), {}).get("text", "")
        for item in data.get("actions", [])
    ]
    decisions = [
        DECISION_CATALOG.get(item, "") for item in data.get("user_decisions", [])
    ]
    sections = [
        ("## 1. 可观察事实", _bullet(facts, "当前没有可进入事实层的内容。")),
        (
            "## 1A. 相关人员的直接表态（不等同于客观事实）",
            _bullet(
                direct_statements,
                "当前没有可绑定到说话语境的直接表态。",
            ),
        ),
        (
            "## 1B. 待确认的观察（未进入事实层）",
            _bullet(pending_observations, "当前没有待人工确认的观察。"),
        ),
        (
            "## 1C. 历史版本保留项（未按当前规则重新验证）",
            _bullet(legacy_claims, "当前没有历史版本保留项。"),
        ),
        ("## 2. 用户明确表达的感受和体验", _bullet(feelings, "未明确。")),
        ("## 3. 用户当前的解释", _bullet(interpretations, "未明确。")),
        ("## 4. 尚未验证的动机推断", _bullet(motives, "未发现独立的动机推断。")),
        ("## 5. 当前未知", _bullet(unknowns, "当前没有额外未知项。")),
        ("## 6. 能区分不同解释的证据", _bullet(evidence_lines, "尚未建立可区分的证据。")),
        ("## 7. 不依赖猜中动机也能采取的下一步行动", _bullet(actions, "暂不行动，先补充可观察信息。")),
        ("## 8. 最终仍由用户决定的部分", _bullet(decisions, "最终决定仍由用户作出。")),
    ]
    if superseded_positions:
        sections.append(
            (
                "## 已被明确更正的历史表态",
                _bullet(superseded_positions, ""),
            )
        )
    if retracted_stories:
        sections.append(
            (
                "## 已被用户明确撤回的历史解释",
                _bullet(retracted_stories, ""),
            )
        )
    if resolved_observations:
        sections.append(
            (
                "## 已解决的历史待确认观察",
                _bullet(resolved_observations, ""),
            )
        )
    return "\n\n".join(f"{heading}\n\n{body}" for heading, body in sections) + "\n"


def make_draft(input_text: str, case_id: str, mode: str) -> dict[str, Any]:
    if mode == "auto":
        if detect_immediate_risk(input_text):
            mode = "safety"
        elif parse_pure_transform_task(input_text) is not None:
            mode = "passthrough"
        else:
            mode = "standard"
    elif mode == "standard" and detect_immediate_risk(input_text):
        mode = "safety"
    digest = sha256_text(input_text)
    source_spans = generate_source_spans("I1", input_text)
    observation_candidates = (
        generate_unclassified_observation_candidates(
            "I1", input_text, source_spans
        )
        if mode == "standard"
        else []
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "skill_version": SKILL_VERSION,
        "case_id": case_id,
        "revision": 1,
        "previous_case_sha256": None,
        "mode": mode,
        "current_input_id": "I1",
        "input_sha256": digest,
        "inputs": [{"id": "I1", "text": input_text, "sha256": digest}],
        "source_spans": source_spans,
        "unclassified_observation_candidates": observation_candidates,
        "candidate_resolutions": [],
        "claims": [],
        "evidence": [],
        "evidence_links": [],
        "unknowns": [],
        "hypotheses": [],
        "hypothesis_request": None,
        "discriminator": None,
        "actions": [],
        "user_decisions": [],
        "safety": {"risk_signals": []},
        "change_log": [],
    }


def start_update(
    previous: dict[str, Any],
    input_text: str,
    mode: str = "auto",
    *,
    legacy_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if mode not in {"auto", "safety"}:
        raise ValueError("update mode must be auto or safety")
    previous_pair = _casefile_version_pair(previous)
    if (
        previous_pair not in SUPPORTED_VERSION_PAIRS
        or _validation_profile_for_pair(previous_pair) is None
    ):
        raise ValueError("unsupported previous version pair")
    if (previous_pair, CURRENT_VERSION_PAIR) not in VERSION_MIGRATION_EDGES:
        raise ValueError("unsupported previous-to-current migration edge")
    if previous_pair in MIGRATABLE_VERSION_PAIRS:
        receipt_errors = _legacy_receipt_validation_errors(
            previous, legacy_receipt
        )
        if receipt_errors:
            raise ValueError(receipt_errors[0]["code"])
    elif legacy_receipt is not None:
        raise ValueError("LEGACY_RECEIPT_UNEXPECTED")
    current = copy.deepcopy(previous)
    current["schema_version"] = SCHEMA_VERSION
    current["skill_version"] = SKILL_VERSION
    legacy_epoch = _legacy_epoch_from_previous(previous)
    if legacy_epoch is not None:
        current["legacy_epoch"] = legacy_epoch
    existing_ids = {item.get("id") for item in current.get("inputs", []) if isinstance(item, dict)}
    counter = 1
    while f"I{counter}" in existing_ids:
        counter += 1
    input_id = f"I{counter}"
    digest = sha256_text(input_text)
    current["revision"] = int(previous.get("revision", 0)) + 1
    current["previous_case_sha256"] = canonical_sha256(previous)
    current["current_input_id"] = input_id
    current["input_sha256"] = digest
    current.setdefault("inputs", []).append({"id": input_id, "text": input_text, "sha256": digest})
    next_span_number = len(current.get("source_spans", [])) + 1
    new_source_spans = generate_source_spans(
        input_id, input_text, next_span_number
    )
    current.setdefault("source_spans", []).extend(new_source_spans)
    current["change_log"] = []
    if mode == "safety" or detect_immediate_risk(input_text):
        current["mode"] = "safety"
    candidates = current.setdefault("unclassified_observation_candidates", [])
    resolutions = current.setdefault("candidate_resolutions", [])
    if current.get("mode") == "standard":
        resolutions.extend(
            generate_candidate_resolutions(
                input_id,
                input_text,
                new_source_spans,
                list(previous.get("unclassified_observation_candidates", [])),
                list(previous.get("candidate_resolutions", [])),
                len(resolutions) + 1,
            )
        )
        candidates.extend(
            generate_unclassified_observation_candidates(
                input_id,
                input_text,
                new_source_spans,
                len(candidates) + 1,
            )
        )
    return current


def diff_casefiles(
    previous: dict[str, Any],
    current: dict[str, Any],
    *,
    legacy_receipt: dict[str, Any] | None = None,
) -> dict[str, Any]:
    errors = validate_casefile(
        current,
        previous=previous,
        legacy_receipt=(
            legacy_receipt
            if _casefile_version_pair(previous) in MIGRATABLE_VERSION_PAIRS
            else None
        ),
    )
    if errors:
        return {"valid": False, "error_count": len(errors), "errors": errors}

    def ids(data: dict[str, Any], field: str) -> set[str]:
        return {item.get("id") for item in data.get(field, []) if isinstance(item, dict)}

    previous_claims = {item.get("id"): item for item in previous.get("claims", []) if isinstance(item, dict)}
    current_claims = {item.get("id"): item for item in current.get("claims", []) if isinstance(item, dict)}
    changed_statuses = []
    for item_id in sorted(set(previous_claims) & set(current_claims)):
        old = previous_claims[item_id].get("epistemic_status")
        new = current_claims[item_id].get("epistemic_status")
        if old != new:
            changed_statuses.append({"claim_id": item_id, "from": old, "to": new})
    return {
        "valid": True,
        "previous_case_sha256": canonical_sha256(previous),
        "current_case_sha256": canonical_sha256(current),
        "revision_from": previous.get("revision"),
        "revision_to": current.get("revision"),
        "added_inputs": sorted(ids(current, "inputs") - ids(previous, "inputs")),
        "added_claims": sorted(ids(current, "claims") - ids(previous, "claims")),
        "added_evidence": sorted(ids(current, "evidence") - ids(previous, "evidence")),
        "changed_claim_statuses": changed_statuses,
        "change_log": current.get("change_log", []),
    }


def validation_receipt(
    artifact_path: Path, data: Any, errors: list[dict[str, str]]
) -> dict[str, Any]:
    artifact_pair = _casefile_version_pair(data)
    return {
        "valid": not errors,
        "error_count": len(errors),
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "artifact_path": str(artifact_path.resolve()),
        "artifact_sha256": sha256_bytes(artifact_path.read_bytes()),
        "casefile_sha256": canonical_sha256(data) if isinstance(data, dict) else None,
        "artifact_version_pair": (
            {
                "schema_version": artifact_pair[0],
                "skill_version": artifact_pair[1],
            }
            if artifact_pair is not None
            else None
        ),
        "validation_profile": _validation_profile_for_pair(artifact_pair),
        "schema_version": SCHEMA_VERSION,
        "validator_version": VALIDATOR_VERSION,
        "errors": errors,
    }


def command_init(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    output_path = Path(args.output)
    if output_path.exists():
        print(json.dumps({"error": "OUTPUT_EXISTS", "path": str(output_path)}, ensure_ascii=False), file=sys.stderr)
        return 2
    draft = make_draft(input_path.read_text(encoding="utf-8"), args.case_id, args.mode)
    atomic_write_json(output_path, draft)
    print(str(output_path.resolve()))
    return 0


def command_start_update(args: argparse.Namespace) -> int:
    history_paths = [Path(item) for item in args.history]
    previous_path = history_paths[-1]
    output_path = Path(args.output)
    if output_path.resolve() in {path.resolve() for path in history_paths}:
        print(json.dumps({"error": "REFUSE_OVERWRITE_HISTORY", "path": str(output_path)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if output_path.exists():
        print(json.dumps({"error": "OUTPUT_EXISTS", "path": str(output_path)}, ensure_ascii=False), file=sys.stderr)
        return 2
    legacy_receipt = (
        read_json(Path(args.legacy_receipt))
        if getattr(args, "legacy_receipt", None)
        else None
    )
    previous: dict[str, Any] | None = None
    for index, history_path in enumerate(history_paths):
        current = read_json(history_path)
        needs_receipt = (
            _casefile_version_pair(current) in MIGRATABLE_VERSION_PAIRS
            or _casefile_version_pair(previous) in MIGRATABLE_VERSION_PAIRS
        )
        history_errors = validate_casefile(
            current,
            previous=previous,
            legacy_receipt=legacy_receipt if needs_receipt else None,
        )
        if history_errors:
            print(
                json.dumps(
                    {
                        "valid": False,
                        "history_index": index,
                        "artifact": str(history_path.resolve()),
                        "error_count": len(history_errors),
                        "errors": history_errors,
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                file=sys.stderr,
            )
            return 1
        previous = current
    assert previous is not None
    current = start_update(
        previous,
        Path(args.input).read_text(encoding="utf-8"),
        mode=args.mode,
        legacy_receipt=(
            legacy_receipt
            if _casefile_version_pair(previous) in MIGRATABLE_VERSION_PAIRS
            else None
        ),
    )
    atomic_write_json(output_path, current)
    print(str(output_path.resolve()))
    return 0


def _resolve_cli_previous(
    data: dict[str, Any],
    history_values: list[str] | None,
    previous_value: str | None,
    legacy_receipt: dict[str, Any] | None = None,
) -> tuple[dict[str, Any] | None, list[dict[str, str]]]:
    revision = data.get("revision")
    if history_values:
        if not isinstance(revision, int) or revision <= 1 or len(history_values) != revision - 1:
            return None, [
                error(
                    "FULL_HISTORY_REQUIRED",
                    "/revision",
                    "history must contain every prior revision from 1 through revision minus 1",
                )
            ]
        previous: dict[str, Any] | None = None
        for index, value in enumerate(history_values):
            history_item = read_json(Path(value))
            needs_receipt = (
                _casefile_version_pair(history_item) in MIGRATABLE_VERSION_PAIRS
                or _casefile_version_pair(previous) in MIGRATABLE_VERSION_PAIRS
            )
            history_errors = validate_casefile(
                history_item,
                previous=previous,
                legacy_receipt=legacy_receipt if needs_receipt else None,
            )
            if history_errors:
                return None, [
                    error(
                        "HISTORY_INVALID",
                        f"/history/{index}",
                        f"prior revision is invalid: {history_errors[0]['code']}",
                    )
                ]
            previous = history_item
        return previous, []
    if previous_value:
        if isinstance(revision, int) and revision > 2:
            return None, [
                error(
                    "FULL_HISTORY_REQUIRED",
                    "/revision",
                    "revision 3 or later must be validated with the complete --history",
                )
            ]
        previous = read_json(Path(previous_value))
        previous_errors = validate_casefile(
            previous,
            previous=None,
            legacy_receipt=(
                legacy_receipt
                if _casefile_version_pair(previous) in MIGRATABLE_VERSION_PAIRS
                else None
            ),
        )
        if previous_errors:
            return None, [
                error(
                    "HISTORY_INVALID",
                    "/history/0",
                    f"root prior revision is invalid: {previous_errors[0]['code']}",
                )
            ]
        return previous, []
    return None, []


def command_validate(args: argparse.Namespace) -> int:
    artifact_path = Path(args.artifact)
    legacy_receipt = (
        read_json(Path(args.legacy_receipt))
        if getattr(args, "legacy_receipt", None)
        else None
    )
    try:
        data = read_json(artifact_path)
    except (OSError, json.JSONDecodeError) as exc:
        errors = [error("JSON_READ_ERROR", "", str(exc))]
        receipt = {
            "valid": False,
            "error_count": 1,
            "validated_at": datetime.now(timezone.utc).isoformat(),
            "artifact_path": str(artifact_path.resolve()),
            "artifact_sha256": sha256_bytes(artifact_path.read_bytes()) if artifact_path.exists() else None,
            "schema_version": SCHEMA_VERSION,
            "validator_version": VALIDATOR_VERSION,
            "errors": errors,
        }
        if args.report:
            atomic_write_json(Path(args.report), receipt)
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 1
    previous, history_errors = _resolve_cli_previous(
        data,
        getattr(args, "history", None),
        args.previous,
        legacy_receipt,
    )
    needs_receipt = (
        _casefile_version_pair(data) in MIGRATABLE_VERSION_PAIRS
        or _casefile_version_pair(previous) in MIGRATABLE_VERSION_PAIRS
    )
    errors = history_errors or validate_casefile(
        data,
        previous=previous,
        legacy_receipt=legacy_receipt if needs_receipt else None,
    )
    receipt = validation_receipt(artifact_path, data, errors)
    if args.report:
        atomic_write_json(Path(args.report), receipt)
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


def command_render(args: argparse.Namespace) -> int:
    artifact_path = Path(args.artifact)
    data = read_json(artifact_path)
    legacy_receipt = (
        read_json(Path(args.legacy_receipt))
        if getattr(args, "legacy_receipt", None)
        else None
    )
    previous, history_errors = _resolve_cli_previous(
        data,
        getattr(args, "history", None),
        args.previous,
        legacy_receipt,
    )
    needs_receipt = (
        _casefile_version_pair(data) in MIGRATABLE_VERSION_PAIRS
        or _casefile_version_pair(previous) in MIGRATABLE_VERSION_PAIRS
    )
    errors = history_errors or validate_casefile(
        data,
        previous=previous,
        legacy_receipt=legacy_receipt if needs_receipt else None,
    )
    if errors:
        print(json.dumps({"valid": False, "error_count": len(errors), "errors": errors}, ensure_ascii=False, indent=2), file=sys.stderr)
        return 1
    try:
        rendered = render_markdown(data)
    except ValueError as exc:
        print(json.dumps({"error": "PASSTHROUGH_NOT_RENDERED", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    if args.output:
        atomic_write(Path(args.output), rendered)
        print(str(Path(args.output).resolve()))
    else:
        print(rendered, end="")
    return 0


def command_diff(args: argparse.Namespace) -> int:
    current = read_json(Path(args.current))
    legacy_receipt = (
        read_json(Path(args.legacy_receipt))
        if getattr(args, "legacy_receipt", None)
        else None
    )
    if current.get("revision", 1) > 2:
        history_values = getattr(args, "history", None)
        previous, history_errors = _resolve_cli_previous(
            current, history_values, None, legacy_receipt
        )
        if history_errors:
            result = {
                "valid": False,
                "error_count": len(history_errors),
                "errors": history_errors,
            }
        elif not history_values or Path(history_values[-1]).resolve() != Path(args.previous).resolve():
            history_error = error(
                "FULL_HISTORY_REQUIRED",
                "/history",
                "the last history item must be the adjacent previous casefile",
            )
            result = {"valid": False, "error_count": 1, "errors": [history_error]}
        else:
            assert previous is not None
            result = diff_casefiles(
                previous, current, legacy_receipt=legacy_receipt
            )
    else:
        previous, history_errors = _resolve_cli_previous(
            current, None, args.previous, legacy_receipt
        )
        if history_errors:
            result = {
                "valid": False,
                "error_count": len(history_errors),
                "errors": history_errors,
            }
        else:
            assert previous is not None
            result = diff_casefiles(
                previous, current, legacy_receipt=legacy_receipt
            )
    content = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        atomic_write(Path(args.output), content)
        print(str(Path(args.output).resolve()))
    else:
        print(content, end="")
    return 0 if result.get("valid") else 1


def runtime_self_test() -> dict[str, Any]:
    compound = "他三次没回就是根本不在乎我。"
    compound_spans = generate_source_spans("I1", compound)
    unseen_tail = "老板取消会议盘算着让我难堪。"
    unseen_tail_spans = generate_source_spans("I1", unseen_tail)
    legal_observation = generate_source_spans("I1", "老板把我的工位搬走了。")[0]
    secondhand_span = generate_source_spans("I1", "据说老板取消了会议。")[0]
    negated_then_fact_spans = generate_source_spans(
        "I1", "老板没有说要开除我，给我发了升职邮件。"
    )
    qualified_text = "他说‘我会留下但只是暂时’。"
    qualified_spans = generate_source_spans("I1", qualified_text)
    truncated_quote = next(
        item
        for item in qualified_spans
        if item.get("quoted") is True and item.get("text") == "我会留下"
    )
    question_text = "他问我：“我会留下吗？”"
    question_span = next(
        item
        for item in generate_source_spans("I1", question_text)
        if item.get("quoted") is True
    )
    retracted_text = "他说“我会留下”，但马上又改口了。"
    retracted_span = next(
        item
        for item in generate_source_spans("I1", retracted_text)
        if item.get("quoted") is True
    )
    possessive_spans = generate_source_spans("I1", "老板回复了我的老板。")
    nested_quote_span = next(
        item
        for item in generate_source_spans(
            "I1", "项目协调员告诉我，老板说“我会留下”。"
        )
        if item.get("quoted") is True
    )
    artifact_fact_span = generate_source_spans(
        "I1", "老板取消了会议，这是系统消息显示的。"
    )[0]
    story_span = {"source_label": "input"}
    cross_entity_relation = _allowed_relation_for_claim_evidence(
        {
            "kind": "interpretation",
            "input_id": "I1",
            "source_span_id": "SP1",
            "exact_quote": "我认为老板在架空我。",
        },
        {
            "input_id": "I1",
            "source_span_id": "SP2",
            "exact_quote": "另一家公司员工连续两次没有被邀请参加项目会。",
        },
    )
    cross_span_safety_inputs = (
        "我胸口，像被巨石压住。",
        "他威胁，今晚要杀我。",
        "他威胁我，今晚让我消失。",
    )
    explicit_label_secondhand = next(
        item
        for item in generate_source_spans(
            "I1", "[我的观察] 据秘书转述，老板取消周会。"
        )
        if item.get("text") == "老板取消周会。"
    )
    past_quote_text = "去年他说：“我会留下”。"
    past_quote_span = next(
        item
        for item in generate_source_spans("I1", past_quote_text)
        if item.get("quoted") is True
    )
    nonasserted_text = "这不足以证明他不爱我。"
    nonasserted_span = generate_source_spans("I1", nonasserted_text)[0]
    coordinated_text = "他既不爱我又是回避型。"
    coordinated_spans = generate_source_spans("I1", coordinated_text)
    injected_source_span = generate_source_spans(
        "I1", "[inferred_secondhand_context] 他不爱我。"
    )[0]
    proxy_text = "我以他的名义回答：“我会离开。”"
    proxy_quote = next(
        item
        for item in generate_source_spans("I1", proxy_text)
        if item.get("quoted") is True
    )
    corner_quote_text = "他说：「他不爱你。」"
    corner_quote_spans = generate_source_spans("I1", corner_quote_text)
    unlabelled_fact_span = generate_source_spans(
        "I1", "老板取消了会议。"
    )[0]
    owner_reset_text = "同事说他很忙，但在我看来他不爱我。"
    owner_reset_span = next(
        item
        for item in generate_source_spans("I1", owner_reset_text)
        if "在我看来" in str(item.get("text", ""))
    )
    artifact_outer_span = generate_source_spans(
        "I1", "录音里他说他不爱我。"
    )[0]
    hearsay_outer_span = next(
        item
        for item in generate_source_spans(
            "I1", "他说，系统显示我的权限取消。"
        )
        if item.get("text") == "系统显示我的权限取消。"
    )
    governed_scope_text = "单凭这两次没回不足以证明他不爱我。"
    governed_scope_spans = generate_source_spans("I1", governed_scope_text)
    correlative_story_text = "他不仅不爱我还准备离开我。"
    correlative_story_spans = generate_source_spans("I1", correlative_story_text)
    nonfactive_cleft_text = "我担心的是老板取消了会议。"
    nonfactive_cleft_span = next(
        item
        for item in generate_source_spans("I1", nonfactive_cleft_text)
        if "老板取消了会议" in str(item.get("text", ""))
    )
    compound_label_text = "[二手｜邮件] 他说：“我会离开。”"
    compound_label_quote = next(
        item
        for item in generate_source_spans("I1", compound_label_text)
        if item.get("quoted") is True
    )
    account_proxy_text = "我用他的账号回复：“我会离开。”"
    account_proxy_quote = next(
        item
        for item in generate_source_spans("I1", account_proxy_text)
        if item.get("quoted") is True
    )
    fresh_hearsay_text = "据内部消息，老板在架空我。"
    fresh_hearsay_span = next(
        item
        for item in generate_source_spans("I1", fresh_hearsay_text)
        if "老板在架空我" in str(item.get("text", ""))
    )
    relay_label_text = "[转告｜邮件] 他说：“我会离开。”"
    relay_label_quote = next(
        item
        for item in generate_source_spans("I1", relay_label_text)
        if item.get("quoted") is True
    )
    proxy_sender_text = "我替他发来原话：“我会离开。”"
    proxy_sender_quote = next(
        item
        for item in generate_source_spans("I1", proxy_sender_text)
        if item.get("quoted") is True
    )
    net_hearsay_text = "网传老板在架空我。"
    net_hearsay_span = generate_source_spans("I1", net_hearsay_text)[0]
    postfix_relay_text = "他说：“我会离开。”，这是邮件转述的。"
    postfix_relay_quote = next(
        item
        for item in generate_source_spans("I1", postfix_relay_text)
        if item.get("quoted") is True
    )
    conclusion_owner_text = "朋友说他忙，不过这是我得出的结论：他不爱我。"
    conclusion_owner_span = next(
        item
        for item in generate_source_spans("I1", conclusion_owner_text)
        if "这是我得出的结论" in str(item.get("text", ""))
    )
    suo_cleft_text = "我所担心的是老板取消了会议。"
    suo_cleft_span = next(
        item
        for item in generate_source_spans("I1", suo_cleft_text)
        if "老板取消了会议" in str(item.get("text", ""))
    )
    relay_position_text = "中间人代为带话，老板表示：“我会留下。”"
    relay_position_quote = next(
        item
        for item in generate_source_spans("I1", relay_position_text)
        if item.get("quoted") is True
    )
    owner_coordination_text = "同事说老板讨厌我，而且我本人认为老板是在排挤我。"
    owner_coordination_span = next(
        item
        for item in generate_source_spans("I1", owner_coordination_text)
        if "而且我本人认为" in str(item.get("text", ""))
    )
    feeling_reset_text = "即便同事说老板讨厌我，我很难过。"
    feeling_reset_span = next(
        item
        for item in generate_source_spans("I1", feeling_reset_text)
        if item.get("text") == "我很难过。"
    )
    proxy_future_text = "我念出同事的原话：“老板明天会取消会议”，不过我本人认为老板是在排挤我。"
    proxy_future_carrier = next(
        item
        for item in generate_source_spans("I1", proxy_future_text)
        if item.get("quoted") is not True and "我念出" in str(item.get("text", ""))
    )
    transform_future_text = "请把同事说的“老板明天会取消会议”整理成项目符号，但我认为他在排挤我。"
    transform_future_carrier = next(
        item
        for item in generate_source_spans("I1", transform_future_text)
        if item.get("quoted") is not True and "整理成项目符号" in str(item.get("text", ""))
    )
    explicit_interpretation_text = "我将这解读为自己被排除在决策之外。"
    explicit_interpretation_span = generate_source_spans(
        "I1", explicit_interpretation_text
    )[0]
    conditional_consequent_text = (
        "如果同事说老板会开掉我，我注定会失败。我今天收到邮件。"
    )
    conditional_consequent_span = next(
        item
        for item in generate_source_spans("I1", conditional_consequent_text)
        if item.get("text") == "我注定会失败。"
    )
    prediction_owner_text = "同事说老板会开掉我，但我注定会失败。"
    prediction_owner_span = next(
        item
        for item in generate_source_spans("I1", prediction_owner_text)
        if item.get("text") == "我注定会失败。"
    )
    temporal_feeling_text = "同事说老板会开掉我，但我现在很害怕。"
    temporal_feeling_span = next(
        item
        for item in generate_source_spans("I1", temporal_feeling_text)
        if item.get("text") == "我现在很害怕。"
    )
    corrective_quote_text = "他没有说“我会离开”，而是说“我会留下”。"
    corrective_quote_span = next(
        item
        for item in generate_source_spans("I1", corrective_quote_text)
        if item.get("quoted") is True
    )
    excluded_quote_text = "他说的是“我会留下”，而非“我会离开”。"
    excluded_quote_spans = [
        item
        for item in generate_source_spans("I1", excluded_quote_text)
        if item.get("quoted") is True
    ]
    feeling_prediction_text = "我很焦虑并且我永远不会成功。"
    feeling_prediction_spans = generate_source_spans(
        "I1", feeling_prediction_text
    )
    recipient_feeling_text = "我回复了消息。我现在对老板说：“我很害怕。”"
    recipient_feeling_quote = next(
        item
        for item in generate_source_spans("I1", recipient_feeling_text)
        if item.get("quoted") is True
    )
    epistemic_complement_text = (
        "我回复了消息。同事说老板要开除我，但我认为，他只是故意吓我。"
    )
    epistemic_complement_span = next(
        item
        for item in generate_source_spans("I1", epistemic_complement_text)
        if item.get("text") == "他只是故意吓我。"
    )
    meta_negation_text = "这不等于他故意排挤我。"
    meta_negation_span = generate_source_spans("I1", meta_negation_text)[0]
    only_if_story_text = "只有在他再次回复消息时，我才会认为他在乎我。"
    only_if_story_span = next(
        item
        for item in generate_source_spans("I1", only_if_story_text)
        if item.get("text") == "我才会认为他在乎我。"
    )
    only_if_quote_text = "只有老板说：“我决定离开”，我才辞职。"
    only_if_quote_span = next(
        item
        for item in generate_source_spans("I1", only_if_quote_text)
        if item.get("quoted") is True
    )
    coordinated_event_text = "他回复了消息，而且他参加了会议。"
    coordinated_event_span = next(
        item
        for item in generate_source_spans("I1", coordinated_event_text)
        if item.get("text") == "而且他参加了会议。"
    )
    only_quantifier_text = "只有一个事实，我看见他回复了消息。"
    only_quantifier_draft = make_draft(
        only_quantifier_text, "self-test-only-quantifier", "standard"
    )
    only_quantifier_span = next(
        item
        for item in only_quantifier_draft["source_spans"]
        if item.get("text") == "我看见他回复了消息。"
    )
    meta_contrast_text = "这不等于他故意排挤我但我认为他确实在排挤我。"
    meta_contrast_spans = generate_source_spans("I1", meta_contrast_text)
    nested_recipient_text = "我对老板说他说：“我决定离开。”"
    nested_recipient_quote = next(
        item
        for item in generate_source_spans("I1", nested_recipient_text)
        if item.get("quoted") is True
    )
    nearest_user_speech_text = "老板问我，我回答：“我会离开。”"
    nearest_user_speech_quote = next(
        item
        for item in generate_source_spans("I1", nearest_user_speech_text)
        if item.get("quoted") is True
    )
    secretary_proxy_text = "秘书代老板对我说：“我会离开。”"
    secretary_proxy_quote = next(
        item
        for item in generate_source_spans("I1", secretary_proxy_text)
        if item.get("quoted") is True
    )
    er_owner_text = "同事告诉我，他不爱我，而我认为他是回避型。"
    er_owner_span = next(
        item
        for item in generate_source_spans("I1", er_owner_text)
        if "我认为他是回避型" in str(item.get("text", ""))
    )
    uncomma_correction_text = "我不是说他不爱我而是说他是回避型。"
    uncomma_correction_spans = generate_source_spans(
        "I1", uncomma_correction_text
    )
    uncomma_only_if_text = "只有老板说：“你不用参加。”我才离开。"
    uncomma_only_if_quote = next(
        item
        for item in generate_source_spans("I1", uncomma_only_if_text)
        if item.get("quoted") is True
    )
    ideographic_actions_text = "老板取消了会议、删除了文档。"
    ideographic_action_spans = generate_source_spans(
        "I1", ideographic_actions_text
    )
    quoted_update_text = "他后来回复原话是‘手机送修，刚拿回来’，并发来当天维修单。"
    quoted_update_action_spans = [
        item
        for item in generate_source_spans("I2", quoted_update_text)
        if item.get("quoted") is True
        and derive_observation_type(str(item.get("text", "")), item) is not None
    ]
    attributed_update_text = "他回复：‘手机送修，刚拿回来’。"
    attributed_update_span = next(
        item
        for item in generate_source_spans("I2", attributed_update_text)
        if item.get("quoted") is True
        and item.get("text") == "手机送修，刚拿回来"
    )

    def safety_types_are_anchored(text: str) -> bool:
        draft = make_draft(text, "self-test-safety-anchor", "auto")
        full_types = expected_safety_signal_types(text)
        inputs = {
            item["id"]: item
            for item in draft["inputs"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        spans = {
            item["id"]: item
            for item in draft["source_spans"]
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        required = _required_safety_span_types(spans, inputs, "I1")
        return bool(full_types) and {item[1] for item in required} == full_types

    def has_current_user_feeling(text: str) -> bool:
        return any(
            _is_current_user_explicit_feeling(
                str(span.get("text", "")), span, text
            )
            for span in generate_source_spans("I1", text)
        )

    def full_quote_kind(text: str) -> str | None:
        quote_spans = [
            item
            for item in generate_source_spans("I1", text)
            if item.get("quoted") is True
        ]
        if not quote_spans:
            return None
        span = max(quote_spans, key=lambda item: len(str(item.get("text", ""))))
        return derive_claim_kind_for_span(str(span.get("text", "")), span, text)

    def malformed_version_is_rejected(field: str, value: Any) -> bool:
        draft = make_draft(
            "只翻译成英文：你好。", "self-test-version-pair", "passthrough"
        )
        draft[field] = value
        return "VERSION_PAIR_UNSUPPORTED" in {
            item.get("code") for item in validate_casefile(draft)
        }

    forged_legacy = make_draft(
        "只翻译成英文：你好。",
        "self-test-forged-legacy",
        "passthrough",
    )
    forged_legacy["schema_version"] = "3.0.0"
    forged_legacy["skill_version"] = "4.0.1"
    forged_legacy_receipt = {
        "valid": True,
        "error_count": 0,
        "errors": [],
        "casefile_sha256": canonical_sha256(forged_legacy),
        "schema_version": "3.0.0",
        "validator_version": "4.0.1",
    }
    forged_legacy_codes = {
        item.get("code")
        for item in validate_casefile(
            forged_legacy,
            legacy_receipt=forged_legacy_receipt,
        )
    }
    trusted_legacy_attestations, trusted_legacy_registry_error = (
        _trusted_legacy_attestations()
    )

    checks = {
        "compound_story_split": compound
        not in {item.get("text") for item in compound_spans},
        "finite_story_tail_rejected": derive_observation_type(unseen_tail) is None,
        "future_participation_not_observation": derive_observation_type(
            "他会参加会议。"
        )
        is None,
        "future_deadline_not_observation": derive_observation_type(
            "老板周五前完成交接。"
        )
        is None,
        "core_silence_observation_supported": derive_observation_type(
            "他看了消息六个小时没回。"
        )
        == "communication_event",
        "finite_observation_prefix_preserved": any(
            derive_observation_type(str(item.get("text", "")), item)
            == "participation_or_schedule_event"
            for item in unseen_tail_spans
        ),
        "artifact_label_not_semantics": derive_observation_type(
            "他品行恶劣。", {"source_label": "截图"}
        )
        is None,
        "negative_report_tail_rejected": derive_observation_type(
            "她没有解释原因足以看出她不在乎我。"
        )
        is None,
        "common_observation_supported": derive_observation_type(
            legal_observation["text"], legal_observation
        )
        == "task_or_action_event",
        "quoted_update_actions_are_not_mandatory_facts": (
            [item.get("text") for item in quoted_update_action_spans]
            == ["手机送修，", "刚拿回来"]
            and not any(
                _is_required_current_observation_span(item)
                for item in quoted_update_action_spans
            )
        ),
        "quoted_account_is_attributed_without_becoming_fact": (
            derive_claim_kind_for_span(
                attributed_update_span["text"],
                attributed_update_span,
                attributed_update_text,
            )
            == "attributed_statement"
            and not _is_required_current_observation_span(attributed_update_span)
        ),
        "quote_attribution_outer_scope_is_fail_closed": (
            all(
                full_quote_kind(text) != "attributed_statement"
                for text in (
                    "他说：‘手机究竟有没有送修。’",
                    "据同事说，他原话是：‘手机送修，刚拿回来’。",
                    "朋友发截图说这是他的原话：‘手机送修，刚拿回来’。",
                    "朋友替他说：‘手机送修，刚拿回来’。",
                    "案例中他说：‘手机送修，刚拿回来’。",
                    "我梦见他回复：‘手机送修，刚拿回来’。",
                    "语法分析：他说‘手机送修，刚拿回来’。",
                    "他说同事告诉他：‘手机送修，刚拿回来’。",
                    "他说：‘手机送修，刚拿回来’，接着表示这句话不作数。",
                )
            )
            and full_quote_kind("他回复：‘手机送修，刚拿回来’。")
            == "attributed_statement"
            and full_quote_kind("去年他说：‘手机送修，刚拿回来’。")
            == "attributed_statement"
        ),
        "artifact_nonreal_and_nonhuman_quote_carriers_fail_closed": all(
            full_quote_kind(text) != "attributed_statement"
            for text in (
                "[截屏] 老板说：‘手机送修，刚拿回来’。",
                "培训材料里老板说：‘手机送修，刚拿回来’。",
                "童话里老板说：‘手机送修，刚拿回来’。",
                "天气预报说：‘明天有雨’。",
                "研究论文说：‘收入增长’。",
            )
        ),
        "conditional_and_future_quotes_are_not_asserted_speech": all(
            full_quote_kind(text) != "attributed_statement"
            for text in (
                "倘若他到场，他会说：‘手机送修，刚拿回来’。",
                "即使他到场，他也会说：‘手机送修，刚拿回来’。",
                "一旦他到场，他就会说：‘手机送修，刚拿回来’。",
                "他下周会说：‘手机送修，刚拿回来’。",
            )
        ),
        "markdown_secondhand_scope_is_preserved": _expected_source_type_for_span(
            next(
                item
                for item in generate_source_spans(
                    "I1",
                    "同事告诉我：\n- 老板说：‘手机送修，刚拿回来’。",
                )
                if item.get("quoted") is True
            )
        )
        == "secondhand",
        "direct_reset_requires_user_recipient": (
            full_quote_kind(
                "据同事转述，但老板当面告诉秘书：‘手机送修，刚拿回来’。"
            )
            != "attributed_statement"
            and full_quote_kind(
                "据说项目要停，但老板当面告诉我：‘手机送修，刚拿回来’。"
            )
            == "attributed_statement"
        ),
        "nonverbatim_and_unconfirmed_quotes_fail_closed": all(
            full_quote_kind(text) != "attributed_statement"
            for text in (
                "[非原话] 老板说：‘手机送修，刚拿回来’。",
                "[意译] 老板说：‘手机送修，刚拿回来’。",
                "[待确认] 老板说：‘手机送修，刚拿回来’。",
                "我用自己的话概括，老板说：‘手机送修，刚拿回来’。",
            )
        ),
        "format_plus_truth_request_is_not_passthrough": parse_pure_transform_task(
            "整理：老板说他会开除我；请核实来源。"
        )
        is None,
        "expanded_document_future_summary_attribution_fails_closed": all(
            full_quote_kind(text) != "attributed_statement"
            for text in (
                "白皮书里老板说：‘手机送修，刚拿回来’。",
                "备忘录里老板说：‘手机送修，刚拿回来’。",
                "电子表格里老板说：‘手机送修，刚拿回来’。",
                "过两天老板会说：‘手机送修，刚拿回来’。",
                "等他到场，老板会说：‘手机送修，刚拿回来’。",
                "假使他到场，老板会说：‘手机送修，刚拿回来’。",
                "[大意] 老板说：‘手机送修，刚拿回来’。",
                "[摘要] 老板说：‘手机送修，刚拿回来’。",
            )
        ),
        "expanded_format_epistemic_second_tasks_are_not_passthrough": all(
            parse_pure_transform_task(text) is None
            for text in (
                "整理：老板说他会开除我；看看这是不是实话。",
                "整理：老板说他会开除我；确认一下消息靠不靠谱。",
                "整理：老板说他会开除我；查一下是否可信。",
                "整理：老板说他会开除我；告诉我这话能不能信。",
                "整理：老板说他会开除我；分析一下这话的来路。",
                "整理：老板说他会开除我；看看他到底想干嘛。",
            )
        ),
        "open_attribution_grammar_fails_closed": all(
            full_quote_kind(text) != "attributed_statement"
            for text in (
                "Excel表里老板说：‘手机送修，刚拿回来’。",
                "工作日志里老板说：‘手机送修，刚拿回来’。",
                "[摘录] 老板说：‘手机送修，刚拿回来’。",
                "按我的理解概括，老板说：‘手机送修，刚拿回来’。",
                "等他到场之后，老板会说：‘手机送修，刚拿回来’。",
            )
        ),
        "cross_language_epistemic_second_tasks_are_not_passthrough": all(
            parse_pure_transform_task(text) is None
            for text in (
                "整理：老板说他会开除我；顺带看看这话是否经得起推敲。",
                "Put this sentence in a Markdown blockquote: My boss said he would fire me; "
                "assess whether the claim is credible.",
            )
        ),
        "legacy_registry_is_packaged_and_nonempty": (
            trusted_legacy_registry_error is None
            and len(trusted_legacy_attestations) == 17
        ),
        "self_forged_legacy_receipt_is_rejected": (
            "LEGACY_ARTIFACT_NOT_ATTESTED" in forged_legacy_codes
        ),
        "migratable_version_claim_matches_attested_pairs": (
            MIGRATABLE_VERSION_PAIRS
            == {("3.0.0", "4.0.0"), ("3.0.0", "4.0.1")}
        ),
        "malformed_version_pair_is_structurally_rejected": all(
            malformed_version_is_rejected(field, value)
            for field, value in (
                ("schema_version", []),
                ("schema_version", {}),
                ("skill_version", []),
                ("skill_version", {}),
            )
        ),
        "story_not_observation": derive_observation_type(
            "根本不在乎我。", story_span
        )
        is None,
        "interpretation_fails_closed": cross_entity_relation
        == {"does_not_establish"},
        "secondhand_source_preserved": _expected_source_type_for_span(
            secondhand_span
        )
        == "secondhand",
        "secondhand_limitation_available": "secondhand" in LIMITATION_CODES,
        "qualified_quote_not_truncated": _direct_quote_scope_error(
            qualified_text, truncated_quote
        )
        == (
            "DIRECT_QUOTE_SCOPE_TRUNCATED",
            "stated positions must preserve the complete visible quotation, including qualifications",
        ),
        "question_quote_not_position": _direct_quote_scope_error(
            question_text, question_span
        )
        == (
            "DIRECT_QUOTE_NOT_ASSERTED",
            "an interrogative quote is not the speaker's stated position",
        ),
        "retracted_quote_not_current": _direct_quote_scope_error(
            retracted_text, retracted_span
        )
        == (
            "DIRECT_QUOTE_SUPERSEDED",
            "a visibly retracted or corrected quote is not a current stated position",
        ),
        "possessive_recipient_not_truncated": "老板回复了我"
        not in {item.get("text") for item in possessive_spans},
        "nested_reporting_is_secondhand": _expected_source_type_for_span(
            nested_quote_span
        )
        == "secondhand",
        "postfixed_channel_is_artifact": _expected_source_type_for_span(
            artifact_fact_span
        )
        == "unverified_artifact",
        "imagined_quote_not_generated": not any(
            item.get("quoted") is True
            for item in generate_source_spans("I1", "我希望他说‘我会留下’。")
        ),
        "other_person_feeling_not_self_report": not is_explicit_feeling(
            "他对我很生气。"
        ),
        "self_feeling_preserved": is_explicit_feeling("我很生气。"),
        "possessive_feeling_subject_rejected": not is_explicit_feeling(
            "我女儿害怕。"
        ),
        "textual_secondhand_overrides_direct_label": _expected_source_type_for_span(
            explicit_label_secondhand
        )
        == "secondhand",
        "unquoted_pronoun_report_is_secondhand": _expected_source_type_for_span(
            next(
                item
                for item in generate_source_spans(
                    "I1", "他说，系统显示我的权限取消。"
                )
                if item.get("text") == "系统显示我的权限取消。"
            )
        )
        == "secondhand",
        "past_quote_not_current": _direct_quote_has_past_scope(
            past_quote_text, past_quote_span
        ),
        "nonasserted_story_scope_preserved": derive_claim_kind_for_span(
            nonasserted_span["text"], nonasserted_span, nonasserted_text
        )
        is None,
        "coordinated_story_layers_preserved": [
            derive_claim_kind_for_span(item["text"], item, coordinated_text)
            for item in coordinated_spans
        ]
        == ["motive_inference", "identity_claim"],
        "external_source_token_cannot_inject_context": (
            _expected_source_type_for_span(injected_source_span) is None
        ),
        "proxy_quote_not_direct_position": _direct_quote_scope_error(
            proxy_text, proxy_quote
        )
        is not None,
        "corner_quote_carrier_not_story": all(
            derive_claim_kind_for_span(item["text"], item, corner_quote_text)
            is None
            for item in corner_quote_spans
            if item.get("quoted") is not True
        ),
        "format_operation_routes_passthrough": make_draft(
            "只改格式：“他不爱我。”", "self-test-format", "auto"
        ).get("mode")
        == "passthrough",
        "unlabelled_fact_source_is_derived": (
            _expected_source_type_for_claim_span(
                unlabelled_fact_span, "observable_fact"
            )
            == "user_direct_observation"
        ),
        "first_person_owner_resets_hearsay": (
            _expected_source_type_for_claim_span(
                owner_reset_span,
                derive_claim_kind_for_span(
                    owner_reset_span["text"],
                    owner_reset_span,
                    owner_reset_text,
                ),
            )
            == "user_report"
        ),
        "outer_provenance_order_is_preserved": (
            _expected_source_type_for_span(artifact_outer_span)
            == "unverified_artifact"
            and _expected_source_type_for_span(hearsay_outer_span)
            == "secondhand"
        ),
        "governing_nonassertion_scope_is_preserved": all(
            derive_claim_kind_for_span(item["text"], item, governed_scope_text)
            is None
            for item in governed_scope_spans
        ),
        "correlative_story_layers_are_split": [
            derive_claim_kind_for_span(item["text"], item, correlative_story_text)
            for item in correlative_story_spans
        ]
        == ["motive_inference", "prediction"],
        "nonfactive_cleft_does_not_create_fact": derive_observation_type(
            nonfactive_cleft_span["text"], nonfactive_cleft_span
        )
        is None,
        "postfix_format_operation_routes_passthrough": make_draft(
            "“他不爱我。”，请只改格式。", "self-test-postfix-format", "auto"
        ).get("mode")
        == "passthrough",
        "named_actor_prediction_is_visible": derive_claim_kind_for_span(
            generate_source_spans("I1", "小李准备离开。")[0]["text"],
            generate_source_spans("I1", "小李准备离开。")[0],
            "小李准备离开。",
        )
        == "prediction",
        "passive_quantity_observation_is_visible": derive_observation_type(
            "约会被她取消了两次。"
        )
        == "participation_or_schedule_event",
        "compound_secondhand_label_is_conservative": _expected_source_type_for_span(
            compound_label_quote
        )
        == "secondhand",
        "account_proxy_quote_is_not_direct": _direct_quote_scope_error(
            account_proxy_text, account_proxy_quote
        )
        is not None,
        "fresh_hearsay_frame_is_secondhand": _expected_source_type_for_claim_span(
            fresh_hearsay_span,
            derive_claim_kind_for_span(
                fresh_hearsay_span["text"], fresh_hearsay_span, fresh_hearsay_text
            ),
        )
        == "secondhand",
        "relay_label_cannot_be_upgraded_by_carrier": _expected_source_type_for_span(
            relay_label_quote
        )
        == "secondhand",
        "proxy_message_sender_is_not_direct": _direct_quote_scope_error(
            proxy_sender_text, proxy_sender_quote
        )
        is not None,
        "net_hearsay_frame_is_secondhand": _expected_source_type_for_claim_span(
            net_hearsay_span,
            derive_claim_kind_for_span(
                net_hearsay_span["text"], net_hearsay_span, net_hearsay_text
            ),
        )
        == "secondhand",
        "postfix_relay_revokes_direct_quote": (
            _expected_source_type_for_span(postfix_relay_quote) == "secondhand"
            and _direct_quote_scope_error(postfix_relay_text, postfix_relay_quote)
            is not None
        ),
        "conclusion_owner_resets_hearsay": _expected_source_type_for_claim_span(
            conclusion_owner_span,
            derive_claim_kind_for_span(
                conclusion_owner_span["text"],
                conclusion_owner_span,
                conclusion_owner_text,
            ),
        )
        == "user_report",
        "directly_negated_determination_is_nonasserted": derive_claim_kind_for_span(
            generate_source_spans("I1", "我暂时不认定他是回避型。")[0]["text"],
            generate_source_spans("I1", "我暂时不认定他是回避型。")[0],
            "我暂时不认定他是回避型。",
        )
        is None,
        "subjectless_coordinated_prediction_is_visible": [
            derive_claim_kind_for_span(item["text"], item, "他既不爱我，也不会再回来。")
            for item in generate_source_spans("I1", "他既不爱我，也不会再回来。")
        ]
        == ["motive_inference", "prediction"],
        "suo_cleft_complement_is_nonfactive": derive_observation_type(
            suo_cleft_span["text"], suo_cleft_span
        )
        is None,
        "relayed_position_is_secondhand": (
            _expected_source_type_for_span(relay_position_quote) == "secondhand"
        ),
        "passive_physical_change_becomes_candidate": bool(
            make_draft(
                "老板取消了会议。随后我的蓝色工牌被剪成两半。",
                "self-test-passive-candidate",
                "standard",
            ).get("unclassified_observation_candidates")
        ),
        "visible_state_change_becomes_candidate": bool(
            make_draft(
                "老板取消了会议。接着会议室门口多了一把铜挂锁。",
                "self-test-state-candidate",
                "standard",
            ).get("unclassified_observation_candidates")
        ),
        "epistemic_owner_with_discourse_adverb_is_story": any(
            derive_claim_kind_for_span(item["text"], item, "我由此认定他是在给我下马威。")
            == "interpretation"
            for item in generate_source_spans("I1", "我由此认定他是在给我下马威。")
        ),
        "epistemic_view_frame_is_story": any(
            derive_claim_kind_for_span(item["text"], item, "在我看来这是一场敲山震虎。")
            == "interpretation"
            for item in generate_source_spans("I1", "在我看来这是一场敲山震虎。")
        ),
        "mixed_translation_second_task_is_not_pure": parse_pure_transform_task(
            "翻译成英文：他没回消息。另问：他这样做是不是故意惩罚我？"
        )
        is None,
        "rhetorical_denial_is_nonasserted": all(
            derive_claim_kind_for_span(item["text"], item, "谁能说这就证明老板会开掉我？")
            is None
            for item in generate_source_spans("I1", "谁能说这就证明老板会开掉我？")
        ),
        "concessive_antecedent_is_nonasserted": all(
            derive_claim_kind_for_span(item["text"], item, "即便老板会开掉我，也不能据此说他恨我。")
            is None
            for item in generate_source_spans("I1", "即便老板会开掉我，也不能据此说他恨我。")
        ),
        "negated_artifact_story_is_nonasserted": derive_claim_kind_for_span(
            generate_source_spans("I1", "不是截图显示老板讨厌我，而是我本人认为老板是在排挤我。")[0]["text"],
            generate_source_spans("I1", "不是截图显示老板讨厌我，而是我本人认为老板是在排挤我。")[0],
            "不是截图显示老板讨厌我，而是我本人认为老板是在排挤我。",
        )
        is None,
        "coordinated_first_person_owner_resets_source": (
            _expected_source_type_for_claim_span(
                owner_coordination_span,
                derive_claim_kind_for_span(
                    owner_coordination_span["text"],
                    owner_coordination_span,
                    owner_coordination_text,
                ),
            )
            == "user_report"
        ),
        "hope_scope_does_not_assert_story": all(
            derive_claim_kind_for_span(item["text"], item, "我希望同事说老板讨厌我。")
            is None
            for item in generate_source_spans("I1", "我希望同事说老板讨厌我。")
        ),
        "first_person_feeling_resets_source": (
            _expected_source_type_for_span(feeling_reset_span) is None
            and _is_current_user_explicit_feeling(
                feeling_reset_span["text"], feeling_reset_span, feeling_reset_text
            )
        ),
        "proxy_carrier_does_not_inherit_future_quote": derive_claim_kind_for_span(
            proxy_future_carrier["text"], proxy_future_carrier, proxy_future_text
        )
        is None,
        "transform_carrier_does_not_inherit_future_quote": derive_claim_kind_for_span(
            transform_future_carrier["text"],
            transform_future_carrier,
            transform_future_text,
        )
        is None,
        "explicit_interpretation_frame_is_story": derive_claim_kind_for_span(
            explicit_interpretation_span["text"],
            explicit_interpretation_span,
            explicit_interpretation_text,
        )
        == "interpretation",
        "ordinary_lock_event_becomes_candidate": any(
            item.get("exact_quote") == "老板锁上了办公室的门。"
            for item in make_draft(
                "老板取消了会议。老板锁上了办公室的门。",
                "self-test-lock-candidate",
                "standard",
            ).get("unclassified_observation_candidates", [])
        ),
        "interrogative_story_is_not_required_as_assertion": not any(
            item.get("code") == "USER_STORY_CLAIM_MISSING"
            for item in validate_casefile(
                make_draft(
                    "老板取消了会议。他是不是回避型？",
                    "self-test-story-question",
                    "standard",
                )
            )
        ),
        "conditional_consequent_is_nonasserted": (
            "inferred_nonasserted_context"
            in {
                part.strip()
                for part in re.split(
                    r"[｜|]", str(conditional_consequent_span.get("source_label", ""))
                )
            }
            and derive_claim_kind_for_span(
                conditional_consequent_span["text"],
                conditional_consequent_span,
                conditional_consequent_text,
            )
            is None
        ),
        "first_person_prediction_resets_hearsay": (
            _expected_source_type_for_span(prediction_owner_span) is None
            and derive_claim_kind_for_span(
                prediction_owner_span["text"],
                prediction_owner_span,
                prediction_owner_text,
            )
            == "prediction"
        ),
        "temporal_first_person_feeling_resets_hearsay": (
            _expected_source_type_for_span(temporal_feeling_span) is None
            and _is_current_user_explicit_feeling(
                temporal_feeling_span["text"],
                temporal_feeling_span,
                temporal_feeling_text,
            )
        ),
        "affirmative_corrective_quote_is_position": (
            corrective_quote_span.get("text") == "我会留下"
            and derive_claim_kind_for_span(
                corrective_quote_span["text"],
                corrective_quote_span,
                corrective_quote_text,
            )
            == "stated_position"
        ),
        "excluded_quote_is_not_a_position": [
            derive_claim_kind_for_span(
                item["text"], item, excluded_quote_text
            )
            for item in excluded_quote_spans
        ]
        == ["stated_position", None],
        "feeling_and_prediction_are_atomic": (
            [item.get("text") for item in feeling_prediction_spans]
            == ["我很焦虑", "并且我永远不会成功。"]
            and _is_current_user_explicit_feeling(
                feeling_prediction_spans[0]["text"],
                feeling_prediction_spans[0],
                feeling_prediction_text,
            )
            and derive_claim_kind_for_span(
                feeling_prediction_spans[1]["text"],
                feeling_prediction_spans[1],
                feeling_prediction_text,
            )
            == "prediction"
        ),
        "relationship_degradation_is_story": derive_claim_kind_for_span(
            generate_source_spans("I1", "我把这个信号看成关系已经降级。")[0]["text"],
            generate_source_spans("I1", "我把这个信号看成关系已经降级。")[0],
            "我把这个信号看成关系已经降级。",
        )
        == "interpretation",
        "user_to_recipient_quote_keeps_user_speaker": (
            _quoted_speaker_role(
                recipient_feeling_text,
                recipient_feeling_quote["start"],
                recipient_feeling_quote["end"],
            )
            == "user"
            and _is_current_user_explicit_feeling(
                recipient_feeling_quote["text"],
                recipient_feeling_quote,
                recipient_feeling_text,
            )
        ),
        "epistemic_complement_resets_hearsay": (
            _expected_source_type_for_span(epistemic_complement_span)
            != "secondhand"
            and derive_claim_kind_for_span(
                epistemic_complement_span["text"],
                epistemic_complement_span,
                epistemic_complement_text,
            )
            == "motive_inference"
        ),
        "meta_negation_does_not_assert_story": derive_claim_kind_for_span(
            meta_negation_span["text"], meta_negation_span, meta_negation_text
        )
        is None,
        "only_if_scope_is_nonasserted": (
            derive_claim_kind_for_span(
                only_if_story_span["text"],
                only_if_story_span,
                only_if_story_text,
            )
            is None
            and _direct_quote_scope_error(
                only_if_quote_text, only_if_quote_span
            )
            is not None
        ),
        "coordinated_observation_event_is_visible": derive_observation_type(
            coordinated_event_span["text"], coordinated_event_span
        )
        == "participation_or_schedule_event",
        "only_quantifier_does_not_create_conditional_scope": (
            "inferred_nonasserted_context"
            not in {
                part.strip()
                for part in re.split(
                    r"[｜|]", str(only_quantifier_span.get("source_label", ""))
                )
            }
            and only_quantifier_span["id"]
            in {
                item.get("source_span_id")
                for item in only_quantifier_draft.get(
                    "unclassified_observation_candidates", []
                )
            }
        ),
        "meta_negation_contrast_preserves_affirmative_story": (
            lambda kinds: len([kind for kind in kinds if kind is not None]) == 1
            and next(kind for kind in kinds if kind is not None)
            in {"interpretation", "motive_inference"}
        )(
            [
                derive_claim_kind_for_span(
                    item["text"], item, meta_contrast_text
                )
                for item in meta_contrast_spans
            ]
        ),
        "nested_recipient_frame_is_not_user_speech": _quoted_speaker_role(
            nested_recipient_text,
            nested_recipient_quote["start"],
            nested_recipient_quote["end"],
        )
        != "user",
        "nearest_user_speech_frame_wins": _quoted_speaker_role(
            nearest_user_speech_text,
            nearest_user_speech_quote["start"],
            nearest_user_speech_quote["end"],
        )
        == "user",
        "secretary_proxy_is_not_direct_position": _direct_quote_scope_error(
            secretary_proxy_text, secretary_proxy_quote
        )
        is not None,
        "er_owner_resets_hearsay": (
            derive_claim_kind_for_span(
                er_owner_span["text"], er_owner_span, er_owner_text
            )
            == "identity_claim"
            and _expected_source_type_for_claim_span(
                er_owner_span, "identity_claim"
            )
            == "user_report"
        ),
        "uncomma_corrective_story_is_visible": [
            derive_claim_kind_for_span(
                item["text"], item, uncomma_correction_text
            )
            for item in uncomma_correction_spans
        ].count("identity_claim")
        == 1,
        "uncomma_only_if_quote_is_nonasserted": _direct_quote_scope_error(
            uncomma_only_if_text, uncomma_only_if_quote
        )
        is not None,
        "ideographic_parallel_actions_are_visible": [
            derive_observation_type(item["text"], item)
            for item in ideographic_action_spans
        ]
        == ["participation_or_schedule_event", "task_or_action_event"],
        "postfix_bold_operation_routes_passthrough": make_draft(
            "“他不爱我”，请只加粗。", "self-test-postfix-bold", "auto"
        ).get("mode")
        == "passthrough",
        "explicit_future_date_is_prediction": derive_claim_kind_for_span(
            generate_source_spans("I1", "公司下个月裁掉我。")[0]["text"],
            generate_source_spans("I1", "公司下个月裁掉我。")[0],
            "公司下个月裁掉我。",
        )
        == "prediction",
        "fronted_quantity_passive_is_observation": derive_observation_type(
            "两次约会均被她取消。"
        )
        == "participation_or_schedule_event",
        "combined_current_boundary_supported": derive_stated_position_type(
            "我不想再继续约会，也不会参加周六的见面。"
        )
        == "decision_or_boundary",
        "labelled_role_evidence_is_bidirectional": (
            "supports"
            in _allowed_relation_for_claim_evidence(
                {
                    "kind": "interpretation",
                    "source_ref": "P1",
                    "exact_quote": "公司已经决定架空我。",
                },
                {
                    "source_ref": "E1",
                    "exact_quote": "我连续三次没有被邀请参加决策会。",
                },
            )
            and "conflicts"
            in _allowed_relation_for_claim_evidence(
                {
                    "kind": "interpretation",
                    "source_ref": "P1",
                    "exact_quote": "公司已经决定架空我。",
                },
                {
                    "source_ref": "E2",
                    "exact_quote": "经理书面确认我的岗位保持不变，并保留我的预算审批职责。",
                },
            )
        ),
        "fact_after_negated_report_preserved": any(
            item.get("text") == "给我发了升职邮件。"
            and derive_observation_type(str(item.get("text", "")), item)
            == "communication_event"
            for item in negated_then_fact_spans
        ),
        "safety_positive": detect_immediate_risk("他威胁明天让我消失。"),
        "safety_typed_detector_alignment": all(
            detect_immediate_risk(text) == bool(expected_safety_signal_types(text))
            for text in (
                "我现在要杀他。",
                "他发消息说今晚要杀我。",
                "这不是电影，他现在持刀堵在我门外。",
                "我准备从桥上跳下去。",
                "我想打他电话。",
            )
        ),
        "benign_phone_not_harm": not detect_immediate_risk("我想打他电话。"),
        "safety_negation_scope": detect_immediate_risk("没有人能阻止我自杀。"),
        "safety_negation": not detect_immediate_risk("我没有胸痛，也没有呼吸困难。"),
        "safety_negated_death_wish": not detect_immediate_risk("我不想死。"),
        "safety_third_party_jump_ownership": expected_safety_signal_types(
            "朋友说他现在想跳楼。"
        )
        == {"third_party_self_harm_risk"},
        "safety_reported_current_user_ownership": expected_safety_signal_types(
            "朋友说我现在想跳楼。"
        )
        == {"self_harm_risk"},
        "safety_negated_third_party_jump": all(
            not expected_safety_signal_types(text)
            for text in (
                "朋友说他现在不想跳楼。",
                "朋友发来消息：\u201c我现在不想跳楼\u201d。",
            )
        ),
        "safety_third_party_death_wish_ownership": expected_safety_signal_types(
            "朋友发消息说：\u201c我不想活了。\u201d"
        )
        == {"third_party_self_harm_risk"},
        "safety_third_party_double_negation_ownership": (
            expected_safety_signal_types(
                "朋友发消息说：\u201c我并非不想自杀。\u201d"
            )
            == {"third_party_self_harm_risk"}
            and expected_safety_signal_types("我并非不想自杀。")
            == {"self_harm_risk"}
        ),
        "reaction_feeling_owner_reset": all(
            has_current_user_feeling(text)
            for text in (
                "同事说老板取消了会议，我听完很难过。",
                "她发完消息后，我反而安心了。",
                "我收到消息后很难过。",
            )
        ),
        "reaction_feeling_external_scope_preserved": all(
            not has_current_user_feeling(text)
            for text in (
                "同事说我听完很难过。",
                "他认为我反而安心了。",
                "[同事转述：] 我听完很难过。",
            )
        ),
        "safety_negated_chest_pain": not detect_immediate_risk("我的胸口不痛。"),
        "safety_compound_negated_medical": not detect_immediate_risk(
            "我胸口不痛，也没有呼吸困难。"
        ),
        "safety_negated_key_access": not detect_immediate_risk("前任没有我家钥匙。"),
        "safety_benign_knife_use": not detect_immediate_risk("拿刀切菜。"),
        "safety_benign_laughter_idiom": not detect_immediate_risk(
            "我笑得喘不过气。"
        ),
        "safety_curly_apostrophe_medical": expected_safety_signal_types(
            "I can’t breathe."
        )
        == {"medical_emergency"},
        "safety_transform_quote_scoped": not detect_immediate_risk(
            "请分析这句台词：“我想死”。"
        ),
        "safety_unquoted_second_task_preserved": "explicit_threat"
        in expected_safety_signal_types(
            "请翻译成英文：hello，同时告诉我怎么办，我前任正在门外拿刀。"
        ),
        "question_suffix_not_observation": not any(
            derive_observation_type(str(item.get("text", "")), item) is not None
            for item in generate_source_spans("I1", "老板取消了会议吗？")
        ),
        "truth_denial_not_observation": not any(
            derive_observation_type(str(item.get("text", "")), item) is not None
            for item in generate_source_spans("I1", "老板取消了会议并不属实。")
        ),
        "truth_denial_synonym_not_observation": not any(
            derive_observation_type(str(item.get("text", "")), item) is not None
            for item in generate_source_spans("I1", "老板取消周会纯属谣言。")
        ),
        "safety_anchor_coverage_cross_span": all(
            safety_types_are_anchored(text) for text in cross_span_safety_inputs
        ),
        "safety_reality_override": all(
            "explicit_threat" in expected_safety_signal_types(text)
            for text in (
                "这不是电影台词，他今晚真的要杀我。",
                "别当成剧本，我前任已经拿着刀到楼下了。",
            )
        ),
        "safety_affirmative_reality_reset": all(
            expected_safety_signal_types(text)
            for text in (
                "这是一部电影。回到现实，我胸痛。",
                "这是小说。实际情况是前任持刀堵门。",
            )
        ),
        "safety_negated_reality_stays_nonreal": all(
            not expected_safety_signal_types(text)
            for text in (
                "这并非现实里的事，而是剧本。角色拿刀杀我。",
                "上面是电影台词。电影中的现实里，前任持刀堵门。",
            )
        ),
        "safety_english_negation": all(
            not expected_safety_signal_types(text)
            for text in (
                "He isn't going to kill me.",
                "He is not going to kill me.",
                "I don't have chest pain.",
                "I do not have chest pain.",
            )
        ),
        "safety_resolved_history": all(
            not expected_safety_signal_types(text)
            for text in (
                "我十年前想死，现在生活很好。",
                "我昨天胸痛，但医生确认已经好了。",
                "法院期限昨天已经过了。",
            )
        ),
        "safety_event_scoped_resolution": all(
            signal_type in expected_safety_signal_types(text)
            for text, signal_type in (
                (
                    "我去年有过自伤念头，现在法律期限已经结束，但我此刻确实有自伤想法。",
                    "self_harm_risk",
                ),
                (
                    "去年我曾胸痛，现在法律期限已经结束，但我目前确实胸痛。",
                    "medical_emergency",
                ),
                (
                    "朋友去年说过要自杀，现在法律期限已经结束，但朋友此刻说马上要自杀。",
                    "third_party_self_harm_risk",
                ),
                (
                    "旧聊天里他威胁过我，现在法律期限已经结束，但他此刻就在我门口。",
                    "explicit_threat",
                ),
            )
        ),
        "safety_current_risk_polarity": (
            "self_harm_risk"
            in expected_safety_signal_types("我不是没有自伤想法，我现在确实有。")
            and "self_harm_risk"
            in expected_safety_signal_types("我没有自伤念头，不过现在确实有。")
            and not expected_safety_signal_types(
                "去年情绪失控时刀在手边，现在刀已经收走且没有风险。"
            )
            and not expected_safety_signal_types("我从未想过伤害我的室友。")
        ),
        "safety_translation_instruction_boundary": (
            is_pure_translation_task(
                "Please translate into English: 我现在想伤害自己。"
            )
            and not expected_safety_signal_types(
                "Please translate into English: 我现在想伤害自己。"
            )
            and not is_pure_translation_task(
                "English translation is inaccurate. I will hurt my roommate right now."
            )
            and "harm_to_others_risk"
            in expected_safety_signal_types(
                "English translation is inaccurate. I will hurt my roommate right now."
            )
        ),
        "safety_legal_event_scope": (
            "urgent_legal_risk"
            in expected_safety_signal_types(
                "法院要求我两小时内提交材料，否则失去上诉权。"
            )
            and "urgent_legal_risk"
            in expected_safety_signal_types("法院文件显示今天是紧迫期限。")
            and not expected_safety_signal_types("法院通知我下个月是提交期限。")
            and "urgent_legal_risk"
            not in expected_safety_signal_types(
                "今天我要提交课程材料。上周参观了法院。否则我会失去上诉权这个词怎么翻译？"
            )
        ),
        "safety_uncertain_recovery_not_suppressed": "self_harm_risk"
        in expected_safety_signal_types(
            "三年前我想轻生，如今可能已康复且安全。"
        ),
        "safety_uncertain_medical_resolution_not_suppressed": "medical_emergency"
        in expected_safety_signal_types(
            "两年前我胸痛，现在医生没说没事。"
        ),
        "safety_connected_transform_operands_scoped": not expected_safety_signal_types(
            "请把“杀了你”和“拿刀”都翻译成英文。"
        ),
        "safety_transform_tail_preserved": "explicit_threat"
        in expected_safety_signal_types(
            "请翻译“hello”，另外，他发消息说“今晚杀了你”。"
        ),
        "negated_report_quantifiers_not_generated": all(
            not any(
                item.get("quoted") is True
                for item in generate_source_spans("I1", text)
            )
            for text in (
                "并没有人说过“我会留下”。",
                "没人真正说过“我会留下”。",
                "我没听他说过“我会留下”。",
            )
        ),
        "safety_meta_quote_scoped": all(
            not expected_safety_signal_types(text)
            for text in (
                "请分析这句台词：“我想死”。",
                "请把“前任有我家钥匙”改成被动句。",
                "请检查这段正则是否匹配“我想死”。",
            )
        ),
        "safety_high_confidence_family_matrix": all(
            signal_type in expected_safety_signal_types(text)
            for text, signal_type in (
                (
                    "Do not format this: he is pointing a gun at me right now.",
                    "explicit_threat",
                ),
                (
                    "This is real: Maya just texted me that she will die tonight and stopped answering.",
                    "third_party_self_harm_risk",
                ),
                (
                    "A stranger used a copied key to enter my apartment and is inside while I hide in the bathroom.",
                    "access_or_location_exposure",
                ),
                (
                    "This is not a JSON exercise. I planted a bomb in the lobby and the timer is running.",
                    "harm_to_others_risk",
                ),
                (
                    "I cannot promise that I won't hurt myself tonight; the pills are beside me.",
                    "self_harm_risk",
                ),
                (
                    "It is not true that no one is bleeding; one person is losing blood quickly right now.",
                    "medical_emergency",
                ),
                (
                    "Immigration officers are detaining me now and say I will be removed tonight; I cannot reach counsel or family.",
                    "urgent_legal_risk",
                ),
                (
                    "There is immediate danger: my partner is strangling me now.",
                    "other_immediate_risk",
                ),
            )
        ),
        "safety_resolved_lifecycle_matrix": all(
            not expected_safety_signal_types(text)
            for text in (
                "上个月他持刀威胁过我。警方已处理，他目前被拘留，我现在安全，也没有新的接触。",
                "两年前我有过自杀念头，后来持续治疗。现在没有自伤念头，也没有计划。",
                "I had severe chest pain yesterday, was evaluated in the ER, and the doctor discharged me. I have no symptoms now.",
                "去年有人泄露过我的住址。我已经搬家并更换门锁，此后没有人跟踪或联系我。",
                "假设有人说“我今晚要死”，应该如何区分修辞、玩笑和真实风险？",
            )
        ),
        "passthrough_finite_transform_ownership": (
            parse_pure_transform_task("只翻译成英文：门关着。")
            == {"kind": "translation", "payload": "门关着"}
            and parse_pure_transform_task(
                "把小说台词翻成英文：“我今晚要自杀。”"
            )
            == {"kind": "translation", "payload": "“我今晚要自杀。”"}
            and parse_pure_transform_task(
                "Return valid JSON with one field named quote: 'I planted a bomb in the lobby.'"
            )
            == {
                "kind": "formatting",
                "payload": "'I planted a bomb in the lobby.'",
            }
            and not expected_safety_signal_types(
                "Return valid JSON with one field named quote: 'I planted a bomb in the lobby.'"
            )
            and parse_pure_transform_task(
                "Translate this later; first, my ex is outside my door with a knife saying, 'I will kill you tonight.'"
            )
            is None
            and "explicit_threat"
            in expected_safety_signal_types(
                "Translate this later; first, my ex is outside my door with a knife saying, 'I will kill you tonight.'"
            )
        ),
        "safety_event_local_polarity": (
            all(
                not expected_safety_signal_types(text)
                for text in (
                    "He is not pointing a gun at me right now.",
                    "My partner is not strangling me now.",
                    "No one is losing blood quickly right now.",
                    "The bailiff says we do not have to leave in ten minutes.",
                    "I can promise I won't hurt myself tonight.",
                )
            )
            and "explicit_threat"
            in expected_safety_signal_types(
                "He said he is not carrying a gun, but he is pointing a gun at me right now."
            )
        ),
        "safety_clause_local_slot_binding": (
            all(
                not expected_safety_signal_types(text)
                for text in (
                    "My ex is outside my door for an agreed property pickup. A kitchen knife is on the table. I told the smart speaker to kill the lights.",
                    "The bailiff is at my door for a scheduled document delivery. I will leave in ten minutes for class.",
                    "My brother says he is driving to his boss's house now for dinner. I will shoot a photo there, and the antique rifle remains locked at the museum.",
                    "厨房有做饭产生的烟雾。幻灯片里的火焰图案正在往楼梯方向蔓延。",
                    "快递员发来我家门口照片，确认包裹已经放在门口。",
                )
            )
            and "explicit_threat"
            in expected_safety_signal_types(
                "The locksmith opened the stuck door and left. My ex is forcing my door open right now."
            )
            and "access_or_location_exposure"
            in expected_safety_signal_types(
                "The courier delivered a package earlier. A stranger is following me to my front door now."
            )
        ),
        "auto_entrypoint_passthrough_alignment": all(
            make_draft(text, "self-test-auto-route", "auto").get("mode")
            == "passthrough"
            for text in (
                "只翻译成英文：门关着。",
                "把这句话改成项目符号：她只回复了一个‘嗯’。",
                "Return valid JSON with one field named quote: 'I planted a bomb in the lobby.'",
            )
        ),
        "safety_roleplay_scope_matrix": (
            not expected_safety_signal_types(
                "桌游角色扮演设定：我的角色被绑在仓库里。请给这个角色取名。"
            )
            and "other_immediate_risk"
            in expected_safety_signal_types(
                "桌游角色扮演设定：我的角色被绑在仓库里。回到现实，我现在真的被人绑在仓库里。"
            )
        ),
    }
    return {"valid": all(checks.values()), "checks": checks}


def command_self_test(args: argparse.Namespace) -> int:
    result = runtime_self_test()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["valid"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Create and enforce versioned fact-story separation casefiles."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create a revision 1 draft with a verified input hash")
    init_parser.add_argument("--input", required=True, help="UTF-8 text file containing the current user material")
    init_parser.add_argument("--output", required=True, help="new JSON casefile path")
    init_parser.add_argument("--case-id", required=True)
    init_parser.add_argument("--mode", choices=["auto", *sorted(MODES)], default="auto")
    init_parser.set_defaults(handler=command_init)

    update_parser = subparsers.add_parser("start-update", help="start a new immutable revision after validating the full oldest-to-newest history")
    update_parser.add_argument("--history", nargs="+", required=True, help="ordered casefiles from revision 1 through the current revision")
    update_parser.add_argument("--input", required=True, help="UTF-8 text file containing only the new material")
    update_parser.add_argument("--output", required=True)
    update_parser.add_argument("--mode", choices=["auto", "safety"], default="auto")
    update_parser.add_argument(
        "--legacy-receipt",
        help="hash-bound validation receipt required when history starts on a legacy profile",
    )
    update_parser.set_defaults(handler=command_start_update)

    validate_parser = subparsers.add_parser("validate", help="validate structure, anchors, evidence limits, actions, and history")
    validate_parser.add_argument("artifact")
    validate_history = validate_parser.add_mutually_exclusive_group()
    validate_history.add_argument("--previous", help="adjacent prior revision, accepted only for revision 2")
    validate_history.add_argument("--history", nargs="+", help="all prior revisions in oldest-to-newest order")
    validate_parser.add_argument("--report", help="write a JSON validation receipt atomically")
    validate_parser.add_argument(
        "--legacy-receipt",
        help="external receipt for a legacy root or its first current migration",
    )
    validate_parser.set_defaults(handler=command_validate)

    render_parser = subparsers.add_parser("render", help="render validated standard or safety casefile to Markdown")
    render_parser.add_argument("artifact")
    render_history = render_parser.add_mutually_exclusive_group()
    render_history.add_argument("--previous", help="adjacent prior revision, accepted only for revision 2")
    render_history.add_argument("--history", nargs="+", help="all prior revisions in oldest-to-newest order")
    render_parser.add_argument("--output")
    render_parser.add_argument(
        "--legacy-receipt",
        help="external receipt for a legacy root or its first current migration",
    )
    render_parser.set_defaults(handler=command_render)

    diff_parser = subparsers.add_parser("diff", help="validate and summarize a revision delta")
    diff_parser.add_argument("previous")
    diff_parser.add_argument("current")
    diff_parser.add_argument("--history", nargs="+", help="all prior revisions through previous for revision 3+")
    diff_parser.add_argument("--output")
    diff_parser.add_argument(
        "--legacy-receipt",
        help="external receipt for a legacy root or its first current migration",
    )
    diff_parser.set_defaults(handler=command_diff)

    self_test_parser = subparsers.add_parser(
        "self-test", help="run packaged-runtime epistemic and safety invariants"
    )
    self_test_parser.set_defaults(handler=command_self_test)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.handler(args))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"error": "RUNTIME_ERROR", "message": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
