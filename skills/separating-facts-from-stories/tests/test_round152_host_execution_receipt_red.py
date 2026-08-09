from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
HOST_SCRIPT = SKILL_DIR / "scripts" / "codex_exec_host.py"
RUNNER_SCRIPT = SKILL_DIR / "scripts" / "run_evals.py"


def _load(path: Path, name: str):
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class Round152HostExecutionReceiptRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.host = _load(HOST_SCRIPT, "round152_codex_exec_host")
        cls.runner = _load(RUNNER_SCRIPT, "round152_run_evals")

    def _require_host(self):
        if self.host is None:
            self.fail(f"missing host launcher: {HOST_SCRIPT}")
        return self.host

    def _fake_codex(self, root: Path) -> Path:
        executable = root / "fake-codex"
        executable.write_text(
            "#!/usr/bin/env python3\n"
            "import json, pathlib, sys\n"
            "if '--version' in sys.argv:\n"
            "    print('codex-cli 9.9.9-test')\n"
            "    raise SystemExit(0)\n"
            "flag = '-o' if '-o' in sys.argv else '--output-last-message'\n"
            "target = pathlib.Path(sys.argv[sys.argv.index(flag) + 1])\n"
            "target.write_text('OK', encoding='utf-8')\n"
            "events = [\n"
            " {'type':'thread.started','thread_id':'thread-host-observed-001'},\n"
            " {'type':'turn.started'},\n"
            " {'type':'item.completed','item':{'id':'item_0','type':'agent_message','text':'OK'}},\n"
            " {'type':'turn.completed','usage':{'input_tokens':1,'output_tokens':1}},\n"
            "]\n"
            "for event in events: print(json.dumps(event))\n",
            encoding="utf-8",
        )
        executable.chmod(
            executable.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH
        )
        return executable

    def test_launcher_creates_a_host_observed_hash_bound_receipt(self) -> None:
        host = self._require_host()
        with tempfile.TemporaryDirectory(prefix="sffs-round152-host-") as temp_dir:
            root = Path(temp_dir)
            prompt = root / "prompt.txt"
            input_path = root / "input.json"
            context = root / "evaluation-context.json"
            prompt.write_text("Return exactly OK.", encoding="utf-8")
            input_path.write_text('{"input":"x"}\n', encoding="utf-8")
            context.write_text('{"context":"y"}\n', encoding="utf-8")
            receipt_path = host.run_codex_execution(
                codex_path=self._fake_codex(root),
                prompt_path=prompt,
                output_dir=root / "host-output",
                cwd=root,
                execution_kind="eval",
                subject_id="relationship-silence",
                model="gpt-test",
                reasoning_effort="high",
                sandbox="read-only",
                timeout_seconds=10,
                input_path=input_path,
                context_path=context,
                source_sha256=None,
            )
            derived, errors = host.validate_host_receipt(
                receipt_path,
                expected_kind="eval",
                expected_subject_id="relationship-silence",
                expected_input_sha256=host.file_sha256(input_path),
                expected_context_sha256=host.file_sha256(context),
                expected_source_sha256=None,
            )
        self.assertEqual([], errors)
        self.assertEqual("thread-host-observed-001", derived["thread_id"])
        self.assertEqual(1, derived["turn_completed_count"])
        self.assertEqual("gpt-test", derived["model"])

    def test_receipt_rejects_tampered_output_or_incomplete_event_stream(self) -> None:
        host = self._require_host()
        with tempfile.TemporaryDirectory(prefix="sffs-round152-tamper-") as temp_dir:
            root = Path(temp_dir)
            prompt = root / "prompt.txt"
            prompt.write_text("Return exactly OK.", encoding="utf-8")
            receipt_path = host.run_codex_execution(
                codex_path=self._fake_codex(root),
                prompt_path=prompt,
                output_dir=root / "host-output",
                cwd=root,
                execution_kind="review",
                subject_id="review-a",
                model="gpt-test",
                reasoning_effort="high",
                sandbox="read-only",
                timeout_seconds=10,
                input_path=None,
                context_path=None,
                source_sha256="a" * 64,
            )
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            last_message = receipt_path.parent / receipt["artifacts"]["last_message"]["path"]
            last_message.write_text("tampered", encoding="utf-8")
            _, errors = host.validate_host_receipt(
                receipt_path,
                expected_kind="review",
                expected_subject_id="review-a",
                expected_input_sha256=None,
                expected_context_sha256=None,
                expected_source_sha256="a" * 64,
            )
            self.assertIn("HOST_ARTIFACT_HASH_MISMATCH", errors)

            last_message.write_text("OK", encoding="utf-8")
            events = receipt_path.parent / receipt["artifacts"]["events"]["path"]
            lines = events.read_text(encoding="utf-8").splitlines()
            events.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
            receipt["artifacts"]["events"]["sha256"] = host.file_sha256(events)
            receipt_path.write_text(
                json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            _, errors = host.validate_host_receipt(
                receipt_path,
                expected_kind="review",
                expected_subject_id="review-a",
                expected_input_sha256=None,
                expected_context_sha256=None,
                expected_source_sha256="a" * 64,
            )
            self.assertIn("HOST_EVENT_STREAM_INVALID", errors)

    def test_prepared_eval_rejects_self_declared_identity_without_host_receipt(self) -> None:
        self.assertIsNotNone(self.runner)
        runner = self.runner
        case_id = "translation-non-trigger"
        frozen = runner.EXPECTED_CASES[case_id]
        with tempfile.TemporaryDirectory(prefix="sffs-round152-eval-") as temp_dir:
            root = Path(temp_dir) / "eval"
            runner.prepare_root(root)
            case_dir = root / case_id
            (case_dir / "response.md").write_text(
                "The meeting has been moved to Friday at 3 p.m.", encoding="utf-8"
            )
            context = root / runner.EVALUATION_CONTEXT_FILE
            result = {
                "case_id": case_id,
                "status": "completed",
                "model_environment": {
                    "runner": "self-declared-unique-runner",
                    "model": "self-declared-model",
                    "isolation": runner.EXPECTED_ISOLATION,
                    "reasoning_effort": "self-declared-high",
                    "execution_id": "self-declared-unique-execution",
                },
                "input_sha256": runner.expected_input_sha256(case_id, frozen),
                "evaluation_context_sha256": hashlib.sha256(context.read_bytes()).hexdigest(),
                "raw_input_path": "input.json",
                "raw_output_path": "response.md",
                "artifact_paths": [],
                "receipt_paths": [],
            }
            (case_dir / "case-result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            audited = runner.audit_case_result(root, case_id, frozen)
        self.assertIn(
            "HOST_EXECUTION_RECEIPT_MISSING",
            {item["code"] for item in audited["errors"]},
        )


if __name__ == "__main__":
    unittest.main()
