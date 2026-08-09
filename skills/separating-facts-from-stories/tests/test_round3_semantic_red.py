import importlib.util
import unittest

from test_casefile import SCRIPT, replace_first_input, valid_standard


def load_runtime():
    spec = importlib.util.spec_from_file_location("round3_semantic_runtime", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Round3SemanticRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_runtime()

    def codes(self, case):
        return {item["code"] for item in self.module.validate_casefile(case)}

    def appended_case(self, text):
        case = valid_standard()
        replace_first_input(case, case["inputs"][0]["text"] + text)
        return case

    def fact_case(self, text, observation_type):
        case = self.appended_case(text)
        span = next(
            (item for item in case["source_spans"] if item["text"] == text),
            None,
        )
        if span is None:
            return None
        case["claims"][0].update(
            {
                "observation_type": observation_type,
                "text": span["text"],
                "source_span_id": span["id"],
                "exact_quote": span["text"],
            }
        )
        case["evidence"][0].update(
            {
                "source_span_id": span["id"],
                "exact_quote": span["text"],
            }
        )
        return case

    def feeling_case(self, text):
        case = self.appended_case(text)
        span = next(
            (item for item in case["source_spans"] if item["text"] == text),
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

    def secondhand_span(self, case, event_fragment):
        return next(
            (
                item
                for item in case["source_spans"]
                if not item["quoted"] and event_fragment in item["text"]
            ),
            None,
        )

    def test_diagnosis_or_motive_cannot_share_an_observable_fact_span(self):
        examples = {
            "他有双相情感障碍并拉黑了我。": "task_or_action_event",
            "他删除文档以报复我。": "artifact_or_system_state",
        }
        for text, observation_type in examples.items():
            with self.subTest(text=text):
                case = self.fact_case(text, observation_type)
                if case is None:
                    continue
                self.assertTrue(
                    {"FACT_TYPE_UNSUPPORTED", "CLAIM_KIND_MISMATCH"}
                    & self.codes(case),
                    "a diagnosis or motive was accepted inside an observable fact span",
                )

    def test_fear_plus_diagnosis_is_not_a_pure_explicit_feeling_span(self):
        case = self.feeling_case("我害怕他是NPD。")
        if case is None:
            return
        self.assertIn("CLAIM_KIND_MISMATCH", self.codes(case))

    def test_other_persons_anger_is_not_the_users_explicit_feeling(self):
        case = self.feeling_case("他对我很生气。")
        if case is None:
            return
        self.assertIn("CLAIM_KIND_MISMATCH", self.codes(case))

    def test_secondhand_reports_cannot_impersonate_direct_observation(self):
        examples = {
            "据说老板取消了会议。": ("取消了会议", "participation_or_schedule_event"),
            "朋友说他删除了文档。": ("删除了文档", "artifact_or_system_state"),
        }
        for text, (event_fragment, observation_type) in examples.items():
            with self.subTest(text=text):
                case = self.appended_case(text)
                span = self.secondhand_span(case, event_fragment)
                self.assertIsNotNone(span)
                case["claims"][0].update(
                    {
                        "observation_type": observation_type,
                        "text": span["text"],
                        "source_span_id": span["id"],
                        "source_type": "user_direct_observation",
                        "exact_quote": span["text"],
                    }
                )
                case["evidence"][0].update(
                    {
                        "source_span_id": span["id"],
                        "source_type": "user_direct_observation",
                        "exact_quote": span["text"],
                    }
                )
                self.assertIn("SOURCE_TYPE_MISMATCH", self.codes(case))

    def test_secondhand_evidence_requires_a_secondhand_limitation(self):
        examples = {
            "据说老板取消了会议。": "取消了会议",
            "朋友说他删除了文档。": "删除了文档",
        }
        for text, event_fragment in examples.items():
            with self.subTest(text=text):
                case = self.appended_case(text)
                span = self.secondhand_span(case, event_fragment)
                self.assertIsNotNone(span)
                case["evidence"].append(
                    {
                        "id": "E2",
                        "input_id": span["input_id"],
                        "source_span_id": span["id"],
                        "source_ref": span["source_ref"],
                        "source_type": "secondhand",
                        "exact_quote": span["text"],
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
                errors = self.module.validate_casefile(case)
                self.assertTrue(
                    any(item["path"] == "/evidence/1/limitations" for item in errors),
                    "secondhand evidence validated without the secondhand limitation",
                )

    def test_qualified_quote_cannot_be_truncated_into_a_stated_position(self):
        case = self.stated_position_case(
            "他说“我会留下但只是暂时”。",
            "我会留下",
        )
        if case is None:
            return
        self.assertTrue(
            self.module.validate_casefile(case),
            "a qualified quote was truncated into a complete stated position",
        )

    def test_desired_quote_cannot_become_the_other_persons_stated_position(self):
        case = self.stated_position_case(
            "我希望他说“我会留下”。",
            "我会留下",
        )
        if case is None:
            return
        self.assertTrue(
            self.module.validate_casefile(case),
            "a desired quote was accepted as the other person's direct position",
        )

    def test_fact_after_negated_report_keeps_an_independent_span(self):
        text = "老板没有说要开除我，给我发了升职邮件。"
        spans = self.module.generate_source_spans("I1", text)
        fact = next(
            (item for item in spans if item["text"] == "给我发了升职邮件。"),
            None,
        )
        self.assertIsNotNone(fact, "the independent fact after the negation was dropped")
        self.assertIsNotNone(
            self.module.derive_observation_type(fact["text"], fact)
        )


if __name__ == "__main__":
    unittest.main()
