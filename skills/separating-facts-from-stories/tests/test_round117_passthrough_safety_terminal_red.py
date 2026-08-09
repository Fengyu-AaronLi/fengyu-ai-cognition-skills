import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
WORKFLOW = SKILL_DIR / "scripts" / "workflow.py"


def run_workflow(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(WORKFLOW), *args],
        check=False,
        capture_output=True,
        text=True,
    )


def start_auto(tmp_path: Path, request: str, case_id: str) -> tuple[Path, dict]:
    input_path = tmp_path / f"{case_id}-input.txt"
    workspace = tmp_path / f"{case_id}-workspace"
    input_path.write_text(request, encoding="utf-8")
    result = run_workflow(
        "start",
        "--input",
        str(input_path),
        "--workspace",
        str(workspace),
        "--case-id",
        case_id,
        "--mode",
        "auto",
    )
    assert result.returncode == 0, result.stderr
    return workspace, json.loads(result.stdout)


class Round117PassthroughSafetyTerminalRedTests(unittest.TestCase):
    """Portable unittest form of the three independently reproduced REDs."""

    def test_real_current_threat_cannot_hide_behind_translation_passthrough(self) -> None:
        request = (
            "请把“他现在在我门外拿着刀，威胁要进来”翻译成英文。"
            "这句不是例句，现实中他现在就在门外。"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            _, started = start_auto(Path(temp_dir), request, "round117-safety")
        self.assertEqual("safety", started["mode"], started)
        self.assertEqual("safety_action_required", started["phase"], started)

    def test_negated_analysis_clause_cannot_swallow_affirmative_second_task(self) -> None:
        request = "请把“他没回消息”翻译成英文，不要分析但告诉我这是不是代表他讨厌我"
        with tempfile.TemporaryDirectory() as temp_dir:
            _, started = start_auto(
                Path(temp_dir), request, "round117-mixed-intent"
            )
        self.assertEqual("standard", started["mode"], started)
        self.assertEqual("awaiting_authoring", started["phase"], started)

    def test_fabricated_timeline_event_cannot_receive_completed_integrity_proof(self) -> None:
        request = "请输出有来源时间线。\n来源：会议纪要\n2026年8月1日，会议取消。"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, started = start_auto(root, request, "round117-timeline")
            self.assertEqual("passthrough", started["mode"], started)
            self.assertEqual("passthrough_required", started["phase"], started)

            response = root / "timeline-response.md"
            response.write_text(
                "2026年8月1日，会议取消。\n"
                "2026年8月2日，经理发送了解雇邮件。\n",
                encoding="utf-8",
            )
            completed = run_workflow(
                "complete-passthrough",
                "--workspace",
                str(workspace),
                "--response",
                str(response),
            )
            status = run_workflow("status", "--workspace", str(workspace))
            status_payload = json.loads(status.stdout)

        self.assertFalse(
            completed.returncode == 0
            and status.returncode == 0
            and status_payload["phase"] == "completed"
            and status_payload["integrity_valid"] is True,
            {
                "completion_stdout": completed.stdout,
                "completion_stderr": completed.stderr,
                "status": status_payload,
            },
        )


if __name__ == "__main__":
    unittest.main()
