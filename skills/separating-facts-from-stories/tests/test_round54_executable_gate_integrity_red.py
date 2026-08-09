from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
LOOP_PATH = SKILL_DIR / "scripts" / "improvement_loop.py"
PRODUCER_PATH = SKILL_DIR / "scripts" / "produce_release_gate.py"

sys.path.insert(0, str(SKILL_DIR / "tests"))
import test_round29_improvement_loop_red as round29  # noqa: E402
from host_execution_fixture import prepare_review_source, write_host_review  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Round54ExecutableGateIntegrityRedTests(unittest.TestCase):
    maxDiff = None

    def test_stop_revalidates_source_immediately_before_commit(self) -> None:
        loop = load_module("round54_commit_source_cas", LOOP_PATH)
        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round54-commit-cas-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            state = helper.start(paths)
            gate_path, _ = helper.write_gate(paths, state)
            original_validate = loop.validate_gate_evidence
            mutation_count = 0

            def mutate_after_gate_validation(repo_root, gate, **kwargs):
                nonlocal mutation_count
                original_validate(repo_root, gate, **kwargs)
                if mutation_count == 0:
                    paths["skill_file"].write_text(
                        paths["skill_file"].read_text(encoding="utf-8")
                        + "\nlate source change\n",
                        encoding="utf-8",
                    )
                mutation_count += 1

            loop.validate_gate_evidence = mutate_after_gate_validation
            with self.assertRaises(loop.LoopError) as raised:
                loop.command_advance(
                    argparse.Namespace(
                        state_dir=str(paths["state_dir"]),
                        gate=str(gate_path),
                        finding=None,
                        red_test=None,
                    )
                )
            self.assertEqual("SOURCE_DRIFT_DURING_COMMIT", raised.exception.code)
            persisted = json.loads(
                (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual("active", persisted["status"])
            self.assertIsNone(persisted["decision"])

    def test_timeout_terminates_the_whole_inherited_process_group(self) -> None:
        producer = load_module("round54_timeout_process_group", PRODUCER_PATH)
        with tempfile.TemporaryDirectory(prefix="sffs-round54-timeout-") as temp_dir:
            root = Path(temp_dir)
            marker = root / "grandchild-survived.txt"
            script = root / "spawn-grandchild.py"
            script.write_text(
                "import subprocess,sys,time\n"
                "subprocess.Popen([sys.executable,'-I','-S','-B','-c',"
                "'import pathlib,sys,time; time.sleep(0.4); pathlib.Path(sys.argv[1]).write_text(\\\"alive\\\")',"
                "sys.argv[1]],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n"
                "time.sleep(5)\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "RECIPE_TIMEOUT"):
                producer.run_isolated_command(
                    step_id="timeout-process-group",
                    script=script,
                    arguments=[str(marker)],
                    cwd=root,
                    timeout_seconds=0.1,
                    receipt_path=root / "receipt.json",
                )
            time.sleep(0.8)
            self.assertFalse(marker.exists(), "a timed-out grandchild remained alive")

    def test_review_pair_rejects_cross_swapped_severity_sets(self) -> None:
        producer = load_module("round54_review_pair", PRODUCER_PATH)
        with tempfile.TemporaryDirectory(prefix="sffs-round54-review-") as temp_dir:
            root = Path(temp_dir)
            source_sha = prepare_review_source(root)
            _, p0_report = write_host_review(
                root,
                "p0_zero",
                source_sha,
                suffix="p0",
                findings=[
                    {
                        "finding_id": "OPEN-P1",
                        "severity": "P1",
                        "reproducible": True,
                        "status": "open",
                    }
                ],
            )
            _, p1_report = write_host_review(
                root,
                "reproducible_p1_zero",
                source_sha,
                suffix="p1",
                findings=[
                    {
                        "finding_id": "OPEN-P0",
                        "severity": "P0",
                        "reproducible": True,
                        "status": "open",
                    }
                ],
            )
            with self.assertRaisesRegex(ValueError, "same findings"):
                producer.validate_review_pair(
                    p0_report, p1_report, source_sha256=source_sha, repo_root=root
                )

    def test_validator_rejects_raw_command_exit_that_differs_from_summary(self) -> None:
        loop = load_module("round54_raw_receipt_binding", LOOP_PATH)
        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round54-receipt-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            state = helper.start(paths)
            gate_path, gate = helper.write_gate(paths, state)
            producer_script = paths["controller"].with_name("produce_release_gate.py")
            producer_script.write_text("# producer fixture\n", encoding="utf-8")
            raw_dir = paths["state_dir"] / "raw"
            raw_dir.mkdir()
            indexed_receipts: dict[str, str] = {}

            for check in round29.REQUIRED_GATE_CHECKS:
                evidence_ref = gate["evidence"][check]
                evidence_path = paths["repo"] / evidence_ref["path"]
                evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
                command_receipts = []
                for index, command in enumerate(evidence["commands"], start=1):
                    receipt_path = raw_dir / f"{check}-{index}.json"
                    raw_exit = 7 if check == "unit_tests" else command["exit_code"]
                    receipt = {
                        "schema_version": "1.1.0",
                        "recipe_version": "2.0.0",
                        "step_id": check,
                        "argv": command["argv"],
                        "cwd": str(paths["repo"].resolve()),
                        "timeout_seconds": 300,
                        "shell": False,
                        "environment_policy": {
                            "PYTHONPATH": "removed",
                            "PYTHONHOME": "removed",
                            "PYTHONNOUSERSITE": "1",
                            "PYTHONDONTWRITEBYTECODE": "1",
                        },
                        "exit_code": raw_exit,
                        "timed_out": False,
                        "stdout": "{}",
                        "stderr": "",
                        "process_family_policy": {
                            "token_sha256": "c" * 64,
                            "same_uid_only": True,
                            "confirmed_empty": True,
                            "trust_boundary": "cooperative_inherited_token_not_os_sandbox",
                        },
                    }
                    receipt_path.write_text(
                        json.dumps(receipt, indent=2) + "\n", encoding="utf-8"
                    )
                    indexed_receipts[receipt_path.name] = sha256(receipt_path)
                    command_receipts.append(
                        {
                            "path": str(receipt_path.relative_to(paths["repo"])),
                            "sha256": sha256(receipt_path),
                        }
                    )
                evidence["command_receipts"] = command_receipts
                evidence_path.write_text(
                    json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
                )
                evidence_ref["sha256"] = sha256(evidence_path)

            receipt_index_path = paths["state_dir"] / "raw-receipt-index.json"
            receipt_index_path.write_text(
                json.dumps(
                    {
                        "schema_version": "1.1.0",
                        "recipe_version": "2.0.0",
                        "iteration_id": state["iterations"][0]["iteration_id"],
                        "source_sha256": state["source_snapshot"]["sha256"],
                        "receipts": indexed_receipts,
                    },
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            gate["producer"] = {
                "authority": "controller_prove_stop",
                "recipe_version": "2.0.0",
                "script_path": str(producer_script.relative_to(paths["repo"])),
                "script_sha256": sha256(producer_script),
                "raw_receipt_index_path": str(
                    receipt_index_path.relative_to(paths["repo"])
                ),
                "raw_receipt_index_sha256": sha256(receipt_index_path),
            }
            gate_path.write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")

            loop.validate_gate_shape(gate)
            with self.assertRaises(loop.LoopError) as raised:
                loop.validate_gate_evidence(
                    paths["repo"].resolve(),
                    gate,
                    iteration_id_value=state["iterations"][0]["iteration_id"],
                    source_sha256=state["source_snapshot"]["sha256"],
                )
            self.assertEqual("GATE_COMMAND_RECEIPT_MISMATCH", raised.exception.code)


if __name__ == "__main__":
    unittest.main()
