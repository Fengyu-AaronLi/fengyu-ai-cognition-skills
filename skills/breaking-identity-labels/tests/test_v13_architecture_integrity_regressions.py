#!/usr/bin/env python3
"""V13 red contracts for semantic baselines and audit receipt integrity."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CASE_CLI = ROOT / "scripts" / "identity_label_case.py"
CONTROLLER = ROOT / "scripts" / "run_evolution.py"
BASE_ANALYSIS = ROOT / "tests" / "fixtures" / "analysis-c01.json"
IDENTITY_TEXT = "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。"
SAFETY_TEXT = "我现在想自杀，刀就在手边，已经决定今晚动手。"
SCAFFOLD_CLOCK = "2026-08-06T00:00:00Z"
PLAN_CLOCK = "2026-08-06T00:01:00Z"
AUDIT_IDS = (
    "independent_attribution_audit",
    "independent_clinical_safety_audit",
    "independent_state_integrity_audit",
    "release_package_audit",
)
DEMO_FILES = (
    ".case.lock",
    "analysis.json",
    "case.json",
    "demo-input.txt",
    "events.head.json",
    "events.jsonl",
    "report.md",
    "run-manifest.json",
)


def sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def json_payload(result: subprocess.CompletedProcess[str]) -> dict:
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def run_case(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CASE_CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


class SemanticBaselineIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v13-semantic-")
        self.temp_root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def scaffold(self, text: str, case_id: str) -> dict:
        result = run_case(
            "scaffold",
            "--text",
            text,
            "--case-id",
            case_id,
            "--clock",
            SCAFFOLD_CLOCK,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return json_payload(result)

    def compile(self, scaffold: dict, analysis: dict, name: str) -> subprocess.CompletedProcess[str]:
        scaffold_path = self.temp_root / f"{name}-scaffold.json"
        analysis_path = self.temp_root / f"{name}-analysis.json"
        output_path = self.temp_root / f"{name}-case.json"
        write_json(scaffold_path, scaffold)
        write_json(analysis_path, analysis)
        return run_case(
            "compile",
            "--scaffold",
            str(scaffold_path),
            "--analysis",
            str(analysis_path),
            "--out",
            str(output_path),
            "--clock",
            PLAN_CLOCK,
        )

    def base_analysis(self) -> dict:
        return json.loads(BASE_ANALYSIS.read_text(encoding="utf-8"))

    def test_compile_cannot_drop_runtime_extracted_labels_or_judgments(self) -> None:
        scaffold = self.scaffold(IDENTITY_TEXT, "v13-semantic-compile")
        analysis = self.base_analysis()
        analysis["labels"] = []
        analysis["judgments"] = []

        result = self.compile(scaffold, analysis, "drop-baseline")
        if result.returncode != 0:
            codes = {item.get("code") for item in json_payload(result).get("errors", [])}
            self.assertTrue(
                {
                    "semantic_baseline_label_missing",
                    "semantic_baseline_judgment_missing",
                }
                & codes,
                result.stdout + result.stderr,
            )
            return

        case = json_payload(result)["case"]
        expected_labels = {item["text"] for item in scaffold["analysis"]["labels"]}
        expected_judgments = {item["text"] for item in scaffold["analysis"]["judgments"]}
        actual_labels = {item["text"] for item in case["analysis"]["labels"]}
        actual_judgments = {item["text"] for item in case["analysis"]["judgments"]}
        self.assertTrue(expected_labels.issubset(actual_labels))
        self.assertTrue(expected_judgments.issubset(actual_judgments))

    def test_validate_rederives_unknowns_and_reserved_judgments_from_e000(self) -> None:
        scaffold = self.scaffold(IDENTITY_TEXT, "v13-semantic-validate")
        case = copy.deepcopy(scaffold)
        case["revision"] = 1
        case["status"] = "planned"
        case["updated_at"] = PLAN_CLOCK
        case["analysis"] = self.base_analysis()
        case["analysis"]["unknowns"] = []
        case["analysis"]["reserved_judgments"] = []
        case["analysis"]["experiment"]["started_at"] = None
        case_path = self.temp_root / "forged-planned-case.json"
        write_json(case_path, case)

        result = run_case("validate", str(case_path))
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        codes = {item.get("code") for item in json_payload(result).get("errors", [])}
        self.assertIn("semantic_baseline_unknown_missing", codes)
        self.assertIn("semantic_baseline_reserved_judgment_missing", codes)

    def test_validate_cannot_delete_the_safety_reserved_judgment(self) -> None:
        case = self.scaffold(SAFETY_TEXT, "v13-safety-reservation")
        self.assertEqual("safety_support", case["route"]["mode"])
        self.assertTrue(case["analysis"]["reserved_judgments"])
        case["analysis"]["reserved_judgments"] = []
        case_path = self.temp_root / "forged-safety-case.json"
        write_json(case_path, case)

        result = run_case("validate", str(case_path))
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        codes = {item.get("code") for item in json_payload(result).get("errors", [])}
        self.assertIn("semantic_baseline_reserved_judgment_missing", codes)

    def test_compile_rejects_an_experiment_unbound_to_the_original_judgment(self) -> None:
        scaffold = self.scaffold(IDENTITY_TEXT, "v13-experiment-binding")
        analysis = self.base_analysis()
        analysis["experiment"]["target_claim"] = "天气决定我的全部职业能力"

        result = self.compile(scaffold, analysis, "unbound-experiment")
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        codes = {item.get("code") for item in json_payload(result).get("errors", [])}
        self.assertIn("experiment_target_unbound", codes)


class AuditFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        for relative in (
            "scripts",
            "schemas",
            "tests",
            "workflows",
            "examples/real-run",
            "evals/receipts",
            "evals/runs",
        ):
            (root / relative).mkdir(parents=True, exist_ok=True)
        (root / "SKILL.md").write_text("ordinary skill file\n", encoding="utf-8")
        (root / "scripts" / "identity_label_case.py").write_text(
            "print('runtime')\n", encoding="utf-8"
        )
        (root / "scripts" / "build_package.py").write_text(
            "import json\nprint(json.dumps({'status': 'built', 'tree_sha256': 'f' * 64}))\n",
            encoding="utf-8",
        )
        (root / "scripts" / "run_evolution.py").write_text(
            "# controller governance fixture\n", encoding="utf-8"
        )
        (root / "scripts" / "build_demo.py").write_text(
            "# demo builder governance fixture\n", encoding="utf-8"
        )
        (root / "evals" / "validate.py").write_text(
            "# evaluator governance fixture\n", encoding="utf-8"
        )
        (root / "scripts" / "worker.py").write_text("print('OK')\n", encoding="utf-8")
        write_json(root / "schemas" / "case.schema.json", {"type": "object"})
        write_json(root / "schemas" / "release-gate.schema.json", {"type": "object"})
        write_json(root / "schemas" / "audit-receipt.schema.json", {"type": "object"})
        (root / "tests" / "test_v13_gate.py").write_text(
            "# synthetic frozen test generation\n", encoding="utf-8"
        )
        for name in DEMO_FILES:
            (root / "examples" / "real-run" / name).write_text(
                f"fixture:{name}\n", encoding="utf-8"
            )
        self.state_path = root / "evals" / "release-gate.json"
        self.manifest_path = root / "evals" / "test-generation-manifest.json"
        test_path = root / "tests" / "test_v13_gate.py"
        write_json(
            self.manifest_path,
            {
                "schema_version": "1.0",
                "generation_rules": [
                    {
                        "generation": "v13",
                        "minimum": 1,
                        "pattern": "tests/test_v13_*.py",
                    }
                ],
                "files": [
                    {
                        "generation": "v13",
                        "path": "tests/test_v13_gate.py",
                        "sha256": sha256(test_path.read_bytes()),
                    }
                ],
            },
        )
        self.workflow = root / "workflows" / "v13-audit.json"
        write_json(
            self.workflow,
            {
                "schema_version": "1.0",
                "workflow_id": "identity-v13-audit-receipts",
                "steps": [
                    {
                        "id": "green",
                        "kind": "command",
                        "depends_on": [],
                        "argv": ["{python}", "{root}/scripts/worker.py"],
                        "expected": "exit_zero",
                    }
                ],
            },
        )

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(CONTROLLER),
                *args,
                "--root",
                str(self.root),
                "--state",
                str(self.state_path),
                "--test-manifest",
                str(self.manifest_path),
            ],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )

    def freeze(self) -> dict:
        completed_run = self.root / "evals" / "runs" / "v13-audit"
        executed = self.run(
            "run",
            "--workflow",
            str(self.workflow),
            "--run-dir",
            str(completed_run),
            "--run-id",
            "v13-audit",
            "--candidate-id",
            "v13-receipt-candidate",
        )
        if executed.returncode != 0:
            raise AssertionError(executed.stdout + executed.stderr)
        result = self.run(
            "freeze",
            "--candidate-id",
            "v13-receipt-candidate",
            "--workflow",
            str(self.workflow),
            "--completed-run-dir",
            str(completed_run),
            "--clock",
            SCAFFOLD_CLOCK,
        )
        if result.returncode != 0:
            raise AssertionError(result.stdout + result.stderr)
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    def receipt(
        self,
        audit_id: str,
        *,
        name: str | None = None,
        artifacts: dict[str, str] | None = None,
    ) -> str:
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        relative = f"evals/receipts/{name or audit_id}.json"
        receipt_id = name or f"receipt-{audit_id}"
        evidence_root = self.root / "evals" / "receipts" / receipt_id
        evidence_root.mkdir(parents=True, exist_ok=True)
        evidence_files = {
            "preregistration.json": "{\"cases\":[\"fixture\"]}\n",
            "environment.json": "{\"environment\":\"fixture\"}\n",
            "command.stdout.txt": "OK\n",
            "command.stderr.txt": "",
            "raw-output.txt": "OK\n",
        }
        for filename, content in evidence_files.items():
            (evidence_root / filename).write_text(content, encoding="utf-8")
        evidence_prefix = f"evals/receipts/{receipt_id}"
        receipt = {
            "schema_version": "1.1",
            "receipt_id": receipt_id,
            "audit_id": audit_id,
            "candidate": {
                "candidate_id": state["candidate_id"],
                "artifacts": artifacts or state["artifacts"],
                "test_manifest_sha256": state["test_manifest_sha256"],
            },
            "completed_run": state["completed_run"],
            "preregistration": {
                "path": f"{evidence_prefix}/preregistration.json",
                "case_set_sha256": sha256(
                    (evidence_root / "preregistration.json").read_bytes()
                ),
            },
            "environment": {
                "path": f"{evidence_prefix}/environment.json",
                "sha256": sha256((evidence_root / "environment.json").read_bytes()),
            },
            "commands": [
                {
                    "argv": ["python3", "tests/run_audit.py"],
                    "exit_code": 0,
                    "stdout_path": f"{evidence_prefix}/command.stdout.txt",
                    "stdout_sha256": sha256(
                        (evidence_root / "command.stdout.txt").read_bytes()
                    ),
                    "stderr_path": f"{evidence_prefix}/command.stderr.txt",
                    "stderr_sha256": sha256(
                        (evidence_root / "command.stderr.txt").read_bytes()
                    ),
                }
            ],
            "raw_output_path": f"{evidence_prefix}/raw-output.txt",
            "raw_output_sha256": sha256(
                (evidence_root / "raw-output.txt").read_bytes()
            ),
            "manual_findings": [],
            "blockers": [],
            "status": "passed",
        }
        write_json(self.root / relative, receipt)
        return relative

    def force_passed_state(self, receipts: dict[str, str]) -> None:
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        for audit in state["audits"]:
            relative = receipts[audit["audit_id"]]
            audit.update(
                {
                    "status": "passed",
                    "blocker_count": 0,
                    "artifact_sha256": dict(state["artifacts"]),
                    "evidence": [relative],
                    "receipt_sha256": sha256((self.root / relative).read_bytes()),
                }
            )
        state["blockers"] = []
        state["blocker_count"] = 0
        state["decision"] = "candidate"
        write_json(self.state_path, state)


class AuditReceiptIntegrityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="identity-v13-receipt-")
        self.fixture = AuditFixture(Path(self.temporary.name))
        self.fixture.freeze()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def record(self, audit_id: str, evidence: str) -> subprocess.CompletedProcess[str]:
        return self.fixture.run(
            "record-audit",
            "--audit-id",
            audit_id,
            "--status",
            "passed",
            "--blocker-count",
            "0",
            "--evidence",
            evidence,
        )

    def test_record_audit_rejects_an_ordinary_file_and_self_reported_status(self) -> None:
        before = self.fixture.state_path.read_bytes()
        result = self.record("independent_attribution_audit", "SKILL.md")

        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertEqual(before, self.fixture.state_path.read_bytes())
        self.assertIn(
            "audit_receipt_required",
            set(json_payload(result).get("errors", [])),
        )

    def test_record_audit_rejects_a_receipt_with_the_wrong_inner_audit_id(self) -> None:
        relative = self.fixture.receipt(
            "independent_clinical_safety_audit",
            name="wrong-type-for-attribution",
        )
        result = self.record("independent_attribution_audit", relative)

        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn(
            "audit_receipt_type_mismatch",
            set(json_payload(result).get("errors", [])),
        )

    def test_record_audit_rejects_a_receipt_bound_to_other_artifacts(self) -> None:
        state = json.loads(self.fixture.state_path.read_text(encoding="utf-8"))
        wrong = dict(state["artifacts"])
        wrong["runtime_sha256"] = "0" * 64
        relative = self.fixture.receipt(
            "independent_attribution_audit",
            name="wrong-candidate-hash",
            artifacts=wrong,
        )
        result = self.record("independent_attribution_audit", relative)

        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn(
            "audit_receipt_candidate_mismatch",
            set(json_payload(result).get("errors", [])),
        )

    def test_record_audit_cli_accepts_only_a_structured_receipt(self) -> None:
        result = subprocess.run(
            [sys.executable, str(CONTROLLER), "record-audit", "--help"],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn("--receipt", result.stdout)
        self.assertNotIn("--status", result.stdout)
        self.assertNotIn("--blocker-count", result.stdout)

    def test_strict_gate_rejects_four_slots_backed_by_plain_files(self) -> None:
        self.fixture.force_passed_state({audit_id: "SKILL.md" for audit_id in AUDIT_IDS})
        result = self.fixture.run("check", "--strict-release")

        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json_payload(result)
        self.assertFalse(payload.get("release_eligible", False))
        self.assertIn("audit_receipt_required", set(payload.get("errors", [])))

    def test_strict_gate_rejects_one_receipt_reused_for_four_audit_types(self) -> None:
        relative = self.fixture.receipt(
            "independent_attribution_audit",
            name="reused-for-every-audit",
        )
        self.fixture.force_passed_state({audit_id: relative for audit_id in AUDIT_IDS})
        result = self.fixture.run("check", "--strict-release")

        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        errors = set(json_payload(result).get("errors", []))
        self.assertIn("audit_receipt_reused", errors)
        self.assertIn("audit_receipt_type_mismatch", errors)

    def test_strict_gate_rejects_distinct_receipts_swapped_between_audit_types(self) -> None:
        receipts = {audit_id: self.fixture.receipt(audit_id) for audit_id in AUDIT_IDS}
        receipts["independent_attribution_audit"], receipts[
            "independent_clinical_safety_audit"
        ] = (
            receipts["independent_clinical_safety_audit"],
            receipts["independent_attribution_audit"],
        )
        self.fixture.force_passed_state(receipts)
        result = self.fixture.run("check", "--strict-release")

        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        self.assertIn(
            "audit_receipt_type_mismatch",
            set(json_payload(result).get("errors", [])),
        )

    def test_strict_gate_rehashes_each_receipt_instead_of_trusting_saved_status(self) -> None:
        receipts = {audit_id: self.fixture.receipt(audit_id) for audit_id in AUDIT_IDS}
        self.fixture.force_passed_state(receipts)
        target = self.fixture.root / receipts["independent_attribution_audit"]
        receipt = json.loads(target.read_text(encoding="utf-8"))
        receipt["raw_output_sha256"] = "0" * 64
        write_json(target, receipt)

        result = self.fixture.run("check", "--strict-release")
        self.assertNotEqual(0, result.returncode, result.stdout + result.stderr)
        payload = json_payload(result)
        self.assertFalse(payload.get("release_eligible", False))
        self.assertIn("audit_receipt_hash_mismatch", set(payload.get("errors", [])))


if __name__ == "__main__":
    unittest.main()
