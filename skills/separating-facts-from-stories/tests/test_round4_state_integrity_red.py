import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_casefile import valid_safety, valid_standard


SKILL_DIR = Path(__file__).resolve().parents[1]
WORKFLOW = SKILL_DIR / "scripts" / "workflow.py"


class Round4StateIntegrityRedTests(unittest.TestCase):
    def run_workflow(self, *args):
        return subprocess.run(
            [sys.executable, str(WORKFLOW), *map(str, args)],
            cwd=SKILL_DIR,
            text=True,
            capture_output=True,
            check=False,
        )

    def complete_standard(self, root: Path) -> Path:
        case = valid_standard()
        input_path = root / "input.txt"
        input_path.write_text(case["inputs"][0]["text"], encoding="utf-8")
        workspace = root / "session"
        started = self.run_workflow(
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
        self.assertEqual(0, started.returncode, started.stderr)
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
        return workspace

    def integrity_codes(self, workspace: Path) -> set[str]:
        result = self.run_workflow("status", "--workspace", workspace)
        self.assertNotEqual(0, result.returncode)
        payload = json.loads(result.stdout)
        return {item["code"] for item in payload["integrity_errors"]}

    def test_completed_state_requires_its_bound_response_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.complete_standard(Path(temp_dir))
            state_path = workspace / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.pop("response_path")
            state.pop("response_sha256")
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self.assertIn("RESPONSE_BINDING_MISSING", self.integrity_codes(workspace))

    def test_status_requires_every_declared_receipt_to_exist(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.complete_standard(Path(temp_dir))
            (workspace / "receipts" / "attempt-1.json").unlink()
            self.assertIn("RECEIPT_MISSING", self.integrity_codes(workspace))

    def test_status_binds_latest_receipt_content_to_last_validation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.complete_standard(Path(temp_dir))
            receipt = workspace / "receipts" / "attempt-1.json"
            receipt.write_text("{}\n", encoding="utf-8")
            self.assertIn("RECEIPT_HASH_MISMATCH", self.integrity_codes(workspace))

    def test_receipt_paths_cannot_leave_the_workspace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = self.complete_standard(root)
            outside = root / "outside.json"
            outside.write_text("{}\n", encoding="utf-8")
            state_path = workspace / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["receipt_paths"][0] = "../outside.json"
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self.assertIn(
                "STATE_PATH_OUTSIDE_WORKSPACE", self.integrity_codes(workspace)
            )

    def test_start_configuration_is_event_bound(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.complete_standard(Path(temp_dir))
            state_path = workspace / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["max_attempts"] = 99
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self.assertIn("STATE_CONFIG_MUTATED", self.integrity_codes(workspace))

    def test_safety_acknowledgement_cannot_disappear_after_completion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case = valid_safety()
            input_path = root / "input.txt"
            input_path.write_text(case["inputs"][0]["text"], encoding="utf-8")
            workspace = root / "session"
            started = self.run_workflow(
                "start",
                "--input",
                input_path,
                "--workspace",
                workspace,
                "--case-id",
                case["case_id"],
                "--mode",
                "auto",
            )
            self.assertEqual(0, started.returncode, started.stderr)
            template = self.run_workflow(
                "safety-template", "--workspace", workspace
            )
            self.assertEqual(0, template.returncode, template.stderr)
            safety_reply = root / "safety.md"
            safety_reply.write_text(template.stdout, encoding="utf-8")
            acknowledged = self.run_workflow(
                "acknowledge-safety",
                "--workspace",
                workspace,
                "--response",
                safety_reply,
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
            state_path = workspace / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state.pop("safety_response_path")
            state.pop("safety_response_sha256")
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            self.assertIn(
                "SAFETY_RESPONSE_BINDING_MISSING", self.integrity_codes(workspace)
            )


if __name__ == "__main__":
    unittest.main()
