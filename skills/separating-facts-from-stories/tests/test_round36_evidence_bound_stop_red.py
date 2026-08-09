from __future__ import annotations

import hashlib
import json
import os
import py_compile
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
PACKAGER_PATH = SKILL_DIR / "scripts" / "package_runtime.py"
sys.path.insert(0, str(SKILL_DIR / "tests"))

import test_round29_improvement_loop_red as round29  # noqa: E402
import test_round4_release_gate_red as round4_release  # noqa: E402


class Round36EvidenceBoundStopRedTests(unittest.TestCase):
    """RED regressions: STOP must be evidence-bound, not self-declared."""

    @staticmethod
    def parsed(result: object) -> dict[str, object]:
        stdout = getattr(result, "stdout", "")
        if not isinstance(stdout, str) or not stdout.strip():
            raise AssertionError(f"controller returned no JSON: {result!r}")
        value = json.loads(stdout)
        if not isinstance(value, dict):
            raise AssertionError(f"controller output is not an object: {value!r}")
        return value

    def test_nine_bare_true_booleans_cannot_authorize_stop(self) -> None:
        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round36-bare-stop-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            started = helper.start(paths)
            gate_path, _ = helper.write_gate(paths, started)
            bare_gate = json.loads(gate_path.read_text(encoding="utf-8"))
            bare_gate.pop("evidence")
            gate_path.write_text(
                json.dumps(bare_gate, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            result = helper.advance(paths, gate_path)

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            payload = self.parsed(result)
            self.assertEqual(
                "GATE_EVIDENCE_REQUIRED",
                payload["error"]["code"],
                "nine self-authored true values must not be enough to create STOP",
            )
            persisted = json.loads(
                (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual("active", persisted["status"])
            self.assertIsNone(persisted["decision"])

    def test_terminal_stop_without_a_bound_passing_gate_is_invalid_state(self) -> None:
        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round36-forged-stop-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            helper.start(paths)
            state_path = paths["state_dir"] / "loop-state.json"
            forged = json.loads(state_path.read_text(encoding="utf-8"))
            forged["status"] = "completed"
            forged["decision"] = "STOP"
            forged["iterations"][-1]["decision"] = "STOP"
            state_path.write_text(
                json.dumps(forged, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            result = helper.run_loop("resume", "--state-dir", paths["state_dir"])

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            payload = self.parsed(result)
            self.assertEqual("STATE_INVALID", payload["error"]["code"])

    def test_install_verify_rejects_forged_isolation_evidence(self) -> None:
        packager = round4_release.load_module(
            "round36_package_runtime", PACKAGER_PATH
        )
        helper = round4_release.Round4ReleaseGateRedTests()
        helper.packager = packager
        helper.runner = round4_release.load_module(
            "round36_run_evals", SKILL_DIR / "scripts" / "run_evals.py"
        )
        with tempfile.TemporaryDirectory(prefix="sffs-round36-install-") as temp_dir:
            installed = helper._make_installed_tree(Path(temp_dir))
            manifest_path = installed / "runtime-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["preflight"]["packaged_markdown_links_valid"] = True
            unit_gate = manifest["release_gate"]["unit_tests"]
            unit_gate["isolated_python"] = False
            unit_gate["unittest_module_path"] = str(installed / "unittest.py")
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            result = packager.verify_install(installed)

            self.assertFalse(result["valid"])
            self.assertIn(
                "RELEASE_GATE_INVALID",
                {item["code"] for item in result["errors"]},
            )

    def test_sourceless_bytecode_cannot_participate_in_the_unit_gate(self) -> None:
        packager = round4_release.load_module(
            "round36_bytecode_package_runtime", PACKAGER_PATH
        )
        with tempfile.TemporaryDirectory(prefix="sffs-round36-bytecode-") as temp_dir:
            source = Path(temp_dir) / "source"
            tests = source / "tests"
            tests.mkdir(parents=True)
            helper_source = tests / "hidden_helper.py"
            helper_source.write_text("VALUE = 11\n", encoding="utf-8")
            py_compile.compile(
                str(helper_source),
                cfile=str(tests / "hidden_helper.pyc"),
                doraise=True,
            )
            helper_source.unlink()
            (tests / "test_contract.py").write_text(
                "import hidden_helper\n"
                "import unittest\n"
                "class Contract(unittest.TestCase):\n"
                "    def test_hidden(self): self.assertEqual(11, hidden_helper.VALUE)\n",
                encoding="utf-8",
            )
            evidence = {"test_contract": "tests/test_contract.py"}
            with mock.patch.object(
                packager, "REQUIRED_TEST_FILES", {"test_contract.py"}
            ), mock.patch.object(
                packager, "RELEASE_EVIDENCE_FILES", evidence
            ):
                with self.assertRaisesRegex(
                    OSError,
                    "UNIT_TEST_GATE_FAILED.*bytecode",
                ):
                    packager.run_unit_test_gate(source)

    def test_eval_replay_cannot_be_forged_through_pythonpath(self) -> None:
        packager = round4_release.load_module(
            "round36_eval_isolation_package_runtime", PACKAGER_PATH
        )
        runner = round4_release.load_module(
            "round36_eval_isolation_runner", SKILL_DIR / "scripts" / "run_evals.py"
        )
        helper = round4_release.Round4ReleaseGateRedTests()
        helper.packager = packager
        helper.runner = runner
        with tempfile.TemporaryDirectory(prefix="sffs-round36-eval-inject-") as temp_dir:
            root = Path(temp_dir)
            eval_root = root / "fake-eval"
            injector = root / "injector"
            eval_root.mkdir()
            injector.mkdir()

            release_evidence = runner.current_release_evidence()
            context_path = eval_root / packager.EVALUATION_CONTEXT_NAME
            context_path.write_text(
                json.dumps(
                    {"release_evidence": release_evidence},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            report = helper._release_report(SKILL_DIR)
            report["release_evidence"] = release_evidence
            report["evaluation_context_sha256"] = hashlib.sha256(
                context_path.read_bytes()
            ).hexdigest()
            report_path = eval_root / "machine-report.json"
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            (injector / "sitecustomize.py").write_text(
                "import os, pathlib, sys\n"
                "if any(str(item).endswith('run_evals.py') for item in sys.argv):\n"
                "    payload = pathlib.Path(os.environ['SFFS_FORGED_REPORT']).read_text(encoding='utf-8')\n"
                "    os.write(1, payload.encode('utf-8'))\n"
                "    os._exit(0)\n",
                encoding="utf-8",
            )
            injected_env = {
                "PYTHONPATH": str(injector),
                "SFFS_FORGED_REPORT": str(report_path),
            }

            with mock.patch.dict(os.environ, injected_env, clear=False):
                with self.assertRaisesRegex(
                    OSError,
                    "EVAL_GATE_FAILED",
                ):
                    packager.run_eval_gate(SKILL_DIR, eval_root)

    def test_cli_cannot_expand_the_frozen_workflow_policy(self) -> None:
        helper = round29.Round29ImprovementLoopRedTests()
        policy_text = (
            "name: separating-facts-loop\n"
            "controller:\n"
            "  executable: \"skills/separating-facts-from-stories/scripts/improvement_loop.py\"\n"
            "  schema_version: \"1.1.0\"\n"
            "  source_manifest: \"workflows/separating-facts-release-sources.json\"\n"
            "loop_policy:\n"
            "  max_rounds: 2\n"
            "  required_gate_checks:\n"
            + "".join(
                f"    - {item}\n" for item in round29.REQUIRED_GATE_CHECKS
            )
            + "write_policy:\n"
            "  allowed_roots:\n"
            "    - \"skills/separating-facts-from-stories\"\n"
            "    - \"workflows\"\n"
            "    - \".ao-output\"\n"
            "  denied_operations:\n"
            "    - delete\n"
            "    - push\n"
            "    - publish\n"
        )
        with tempfile.TemporaryDirectory(prefix="sffs-round36-policy-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            paths["workflow"].write_text(policy_text, encoding="utf-8")
            expanded_rounds = helper.run_loop(
                "start",
                "--repo-root",
                paths["repo"],
                "--workflow",
                "workflows/separating-facts-loop.yaml",
                "--state-dir",
                ".ao-output/loop-run",
                "--source-file",
                "skills/separating-facts-from-stories/SKILL.md",
                "--allow-write",
                ".ao-output",
                "--max-rounds",
                3,
            )
            self.assertNotEqual(0, expanded_rounds.returncode)
            self.assertEqual(
                "WORKFLOW_POLICY_VIOLATION",
                self.parsed(expanded_rounds)["error"]["code"],
            )

            expanded_write = helper.run_loop(
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
                "workflows/separating-facts-release-sources.json",
                "--allow-write",
                ".",
                "--max-rounds",
                2,
            )
            self.assertNotEqual(0, expanded_write.returncode)
            self.assertEqual(
                "WORKFLOW_POLICY_VIOLATION",
                self.parsed(expanded_write)["error"]["code"],
            )


if __name__ == "__main__":
    unittest.main()
