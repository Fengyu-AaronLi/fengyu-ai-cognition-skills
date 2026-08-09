from __future__ import annotations

import copy
import concurrent.futures
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "dpbp"


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def request_hash(raw: str) -> str:
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def source(raw: str, quote: str) -> dict[str, object]:
    start = raw.index(quote)
    return {"start": start, "end": start + len(quote), "quote": quote}


def envelope(
    raw: str,
    *,
    request_id: str = "fixture-request",
    domain: str = "general",
    deliverable_clear: bool,
    inputs_sufficient: bool,
    success_criteria_clear: bool,
    decisive_unknowns: bool,
    high_risk_value_decision: bool,
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "request_id": request_id,
        "original_request": raw,
        "signals": {
            "domain": domain,
            "deliverable_clear": deliverable_clear,
            "inputs_sufficient": inputs_sufficient,
            "success_criteria_clear": success_criteria_clear,
            "decisive_unknowns": decisive_unknowns,
            "high_risk_value_decision": high_risk_value_decision,
        },
    }


def gate_receipt(
    request_envelope: dict[str, object],
    *,
    mode: str,
    rule: str,
    priority_index: int,
    resources: list[str],
) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "request_id": request_envelope["request_id"],
        "request_sha256": request_hash(request_envelope["original_request"]),
        "domain": request_envelope["signals"]["domain"],
        "mode": mode,
        "execution_allowed": mode == "execute",
        "resources": resources,
        "trace": {
            "priority_index": priority_index,
            "rule": rule,
            "source": "runtime/routes.json",
        },
    }


def valid_define_spec() -> dict[str, object]:
    raw = "怎么用 AI 提高效率？老板让我今天交方案，我最常做的是整理访谈记录。"
    request_envelope = envelope(
        raw,
        request_id="DPBP-002",
        domain="ai_efficiency",
        deliverable_clear=False,
        inputs_sufficient=False,
        success_criteria_clear=False,
        decisive_unknowns=True,
        high_risk_value_decision=False,
    )
    return {
        "schema_version": "1.0",
        "request_id": "DPBP-002",
        "request_sha256": request_hash(raw),
        "request_envelope": request_envelope,
        "gate_receipt": gate_receipt(
            request_envelope,
            mode="define",
            rule="decisive_unknowns",
            priority_index=1,
            resources=["references/core.md", "references/playbooks/ai-efficiency.md"],
        ),
        "mode": "define",
        "domain": "ai_efficiency",
        "status": "provisional",
        "original_request": raw,
        "original_question": "怎么用 AI 提高效率？",
        "desired_outcome": {
            "status": "unknown",
            "value": "当前未知",
            "sources": [],
        },
        "proxy_problem": {
            "status": "hypothesis",
            "value": "当前问题可能把采用 AI 当成了改善结果的代理问题。",
            "sources": [source(raw, "用 AI 提高效率")],
        },
        "hidden_assumptions": [
            {
                "status": "hypothesis",
                "value": "采用 AI 本身会改善尚未定义的效率结果。",
                "sources": [source(raw, "用 AI 提高效率")],
            }
        ],
        "known_facts": [
            {
                "value": "老板要求今天交方案。",
                "source": source(raw, "老板让我今天交方案"),
            },
            {
                "value": "用户常做整理访谈记录这条流程。",
                "source": source(raw, "我最常做的是整理访谈记录"),
            },
        ],
        "decisive_unknowns": [
            {
                "id": "u1",
                "category": "desired_outcome",
                "value": "要改善的现实结果是什么？",
                "changes": "改变成功口径。",
            },
            {
                "id": "u2",
                "category": "current_bottleneck",
                "value": "当前损失发生在哪一步？",
                "changes": "改变是否需要 AI 以及干预位置。",
            },
            {
                "id": "u3",
                "category": "measurement_source",
                "value": "现有记录如何衡量改善？",
                "changes": "改变验证方式。",
            },
        ],
        "hard_constraints": [
            {
                "value": "今天需要提交方案。",
                "constraint_type": "deadline",
                "source": source(raw, "今天交方案"),
            }
        ],
        "value_tradeoffs": [],
        "success_evidence": [],
        "failure_conditions": ["没有定位真实流程损失，却开始列工具或实施方案。"],
        "change_evidence": ["真实流程记录显示可观察的等待、返工、错误或遗漏。"],
        "rewritten_problem": "在一条近期真实流程中，哪一步造成了可观察损失，什么已有记录能确认它？",
        "next_test": {
            "action": "选择用户自己近期反复发生的一条流程，读取一个已有样本，记录耗时、等待、返工、错误或遗漏后停止。",
            "evidence_sought": "损失发生在哪一步，以及是否存在可观察基线。",
            "reversible": True,
            "low_cost": True,
            "stops_before_solution": True,
            "action_type": "evidence_collection",
            "evidence_only": True,
            "solution_commitment": "none",
        },
        "questions": [
            {
                "id": "q1",
                "question": "你真正要改善哪项交付结果？",
                "changes": "确定成功口径。",
                "addresses": ["u1"],
            },
            {
                "id": "q2",
                "question": "当前最慢或最容易返工的是哪一步？",
                "changes": "确定瓶颈。",
                "addresses": ["u2"],
            },
            {
                "id": "q3",
                "question": "你已有哪种记录可以比较变化？",
                "changes": "确定验证证据。",
                "addresses": ["u3"],
            },
        ],
        "decision_owner": "user",
        "execution_allowed": False,
    }


