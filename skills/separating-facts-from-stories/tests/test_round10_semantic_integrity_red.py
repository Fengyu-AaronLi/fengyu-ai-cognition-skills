import importlib.util
import unittest

from test_casefile import SCRIPT, replace_first_input, valid_standard


def load_runtime():
    spec = importlib.util.spec_from_file_location("round10_semantic_runtime", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Round10SemanticIntegrityRedTests(unittest.TestCase):
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
        return case, span

    def test_finite_prefix_never_splits_inside_a_possessive_recipient(self):
        text = "老板回复了我的老板。"
        spans = self.module.generate_source_spans("I1", text)
        self.assertNotIn("老板回复了我", {item["text"] for item in spans})
        self.assertFalse(
            any(
                item["text"] != text
                and self.module.derive_observation_type(item["text"], item)
                is not None
                for item in spans
            ),
            spans,
        )

    def test_question_is_not_a_current_stated_position(self):
        case = self.stated_position_case(
            "他问我：“我会留下吗？”", "我会留下吗？"
        )
        self.assertIn("DIRECT_QUOTE_NOT_ASSERTED", self.codes(case))

        affirmative = self.stated_position_case(
            "他回答：“我会留下。”", "我会留下。"
        )
        self.assertNotIn("DIRECT_QUOTE_NOT_ASSERTED", self.codes(affirmative))

    def test_superseded_quote_is_not_rendered_as_current_position(self):
        case = self.stated_position_case(
            "他说“我会留下”，但马上又改口了。", "我会留下"
        )
        self.assertTrue(
            {"DIRECT_QUOTE_SUPERSEDED", "DIRECT_QUOTE_NOT_ASSERTED"}
            & self.codes(case)
        )

        current = self.stated_position_case(
            "他说“我会留下”，并解释了交接安排。", "我会留下"
        )
        self.assertFalse(
            {"DIRECT_QUOTE_SUPERSEDED", "DIRECT_QUOTE_NOT_ASSERTED"}
            & self.codes(current)
        )

    def test_nested_reporting_chain_is_secondhand_not_direct_quote(self):
        for messenger in ("邻居", "门卫", "项目协调员"):
            text = f"{messenger}告诉我，老板说“我会留下”。"
            case = self.stated_position_case(text, "我会留下")
            quote_span = next(
                item
                for item in case["source_spans"]
                if item["quoted"] and item["text"] == "我会留下"
            )
            with self.subTest(messenger=messenger):
                self.assertEqual(
                    "secondhand",
                    self.module._expected_source_type_for_span(quote_span),
                )
                self.assertIn("SOURCE_TYPE_MISMATCH", self.codes(case))

        direct = self.stated_position_case(
            "老板告诉我：“我会留下”。", "我会留下"
        )
        self.assertNotIn("SOURCE_TYPE_MISMATCH", self.codes(direct))

    def test_postfixed_message_channel_is_not_direct_observation(self):
        examples = (
            "老板取消了会议，这是行政助理刚发群消息告诉我的。",
            "老板取消了会议，这是项目群公告写明的。",
            "老板取消了会议，这是系统消息显示的。",
        )
        for text in examples:
            with self.subTest(text=text):
                case, span = self.direct_observation_case(
                    text, "老板取消了会议，"
                )
                self.assertEqual(
                    "unverified_artifact",
                    self.module._expected_source_type_for_span(span),
                )
                self.assertIn("SOURCE_TYPE_MISMATCH", self.codes(case))


if __name__ == "__main__":
    unittest.main()
