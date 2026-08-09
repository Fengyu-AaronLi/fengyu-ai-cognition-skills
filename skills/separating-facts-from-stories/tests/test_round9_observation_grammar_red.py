import importlib.util
import unittest

from test_casefile import SCRIPT


def load_runtime():
    spec = importlib.util.spec_from_file_location("round9_observation_runtime", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Round9ObservationGrammarRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_runtime()

    def test_common_observation_paraphrases_are_consumed(self):
        examples = {
            "他没有回我的消息。": "communication_event",
            "他没回复我的消息。": "communication_event",
            "他六小时没有回复我。": "communication_event",
            "他已读消息后六小时没有回复。": "communication_event",
            "老板把我移出会议。": "participation_or_schedule_event",
            "老板取消了明天的会议。": "participation_or_schedule_event",
            "会议改期到下周一上午十点。": "participation_or_schedule_event",
            "我今天没有完成任何一项计划。": "task_or_action_event",
            "我没做完计划。": "task_or_action_event",
            "他把我从好友列表删除了。": "task_or_action_event",
            "老板发邮件通知我会议取消。": "communication_event",
            "系统显示我的审批权限已被取消。": "artifact_or_system_state",
            "项目日历里没有我的名字。": "artifact_or_system_state",
        }
        for text, expected in examples.items():
            with self.subTest(text=text):
                self.assertEqual(expected, self.module.derive_observation_type(text))

    def test_nested_artifact_descriptor_is_not_mistaken_for_a_story(self):
        text = "我连续三次没有被邀请参加岗位说明中写明“项目负责人必须参加”的决策会。"
        self.assertEqual(
            "participation_or_schedule_event",
            self.module.derive_observation_type(text),
        )

    def test_expanded_surfaces_still_reject_story_tails(self):
        examples = (
            "他没有回我的消息所以根本不在乎我。",
            "老板取消了明天的会议流露了对我的敌意。",
            "系统显示我的审批权限已被取消说明老板在架空我。",
            "我今天没有完成任何一项计划证明我注定失败。",
        )
        for text in examples:
            with self.subTest(text=text):
                self.assertIsNone(self.module.derive_observation_type(text))

    def test_predicate_semantics_beat_object_nouns(self):
        self.assertEqual(
            "task_or_action_event",
            self.module.derive_observation_type("他删了文档。"),
        )
        self.assertEqual(
            "communication_event",
            self.module.derive_observation_type("老板给我发了邮件。"),
        )


if __name__ == "__main__":
    unittest.main()
