import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
WORKFLOW = SKILL_DIR / "scripts" / "workflow.py"


class Round10PassthroughRedTests(unittest.TestCase):
    def run_workflow(self, *args):
        return subprocess.run(
            [sys.executable, str(WORKFLOW), *map(str, args)],
            cwd=SKILL_DIR,
            text=True,
            capture_output=True,
            check=False,
        )

    def write(self, root: Path, name: str, text: str) -> Path:
        path = root / name
        path.write_text(text, encoding="utf-8")
        return path

    def start(self, root: Path, text: str, mode: str = "auto"):
        input_path = self.write(root, "input.txt", text)
        workspace = root / "session"
        result = self.run_workflow(
            "start",
            "--input",
            input_path,
            "--workspace",
            workspace,
            "--case-id",
            "round10-passthrough",
            "--mode",
            mode,
        )
        return result, workspace

    def test_auto_mixed_format_and_diagnosis_routes_standard(self):
        text = (
            "请把下面整理成表格，并告诉我他是不是NPD："
            "他六小时没回，就是故意惩罚我，他永远不会改变。"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result, workspace = self.start(Path(temp_dir), text)
            self.assertEqual(0, result.returncode, result.stderr)
            state = json.loads(result.stdout)
            self.assertEqual("standard", state["mode"])
            self.assertEqual("awaiting_authoring", state["phase"])
            self.assertTrue((workspace / "casefile.json").is_file())

    def test_explicit_passthrough_rejects_mixed_intent(self):
        text = (
            "请把下面整理成表格，并告诉我他是不是NPD："
            "他六小时没回，就是故意惩罚我，他永远不会改变。"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            result, workspace = self.start(Path(temp_dir), text, "passthrough")
            self.assertNotEqual(0, result.returncode)
            self.assertIn("PASSTHROUGH_MIXED_INTENT", result.stderr)
            self.assertFalse(workspace.exists())

    def test_passthrough_rejects_an_added_story_without_reserved_headings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result, workspace = self.start(
                root,
                "请把下面三项整理成表格：姓名、日期、状态。",
                "passthrough",
            )
            self.assertEqual(0, result.returncode, result.stderr)
            response = self.write(
                root,
                "bad.md",
                "表格结论：他就是NPD，而且永远不会改变，所以你应该立即分手。",
            )
            completed = self.run_workflow(
                "complete-passthrough",
                "--workspace",
                workspace,
                "--response",
                response,
            )
            self.assertNotEqual(0, completed.returncode)
            self.assertIn("PASSTHROUGH_SCOPE_VIOLATION", completed.stderr)
            state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
            self.assertEqual("passthrough_required", state["phase"])
            self.assertFalse((workspace / "response.md").exists())

    def test_completed_passthrough_has_a_bound_validation_receipt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result, workspace = self.start(
                root,
                "请把下面三项整理成表格：姓名、日期、状态。",
                "passthrough",
            )
            self.assertEqual(0, result.returncode, result.stderr)
            response = self.write(
                root,
                "good.md",
                "| 字段 | 值 |\n|---|---|\n| 姓名 |  |\n| 日期 |  |\n| 状态 |  |\n",
            )
            completed = self.run_workflow(
                "complete-passthrough",
                "--workspace",
                workspace,
                "--response",
                response,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)
            receipt_path = workspace / "passthrough-validation.json"
            self.assertTrue(receipt_path.is_file())
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            self.assertTrue(receipt["valid"])
            self.assertEqual(
                hashlib.sha256((workspace / "input.txt").read_bytes()).hexdigest(),
                receipt["input_sha256"],
            )
            self.assertEqual(
                hashlib.sha256((workspace / "response.md").read_bytes()).hexdigest(),
                receipt["response_sha256"],
            )
            state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
            self.assertEqual("formatting", state["passthrough_kind"])
            self.assertEqual(
                "passthrough-validation.json",
                state["passthrough_validation_path"],
            )

            receipt["valid"] = False
            receipt_path.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            status = self.run_workflow("status", "--workspace", workspace)
            self.assertNotEqual(0, status.returncode)
            status_data = json.loads(status.stdout)
            self.assertIn(
                "PASSTHROUGH_VALIDATION_HASH_MISMATCH",
                {item["code"] for item in status_data["integrity_errors"]},
            )

    def test_translation_payload_may_contain_diagnostic_words(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            result, workspace = self.start(
                root,
                "请翻译成英文：“他说她是NPD。”",
                "auto",
            )
            self.assertEqual(0, result.returncode, result.stderr)
            self.assertEqual("passthrough", json.loads(result.stdout)["mode"])
            response = self.write(root, "translated.md", '"He said she was NPD."')
            completed = self.run_workflow(
                "complete-passthrough",
                "--workspace",
                workspace,
                "--response",
                response,
            )
            self.assertEqual(0, completed.returncode, completed.stderr)


if __name__ == "__main__":
    unittest.main()
