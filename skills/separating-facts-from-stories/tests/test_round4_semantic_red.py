import importlib.util
import unittest

from test_casefile import SCRIPT, replace_first_input, valid_standard


def load_runtime():
    spec = importlib.util.spec_from_file_location("round4_semantic_runtime", SCRIPT)
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


class Round4SemanticRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_runtime()

    def appended_case(self, text):
        case = valid_standard()
        replace_first_input(case, case["inputs"][0]["text"] + text)
        return case

    def codes(self, case):
        return {item["code"] for item in self.module.validate_casefile(case)}

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

    def denied_hypothesis_case(self, text):
        case = self.appended_case(text)
        span = next(
            item
            for item in case["source_spans"][2:]
            if not item["quoted"]
            and any(marker in item["text"] for marker in ("假设", "可能性"))
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

    def test_adverbial_negation_cannot_turn_a_denied_quote_into_a_position(self):
        examples = (
            ("他并没有亲口说“我不爱你”。", "我不爱你"),
            ("老板并未当面讲过“我要架空你”。", "我要架空你"),
            ("他本来想说“我会回来”但没说出口。", "我会回来"),
        )
        for text, quote in examples:
            with self.subTest(text=text):
                case = self.stated_position_case(text, quote)
                if case is None:
                    continue
                self.assertTrue(
                    {
                        "DIRECT_QUOTE_NOT_ASSERTED",
                        "SOURCE_TYPE_MISMATCH",
                    }
                    & self.codes(case),
                    "a denied or unrealized quotation became a stated position",
                )

    def test_uncertain_or_secondhand_quote_cannot_claim_direct_attribution(self):
        examples = (
            ("据小王回忆，他说“我会留下”。", "我会留下"),
            ("小张告诉我，他说“我会回来”。", "我会回来"),
            ("我记得他好像说过“我会回来”。", "我会回来"),
            ("我担心他会说“我不爱你”。", "我不爱你"),
        )
        for text, quote in examples:
            with self.subTest(text=text):
                case = self.stated_position_case(text, quote)
                if case is None:
                    continue
                self.assertTrue(
                    {
                        "DIRECT_QUOTE_NOT_ASSERTED",
                        "SOURCE_TYPE_MISMATCH",
                    }
                    & self.codes(case),
                    "an uncertain, anticipated, or secondhand quote claimed direct attribution",
                )

    def test_messenger_variants_remain_secondhand(self):
        examples = (
            "同学告诉我老板取消了会议。",
            "室友说老板删除了文档。",
            "小王转告我老板删除了文档。",
            "我听小王说老板取消了会议。",
        )
        for text in examples:
            with self.subTest(text=text):
                case = self.observable_fact_case(text)
                if case is None:
                    continue
                self.assertIn(
                    "SOURCE_TYPE_MISMATCH",
                    self.codes(case),
                    "a reported event impersonated the user's direct observation",
                )

    def test_other_persons_feeling_cannot_borrow_the_users_subject(self):
        examples = (
            "我看到他很难过。",
            "我觉得老板很焦虑。",
            "我知道她很害怕。",
            "我发现同事很不安。",
        )
        for text in examples:
            with self.subTest(text=text):
                case = self.explicit_feeling_case(text)
                if case is None:
                    continue
                self.assertIn(
                    "CLAIM_KIND_MISMATCH",
                    self.codes(case),
                    "another person's inferred feeling was accepted as the user's feeling",
                )

    def test_mixed_user_feeling_and_third_party_proposition_is_not_one_feeling(self):
        for text in ("我担心他很难过。", "我害怕老板很生气。"):
            with self.subTest(text=text):
                case = self.explicit_feeling_case(text)
                if case is None:
                    continue
                self.assertIn(
                    "CLAIM_KIND_MISMATCH",
                    self.codes(case),
                    "a real user feeling smuggled an unverified third-party feeling",
                )

    def test_new_diagnosis_or_motive_words_cannot_hide_inside_action_facts(self):
        examples = (
            "他患抑郁症还把我删了。",
            "他有躁狂症并删除文档。",
            "老板删掉文档出于恶意。",
            "老板取消会议借此羞辱我。",
        )
        for text in examples:
            with self.subTest(text=text):
                case = self.observable_fact_case(text)
                if case is None:
                    continue
                self.assertTrue(
                    {"FACT_TYPE_UNSUPPORTED", "CLAIM_KIND_MISMATCH"}
                    & self.codes(case),
                    "diagnosis or motive language was accepted inside an observable fact",
                )

    def test_refusal_paraphrases_do_not_authorize_hypotheses(self):
        examples = (
            "不要推测，给我一个工作假设是不可以的。",
            "我不是让你给假设，请给我一个事实表格。",
            "给我一个不包含假设的版本。",
        )
        for text in examples:
            with self.subTest(text=text):
                self.assertIn(
                    "HYPOTHESIS_NOT_REQUESTED",
                    self.codes(self.denied_hypothesis_case(text)),
                    "a refusal paraphrase was misread as hypothesis authorization",
                )


if __name__ == "__main__":
    unittest.main()
