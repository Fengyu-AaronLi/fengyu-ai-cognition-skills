from __future__ import annotations

import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[1]
PRODUCER_PATH = SKILL_DIR / "scripts" / "produce_release_gate.py"

sys.path.insert(0, str(SKILL_DIR / "tests"))
import test_round29_improvement_loop_red as round29  # noqa: E402
from host_execution_fixture import prepare_review_source, write_host_review  # noqa: E402


def load_producer(name: str):
    spec = importlib.util.spec_from_file_location(name, PRODUCER_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("release gate producer is not importable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Round49ExecutableGateProducerRedTests(unittest.TestCase):
    maxDiff = None

    def test_external_all_true_gate_cannot_stop_controller_owned_workflow(self) -> None:
        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round49-external-stop-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            workflow = paths["workflow"]
            text = workflow.read_text(encoding="utf-8")
            text = text.replace(
                '  source_manifest: "workflows/separating-facts-release-sources.json"\n',
                '  source_manifest: "workflows/separating-facts-release-sources.json"\n'
                '  stop_authority: "controller_prove_stop"\n'
                '  gate_producer: "skills/separating-facts-from-stories/scripts/produce_release_gate.py"\n',
            )
            workflow.write_text(text, encoding="utf-8")
            started = helper.start(paths)
            gate_path, _ = helper.write_gate(paths, started)

            result = helper.advance(paths, gate_path)

            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(
                "EXTERNAL_STOP_FORBIDDEN", helper.parsed(result)["error"]["code"]
            )
            state = json.loads(
                (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual("active", state["status"])
            self.assertIsNone(state["decision"])

    def test_command_runner_is_fixed_isolated_timed_and_never_uses_a_shell(self) -> None:
        producer = load_producer("round49_command_runner")
        fake_process = mock.Mock(pid=4242, returncode=0)
        fake_process.communicate.return_value = ("ok", "")
        ps_process = mock.Mock(returncode=0)
        ps_process.communicate.return_value = ("", "")

        def popen_side_effect(argv, *args, **kwargs):
            if argv == ["/bin/ps", "-axo", "pid=,uid="]:
                return ps_process
            return fake_process

        with tempfile.TemporaryDirectory(prefix="sffs-round49-command-") as temp_dir:
            root = Path(temp_dir)
            receipt = root / "raw" / "unit.json"
            with mock.patch.object(
                producer.subprocess, "Popen", side_effect=popen_side_effect
            ) as popen:
                result = producer.run_isolated_command(
                    step_id="unit_tests",
                    script=Path("/candidate/scripts/package_runtime.py"),
                    arguments=["--unit-gate"],
                    cwd=root,
                    timeout_seconds=41,
                    receipt_path=receipt,
                )

            command_call = popen.call_args_list[0]
            argv = command_call.args[0]
            self.assertEqual([sys.executable, "-I", "-S", "-B"], argv[:4])
            self.assertNotIn("-m", argv[:4])
            self.assertIs(command_call.kwargs["shell"], False)
            self.assertIs(command_call.kwargs["start_new_session"], True)
            self.assertEqual(
                41, fake_process.communicate.call_args_list[0].kwargs["timeout"]
            )
            self.assertEqual(root, command_call.kwargs["cwd"])
            env = command_call.kwargs["env"]
            self.assertNotIn("PYTHONPATH", env)
            self.assertNotIn("PYTHONHOME", env)
            self.assertEqual("1", env["PYTHONNOUSERSITE"])
            self.assertEqual("1", env["PYTHONDONTWRITEBYTECODE"])
            self.assertEqual(0, result["exit_code"])
            saved = json.loads(receipt.read_text(encoding="utf-8"))
            self.assertEqual(argv, saved["argv"])
            self.assertEqual(str(root), saved["cwd"])
            self.assertEqual(41, saved["timeout_seconds"])
            self.assertEqual("ok", saved["stdout"])

    def test_recipe_contains_two_independent_eval_replays_and_one_install_chain(self) -> None:
        producer = load_producer("round49_recipe")
        recipe = producer.fixed_recipe(
            repo_root=REPO_ROOT,
            eval_root=Path("/tmp/frozen-eval"),
            target_root=Path("/tmp/clean-target"),
        )
        step_ids = [item["step_id"] for item in recipe]
        self.assertEqual(2, step_ids.count("eval_replay"))
        eval_receipts = [item["receipt_name"] for item in recipe if item["step_id"] == "eval_replay"]
        self.assertEqual(2, len(set(eval_receipts)))
        self.assertIn("clean_install", step_ids)
        self.assertIn("verify_install", step_ids)
        self.assertIn("rollback_restore", step_ids)

    def test_reviewer_attestation_is_source_bound_and_not_a_self_reported_pass(self) -> None:
        producer = load_producer("round49_review")
        with tempfile.TemporaryDirectory(prefix="sffs-round49-review-") as temp_dir:
            root = Path(temp_dir)
            source_sha = prepare_review_source(root)
            _, report = write_host_review(
                root, "p0_zero", source_sha, suffix="source-binding"
            )
            report["passed"] = True
            with self.assertRaisesRegex(ValueError, "self-reported pass"):
                producer.derive_review_open_count(
                    report, expected_type="p0_zero", source_sha256=source_sha,
                    repo_root=root,
                )
            report.pop("passed")
            self.assertEqual(
                0,
                producer.derive_review_open_count(
                    report, expected_type="p0_zero", source_sha256=source_sha,
                    repo_root=root,
                ),
            )
            report["source_sha256"] = "b" * 64
            with self.assertRaisesRegex(ValueError, "source"):
                producer.derive_review_open_count(
                    report, expected_type="p0_zero", source_sha256=source_sha,
                    repo_root=root,
                )

    def test_source_drift_guard_fails_before_gate_publication(self) -> None:
        producer = load_producer("round49_source_guard")
        with tempfile.TemporaryDirectory(prefix="sffs-round49-drift-") as temp_dir:
            root = Path(temp_dir)
            source = root / "source.py"
            source.write_text("before\n", encoding="utf-8")
            frozen = producer.snapshot_files(root, ["source.py"])
            source.write_text("after\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "SOURCE_DRIFT_DURING_PROOF"):
                producer.require_snapshot(root, ["source.py"], frozen)

    def test_minimal_fixed_recipe_executes_all_nine_gates_and_retains_raw_receipts(self) -> None:
        producer = load_producer("round49_executable_fixture")
        with tempfile.TemporaryDirectory(prefix="sffs-round49-executable-") as temp_dir:
            repo = Path(temp_dir) / "candidate"
            scripts = repo / "skills" / "separating-facts-from-stories" / "scripts"
            scripts.mkdir(parents=True)
            copied_producer = scripts / "produce_release_gate.py"
            shutil.copy2(PRODUCER_PATH, copied_producer)
            shutil.copy2(
                SKILL_DIR / "scripts" / "codex_exec_host.py",
                scripts / "codex_exec_host.py",
            )
            (scripts / "casefile.py").write_text(
                "import json,sys\n"
                "assert sys.argv[1:] == ['self-test']\n"
                "print(json.dumps({'valid':True,'checks':{'a':True,'b':True}}))\n",
                encoding="utf-8",
            )
            (scripts / "run_evals.py").write_text(
                "import json,sys\n"
                "assert sys.argv[1] == '--root'\n"
                "print(json.dumps({'valid':True,'expected_case_count':18,"
                "'completed_case_count':18,'expected_artifact_count':16,"
                "'artifact_count':16,'passed':16,'failed':0,"
                "'suite_errors':[],'missing_cases':[]}))\n",
                encoding="utf-8",
            )
            (scripts / "package_runtime.py").write_text(
                "import json,shutil,sys\n"
                "from pathlib import Path\n"
                "a=sys.argv[1:]\n"
                "if a == ['--unit-gate']:\n"
                " print(json.dumps({'tests_run':7,'test_source_set_sha256':'1'*64}))\n"
                "elif a and a[0] == '--target-root':\n"
                " root=Path(a[1]); dest=root/'separating-facts-from-stories'; "
                "(dest/'scripts').mkdir(parents=True); "
                "shutil.copy2(__file__,dest/'scripts'/'package_runtime.py'); "
                "(dest/'runtime-manifest.json').write_text('{}\\n',encoding='utf-8'); "
                "print(json.dumps({'installed':str(dest.resolve())}))\n"
                "elif a and a[0] == '--verify':\n"
                " print(json.dumps({'valid':True,'error_count':0,'errors':[]}))\n"
                "else:\n"
                " raise SystemExit(2)\n",
                encoding="utf-8",
            )
            source_files = sorted(
                str(path.relative_to(repo)) for path in scripts.glob("*.py")
            )
            manifest = repo / "workflows" / "separating-facts-release-sources.json"
            manifest.parent.mkdir(parents=True)
            source_files = sorted(
                [*source_files, manifest.relative_to(repo).as_posix()]
            )
            manifest.write_text(
                json.dumps(
                    {"schema_version": "1.0.0", "source_files": source_files},
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            frozen = producer.snapshot_files(repo, source_files)
            state_dir = repo / ".ao-output" / "run"
            state_dir.mkdir(parents=True)
            state = {
                "repo_root": str(repo.resolve()),
                "status": "active",
                "source_files": source_files,
                "source_snapshot": frozen,
                "iterations": [
                    {
                        "iteration_id": f"r001-{frozen['sha256'][:12]}",
                        "source_sha256": frozen["sha256"],
                        "active_source_sha256": frozen["sha256"],
                    }
                ],
            }
            state_file = state_dir / "loop-state.json"
            state_file.write_text(json.dumps(state) + "\n", encoding="utf-8")
            reviews = [
                write_host_review(
                    repo,
                    gate_type,
                    frozen["sha256"],
                    suffix=f"release-{index}",
                )[0]
                for index, gate_type in enumerate(
                    ("p0_zero", "reproducible_p1_zero"), start=1
                )
            ]
            eval_root = repo / "eval-root"
            eval_root.mkdir()
            output = state_dir / "proof"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    str(copied_producer),
                    "--repo-root",
                    str(repo),
                    "--state-file",
                    str(state_file),
                    "--eval-root",
                    str(eval_root),
                    "--p0-review",
                    str(reviews[0]),
                    "--p1-review",
                    str(reviews[1]),
                    "--output-dir",
                    str(output),
                ],
                cwd=repo,
                text=True,
                capture_output=True,
                check=False,
                timeout=30,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            result = json.loads(completed.stdout)
            gate = json.loads(Path(result["gate"]).read_text(encoding="utf-8"))
            self.assertEqual(
                set(round29.REQUIRED_GATE_CHECKS), set(gate["checks"])
            )
            self.assertTrue(all(gate["checks"].values()))
            self.assertEqual(
                "controller_prove_stop", gate["producer"]["authority"]
            )
            loop_spec = importlib.util.spec_from_file_location(
                "round49_gate_validator", SKILL_DIR / "scripts" / "improvement_loop.py"
            )
            assert loop_spec is not None and loop_spec.loader is not None
            loop = importlib.util.module_from_spec(loop_spec)
            loop_spec.loader.exec_module(loop)
            loop.validate_gate_shape(gate)
            loop.validate_gate_evidence(
                repo.resolve(),
                gate,
                iteration_id_value=state["iterations"][0]["iteration_id"],
                source_sha256=frozen["sha256"],
            )
            raw_index = json.loads(
                (output / "raw-receipt-index.json").read_text(encoding="utf-8")
            )
            self.assertGreaterEqual(len(raw_index["receipts"]), 10)
            self.assertTrue((output / "raw" / "03-eval-replay-cases.json").is_file())
            self.assertTrue((output / "raw" / "04-eval-replay-artifacts.json").is_file())


if __name__ == "__main__":
    unittest.main()
