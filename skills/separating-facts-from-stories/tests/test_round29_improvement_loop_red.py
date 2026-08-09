from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[1]
LOOP_SCRIPT = SKILL_DIR / "scripts" / "improvement_loop.py"
REQUIRED_GATE_CHECKS = (
    "p0_zero",
    "reproducible_p1_zero",
    "unit_tests",
    "self_test",
    "frozen_eval_18_of_18",
    "artifacts_16_of_16",
    "clean_install",
    "verify_install",
    "rollback",
)
WORKFLOW_STEPS_TEXT = (
    "steps:\n"
    "  - id: preflight_snapshot\n"
    "  - id: adversarial_review\n"
    "    depends_on: [preflight_snapshot]\n"
    "  - id: red_green_fix\n"
    "    depends_on: [adversarial_review]\n"
    "  - id: deterministic_gate\n"
    "    depends_on: [red_green_fix]\n"
    "  - id: independent_recheck\n"
    "    depends_on: [deterministic_gate]\n"
    "  - id: source_freeze\n"
    "    depends_on: [independent_recheck]\n"
    "  - id: frozen_eval_prepare\n"
    "    depends_on: [source_freeze]\n"
    "  - id: isolated_eval\n"
    "    depends_on: [frozen_eval_prepare]\n"
    "  - id: eval_audit\n"
    "    depends_on: [isolated_eval]\n"
    "  - id: clean_install\n"
    "    depends_on: [eval_audit]\n"
    "  - id: rollback_validation\n"
    "    depends_on: [clean_install]\n"
    "  - id: evidence_gate\n"
    "    depends_on: [rollback_validation]\n"
    "  - id: loop_decision\n"
    "    depends_on: [evidence_gate]\n"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Round29ImprovementLoopRedTests(unittest.TestCase):
    maxDiff = None

    def run_loop(
        self,
        *args: object,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        process_env = os.environ.copy()
        if env:
            process_env.update(env)
        return subprocess.run(
            [sys.executable, str(LOOP_SCRIPT), *map(str, args)],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
            env=process_env,
        )

    def parsed(self, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        self.assertTrue(result.stdout.strip(), result.stderr)
        value = json.loads(result.stdout)
        self.assertIsInstance(value, dict)
        return value

    def make_candidate(self, root: Path) -> dict[str, Path]:
        repo = root / "candidate"
        skill = repo / "skills" / "separating-facts-from-stories"
        tests = skill / "tests"
        workflows = repo / "workflows"
        tests.mkdir(parents=True)
        workflows.mkdir(parents=True)
        skill_file = skill / "SKILL.md"
        red_test = tests / "test_probe.py"
        workflow = workflows / "separating-facts-loop.yaml"
        source_manifest = workflows / "separating-facts-release-sources.json"
        controller = skill / "scripts" / "improvement_loop.py"
        controller.parent.mkdir(parents=True)
        controller.write_text("# frozen controller fixture\n", encoding="utf-8")
        skill_file.write_text(
            "---\nname: separating-facts-from-stories\n---\n# Candidate\n",
            encoding="utf-8",
        )
        red_test.write_text(
            "import unittest\n"
            "class Probe(unittest.TestCase):\n"
            "    def test_probe(self): self.assertTrue(True)\n",
            encoding="utf-8",
        )
        workflow.write_text(
            "name: separating-facts-loop\n"
            "controller:\n"
            "  executable: \"skills/separating-facts-from-stories/scripts/improvement_loop.py\"\n"
            "  schema_version: \"1.1.0\"\n"
            "  source_manifest: \"workflows/separating-facts-release-sources.json\"\n"
            "loop_policy:\n"
            "  back_edge: loop_decision -> preflight_snapshot\n"
            "  max_rounds: 3\n"
            "  required_gate_checks:\n"
            + "".join(f"    - {item}\n" for item in REQUIRED_GATE_CHECKS)
            + "write_policy:\n"
            "  allowed_roots:\n"
            "    - \"skills/separating-facts-from-stories\"\n"
            "    - \"workflows\"\n"
            "    - \".ao-output\"\n"
            "  denied_operations:\n"
            "    - delete\n"
            "    - push\n"
            "    - publish\n"
            + WORKFLOW_STEPS_TEXT,
            encoding="utf-8",
        )
        source_manifest.write_text(
            json.dumps(
                {
                    "schema_version": "1.0.0",
                    "source_files": sorted(
                        [
                            "skills/separating-facts-from-stories/SKILL.md",
                            "skills/separating-facts-from-stories/scripts/improvement_loop.py",
                            "skills/separating-facts-from-stories/tests/test_probe.py",
                            "workflows/separating-facts-loop.yaml",
                            "workflows/separating-facts-release-sources.json",
                        ]
                    ),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return {
            "repo": repo,
            "skill_file": skill_file,
            "red_test": red_test,
            "workflow": workflow,
            "source_manifest": source_manifest,
            "controller": controller,
            "state_dir": repo / ".ao-output" / "loop-run",
        }

    def start(self, paths: dict[str, Path], *, max_rounds: int = 3) -> dict[str, Any]:
        result = self.run_loop(
            "start",
            "--repo-root",
            paths["repo"],
            "--workflow",
            "workflows/separating-facts-loop.yaml",
            "--state-dir",
            ".ao-output/loop-run",
            "--source-file",
            "skills/separating-facts-from-stories/SKILL.md",
            "--source-file",
            "skills/separating-facts-from-stories/tests/test_probe.py",
            "--source-file",
            "workflows/separating-facts-loop.yaml",
            "--source-file",
            "workflows/separating-facts-release-sources.json",
            "--allow-write",
            "skills/separating-facts-from-stories",
            "--allow-write",
            "workflows",
            "--allow-write",
            ".ao-output",
            "--max-rounds",
            max_rounds,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return self.parsed(result)

    def write_finding(self, paths: dict[str, Path]) -> tuple[Path, dict[str, str]]:
        finding = {
            "finding_id": "R29-P1-001",
            "severity": "P1",
            "summary": "The declarative back edge did not execute another round.",
            "reproducer": "Run a failed gate through advance.",
            "actual": "The previous runner stopped after one DAG pass.",
            "expected": "A new iteration is durably created.",
        }
        path = paths["state_dir"] / "finding.json"
        path.write_text(json.dumps(finding, indent=2) + "\n", encoding="utf-8")
        return path, finding

    def write_gate(
        self,
        paths: dict[str, Path],
        state: dict[str, Any],
        *,
        overrides: dict[str, Any] | None = None,
        name: str = "gate.json",
    ) -> tuple[Path, dict[str, Any]]:
        checks: dict[str, Any] = {key: True for key in REQUIRED_GATE_CHECKS}
        if overrides:
            checks.update(overrides)
        gate = {
            "schema_version": "1.1.0",
            "iteration_id": state["iterations"][-1]["iteration_id"],
            "source_sha256": state["source_snapshot"]["sha256"],
            "checks": checks,
        }
        roles = {
            "p0_zero": "reviewer_report",
            "reproducible_p1_zero": "reviewer_report",
            "unit_tests": "unit_test_log",
            "self_test": "self_test_log",
            "frozen_eval_18_of_18": "machine_report",
            "artifacts_16_of_16": "eval_artifact_report",
            "clean_install": "install_manifest",
            "verify_install": "verification_report",
            "rollback": "rollback_receipt",
        }
        stem = Path(name).stem
        gate["evidence"] = {}
        for key in REQUIRED_GATE_CHECKS:
            passed = checks[key] if type(checks[key]) is bool else False
            command_exit = 0 if passed else 1
            proof_by_check = {
                "p0_zero": {
                    "open_count": 0 if passed else 1,
                    "reviewer_id": "fixture-reviewer-p0",
                    "execution_id": "fixture-execution-p0",
                    "model_environment": {
                        "runner": "fixture-runner",
                        "model": "fixture-model",
                        "isolation": "fresh codex exec --ephemeral; no resume; host observed",
                        "reasoning": "high",
                        "execution_id": "fixture-execution-p0",
                    },
                    "review_scope": [
                        "runtime_semantics",
                        "safety_routing",
                        "state_integrity",
                        "release_evidence",
                        "packaging_installation",
                        "documentation_claims",
                    ],
                    "host_execution_receipt_sha256": "a" * 64,
                    "trust_boundary": "controller_observed_local_codex_process_and_thread_not_external_identity_proof",
                },
                "reproducible_p1_zero": {
                    "open_count": 0 if passed else 1,
                    "reviewer_id": "fixture-reviewer-p1",
                    "execution_id": "fixture-execution-p1",
                    "model_environment": {
                        "runner": "fixture-runner",
                        "model": "fixture-model",
                        "isolation": "fresh codex exec --ephemeral; no resume; host observed",
                        "reasoning": "high",
                        "execution_id": "fixture-execution-p1",
                    },
                    "review_scope": [
                        "runtime_semantics",
                        "safety_routing",
                        "state_integrity",
                        "release_evidence",
                        "packaging_installation",
                        "documentation_claims",
                    ],
                    "host_execution_receipt_sha256": "b" * 64,
                    "trust_boundary": "controller_observed_local_codex_process_and_thread_not_external_identity_proof",
                },
                "unit_tests": {
                    "tests_run": 1,
                    "failures": 0 if passed else 1,
                    "errors": 0,
                    "skipped": 0,
                    "expected_failures": 0,
                    "test_source_set_sha256": "1" * 64,
                },
                "self_test": {
                    "checks_run": 1,
                    "failures": 0 if passed else 1,
                },
                "frozen_eval_18_of_18": {
                    "expected_cases": 18,
                    "completed_cases": 18 if passed else 17,
                    "missing_cases": 0 if passed else 1,
                    "suite_errors": 0,
                },
                "artifacts_16_of_16": {
                    "expected_artifacts": 16,
                    "completed_artifacts": 16 if passed else 15,
                    "passed": 16 if passed else 15,
                    "failed": 0 if passed else 1,
                },
                "clean_install": {
                    "destination_was_absent": passed,
                    "installed_file_count": 1 if passed else 0,
                    "manifest_sha256": "2" * 64,
                    "install_exit_code": command_exit,
                },
                "verify_install": {
                    "valid": passed,
                    "error_count": 0 if passed else 1,
                    "manifest_sha256": "2" * 64,
                    "verify_exit_code": command_exit,
                },
                "rollback": {
                    "operation": "file_level_rollback_and_restore",
                    "installed_path": "/tmp/clean-target/separating-facts-from-stories",
                    "baseline_state_sha256": "3" * 64,
                    "rolled_back_state_sha256": ("3" if passed else "4") * 64,
                    "install_absent_during_rollback": passed,
                    "original_path_absent_in_fresh_python_process": passed,
                    "restore_verified": passed,
                    "installed_manifest_sha256": "2" * 64,
                    "restored_manifest_sha256": ("2" if passed else "5") * 64,
                },
            }
            artifact_path = paths["state_dir"] / f"{stem}.{key}.artifact.json"
            artifact_path.write_text(
                json.dumps({"gate_check": key, "captured": True}, indent=2)
                + "\n",
                encoding="utf-8",
            )
            evidence_path = paths["state_dir"] / f"{stem}.{key}.evidence.json"
            evidence = {
                "schema_version": "1.1.0",
                "iteration_id": gate["iteration_id"],
                "source_sha256": gate["source_sha256"],
                "gate_check": key,
                "passed": passed,
                "proof": proof_by_check[key],
                "commands": (
                    []
                    if key in {"p0_zero", "reproducible_p1_zero"}
                    else (
                        [
                            {"argv": ["test-command", key, str(index)], "exit_code": command_exit}
                            for index in range(3 if key == "rollback" else 1)
                        ]
                    )
                ),
                "artifacts": [
                    {
                        "role": roles[key],
                        "path": str(artifact_path.relative_to(paths["repo"])),
                        "sha256": _sha256(artifact_path),
                    }
                ],
            }
            evidence_path.write_text(
                json.dumps(evidence, indent=2) + "\n", encoding="utf-8"
            )
            gate["evidence"][key] = {
                "path": str(evidence_path.relative_to(paths["repo"])),
                "sha256": _sha256(evidence_path),
                "json_pointer": "/passed",
                "expected": checks[key],
            }
        path = paths["state_dir"] / name
        path.write_text(json.dumps(gate, indent=2) + "\n", encoding="utf-8")
        return path, gate

    def advance(
        self,
        paths: dict[str, Path],
        gate: Path,
        *,
        finding: Path | None = None,
        env: dict[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        args: list[object] = [
            "advance",
            "--state-dir",
            paths["state_dir"],
            "--gate",
            gate,
        ]
        if finding is not None:
            args.extend(
                [
                    "--finding",
                    finding,
                    "--red-test",
                    "skills/separating-facts-from-stories/tests/test_probe.py",
                ]
            )
        return self.run_loop(*args, env=env)

    def test_start_persists_iteration_source_and_workflow_identity(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-loop-start-") as temp_dir:
            paths = self.make_candidate(Path(temp_dir))
            state = self.start(paths)

            self.assertEqual("active", state["status"])
            self.assertEqual(1, state["current_round"])
            self.assertEqual(3, state["max_rounds"])
            self.assertEqual(1, len(state["iterations"]))
            self.assertRegex(state["iterations"][0]["iteration_id"], r"^r001-[0-9a-f]{12}$")
            self.assertEqual(
                state["source_snapshot"]["sha256"],
                state["iterations"][0]["source_sha256"],
            )
            self.assertEqual(64, len(state["source_snapshot"]["sha256"]))
            self.assertEqual(
                "workflows/separating-facts-loop.yaml", state["workflow"]["path"]
            )
            persisted = json.loads(
                (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(state, persisted)

    def test_loop_decision_persists_evidence_and_really_advances(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-loop-advance-") as temp_dir:
            paths = self.make_candidate(Path(temp_dir))
            started = self.start(paths)
            finding_path, finding = self.write_finding(paths)
            gate_path, gate = self.write_gate(
                paths, started, overrides={"clean_install": False}
            )

            result = self.advance(paths, gate_path, finding=finding_path)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            state = self.parsed(result)

            self.assertEqual("LOOP", state["decision"])
            self.assertEqual("active", state["status"])
            self.assertEqual(2, state["current_round"])
            self.assertEqual(2, len(state["iterations"]))
            completed, following = state["iterations"]
            self.assertEqual(finding, completed["finding"])
            self.assertEqual(gate["checks"], completed["gate_result"]["checks"])
            self.assertEqual(
                "skills/separating-facts-from-stories/tests/test_probe.py",
                completed["red_test"]["path"],
            )
            self.assertEqual(_sha256(paths["red_test"]), completed["red_test"]["sha256"])
            self.assertEqual("LOOP", completed["decision"])
            self.assertNotEqual(completed["iteration_id"], following["iteration_id"])
            self.assertEqual(finding["finding_id"], following["carried_findings"][0])

    def test_stop_requires_a_current_gate_with_every_required_boolean_true(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-loop-stop-") as temp_dir:
            paths = self.make_candidate(Path(temp_dir))
            started = self.start(paths)

            missing_gate = self.advance(paths, paths["state_dir"] / "missing.json")
            self.assertNotEqual(0, missing_gate.returncode)
            self.assertEqual("GATE_REQUIRED", self.parsed(missing_gate)["error"]["code"])

            malformed_path, _ = self.write_gate(paths, started, name="malformed.json")
            malformed = json.loads(malformed_path.read_text(encoding="utf-8"))
            malformed["checks"].pop("rollback")
            malformed["checks"]["unit_tests"] = "true"
            malformed_path.write_text(
                json.dumps(malformed, indent=2) + "\n", encoding="utf-8"
            )
            rejected = self.advance(paths, malformed_path)
            self.assertNotEqual(0, rejected.returncode)
            self.assertEqual("GATE_INVALID", self.parsed(rejected)["error"]["code"])

            gate_path, _ = self.write_gate(paths, started)
            stopped = self.advance(paths, gate_path)
            self.assertEqual(0, stopped.returncode, stopped.stdout + stopped.stderr)
            state = self.parsed(stopped)
            self.assertEqual("STOP", state["decision"])
            self.assertEqual("completed", state["status"])
            self.assertEqual(1, state["current_round"])
            self.assertTrue(state["iterations"][0]["gate_result"]["all_true"])

    def test_false_gate_at_max_rounds_is_budget_exhausted_never_stop(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-loop-budget-") as temp_dir:
            paths = self.make_candidate(Path(temp_dir))
            started = self.start(paths, max_rounds=1)
            finding_path, _ = self.write_finding(paths)
            gate_path, _ = self.write_gate(
                paths, started, overrides={"reproducible_p1_zero": False}
            )

            result = self.advance(paths, gate_path, finding=finding_path)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            state = self.parsed(result)
            self.assertEqual("BUDGET_EXHAUSTED", state["decision"])
            self.assertEqual("blocked", state["status"])
            self.assertEqual("max_rounds_reached", state["stop_reason"])
            self.assertNotEqual("STOP", state["decision"])
            self.assertEqual(1, len(state["iterations"]))

    def test_source_drift_invalidates_an_old_all_true_gate_and_loops(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-loop-drift-") as temp_dir:
            paths = self.make_candidate(Path(temp_dir))
            started = self.start(paths)
            original_hash = started["source_snapshot"]["sha256"]
            gate_path, _ = self.write_gate(paths, started)
            paths["skill_file"].write_text(
                paths["skill_file"].read_text(encoding="utf-8") + "\nChanged.\n",
                encoding="utf-8",
            )

            result = self.advance(paths, gate_path)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            state = self.parsed(result)
            self.assertEqual("LOOP", state["decision"])
            self.assertEqual(2, state["current_round"])
            self.assertNotEqual(original_hash, state["source_snapshot"]["sha256"])
            prior_gate = state["iterations"][0]["gate_result"]
            self.assertFalse(prior_gate["valid"])
            self.assertEqual("SOURCE_DRIFT_INVALIDATED_GATE", prior_gate["code"])
            self.assertNotEqual("STOP", state["iterations"][0]["decision"])

    def test_crash_after_prepare_is_resumed_exactly_once(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-loop-recovery-") as temp_dir:
            paths = self.make_candidate(Path(temp_dir))
            started = self.start(paths)
            finding_path, _ = self.write_finding(paths)
            gate_path, _ = self.write_gate(
                paths, started, overrides={"clean_install": False}
            )

            crashed = self.advance(
                paths,
                gate_path,
                finding=finding_path,
                env={"SFFS_IMPROVEMENT_LOOP_FAILPOINT": "after_prepare"},
            )
            self.assertNotEqual(0, crashed.returncode)
            state_after_crash = json.loads(
                (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual(1, state_after_crash["current_round"])
            self.assertTrue((paths["state_dir"] / "pending-transition.json").is_file())

            resumed = self.run_loop("resume", "--state-dir", paths["state_dir"])
            self.assertEqual(0, resumed.returncode, resumed.stdout + resumed.stderr)
            recovered = self.parsed(resumed)
            self.assertEqual(2, recovered["current_round"])
            self.assertEqual(2, len(recovered["iterations"]))
            committed = list((paths["state_dir"] / "transactions").glob("*.json"))
            self.assertTrue(committed, "prepared transaction was deleted instead of archived")
            self.assertTrue(
                any(
                    json.loads(path.read_text(encoding="utf-8")).get("status")
                    == "committed"
                    for path in committed
                )
            )

            repeated = self.run_loop("resume", "--state-dir", paths["state_dir"])
            self.assertEqual(0, repeated.returncode, repeated.stdout + repeated.stderr)
            repeated_state = self.parsed(repeated)
            self.assertEqual(2, repeated_state["current_round"])
            self.assertEqual(2, len(repeated_state["iterations"]))

    def test_guard_allows_only_configured_write_roots_and_blocks_escapes(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-loop-guard-") as temp_dir:
            paths = self.make_candidate(Path(temp_dir))
            self.start(paths)

            allowed = self.run_loop(
                "guard",
                "--state-dir",
                paths["state_dir"],
                "--operation",
                "write",
                "--path",
                "skills/separating-facts-from-stories/tests/new_red.py",
            )
            self.assertEqual(0, allowed.returncode, allowed.stdout + allowed.stderr)
            self.assertTrue(self.parsed(allowed)["allowed"])

            outside_scope = self.run_loop(
                "guard",
                "--state-dir",
                paths["state_dir"],
                "--operation",
                "write",
                "--path",
                "README.md",
            )
            self.assertNotEqual(0, outside_scope.returncode)
            self.assertEqual(
                "WRITE_SCOPE_DENIED", self.parsed(outside_scope)["error"]["code"]
            )

            absolute_outside = Path(temp_dir) / "not-the-candidate" / "file.md"
            outside_repo = self.run_loop(
                "guard",
                "--state-dir",
                paths["state_dir"],
                "--operation",
                "write",
                "--path",
                absolute_outside,
            )
            self.assertNotEqual(0, outside_repo.returncode)
            self.assertEqual(
                "PATH_OUTSIDE_REPO", self.parsed(outside_repo)["error"]["code"]
            )

            outside = Path(temp_dir) / "outside"
            outside.mkdir()
            escape = paths["repo"] / "skills" / "separating-facts-from-stories" / "escape"
            escape.symlink_to(outside, target_is_directory=True)
            symlink_escape = self.run_loop(
                "guard",
                "--state-dir",
                paths["state_dir"],
                "--operation",
                "write",
                "--path",
                "skills/separating-facts-from-stories/escape/file.md",
            )
            self.assertNotEqual(0, symlink_escape.returncode)
            self.assertEqual(
                "PATH_SYMLINK_ESCAPE", self.parsed(symlink_escape)["error"]["code"]
            )

    def test_guard_rejects_protected_paths_delete_push_and_publish(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-loop-deny-") as temp_dir:
            paths = self.make_candidate(Path(temp_dir))
            self.start(paths)
            victim = paths["red_test"]

            protected_paths = (
                ".claude/settings.json",
                "CLAUDE.md",
                "10-自媒体/12-观点索引/VP-999.md",
                "10-自媒体/17-观点库HL/HL-999.md",
                "10-自媒体/13-选题库/TP-999.md",
                "10-自媒体/11-已发布文案/published.md",
                "80-投资/83-投资信号/signal.md",
            )
            for protected_path in protected_paths:
                with self.subTest(protected_path=protected_path):
                    protected_write = self.run_loop(
                        "guard",
                        "--state-dir",
                        paths["state_dir"],
                        "--operation",
                        "write",
                        "--path",
                        protected_path,
                    )
                    self.assertNotEqual(0, protected_write.returncode)
                    self.assertEqual(
                        "PROTECTED_PATH",
                        self.parsed(protected_write)["error"]["code"],
                    )

            cases = (
                ("delete", "skills/separating-facts-from-stories/tests/test_probe.py", "DELETE_DENIED"),
                ("push", None, "PUSH_DENIED"),
                ("publish", None, "PUBLISH_DENIED"),
            )
            for operation, path, expected_code in cases:
                with self.subTest(operation=operation):
                    args: list[object] = [
                        "guard",
                        "--state-dir",
                        paths["state_dir"],
                        "--operation",
                        operation,
                    ]
                    if path is not None:
                        args.extend(["--path", path])
                    rejected = self.run_loop(*args)
                    self.assertNotEqual(0, rejected.returncode)
                    self.assertEqual(
                        expected_code, self.parsed(rejected)["error"]["code"]
                    )
            self.assertTrue(victim.is_file(), "guard performed the forbidden deletion")


if __name__ == "__main__":
    unittest.main()
