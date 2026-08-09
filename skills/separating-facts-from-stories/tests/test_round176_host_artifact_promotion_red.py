#!/usr/bin/env python3
"""Round 176 RED: canonical eval artifacts come from one bound runtime workspace."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import shutil
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
WORKFLOW_PATH = SKILL_DIR / "scripts" / "workflow.py"
FIXTURE = (
    SKILL_DIR
    / "evals/raw/with-skill-v44-host-run-20260806-r2/relationship-silence/workspace-raw/casefile.json"
)


def load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Round176HostArtifactPromotionRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load(RUNNER_PATH, "round176_host_eval_runner")
        cls.host = load(HOST_PATH, "round176_codex_exec_host")
        cls.auditor = load(AUDITOR_PATH, "round176_eval_auditor")

    def run_workflow(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        completed = subprocess.run(
            [sys.executable, "-B", str(WORKFLOW_PATH), *arguments],
            cwd=SKILL_DIR,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, completed.returncode, completed.stderr)
        return completed

    def completed_workspace(self, root: Path, case_id: str) -> tuple[Path, str]:
        case_dir = root / case_id
        layout = self.runner.prepare_runtime_materials(
            eval_root=root,
            case_dir=case_dir,
            case_id=case_id,
        )
        workspace = case_dir / layout["workspace_paths"][0]
        input_path = case_dir / layout["input_paths"][0]
        self.run_workflow(
            "start",
            "--input",
            str(input_path),
            "--workspace",
            str(workspace),
            "--case-id",
            case_id,
            "--mode",
            "standard",
        )
        fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
        exact_input = input_path.read_text(encoding="utf-8")
        exact_hash = hashlib.sha256(exact_input.encode("utf-8")).hexdigest()
        fixture["inputs"][0]["text"] = exact_input
        fixture["inputs"][0]["sha256"] = exact_hash
        fixture["input_sha256"] = exact_hash
        (workspace / "casefile.json").write_text(
            json.dumps(fixture, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self.run_workflow("check", "--workspace", str(workspace))
        self.run_workflow("finalize", "--workspace", str(workspace))
        return workspace, (workspace / "response.md").read_text(encoding="utf-8")

    def fake_codex(self, root: Path, message: str) -> Path:
        executable = root / "codex"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json,pathlib,sys\n"
            "if '--version' in sys.argv:\n"
            " print('codex-cli round176 fixture')\n"
            " raise SystemExit(0)\n"
            f"message={message!r}\n"
            "target=pathlib.Path(sys.argv[sys.argv.index('--output-last-message')+1])\n"
            "target.write_text(message,encoding='utf-8')\n"
            "for event in [\n"
            " {'type':'thread.started','thread_id':'thread-round176'},\n"
            " {'type':'turn.started'},\n"
            " {'type':'item.completed','item':{'type':'agent_message','text':message}},\n"
            " {'type':'turn.completed'}]: print(json.dumps(event))\n",
            encoding="utf-8",
        )
        executable.chmod(
            executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return executable

    def host_receipt(self, root: Path, case_id: str, message: str, temp: Path) -> Path:
        case_dir = root / case_id
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
        return self.host.run_codex_execution(
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

    def test_binder_promotes_workspace_artifact_and_revalidates_canonical_path(self) -> None:
        case_id = "relationship-silence"
        with tempfile.TemporaryDirectory(prefix="sffs-round176-promote-") as temp_dir:
            temp = Path(temp_dir)
            root = temp / "eval"
            self.auditor.prepare_root(root)
            workspace, message = self.completed_workspace(root, case_id)
            receipt = self.host_receipt(root, case_id, message.rstrip("\n"), temp)

            result_path = self.host.bind_eval_case_result(
                receipt_path=receipt,
                eval_root=root,
                case_id=case_id,
            )

            result = json.loads(result_path.read_text(encoding="utf-8"))
            artifact = root / case_id / "artifacts/separation.json"
            validation = root / case_id / "receipts/validation.json"
            self.assertEqual((workspace / "casefile.json").read_bytes(), artifact.read_bytes())
            validation_data = json.loads(validation.read_text(encoding="utf-8"))
            self.assertEqual(str(artifact.resolve()), validation_data["artifact_path"])
            self.assertEqual([".runtime/workspace-1"], result["runtime_workspace_paths"])
            self.assertEqual([".runtime/input-1.txt"], result["runtime_input_paths"])
            audit = self.auditor.audit_case_result(
                root, case_id, self.auditor.EXPECTED_CASES[case_id]
            )
            self.assertTrue(audit["valid"], audit)

    def test_second_workspace_casefile_is_rejected_not_hidden(self) -> None:
        case_id = "relationship-silence"
        with tempfile.TemporaryDirectory(prefix="sffs-round176-duplicate-") as temp_dir:
            temp = Path(temp_dir)
            root = temp / "eval"
            self.auditor.prepare_root(root)
            _, message = self.completed_workspace(root, case_id)
            alternate = root / case_id / ".runtime/alternate"
            alternate.mkdir()
            shutil.copyfile(FIXTURE, alternate / "casefile.json")
            receipt = self.host_receipt(root, case_id, message, temp)

            with self.assertRaisesRegex(
                self.host.HostExecutionError,
                "EVAL_RUNTIME_CASEFILE_SET_MISMATCH",
            ):
                self.host.bind_eval_case_result(
                    receipt_path=receipt,
                    eval_root=root,
                    case_id=case_id,
                )


if __name__ == "__main__":
    unittest.main()
