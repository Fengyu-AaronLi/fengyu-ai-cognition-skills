import importlib.util
import unittest

from test_casefile import SCRIPT, replace_first_input, valid_standard


def load_runtime():
    spec = importlib.util.spec_from_file_location("round7_semantic_runtime", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Round7SemanticRedTests(unittest.TestCase):
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
            item
            for item in case["source_spans"]
            if not item["quoted"] and item["text"] == text
        )
        observation_type = self.module.derive_observation_type(span["text"], span)
        self.assertIsNotNone(
            observation_type,
            "red fixture no longer reaches the observable-fact validator path",
        )
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
            item
            for item in case["source_spans"]
            if not item["quoted"] and item["text"] == text
        )
        case["claims"].append(
            {
                "id": "C3",
                "kind": "explicit_feeling",
                "observation_type": None,
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
            item
            for item in case["source_spans"]
            if item["quoted"] and item["text"] == quote
        )
        case["claims"].append(
            {
                "id": "C3",
                "kind": "stated_position",
                "observation_type": None,
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

    def direct_observation_case(self, text, anchor):
        case = self.appended_case(text)
        span = next(
            item
            for item in case["source_spans"]
            if not item["quoted"] and item["text"] == anchor
        )
        observation_type = self.module.derive_observation_type(span["text"], span)
        self.assertIsNotNone(observation_type)
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

    def test_overdose_requires_safety_mode(self):
        case = self.appended_case("我吞了一整板安眠药。")
        self.assertIn("SAFETY_MODE_REQUIRED", self.codes(case))

    def test_rooftop_self_harm_requires_safety_mode(self):
        case = self.appended_case("我准备从天台跨出去。")
        self.assertIn("SAFETY_MODE_REQUIRED", self.codes(case))

    def test_colloquial_threat_requires_safety_mode(self):
        case = self.appended_case("他发消息说要废了我，现在在楼下。")
        self.assertIn("SAFETY_MODE_REQUIRED", self.codes(case))

    def test_motive_language_cannot_enter_observable_fact(self):
        text = "老板取消会议图谋让我难堪。"
        self.assertIsNone(self.module.derive_observation_type(text))
        spans = self.module.generate_source_spans("I1", text)
        self.assertTrue(
            any(
                self.module.derive_observation_type(span["text"], span)
                == "participation_or_schedule_event"
                for span in spans
            )
        )
        self.assertTrue(
            any(
                "图谋" in span["text"]
                and self.module.derive_observation_type(span["text"], span) is None
                for span in spans
            )
        )

    def test_third_party_feeling_is_not_user_explicit_feeling(self):
        case = self.explicit_feeling_case("我妈很伤心。")
        self.assertIn("CLAIM_KIND_MISMATCH", self.codes(case))

    def test_postfixed_secondhand_source_is_not_direct_observation(self):
        case = self.direct_observation_case(
            "老板取消了会议，这是同事后来转告我的。",
            "老板取消了会议，",
        )
        self.assertIn("SOURCE_TYPE_MISMATCH", self.codes(case))

    def test_denied_quote_is_not_a_stated_position(self):
        case = self.stated_position_case(
            "他否定了这句话：“我要辞职”。",
            "我要辞职",
        )
        self.assertIn("DIRECT_QUOTE_NOT_ASSERTED", self.codes(case))


if __name__ == "__main__":
    unittest.main()