def valid_high_risk_spec() -> dict[str, object]:
    raw = "我该不该辞职？别问我那么多，你就根据这几句话告诉我。"
    request_envelope = envelope(
        raw,
        request_id="DPBP-001",
        domain="career",
        deliverable_clear=False,
        inputs_sufficient=False,
        success_criteria_clear=False,
        decisive_unknowns=True,
        high_risk_value_decision=True,
    )
    return {
        "schema_version": "1.0",
        "request_id": "DPBP-001",
        "request_sha256": request_hash(raw),
        "request_envelope": request_envelope,
        "gate_receipt": gate_receipt(
            request_envelope,
            mode="defer_to_user",
            rule="high_risk_value_decision",
            priority_index=0,
            resources=[
                "references/core.md",
                "references/high-risk.md",
                "references/playbooks/career-exit.md",
            ],
        ),
        "mode": "defer_to_user",
        "domain": "career",
        "status": "provisional",
        "original_request": raw,
        "original_question": "我该不该辞职？",
        "desired_outcome": {"status": "unknown", "value": "当前未知", "sources": []},
        "proxy_problem": {
            "status": "hypothesis",
            "value": "二选一问题可能代理了对工作现状、替代路径和可承受风险的判断。",
            "sources": [source(raw, "该不该辞职")],
        },
        "hidden_assumptions": [
            {
                "status": "hypothesis",
                "value": "几句话足以支持不可逆职业决定。",
                "sources": [source(raw, "根据这几句话告诉我")],
            }
        ],
        "known_facts": [
            {"value": "用户要求直接结论。", "source": source(raw, "你就根据这几句话告诉我")}
        ],
        "decisive_unknowns": [
            {
                "id": "u1",
                "category": "financial_capacity",
                "value": "收入中断承受力如何？",
                "changes": "改变财务风险边界。",
            },
            {
                "id": "u2",
                "category": "alternatives",
                "value": "现实替代选择有哪些？",
                "changes": "改变路径可逆性。",
            },
            {
                "id": "u3",
                "category": "health_status",
                "value": "健康与工作状态如何？",
                "changes": "改变安全优先级。",
            },
            {
                "id": "u4",
                "category": "desired_outcome",
                "value": "用户真正想改变的现实结果是什么？",
                "changes": "改变职业问题的目标。",
            },
            {
                "id": "u5",
                "category": "risk_tolerance",
                "value": "哪些不确定性和损失不可承受？",
                "changes": "改变可接受的风险边界。",
            },
            {
                "id": "u6",
                "category": "decision_target",
                "value": "当前到底要决定辞职、谈条件还是先排除健康风险？",
                "changes": "改变本次真正需要决定的对象。",
            },
        ],
        "hard_constraints": [],
        "value_tradeoffs": [
            {"value": "稳定、健康、成长和机会成本如何排序。", "decision_owner": "user"}
        ],
        "success_evidence": [],
        "failure_conditions": ["模型替用户给出职业二选一结论。"],
        "change_evidence": ["用户补充现实条件并亲自确定不可接受的代价。"],
        "rewritten_problem": "在不替用户拍板的前提下，哪些现实条件和价值排序会区分可行路径？",
        "next_test": {
            "action": "只整理现有现金、替代路径、健康与工作事实，并标出仍由用户决定的取舍。",
            "evidence_sought": "哪些事实会排除路径，哪些冲突无法由事实自动解决。",
            "reversible": True,
            "low_cost": True,
            "stops_before_solution": True,
            "action_type": "evidence_collection",
            "evidence_only": True,
            "solution_commitment": "none",
        },
        "questions": [
            {
                "id": "q1",
                "question": "如果收入中断，你能承受多久，离开后有哪些现实替代选择？",
                "changes": "改变财务风险和可行路径。",
                "addresses": ["u1", "u2"],
            },
            {
                "id": "q2",
                "question": "当前状态对健康造成了什么可观察影响，哪些损失是你不能承受的？",
                "changes": "改变安全优先级和风险边界。",
                "addresses": ["u3", "u5"],
            },
            {
                "id": "q3",
                "question": "你真正想改变什么，这次具体需要决定哪件事？",
                "changes": "确定现实目标和决策对象。",
                "addresses": ["u4", "u6"],
            },
        ],
        "decision_owner": "user",
        "execution_allowed": False,
    }


def valid_ai_product_spec() -> dict[str, object]:
    raw = "帮我做一个能赚钱的 AI App，老板明天要看方案。"
    request_envelope = envelope(
        raw,
        request_id="DPBP-003",
        domain="ai_product",
        deliverable_clear=False,
        inputs_sufficient=False,
        success_criteria_clear=False,
        decisive_unknowns=True,
        high_risk_value_decision=False,
    )
    return {
        "schema_version": "1.0",
        "request_id": "DPBP-003",
        "request_sha256": request_hash(raw),
        "request_envelope": request_envelope,
        "gate_receipt": gate_receipt(
            request_envelope,
            mode="define",
            rule="decisive_unknowns",
            priority_index=1,
            resources=["references/core.md", "references/playbooks/ai-product.md"],
        ),
        "mode": "define",
        "domain": "ai_product",
        "status": "provisional",
        "original_request": raw,
        "original_question": "帮我做一个能赚钱的 AI App",
        "desired_outcome": {"status": "unknown", "value": "当前未知", "sources": []},
        "proxy_problem": {
            "status": "hypothesis",
            "value": "AI App 可能是未经验证的代理解法。",
            "sources": [source(raw, "能赚钱的 AI App")],
        },
        "hidden_assumptions": [
            {
                "status": "hypothesis",
                "value": "做出 App 就能赚钱。",
                "sources": [source(raw, "能赚钱")],
            }
        ],
        "known_facts": [
            {"value": "老板明天要看方案。", "source": source(raw, "老板明天要看方案")}
        ],
        "decisive_unknowns": [
            {"id": "u1", "category": "target_user", "value": "目标用户是谁？", "changes": "改变取证对象。"},
            {
                "id": "u2",
                "category": "recurring_pain",
                "value": "是否有重复需求证据？",
                "changes": "改变是否值得继续。",
            },
            {
                "id": "u3",
                "category": "payment_evidence",
                "value": "是否存在付费证据？",
                "changes": "改变商业判断。",
            },
            {
                "id": "u4",
                "category": "resources",
                "value": "目前有哪些可核查的客户记录和资源？",
                "changes": "改变最小取证范围。",
            },
            {
                "id": "u5",
                "category": "success_criteria",
                "value": "什么证据才算值得继续投入？",
                "changes": "改变成功口径。",
            },
        ],
        "hard_constraints": [
            {
                "value": "明天需要展示当前进展。",
                "constraint_type": "deadline",
                "source": source(raw, "明天要看方案"),
            }
        ],
        "value_tradeoffs": [],
        "success_evidence": [],
        "failure_conditions": ["没有重复需求证据就进入产品实施。"],
        "change_evidence": ["现有客户记录中出现同一人群的重复请求。"],
        "rewritten_problem": "现有客户记录中是否存在同一人群的重复需求证据？",
        "next_test": {
            "action": "只查阅现有客户记录、请求和 brief，记录重复出现的人群与问题后停止。",
            "evidence_sought": "是否存在重复需求证据。",
            "reversible": True,
            "low_cost": True,
            "stops_before_solution": True,
            "action_type": "evidence_collection",
            "evidence_only": True,
            "solution_commitment": "none",
        },
        "questions": [
            {
                "id": "q1",
                "question": "现有客户记录来自哪里，记录中的目标用户是谁？",
                "changes": "确定取证范围和对象。",
                "addresses": ["u4", "u1"],
            },
            {
                "id": "q2",
                "question": "哪类请求曾重复出现，有哪些付费或采购记录？",
                "changes": "确定重复需求和付费证据。",
                "addresses": ["u2", "u3"],
            },
            {
                "id": "q3",
                "question": "什么现有证据才算值得继续投入？",
                "changes": "确定成功标准。",
                "addresses": ["u5"],
            },
        ],
        "decision_owner": "user",
        "execution_allowed": False,
    }


