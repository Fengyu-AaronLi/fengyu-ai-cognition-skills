import importlib.util
import unittest

from test_casefile import SCRIPT


def load_runtime():
    spec = importlib.util.spec_from_file_location("round10_temporal_runtime", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Round10TemporalSemanticsRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_runtime()

    def test_future_or_deadline_language_is_not_an_observed_event(self):
        examples = (
            "他会参加会议。",
            "他不会参加会议。",
            "老板周五前完成交接。",
        )
        for text in examples:
            with self.subTest(text=text):
                self.assertIsNone(self.module.derive_observation_type(text))

    def test_core_and_common_observation_surfaces_are_supported(self):
        examples = {
            "他看了消息六个小时没回。": "communication_event",
            "他给我打了电话。": "communication_event",
            "老板把会议改到周五下午三点。": "participation_or_schedule_event",
            "我亲眼看到他删了文档。": "task_or_action_event",
            "系统显示审批通过。": "artifact_or_system_state",
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertEqual(expected, self.module.derive_observation_type(text))

    def test_new_surfaces_do_not_absorb_story_tails(self):
        examples = {
            "他看了消息六个小时没回证明他不爱我。": (
                "他看了消息六个小时没回",
                "communication_event",
            ),
            "他给我打了电话证明他还爱我。": (
                "他给我打了电话",
                "communication_event",
            ),
            "老板把会议改到周五下午三点说明他在架空我。": (
                "老板把会议改到周五下午三点",
                "participation_or_schedule_event",
            ),
            "我亲眼看到他删了文档足以看出他品行恶劣。": (
                "我亲眼看到他删了文档",
                "task_or_action_event",
            ),
            "系统显示审批通过证明老板偏袒他。": (
                "系统显示审批通过",
                "artifact_or_system_state",
            ),
        }
        for text, (fact_prefix, expected_type) in examples.items():
            with self.subTest(text=text):
                self.assertIsNone(self.module.derive_observation_type(text))
                spans = self.module.generate_source_spans("I1", text)
                matching = [item for item in spans if item.get("text") == fact_prefix]
                self.assertTrue(matching, spans)
                self.assertEqual(
                    expected_type,
                    self.module.derive_observation_type(fact_prefix, matching[0]),
                )

    def test_future_prediction_is_not_recovered_as_a_fact_span(self):
        for text in ("他会参加会议。", "老板周五前完成交接。"):
            with self.subTest(text=text):
                spans = self.module.generate_source_spans("I1", text)
                self.assertFalse(
                    any(
                        self.module.derive_observation_type(
                            str(item.get("text", "")), item
                        )
                        is not None
                        for item in spans
                    ),
                    spans,
                )


if __name__ == "__main__":
    unittest.main()
