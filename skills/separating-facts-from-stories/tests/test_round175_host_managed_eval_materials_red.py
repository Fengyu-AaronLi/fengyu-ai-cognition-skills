#!/usr/bin/env python3
"""Round 175 RED: the host, not the model, fixes eval inputs and workspaces."""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
RUNNER_PATH = SKILL_DIR / "scripts" / "host_eval_runner.py"
HOST_PATH = SKILL_DIR / "scripts" / "codex_exec_host.py"
AUDITOR_PATH = SKILL_DIR / "scripts" / "run_evals.py"


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Round175HostManagedEvalMaterialsRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load(RUNNER_PATH, "round175_host_eval_runner")
        cls.host = load(HOST_PATH, "round175_codex_exec_host")
        cls.auditor = load(AUDITOR_PATH, "round175_eval_auditor")

    def test_host_extracts_exact_raw_input_and_leaves_one_workspace_uncreated(self) -> None:
        case_id = "immediate-safety-override"
        with tempfile.TemporaryDirectory(prefix="sffs-round175-single-") as temp_dir:
            root = Path(temp_dir) / "eval"
            self.auditor.prepare_root(root)
            case_dir = root / case_id
            envelope = json.loads((case_dir / "input.json").read_text(encoding="utf-8"))

            layout = self.runner.prepare_runtime_materials(
                eval_root=root,
                case_dir=case_dir,
                case_id=case_id,
            )

            self.assertEqual([".runtime/input-1.txt"], layout["input_paths"])
            self.assertEqual([".runtime/workspace-1"], layout["workspace_paths"])
            input_path = case_dir / layout["input_paths"][0]
            self.assertEqual(envelope["input"], input_path.read_text(encoding="utf-8"))
            self.assertEqual(0, stat.S_IMODE(input_path.stat().st_mode) & 0o222)
            self.assertFalse((case_dir / layout["workspace_paths"][0]).exists())

    def test_versioned_case_gets_two_exact_inputs_and_two_fixed_workspaces(self) -> None:
        case_id = "versioned-evidence-update"
        with tempfile.TemporaryDirectory(prefix="sffs-round175-versioned-") as temp_dir:
            root = Path(temp_dir) / "eval"
            self.auditor.prepare_root(root)
            case_dir = root / case_id
            envelope = json.loads((case_dir / "input.json").read_text(encoding="utf-8"))

            layout = self.runner.prepare_runtime_materials(
                eval_root=root,
                case_dir=case_dir,
                case_id=case_id,
            )

            self.assertEqual(
                [".runtime/input-1.txt", ".runtime/input-2.txt"],
                layout["input_paths"],
            )
            self.assertEqual(
                [".runtime/workspace-1", ".runtime/workspace-2"],
                layout["workspace_paths"],
            )
            self.assertEqual(
                envelope["turns"],
                [
                    (case_dir / relative).read_text(encoding="utf-8")
                    for relative in layout["input_paths"]
                ],
            )
            self.assertTrue(
                all(not (case_dir / relative).exists() for relative in layout["workspace_paths"])
            )

    def test_prompt_binds_runtime_paths_and_forbids_model_promotion(self) -> None:
        case_id = "relationship-silence"
        with tempfile.TemporaryDirectory(prefix="sffs-round175-prompt-") as temp_dir:
            root = Path(temp_dir) / "eval"
            self.auditor.prepare_root(root)
            case_dir = root / case_id
            self.runner.prepare_runtime_materials(
                eval_root=root,
                case_dir=case_dir,
                case_id=case_id,
            )

            prompt = self.host.build_eval_prompt(
                eval_root=root,
                case_dir=case_dir,
                case_id=case_id,
            )
            resolved_case_dir = case_dir.resolve()

            self.assertIn(f"RUNTIME_INPUT_1: {resolved_case_dir / '.runtime/input-1.txt'}", prompt)
            self.assertIn(f"RUNTIME_WORKSPACE_1: {resolved_case_dir / '.runtime/workspace-1'}", prompt)
            self.assertNotIn(f"INPUT_FILE: {case_dir / 'input.json'}", prompt)
            self.assertIn("Do not create an alternate workspace", prompt)
            self.assertIn("The host promotes canonical artifacts", prompt)

    def test_safety_final_message_is_the_exact_runtime_safety_response(self) -> None:
        contract = self.host._eval_final_response_contract(
            "immediate-safety-override"
        )
        self.assertIn("safety-response.md", contract)
        self.assertIn("exact bytes", contract)
        self.assertNotIn("runtime-rendered final response", contract)


if __name__ == "__main__":
    unittest.main()
