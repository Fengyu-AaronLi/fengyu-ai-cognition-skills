from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "evals" / "runtime" / "run_runtime_evals.py"
ENVELOPES = ROOT / "evals" / "runtime" / "fixtures" / "envelopes"
SPECS = ROOT / "evals" / "runtime" / "fixtures" / "specs"

EXPECTED = {
    "DPBP-001": {
        "mode": "defer_to_user",
        "resources": [
            "references/core.md",
            "references/high-risk.md",
            "references/playbooks/career-exit.md",
        ],
    },
    "DPBP-002": {
        "mode": "define",
        "resources": [
            "references/core.md",
            "references/playbooks/ai-efficiency.md",
        ],
    },
    "DPBP-003": {
        "mode": "define",
        "resources": [
            "references/core.md",
            "references/playbooks/ai-product.md",
        ],
    },
    "DPBP-004": {"mode": "execute", "resources": []},
}


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def routed_reference_paths() -> set[str]:
    routes = json.loads((ROOT / "runtime" / "routes.json").read_text(encoding="utf-8"))
    found: set[str] = set()

    def visit(value: object) -> None:
        if isinstance(value, str) and value.startswith("references/"):
            found.add(value)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)

    visit(routes["resources"])
    return found


def load_runner_module():
    if not RUNNER.is_file():
        raise AssertionError("offline runtime eval runner is missing")
    module_spec = importlib.util.spec_from_file_location("runtime_eval_runner", RUNNER)
    if module_spec is None or module_spec.loader is None:
        raise AssertionError("could not load offline runtime eval runner")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


