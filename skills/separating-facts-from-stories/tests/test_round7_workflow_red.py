import json
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path

from test_casefile import valid_standard


SKILL_DIR = Path(__file__).resolve().parents[1]
WORKFLOW = SKILL_DIR / "scripts" / "workflow.py"


class Round7WorkflowRedTests(unittest.TestCase):
    def run_workflow(self, *args):
        return subprocess.run(
            [sys.executable, str(WORKFLOW), *map(str, args)],
            cwd=SKILL_DIR,
            text=True,
            capture_output=True,
            check=False,
        )

    def start(self, root: Path, text: str, mode: str) -> Path:
        input_path = root / "input.txt"
        input_path.write_text(text, encoding="utf-8")
        workspace = root / "session"
        started = self.run_workflow(
            "start",
            "--input",
            input_path,
            "--workspace",
            workspace,
            "--case-id",
            "round7-workflow-red",
            "--mode",
            mode,
        )
        self.assertEqual(0, started.returncode, started.stderr)
        return workspace

    def test_safety_response_cannot_direct_contact_with_the_threat_actor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = self.start(
                root,
                "他拿着刀在门外，说要杀了我。",
                "safety",
            )
            response = root / "unsafe-response.md"
            response.write_text(
                "立即联系威胁你的人，和他当面对质。",
                encoding="utf-8",
            )
            acknowledged = self.run_workflow(
                "acknowledge-safety",
                "--workspace",
                workspace,
                "--response",
                response,
            )
            self.assertNotEqual(0, acknowledged.returncode)
            self.assertIn("SAFETY_RESPONSE_INVALID", acknowledged.stderr)
            state = json.loads(
                (workspace / "state.json").read_text(encoding="utf-8")
            )
            self.assertEqual("safety_action_required", state["phase"])
            self.assertFalse((workspace / "safety-response.md").exists())

    def test_parallel_checks_cannot_lose_attempt_updates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case = valid_standard()
            workspace = self.start(
                root,
                case["inputs"][0]["text"],
                "standard",
            )
            draft_path = workspace / "casefile.json"
            draft = json.loads(draft_path.read_text(encoding="utf-8"))
            draft["claims"] = [{} for _ in range(1500)]
            draft_path.write_text(
                json.dumps(draft, ensure_ascii=False),
                encoding="utf-8",
            )
            worker_count = 6
            barrier = threading.Barrier(worker_count)
            results = []
            result_lock = threading.Lock()

            def run_check():
                barrier.wait()
                completed = self.run_workflow("check", "--workspace", workspace)
                with result_lock:
                    results.append(completed)

            workers = [threading.Thread(target=run_check) for _ in range(worker_count)]
            for worker in workers:
                worker.start()
            for worker in workers:
                worker.join(timeout=20)

            self.assertEqual(worker_count, len(results))
            state = json.loads(
                (workspace / "state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(2, state["attempt_count"])
            self.assertEqual("blocked", state["phase"])
            self.assertEqual(
                ["receipts/attempt-1.json", "receipts/attempt-2.json"],
                state["receipt_paths"],
            )
            status = self.run_workflow("status", "--workspace", workspace)
            self.assertEqual(0, status.returncode, status.stderr)
            self.assertTrue(json.loads(status.stdout)["integrity_valid"])


if __name__ == "__main__":
    unittest.main()
