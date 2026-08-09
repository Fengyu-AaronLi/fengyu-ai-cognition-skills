import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_casefile import SCRIPT as CASEFILE_SCRIPT
from test_casefile import valid_safety, valid_standard


SKILL_DIR = Path(__file__).resolve().parents[1]
WORKFLOW = SKILL_DIR / "scripts" / "workflow.py"


def load_casefile():
    spec = importlib.util.spec_from_file_location("workflow_test_casefile", CASEFILE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class WorkflowRuntimeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.casefile = load_casefile()

    def run_workflow(self, *args):
        return subprocess.run(
            [sys.executable, str(WORKFLOW), *map(str, args)],
            cwd=SKILL_DIR,
            text=True,
            capture_output=True,
            check=False,
        )

    def write_input(self, root: Path, text: str, name: str = "input.txt") -> Path:
        path = root / name
        path.write_text(text, encoding="utf-8")
        return path

    def start_standard(self, root: Path) -> tuple[Path, dict]:
        case = valid_standard()
        input_path = self.write_input(root, case["inputs"][0]["text"])
        workspace = root / "session"
        completed = self.run_workflow(
            "start",
            "--input",
            input_path,
            "--workspace",
            workspace,
            "--case-id",
            case["case_id"],
            "--mode",
            "standard",
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        return workspace, json.loads(completed.stdout)

    def test_start_creates_stateful_workspace_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, result = self.start_standard(root)
            self.assertEqual("awaiting_authoring", result["phase"])
            self.assertEqual("fill_casefile", result["next_action"])
            self.assertTrue((workspace / "state.json").is_file())
            self.assertTrue((workspace / "casefile.json").is_file())
            state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(0, state["attempt_count"])
            self.assertEqual([], state["receipt_paths"])
            self.assertEqual("separating-facts-from-stories", state["skill"])

            repeated = self.run_workflow(
                "start",
                "--input",
                root / "input.txt",
                "--workspace",
                workspace,
                "--case-id",
                "ignored",
                "--mode",
                "standard",
            )
            self.assertNotEqual(0, repeated.returncode)
            self.assertIn("WORKSPACE_EXISTS", repeated.stderr)

    def test_invalid_draft_enters_bounded_repair_loop_then_blocks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, _ = self.start_standard(root)

            first = self.run_workflow("check", "--workspace", workspace)
            self.assertEqual(1, first.returncode)
            first_result = json.loads(first.stdout)
            self.assertEqual("repair_required", first_result["phase"])
            self.assertEqual(1, first_result["attempt_count"])
            self.assertEqual("repair_casefile", first_result["next_action"])
            self.assertGreater(first_result["error_count"], 0)

            second = self.run_workflow("check", "--workspace", workspace)
            self.assertEqual(1, second.returncode)
            second_result = json.loads(second.stdout)
            self.assertEqual("blocked", second_result["phase"])
            self.assertEqual(2, second_result["attempt_count"])
            self.assertEqual("start_new_workspace_after_review", second_result["next_action"])
            self.assertEqual(2, len(second_result["receipt_paths"]))

            final = self.run_workflow("finalize", "--workspace", workspace)
            self.assertNotEqual(0, final.returncode)
            self.assertIn("PHASE_NOT_FINALIZABLE", final.stderr)
            self.assertFalse((workspace / "response.md").exists())

    def test_missing_casefile_becomes_a_bounded_failure_with_a_receipt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, _ = self.start_standard(root)
            (workspace / "casefile.json").rename(workspace / "casefile.missing")
            checked = self.run_workflow("check", "--workspace", workspace)
            self.assertEqual(1, checked.returncode, checked.stderr)
            result = json.loads(checked.stdout)
            self.assertEqual("repair_required", result["phase"])
            self.assertEqual(1, result["attempt_count"])
            receipt = json.loads(
                (workspace / "receipts" / "attempt-1.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(receipt["valid"])
            self.assertIsNone(receipt["artifact_sha256"])
            self.assertIn(
                "CASEFILE_MISSING", {item["code"] for item in receipt["errors"]}
            )

    def test_valid_casefile_must_pass_check_before_deterministic_finalize(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, _ = self.start_standard(root)
            case = valid_standard()
            (workspace / "casefile.json").write_text(
                json.dumps(case, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            early = self.run_workflow("finalize", "--workspace", workspace)
            self.assertNotEqual(0, early.returncode)
            self.assertIn("PHASE_NOT_FINALIZABLE", early.stderr)

            checked = self.run_workflow("check", "--workspace", workspace)
            self.assertEqual(0, checked.returncode, checked.stderr)
            checked_result = json.loads(checked.stdout)
            self.assertEqual("ready_to_finalize", checked_result["phase"])
            self.assertEqual(1, checked_result["attempt_count"])
            self.assertEqual("finalize", checked_result["next_action"])

            finalized = self.run_workflow("finalize", "--workspace", workspace)
            self.assertEqual(0, finalized.returncode, finalized.stderr)
            final_result = json.loads(finalized.stdout)
            self.assertEqual("completed", final_result["phase"])
            response = (workspace / "response.md").read_text(encoding="utf-8")
            self.assertEqual(self.casefile.render_markdown(case), response)

            status = self.run_workflow("status", "--workspace", workspace)
            self.assertEqual(0, status.returncode, status.stderr)
            status_result = json.loads(status.stdout)
            self.assertTrue(status_result["integrity_valid"])
            self.assertEqual("completed", status_result["phase"])

    def test_finalize_rejects_artifact_changed_after_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, _ = self.start_standard(root)
            case = valid_standard()
            artifact = workspace / "casefile.json"
            artifact.write_text(
                json.dumps(case, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            checked = self.run_workflow("check", "--workspace", workspace)
            self.assertEqual(0, checked.returncode, checked.stderr)
            artifact.write_text(
                json.dumps(case, ensure_ascii=False, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            finalized = self.run_workflow("finalize", "--workspace", workspace)
            self.assertNotEqual(0, finalized.returncode)
            self.assertIn("VALIDATED_ARTIFACT_CHANGED", finalized.stderr)
            self.assertFalse((workspace / "response.md").exists())

    def test_forged_state_cannot_skip_the_check_transition(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, _ = self.start_standard(root)
            case = valid_standard()
            artifact = workspace / "casefile.json"
            artifact.write_text(
                json.dumps(case, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            state_path = workspace / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["phase"] = "ready_to_finalize"
            state["validated_artifact_sha256"] = self.casefile.sha256_bytes(
                artifact.read_bytes()
            )
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            finalized = self.run_workflow("finalize", "--workspace", workspace)
            self.assertNotEqual(0, finalized.returncode)
            self.assertIn("STATE_EVENT_CHAIN_INVALID", finalized.stderr)
            self.assertFalse((workspace / "response.md").exists())

    def test_finalize_output_cannot_escape_the_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, _ = self.start_standard(root)
            case = valid_standard()
            (workspace / "casefile.json").write_text(
                json.dumps(case, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            checked = self.run_workflow("check", "--workspace", workspace)
            self.assertEqual(0, checked.returncode, checked.stderr)
            outside = root / "escaped.md"
            finalized = self.run_workflow(
                "finalize", "--workspace", workspace, "--output", outside
            )
            self.assertNotEqual(0, finalized.returncode)
            self.assertIn("OUTPUT_OUTSIDE_WORKSPACE", finalized.stderr)
            self.assertFalse(outside.exists())

    def test_status_detects_source_input_tampering(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, _ = self.start_standard(root)
            (workspace / "input.txt").write_text("被替换的输入", encoding="utf-8")
            status = self.run_workflow("status", "--workspace", workspace)
            self.assertEqual(1, status.returncode)
            result = json.loads(status.stdout)
            self.assertFalse(result["integrity_valid"])
            self.assertIn(
                "INPUT_HASH_MISMATCH",
                {item["code"] for item in result["integrity_errors"]},
            )

    def test_state_paths_cannot_escape_the_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace, _ = self.start_standard(root)
            outside = root / "outside.txt"
            outside.write_text("private", encoding="utf-8")
            state_path = workspace / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["input_path"] = "../outside.txt"
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            status = self.run_workflow("status", "--workspace", workspace)
            self.assertEqual(1, status.returncode, status.stderr)
            result = json.loads(status.stdout)
            self.assertIn(
                "STATE_PATH_OUTSIDE_WORKSPACE",
                {item["code"] for item in result["integrity_errors"]},
            )

    def test_passthrough_completes_without_casefile_or_psychological_analysis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = self.write_input(root, "Translate: The meeting is Friday at 3 p.m.")
            workspace = root / "passthrough"
            started = self.run_workflow(
                "start",
                "--input",
                input_path,
                "--workspace",
                workspace,
                "--case-id",
                "translation",
                "--mode",
                "passthrough",
            )
            self.assertEqual(0, started.returncode, started.stderr)
            self.assertEqual("passthrough_required", json.loads(started.stdout)["phase"])
            self.assertFalse((workspace / "casefile.json").exists())

            response = self.write_input(root, "会议安排在星期五下午三点。", "translation.md")
            completed = self.run_workflow(
                "complete-passthrough",
                "--workspace",
                workspace,
                "--response",
                response,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            result = json.loads(completed.stdout)
            self.assertEqual("completed", result["phase"])
            self.assertFalse((workspace / "casefile.json").exists())

    def test_auto_route_recognizes_a_clear_translation_task(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = self.write_input(
                root, "Translate: The meeting is Friday at 3 p.m."
            )
            workspace = root / "auto-translation"
            started = self.run_workflow(
                "start",
                "--input",
                input_path,
                "--workspace",
                workspace,
                "--case-id",
                "translation-auto",
                "--mode",
                "auto",
            )
            self.assertEqual(0, started.returncode, started.stderr)
            result = json.loads(started.stdout)
            self.assertEqual("passthrough", result["mode"])
            self.assertEqual("passthrough_required", result["phase"])
            self.assertFalse((workspace / "casefile.json").exists())

    def test_passthrough_cannot_bypass_a_relationship_inference(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = self.write_input(
                root, "他六个小时没回我，直接告诉我他是不是不爱我了。"
            )
            workspace = root / "bypass"
            started = self.run_workflow(
                "start",
                "--input",
                input_path,
                "--workspace",
                workspace,
                "--case-id",
                "bypass",
                "--mode",
                "passthrough",
            )
            self.assertNotEqual(0, started.returncode)
            self.assertIn("PASSTHROUGH_NOT_ELIGIBLE", started.stderr)
            self.assertFalse(workspace.exists())

    def test_passthrough_cannot_override_an_immediate_safety_signal(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = self.write_input(
                root, "他拿着刀堵在门外，说今晚要杀了我。"
            )
            workspace = root / "unsafe-bypass"
            started = self.run_workflow(
                "start",
                "--input",
                input_path,
                "--workspace",
                workspace,
                "--case-id",
                "unsafe-bypass",
                "--mode",
                "passthrough",
            )
            self.assertNotEqual(0, started.returncode)
            self.assertIn("SAFETY_MODE_REQUIRED", started.stderr)
            self.assertFalse(workspace.exists())

    def test_safety_branch_requires_visible_real_world_action_before_analysis(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            input_path = self.write_input(root, "他拿着刀堵在门外，说今晚要杀了我。")
            workspace = root / "safety"
            started = self.run_workflow(
                "start",
                "--input",
                input_path,
                "--workspace",
                workspace,
                "--case-id",
                "safety",
                "--mode",
                "auto",
            )
            self.assertEqual(0, started.returncode, started.stderr)
            self.assertEqual("safety_action_required", json.loads(started.stdout)["phase"])

            refused = self.run_workflow("check", "--workspace", workspace)
            self.assertNotEqual(0, refused.returncode)
            self.assertIn("SAFETY_RESPONSE_REQUIRED", refused.stderr)

            weak = self.write_input(root, "我理解你很害怕。", "weak.md")
            weak_result = self.run_workflow(
                "acknowledge-safety",
                "--workspace",
                workspace,
                "--response",
                weak,
            )
            self.assertNotEqual(0, weak_result.returncode)
            self.assertIn("SAFETY_RESPONSE_INVALID", weak_result.stderr)

            template = self.run_workflow(
                "safety-template", "--workspace", workspace
            )
            self.assertEqual(0, template.returncode, template.stderr)
            action = self.write_input(root, template.stdout, "safety.md")
            accepted = self.run_workflow(
                "acknowledge-safety",
                "--workspace",
                workspace,
                "--response",
                action,
            )
            self.assertEqual(0, accepted.returncode, accepted.stderr)
            self.assertEqual("awaiting_authoring", json.loads(accepted.stdout)["phase"])

    def test_safety_response_remains_hash_bound_after_casefile_finalize(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case = valid_safety()
            input_path = self.write_input(root, case["inputs"][0]["text"])
            workspace = root / "safety-complete"
            started = self.run_workflow(
                "start",
                "--input",
                input_path,
                "--workspace",
                workspace,
                "--case-id",
                case["case_id"],
                "--mode",
                "safety",
            )
            self.assertEqual(0, started.returncode, started.stderr)
            template = self.run_workflow(
                "safety-template", "--workspace", workspace
            )
            self.assertEqual(0, template.returncode, template.stderr)
            action = self.write_input(root, template.stdout, "visible-safety.md")
            acknowledged = self.run_workflow(
                "acknowledge-safety",
                "--workspace",
                workspace,
                "--response",
                action,
            )
            self.assertEqual(0, acknowledged.returncode, acknowledged.stderr)
            (workspace / "casefile.json").write_text(
                json.dumps(case, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self.assertEqual(
                0,
                self.run_workflow("check", "--workspace", workspace).returncode,
            )
            self.assertEqual(
                0,
                self.run_workflow("finalize", "--workspace", workspace).returncode,
            )
            (workspace / "safety-response.md").write_text("已被改写", encoding="utf-8")
            status = self.run_workflow("status", "--workspace", workspace)
            self.assertEqual(1, status.returncode)
            result = json.loads(status.stdout)
            self.assertIn(
                "SAFETY_RESPONSE_HASH_MISMATCH",
                {item["code"] for item in result["integrity_errors"]},
            )

    def test_start_update_binds_full_history_and_new_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            previous = valid_standard()
            previous_path = root / "revision-1.json"
            previous_path.write_text(
                json.dumps(previous, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            new_text = "老板发来邮件，说明上次会议只是临时缩小参会范围。"
            input_path = self.write_input(root, new_text, "new.txt")
            workspace = root / "update"
            started = self.run_workflow(
                "start-update",
                "--history",
                previous_path,
                "--input",
                input_path,
                "--workspace",
                workspace,
            )
            self.assertEqual(0, started.returncode, started.stderr)
            result = json.loads(started.stdout)
            self.assertEqual("awaiting_authoring", result["phase"])
            current = json.loads((workspace / "casefile.json").read_text(encoding="utf-8"))
            self.assertEqual(2, current["revision"])
            self.assertEqual(new_text, current["inputs"][-1]["text"])
            state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
            self.assertEqual(
                self.casefile.canonical_sha256(previous),
                state["history"][0]["casefile_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