class RuntimeContract(unittest.TestCase):
    maxDiff = None

    def run_cli(self, *args: str, payload: object | str) -> subprocess.CompletedProcess[str]:
        self.assertTrue(CLI.is_file(), "scripts/dpbp is missing; current version is prompt-only")
        if isinstance(payload, str):
            raw_input = payload
        else:
            raw_input = canonical_json(payload)
        return subprocess.run(
            [str(CLI), *args],
            input=raw_input,
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )

    def parse_json(self, result: subprocess.CompletedProcess[str]) -> dict[str, object]:
        self.assertEqual("", result.stderr)
        parsed = json.loads(result.stdout)
        self.assertIsInstance(parsed, dict)
        return parsed

    def assert_validation_error(self, spec: dict[str, object], code: str) -> None:
        result = self.run_cli("validate", payload=spec)
        self.assertEqual(5, result.returncode, result.stdout + result.stderr)
        parsed = self.parse_json(result)
        error_codes = [item["code"] for item in parsed["errors"]]
        self.assertIn(code, error_codes)

    def test_gate_is_deterministic_and_progressive(self) -> None:
        fixtures = [
            (
                envelope(
                    "把这段中文翻译成自然英文，保留三个专有名词。",
                    deliverable_clear=True,
                    inputs_sufficient=True,
                    success_criteria_clear=True,
                    decisive_unknowns=False,
                    high_risk_value_decision=False,
                ),
                "execute",
                [],
            ),
            (
                envelope(
                    "怎么用 AI 提高效率？",
                    domain="ai_efficiency",
                    deliverable_clear=False,
                    inputs_sufficient=False,
                    success_criteria_clear=False,
                    decisive_unknowns=True,
                    high_risk_value_decision=False,
                ),
                "define",
                ["references/core.md", "references/playbooks/ai-efficiency.md"],
            ),
            (
                envelope(
                    "帮我做一个能赚钱的 AI App。",
                    domain="ai_product",
                    deliverable_clear=False,
                    inputs_sufficient=False,
                    success_criteria_clear=False,
                    decisive_unknowns=True,
                    high_risk_value_decision=False,
                ),
                "define",
                ["references/core.md", "references/playbooks/ai-product.md"],
            ),
            (
                envelope(
                    "我该不该辞职？",
                    domain="career",
                    deliverable_clear=False,
                    inputs_sufficient=False,
                    success_criteria_clear=False,
                    decisive_unknowns=True,
                    high_risk_value_decision=True,
                ),
                "defer_to_user",
                [
                    "references/core.md",
                    "references/high-risk.md",
                    "references/playbooks/career-exit.md",
                ],
            ),
        ]
        for payload, expected_mode, expected_resources in fixtures:
            outputs = set()
            for _ in range(20):
                result = self.run_cli("gate", "--offline", payload=payload)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)
                outputs.add(result.stdout)
            self.assertEqual(1, len(outputs))
            parsed = json.loads(outputs.pop())
            self.assertEqual(expected_mode, parsed["mode"])
            self.assertEqual(payload["signals"]["domain"], parsed["domain"])
            self.assertEqual(expected_resources, parsed["resources"])
            self.assertEqual(request_hash(payload["original_request"]), parsed["request_sha256"])
            self.assertIn(parsed["trace"]["rule"], {
                "high_risk_value_decision",
                "decisive_unknowns",
                "clear_execution",
                "default_define",
            })
            for relative in parsed["resources"]:
                self.assertTrue((ROOT / relative).is_file(), relative)
            if expected_mode == "execute":
                self.assertTrue(parsed["execution_allowed"])
                self.assertNotIn("problem_spec", parsed)
                self.assertNotIn("questions", parsed)

    def test_non_career_high_risk_keeps_the_generic_progressive_load(self) -> None:
        payload = envelope(
            "你替我决定要不要分手。",
            domain="relationship",
            deliverable_clear=False,
            inputs_sufficient=False,
            success_criteria_clear=False,
            decisive_unknowns=True,
            high_risk_value_decision=True,
        )
        result = self.run_cli("gate", "--offline", payload=payload)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(
            ["references/core.md", "references/high-risk.md"],
            self.parse_json(result)["resources"],
        )

    def test_gate_rejects_a_malformed_envelope(self) -> None:
        malformed = envelope(
            "任务",
            deliverable_clear=True,
            inputs_sufficient=True,
            success_criteria_clear=True,
            decisive_unknowns=False,
            high_risk_value_decision=False,
        )
        del malformed["signals"]["inputs_sufficient"]
        result = self.run_cli("gate", "--offline", payload=malformed)
        self.assertEqual(5, result.returncode)
        parsed = self.parse_json(result)
        self.assertIn("MISSING_FIELD", [item["code"] for item in parsed["errors"]])

        wrong_type = envelope(
            "任务",
            deliverable_clear=True,
            inputs_sufficient=True,
            success_criteria_clear=True,
            decisive_unknowns=False,
            high_risk_value_decision=False,
        )
        wrong_type["signals"]["deliverable_clear"] = "yes"
        result = self.run_cli("gate", "--offline", payload=wrong_type)
        self.assertEqual(5, result.returncode)
        parsed = self.parse_json(result)
        self.assertIn("INVALID_FIELD", [item["code"] for item in parsed["errors"]])

    def test_gate_rule_priority_blocks_false_clearance(self) -> None:
        both = envelope(
            "我该不该辞职？",
            domain="career",
            deliverable_clear=True,
            inputs_sufficient=True,
            success_criteria_clear=True,
            decisive_unknowns=True,
            high_risk_value_decision=True,
        )
        result = self.run_cli("gate", "--offline", payload=both)
        self.assertEqual(0, result.returncode)
        parsed = self.parse_json(result)
        self.assertEqual("defer_to_user", parsed["mode"])
        self.assertEqual("high_risk_value_decision", parsed["trace"]["rule"])

    def test_init_builds_a_deterministic_linked_draft(self) -> None:
        payload = envelope(
            "怎么用 AI 提高效率？",
            domain="ai_efficiency",
            deliverable_clear=False,
            inputs_sufficient=False,
            success_criteria_clear=False,
            decisive_unknowns=True,
            high_risk_value_decision=False,
        )
        outputs = set()
        for _ in range(20):
            result = self.run_cli("init", payload=payload)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            outputs.add(result.stdout)
        self.assertEqual(1, len(outputs))
        draft = json.loads(outputs.pop())
        schema = json.loads((ROOT / "schemas" / "problem-spec.schema.json").read_text())
        self.assertEqual(set(schema["required"]), set(draft))
        self.assertEqual("define", draft["mode"])
        self.assertEqual("ai_efficiency", draft["domain"])
        self.assertEqual(payload["original_request"], draft["original_request"])
        self.assertEqual(request_hash(payload["original_request"]), draft["request_sha256"])
        self.assertEqual(
            {"status": "unknown", "value": "当前未知", "sources": []},
            draft["desired_outcome"],
        )
        self.assertFalse(draft["execution_allowed"])

    def test_init_refuses_to_turn_a_clear_task_into_a_problem_spec(self) -> None:
        clear = envelope(
            "翻译这段文字。",
            deliverable_clear=True,
            inputs_sufficient=True,
            success_criteria_clear=True,
            decisive_unknowns=False,
            high_risk_value_decision=False,
        )
        result = self.run_cli("init", payload=clear)
        self.assertEqual(5, result.returncode)
        parsed = self.parse_json(result)
        self.assertEqual("CLEAR_TASK_HAS_NO_SPEC", parsed["error"]["code"])

    def test_validate_accepts_a_complete_anchored_spec(self) -> None:
        result = self.run_cli("validate", payload=valid_define_spec())
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual({"errors": [], "valid": True}, self.parse_json(result))

    def test_validator_recomputes_and_binds_the_gate_receipt(self) -> None:
        resignation = valid_high_risk_spec()
        resignation["mode"] = "define"
        resignation["domain"] = "general"
        resignation["rewritten_problem"] = "我的判断是选择离开这份工作。"
        self.assert_validation_error(resignation, "SPEC_GATE_BINDING_MISMATCH")

        efficiency = valid_define_spec()
        efficiency["domain"] = "general"
        self.assert_validation_error(efficiency, "SPEC_GATE_BINDING_MISMATCH")

        receipt_tamper = valid_define_spec()
        receipt_tamper["gate_receipt"]["resources"] = []
        receipt_tamper["gate_receipt"]["trace"]["rule"] = "default_define"
        self.assert_validation_error(receipt_tamper, "GATE_RECEIPT_MISMATCH")

    def test_required_strings_reject_whitespace_only_exploits(self) -> None:
        spec = valid_define_spec()
        for unknown in spec["decisive_unknowns"]:
            unknown["value"] = " \t "
            unknown["changes"] = "\n"
        for question in spec["questions"]:
            question["question"] = "   "
            question["changes"] = "\t"
        self.assert_validation_error(spec, "BLANK_STRING")

    def test_runtime_enforces_unique_items_for_known_facts(self) -> None:
        spec = valid_define_spec()
        spec["known_facts"].append(copy.deepcopy(spec["known_facts"][0]))
        self.assert_validation_error(spec, "DUPLICATE_ITEM")

    def test_known_fact_values_are_unique_after_trimming(self) -> None:
        spec = valid_define_spec()
        spec["known_facts"][0]["value"] = "  同一事实  "
        spec["known_facts"][1]["value"] = "同一事实"
        self.assert_validation_error(spec, "DUPLICATE_FACT_VALUE")

    def test_problem_dimensions_are_typed_and_questions_address_them(self) -> None:
        missing_id = valid_define_spec()
        del missing_id["decisive_unknowns"][0]["id"]
        self.assert_validation_error(missing_id, "MISSING_FIELD")

        missing_category = valid_define_spec()
        del missing_category["decisive_unknowns"][0]["category"]
        self.assert_validation_error(missing_category, "MISSING_FIELD")

        invalid_category = valid_define_spec()
        invalid_category["decisive_unknowns"][0]["category"] = "prompt_quality"
        self.assert_validation_error(invalid_category, "INVALID_UNKNOWN_CATEGORY")

        missing_addresses = valid_define_spec()
        del missing_addresses["questions"][0]["addresses"]
        self.assert_validation_error(missing_addresses, "MISSING_FIELD")

        empty_addresses = valid_define_spec()
        empty_addresses["questions"][0]["addresses"] = []
        self.assert_validation_error(empty_addresses, "INVALID_QUESTION_ADDRESSES")

        invalid_address = valid_define_spec()
        invalid_address["questions"][0]["addresses"] = ["prompt_quality"]
        self.assert_validation_error(invalid_address, "INVALID_QUESTION_ADDRESS")

        unknown_address = valid_define_spec()
        unknown_address["questions"][0]["addresses"] = ["u999"]
        self.assert_validation_error(unknown_address, "QUESTION_ADDRESS_UNKNOWN_ID")

        duplicate_unknown_id = valid_define_spec()
        duplicate_unknown_id["decisive_unknowns"][1]["id"] = "u1"
        self.assert_validation_error(duplicate_unknown_id, "DUPLICATE_UNKNOWN_ID")

        multi_address = valid_high_risk_spec()
        result = self.run_cli("validate", payload=multi_address)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_domain_category_coverage_gate_has_stable_errors(self) -> None:
        cases = (
            (
                valid_define_spec,
                "measurement_source",
                "AI_EFFICIENCY_CATEGORY_COVERAGE_MISSING",
            ),
            (
                valid_ai_product_spec,
                "payment_evidence",
                "AI_PRODUCT_CATEGORY_COVERAGE_MISSING",
            ),
            (
                valid_high_risk_spec,
                "risk_tolerance",
                "CAREER_CATEGORY_COVERAGE_MISSING",
            ),
        )
        for factory, missing, code in cases:
            with self.subTest(category=missing):
                spec = factory()
                spec["decisive_unknowns"] = [
                    item
                    for item in spec["decisive_unknowns"]
                    if item["category"] != missing
                ]
                self.assert_validation_error(spec, code)

    def test_domain_category_coverage_includes_question_addresses(self) -> None:
        cases = (
            (valid_define_spec, "measurement_source", "AI_EFFICIENCY_CATEGORY_COVERAGE_MISSING"),
            (valid_ai_product_spec, "success_criteria", "AI_PRODUCT_CATEGORY_COVERAGE_MISSING"),
            (valid_high_risk_spec, "decision_target", "CAREER_CATEGORY_COVERAGE_MISSING"),
        )
        for factory, missing, code in cases:
            with self.subTest(category=missing):
                spec = factory()
                missing_id = next(
                    item["id"]
                    for item in spec["decisive_unknowns"]
                    if item["category"] == missing
                )
                fallback_id = next(
                    item["id"]
                    for item in spec["decisive_unknowns"]
                    if item["category"] != missing
                )
                for question in spec["questions"]:
                    question["addresses"] = [
                        unknown_id
                        for unknown_id in question["addresses"]
                        if unknown_id != missing_id
                    ] or [fallback_id]
                self.assert_validation_error(spec, code)

    def test_career_defer_accepts_full_six_category_coverage(self) -> None:
        spec = valid_high_risk_spec()
        categories = {item["category"] for item in spec["decisive_unknowns"]}
        self.assertEqual(
            {
                "financial_capacity",
                "alternatives",
                "health_status",
                "desired_outcome",
                "risk_tolerance",
                "decision_target",
            },
            categories,
        )
        result = self.run_cli("validate", payload=spec)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_validator_rejects_structural_and_policy_violations(self) -> None:
        missing = valid_define_spec()
        del missing["rewritten_problem"]
        self.assert_validation_error(missing, "MISSING_FIELD")

        too_many = valid_define_spec()
        too_many["questions"].append(
            {
                "id": "q4",
                "question": "还有别的吗？",
                "changes": "不改变任何决定。",
                "addresses": ["u1"],
            }
        )
        self.assert_validation_error(too_many, "TOO_MANY_QUESTIONS")

        unanchored = valid_define_spec()
        unanchored["known_facts"][0]["source"]["quote"] = "用户没有说过的话"
        self.assert_validation_error(unanchored, "EVIDENCE_SPAN_MISMATCH")

        sunk_cost = valid_define_spec()
        sunk_cost["hard_constraints"][0]["constraint_type"] = "sunk_cost"
        self.assert_validation_error(sunk_cost, "SUNK_COST_NOT_CONSTRAINT")

        execute_spec = valid_define_spec()
        execute_spec["mode"] = "execute"
        self.assert_validation_error(execute_spec, "PROBLEM_SPEC_FOR_EXECUTE")

        premature = valid_define_spec()
        premature["execution_allowed"] = True
        self.assert_validation_error(premature, "DECISIVE_UNKNOWNS_BLOCK_EXECUTION")

        solution = valid_define_spec()
        solution["solution_plan"] = {"stack": "Next.js", "price": 99}
        self.assert_validation_error(solution, "UNEXPECTED_FIELD")

        verdict = valid_high_risk_spec()
        verdict["recommendation"] = "不要辞职"
        self.assert_validation_error(verdict, "HIGH_RISK_VERDICT_FORBIDDEN")

        invented_number = valid_define_spec()
        invented_number["next_test"]["action"] = "连续观察7天后再决定。"
        self.assert_validation_error(invented_number, "UNSOURCED_NUMERIC_THRESHOLD")

    def test_validator_enforces_nested_schema_and_claim_grounding(self) -> None:
        ungrounded_outcome = valid_define_spec()
        ungrounded_outcome["desired_outcome"] = {
            "status": "stated",
            "value": "减少返工",
            "sources": [],
        }
        self.assert_validation_error(ungrounded_outcome, "UNGROUNDED_CLAIM")

        fact_without_source = valid_define_spec()
        del fact_without_source["known_facts"][0]["source"]
        self.assert_validation_error(fact_without_source, "MISSING_FIELD")

        bad_hypothesis = valid_define_spec()
        bad_hypothesis["hidden_assumptions"][0]["status"] = "stated"
        self.assert_validation_error(bad_hypothesis, "INVALID_FIELD")

        fake_unknown = valid_define_spec()
        fake_unknown["desired_outcome"]["value"] = "大概是节省时间"
        self.assert_validation_error(fake_unknown, "UNKNOWN_MUST_REMAIN_UNKNOWN")

        question_without_impact = valid_define_spec()
        del question_without_impact["questions"][0]["changes"]
        self.assert_validation_error(question_without_impact, "MISSING_FIELD")

        duplicate_question = valid_define_spec()
        duplicate_question["questions"][1]["id"] = "q1"
        self.assert_validation_error(duplicate_question, "DUPLICATE_QUESTION_ID")

        incomplete_test = valid_define_spec()
        del incomplete_test["next_test"]["stops_before_solution"]
        self.assert_validation_error(incomplete_test, "MISSING_FIELD")

        empty_failure = valid_define_spec()
        empty_failure["failure_conditions"] = []
        self.assert_validation_error(empty_failure, "EMPTY_REQUIRED_EVIDENCE")

        rewritten_original = valid_define_spec()
        rewritten_original["original_question"] = "请给我十个工具"
        self.assert_validation_error(rewritten_original, "ORIGINAL_QUESTION_MISMATCH")

    def test_validator_enforces_high_risk_semantics(self) -> None:
        missing_tradeoff = valid_high_risk_spec()
        missing_tradeoff["value_tradeoffs"] = []
        self.assert_validation_error(missing_tradeoff, "HIGH_RISK_TRADEOFF_REQUIRED")

        disguised_verdict = valid_high_risk_spec()
        disguised_verdict["rewritten_problem"] = "你应该辞职，因为成长更重要。"
        self.assert_validation_error(disguised_verdict, "HIGH_RISK_VERDICT_FORBIDDEN")

        terse_verdict = valid_high_risk_spec()
        terse_verdict["rewritten_problem"] = "结论：辞职。"
        self.assert_validation_error(terse_verdict, "HIGH_RISK_VERDICT_FORBIDDEN")

    def test_high_risk_rejects_auditor_verdict_paraphrases(self) -> None:
        verdicts = (
            "我的判断是选择离开这份工作。",
            "综合来看，继续留下不划算。",
            "最合适的路径是接受外部机会。",
        )
        for verdict in verdicts:
            with self.subTest(verdict=verdict):
                spec = valid_high_risk_spec()
                spec["rewritten_problem"] = verdict
                self.assert_validation_error(spec, "HIGH_RISK_VERDICT_FORBIDDEN")

    def test_next_test_structural_stop_boundary_rejects_action_classes(self) -> None:
        actions = (
            (valid_define_spec, "implementation", "部署智能体来减少返工。"),
            (valid_ai_product_spec, "solution_design", "制作并发布落地页，收集预约。"),
            (valid_ai_product_spec, "implementation", "用表单预售，看看是否有人付款。"),
            (valid_high_risk_spec, "decision", "选择离开这份工作。"),
            (valid_high_risk_spec, "communication", "回复老板接受外部机会。"),
        )
        for factory, action_type, action in actions:
            with self.subTest(action_type=action_type):
                spec = factory()
                spec["next_test"]["action_type"] = action_type
                spec["next_test"]["action"] = action
                self.assert_validation_error(spec, "NEXT_TEST_STOP_BOUNDARY_VIOLATION")

        not_evidence_only = valid_define_spec()
        not_evidence_only["next_test"]["evidence_only"] = False
        self.assert_validation_error(not_evidence_only, "NEXT_TEST_STOP_BOUNDARY_VIOLATION")

        committed = valid_ai_product_spec()
        committed["next_test"]["solution_commitment"] = "proposed"
        self.assert_validation_error(committed, "NEXT_TEST_STOP_BOUNDARY_VIOLATION")

    def test_validator_rejects_unsourced_chinese_numeric_thresholds(self) -> None:
        invented_duration = valid_high_risk_spec()
        invented_duration["next_test"]["action"] = "先观察六个月再决定。"
        self.assert_validation_error(invented_duration, "UNSOURCED_NUMERIC_THRESHOLD")

        invented_percentage = valid_define_spec()
        invented_percentage["success_evidence"] = ["返工减少百分之三十。"]
        self.assert_validation_error(invented_percentage, "UNSOURCED_NUMERIC_THRESHOLD")

    def test_ai_efficiency_stops_before_ai_or_tool_relevance_judgment(self) -> None:
        mutations = [
            ("rewritten_problem", lambda spec: spec.__setitem__("rewritten_problem", "判断 AI 是否适合这条流程。")),
            ("next_test.action", lambda spec: spec["next_test"].__setitem__("action", "先用 AI 辅助整理访谈记录。")),
            ("next_test.evidence_sought", lambda spec: spec["next_test"].__setitem__("evidence_sought", "判断 AI 是否相关。")),
            ("questions.question", lambda spec: spec["questions"][0].__setitem__("question", "你想在哪一步采用 AI？")),
            ("questions.changes", lambda spec: spec["questions"][0].__setitem__("changes", "判断工具是否匹配。")),
            ("success_evidence", lambda spec: spec.__setitem__("success_evidence", ["找到适合 AI 介入的环节。"])),
            ("change_evidence", lambda spec: spec.__setitem__("change_evidence", ["记录证明工具与流程匹配。"])),
        ]
        for label, mutate in mutations:
            with self.subTest(field=label):
                spec = valid_define_spec()
                mutate(spec)
                self.assert_validation_error(spec, "AI_EFFICIENCY_PREMATURE_JUDGMENT")

    def test_ai_efficiency_rejects_real_model_vendor_bypass_sentence(self) -> None:
        spec = valid_define_spec()
        spec["next_test"]["evidence_sought"] = (
            "判断已购 ChatGPT Team、Notion AI、Zapier 是否能在一个月内对该损耗产生可测改善"
        )
        self.assert_validation_error(spec, "AI_EFFICIENCY_PREMATURE_JUDGMENT")

    def test_high_risk_mode_rejects_delay_and_reply_tactics(self) -> None:
        mutations = [
            ("success_evidence", lambda spec: spec.__setitem__("success_evidence", ["先保留选择。"])),
            ("failure_conditions", lambda spec: spec.__setitem__("failure_conditions", ["没有确保不锁死当前状态。"])),
            ("rewritten_problem", lambda spec: spec.__setitem__("rewritten_problem", "如何先保留选择，之后再决定？")),
            ("next_test.action", lambda spec: spec["next_test"].__setitem__("action", "起草一段具体回复话术给老板。")),
            ("next_test.evidence_sought", lambda spec: spec["next_test"].__setitem__("evidence_sought", "怎样可以不锁死任何选择。")),
            ("questions", lambda spec: spec["questions"][0].__setitem__("question", "你想先保留选择再决定吗？")),
        ]
        for label, mutate in mutations:
            with self.subTest(field=label):
                spec = valid_high_risk_spec()
                mutate(spec)
                self.assert_validation_error(spec, "HIGH_RISK_DELAY_OR_REPLY_FORBIDDEN")

    def test_high_risk_rejects_real_model_reply_sentence(self) -> None:
        spec = valid_high_risk_spec()
        spec["next_test"]["action"] = "在八点前只回复老板：我需要先确认条件，再给出正式决定"
        self.assert_validation_error(spec, "HIGH_RISK_DELAY_OR_REPLY_FORBIDDEN")

    def test_high_risk_rejects_ungrounded_option_consequences(self) -> None:
        mutations = [
            lambda spec: spec.__setitem__("rewritten_problem", "留下=继续疲惫/没成长，离开=稳定受损。"),
            lambda spec: spec["next_test"].__setitem__("action", "比较留下会继续疲惫和离开会损害稳定。"),
            lambda spec: spec.__setitem__("success_evidence", ["确认留下意味着没成长，离开意味着稳定受损。"]),
        ]
        for mutate in mutations:
            spec = valid_high_risk_spec()
            mutate(spec)
            self.assert_validation_error(spec, "HIGH_RISK_UNGROUNDED_OPTION_CONSEQUENCE")

    def test_high_risk_allows_option_consequences_to_remain_unknown(self) -> None:
        spec = valid_high_risk_spec()
        spec["rewritten_problem"] = (
            "疲惫的来源尚未知；留下是否会继续疲惫、离开是否会损害稳定，也尚未知。"
        )
        result = self.run_cli("validate", payload=spec)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_ai_product_rejects_solution_artifacts_as_real_outcome(self) -> None:
        for value in ("方案", "功能清单", "技术栈", "收费方案", "开发排期"):
            with self.subTest(value=value):
                spec = valid_ai_product_spec()
                spec["desired_outcome"] = {
                    "status": "stated",
                    "value": f"交付{value}。",
                    "sources": [source(spec["original_request"], "方案")],
                }
                self.assert_validation_error(spec, "AI_PRODUCT_DELIVERABLE_NOT_OUTCOME")

    def test_ai_efficiency_rejects_vendor_mentions_outside_anchored_fields(self) -> None:
        spec = valid_define_spec()
        spec["questions"][0]["question"] = "Slack、Notion、Zapier 哪个更适合？"
        self.assert_validation_error(spec, "AI_EFFICIENCY_PREMATURE_JUDGMENT")

    def test_ai_efficiency_rejects_candidate_use_case_menus(self) -> None:
        spec = valid_define_spec()
        spec["questions"][0]["question"] = "例如会议纪要、客服回复、内容写作，你想先优化哪个？"
        self.assert_validation_error(spec, "AI_EFFICIENCY_USE_CASE_MENU_FORBIDDEN")

    def test_ai_efficiency_allows_the_no_ai_baseline_phrase(self) -> None:
        spec = valid_define_spec()
        spec["rewritten_problem"] = "哪一步造成可观察损失，怎样记录无 AI 基线？"
        spec["next_test"]["evidence_sought"] = "该流程的无 AI 基线。"
        result = self.run_cli("validate", payload=spec)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_ai_efficiency_outcome_must_be_observable_not_a_solution_label(self) -> None:
        for value in ("用 AI 提高效率", "采用工具提效", "实现自动化", "提高效率"):
            with self.subTest(value=value):
                spec = valid_define_spec()
                spec["desired_outcome"] = {
                    "status": "stated",
                    "value": value,
                    "sources": [source(spec["original_request"], "用 AI 提高效率")],
                }
                self.assert_validation_error(
                    spec,
                    "AI_EFFICIENCY_OUTCOME_NOT_OBSERVABLE",
                )

    def test_ai_efficiency_allows_an_explicit_observable_outcome(self) -> None:
        spec = valid_define_spec()
        spec["desired_outcome"] = {
            "status": "stated",
            "value": "减少整理访谈记录时的返工。",
            "sources": [source(spec["original_request"], "整理访谈记录")],
        }
        result = self.run_cli("validate", payload=spec)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_single_sample_cannot_claim_a_dominant_loss_or_baseline(self) -> None:
        actions = (
            "读取一个已有样本，找出最大损失后停止。",
            "读取一个已有样本，确认主要损失后停止。",
            "读取一个已有样本并形成代表性基线。",
        )
        for action in actions:
            with self.subTest(action=action):
                spec = valid_define_spec()
                spec["next_test"]["action"] = action
                self.assert_validation_error(spec, "SINGLE_SAMPLE_OVERCLAIMS_BASELINE")

    def test_single_sample_can_identify_only_a_candidate_loss(self) -> None:
        spec = valid_define_spec()
        spec["next_test"]["action"] = "读取一个已有样本，只标记候选损失后停止。"
        spec["next_test"]["evidence_sought"] = (
            "候选损失位置；单个样本不足以判断最大损失或形成代表性基线。"
        )
        result = self.run_cli("validate", payload=spec)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_ai_product_rejects_implementation_options_before_demand_evidence(self) -> None:
        mutations = [
            lambda spec: spec["next_test"].__setitem__("action", "做一个假门页面测试需求。"),
            lambda spec: spec.__setitem__("rewritten_problem", "用 manual concierge 先跑一轮。"),
            lambda spec: spec.__setitem__("success_evidence", ["手工增强能得到用户回复。"]),
        ]
        for mutate in mutations:
            spec = valid_ai_product_spec()
            mutate(spec)
            self.assert_validation_error(spec, "AI_PRODUCT_PREMATURE_IMPLEMENTATION")

    def test_ai_product_scans_tradeoff_for_manual_implementation(self) -> None:
        spec = valid_ai_product_spec()
        spec["value_tradeoffs"] = [
            {"value": "可收费的窄场景手工增强版本", "decision_owner": "user"}
        ]
        self.assert_validation_error(spec, "AI_PRODUCT_PREMATURE_IMPLEMENTATION")

    def test_ai_product_rejects_competitor_page_as_demand_evidence(self) -> None:
        spec = valid_ai_product_spec()
        spec["next_test"]["action"] = "查看竞品付费页面，把它当作本项目的需求和付费证据。"
        self.assert_validation_error(spec, "AI_PRODUCT_COMPETITOR_EVIDENCE_FORBIDDEN")

    def test_ai_product_rejects_solution_form_as_the_real_outcome(self) -> None:
        values = (
            "做出 AI App",
            "上线 App",
            "交付应用",
            "完成产品",
            "搭建平台",
            "开发软件",
        )
        for value in values:
            with self.subTest(value=value):
                spec = valid_ai_product_spec()
                spec["desired_outcome"] = {
                    "status": "stated",
                    "value": value,
                    "sources": [source(spec["original_request"], "AI App")],
                }
                self.assert_validation_error(spec, "AI_PRODUCT_DELIVERABLE_NOT_OUTCOME")

    def test_ai_product_rejects_ai_form_bias_while_demand_is_unknown(self) -> None:
        mutations = [
            lambda spec: spec.__setitem__("rewritten_problem", "目标用户有哪些 AI 相关痛点？"),
            lambda spec: spec["questions"][0].__setitem__("question", "你已经看到哪些 AI 场景需求？"),
        ]
        for mutate in mutations:
            spec = valid_ai_product_spec()
            mutate(spec)
            self.assert_validation_error(spec, "AI_PRODUCT_FORM_BIAS")

    def test_ai_product_rejects_conditional_target_rewrite(self) -> None:
        values = (
            "如果没有重复需求证据，应把目标改为做效率工具。",
            "如果没有重复需求，计划应转向效率工具。",
            "如果没有付费记录，方案改为内部助手。",
        )
        for value in values:
            with self.subTest(value=value):
                spec = valid_ai_product_spec()
                spec["change_evidence"] = [value]
                self.assert_validation_error(spec, "AI_PRODUCT_TARGET_REWRITE_FORBIDDEN")

    def test_ai_product_blocks_sunk_cost_from_rewritten_problem_and_questions(self) -> None:
        mutations = (
            lambda spec: spec.__setitem__(
                "rewritten_problem",
                "怎样验证需求，同时不能白费既有投入？",
            ),
            lambda spec: spec["questions"][0].__setitem__(
                "question",
                "怎样不浪费已经做完的功能？",
            ),
        )
        for mutate in mutations:
            spec = valid_ai_product_spec()
            mutate(spec)
            self.assert_validation_error(
                spec,
                "AI_PRODUCT_SUNK_COST_FEEDBACK_FORBIDDEN",
            )

    def test_ai_product_can_only_inventory_existing_evidence(self) -> None:
        spec = valid_ai_product_spec()
        spec["next_test"]["action"] = (
            "只盘点当前实际存在的客户记录、重复请求、付款记录和可用资源后停止。"
        )
        spec["next_test"]["evidence_sought"] = "现有证据能确认什么，仍缺什么。"
        result = self.run_cli("validate", payload=spec)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_ai_product_treats_any_prototype_as_premature_implementation(self) -> None:
        spec = valid_ai_product_spec()
        spec["next_test"]["action"] = "先做原型收集需求证据。"
        self.assert_validation_error(spec, "AI_PRODUCT_PREMATURE_IMPLEMENTATION")

    def test_validator_rejects_unsourced_half_duration_thresholds(self) -> None:
        for duration in ("半天", "半个月", "半年"):
            with self.subTest(duration=duration):
                spec = valid_high_risk_spec()
                spec["next_test"]["action"] = f"先观察{duration}再决定。"
                self.assert_validation_error(spec, "UNSOURCED_NUMERIC_THRESHOLD")

    def test_validator_rejects_unsourced_at_least_one_thresholds(self) -> None:
        for threshold in ("至少一组", "至少一种", "至少一条", "至少一项"):
            with self.subTest(threshold=threshold):
                spec = valid_define_spec()
                spec["next_test"]["action"] = f"收集{threshold}证据后停止。"
                self.assert_validation_error(spec, "UNSOURCED_NUMERIC_THRESHOLD")

    def test_multiple_decisive_unknowns_require_questions_only_when_outcome_unknown(self) -> None:
        no_questions = valid_define_spec()
        no_questions["questions"] = []
        self.assert_validation_error(no_questions, "DECISIVE_UNKNOWNS_REQUIRE_QUESTIONS")

        one_unknown = valid_define_spec()
        one_unknown["domain"] = "general"
        one_unknown["request_envelope"]["signals"]["domain"] = "general"
        one_unknown["gate_receipt"] = gate_receipt(
            one_unknown["request_envelope"],
            mode="define",
            rule="decisive_unknowns",
            priority_index=1,
            resources=["references/core.md"],
        )
        one_unknown["decisive_unknowns"] = one_unknown["decisive_unknowns"][:1]
        one_unknown["questions"] = []
        result = self.run_cli("validate", payload=one_unknown)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_render_is_deterministic_and_has_exactly_twelve_sections(self) -> None:
        outputs = set()
        for _ in range(20):
            result = self.run_cli("render", payload=valid_define_spec())
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual("", result.stderr)
            outputs.add(result.stdout)
        self.assertEqual(1, len(outputs))
        rendered = outputs.pop()
        headings = [
            "1. 原始问题",
            "2. 用户真正想改变的结果",
            "3. 当前问题可能是哪个代理问题",
            "4. 隐藏假设",
            "5. 已知事实",
            "6. 决定性未知",
            "7. 硬约束",
            "8. 需要用户本人决定的价值取舍",
            "9. 成功证据和失败条件",
            "10. 改写后更值得回答的问题",
            "11. 最小、可逆、低成本的下一步测试",
            "12. 信息不足时最多三个高价值问题",
        ]
        for heading in headings:
            self.assertEqual(1, rendered.count(f"## {heading}"), heading)
        self.assertIn("[暂定假设]", rendered)

    def test_invalid_json_and_version_have_stable_errors(self) -> None:
        invalid = self.run_cli("validate", payload="{not json")
        self.assertEqual(2, invalid.returncode)
        self.assertEqual("INVALID_JSON", self.parse_json(invalid)["error"]["code"])
        self.assertNotIn("Traceback", invalid.stdout + invalid.stderr)

        unsupported = valid_define_spec()
        unsupported["schema_version"] = "9.9"
        result = self.run_cli("validate", payload=unsupported)
        self.assertEqual(3, result.returncode)
        self.assertEqual("SCHEMA_VERSION_UNSUPPORTED", self.parse_json(result)["error"]["code"])

    def test_state_resume_is_atomic_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            start = self.run_cli("start", "--state", str(state_path), payload=valid_define_spec())
            self.assertEqual(0, start.returncode, start.stdout + start.stderr)
            first = self.parse_json(start)
            self.assertEqual(1, first["revision"])
            self.assertEqual(3, len(first["pending_questions"]))
            self.assertEqual(
                ["u1"],
                first["pending_questions"][0]["addresses"],
            )
            original_hash = first["request_sha256"]
            self.assertEqual(valid_define_spec()["original_request"], first["original_request"])
            self.assertEqual(valid_define_spec(), first["spec"])
            self.assertEqual("valid", first["validation_status"])

            answer = {
                "answer_id": "answer-001",
                "question_id": "q1",
                "answer": "减少返工。",
                "expected_revision": 1,
            }
            resumed = self.run_cli("resume", "--state", str(state_path), payload=answer)
            self.assertEqual(0, resumed.returncode, resumed.stdout + resumed.stderr)
            second = self.parse_json(resumed)
            self.assertEqual(2, second["revision"])
            self.assertEqual(original_hash, second["request_sha256"])
            self.assertEqual(1, len(second["answers"]))
            self.assertEqual(2, len(second["pending_questions"]))
            self.assertEqual("needs_model_update", second["validation_status"])

            state_schema = json.loads((ROOT / "schemas" / "problem-state.schema.json").read_text())
            self.assertEqual(set(state_schema["required"]), set(second))

            bytes_before_replay = state_path.read_bytes()
            replay = self.run_cli("resume", "--state", str(state_path), payload=answer)
            self.assertEqual(0, replay.returncode, replay.stdout + replay.stderr)
            replayed = self.parse_json(replay)
            self.assertEqual(2, replayed["revision"])
            self.assertEqual(bytes_before_replay, state_path.read_bytes())

            bytes_before_failure = state_path.read_bytes()
            failed = self.run_cli("resume", "--state", str(state_path), payload="{bad json")
            self.assertEqual(2, failed.returncode)
            self.assertEqual(bytes_before_failure, state_path.read_bytes())

    def test_state_rejects_pending_question_and_answer_id_tampering(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            start = self.run_cli("start", "--state", str(state_path), payload=valid_define_spec())
            self.assertEqual(0, start.returncode, start.stdout + start.stderr)

            tampered = json.loads(state_path.read_text(encoding="utf-8"))
            tampered["pending_questions"][0]["id"] = "q9"
            state_path.write_text(canonical_json(tampered) + "\n", encoding="utf-8")
            result = self.run_cli(
                "resume",
                "--state",
                str(state_path),
                payload={
                    "answer_id": "answer-q9",
                    "question_id": "q9",
                    "answer": "伪造答案",
                    "expected_revision": 1,
                },
            )
            self.assertEqual(4, result.returncode, result.stdout + result.stderr)
            self.assertEqual("STATE_INVALID", self.parse_json(result)["error"]["code"])

    def test_resume_uses_expected_revision_compare_and_swap(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            start = self.run_cli("start", "--state", str(state_path), payload=valid_define_spec())
            self.assertEqual(0, start.returncode, start.stdout + start.stderr)

            first = self.run_cli(
                "resume",
                "--state",
                str(state_path),
                payload={
                    "answer_id": "answer-1",
                    "question_id": "q1",
                    "answer": "减少返工",
                    "expected_revision": 1,
                },
            )
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)

            stale = self.run_cli(
                "resume",
                "--state",
                str(state_path),
                payload={
                    "answer_id": "answer-2",
                    "question_id": "q2",
                    "answer": "访谈整理步骤",
                    "expected_revision": 1,
                },
            )
            self.assertEqual(5, stale.returncode, stale.stdout + stale.stderr)
            self.assertEqual("REVISION_CONFLICT", self.parse_json(stale)["error"]["code"])
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(2, persisted["revision"])
            self.assertEqual(["answer-1"], [item["answer_id"] for item in persisted["answers"]])

    def test_concurrent_resume_cannot_lose_an_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            state_path = Path(temp_dir) / "state.json"
            start = self.run_cli("start", "--state", str(state_path), payload=valid_define_spec())
            self.assertEqual(0, start.returncode, start.stdout + start.stderr)
            payloads = (
                {
                    "answer_id": "answer-a",
                    "question_id": "q1",
                    "answer": "减少返工",
                    "expected_revision": 1,
                },
                {
                    "answer_id": "answer-b",
                    "question_id": "q2",
                    "answer": "访谈整理步骤",
                    "expected_revision": 1,
                },
            )

            def invoke(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
                return subprocess.run(
                    [str(CLI), "resume", "--state", str(state_path)],
                    input=canonical_json(payload),
                    text=True,
                    capture_output=True,
                    cwd=ROOT,
                    check=False,
                )

            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(invoke, payloads))
            self.assertEqual([0, 5], sorted(result.returncode for result in results))
            conflict = next(result for result in results if result.returncode == 5)
            self.assertEqual("REVISION_CONFLICT", self.parse_json(conflict)["error"]["code"])
            persisted = json.loads(state_path.read_text(encoding="utf-8"))
            self.assertEqual(2, persisted["revision"])
            self.assertEqual(1, len(persisted["answers"]))

    def test_missing_state_is_a_clean_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing.json"
            result = self.run_cli(
                "resume",
                "--state",
                str(missing),
                payload={"answer_id": "a", "question_id": "q1", "answer": "x"},
            )
            self.assertEqual(4, result.returncode)
            parsed = self.parse_json(result)
            self.assertEqual("STATE_NOT_FOUND", parsed["error"]["code"])
            self.assertNotIn("Traceback", result.stdout + result.stderr)

    def test_cli_help_and_version_need_no_stdin(self) -> None:
        for command in ("--help", "help"):
            result = subprocess.run(
                [str(CLI), command],
                text=True,
                capture_output=True,
                cwd=ROOT,
                check=False,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual("", result.stderr)
            self.assertIn("Usage: dpbp", result.stdout)
            self.assertIn("doctor", result.stdout)

        version = subprocess.run(
            [str(CLI), "version"],
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(0, version.returncode, version.stdout + version.stderr)
        self.assertEqual((ROOT / "VERSION").read_text(), version.stdout)
        self.assertEqual("", version.stderr)

    def test_doctor_is_structured_offline_and_read_only(self) -> None:
        observed = [
            ROOT / "runtime" / "routes.json",
            ROOT / "schemas" / "request-envelope.schema.json",
            ROOT / "schemas" / "problem-spec.schema.json",
            ROOT / "schemas" / "problem-state.schema.json",
            ROOT / "references" / "core.md",
            ROOT / "references" / "high-risk.md",
            ROOT / "references" / "playbooks" / "ai-efficiency.md",
            ROOT / "references" / "playbooks" / "ai-product.md",
        ]
        before = {path: path.read_bytes() for path in observed}
        result = subprocess.run(
            [str(CLI), "doctor"],
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        report = self.parse_json(result)
        self.assertTrue(report["ok"])
        self.assertEqual((ROOT / "VERSION").read_text().strip(), report["version"])
        self.assertTrue(report["checks"])
        self.assertTrue(all(check["ok"] for check in report["checks"]))
        self.assertEqual(before, {path: path.read_bytes() for path in observed})


if __name__ == "__main__":
    unittest.main()
