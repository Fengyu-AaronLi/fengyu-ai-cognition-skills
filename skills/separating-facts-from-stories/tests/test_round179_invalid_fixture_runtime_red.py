#!/usr/bin/env python3
"""Round 179 RED: invalid-fixture eval is frozen, staged, promoted, and replayed."""

from __future__ import annotations

import importlib.util
import json
import stat
import subprocess
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


class Round179InvalidFixtureRuntimeRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load(RUNNER_PATH, "round179_host_eval_runner")
        cls.host = load(HOST_PATH, "round179_codex_exec_host")
        cls.auditor = load(AUDITOR_PATH, "round179_eval_auditor")

    def fake_codex(self, root: Path, message: str) -> Path:
        executable = root / "codex"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json,pathlib,sys\n"
            "if '--version' in sys.argv:\n"
            " print('codex-cli round179 fixture')\n"
            " raise SystemExit(0)\n"
            f"message={message!r}\n"
            "target=pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
            "target.write_text(message,encoding='utf-8')\n"
            "for event in [\n"
            " {'type':'thread.started','thread_id':'thread-round179'},\n"
            " {'type':'turn.started'},\n"
            " {'type':'item.completed','item':{'type':'agent_message','text':message}},\n"
            " {'type':'turn.completed'}]: print(json.dumps(event))\n",
            encoding="utf-8",
        )
        executable.chmod(
            executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return executable

    def test_invalid_fixture_is_inside_read_only_runtime_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round179-snapshot-") as temp_dir:
            root = Path(temp_dir) / "eval"
            self.auditor.prepare_root(root)
            frozen = root / "runtime-snapshot/evals/fixtures/invalid-epistemic.json"
            self.assertTrue(frozen.is_file())
            self.assertEqual(
                (SKILL_DIR / "evals/fixtures/invalid-epistemic.json").read_bytes(),
                frozen.read_bytes(),
            )
            self.assertEqual(0, stat.S_IMODE(frozen.stat().st_mode) & 0o222)

    def test_prompt_binds_internal_receipt_not_model_authored_canonical_path(self) -> None:
        case_id = "validator-rejects-epistemic-violations"
        with tempfile.TemporaryDirectory(prefix="sffs-round179-prompt-") as temp_dir:
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
            self.assertIn(
                f"RUNTIME_INVALID_FIXTURE: {root.resolve() / 'runtime-snapshot/evals/fixtures/invalid-epistemic.json'}",
                prompt,
            )
            self.assertIn(
                f"RUNTIME_VALIDATION_RECEIPT: {case_dir.resolve() / '.runtime/invalid-validation.json'}",
                prompt,
            )
            final_contract = self.host._eval_final_response_contract(case_id)
            self.assertIn("RUNTIME_VALIDATION_RECEIPT", final_contract)
            self.assertNotIn("receipts/validation.json", final_contract)

    def test_binder_promotes_internal_invalid_receipt_and_audits_it(self) -> None:
        case_id = "validator-rejects-epistemic-violations"
        with tempfile.TemporaryDirectory(prefix="sffs-round179-bind-") as temp_dir:
            temp = Path(temp_dir)
            root = temp / "eval"
            self.auditor.prepare_root(root)
            case_dir = root / case_id
            self.runner.prepare_runtime_materials(
                eval_root=root,
                case_dir=case_dir,
                case_id=case_id,
            )
            fixture = root / "runtime-snapshot/evals/fixtures/invalid-epistemic.json"
            internal = case_dir / ".runtime/invalid-validation.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    "-I",
                    "-S",
                    "-B",
                    str(root / "runtime-snapshot/scripts/casefile.py"),
                    "validate",
                    str(fixture),
                    "--report",
                    str(internal),
                ],
                cwd=root,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(1, completed.returncode, completed.stderr)
            message = internal.read_text(encoding="utf-8")
            prompt = root / ".control" / case_id / "host-eval-prompt.txt"
            prompt.parent.mkdir(parents=True)
            prompt.write_text(
                self.host.build_eval_prompt(
                    eval_root=root,
                    case_dir=case_dir,
                    case_id=case_id,
                ),
                encoding="utf-8",
            )
            receipt = self.host.run_codex_execution(
                codex_path=self.fake_codex(temp, message),
                prompt_path=prompt,
                output_dir=root / ".host" / case_id,
                cwd=case_dir,
                execution_kind="eval",
                subject_id=case_id,
                model=self.host.EVAL_MODEL,
                reasoning_effort=self.host.EVAL_REASONING_EFFORT,
                sandbox=self.host.EVAL_SANDBOX,
                timeout_seconds=10,
                input_path=case_dir / "input.json",
                context_path=root / self.auditor.EVALUATION_CONTEXT_FILE,
                source_sha256=self.auditor.runtime_snapshot_sha256(root),
            )

            result_path = self.host.bind_eval_case_result(
                receipt_path=receipt,
                eval_root=root,
                case_id=case_id,
            )

            result = json.loads(result_path.read_text(encoding="utf-8"))
            canonical = case_dir / "receipts/validation.json"
            self.assertEqual(internal.read_bytes(), canonical.read_bytes())
            self.assertEqual(
                [".runtime/invalid-validation.json"],
                result["runtime_validation_paths"],
            )
            audit = self.auditor.audit_case_result(
                root, case_id, self.auditor.EXPECTED_CASES[case_id]
            )
            self.assertTrue(audit["valid"], audit)


if __name__ == "__main__":
    unittest.main()
