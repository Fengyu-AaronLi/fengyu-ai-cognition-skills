from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import improvement_loop  # noqa: E402
import test_round86_workflow_step_ledger_red as round86  # noqa: E402


class Round88ControllerOwnedTerminalStepsRedTests(unittest.TestCase):
    """The fixed producer must yield four distinct terminal phase receipts."""

    def state_at_clean_install(self, root: Path):
        helper = round86.Round86WorkflowStepLedgerRedTests()
        paths, state = helper.make_graph_candidate(root)
        dependencies = dict(improvement_loop.REQUIRED_EXECUTION_GRAPH)
        for step_id in improvement_loop.EXTERNAL_EXECUTION_STEPS:
            accepted = {
                item["step_id"]: item["receipt"]["sha256"]
                for item in state["iterations"][-1]["step_ledger"]
            }
            receipt, _ = helper.write_receipt(
                paths,
                state,
                step_id,
                dependency_receipts={
                    dependency: accepted[dependency]
                    for dependency in dependencies[step_id]
                },
            )
            state = helper.record(paths, step_id, receipt)
        self.assertEqual("clean_install", state["iterations"][-1]["next_step"])
        return paths, state

    def make_artifacts(self, paths):
        artifacts = {}
        for step_id in improvement_loop.CONTROLLER_EXECUTION_STEPS:
            path = paths["state_dir"] / f"terminal-{step_id}.artifact.json"
            path.write_text(
                json.dumps({"step_id": step_id, "passed": True}) + "\n",
                encoding="utf-8",
            )
            artifacts[step_id] = {
                "role": f"{step_id}_evidence",
                "path": path.relative_to(paths["repo"]).as_posix(),
                "sha256": round86.sha256(path),
            }
        return artifacts

    def test_terminal_receipts_complete_the_graph_in_order(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round88-complete-") as temp_dir:
            paths, state = self.state_at_clean_install(Path(temp_dir))
            artifacts = self.make_artifacts(paths)
            receipt_paths = improvement_loop.write_controller_step_receipts(
                state,
                (paths["state_dir"] / "terminal-receipts")
                .relative_to(paths["repo"])
                .as_posix(),
                artifacts,
                execution_id="round88-controller-execution",
            )
            completed = improvement_loop.append_controller_step_receipts(
                state, receipt_paths
            )

            iteration = completed["iterations"][-1]
            self.assertIsNone(iteration["next_step"])
            self.assertEqual(
                [step_id for step_id, _ in improvement_loop.REQUIRED_EXECUTION_GRAPH],
                [entry["step_id"] for entry in iteration["step_ledger"]],
            )
            hashes = [
                entry["receipt"]["sha256"]
                for entry in iteration["step_ledger"][-4:]
            ]
            self.assertEqual(4, len(set(hashes)))

    def test_missing_or_reordered_terminal_receipts_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round88-order-") as temp_dir:
            paths, state = self.state_at_clean_install(Path(temp_dir))
            receipt_paths = improvement_loop.write_controller_step_receipts(
                state,
                (paths["state_dir"] / "terminal-receipts")
                .relative_to(paths["repo"])
                .as_posix(),
                self.make_artifacts(paths),
                execution_id="round88-controller-execution",
            )
            for name, values in {
                "missing": receipt_paths[:-1],
                "reordered": [receipt_paths[1], receipt_paths[0], *receipt_paths[2:]],
            }.items():
                with self.subTest(name=name):
                    with self.assertRaises(improvement_loop.LoopError) as raised:
                        improvement_loop.append_controller_step_receipts(state, values)
                    self.assertEqual(
                        "CONTROLLER_STEP_RECEIPTS_INVALID", raised.exception.code
                    )

    def test_dependency_receipt_tamper_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round88-tamper-") as temp_dir:
            paths, state = self.state_at_clean_install(Path(temp_dir))
            receipt_paths = improvement_loop.write_controller_step_receipts(
                state,
                (paths["state_dir"] / "terminal-receipts")
                .relative_to(paths["repo"])
                .as_posix(),
                self.make_artifacts(paths),
                execution_id="round88-controller-execution",
            )
            second = paths["repo"] / receipt_paths[1]
            document = json.loads(second.read_text(encoding="utf-8"))
            document["dependency_receipts"] = {"clean_install": "0" * 64}
            second.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
            with self.assertRaises(improvement_loop.LoopError) as raised:
                improvement_loop.append_controller_step_receipts(state, receipt_paths)
            self.assertEqual("CONTROLLER_STEP_RECEIPTS_INVALID", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
