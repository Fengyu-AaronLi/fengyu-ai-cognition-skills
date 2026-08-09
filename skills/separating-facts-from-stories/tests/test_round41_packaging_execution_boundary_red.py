from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
PACKAGER_PATH = SKILL_DIR / "scripts" / "package_runtime.py"
RUNNER_PATH = SKILL_DIR / "scripts" / "run_evals.py"
sys.path.insert(0, str(SKILL_DIR / "tests"))

import test_round4_release_gate_red as round4_release  # noqa: E402


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Round41PackagingExecutionBoundaryRedTests(unittest.TestCase):
    def test_verify_executes_only_a_hash_verified_private_snapshot(self) -> None:
        packager = load_module("round41_verify_snapshot", PACKAGER_PATH)
        helper = round4_release.Round4ReleaseGateRedTests()
        helper.packager = packager
        helper.runner = load_module("round41_runner_fixture", RUNNER_PATH)
        with tempfile.TemporaryDirectory(prefix="sffs-round41-verify-race-") as temp_dir:
            root = Path(temp_dir)
            installed = helper._make_installed_tree(root)
            runtime_path = installed / "scripts" / "casefile.py"
            marker = root / "mutated-code-executed.txt"
            original_sha256 = packager.sha256_file
            mutated = False

            def mutate_after_hash(path: Path) -> str:
                nonlocal mutated
                digest = original_sha256(path)
                if path.resolve() == runtime_path.resolve() and not mutated:
                    mutated = True
                    runtime_path.write_text(
                        runtime_path.read_text(encoding="utf-8")
                        + "\nfrom pathlib import Path as _RacePath\n"
                        + f"_RacePath({str(marker)!r}).write_text('executed', encoding='utf-8')\n",
                        encoding="utf-8",
                    )
                return digest

            with mock.patch.object(packager, "sha256_file", side_effect=mutate_after_hash):
                result = packager.verify_install(installed)

            self.assertTrue(mutated)
            self.assertFalse(result["valid"], result)
            self.assertFalse(marker.exists(), "mutable installed code was executed")
            self.assertIn(
                "VERIFICATION_SNAPSHOT_MISMATCH",
                {item["code"] for item in result["errors"]},
            )

    def test_preflight_python_processes_are_isolated_and_environment_scrubbed(self) -> None:
        packager = load_module("round41_preflight_isolation", PACKAGER_PATH)
        runtime_probe = packager.run_runtime_probe(SKILL_DIR)
        calls: list[tuple[list[str], dict[str, object]]] = []

        def fake_run(command: list[str], **kwargs: object):
            calls.append((command, kwargs))
            return subprocess.CompletedProcess(command, 0, "{}\n", "")

        with mock.patch.object(packager.subprocess, "run", side_effect=fake_run), mock.patch.object(
            packager, "run_runtime_probe", return_value=runtime_probe
        ), mock.patch.object(
            packager,
            "run_workflow_lifecycle_smoke",
            return_value={
                "exit_codes": {"start": 0, "check": 0, "finalize": 0, "status": 0},
                "completed": True,
                "integrity_valid": True,
                "workflow_version": packager.read_python_string_constant(
                    SKILL_DIR / "scripts" / "workflow.py", "WORKFLOW_VERSION"
                ),
            },
        ):
            packager.preflight(SKILL_DIR)

        self.assertEqual(3, len(calls))
        for command, kwargs in calls:
            self.assertEqual(["-I", "-S", "-B"], command[1:4])
            environment = kwargs.get("env")
            self.assertIsInstance(environment, dict)
            assert isinstance(environment, dict)
            self.assertNotIn("PYTHONPATH", environment)
            self.assertNotIn("PYTHONHOME", environment)
            self.assertEqual("1", environment.get("PYTHONNOUSERSITE"))

    def test_workflow_lifecycle_processes_use_the_same_isolation_boundary(self) -> None:
        packager = load_module("round41_lifecycle_isolation", PACKAGER_PATH)
        runtime = load_module("round41_casefile", SKILL_DIR / "scripts" / "casefile.py")
        calls: list[tuple[list[str], dict[str, object]]] = []

        def fake_run(command: list[str], **kwargs: object):
            calls.append((command, kwargs))
            stdout = "{}\n"
            if "start" in command:
                workspace = Path(command[command.index("--workspace") + 1])
                workspace.mkdir(parents=True, exist_ok=True)
            if "status" in command:
                stdout = json.dumps(
                    {
                        "phase": "completed",
                        "integrity_valid": True,
                        "workflow_version": packager.read_python_string_constant(
                            SKILL_DIR / "scripts" / "workflow.py", "WORKFLOW_VERSION"
                        ),
                    }
                )
                workspace = Path(command[-1])
                (workspace / "response.md").parent.mkdir(parents=True, exist_ok=True)
                (workspace / "response.md").write_text("ok\n", encoding="utf-8")
            return subprocess.CompletedProcess(command, 0, stdout, "")

        with mock.patch.object(packager.subprocess, "run", side_effect=fake_run):
            result = packager.run_workflow_lifecycle_smoke(SKILL_DIR, runtime)

        self.assertTrue(result["completed"])
        self.assertEqual(4, len(calls))
        for command, kwargs in calls:
            self.assertEqual(["-I", "-S", "-B"], command[1:4])
            environment = kwargs.get("env")
            self.assertIsInstance(environment, dict)
            assert isinstance(environment, dict)
            self.assertNotIn("PYTHONPATH", environment)
            self.assertNotIn("PYTHONHOME", environment)

    def test_eval_runtime_replays_have_named_timeouts(self) -> None:
        runner = load_module("round41_runner_timeout", RUNNER_PATH)
        completed = subprocess.CompletedProcess(["python"], 0, "", "")
        with mock.patch.object(runner.subprocess, "run", return_value=completed) as called:
            runner._run_casefile_cli(["--help"])
        self.assertEqual(runner.SUBPROCESS_TIMEOUT_SECONDS, called.call_args.kwargs["timeout"])

        with mock.patch.object(
            runner.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["python"], 1),
        ):
            with self.assertRaisesRegex(RuntimeError, "INVALID_FIXTURE_REPLAY_TIMEOUT"):
                runner.fresh_invalid_fixture_receipt()

    def test_non_utf8_evaluation_context_is_a_structured_runner_error(self) -> None:
        runner = load_module("round41_runner_utf8", RUNNER_PATH)
        with tempfile.TemporaryDirectory(prefix="sffs-round41-context-bytes-") as temp_dir:
            root = Path(temp_dir)
            (root / runner.EVALUATION_CONTEXT_FILE).write_bytes(b"\xff\xfe")
            evidence, digest, errors = runner.inspect_evaluation_context(root)
        self.assertIsNone(evidence)
        self.assertIsInstance(digest, str)
        self.assertEqual("EVAL_CONTEXT_SOURCE_MISMATCH", errors[0]["code"])

    def test_non_utf8_machine_report_is_a_named_package_failure(self) -> None:
        packager = load_module("round41_report_utf8", PACKAGER_PATH)
        with tempfile.TemporaryDirectory(prefix="sffs-round41-report-bytes-") as temp_dir:
            root = Path(temp_dir)
            root.mkdir(exist_ok=True)
            (root / "machine-report.json").write_bytes(b"\xff\xfe")
            (root / packager.EVALUATION_CONTEXT_NAME).write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(OSError, "EVAL_GATE_FAILED.*machine report"):
                packager.run_eval_gate(SKILL_DIR, root)

    def test_directory_commit_uses_atomic_no_replace_semantics(self) -> None:
        packager = load_module("round41_no_replace", PACKAGER_PATH)
        with tempfile.TemporaryDirectory(prefix="sffs-round41-no-replace-") as temp_dir:
            root = Path(temp_dir)
            staged = root / "staged"
            destination = root / "destination"
            staged.mkdir()
            destination.mkdir()
            (staged / "payload").write_text("new\n", encoding="utf-8")
            (destination / "owner").write_text("existing\n", encoding="utf-8")
            with self.assertRaises(FileExistsError):
                packager.commit_directory_no_replace(staged, destination)
            self.assertTrue((staged / "payload").is_file())
            self.assertEqual("existing\n", (destination / "owner").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
