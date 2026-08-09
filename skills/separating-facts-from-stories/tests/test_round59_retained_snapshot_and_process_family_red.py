from __future__ import annotations

import argparse
import importlib.util
import io
import json
import os
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
PRODUCER_PATH = SKILL_DIR / "scripts" / "produce_release_gate.py"
LOOP_PATH = SKILL_DIR / "scripts" / "improvement_loop.py"

sys.path.insert(0, str(SKILL_DIR / "tests"))
import test_round29_improvement_loop_red as round29  # noqa: E402
from host_execution_fixture import write_host_review  # noqa: E402


def load_producer(name: str):
    spec = importlib.util.spec_from_file_location(name, PRODUCER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_review(root: Path, name: str, source_sha: str) -> Path:
    return write_host_review(root, name, source_sha, suffix=name)[0]


class Round59RetainedSnapshotAndProcessFamilyRedTests(unittest.TestCase):
    maxDiff = None

    def make_inputs(self, root: Path):
        producer = load_producer("round59_fixture")
        repo = root / "repo"
        source = repo / "skills" / "separating-facts-from-stories" / "scripts"
        source.mkdir(parents=True)
        (source / "package_runtime.py").write_text("print('source')\n", encoding="utf-8")
        (source / "casefile.py").write_text("print('case')\n", encoding="utf-8")
        (source / "run_evals.py").write_text("print('eval')\n", encoding="utf-8")
        source_files = sorted(
            path.relative_to(repo).as_posix() for path in source.glob("*.py")
        )
        manifest = repo / "workflows" / "separating-facts-release-sources.json"
        manifest.parent.mkdir(parents=True)
        source_files = sorted(
            [
                *source_files,
                manifest.relative_to(repo).as_posix(),
            ]
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
        eval_root = repo / "eval-root"
        (eval_root / "case-a").mkdir(parents=True)
        (eval_root / "case-a" / "artifact.json").write_text(
            '{"passed": true}\n', encoding="utf-8"
        )
        p0 = write_review(repo, "p0_zero", frozen["sha256"])
        p1 = write_review(repo, "reproducible_p1_zero", frozen["sha256"])
        return producer, repo, source_files, frozen, eval_root, (p0, p1)

    def test_retained_basis_is_content_addressed_independent_and_recipe_uses_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round59-basis-") as temp_dir:
            producer, repo, files, frozen, eval_root, reviews = self.make_inputs(
                Path(temp_dir)
            )
            basis = producer.materialize_release_basis(
                repo_root=repo,
                source_files=files,
                expected_source=frozen,
                eval_root=eval_root,
                review_paths=reviews,
                destination_parent=repo / ".ao-output" / "release-bases",
            )
            basis_root = Path(basis["root"])
            self.assertEqual(basis["sha256"], basis_root.name)
            self.assertTrue((basis_root / "snapshot-index.json").is_file())
            copied_source = basis_root / "source" / files[0]
            original_source = repo / files[0]
            self.assertNotEqual(original_source.stat().st_ino, copied_source.stat().st_ino)

            original_source.write_text("live drift after retention\n", encoding="utf-8")
            (eval_root / "case-a" / "artifact.json").write_text(
                '{"passed": false}\n', encoding="utf-8"
            )
            producer.validate_release_basis(basis)
            self.assertNotIn("live drift", copied_source.read_text(encoding="utf-8"))
            self.assertIn(
                '"passed": true',
                (Path(basis["eval_root"]) / "case-a" / "artifact.json").read_text(
                    encoding="utf-8"
                ),
            )
            recipe = producer.fixed_recipe(
                repo_root=Path(basis["source_root"]),
                eval_root=Path(basis["eval_root"]),
                target_root=repo / ".ao-output" / "target",
            )
            self.assertTrue(
                all(
                    str(item["script"]).startswith(str(Path(basis["source_root"])))
                    for item in recipe[:5]
                )
            )

    def test_retained_basis_tamper_and_second_publication_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round59-tamper-") as temp_dir:
            producer, repo, files, frozen, eval_root, reviews = self.make_inputs(
                Path(temp_dir)
            )
            parent = repo / ".ao-output" / "release-bases"
            basis = producer.materialize_release_basis(
                repo_root=repo,
                source_files=files,
                expected_source=frozen,
                eval_root=eval_root,
                review_paths=reviews,
                destination_parent=parent,
            )
            with self.assertRaisesRegex(RuntimeError, "RELEASE_BASIS_EXISTS"):
                producer.materialize_release_basis(
                    repo_root=repo,
                    source_files=files,
                    expected_source=frozen,
                    eval_root=eval_root,
                    review_paths=reviews,
                    destination_parent=parent,
                )
            victim = Path(basis["source_root"]) / files[0]
            victim.write_text("tampered\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "RELEASE_BASIS_TAMPERED"):
                producer.validate_release_basis(basis)

    def test_release_basis_source_identity_cannot_be_relabelled(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round59-relabel-") as temp_dir:
            producer, repo, files, frozen, eval_root, reviews = self.make_inputs(
                Path(temp_dir)
            )
            basis = producer.materialize_release_basis(
                repo_root=repo,
                source_files=files,
                expected_source=frozen,
                eval_root=eval_root,
                review_paths=reviews,
                destination_parent=repo / ".ao-output" / "release-bases",
            )
            relabelled = dict(basis)
            relabelled["source_sha256"] = "f" * 64
            with self.assertRaisesRegex(RuntimeError, "RELEASE_BASIS_TAMPERED"):
                producer.validate_release_basis(relabelled)

    def test_canonical_install_artifact_is_copied_from_snapshot_built_install(self) -> None:
        producer = load_producer("round59_install_artifact")
        with tempfile.TemporaryDirectory(prefix="sffs-round59-install-") as temp_dir:
            root = Path(temp_dir)
            installed = root / "clean-target" / "separating-facts-from-stories"
            (installed / "scripts").mkdir(parents=True)
            (installed / "scripts" / "runtime.py").write_text(
                "snapshot build\n", encoding="utf-8"
            )
            artifact = producer.materialize_canonical_install_artifact(
                installed=installed,
                destination_parent=root / "canonical-installs",
                source_basis_sha256="b" * 64,
            )
            self.assertEqual(artifact["sha256"], Path(artifact["root"]).name)
            self.assertEqual("b" * 64, artifact["source_basis_sha256"])
            self.assertNotEqual(
                (installed / "scripts" / "runtime.py").stat().st_ino,
                (Path(artifact["root"]) / "scripts" / "runtime.py").stat().st_ino,
            )
            (installed / "scripts" / "runtime.py").write_text(
                "later mutation\n", encoding="utf-8"
            )
            producer.validate_canonical_install_artifact(artifact)
            self.assertEqual(
                "snapshot build\n",
                (Path(artifact["root"]) / "scripts" / "runtime.py").read_text(
                    encoding="utf-8"
                ),
            )

    def test_snapshot_rejects_symlink_and_hardlink_inputs(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round59-links-") as temp_dir:
            producer, repo, files, frozen, eval_root, reviews = self.make_inputs(
                Path(temp_dir)
            )
            outside = repo / "outside.txt"
            outside.write_text("outside\n", encoding="utf-8")
            link = eval_root / "linked.txt"
            link.symlink_to(outside)
            with self.assertRaisesRegex(RuntimeError, "SNAPSHOT_INPUT_LINK"):
                producer.materialize_release_basis(
                    repo_root=repo,
                    source_files=files,
                    expected_source=frozen,
                    eval_root=eval_root,
                    review_paths=reviews,
                    destination_parent=repo / ".ao-output" / "links-a",
                )
            link.unlink()
            hardlink = eval_root / "hardlinked.txt"
            os.link(outside, hardlink)
            with self.assertRaisesRegex(RuntimeError, "SNAPSHOT_INPUT_LINK"):
                producer.materialize_release_basis(
                    repo_root=repo,
                    source_files=files,
                    expected_source=frozen,
                    eval_root=eval_root,
                    review_paths=reviews,
                    destination_parent=repo / ".ao-output" / "links-b",
                )

    def test_source_change_between_initial_check_and_copy_fails_retention(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round59-copy-race-") as temp_dir:
            producer, repo, files, frozen, eval_root, reviews = self.make_inputs(
                Path(temp_dir)
            )
            target = (repo / files[0]).resolve()
            original_copy = producer._copy_regular_snapshot_file
            changed = False

            def change_then_copy(source: Path, destination: Path):
                nonlocal changed
                if source.resolve() == target and not changed:
                    changed = True
                    source.write_text("changed in retention window\n", encoding="utf-8")
                return original_copy(source, destination)

            with mock.patch.object(
                producer, "_copy_regular_snapshot_file", side_effect=change_then_copy
            ):
                with self.assertRaisesRegex(
                    RuntimeError, "SOURCE_DRIFT_DURING_RETENTION"
                ):
                    producer.materialize_release_basis(
                        repo_root=repo,
                        source_files=files,
                        expected_source=frozen,
                        eval_root=eval_root,
                        review_paths=reviews,
                        destination_parent=repo / ".ao-output" / "copy-race",
                    )

    def _timeout_script(self, root: Path, *, ignore_term: bool = False) -> tuple[Path, Path]:
        marker = root / "escaped-marker.txt"
        child_code = (
            "import os,pathlib,signal,sys,time; os.setsid(); "
            + ("signal.signal(signal.SIGTERM,signal.SIG_IGN); " if ignore_term else "")
            + "time.sleep(0.5); pathlib.Path(sys.argv[1]).write_text('escaped')"
        )
        script = root / "spawn.py"
        script.write_text(
            "import subprocess,sys,time\n"
            f"subprocess.Popen([sys.executable,'-c',{child_code!r},sys.argv[1]],"
            "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=False)\n"
            "time.sleep(5)\n",
            encoding="utf-8",
        )
        return script, marker

    def test_timeout_cleans_escaped_session_and_sigterm_ignoring_family(self) -> None:
        producer = load_producer("round59_family_cleanup")
        for ignore_term in (False, True):
            with self.subTest(ignore_term=ignore_term), tempfile.TemporaryDirectory(
                prefix="sffs-round59-family-"
            ) as temp_dir:
                root = Path(temp_dir)
                script, marker = self._timeout_script(root, ignore_term=ignore_term)
                with self.assertRaisesRegex(RuntimeError, "RECIPE_TIMEOUT"):
                    producer.run_isolated_command(
                        step_id="family-timeout",
                        script=script,
                        arguments=[str(marker)],
                        cwd=root,
                        timeout_seconds=0.1,
                        receipt_path=root / "receipt.json",
                    )
                time.sleep(0.8)
                self.assertFalse(marker.exists())
                receipt = json.loads((root / "receipt.json").read_text(encoding="utf-8"))
                self.assertEqual(
                    "cooperative_inherited_token_not_os_sandbox",
                    receipt["process_family_policy"]["trust_boundary"],
                )
                self.assertTrue(receipt["process_family_policy"]["confirmed_empty"])

    def test_enumeration_failure_fails_closed(self) -> None:
        producer = load_producer("round59_enum_failure")
        with tempfile.TemporaryDirectory(prefix="sffs-round59-enum-") as temp_dir:
            root = Path(temp_dir)
            script = root / "ok.py"
            script.write_text("print('ok')\n", encoding="utf-8")
            with mock.patch.object(
                producer, "enumerate_process_family", side_effect=RuntimeError("ps failed")
            ):
                with self.assertRaisesRegex(RuntimeError, "PROCESS_FAMILY_CLEANUP_INCOMPLETE"):
                    producer.run_isolated_command(
                        step_id="enum-failure",
                        script=script,
                        arguments=[],
                        cwd=root,
                        timeout_seconds=5,
                        receipt_path=root / "receipt.json",
                    )

    def test_normal_parent_exit_still_cleans_marked_escaped_child(self) -> None:
        producer = load_producer("round59_normal_exit_cleanup")
        with tempfile.TemporaryDirectory(prefix="sffs-round59-normal-exit-") as temp_dir:
            root = Path(temp_dir)
            marker = root / "normal-exit-marker.txt"
            child_code = (
                "import os,pathlib,sys,time; os.setsid(); time.sleep(0.5); "
                "pathlib.Path(sys.argv[1]).write_text('escaped')"
            )
            script = root / "spawn-and-exit.py"
            script.write_text(
                "import subprocess,sys\n"
                f"subprocess.Popen([sys.executable,'-c',{child_code!r},sys.argv[1]],"
                "stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)\n",
                encoding="utf-8",
            )
            receipt = producer.run_isolated_command(
                step_id="normal-exit-cleanup",
                script=script,
                arguments=[str(marker)],
                cwd=root,
                timeout_seconds=5,
                receipt_path=root / "receipt.json",
            )
            time.sleep(0.8)
            self.assertFalse(marker.exists())
            self.assertTrue(receipt["process_family_policy"]["confirmed_empty"])

    def test_same_uid_process_without_token_is_not_killed(self) -> None:
        producer = load_producer("round59_no_false_kill")
        survivor = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
        try:
            with tempfile.TemporaryDirectory(prefix="sffs-round59-unmarked-") as temp_dir:
                root = Path(temp_dir)
                script, _ = self._timeout_script(root)
                with self.assertRaisesRegex(RuntimeError, "RECIPE_TIMEOUT"):
                    producer.run_isolated_command(
                        step_id="unmarked-survivor",
                        script=script,
                        arguments=[str(root / "marker")],
                        cwd=root,
                        timeout_seconds=0.1,
                        receipt_path=root / "receipt.json",
                    )
                self.assertIsNone(survivor.poll())
        finally:
            if survivor.poll() is None:
                survivor.send_signal(signal.SIGTERM)
                survivor.wait(timeout=2)

    def test_after_prepare_resume_keeps_stop_bound_to_basis_despite_live_divergence(self) -> None:
        producer = load_producer("round59_resume_producer")
        loop = load_producer.__globals__["importlib"].util.spec_from_file_location(
            "round59_resume_loop", LOOP_PATH
        )
        assert loop is not None and loop.loader is not None
        controller = importlib.util.module_from_spec(loop)
        loop.loader.exec_module(controller)
        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round59-resume-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            before = helper.start(paths)
            eval_root = paths["repo"] / "eval-root"
            eval_root.mkdir()
            p0 = write_review(paths["repo"], "p0_zero", before["source_snapshot"]["sha256"])
            p1 = write_review(
                paths["repo"],
                "reproducible_p1_zero",
                before["source_snapshot"]["sha256"],
            )
            basis = producer.materialize_release_basis(
                repo_root=paths["repo"],
                source_files=before["source_files"],
                expected_source=before["source_snapshot"],
                eval_root=eval_root,
                review_paths=(p0, p1),
                destination_parent=paths["repo"] / ".ao-output" / "resume-bases",
            )
            installed = paths["repo"] / ".ao-output" / "fixture-install"
            installed.mkdir()
            (installed / "runtime-manifest.json").write_text("{}\n", encoding="utf-8")
            install = producer.materialize_canonical_install_artifact(
                installed=installed,
                destination_parent=paths["repo"] / ".ao-output" / "resume-installs",
                source_basis_sha256=basis["sha256"],
            )

            def relative(value: str) -> str:
                return Path(value).resolve().relative_to(paths["repo"].resolve()).as_posix()

            reference = {
                "schema_version": "1.1.0",
                "sha256": basis["sha256"],
                "root_path": relative(basis["root"]),
                "index_path": relative(basis["index_path"]),
                "index_sha256": basis["index_sha256"],
                "source_sha256": basis["source_sha256"],
                "canonical_install": {
                    "sha256": install["sha256"],
                    "root_path": relative(install["root"]),
                    "index_path": relative(install["index_path"]),
                    "index_sha256": install["index_sha256"],
                    "built_from": "retained_source_snapshot",
                    "source_basis_sha256": basis["sha256"],
                },
                "trust_boundary": "retained_local_snapshot_not_external_signature",
            }
            after = json.loads(json.dumps(before))
            result = {
                "path": ".ao-output/fixture-gate.json",
                "sha256": "a" * 64,
                "checks": {key: True for key in controller.REQUIRED_GATE_CHECKS},
                "evidence": {},
                "evidence_verified": True,
                "valid": True,
                "all_true": True,
                "code": "GATE_VALID",
                "release_basis": reference,
            }
            after["iterations"][-1].update(
                {
                    "finding": None,
                    "red_test": None,
                    "gate_result": result,
                    "decision": "STOP",
                }
            )
            after["status"] = "completed"
            after["decision"] = "STOP"
            after["release_basis"] = reference
            after["observed_source_snapshot"] = before["source_snapshot"]

            with mock.patch.object(
                controller, "validate_persisted_gate_evidence", return_value=None
            ), mock.patch.dict(
                os.environ, {"SFFS_IMPROVEMENT_LOOP_FAILPOINT": "after_prepare"}
            ):
                with self.assertRaises(controller.LoopError) as raised:
                    controller.commit_transition(paths["state_dir"], before, after)
            self.assertEqual("SIMULATED_CRASH", raised.exception.code)
            paths["skill_file"].write_text("live divergence\n", encoding="utf-8")

            with mock.patch.object(
                controller, "validate_persisted_gate_evidence", return_value=None
            ), redirect_stdout(io.StringIO()):
                controller.command_resume(
                    argparse.Namespace(state_dir=str(paths["state_dir"]))
                )
            persisted = json.loads(
                (paths["state_dir"] / "loop-state.json").read_text(encoding="utf-8")
            )
            self.assertEqual("completed", persisted["status"])
            self.assertEqual("STOP", persisted["decision"])
            self.assertEqual(reference, persisted["release_basis"])


if __name__ == "__main__":
    unittest.main()
