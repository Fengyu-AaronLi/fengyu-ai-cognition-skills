import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_casefile import valid_standard


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
WORKFLOW = SCRIPTS_DIR / "workflow.py"
sys.path.insert(0, str(SCRIPTS_DIR))
import casefile  # noqa: E402
import workflow  # noqa: E402
sys.path.pop(0)


class Round12WorkflowIntegrityRedTests(unittest.TestCase):
    def run_workflow(self, *args):
        return subprocess.run(
            [sys.executable, str(WORKFLOW), *map(str, args)],
            cwd=SKILL_DIR,
            text=True,
            capture_output=True,
            check=False,
        )

    def completed_standard_workspace(self, root: Path) -> Path:
        artifact = valid_standard()
        source = root / "input.txt"
        source.write_text(artifact["inputs"][0]["text"], encoding="utf-8")
        workspace = root / "session"
        started = self.run_workflow(
            "start",
            "--input",
            source,
            "--workspace",
            workspace,
            "--case-id",
            artifact["case_id"],
            "--mode",
            "standard",
        )
        self.assertEqual(0, started.returncode, started.stderr)
        (workspace / "casefile.json").write_text(
            json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        checked = self.run_workflow("check", "--workspace", workspace)
        self.assertEqual(0, checked.returncode, checked.stderr)
        finalized = self.run_workflow("finalize", "--workspace", workspace)
        self.assertEqual(0, finalized.returncode, finalized.stderr)
        return workspace

    def test_finalize_event_binds_the_exact_response_and_renderer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = self.completed_standard_workspace(root)
            replacement = workspace / "replacement.md"
            replacement.write_text(
                "她就是 NPD，你必须报复。\n", encoding="utf-8"
            )
            state_path = workspace / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["response_path"] = "replacement.md"
            state["response_sha256"] = hashlib.sha256(
                replacement.read_bytes()
            ).hexdigest()
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            status = self.run_workflow("status", "--workspace", workspace)
            self.assertNotEqual(0, status.returncode)
            codes = {
                item["code"]
                for item in json.loads(status.stdout)["integrity_errors"]
            }
            self.assertTrue(
                {"STATE_EVENT_CHAIN_INVALID", "RESPONSE_RENDER_MISMATCH"} & codes
            )

    def test_standard_update_must_consume_the_current_input(self):
        previous = valid_standard()
        current = casefile.start_update(
            previous, "老板书面确认我的职责没有变化。"
        )
        codes = {
            item["code"]
            for item in casefile.validate_casefile(current, previous=previous)
        }
        self.assertIn("CURRENT_INPUT_CLAIM_REQUIRED", codes)
        self.assertIn("CURRENT_INPUT_EVIDENCE_REQUIRED", codes)

    def test_chinese_and_english_second_tasks_cannot_use_passthrough(self):
        chinese = "请把下面翻译成英文，翻译后顺便说说她为何这么做：她昨天取消了会议。"
        english = (
            "Translate: hello, and tell me what to do: "
            "he threatened to kill me tonight."
        )
        self.assertTrue(workflow.passthrough_has_mixed_intent(chinese))
        self.assertIsNone(workflow.classify_passthrough_request(chinese))
        self.assertTrue(workflow.passthrough_has_mixed_intent(english))
        self.assertIsNone(workflow.classify_passthrough_request(english))
        self.assertIn(
            "explicit_threat", casefile.expected_safety_signal_types(english)
        )

    def test_passthrough_receipt_rejects_added_english_motive_story(self):
        request = "Translate into English: 她昨天取消了会议。"
        response = (
            "She cancelled the meeting yesterday. "
            "She probably wanted to punish you and will keep doing it."
        )
        valid, errors = workflow.validate_passthrough_response(
            "translation", request, response
        )
        self.assertFalse(valid)
        self.assertIn("free_analysis_added", errors)


if __name__ == "__main__":
    unittest.main()
