import importlib.util
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


casefile = load_module("round128_casefile", SCRIPTS_DIR / "casefile.py")
previous_casefile = sys.modules.get("casefile")
sys.modules["casefile"] = casefile
try:
    workflow = load_module("round128_workflow", SCRIPTS_DIR / "workflow.py")
finally:
    if previous_casefile is None:
        sys.modules.pop("casefile", None)
    else:
        sys.modules["casefile"] = previous_casefile


class Round126And127FixRegressionTests(unittest.TestCase):
    def test_double_and_single_negation_keep_their_speaker_and_polarity(self):
        cases = (
            ("我并非不想自杀。", {"self_harm_risk"}),
            ("我说：\u201c我并非不想自杀。\u201d", {"self_harm_risk"}),
            (
                "朋友发消息说：\u201c我并非不想自杀。\u201d",
                {"third_party_self_harm_risk"},
            ),
            ("朋友发消息说：\u201c我不想自杀。\u201d", set()),
            (
                "朋友发消息说：\u201c我不想活了。\u201d",
                {"third_party_self_harm_risk"},
            ),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(
                    expected, casefile.expected_safety_signal_types(text)
                )

    def test_reaction_adverb_does_not_override_external_ownership(self):
        cases = (
            ("我反而安心了。", True),
            ("他认为我反而安心了。", False),
            ("[同事转述：] 我反而安心了。", False),
            ("她发完消息后，我反而安心了。", True),
        )
        for text, expected in cases:
            spans = casefile.generate_source_spans("I1", text)
            actual = any(
                casefile._is_current_user_explicit_feeling(
                    span["text"], span, text
                )
                for span in spans
            )
            with self.subTest(text=text):
                self.assertEqual(expected, actual)

    def test_sourced_timeline_rejects_missing_source_fields(self):
        request = """请按已标来源整理时间线：
2026年5月1日，项目会议取消。（来源：甲方邮件）
2026年5月2日，权限通知已发送。（来源：乙方消息）"""
        response = """2026年5月1日：项目会议取消
2026年5月2日：权限通知已发送"""
        valid, errors = workflow.validate_passthrough_response(
            "sourced_timeline", request, response
        )
        self.assertFalse(valid)
        self.assertIn("timeline_source_changed", errors)

    def test_sourced_timeline_accepts_a_faithful_markdown_table(self):
        request = """请按已标来源整理时间线：
2026年5月1日，项目会议取消。（来源：甲方邮件）
2026年5月2日，权限通知已发送。（来源：乙方消息）"""
        response = """| 日期 | 事件 | 来源 |
| --- | --- | --- |
| 2026年5月1日 | 项目会议取消 | 甲方邮件 |
| 2026年5月2日 | 权限通知已发送 | 乙方消息 |"""
        valid, errors = workflow.validate_passthrough_response(
            "sourced_timeline", request, response
        )
        self.assertTrue(valid, errors)

    def test_one_global_source_may_be_repeated_per_event(self):
        request = """请按已标来源整理时间线：
来源：会议纪要
2026年5月1日，项目会议取消。
2026年5月2日，项目会议改期。"""
        response = """2026年5月1日：项目会议取消（来源：会议纪要）
2026年5月2日：项目会议改期（来源：会议纪要）"""
        valid, errors = workflow.validate_passthrough_response(
            "sourced_timeline", request, response
        )
        self.assertTrue(valid, errors)

    def test_source_mutation_has_a_typed_error(self):
        request = """请按已标来源整理时间线：
2026年5月1日，项目会议取消。（来源：甲方邮件）"""
        response = """2026年5月1日：项目会议取消（来源：匿名转述）"""
        valid, errors = workflow.validate_passthrough_response(
            "sourced_timeline", request, response
        )
        self.assertFalse(valid)
        self.assertIn("timeline_source_changed", errors)


if __name__ == "__main__":
    unittest.main()
