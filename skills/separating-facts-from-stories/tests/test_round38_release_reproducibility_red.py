from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[1]
PACKAGER_PATH = SKILL_DIR / "scripts" / "package_runtime.py"
WORKFLOW_PATH = REPO_ROOT / "workflows" / "separating-facts-loop.yaml"
sys.path.insert(0, str(SKILL_DIR / "tests"))

import test_round29_improvement_loop_red as round29  # noqa: E402
import test_round4_release_gate_red as round4_release  # noqa: E402


def load_packager(name: str):
    spec = importlib.util.spec_from_file_location(name, PACKAGER_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def add_source_manifest(paths: dict[str, Path]) -> Path:
    relative = "workflows/separating-facts-release-sources.json"
    manifest = paths["repo"] / relative
    manifest.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "source_files": sorted(
                    [
                        "skills/separating-facts-from-stories/SKILL.md",
                        "skills/separating-facts-from-stories/scripts/improvement_loop.py",
                        "skills/separating-facts-from-stories/tests/test_probe.py",
                        "workflows/separating-facts-loop.yaml",
                        relative,
                    ]
                ),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    workflow = paths["workflow"].read_text(encoding="utf-8")
    if "  source_manifest:" not in workflow:
        workflow = workflow.replace(
            '  schema_version: "1.1.0"\n',
            '  schema_version: "1.1.0"\n'
            f'  source_manifest: "{relative}"\n',
            1,
        )
    paths["workflow"].write_text(workflow, encoding="utf-8")
    return manifest


class Round38ReleaseReproducibilityRedTests(unittest.TestCase):
    def test_generic_boolean_dossier_cannot_prove_rollback(self) -> None:
        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round38-rollback-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            started = helper.start(paths)
            gate_path, gate = helper.write_gate(paths, started)
            generic_path = paths["state_dir"] / "generic-rollback.json"
            generic = {
                "schema_version": "1.1.0",
                "iteration_id": gate["iteration_id"],
                "source_sha256": gate["source_sha256"],
                "gate_check": "rollback",
                "passed": True,
                "commands": [],
                "artifacts": [
                    {
                        "role": "rollback_receipt",
                        "path": str(paths["red_test"].relative_to(paths["repo"])),
                        "sha256": hashlib.sha256(paths["red_test"].read_bytes()).hexdigest(),
                    }
                ],
            }
            generic_path.write_text(
                json.dumps(generic, indent=2) + "\n", encoding="utf-8"
            )
            gate["evidence"]["rollback"] = {
                "path": str(generic_path.relative_to(paths["repo"])),
                "sha256": hashlib.sha256(generic_path.read_bytes()).hexdigest(),
                "json_pointer": "/passed",
                "expected": True,
            }
            gate_path.write_text(
                json.dumps(gate, indent=2) + "\n", encoding="utf-8"
            )

            result = helper.advance(paths, gate_path)
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            payload = helper.parsed(result)
            self.assertEqual("ROLLBACK_EVIDENCE_INVALID", payload["error"]["code"])

    def test_workflow_source_manifest_prevents_cli_omission(self) -> None:
        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round38-source-set-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            add_source_manifest(paths)
            result = helper.run_loop(
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
                "workflows/separating-facts-loop.yaml",
                "--allow-write",
                ".ao-output",
                "--max-rounds",
                2,
            )
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            payload = helper.parsed(result)
            self.assertEqual("SOURCE_MANIFEST_MISMATCH", payload["error"]["code"])

    def test_manifest_is_the_authoritative_source_set_when_cli_omits_list(self) -> None:
        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round38-manifest-source-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            manifest_path = add_source_manifest(paths)
            declared = json.loads(manifest_path.read_text(encoding="utf-8"))[
                "source_files"
            ]
            result = helper.run_loop(
                "start",
                "--repo-root",
                paths["repo"],
                "--workflow",
                "workflows/separating-facts-loop.yaml",
                "--state-dir",
                ".ao-output/loop-run",
                "--allow-write",
                ".ao-output",
                "--max-rounds",
                2,
            )
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            state = helper.parsed(result)
            self.assertEqual(declared, state["source_files"])
            self.assertEqual(
                "workflows/separating-facts-release-sources.json",
                state["source_manifest"]["path"],
            )

    def test_verify_rejects_non_object_evaluation_context_even_if_rehashed(self) -> None:
        packager = load_packager("round38_nonobject_context")
        helper = round4_release.Round4ReleaseGateRedTests()
        helper.packager = packager
        helper.runner = round4_release.load_module(
            "round38_nonobject_runner", SKILL_DIR / "scripts" / "run_evals.py"
        )
        with tempfile.TemporaryDirectory(prefix="sffs-round38-context-") as temp_dir:
            installed = helper._make_installed_tree(Path(temp_dir))
            context_path = installed / "evidence" / "evaluation-context.json"
            report_path = installed / "evidence" / "machine-report.json"
            manifest_path = installed / "runtime-manifest.json"

            context_path.write_text("[]\n", encoding="utf-8")
            context_sha = hashlib.sha256(context_path.read_bytes()).hexdigest()
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["evaluation_context_sha256"] = context_sha
            report_path.write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            report_sha = hashlib.sha256(report_path.read_bytes()).hexdigest()

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["files"]["evidence/evaluation-context.json"] = context_sha
            manifest["files"]["evidence/machine-report.json"] = report_sha
            manifest["release_evidence"]["evaluation_context"]["sha256"] = context_sha
            manifest["release_evidence"]["machine_report"]["sha256"] = report_sha
            manifest["release_gate"]["eval"]["evaluation_context_sha256"] = context_sha
            manifest_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            result = packager.verify_install(installed)
            self.assertFalse(result["valid"])
            self.assertIn(
                "EVALUATION_CONTEXT_INVALID",
                {item["code"] for item in result["errors"]},
            )

    def test_non_utf8_manifest_returns_structured_invalid_result(self) -> None:
        packager = load_packager("round38_non_utf8_manifest")
        with tempfile.TemporaryDirectory(prefix="sffs-round38-manifest-bytes-") as temp_dir:
            installed = Path(temp_dir) / "separating-facts-from-stories"
            installed.mkdir()
            (installed / "runtime-manifest.json").write_bytes(b"\xff\xfe")
            result = packager.verify_install(installed)
            self.assertFalse(result["valid"])
            self.assertEqual("MANIFEST_INVALID", result["errors"][0]["code"])

    def test_unit_gate_timeout_is_a_named_release_failure(self) -> None:
        packager = load_packager("round38_unit_timeout")
        with tempfile.TemporaryDirectory(prefix="sffs-round38-timeout-") as temp_dir:
            source = Path(temp_dir) / "source"
            tests = source / "tests"
            tests.mkdir(parents=True)
            (tests / "test_probe.py").write_text(
                "import unittest\n"
                "class Probe(unittest.TestCase):\n"
                "    def test_probe(self): self.assertTrue(True)\n",
                encoding="utf-8",
            )
            with mock.patch.object(
                packager, "REQUIRED_TEST_FILES", {"test_probe.py"}
            ), mock.patch.object(
                packager,
                "RELEASE_EVIDENCE_FILES",
                {"test_probe": "tests/test_probe.py"},
            ), mock.patch.object(
                packager.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(["python"], 1),
            ):
                with self.assertRaisesRegex(
                    OSError, "UNIT_TEST_GATE_FAILED.*timed out"
                ):
                    packager.run_unit_test_gate(source)

    def test_workflow_is_portable_and_executes_rollback_before_stop_gate(self) -> None:
        text = WORKFLOW_PATH.read_text(encoding="utf-8")
        self.assertNotIn("/Users/", text)
        self.assertNotIn("agents_dir:", text)
        self.assertIn("  - id: rollback_validation\n", text)
        evidence_gate = text.split("  - id: evidence_gate\n", 1)[1].split(
            "  - id: loop_decision\n", 1
        )[0]
        self.assertIn("depends_on: [rollback_validation]", evidence_gate)


if __name__ == "__main__":
    unittest.main()
