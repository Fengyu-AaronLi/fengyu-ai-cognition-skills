import importlib.util
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
CASEFILE_SCRIPT = SKILL_DIR / "scripts" / "casefile.py"
WORKFLOW_SCRIPT = SKILL_DIR / "scripts" / "workflow.py"


def load_casefile():
    spec = importlib.util.spec_from_file_location(
        "round124_final_semantic_blind_casefile", CASEFILE_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_workflow(casefile_module):
    spec = importlib.util.spec_from_file_location(
        "round124_final_semantic_blind_workflow", WORKFLOW_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    previous = sys.modules.get("casefile")
    sys.modules["casefile"] = casefile_module
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            sys.modules.pop("casefile", None)
        else:
            sys.modules["casefile"] = previous
    return module


class FinalSemanticBlindRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.casefile = load_casefile()
        cls.workflow = load_workflow(cls.casefile)

    def test_third_party_jump_report_routes_as_third_party_self_harm(self):
        reports = (
            "朋友说他现在想跳楼。",
            "朋友发来消息：\u201c我现在想跳楼\u201d。",
        )
        for report in reports:
            with self.subTest(report=report):
                self.assertEqual(
                    {"third_party_self_harm_risk"},
                    self.casefile.expected_safety_signal_types(report),
                )

    def test_hearsay_scope_ends_before_users_explicit_reaction(self):
        text = "同事说老板取消了会议，我听完很难过。"
        spans = self.casefile.generate_source_spans("I1", text)
        feeling_span = next(
            span for span in spans if span["text"] == "我听完很难过。"
        )

        self.assertNotEqual(
            "secondhand",
            self.casefile._expected_source_type_for_span(feeling_span),
        )
        self.assertTrue(
            self.casefile._is_current_user_explicit_feeling(
                feeling_span["text"], feeling_span, text
            )
        )

    def test_sourced_timeline_allows_source_after_unchanged_event(self):
        request = """请根据以下已明确标注来源整理成时间线：
[邮件：] 2026年8月1日，老板取消会议。
[消息：] 2026年8月2日，老板把会议改到周五。"""
        response = """2026年8月1日：老板取消会议（来源：邮件）
2026年8月2日：老板把会议改到周五（来源：消息）"""

        valid, errors = self.workflow.validate_passthrough_response(
            "sourced_timeline", request, response
        )

        self.assertTrue(valid)
        self.assertEqual([], errors)


if __name__ == "__main__":
    unittest.main()