class RuntimeEvalRunnerContract(unittest.TestCase):
    maxDiff = None

    def run_runner(
        self,
        output: Path,
        *,
        repeat: int | None = 3,
        specs_dir: Path | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        self.assertTrue(RUNNER.is_file(), "offline runtime eval runner is missing")
        command = [sys.executable, str(RUNNER), "--output", str(output)]
        if repeat is not None:
            command.extend(["--repeat", str(repeat)])
        if specs_dir is not None:
            command.extend(["--specs-dir", str(specs_dir)])
        return subprocess.run(
            command,
            cwd=ROOT,
            capture_output=True,
            check=False,
        )

    def test_parser_defaults_to_one_hundred_gate_repetitions(self) -> None:
        module = load_runner_module()
        arguments = module.build_parser().parse_args(["--output", "report.json"])
        self.assertEqual(100, arguments.repeat)

    def test_byte_determinism_is_not_json_semantic_equality(self) -> None:
        module = load_runner_module()
        same = module.summarize_stdout([b'{"ok":true}\n', b'{"ok":true}\n'])
        self.assertTrue(same["deterministic"])
        self.assertEqual(1, same["unique_stdout_count"])

        line_ending_differs = module.summarize_stdout(
            [b'{"ok":true}\n', b'{"ok":true}\r\n']
        )
        self.assertFalse(line_ending_differs["deterministic"])
        self.assertEqual(2, line_ending_differs["unique_stdout_count"])

        key_order_differs = module.summarize_stdout(
            [b'{"a":1,"b":2}\n', b'{"b":2,"a":1}\n']
        )
        self.assertFalse(key_order_differs["deterministic"])

    def test_frozen_four_case_suite_passes_and_records_evidence(self) -> None:
        for case_id in EXPECTED:
            self.assertTrue((ENVELOPES / f"{case_id}.json").is_file(), case_id)
        for case_id in ("DPBP-001", "DPBP-002", "DPBP-003"):
            self.assertTrue((SPECS / f"{case_id}.json").is_file(), case_id)
        self.assertFalse((SPECS / "DPBP-004.json").exists())

        with tempfile.TemporaryDirectory() as temporary_directory:
            report_path = Path(temporary_directory) / "runtime-evals.json"
            result = self.run_runner(report_path, repeat=3)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            self.assertEqual(b"", result.stdout)
            self.assertEqual(b"", result.stderr)
            self.assertTrue(report_path.is_file())

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual("1.0", report["schema_version"])
            self.assertEqual("offline-runtime-eval", report["report_type"])
            self.assertEqual("pass", report["status"])
            self.assertEqual([], report["failure_codes"])
            self.assertEqual(4, report["summary"]["case_count"])
            self.assertEqual(4, report["summary"]["passed"])
            self.assertEqual(0, report["summary"]["failed"])

            environment = report["environment"]
            self.assertEqual(3, environment["gate_repetitions"])
            self.assertTrue(environment["offline"])
            self.assertFalse(environment["network_used"])
            self.assertFalse(environment["model_api_used"])
            self.assertTrue(environment["python_version"])
            self.assertTrue(environment["os"])

            artifacts = report["artifacts"]
            self.assertEqual(
                (ROOT / "VERSION").read_text(encoding="utf-8").strip(),
                artifacts["version"],
            )
            self.assertEqual(
                sha256_file(ROOT / "VERSION"), artifacts["version_sha256"]
            )
            self.assertEqual(sha256_file(ROOT / "SKILL.md"), artifacts["skill_sha256"])
            self.assertEqual(sha256_file(ROOT / "scripts" / "dpbp"), artifacts["cli_sha256"])
            self.assertEqual(sha256_file(RUNNER), artifacts["runner_sha256"])
            self.assertEqual(
                sha256_file(ROOT / "schemas" / "request-envelope.schema.json"),
                artifacts["schema_sha256"]["request_envelope"],
            )
            self.assertEqual(
                sha256_file(ROOT / "schemas" / "problem-spec.schema.json"),
                artifacts["schema_sha256"]["problem_spec"],
            )
            self.assertEqual(
                sha256_file(ROOT / "schemas" / "problem-state.schema.json"),
                artifacts["schema_sha256"]["problem_state"],
            )
            expected_references = {
                relative: sha256_file(ROOT / relative)
                for relative in sorted(routed_reference_paths())
            }
            self.assertEqual(
                expected_references,
                artifacts["gate_reference_sha256"],
            )
            self.assertEqual(
                sorted(expected_references),
                list(artifacts["gate_reference_sha256"]),
            )

            cases = {item["case_id"]: item for item in report["cases"]}
            self.assertEqual(set(EXPECTED), set(cases))
            for case_id, expected in EXPECTED.items():
                case = cases[case_id]
                self.assertEqual("pass", case["status"])
                self.assertEqual([], case["failure_codes"])
                gate = case["gate"]
                self.assertEqual(3, gate["repetitions"])
                self.assertTrue(gate["stdout"]["deterministic"])
                self.assertEqual(1, gate["stdout"]["unique_stdout_count"])
                self.assertEqual(expected["mode"], gate["observed"]["mode"])
                self.assertEqual(expected["resources"], gate["observed"]["resources"])

                envelope = json.loads(
                    (ENVELOPES / f"{case_id}.json").read_text(encoding="utf-8")
                )
                request_hash = hashlib.sha256(
                    envelope["original_request"].encode("utf-8")
                ).hexdigest()
                self.assertEqual(request_hash, gate["observed"]["request_sha256"])

            for case_id in ("DPBP-001", "DPBP-002", "DPBP-003"):
                spec_result = cases[case_id]["spec"]
                self.assertTrue(spec_result["present"])
                self.assertEqual(0, spec_result["validate"]["exit_code"])
                self.assertTrue(spec_result["validate"]["valid"])
                self.assertEqual(0, spec_result["render"]["exit_code"])
                self.assertGreater(spec_result["render"]["stdout_bytes"], 0)
                self.assertTrue(spec_result["render"]["stdout_sha256"])

            execute_case = cases["DPBP-004"]
            self.assertTrue(execute_case["gate"]["observed"]["execution_allowed"])
            self.assertEqual([], execute_case["gate"]["observed"]["resources"])
            self.assertFalse(execute_case["spec"]["present"])

    def test_eval_failures_are_written_to_the_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temp = Path(temporary_directory)
            empty_specs = temp / "empty-specs"
            empty_specs.mkdir()
            report_path = temp / "failed-runtime-evals.json"
            result = self.run_runner(report_path, repeat=1, specs_dir=empty_specs)
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            self.assertEqual(b"", result.stdout)
            self.assertEqual(b"", result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual("fail", report["status"])
            self.assertIn("SPEC_FIXTURE_MISSING", report["failure_codes"])
            by_id = {item["case_id"]: item for item in report["cases"]}
            for case_id in ("DPBP-001", "DPBP-002", "DPBP-003"):
                self.assertIn("SPEC_FIXTURE_MISSING", by_id[case_id]["failure_codes"])
            self.assertNotIn("SPEC_FIXTURE_MISSING", by_id["DPBP-004"]["failure_codes"])

    def test_fixture_override_cannot_pass_as_manifest_bound(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            report_path = Path(temporary_directory) / "override.json"
            result = self.run_runner(report_path, repeat=1, specs_dir=SPECS)
            self.assertEqual(1, result.returncode, result.stdout + result.stderr)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertEqual("fail", report["status"])
            self.assertIn("UNBOUND_FIXTURE_OVERRIDE", report["failure_codes"])
            self.assertEqual("unbound_override", report["suite"]["binding_status"])

    def test_output_is_mandatory_and_parent_must_exist(self) -> None:
        missing_output = subprocess.run(
            [sys.executable, str(RUNNER), "--repeat", "1"],
            cwd=ROOT,
            capture_output=True,
            check=False,
        )
        self.assertEqual(2, missing_output.returncode)

        with tempfile.TemporaryDirectory() as temporary_directory:
            impossible = Path(temporary_directory) / "missing-parent" / "report.json"
            result = self.run_runner(impossible, repeat=1)
            self.assertEqual(2, result.returncode)
            self.assertFalse(impossible.exists())


if __name__ == "__main__":
    unittest.main()
