import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "casefile.py"
SCHEMA = SKILL_DIR / "schemas" / "casefile.schema.json"


def runtime_module():
    spec = importlib.util.spec_from_file_location("casefile_fixture_helper", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def replace_first_input(case: dict, text: str) -> None:
    case["inputs"][0]["text"] = text
    case["inputs"][0]["sha256"] = sha256_text(text)
    case["input_sha256"] = sha256_text(text)
    module = runtime_module()
    case["source_spans"] = module.generate_source_spans("I1", text)
    case["unclassified_observation_candidates"] = (
        module.generate_unclassified_observation_candidates(
            "I1", text, case["source_spans"]
        )
        if case.get("mode") == "standard"
        else []
    )


def valid_standard() -> dict:
    text = "老板连续两次没让我参加会议。我认为他在架空我。"
    spans = runtime_module().generate_source_spans("I1", text)
    return {
        "schema_version": runtime_module().SCHEMA_VERSION,
        "skill_version": runtime_module().SKILL_VERSION,
        "case_id": "standard-valid",
        "revision": 1,
        "previous_case_sha256": None,
        "mode": "standard",
        "current_input_id": "I1",
        "input_sha256": sha256_text(text),
        "inputs": [{"id": "I1", "text": text, "sha256": sha256_text(text)}],
        "source_spans": spans,
        "unclassified_observation_candidates": [],
        "candidate_resolutions": [],
        "claims": [
            {
                "id": "C1",
                "kind": "observable_fact",
                "observation_type": "participation_or_schedule_event",
                "text": "老板连续两次没让我参加会议。",
                "input_id": "I1",
                "source_span_id": "SP1",
                "source_ref": "input",
                "source_type": "user_direct_observation",
                "exact_quote": "老板连续两次没让我参加会议。",
                "epistemic_status": "reported",
                "diagnostic_boundary": False,
            },
            {
                "id": "C2",
                "kind": "interpretation",
                "text": "我认为他在架空我。",
                "input_id": "I1",
                "source_span_id": "SP2",
                "source_ref": "input",
                "source_type": "user_report",
                "exact_quote": "我认为他在架空我。",
                "epistemic_status": "unverified",
                "diagnostic_boundary": False,
            },
        ],
        "evidence": [
            {
                "id": "E1",
                "input_id": "I1",
                "source_span_id": "SP1",
                "source_ref": "input",
                "source_type": "user_direct_observation",
                "exact_quote": "老板连续两次没让我参加会议。",
                "can_establish": ["C1"],
                "cannot_establish": ["C2"],
                "limitations": ["single_party_report", "limited_sample"],
            }
        ],
        "evidence_links": [
            {
                "proposition_id": "C1",
                "evidence_ref": "E1",
                "relation": "supports",
                "strength": "direct",
                "reason": "anchor_matches_report",
            },
            {
                "proposition_id": "C2",
                "evidence_ref": "E1",
                "relation": "does_not_establish",
                "strength": "none",
                "reason": "source_scope_limit",
            }
        ],
        "unknowns": [
            {
                "id": "U1",
                "unknown_type": "formal_role_or_authority_change",
                "text": "正式职责、参与范围或审批权限是否发生变化",
                "status": "open",
                "resolved_by_evidence_refs": [],
            }
        ],
        "hypotheses": [],
        "discriminator": {
            "question_type": "formal_role_or_authority_check",
            "question": "我目前的正式职责、决策参与范围或审批权限是否发生变化？",
            "distinguishes": ["C2", "U1"],
            "branches": [
                {
                    "answer_type": "formal_scope_changed",
                    "observable_answer": "正式职责或权限发生变化",
                    "updates": [
                        {"target_id": "C2", "effect": "strengthens"},
                        {"target_id": "U1", "effect": "weakens"},
                    ],
                },
                {
                    "answer_type": "formal_scope_unchanged",
                    "observable_answer": "正式职责或权限保持不变",
                    "updates": [
                        {"target_id": "C2", "effect": "weakens"},
                        {"target_id": "U1", "effect": "weakens"},
                    ],
                },
            ],
            "risk": "low",
            "reversible": True,
        },
        "actions": [
            {
                "id": "A1",
                "action_type": "neutral_check",
                "text": "围绕具体安排、职责、边界或时间做一次中性核对",
                "timing": "next",
                "risk": "low",
                "reversible": True,
                "motive_independent": True,
                "produces_new_evidence": True,
            }
        ],
        "user_decisions": ["employment_continuation"],
        "safety": {"risk_signals": []},
        "change_log": [],
    }


def valid_safety() -> dict:
    text = "前任说‘今晚去你家堵你’，他以前砸过我的门。"
    case = valid_standard()
    case.update(
        {
            "case_id": "safety-valid",
            "mode": "safety",
            "input_sha256": sha256_text(text),
            "inputs": [{"id": "I1", "text": text, "sha256": sha256_text(text)}],
            "source_spans": runtime_module().generate_source_spans("I1", text),
            "claims": [],
            "evidence": [],
            "evidence_links": [],
            "unknowns": [],
            "hypotheses": [],
            "discriminator": None,
            "actions": [
                {
                    "id": "A1",
                    "action_type": "move_to_safe_place",
                    "text": "立即前往有其他人在场或有人值守的安全地点",
                    "timing": "immediate",
                    "risk": "low",
                    "reversible": True,
                    "motive_independent": True,
                    "produces_new_evidence": False,
                }
            ],
            "user_decisions": [],
            "safety": {
                "risk_signals": [
                    {
                        "input_id": "I1",
                        "source_span_id": "SP4",
                        "source_ref": "input",
                        "exact_quote": text,
                        "signal_type": "explicit_threat",
                        "routing_basis": "deterministic_backstop",
                    },
                    {
                        "input_id": "I1",
                        "source_span_id": "SP4",
                        "source_ref": "input",
                        "exact_quote": text,
                        "signal_type": "prior_violence_or_damage",
                        "routing_basis": "deterministic_backstop",
                    },
                ]
            },
        }
    )
    return case


class CasefileContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not SCRIPT.exists():
            raise AssertionError(f"missing executable capability: {SCRIPT}")
        if not SCHEMA.exists():
            raise AssertionError(f"missing machine schema: {SCHEMA}")
        spec = importlib.util.spec_from_file_location("casefile", SCRIPT)
        cls.module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.module)

    def validate(self, data, previous=None):
        return self.module.validate_casefile(data, previous=previous)

    def test_valid_standard_contract_passes(self):
        self.assertEqual([], self.validate(valid_standard()))

    def test_evidence_may_explicitly_establish_nothing(self):
        case = valid_standard()
        case["evidence"].append(
            {
                "id": "E2",
                "input_id": "I1",
                "source_span_id": "SP2",
                "source_ref": "input",
                "source_type": "user_report",
                "exact_quote": "我认为他在架空我。",
                "can_establish": [],
                "cannot_establish": ["C2"],
                "limitations": ["single_party_report"],
            }
        )
        case["evidence_links"].append(
            {
                "proposition_id": "C2",
                "evidence_ref": "E2",
                "relation": "does_not_establish",
                "strength": "none",
                "reason": "source_scope_limit",
            }
        )
        self.assertEqual([], self.validate(case))

    def test_evidence_lists_reject_duplicate_items_like_the_schema(self):
        for field in ("can_establish", "limitations"):
            with self.subTest(field=field):
                case = valid_standard()
                case["evidence"][0][field].append(case["evidence"][0][field][0])
                codes = {item["code"] for item in self.validate(case)}
                self.assertIn("DUPLICATE_LIST_ITEM", codes)

    def test_standard_mode_rejects_empty_claim_and_evidence_shell(self):
        case = valid_standard()
        case["claims"] = []
        case["evidence"] = []
        case["evidence_links"] = []
        case["discriminator"] = None
        codes = {item["code"] for item in self.validate(case)}
        self.assertIn("CLAIM_REQUIRED", codes)
        self.assertIn("EVIDENCE_REQUIRED", codes)

    def test_anchor_not_found_is_rejected(self):
        case = valid_standard()
        case["claims"][0]["exact_quote"] = "老板亲口说要开除我"
        codes = {item["code"] for item in self.validate(case)}
        self.assertIn("ANCHOR_NOT_FOUND", codes)

    def test_source_type_mismatch_is_rejected(self):
        case = valid_standard()
        case["claims"][0]["source_type"] = "direct_quote"
        codes = {item["code"] for item in self.validate(case)}
        self.assertIn("SOURCE_TYPE_MISMATCH", codes)

    def test_evidence_source_label_cannot_claim_a_stronger_source_type(self):
        case = valid_standard()
        text = case["inputs"][0]["text"] + "\n[同事转述] 同事说老板要撤掉我。"
        replace_first_input(case, text)
        span = next(
            item for item in case["source_spans"] if item["source_label"] == "同事转述"
        )
        case["evidence"][0].update(
            {
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "exact_quote": span["text"],
                "source_type": "user_direct_observation",
            }
        )
        codes = {item["code"] for item in self.validate(case)}
        self.assertIn("SOURCE_TYPE_MISMATCH", codes)

    def test_motive_or_interpretation_cannot_be_verified(self):
        case = valid_standard()
        case["claims"][1]["epistemic_status"] = "verified"
        codes = {item["code"] for item in self.validate(case)}
        self.assertIn("CONCLUSION_EXCEEDS_EVIDENCE", codes)

    def test_irreversible_action_cannot_claim_reversible(self):
        case = valid_standard()
        case["actions"][0]["text"] = "立即辞职并公开指责老板"
        codes = {item["code"] for item in self.validate(case)}
        self.assertIn("ACTION_REVERSIBILITY_FALSE", codes)

    def test_feeling_requires_exact_user_anchor(self):
        case = valid_standard()
        case["claims"].append(
            {
                "id": "C3",
                "kind": "explicit_feeling",
                "text": "用户感到难受",
                "input_id": "I1",
                "source_ref": "input",
                "source_type": "explicit_self_report",
                "exact_quote": "我很难受",
                "epistemic_status": "reported",
                "diagnostic_boundary": False,
            }
        )
        codes = {item["code"] for item in self.validate(case)}
        self.assertIn("ANCHOR_NOT_FOUND", codes)

    def test_hypothesis_requires_support_and_weakening_signals(self):
        case = valid_standard()
        case["hypotheses"] = [
            {
                "id": "H1",
                "text": "会议范围临时缩小",
                "confidence": "low",
                "support_signals": ["职责保持不变"],
                "weakening_signals": [],
                "exit_condition": "职责正式削减",
            }
        ]
        codes = {item["code"] for item in self.validate(case)}
        self.assertIn("HYPOTHESIS_NOT_FALSIFIABLE", codes)

    def test_hypotheses_require_explicit_positive_request_anchor(self):
        case = valid_standard()
        case["hypotheses"] = [
            {
                "id": "H1",
                "text": "会议范围临时缩小",
                "confidence": "low",
                "support_signals": ["职责保持不变"],
                "weakening_signals": ["职责正式削减"],
                "exit_condition": "出现正式职责变更",
            }
        ]
        codes = {item["code"] for item in self.validate(case)}
        self.assertIn("HYPOTHESIS_NOT_REQUESTED", codes)

    def test_hypothesis_discriminator_updates_every_hypothesis_in_each_branch(self):
        case = valid_standard()
        text = case["inputs"][0]["text"] + "请给我两个待核对的工作假设。"
        replace_first_input(case, text)
        case["hypothesis_request"] = {
            "input_id": "I1",
            "source_span_id": "SP3",
            "exact_quote": "请给我两个待核对的工作假设。",
            "requested_count": 2,
        }
        case["hypotheses"] = [
            {
                "id": "H1",
                "hypothesis_type": "temporary_scope_or_situational_constraint",
                "text": "当前变化可能来自临时范围或情境约束",
                "confidence": "low",
                "support_signals": ["formal_scope_unchanged"],
                "weakening_signals": ["formal_scope_changed"],
                "exit_condition": "formal_scope_changed",
            },
            {
                "id": "H2",
                "hypothesis_type": "substantive_role_or_boundary_change",
                "text": "当前变化可能反映职责、边界或优先级的实质调整",
                "confidence": "low",
                "support_signals": ["formal_scope_changed"],
                "weakening_signals": ["formal_scope_unchanged"],
                "exit_condition": "formal_scope_unchanged",
            },
        ]
        case["discriminator"]["distinguishes"] = ["H1", "H2"]
        case["discriminator"]["branches"] = [
            {
                "answer_type": "formal_scope_unchanged",
                "observable_answer": "正式职责或权限保持不变",
                "updates": [{"target_id": "H1", "effect": "strengthens"}],
            },
            {
                "answer_type": "formal_scope_changed",
                "observable_answer": "正式职责或权限发生变化",
                "updates": [{"target_id": "H2", "effect": "strengthens"}],
            },
        ]
        codes = {item["code"] for item in self.validate(case)}
        self.assertIn("HYPOTHESIS_BRANCH_INCOMPLETE", codes)

    def test_discriminator_must_be_single_low_risk_question(self):
        case = valid_standard()
        case["discriminator"]["question"] = "职责变了吗？权限变了吗？"
        codes = {item["code"] for item in self.validate(case)}
        self.assertIn("DISCRIMINATOR_NOT_SINGLE", codes)

    def test_safety_mode_requires_immediate_action(self):
        case = valid_safety()
        case["actions"][0]["timing"] = "next"
        codes = {item["code"] for item in self.validate(case)}
        self.assertIn("SAFETY_ACTION_NOT_FIRST", codes)

    def test_renderer_places_safety_action_before_analysis(self):
        rendered = self.module.render_markdown(valid_safety())
        self.assertTrue(rendered.startswith("# 先处理现实安全"))
        self.assertNotIn("可观察事实", rendered)

    def test_renderer_preserves_standard_eight_part_contract(self):
        rendered = self.module.render_markdown(valid_standard())
        headings = [
            "## 1. 可观察事实",
            "## 2. 用户明确表达的感受和体验",
            "## 3. 用户当前的解释",
            "## 4. 尚未验证的动机推断",
            "## 5. 当前未知",
            "## 6. 能区分不同解释的证据",
            "## 7. 不依赖猜中动机也能采取的下一步行动",
            "## 8. 最终仍由用户决定的部分",
        ]
        positions = [rendered.index(item) for item in headings]
        self.assertEqual(positions, sorted(positions))

    def test_update_requires_hash_chain_and_preserves_prior_items(self):
        previous = valid_standard()
        new_text = "老板发来原话：“我的岗位职责和审批权限保持不变。”"
        current = self.module.start_update(previous, new_text)
        current["claims"].append(
            {
                "id": "C3",
                "kind": "stated_position",
                "text": "我的岗位职责和审批权限保持不变。",
                "input_id": "I2",
                "source_span_id": "SP4",
                "source_ref": "input",
                "source_type": "direct_quote",
                "exact_quote": "我的岗位职责和审批权限保持不变。",
                "epistemic_status": "directly_stated",
                "diagnostic_boundary": False,
            }
        )
        current["evidence"].append(
            {
                "id": "E2",
                "input_id": "I2",
                "source_span_id": "SP4",
                "source_ref": "input",
                "source_type": "direct_quote",
                "exact_quote": "我的岗位职责和审批权限保持不变。",
                "can_establish": ["C3"],
                "cannot_establish": ["C2"],
                "limitations": ["time_scope_limited"],
            }
        )
        current["evidence_links"].extend(
            [
                {
                    "proposition_id": "C3",
                    "evidence_ref": "E2",
                    "relation": "supports",
                    "strength": "direct",
                    "reason": "direct_current_statement_only",
                },
                {
                    "proposition_id": "C2",
                    "evidence_ref": "E2",
                    "relation": "does_not_establish",
                    "strength": "none",
                    "reason": "source_scope_limit",
                },
            ]
        )
        self.assertEqual([], self.validate(current, previous=previous))
        current["claims"].pop(0)
        codes = {item["code"] for item in self.validate(current, previous=previous)}
        self.assertIn("HISTORY_ITEM_REMOVED", codes)

    def test_cli_writes_receipt_and_returns_nonzero_for_invalid_artifact(self):
        invalid = SKILL_DIR / "evals" / "fixtures" / "invalid-epistemic.json"
        original_hash = hashlib.sha256(invalid.read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as temp_dir:
            report = Path(temp_dir) / "receipt.json"
            completed = subprocess.run(
                [sys.executable, str(SCRIPT), "validate", str(invalid), "--report", str(report)],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, completed.returncode)
            receipt = json.loads(report.read_text(encoding="utf-8"))
            self.assertFalse(receipt["valid"])
            self.assertGreaterEqual(receipt["error_count"], 4)
            self.assertEqual(original_hash, hashlib.sha256(invalid.read_bytes()).hexdigest())
            codes = {item["code"] for item in receipt["errors"]}
            self.assertTrue(
                {
                    "ANCHOR_NOT_FOUND",
                    "SOURCE_TYPE_MISMATCH",
                    "CONCLUSION_EXCEEDS_EVIDENCE",
                    "ACTION_REVERSIBILITY_FALSE",
                }.issubset(codes)
            )


if __name__ == "__main__":
    unittest.main()
