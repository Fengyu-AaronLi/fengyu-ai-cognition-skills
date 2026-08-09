import importlib.util
import unittest

from test_casefile import SCRIPT, replace_first_input, valid_standard


def load_runtime():
    spec = importlib.util.spec_from_file_location("round8_fail_closed_runtime", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Round8FailClosedRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_runtime()

    def case_with_claim_on_span(self, text, span, observation_type, source_type):
        case = valid_standard()
        replace_first_input(case, case["inputs"][0]["text"] + text)
        span = next(item for item in case["source_spans"] if item["text"] == span["text"])
        case["claims"][0].update(
            {
                "observation_type": observation_type,
                "text": span["text"],
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": source_type,
                "exact_quote": span["text"],
            }
        )
        case["evidence"][0].update(
            {
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": source_type,
                "exact_quote": span["text"],
            }
        )
        return case, span

    def codes(self, case):
        return {item["code"] for item in self.module.validate_casefile(case)}

    def assert_fact_rejected(self, text, observation_type, source_type="user_direct_observation"):
        self.assertIsNone(
            self.module.derive_observation_type(text),
            "the classifier must fail closed on a full span containing a story predicate",
        )
        spans = self.module.generate_source_spans("I1", text)
        fact_span = next(
            (
                span
                for span in spans
                if self.module.derive_observation_type(span["text"], span)
                == observation_type
            ),
            None,
        )
        self.assertIsNotNone(fact_span, "the observable prefix must remain available")
        story_span = next(
            (
                span
                for span in spans
                if span is not fact_span
                and self.module.derive_observation_type(span["text"], span) is None
            ),
            None,
        )
        self.assertIsNotNone(story_span, "the unconsumed story tail must be a separate span")
        case, _ = self.case_with_claim_on_span(
            text,
            story_span,
            observation_type,
            source_type,
        )
        self.assertTrue(
            {"FACT_TYPE_UNSUPPORTED", "CLAIM_KIND_MISMATCH"} & self.codes(case),
            "a non-observational span entered observable_fact",
        )

    def test_unseen_post_event_predicates_fail_closed(self):
        examples = (
            ("老板取消会议盘算着让我难堪。", "participation_or_schedule_event"),
            ("他删了文档彰显其自私自利。", "task_or_action_event"),
            ("他删了文档印证他品行恶劣。", "task_or_action_event"),
            ("他删了文档足以看出他人品差。", "task_or_action_event"),
            ("老板取消会议怀着让我出丑的心思。", "participation_or_schedule_event"),
            ("他六小时没回只为让我着急。", "communication_event"),
        )
        for text, observation_type in examples:
            with self.subTest(text=text):
                self.assert_fact_rejected(text, observation_type)

    def test_negative_report_does_not_bypass_full_span_validation(self):
        self.assert_fact_rejected(
            "她没有解释原因足以看出她不在乎我。",
            "negative_report_event",
        )

    def test_artifact_label_does_not_replace_sentence_semantics(self):
        text = "[截图] 他品行恶劣。"
        case = valid_standard()
        replace_first_input(case, case["inputs"][0]["text"] + "\n" + text)
        span = next(item for item in case["source_spans"] if item["text"] == "他品行恶劣。")
        case["claims"][0].update(
            {
                "observation_type": "artifact_or_system_state",
                "text": span["text"],
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "unverified_artifact",
                "exact_quote": span["text"],
            }
        )
        case["evidence"][0].update(
            {
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "unverified_artifact",
                "exact_quote": span["text"],
            }
        )
        self.assertIsNone(self.module.derive_observation_type(span["text"], span))
        self.assertIn("FACT_TYPE_UNSUPPORTED", self.codes(case))

    def test_bounded_observation_surfaces_remain_supported(self):
        examples = {
            "他删了我。": "task_or_action_event",
            "他删了文档。": "task_or_action_event",
            "老板把我的工位搬走了。": "task_or_action_event",
            "同事迟到了。": "participation_or_schedule_event",
            "随后取消了我的会议。": "participation_or_schedule_event",
            "她连续两次临时取消约会。": "participation_or_schedule_event",
            "她没有解释原因。": "negative_report_event",
            "今天收到一封节日放假通知。": "communication_event",
            "我打开项目日历。": "artifact_or_system_state",
            "没有看到自己的名字。": "artifact_or_system_state",
            "审批权限已经失效。": "artifact_or_system_state",
            "系统今天仍允许我审批该项目预算。": "artifact_or_system_state",
            "我两周没有完成计划。": "task_or_action_event",
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                span = self.module.generate_source_spans("I1", text)[0]
                self.assertEqual(
                    expected,
                    self.module.derive_observation_type(span["text"], span),
                )


if __name__ == "__main__":
    unittest.main()
