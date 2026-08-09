import copy
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_casefile import SCRIPT, valid_standard


SKILL_DIR = Path(__file__).resolve().parents[1]
WORKFLOW = SKILL_DIR / "scripts" / "workflow.py"


def load_runtime():
    spec = importlib.util.spec_from_file_location("casefile_round5_state_red", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Round5StateRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.casefile = load_runtime()

    def run_workflow(self, *args):
        return subprocess.run(
            [sys.executable, str(WORKFLOW), *map(str, args)],
            cwd=SKILL_DIR,
            text=True,
            capture_output=True,
            check=False,
        )

    def write_json(self, path: Path, value: dict) -> None:
        path.write_text(
            json.dumps(value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def start_standard(self, root: Path) -> tuple[Path, dict]:
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
        return workspace, case

    def ready_standard(self, root: Path) -> tuple[Path, dict]:
        workspace, case = self.start_standard(root)
        self.write_json(workspace / "casefile.json", case)
        checked = self.run_workflow("check", "--workspace", workspace)
        self.assertEqual(0, checked.returncode, checked.stderr)
        state = json.loads((workspace / "state.json").read_text(encoding="utf-8"))
        self.assertEqual("ready_to_finalize", state["phase"])
        return workspace, state

    def test_revision_rejects_reordering_prior_rendered_lists(self):
        previous = valid_standard()
        base = self.casefile.start_update(previous, "老板取消了会议。")
        span = next(
            item
            for item in base["source_spans"]
            if item["input_id"] == base["current_input_id"]
            and self.casefile.derive_observation_type(item["text"], item)
            is not None
        )
        base["claims"].append(
            {
                "id": "C3",
                "kind": "observable_fact",
                "observation_type": self.casefile.derive_observation_type(
                    span["text"], span
                ),
                "text": span["text"],
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "user_direct_observation",
                "exact_quote": span["text"],
                "epistemic_status": "reported",
                "diagnostic_boundary": False,
            }
        )
        base["evidence"].append(
            {
                "id": "E2",
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "user_direct_observation",
                "exact_quote": span["text"],
                "can_establish": ["C3"],
                "cannot_establish": [],
                "limitations": ["single_party_report"],
            }
        )
        base["evidence_links"].append(
            {
                "proposition_id": "C3",
                "evidence_ref": "E2",
                "relation": "supports",
                "strength": "direct",
                "reason": "anchor_matches_report",
            }
        )
        self.assertEqual([], self.casefile.validate_casefile(base, previous=previous))

        for field in ("claims", "evidence_links"):
            with self.subTest(field=field):
                current = copy.deepcopy(base)
                current[field].reverse()
                codes = {
                    item["code"]
                    for item in self.casefile.validate_casefile(
                        current, previous=previous
                    )
                }
                self.assertIn("HISTORY_ITEM_MUTATED", codes)

    def test_check_recovers_after_receipt_write_before_state_save(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, _ = self.start_standard(Path(temp_dir))
            state_path = workspace / "state.json"
            state_before_check = json.loads(state_path.read_text(encoding="utf-8"))

            first_check = self.run_workflow("check", "--workspace", workspace)
            self.assertEqual(1, first_check.returncode, first_check.stderr)
            self.assertTrue((workspace / "receipts" / "attempt-1.json").is_file())

            # Equivalent on-disk state to a crash after the receipt was atomically
            # written but before the updated state was durably replaced.
            self.write_json(state_path, state_before_check)
            status = self.run_workflow("status", "--workspace", workspace)
            status_payload = json.loads(status.stdout)
            retry = self.run_workflow("check", "--workspace", workspace)

            with self.subTest(step="status"):
                self.assertNotEqual(0, status.returncode)
                self.assertIn(
                    "RECOVERY_REQUIRED",
                    {item["code"] for item in status_payload["integrity_errors"]},
                )
            with self.subTest(step="retry"):
                self.assertEqual(1, retry.returncode, retry.stderr)
                retry_payload = json.loads(retry.stdout)
                self.assertEqual("repair_required", retry_payload["phase"])
                self.assertEqual(1, retry_payload["attempt_count"])

    def test_finalize_recovers_after_response_write_before_state_save(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace, state_before_finalize = self.ready_standard(Path(temp_dir))
            state_path = workspace / "state.json"

            first_finalize = self.run_workflow("finalize", "--workspace", workspace)
            self.assertEqual(0, first_finalize.returncode, first_finalize.stderr)
            self.assertTrue((workspace / "response.md").is_file())

            # This is both the finalize crash window and the observable form of a
            # completed state restored to its pre-finalize snapshot. Recovery must
            # move forward to completed instead of accepting a silent downgrade.
            self.write_json(state_path, state_before_finalize)
            status = self.run_workflow("status", "--workspace", workspace)
            status_payload = json.loads(status.stdout)
            retry = self.run_workflow("finalize", "--workspace", workspace)

            with self.subTest(step="status"):
                self.assertNotEqual(0, status.returncode)
                self.assertIn(
                    "RECOVERY_REQUIRED",
                    {item["code"] for item in status_payload["integrity_errors"]},
                )
            with self.subTest(step="retry"):
                self.assertEqual(0, retry.returncode, retry.stderr)
                self.assertEqual("completed", json.loads(retry.stdout)["phase"])

    def test_state_configuration_is_bound_to_start_event(self):
        mutations = {
            "mode": lambda state: state.__setitem__("mode", "passthrough"),
            "casefile_path": lambda state: state.__setitem__("casefile_path", None),
        }
        for field, mutate in mutations.items():
            with self.subTest(field=field), tempfile.TemporaryDirectory() as temp_dir:
                workspace, _ = self.start_standard(Path(temp_dir))
                state_path = workspace / "state.json"
                state = json.loads(state_path.read_text(encoding="utf-8"))
                mutate(state)
                self.write_json(state_path, state)

                status = self.run_workflow("status", "--workspace", workspace)
                payload = json.loads(status.stdout)
                self.assertNotEqual(0, status.returncode)
                self.assertIn(
                    "STATE_CONFIG_MUTATED",
                    {item["code"] for item in payload["integrity_errors"]},
                )


if __name__ == "__main__":
    unittest.main()
