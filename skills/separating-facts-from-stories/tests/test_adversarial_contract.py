import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_casefile import (
    SKILL_DIR,
    SCRIPT,
    replace_first_input,
    sha256_text,
    valid_safety,
    valid_standard,
)


class AdversarialContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import importlib.util

        spec = importlib.util.spec_from_file_location("casefile_adversarial", SCRIPT)
        cls.module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.module)

    def codes(self, data, previous=None):
        return {item["code"] for item in self.module.validate_casefile(data, previous=previous)}

    def add_current_observation(self, data, claim_id, evidence_id):
        current_input_id = data["current_input_id"]
        span = next(
            item
            for item in data["source_spans"]
            if item["input_id"] == current_input_id
            and self.module.derive_observation_type(item["text"], item)
            is not None
        )
        data["claims"].append(
            {
                "id": claim_id,
                "kind": "observable_fact",
                "observation_type": self.module.derive_observation_type(
                    span["text"], span
                ),
                "text": span["text"],
                "input_id": current_input_id,
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "user_direct_observation",
                "exact_quote": span["text"],
                "epistemic_status": "reported",
                "diagnostic_boundary": False,
            }
        )
        data["evidence"].append(
            {
                "id": evidence_id,
                "input_id": current_input_id,
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "user_direct_observation",
                "exact_quote": span["text"],
                "can_establish": [claim_id],
                "cannot_establish": [],
                "limitations": ["single_party_report"],
            }
        )
        data["evidence_links"].append(
            {
                "proposition_id": claim_id,
                "evidence_ref": evidence_id,
                "relation": "supports",
                "strength": "direct",
                "reason": "anchor_matches_report",
            }
        )

    def test_free_claim_text_cannot_hide_behind_unrelated_anchor(self):
        case = valid_standard()
        case["claims"][0].update(
            {
                "text": "老板已经确定要架空我",
                "kind": "observable_fact",
                "source_type": "external_verified",
                "epistemic_status": "verified",
                "exact_quote": "老板连续两次没让我参加会议",
            }
        )
        codes = self.codes(case)
        self.assertIn("CLAIM_TEXT_NOT_ANCHOR", codes)
        self.assertIn("SOURCE_ATTESTATION_UNSUPPORTED", codes)

    def test_every_claim_requires_evidence_scope_link(self):
        case = valid_standard()
        case["evidence_links"] = []
        self.assertIn("CLAIM_EVIDENCE_REQUIRED", self.codes(case))

    def test_status_must_match_evidence_relations(self):
        case = valid_standard()
        case["claims"][1]["epistemic_status"] = "strongly_supported"
        self.assertIn("STATUS_NOT_DERIVED", self.codes(case))

    def test_safety_action_cannot_be_free_text_retaliation(self):
        case = valid_safety()
        case["actions"][0].update(
            {
                "text": "立即去前任家报复并当面对质",
                "risk": "high",
                "reversible": False,
                "motive_independent": False,
            }
        )
        self.assertIn("SAFE_ACTION_CONSTRAINT", self.codes(case))

    def test_standard_action_keyword_bypass_is_rejected(self):
        case = valid_standard()
        case["actions"][0]["text"] = "立刻去公司大闹并逼老板交代，否则让朋友围堵他"
        self.assertIn("ACTION_TEXT_NOT_CANONICAL", self.codes(case))

    def test_standard_history_can_switch_to_safety_without_deleting_it(self):
        previous = valid_standard()
        new_text = "他刚发来消息说十五分钟后到我家堵我。"
        current = self.module.start_update(previous, new_text)
        current["mode"] = "safety"
        current["actions"] = [
            {
                "id": "A2",
                "action_type": "move_to_safe_place",
                "text": "立即前往有其他人在场或有人值守的安全地点",
                "timing": "immediate",
                "risk": "low",
                "reversible": True,
                "motive_independent": True,
                "produces_new_evidence": False,
            }
        ]
        current["safety"] = {
            "risk_signals": [
                {
                    "input_id": "I2",
                    "source_span_id": "SP3",
                    "source_ref": "input",
                    "exact_quote": "他刚发来消息说十五分钟后到我家堵我。",
                    "signal_type": "explicit_threat",
                    "routing_basis": "deterministic_backstop",
                }
            ]
        }
        errors = self.module.validate_casefile(current, previous=previous)
        self.assertEqual([], errors)

    def test_change_log_must_use_new_evidence_and_real_transition(self):
        previous = valid_standard()
        current = self.module.start_update(previous, "老板没有补充任何新信息。")
        current["claims"][1]["epistemic_status"] = "conflicted"
        current["change_log"] = [
            {
                "target_id": "C2",
                "from_status": "unverified",
                "to_status": "conflicted",
                "reason_evidence_refs": ["E1"],
            }
        ]
        self.assertIn(
            "CHANGE_REQUIRES_NEW_EVIDENCE",
            self.codes(current, previous=previous),
        )

    def test_renderer_includes_requested_hypotheses(self):
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
        rendered = self.module.render_markdown(case)
        self.assertIn("当前变化可能来自临时范围或情境约束", rendered)
        self.assertIn("当前变化可能反映职责、边界或优先级的实质调整", rendered)

    def test_direct_quote_must_be_inside_the_actual_quote_span(self):
        case = valid_standard()
        text = case["inputs"][0]["text"] + "。另有人说：“下午见”。"
        replace_first_input(case, text)
        case["claims"][1].update(
            {
                "kind": "stated_position",
                "source_type": "direct_quote",
                "epistemic_status": "directly_stated",
            }
        )
        self.assertIn("DIRECT_QUOTE_NOT_BOUNDED", self.codes(case))

    def test_revision_two_can_seed_revision_three_with_full_history(self):
        previous = valid_standard()
        revision_two = self.module.start_update(previous, "老板取消了会议。")
        self.add_current_observation(revision_two, "C3", "E2")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            r1 = root / "r1.json"
            r2 = root / "r2.json"
            input_three = root / "round-3.txt"
            r3 = root / "r3.json"
            r1.write_text(json.dumps(previous, ensure_ascii=False), encoding="utf-8")
            r2.write_text(json.dumps(revision_two, ensure_ascii=False), encoding="utf-8")
            input_three.write_text("第三轮新证据。", encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "start-update",
                    "--history",
                    str(r1),
                    str(r2),
                    "--input",
                    str(input_three),
                    "--output",
                    str(r3),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            self.assertTrue(r3.exists())

    def test_revision_three_cli_validation_requires_full_history(self):
        revision_one = valid_standard()
        revision_two = self.module.start_update(revision_one, "老板取消了会议。")
        self.add_current_observation(revision_two, "C3", "E2")
        revision_three = self.module.start_update(revision_two, "老板回复了消息。")
        self.add_current_observation(revision_three, "C4", "E3")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paths = []
            for index, value in enumerate((revision_one, revision_two, revision_three), start=1):
                path = root / f"r{index}.json"
                path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
                paths.append(path)
            incomplete = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "validate",
                    str(paths[2]),
                    "--previous",
                    str(paths[1]),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertNotEqual(0, incomplete.returncode)
            self.assertIn("FULL_HISTORY_REQUIRED", incomplete.stdout + incomplete.stderr)
            complete = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "validate",
                    str(paths[2]),
                    "--history",
                    str(paths[0]),
                    str(paths[1]),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(0, complete.returncode, complete.stdout + complete.stderr)

    def test_revision_two_cli_rejects_a_forged_root_revision(self):
        forged_root = valid_standard()
        forged_root["previous_case_sha256"] = "0" * 64
        revision_two = self.module.start_update(forged_root, "第二轮新材料。")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            r1 = root / "r1.json"
            r2 = root / "r2.json"
            r1.write_text(json.dumps(forged_root, ensure_ascii=False), encoding="utf-8")
            r2.write_text(json.dumps(revision_two, ensure_ascii=False), encoding="utf-8")
            completed = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "validate",
                    str(r2),
                    "--previous",
                    str(r1),
                ],
                text=True,
                capture_output=True,
                check=False,
            )
        self.assertNotEqual(0, completed.returncode)
        self.assertIn("HISTORY_INVALID", completed.stdout + completed.stderr)

    def test_anchor_cannot_drop_negation_or_scope(self):
        case = valid_standard()
        text = case["inputs"][0]["text"] + "老板没有说要开除我。"
        replace_first_input(case, text)
        case["claims"][0]["text"] = "要开除我"
        case["claims"][0]["exact_quote"] = "要开除我"
        case["evidence"][0]["exact_quote"] = "要开除我"
        self.assertIn("SOURCE_SPAN_MISMATCH", self.codes(case))

    def test_negated_report_does_not_generate_a_positive_inner_quote_span(self):
        spans = self.module.generate_source_spans("I1", "老板没有说：‘我要开除你’。")
        self.assertNotIn("我要开除你", {item["text"] for item in spans})
        unquoted = self.module.generate_source_spans("I1", "老板没有说，他要开除我。")
        self.assertNotIn("他要开除我。", {item["text"] for item in unquoted})
        alternate = self.module.generate_source_spans("I1", "老板从来没讲‘我会开除你’。")
        self.assertNotIn("我会开除你", {item["text"] for item in alternate})
        post_denial = self.module.generate_source_spans(
            "I1", "老板澄清‘我会开除你’不是他说的。"
        )
        self.assertNotIn("我会开除你", {item["text"] for item in post_denial})

    def test_positive_hypothesis_request_can_produce_valid_bounded_hypotheses(self):
        case = valid_standard()
        text = case["inputs"][0]["text"] + "请给我两个待核对的工作假设。"
        replace_first_input(case, text)
        case["hypothesis_request"] = {
            "input_id": "I1",
            "source_span_id": "SP3",
            "source_ref": "input",
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
        self.assertEqual([], self.module.validate_casefile(case))
        case["discriminator"] = {
            "question_type": "formal_role_or_authority_check",
            "question": "我目前的正式职责、决策参与范围或审批权限是否发生变化？",
            "distinguishes": ["H1", "H2"],
            "branches": [
                {
                    "answer_type": "formal_scope_unchanged",
                    "observable_answer": "正式职责或权限保持不变",
                    "updates": [
                        {"target_id": "H1", "effect": "weakens"},
                        {"target_id": "H2", "effect": "strengthens"},
                    ],
                },
                {
                    "answer_type": "formal_scope_changed",
                    "observable_answer": "正式职责或权限发生变化",
                    "updates": [
                        {"target_id": "H1", "effect": "strengthens"},
                        {"target_id": "H2", "effect": "weakens"},
                    ],
                },
            ],
            "risk": "low",
            "reversible": True,
        }
        self.assertIn(
            "DISCRIMINATOR_EFFECT_CONTRADICTS_HYPOTHESIS",
            self.codes(case),
        )

    def test_unverified_infidelity_assertion_cannot_self_label_as_fact(self):
        case = valid_standard()
        text = case["inputs"][0]["text"] + "他已经出轨了。"
        replace_first_input(case, text)
        case["claims"].append(
            {
                "id": "C3",
                "kind": "observable_fact",
                "text": "他已经出轨了。",
                "input_id": "I1",
                "source_span_id": "SP3",
                "source_ref": "input",
                "source_type": "user_direct_observation",
                "exact_quote": "他已经出轨了。",
                "epistemic_status": "reported",
                "diagnostic_boundary": False,
            }
        )
        case["evidence"].append(
            {
                "id": "E2",
                "input_id": "I1",
                "source_span_id": "SP3",
                "source_ref": "input",
                "source_type": "user_direct_observation",
                "exact_quote": "他已经出轨了。",
                "can_establish": ["C3"],
                "cannot_establish": ["C2"],
                "limitations": ["single_party_report"],
            }
        )
        case["evidence_links"].extend(
            [
                {
                    "proposition_id": "C3",
                    "evidence_ref": "E2",
                    "relation": "supports",
                    "strength": "direct",
                    "reason": "anchor_matches_report",
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
        self.assertIn("CLAIM_KIND_MISMATCH", self.codes(case))

    def test_story_synonyms_cannot_self_label_as_atomic_facts(self):
        phrases = (
            "他根本没把我当回事。",
            "老板想把我边缘化。",
            "他就是在惩罚我。",
            "她瞧不起我。",
            "他在冷暴力我。",
            "我就是个失败者。",
            "我天生不配被爱。",
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                case = valid_standard()
                text = case["inputs"][0]["text"] + phrase
                replace_first_input(case, text)
                case["claims"].append(
                    {
                        "id": "C3",
                        "kind": "observable_fact",
                        "text": phrase,
                        "input_id": "I1",
                        "source_span_id": "SP3",
                        "source_ref": "input",
                        "source_type": "user_direct_observation",
                        "exact_quote": phrase,
                        "epistemic_status": "reported",
                        "diagnostic_boundary": False,
                    }
                )
                case["evidence"].append(
                    {
                        "id": "E2",
                        "input_id": "I1",
                        "source_span_id": "SP3",
                        "source_ref": "input",
                        "source_type": "user_direct_observation",
                        "exact_quote": phrase,
                        "can_establish": ["C3"],
                        "cannot_establish": ["C2"],
                        "limitations": ["single_party_report"],
                    }
                )
                case["evidence_links"].extend(
                    [
                        {
                            "proposition_id": "C3",
                            "evidence_ref": "E2",
                            "relation": "supports",
                            "strength": "direct",
                            "reason": "anchor_matches_report",
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
                self.assertIn("FACT_TYPE_UNSUPPORTED", self.codes(case))

    def test_observation_plus_story_is_split_before_fact_classification(self):
        phrases = (
            "他三次没回就是根本不在乎我。",
            "老板连续两次没让我参加会议就是想把我踢出核心圈。",
            "我两周没完成计划证明我这辈子成不了事。",
            "他已读没回是在拿我当备胎。",
            "她回复很慢就是看不起我。",
            "老板取消会议是要暗中削弱我。",
            "老板没有说要开除我但我肯定他在架空我。",
            "他没说不爱我可他就是在冷暴力我。",
            "老板把我的工位搬走是有意孤立我。",
            "老板把我的工位搬走是蓄意排斥我。",
        )
        story_markers = (
            "不在乎", "踢出核心圈", "成不了事", "备胎",
            "看不起", "暗中削弱", "架空", "冷暴力", "孤立", "排斥",
        )
        for phrase in phrases:
            with self.subTest(phrase=phrase):
                spans = self.module.generate_source_spans("I1", phrase)
                self.assertNotIn(phrase, {item["text"] for item in spans})
                for span in spans:
                    if any(marker in span["text"] for marker in story_markers):
                        self.assertIsNone(
                            self.module.derive_observation_type(span["text"], span)
                        )

    def test_common_observations_are_not_limited_to_frozen_phrases(self):
        examples = {
            "他删了我。": "task_or_action_event",
            "老板把我的工位搬走了。": "task_or_action_event",
            "同事迟到了。": "participation_or_schedule_event",
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                span = self.module.generate_source_spans("I1", text)[0]
                self.assertEqual(expected, self.module.derive_observation_type(text, span))

    def test_common_explicit_feelings_are_recognized(self):
        for text in (
            "我很烦。",
            "我心里一沉。",
            "我很紧张。",
            "我很尴尬。",
            "我受够了。",
            "今天我很焦虑。",
            "一想到这件事我很焦虑。",
        ):
            with self.subTest(text=text):
                self.assertTrue(self.module.is_explicit_feeling(text))

    def test_negated_report_only_exempts_its_atomic_clause(self):
        text = "老板没有说要开除我但我肯定他在架空我。"
        spans = self.module.generate_source_spans("I1", text)
        first = next(item for item in spans if "没有说" in item["text"])
        story = next(item for item in spans if "架空" in item["text"])
        self.assertEqual(
            "negative_report_event",
            self.module.derive_observation_type(first["text"], first),
        )
        self.assertIsNone(self.module.derive_observation_type(story["text"], story))

    def test_contrast_after_negated_report_starts_a_new_observation_span(self):
        text = "老板没有说要开除我，却取消了我的会议。"
        spans = self.module.generate_source_spans("I1", text)
        later = next(item for item in spans if "取消" in item["text"])
        self.assertEqual("取消了我的会议。", later["text"])
        self.assertEqual(
            "participation_or_schedule_event",
            self.module.derive_observation_type(later["text"], later),
        )

    def test_sequence_after_negated_report_starts_a_new_observation_span(self):
        text = "老板没有说要开除我，随后取消了我的会议。"
        spans = self.module.generate_source_spans("I1", text)
        later = next(item for item in spans if "取消" in item["text"])
        self.assertEqual("随后取消了我的会议。", later["text"])
        self.assertEqual(
            "participation_or_schedule_event",
            self.module.derive_observation_type(later["text"], later),
        )

    def test_hypothesis_evidence_requires_current_case_source_scope(self):
        hypothesis = {
            "hypothesis_type": "temporary_scope_or_situational_constraint"
        }
        evidence = {
            "source_ref": "A公司2021年截图",
            "exact_quote": "A公司的岗位职责保持不变。",
        }
        self.assertEqual(
            {"does_not_establish"},
            self.module._allowed_relation_for_hypothesis_evidence(
                hypothesis, evidence
            ),
        )
        hidden_in_label = {
            "source_ref": "E2",
            "source_label": "E2｜A公司2021年截图",
            "exact_quote": "岗位职责保持不变。",
        }
        self.assertEqual(
            {"does_not_establish"},
            self.module._allowed_relation_for_hypothesis_evidence(
                hypothesis, hidden_in_label
            ),
        )

    def test_negated_hypothesis_evidence_cannot_reverse_polarity(self):
        hypothesis = {
            "hypothesis_type": "temporary_scope_or_situational_constraint"
        }
        evidence = {
            "source_ref": "E1",
            "exact_quote": "材料并不能证明岗位职责保持不变。",
        }
        self.assertEqual(
            {"does_not_establish"},
            self.module._allowed_relation_for_hypothesis_evidence(
                hypothesis, evidence
            ),
        )
        alternate = {
            "source_ref": "E2",
            "exact_quote": "材料没有佐证岗位职责保持不变。",
        }
        self.assertEqual(
            {"does_not_establish"},
            self.module._allowed_relation_for_hypothesis_evidence(
                hypothesis, alternate
            ),
        )

    def test_hypothesis_request_cannot_be_rewritten_in_a_later_revision(self):
        previous = valid_standard()
        previous_text = previous["inputs"][0]["text"] + "请给我一个待核对的工作假设。"
        replace_first_input(previous, previous_text)
        request_span = next(
            item for item in previous["source_spans"] if "一个待核对" in item["text"]
        )
        previous["hypothesis_request"] = {
            "input_id": "I1",
            "source_span_id": request_span["id"],
            "source_ref": request_span["source_ref"],
            "exact_quote": request_span["text"],
            "requested_count": 1,
        }
        previous["hypotheses"] = [
            {
                "id": "H1",
                "hypothesis_type": "temporary_scope_or_situational_constraint",
                "text": "当前变化可能来自临时范围或情境约束",
                "confidence": "low",
                "support_signals": ["formal_scope_unchanged"],
                "weakening_signals": ["formal_scope_changed"],
                "exit_condition": "formal_scope_changed",
            }
        ]
        self.assertEqual([], self.module.validate_casefile(previous))

        current = self.module.start_update(previous, "第二轮只有新的安排信息。")
        current["hypothesis_request"]["requested_count"] = 2
        current["hypotheses"].append(
            {
                "id": "H2",
                "hypothesis_type": "substantive_role_or_boundary_change",
                "text": "当前变化可能反映职责、边界或优先级的实质调整",
                "confidence": "low",
                "support_signals": ["formal_scope_changed"],
                "weakening_signals": ["formal_scope_unchanged"],
                "exit_condition": "formal_scope_unchanged",
            }
        )
        codes = self.codes(current, previous=previous)
        self.assertIn("HISTORY_ITEM_MUTATED", codes)
        self.assertIn("HYPOTHESIS_REQUEST_COUNT_MISMATCH", codes)

    def test_multisentence_quoted_material_gets_deterministic_atomic_spans(self):
        text = "材料：‘她连续两次临时取消约会。我认为她在故意吊着我，但她没有解释原因。我没有说自己现在是什么感受。’"
        spans = self.module.generate_source_spans("I1", text)
        by_text = {item["text"]: item for item in spans}
        for expected in (
            "她连续两次临时取消约会。",
            "我认为她在故意吊着我，",
            "她没有解释原因。",
            "我没有说自己现在是什么感受。",
        ):
            self.assertIn(expected, by_text)
            self.assertTrue(by_text[expected]["quoted"])
        self.assertEqual(
            "participation_or_schedule_event",
            self.module.derive_observation_type(
                "她连续两次临时取消约会。",
                by_text["她连续两次临时取消约会。"],
            ),
        )
        self.assertEqual(
            "negative_report_event",
            self.module.derive_observation_type(
                "她没有解释原因。", by_text["她没有解释原因。"]
            ),
        )

    def test_interpretation_cannot_be_supported_by_cross_entity_evidence(self):
        case = valid_standard()
        new_text = case["inputs"][0]["text"] + "[新闻截图] 另一家公司员工连续两次没有被邀请参加项目会。"
        replace_first_input(case, new_text)
        foreign_span = next(
            item for item in case["source_spans"] if "另一家公司" in item["text"]
        )
        case["evidence"].append(
            {
                "id": "E2",
                "input_id": "I1",
                "source_span_id": foreign_span["id"],
                "source_ref": foreign_span["source_ref"],
                "source_type": "unverified_artifact",
                "exact_quote": foreign_span["text"],
                "can_establish": ["C2"],
                "cannot_establish": ["C1"],
                "limitations": ["artifact_not_verified", "missing_context"],
            }
        )
        case["evidence_links"].extend(
            [
                {
                    "proposition_id": "C2",
                    "evidence_ref": "E2",
                    "relation": "supports",
                    "strength": "weak",
                    "reason": "behavior_is_compatible_but_not_diagnostic",
                },
                {
                    "proposition_id": "C1",
                    "evidence_ref": "E2",
                    "relation": "does_not_establish",
                    "strength": "none",
                    "reason": "source_scope_limit",
                },
            ]
        )
        case["claims"][1]["epistemic_status"] = "weakly_supported"
        self.assertIn("RELATION_SEMANTICALLY_UNSUPPORTED", self.codes(case))

    def test_unrelated_evidence_cannot_support_an_interpretation(self):
        case = valid_standard()
        text = case["inputs"][0]["text"] + "今天下雨了。"
        replace_first_input(case, text)
        case["evidence"].append(
            {
                "id": "E2",
                "input_id": "I1",
                "source_span_id": "SP3",
                "source_ref": "input",
                "source_type": "user_direct_observation",
                "exact_quote": "今天下雨了。",
                "can_establish": ["C2"],
                "cannot_establish": ["C1"],
                "limitations": ["single_party_report"],
            }
        )
        case["evidence_links"].extend(
            [
                {
                    "proposition_id": "C2",
                    "evidence_ref": "E2",
                    "relation": "supports",
                    "strength": "weak",
                    "reason": "behavior_is_compatible_but_not_diagnostic",
                },
                {
                    "proposition_id": "C1",
                    "evidence_ref": "E2",
                    "relation": "does_not_establish",
                    "strength": "none",
                    "reason": "source_scope_limit",
                },
            ]
        )
        case["claims"][1]["epistemic_status"] = "weakly_supported"
        self.assertIn("RELATION_SEMANTICALLY_UNSUPPORTED", self.codes(case))

    def test_secondhand_context_survives_comma_segmentation(self):
        text = "同事告诉我，老板下个月不会让我续约。"
        spans = self.module.generate_source_spans("I1", text)
        reported = next(item for item in spans if "老板下个月" in item["text"])
        self.assertIn("inferred_secondhand_context", reported["source_label"])

    def test_unknown_text_cannot_inject_headings_or_escalatory_actions(self):
        case = valid_standard()
        case["unknowns"][0]["text"] = "# 新结论\n是否立即报复并曝光对方"
        self.assertIn("UNKNOWN_TEXT_NOT_CANONICAL", self.codes(case))

    def test_unknown_cannot_be_marked_resolved_by_unrelated_new_evidence(self):
        previous = valid_standard()
        current = self.module.start_update(previous, "今天收到一封节日放假通知。")
        current["unknowns"][0].update(
            {"status": "resolved", "resolved_by_evidence_refs": ["E2"]}
        )
        current["claims"].append(
            {
                "id": "C3",
                "kind": "observable_fact",
                "text": "今天收到一封节日放假通知。",
                "input_id": "I2",
                "source_span_id": "SP3",
                "source_ref": "input",
                "source_type": "user_direct_observation",
                "exact_quote": "今天收到一封节日放假通知。",
                "epistemic_status": "reported",
                "diagnostic_boundary": False,
            }
        )
        current["evidence"].append(
            {
                "id": "E2",
                "input_id": "I2",
                "source_span_id": "SP3",
                "source_ref": "input",
                "source_type": "user_direct_observation",
                "exact_quote": "今天收到一封节日放假通知。",
                "can_establish": ["C3"],
                "cannot_establish": ["C2"],
                "limitations": ["single_party_report"],
            }
        )
        current["evidence_links"].extend(
            [
                {
                    "proposition_id": "C3",
                    "evidence_ref": "E2",
                    "relation": "supports",
                    "strength": "direct",
                    "reason": "anchor_matches_report",
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
        self.assertIn(
            "UNKNOWN_RESOLUTION_UNSUPPORTED",
            self.codes(current, previous=previous),
        )

    def test_interpretation_cannot_self_label_as_observable_fact(self):
        case = valid_standard()
        case["claims"][1].update(
            {
                "kind": "observable_fact",
                "source_type": "user_direct_observation",
                "epistemic_status": "reported",
            }
        )
        codes = self.codes(case)
        self.assertTrue({"CLAIM_KIND_MISMATCH", "FACT_SUPPORT_REQUIRED"} & codes)

    def test_hypothesis_request_cannot_drop_a_negation_prefix(self):
        case = valid_standard()
        text = case["inputs"][0]["text"] + "不要给我两个工作假设。"
        replace_first_input(case, text)
        case["hypothesis_request"] = {
            "input_id": "I1",
            "source_span_id": "SP3",
            "exact_quote": "给我两个工作假设",
            "requested_count": 2,
        }
        case["hypotheses"] = [
            {
                "id": "H1",
                "text": "会议范围临时缩小",
                "confidence": "low",
                "support_signals": ["职责保持不变"],
                "weakening_signals": ["职责正式削减"],
                "exit_condition": "职责正式削减",
            },
            {
                "id": "H2",
                "text": "职责正在削减",
                "confidence": "low",
                "support_signals": ["职责正式削减"],
                "weakening_signals": ["职责保持不变"],
                "exit_condition": "职责保持不变",
            },
        ]
        self.assertIn("HYPOTHESIS_NOT_REQUESTED", self.codes(case))

    def test_full_negative_hypothesis_request_is_rejected(self):
        case = valid_standard()
        text = case["inputs"][0]["text"] + "不许给我一个假设。"
        replace_first_input(case, text)
        case["hypothesis_request"] = {
            "input_id": "I1",
            "source_span_id": "SP3",
            "source_ref": "input",
            "exact_quote": "不许给我一个假设。",
            "requested_count": 1,
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
            }
        ]
        self.assertIn("HYPOTHESIS_NOT_REQUESTED", self.codes(case))

    def test_forbidden_diagnosis_or_infidelity_cannot_enter_hypotheses(self):
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
                "text": "他是 NPD",
                "confidence": "low",
                "support_signals": ["他不回消息"],
                "weakening_signals": ["他回复消息"],
                "exit_condition": "他回复消息",
            },
            {
                "id": "H2",
                "text": "他已经出轨",
                "confidence": "low",
                "support_signals": ["他不回消息"],
                "weakening_signals": ["他回复消息"],
                "exit_condition": "他回复消息",
            },
        ]
        self.assertIn("HYPOTHESIS_TYPE_REQUIRED", self.codes(case))

    def test_user_decisions_use_finite_non_action_scopes(self):
        case = valid_standard()
        case["user_decisions"] = ["立即辞职并公开报复老板"]
        self.assertIn("DECISION_SCOPE_REQUIRED", self.codes(case))

    def test_safety_detector_catches_weapon_and_medical_language(self):
        self.assertTrue(self.module.detect_immediate_risk("他十分钟后带斧头来收拾我"))
        self.assertTrue(self.module.detect_immediate_risk("我胸痛而且呼吸困难"))
        self.assertTrue(self.module.detect_immediate_risk("He said he will stab me tonight"))
        self.assertTrue(self.module.detect_immediate_risk("他现在就在门外，扬言让我见不到明天"))
        self.assertTrue(self.module.detect_immediate_risk("我准备结束自己的生命"))
        self.assertTrue(self.module.detect_immediate_risk("有人持刀在门外等我"))
        self.assertTrue(self.module.detect_immediate_risk("法院通知我今天是上诉最后期限"))
        self.assertFalse(self.module.detect_immediate_risk("我没有胸痛，也没有呼吸困难"))

    def test_safety_detector_catches_disappear_and_end_everything_language(self):
        self.assertTrue(self.module.detect_immediate_risk("他威胁明天让我消失。"))
        self.assertIn(
            "explicit_threat",
            self.module.expected_safety_signal_types("他威胁明天让我消失。"),
        )
        self.assertTrue(self.module.detect_immediate_risk("我想结束这一切。"))
        self.assertIn(
            "self_harm_risk",
            self.module.expected_safety_signal_types("我想结束这一切。"),
        )
        self.assertFalse(self.module.detect_immediate_risk("我想结束这段合作关系。"))

    def test_medical_signal_requires_medical_support_action(self):
        case = valid_safety()
        text = "我胸痛而且呼吸困难。"
        replace_first_input(case, text)
        case["safety"] = {
            "risk_signals": [
                {
                    "input_id": "I1",
                    "source_span_id": "SP1",
                    "source_ref": "input",
                    "exact_quote": text,
                    "signal_type": "medical_emergency",
                    "routing_basis": "deterministic_backstop",
                }
            ]
        }
        self.assertIn("SAFETY_SUPPORT_MISMATCH", self.codes(case))

    def test_medical_signal_cannot_self_label_as_other_risk(self):
        case = valid_safety()
        text = "我胸痛而且呼吸困难。"
        replace_first_input(case, text)
        case["safety"] = {
            "risk_signals": [
                {
                    "input_id": "I1",
                    "source_span_id": "SP1",
                    "source_ref": "input",
                    "exact_quote": text,
                    "signal_type": "other_immediate_risk",
                    "routing_basis": "deterministic_backstop",
                }
            ]
        }
        self.assertIn("SAFETY_SIGNAL_TYPE_MISMATCH", self.codes(case))

    def test_urgent_legal_support_can_be_the_first_action(self):
        case = valid_safety()
        text = "法院文件显示今天是紧迫期限。"
        replace_first_input(case, text)
        case["safety"] = {
            "risk_signals": [
                {
                    "input_id": "I1",
                    "source_span_id": "SP1",
                    "source_ref": "input",
                    "exact_quote": text,
                    "signal_type": "urgent_legal_risk",
                    "routing_basis": "deterministic_backstop",
                }
            ]
        }
        case["actions"] = [
            {
                "id": "A1",
                "action_type": "seek_legal_support",
                "text": "尽快联系当地合格法律支持，避免错过紧迫期限",
                "timing": "immediate",
                "risk": "low",
                "reversible": True,
                "motive_independent": True,
                "produces_new_evidence": False,
            }
        ]
        self.assertEqual([], self.module.validate_casefile(case))

    def test_new_safety_revision_requires_a_current_input_signal(self):
        previous = valid_safety()
        current = self.module.start_update(previous, "他十分钟后带斧头来。")
        self.assertIn(
            "CURRENT_SAFETY_SIGNAL_REQUIRED",
            self.codes(current, previous=previous),
        )

    def test_quote_detector_does_not_cross_two_quote_spans(self):
        text = "老板说：“下午见”。我认为他真会架空我。后来他说：“明天见”。"
        self.assertFalse(self.module._quote_is_bounded(text, "我认为他真会架空我"))

    def test_one_evidence_target_pair_cannot_have_two_relations(self):
        case = valid_standard()
        case["evidence_links"].insert(
            1,
            {
                "proposition_id": "C2",
                "evidence_ref": "E1",
                "relation": "supports",
                "strength": "weak",
                "reason": "behavior_is_compatible_but_not_diagnostic",
            },
        )
        case["claims"][1]["epistemic_status"] = "weakly_supported"
        self.assertIn("DUPLICATE_LINK_TARGET", self.codes(case))

    def test_evidence_link_cannot_exceed_declared_scope(self):
        case = valid_standard()
        case["evidence_links"][1].update(
            {
                "relation": "supports",
                "strength": "weak",
                "reason": "behavior_is_compatible_but_not_diagnostic",
            }
        )
        case["claims"][1]["epistemic_status"] = "weakly_supported"
        self.assertIn("EVIDENCE_LINK_SCOPE_UNDECLARED", self.codes(case))

    def test_unknown_resolution_is_not_self_attestable(self):
        previous = valid_standard()
        current = self.module.start_update(previous, "没有任何新信息。")
        current["unknowns"][0]["status"] = "resolved"
        current["unknowns"][0]["resolved_by_evidence_refs"] = ["E1"]
        self.assertIn("UNKNOWN_RESOLUTION_UNSUPPORTED", self.codes(current, previous=previous))

    def test_discriminator_branches_must_really_differ(self):
        case = valid_standard()
        case["discriminator"]["branches"][1] = copy.deepcopy(
            case["discriminator"]["branches"][0]
        )
        self.assertIn("DISCRIMINATOR_BRANCHES_NOT_DISTINCT", self.codes(case))

    def test_target_ids_are_globally_unique(self):
        case = valid_standard()
        text = case["inputs"][0]["text"] + "请给我一个待核对的工作假设。"
        replace_first_input(case, text)
        case["hypothesis_request"] = {
            "input_id": "I1",
            "source_span_id": "SP3",
            "exact_quote": "请给我一个待核对的工作假设。",
            "requested_count": 1,
        }
        case["hypotheses"] = [
            {
                "id": "C1",
                "text": "会议范围临时缩小",
                "confidence": "low",
                "support_signals": ["职责保持不变"],
                "weakening_signals": ["职责正式削减"],
                "exit_condition": "职责正式削减",
            }
        ]
        self.assertIn("GLOBAL_ID_COLLISION", self.codes(case))


if __name__ == "__main__":
    unittest.main()
