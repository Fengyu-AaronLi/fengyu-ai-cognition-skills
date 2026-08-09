import importlib.util
import unittest

from test_casefile import SCRIPT, replace_first_input, valid_standard


def load_runtime():
    spec = importlib.util.spec_from_file_location("round5_semantic_runtime", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def bounded_hypothesis():
    return {
        "id": "H1",
        "hypothesis_type": "temporary_scope_or_situational_constraint",
        "text": "当前变化可能来自临时范围或情境约束",
        "confidence": "low",
        "support_signals": ["formal_scope_unchanged"],
        "weakening_signals": ["formal_scope_changed"],
        "exit_condition": "formal_scope_changed",
    }


class Round5SemanticRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_runtime()

    def appended_case(self, text):
        case = valid_standard()
        replace_first_input(case, case["inputs"][0]["text"] + text)
        return case

    def codes(self, case):
        return {item["code"] for item in self.module.validate_casefile(case)}

    def observable_fact_case(self, text):
        case = self.appended_case(text)
        span = next(
            (
                item
                for item in case["source_spans"]
                if not item["quoted"] and item["text"] == text
            ),
            None,
        )
        if span is None:
            return None
        observation_type = self.module.derive_observation_type(span["text"], span)
        if observation_type is None:
            return None
        case["claims"][0].update(
            {
                "observation_type": observation_type,
                "text": span["text"],
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "user_direct_observation",
                "exact_quote": span["text"],
            }
        )
        case["evidence"][0].update(
            {
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "user_direct_observation",
                "exact_quote": span["text"],
            }
        )
        return case

    def explicit_feeling_case(self, text):
        case = self.appended_case(text)
        span = next(
            (
                item
                for item in case["source_spans"]
                if not item["quoted"] and item["text"] == text
            ),
            None,
        )
        if span is None:
            return None
        case["claims"].append(
            {
                "id": "C3",
                "kind": "explicit_feeling",
                "text": span["text"],
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "explicit_self_report",
                "exact_quote": span["text"],
                "epistemic_status": "reported",
                "diagnostic_boundary": False,
            }
        )
        case["evidence"].append(
            {
                "id": "E2",
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "explicit_self_report",
                "exact_quote": span["text"],
                "can_establish": ["C3"],
                "cannot_establish": [],
                "limitations": ["single_party_report"],
            }
        )
        case["evidence_links"].append(
            {
                "proposition_id": "C3",
                "evidence_ref": "E2",
                "relation": "supports",
                "strength": "direct",
                "reason": "anchor_matches_report",
            }
        )
        return case

    def stated_position_case(self, text, quote):
        case = self.appended_case(text)
        span = next(
            (
                item
                for item in case["source_spans"]
                if item["quoted"] and item["text"] == quote
            ),
            None,
        )
        if span is None:
            return None
        case["claims"].append(
            {
                "id": "C3",
                "kind": "stated_position",
                "text": span["text"],
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "direct_quote",
                "exact_quote": span["text"],
                "epistemic_status": "directly_stated",
                "diagnostic_boundary": False,
            }
        )
        case["evidence"].append(
            {
                "id": "E2",
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "direct_quote",
                "exact_quote": span["text"],
                "can_establish": ["C3"],
                "cannot_establish": [],
                "limitations": ["single_party_report"],
            }
        )
        case["evidence_links"].append(
            {
                "proposition_id": "C3",
                "evidence_ref": "E2",
                "relation": "supports",
                "strength": "direct",
                "reason": "direct_current_statement_only",
            }
        )
        return case

    def denied_hypothesis_case(self, text):
        case = self.appended_case(text)
        span = next(
            item
            for item in case["source_spans"][2:]
            if not item["quoted"] and "假设" in item["text"]
        )
        case["hypothesis_request"] = {
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "exact_quote": span["text"],
            "requested_count": 1,
        }
        case["hypotheses"] = [bounded_hypothesis()]
        return case

    def test_diagnosis_identity_motive_and_prediction_cannot_enter_fact_spans(self):
        examples = (
            "他患ADHD还删除了文档。",
            "他是控制狂还拉黑了我。",
            "老板取消会议存心让我出丑。",
            "老板取消会议迟早会把我开除。",
        )
        for text in examples:
            with self.subTest(text=text):
                case = self.observable_fact_case(text)
                if case is None:
                    continue
                self.assertTrue(
                    {"FACT_TYPE_UNSUPPORTED", "CLAIM_KIND_MISMATCH"}
                    & self.codes(case),
                    "diagnosis, identity, motive, or prediction entered observable_fact",
                )

    def test_reported_or_performed_feelings_cannot_become_user_self_reports(self):
        examples = (
            "我看到经理很焦虑。",
            "妈妈说我很伤心。",
            "大家都觉得我很焦虑。",
            "我假装很难过。",
        )
        for text in examples:
            with self.subTest(text=text):
                case = self.explicit_feeling_case(text)
                if case is None:
                    continue
                self.assertTrue(
                    {"CLAIM_KIND_MISMATCH", "SOURCE_TYPE_MISMATCH"}
                    & self.codes(case),
                    "a third-party attribution or performed feeling became an explicit self-report",
                )

    def test_new_messenger_and_hearsay_forms_remain_secondhand(self):
        examples = (
            "领导跟我说会议取消了。",
            "我从同事那里得知会议取消了。",
            "同事声称会议取消了。",
            "HR说会议取消了。",
        )
        for text in examples:
            with self.subTest(text=text):
                case = self.observable_fact_case(text)
                if case is None:
                    continue
                self.assertIn(
                    "SOURCE_TYPE_MISMATCH",
                    self.codes(case),
                    "a hearsay variant impersonated the user's direct observation",
                )

    def test_denied_or_uncertain_quote_variants_are_not_stated_positions(self):
        examples = (
            ("他不曾说过“我会回来”。", "我会回来"),
            ("他哪里说过“我会回来”。", "我会回来"),
            ("我依稀记得他说过“我会回来”。", "我会回来"),
            ("他或许说过“我会回来”。", "我会回来"),
        )
        for text, quote in examples:
            with self.subTest(text=text):
                case = self.stated_position_case(text, quote)
                if case is None:
                    continue
                self.assertTrue(
                    {"DIRECT_QUOTE_NOT_ASSERTED", "SOURCE_TYPE_MISMATCH"}
                    & self.codes(case),
                    "a denied or uncertain quote became a directly stated position",
                )

    def test_refusal_variants_do_not_authorize_hypotheses(self):
        for text in (
            "不必给任何假设，只要事实。",
            "假设并不是我所需要的，请做事实表。",
        ):
            with self.subTest(text=text):
                self.assertIn(
                    "HYPOTHESIS_NOT_REQUESTED",
                    self.codes(self.denied_hypothesis_case(text)),
                    "a refusal variant authorized a working hypothesis",
                )

    def test_common_immediate_risk_variants_route_to_safety(self):
        examples = {
            "我想去死。": "self_harm_risk",
            "我准备寻短见。": "self_harm_risk",
            "他握着刀在门外等我。": "explicit_threat",
            "我胸口剧痛而且喘不上气。": "medical_emergency",
        }
        for text, signal_type in examples.items():
            with self.subTest(text=text):
                self.assertTrue(
                    self.module.detect_immediate_risk(text),
                    "a common immediate-risk phrase stayed in standard routing",
                )
                self.assertIn(
                    signal_type,
                    self.module.expected_safety_signal_types(text),
                    "the safety route could not build a typed anchored signal",
                )

        for text in (
            "我并不想去死。",
            "我从没想过寻短见。",
            "电影里的角色说“我想去死”。",
            "他没有握着刀在门外等我。",
        ):
            with self.subTest(text=text):
                self.assertFalse(
                    self.module.detect_immediate_risk(text),
                    "a denial or fictional mention triggered immediate-risk routing",
                )


if __name__ == "__main__":
    unittest.main()
