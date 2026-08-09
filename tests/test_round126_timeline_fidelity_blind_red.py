from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "skills" / "separating-facts-from-stories" / "scripts"
WORKFLOW_PATH = SCRIPTS_DIR / "workflow.py"

sys.path.insert(0, str(SCRIPTS_DIR))
SPEC = importlib.util.spec_from_file_location("round126_timeline_workflow", WORKFLOW_PATH)
assert SPEC is not None and SPEC.loader is not None
workflow = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(workflow)


REQUEST = """请把以下已明确标注来源的记录整理成一份时间线，只做格式转换，不要分析：
[T1] 2026年5月1日，项目会议取消。（来源：甲方邮件）
[T2] 2026年5月2日，权限通知已发送。（来源：乙方消息）
"""


def validate(response: str) -> tuple[bool, list[str]]:
    assert workflow.classify_passthrough_request(REQUEST) == "sourced_timeline"
    return workflow.validate_passthrough_response(
        "sourced_timeline", REQUEST, response
    )


class TimelineFidelityBlindTests(unittest.TestCase):
    def assert_source_mutation_rejected(
        self, response: str, mutation: str
    ) -> None:
        valid, errors = validate(response)
        self.assertFalse(
            valid, f"accepted {mutation}; validation errors were {errors}"
        )

    def assert_scope_expansion_rejected(self, response: str) -> None:
        valid, errors = validate(response)
        self.assertFalse(valid, errors)
        self.assertIn("timeline_scope_expanded", errors)

    def test_sourced_timeline_allows_source_field_repositioning_without_value_changes(
        self,
    ) -> None:
        response = """[甲方邮件：] 2026年5月1日，项目会议取消。
[乙方消息：] 2026年5月2日，权限通知已发送。
"""

        valid, errors = validate(response)

        self.assertTrue(valid, errors)

    def test_sourced_timeline_rejects_source_values_swapped_between_events(
        self,
    ) -> None:
        response = """| 日期 | 事件 | 来源 |
| --- | --- | --- |
| 2026年5月1日 | 项目会议取消 | 乙方消息 |
| 2026年5月2日 | 权限通知已发送 | 甲方邮件 |
"""

        self.assert_source_mutation_rejected(
            response, "source values swapped between events"
        )

    def test_sourced_timeline_rejects_rewritten_source_value(self) -> None:
        response = """| 日期 | 事件 | 来源 |
| --- | --- | --- |
| 2026年5月1日 | 项目会议取消 | 甲方短信 |
| 2026年5月2日 | 权限通知已发送 | 乙方消息 |
"""

        self.assert_source_mutation_rejected(response, "rewritten source value")

    def test_sourced_timeline_rejects_fabricated_source_values(self) -> None:
        response = """| 日期 | 事件 | 来源 |
| --- | --- | --- |
| 2026年5月1日 | 项目会议取消 | 董事会纪要 |
| 2026年5月2日 | 权限通知已发送 | 匿名转述 |
"""

        self.assert_source_mutation_rejected(response, "fabricated source values")

    def test_sourced_timeline_rejects_added_date(self) -> None:
        response = """| 日期 | 事件 | 来源 |
| --- | --- | --- |
| 2026年5月1日 | 项目会议取消 | 甲方邮件 |
| 2026年5月2日 | 权限通知已发送 | 乙方消息 |
| 2026年5月3日 | 项目会议取消 | 甲方邮件 |
"""

        self.assert_scope_expansion_rejected(response)

    def test_sourced_timeline_rejects_added_event(self) -> None:
        response = """| 日期 | 事件 | 来源 |
| --- | --- | --- |
| 2026年5月1日 | 项目会议取消 | 甲方邮件 |
| 2026年5月2日 | 权限通知已发送 | 乙方消息 |
| 2026年5月2日 | 岗位职责已删除 | 乙方消息 |
"""

        self.assert_scope_expansion_rejected(response)

    def test_sourced_timeline_rejects_added_analysis(self) -> None:
        response = """| 日期 | 事件 | 来源 |
| --- | --- | --- |
| 2026年5月1日 | 项目会议取消 | 甲方邮件 |
| 2026年5月2日 | 权限通知已发送 | 乙方消息 |

结论：这说明老板故意控制团队。
"""

        self.assert_scope_expansion_rejected(response)


if __name__ == "__main__":
    unittest.main()
