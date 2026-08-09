import copy
import importlib.util
import unittest

from test_casefile import SCRIPT, replace_first_input, valid_safety, valid_standard


def load_runtime():
    spec = importlib.util.spec_from_file_location("casefile_round3_history_red", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def hypothesis() -> dict:
    return {
        "id": "H1",
        "hypothesis_type": "temporary_scope_or_situational_constraint",
        "text": "当前变化可能来自临时范围或情境约束",
        "confidence": "low",
        "support_signals": ["formal_scope_unchanged"],
        "weakening_signals": ["formal_scope_changed"],
        "exit_condition": "formal_scope_changed",
    }


class Round3HistoryRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_runtime()

    def codes(self, case, previous=None):
        return {
            item["code"]
            for item in self.module.validate_casefile(case, previous=previous)
        }

    def safety_history(self):
        previous = valid_safety()
        previous["actions"].append(
            {
                "id": "A2",
                "action_type": "contact_trusted_person",
                "text": "立即联系可信任的人，告知当前位置并保持联系",
                "timing": "immediate",
                "risk": "low",
                "reversible": True,
                "motive_independent": True,
                "produces_new_evidence": False,
            }
        )
        previous["user_decisions"] = [
            "professional_support",
            "relationship_boundary",
        ]
        self.assertEqual([], self.module.validate_casefile(previous))

        current = self.module.start_update(previous, "第二轮只有一条普通更新。")
        self.assertEqual(
            [], self.module.validate_casefile(current, previous=previous)
        )
        return previous, current

    def standard_to_safety(self):
        previous = valid_standard()
        current = self.module.start_update(
            previous, "他刚发来消息说十五分钟后到我家堵我。"
        )
        current_span = next(
            item
            for item in current["source_spans"]
            if item["input_id"] == current["current_input_id"]
        )
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
                    "input_id": current_span["input_id"],
                    "source_span_id": current_span["id"],
                    "source_ref": current_span["source_ref"],
                    "exact_quote": current_span["text"],
                    "signal_type": "explicit_threat",
                    "routing_basis": "deterministic_backstop",
                }
            ]
        }
        return previous, current

    def case_with_denied_hypothesis_request(self, text, anchor_text):
        case = valid_standard()
        replace_first_input(case, case["inputs"][0]["text"] + text)
        request_span = next(
            item for item in case["source_spans"] if item["text"] == anchor_text
        )
        case["hypothesis_request"] = {
            "input_id": request_span["input_id"],
            "source_span_id": request_span["id"],
            "source_ref": request_span["source_ref"],
            "exact_quote": request_span["text"],
            "requested_count": 1,
        }
        case["hypotheses"] = [hypothesis()]
        return case

    def test_safety_revision_cannot_remove_prior_history_fields(self):
        previous, current = self.safety_history()
        mutations = {
            "risk_signals": lambda case: case["safety"]["risk_signals"].pop(),
            "mode": lambda case: case.pop("mode"),
            "actions": lambda case: case["actions"].pop(),
            "user_decisions": lambda case: case["user_decisions"].pop(),
            "discriminator": lambda case: case.pop("discriminator"),
        }
        for field, mutate in mutations.items():
            with self.subTest(field=field):
                candidate = copy.deepcopy(current)
                mutate(candidate)
                self.assertIn(
                    "HISTORY_ITEM_REMOVED",
                    self.codes(candidate, previous=previous),
                )

    def test_safety_revision_cannot_reorder_prior_history_lists(self):
        previous, current = self.safety_history()
        mutations = {
            "risk_signals": lambda case: case["safety"]["risk_signals"].reverse(),
            "actions": lambda case: case["actions"].reverse(),
            "user_decisions": lambda case: case["user_decisions"].reverse(),
        }
        for field, mutate in mutations.items():
            with self.subTest(field=field):
                candidate = copy.deepcopy(current)
                mutate(candidate)
                self.assertIn(
                    "HISTORY_ITEM_MUTATED",
                    self.codes(candidate, previous=previous),
                )

    def test_safety_revision_cannot_rewrite_prior_history_fields(self):
        previous, current = self.safety_history()

        def rewrite_risk_signal(case):
            case["safety"]["risk_signals"][0] = copy.deepcopy(
                case["safety"]["risk_signals"][1]
            )

        def rewrite_action(case):
            case["actions"][1] = {
                "id": "A2",
                "action_type": "avoid_contact_or_confrontation",
                "text": "不要开门、单独见面或当面对质",
                "timing": "immediate",
                "risk": "low",
                "reversible": True,
                "motive_independent": True,
                "produces_new_evidence": False,
            }

        def rewrite_user_decision(case):
            case["user_decisions"][1] = "communication_boundary"

        mutations = {
            "risk_signals": rewrite_risk_signal,
            "mode": lambda case: case.__setitem__("mode", "standard"),
            "actions": rewrite_action,
            "user_decisions": rewrite_user_decision,
            "discriminator": lambda case: case.__setitem__("discriminator", {}),
        }
        for field, mutate in mutations.items():
            with self.subTest(field=field):
                candidate = copy.deepcopy(current)
                mutate(candidate)
                self.assertIn(
                    "HISTORY_ITEM_MUTATED",
                    self.codes(candidate, previous=previous),
                )

    def test_standard_to_safety_may_preserve_prior_analysis_unchanged(self):
        previous, current = self.standard_to_safety()
        for field in ("claims", "evidence", "unknowns", "discriminator"):
            with self.subTest(field=field):
                self.assertEqual(previous[field], current[field])
        self.assertEqual([], self.module.validate_casefile(current, previous=previous))

    def test_standard_to_safety_cannot_rewrite_prior_analysis(self):
        previous, current = self.standard_to_safety()

        def rewrite_claim(case):
            case["claims"][0]["text"] = "老板每次都没让我参加会议。"

        def rewrite_evidence(case):
            case["evidence"][0]["limitations"] = ["time_scope_limited"]

        def rewrite_unknown(case):
            case["unknowns"][0] = {
                "id": "U1",
                "unknown_type": "event_cause_or_context",
                "text": "当前事件的具体原因或上下文是什么",
                "status": "open",
                "resolved_by_evidence_refs": [],
            }

        for field, mutate in {
            "claims": rewrite_claim,
            "evidence": rewrite_evidence,
            "unknowns": rewrite_unknown,
        }.items():
            with self.subTest(field=field):
                candidate = copy.deepcopy(current)
                mutate(candidate)
                codes = self.codes(candidate, previous=previous)
                self.assertIn("SAFETY_ANALYSIS_NOT_ALLOWED", codes)
                self.assertIn("HISTORY_ITEM_MUTATED", codes)

    def test_hypothesis_please_do_not_give_even_one_is_not_authorization(self):
        case = self.case_with_denied_hypothesis_request(
            "假设请一个也别给", "假设请一个也别给"
        )
        self.assertIn("HYPOTHESIS_NOT_REQUESTED", self.codes(case))

    def test_no_candidates_just_organize_facts_is_not_authorization(self):
        case = self.case_with_denied_hypothesis_request(
            "不要候选，请整理事实", "不要候选，"
        )
        self.assertIn("HYPOTHESIS_NOT_REQUESTED", self.codes(case))


if __name__ == "__main__":
    unittest.main()
