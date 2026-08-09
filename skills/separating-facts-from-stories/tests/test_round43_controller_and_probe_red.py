from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[1]
PACKAGER_PATH = SKILL_DIR / "scripts" / "package_runtime.py"
LOOP_PATH = SKILL_DIR / "scripts" / "improvement_loop.py"
WORKFLOW_PATH = REPO_ROOT / "workflows" / "separating-facts-loop.yaml"
MANIFEST_PATH = REPO_ROOT / "workflows" / "separating-facts-release-sources.json"


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Round43ControllerAndProbeRedTests(unittest.TestCase):
    def test_controller_executable_is_a_required_frozen_policy_input(self) -> None:
        loop = load_module("round43_loop_policy", LOOP_PATH)
        policy = loop.parse_workflow_policy(WORKFLOW_PATH)
        expected = "skills/separating-facts-from-stories/scripts/improvement_loop.py"
        self.assertEqual(expected, policy["controller_executable"])
        _, sources = loop.parse_source_manifest(
            REPO_ROOT,
            policy["source_manifest"],
            workflow_relative=str(WORKFLOW_PATH.relative_to(REPO_ROOT)),
            controller_executable=policy["controller_executable"],
        )
        self.assertIn(expected, sources)

    def test_runtime_probe_is_isolated_and_has_a_named_timeout(self) -> None:
        packager = load_module("round43_probe_timeout", PACKAGER_PATH)
        with mock.patch.object(
            packager.subprocess,
            "run",
            side_effect=subprocess.TimeoutExpired(["python"], 1),
        ):
            with self.assertRaisesRegex(OSError, "RUNTIME_PROBE_TIMEOUT"):
                packager.run_runtime_probe(SKILL_DIR)

    def test_preflight_never_imports_candidate_runtime_in_the_installer_process(self) -> None:
        packager = load_module("round43_no_host_import", PACKAGER_PATH)
        with mock.patch.object(
            packager.importlib.util,
            "spec_from_file_location",
            side_effect=AssertionError("candidate runtime imported in host process"),
        ):
            _, identity = packager.preflight(SKILL_DIR)
        self.assertTrue(identity["identity_match"])

    def test_manifested_source_symlink_is_rejected(self) -> None:
        sys.path.insert(0, str(SKILL_DIR / "tests"))
        import test_round29_improvement_loop_red as round29

        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round43-symlink-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            probe = paths["red_test"]
            real = probe.with_name("real-probe.py")
            shutil.move(probe, real)
            probe.symlink_to(real.name)
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
            self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(
                "PATH_SYMLINK_ESCAPE", helper.parsed(result)["error"]["code"]
            )


if __name__ == "__main__":
    unittest.main()
