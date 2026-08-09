import importlib.util
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from test_casefile import valid_standard


SKILL_DIR = Path(__file__).resolve().parents[1]
RUNNER = SKILL_DIR / "scripts" / "run_evals.py"
V4 = SKILL_DIR / "evals" / "raw" / "with-skill-v4-capability"


class EvalRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not RUNNER.exists():
            raise AssertionError(f"missing deterministic eval runner: {RUNNER}")
        spec = importlib.util.spec_from_file_location("run_evals", RUNNER)
        cls.module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.module)

    def load(self, relative):
        return json.loads((V4 / relative).read_text(encoding="utf-8"))

    def test_bidirectional_case_passes_semantic_contract(self):
        data = self.load("bidirectional-evidence-on-one-claim/casefile.json")
        self.assertEqual([], self.module.semantic_errors("bidirectional-evidence-on-one-claim", data))

    def test_bidirectional_case_rejects_unrequested_hypotheses(self):
        data = self.load("bidirectional-evidence-on-one-claim/casefile.json")
        data["hypotheses"] = [{"id": "H1"}]
        errors = self.module.semantic_errors("bidirectional-evidence-on-one-claim", data)
        self.assertTrue(any(item["code"] == "UNREQUESTED_HYPOTHESES" for item in errors))

    def test_discriminator_case_passes_branch_contract(self):
        data = self.load("single-high-information-discriminator/casefile.json")
        self.assertEqual([], self.module.semantic_errors("single-high-information-discriminator", data))

    def test_discriminator_case_detects_inverted_branch(self):
        data = self.load("single-high-information-discriminator/casefile.json")
        first = data["discriminator"]["branches"][0]["updates"]
        first[0]["effect"] = "strengthens"
        first[1]["effect"] = "weakens"
        errors = self.module.semantic_errors("single-high-information-discriminator", data)
        self.assertTrue(any(item["code"] == "BRANCH_DIRECTION_WRONG" for item in errors))

    def test_claim_strength_case_passes_semantic_contract(self):
        data = self.load("claim-specific-strength-calibration/casefile.json")
        self.assertEqual([], self.module.semantic_errors("claim-specific-strength-calibration", data))

    def test_receipt_discovery_finds_sibling_receipts_directory(self):
        artifact = V4 / "versioned-evidence-update" / "artifacts" / "revision-2.json"
        receipt_path, receipt = self.module.find_receipt(artifact)
        self.assertIsNotNone(receipt_path)
        self.assertIsNotNone(receipt)
        self.assertTrue(receipt["valid"])

    def test_partial_or_empty_root_cannot_report_full_pass(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            report = self.module.audit_root(Path(temp_dir))
        self.assertFalse(report["valid"])
        self.assertEqual(18, report["expected_case_count"])
        self.assertEqual(0, report["completed_case_count"])
        self.assertIn("relationship-silence", report["missing_cases"])

    def test_prepare_root_writes_only_frozen_inputs_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "fresh"
            prepared = self.module.prepare_root(root)
            self.assertEqual(18, prepared["case_count"])
            snapshot = root / "evaluation-context.json"
            self.assertTrue(snapshot.is_file())
            self.assertEqual(
                prepared["evaluation_context_sha256"],
                hashlib.sha256(snapshot.read_bytes()).hexdigest(),
            )
            self.assertEqual(
                set(self.module.EXPECTED_CASES)
                | {self.module.RUNTIME_SNAPSHOT_DIRECTORY},
                {path.name for path in root.iterdir() if path.is_dir()},
            )
            for case_id, case in self.module.EXPECTED_CASES.items():
                payload = json.loads((root / case_id / "input.json").read_text(encoding="utf-8"))
                self.assertEqual(self.module.expected_input_payload(case_id, case), payload)
            with self.assertRaises(FileExistsError):
                self.module.prepare_root(root)

    def test_audit_rejects_a_release_snapshot_changed_after_prepare(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "fresh"
            self.module.prepare_root(root)
            snapshot = root / "evaluation-context.json"
            value = json.loads(snapshot.read_text(encoding="utf-8"))
            value["release_evidence"]["skill"]["sha256"] = "0" * 64
            snapshot.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            report = self.module.audit_root(root)
        self.assertIn(
            "EVAL_CONTEXT_SOURCE_MISMATCH",
            {item["code"] for item in report["suite_errors"]},
        )

    def test_frozen_suite_hashes_are_enforced(self):
        self.assertEqual(
            {
                "cases.json": "52f46ca874e9aeb6a0d703baefb2607ac9e19be193cd92a6867238b7d9221cc0",
                "capability-cases.json": "1c3f0ac0921a50a3f39d8322c3a220decdae954647d714cb4bdda60dabb74fe9",
            },
            self.module.FROZEN_SUITE_SHA256,
        )

    def test_frozen_invalid_fixture_hash_is_enforced(self):
        fixture = SKILL_DIR / "evals" / "fixtures" / "invalid-epistemic.json"
        self.assertEqual(
            self.module.INVALID_FIXTURE_SHA256,
            hashlib.sha256(fixture.read_bytes()).hexdigest(),
        )

    def test_runtime_replay_sets_are_exact_per_case_mode(self):
        self.assertEqual(
            {"init": 0, "validate": 0, "render": 0},
            self.module.EXPECTED_RUNTIME_REPLAYS["relationship-silence"],
        )
        self.assertEqual(
            {},
            self.module.EXPECTED_RUNTIME_REPLAYS["translation-non-trigger"],
        )
        self.assertEqual(
            {"validate": 1},
            self.module.EXPECTED_RUNTIME_REPLAYS[
                "validator-rejects-epistemic-violations"
            ],
        )
        self.assertEqual(
            {
                "init_revision_1": 0,
                "validate_revision_1": 0,
                "start_update_full_history": 0,
                "validate_revision_2": 0,
                "diff": 0,
                "render_revision_2": 0,
            },
            self.module.EXPECTED_RUNTIME_REPLAYS["versioned-evidence-update"],
        )

    def test_runtime_replay_executes_the_real_cli(self):
        case_id = "relationship-silence"
        frozen = self.module.EXPECTED_CASES[case_id]
        with tempfile.TemporaryDirectory() as temp_dir:
            artifact = Path(temp_dir) / "casefile.json"
            data = valid_standard()
            artifact.write_text(
                json.dumps(data, ensure_ascii=False), encoding="utf-8"
            )
            replay = self.module.replay_runtime_commands(
                case_id,
                frozen,
                {1: (artifact, data)},
            )
        self.assertEqual(
            self.module.EXPECTED_RUNTIME_REPLAYS[case_id], replay
        )

    def test_every_triggering_frozen_case_has_semantic_checks(self):
        expected_codes = {
            "relationship-silence": "RELATIONSHIP_FACT_MISSING",
            "workplace-exclusion": "WORKPLACE_FACT_MISSING",
            "self-identity-story": "SELF_EVENT_MISSING",
            "secondhand-workplace-signal": "SECONDHAND_SIGNAL_MISSING",
            "bounded-working-hypotheses": "HYPOTHESES_WRONG",
            "false-precision-motives": "CANCELLATION_FACT_MISSING",
            "immediate-safety-override": "SAFETY_MODE_MISSING",
        }
        for case_id, expected_code in expected_codes.items():
            with self.subTest(case_id=case_id):
                codes = {item["code"] for item in self.module.semantic_errors(case_id, {})}
                self.assertIn(expected_code, codes)

    def test_versioned_update_rejects_using_new_material_to_prove_love(self):
        previous = {
            "claims": [{"id": "C2", "kind": "motive_inference", "exact_quote": "我认为他不爱我了。", "epistemic_status": "unverified"}],
            "evidence": [{"id": "E1", "input_id": "I1"}],
            "evidence_links": [{"proposition_id": "C2", "evidence_ref": "E1", "relation": "does_not_establish"}],
        }
        current = {
            "current_input_id": "I2",
            "claims": [{"id": "C2", "kind": "motive_inference", "exact_quote": "我认为他不爱我了。", "epistemic_status": "weakly_supported"}],
            "evidence": [{"id": "E1", "input_id": "I1"}, {"id": "E2", "input_id": "I2", "exact_quote": "手机送修，刚拿回来"}],
            "evidence_links": [
                {"proposition_id": "C2", "evidence_ref": "E1", "relation": "does_not_establish"},
                {"proposition_id": "C2", "evidence_ref": "E2", "relation": "supports"},
            ],
            "change_log": [{"target_id": "C2", "reason_evidence_refs": ["E2"]}],
        }
        errors = self.module.check_versioned_update(previous, current)
        self.assertTrue(any(item["code"] == "LOVE_INFERENCE_EXCEEDED" for item in errors))

    def test_case_result_rejects_empty_output_wrong_artifact_and_self_declared_commands(self):
        case_id = "relationship-silence"
        frozen = self.module.EXPECTED_CASES[case_id]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / case_id
            case_dir.mkdir()
            input_payload = self.module.expected_input_payload(case_id, frozen)
            (case_dir / "input.json").write_text(json.dumps(input_payload, ensure_ascii=False), encoding="utf-8")
            wrong = {
                "schema_version": self.module.CASEFILE.SCHEMA_VERSION,
                "case_id": "unrelated-case",
                "revision": 1,
            }
            (case_dir / "casefile.json").write_text(json.dumps(wrong), encoding="utf-8")
            (case_dir / "receipt.json").write_text("{}", encoding="utf-8")
            (case_dir / "response.md").write_text("", encoding="utf-8")
            result = {
                "case_id": case_id,
                "status": "completed",
                "model_environment": {"runner": "test", "model": "test", "isolation": "fork_turns=none; no eval history"},
                "input_sha256": self.module.expected_input_sha256(case_id, frozen),
                "raw_input_path": "input.json",
                "raw_output_path": "response.md",
                "artifact_paths": ["casefile.json"],
                "receipt_paths": ["receipt.json"],
                "command_exit_codes": {"noop": 0},
            }
            (case_dir / "case-result.json").write_text(json.dumps(result), encoding="utf-8")
            audited = self.module.audit_case_result(root, case_id, frozen)
        codes = {item["code"] for item in audited["errors"]}
        self.assertIn("RAW_OUTPUT_EMPTY", codes)
        self.assertIn("ARTIFACT_CASE_ID_MISMATCH", codes)
        self.assertIn("ARTIFACT_INPUT_MISMATCH", codes)
        self.assertIn("SELF_DECLARED_COMMAND_STATUS_FORBIDDEN", codes)

    def test_nonempty_unrelated_standard_output_is_rejected(self):
        case_id = "relationship-silence"
        frozen = self.module.EXPECTED_CASES[case_id]
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            case_dir = root / case_id
            case_dir.mkdir()
            (case_dir / "input.json").write_text(
                json.dumps(self.module.expected_input_payload(case_id, frozen), ensure_ascii=False),
                encoding="utf-8",
            )
            artifact = {
                "schema_version": self.module.CASEFILE.SCHEMA_VERSION,
                "skill_version": self.module.CASEFILE.SKILL_VERSION,
                "case_id": case_id,
                "revision": 1,
                "mode": "standard",
            }
            (case_dir / "casefile.json").write_text(
                json.dumps(artifact, ensure_ascii=False), encoding="utf-8"
            )
            (case_dir / "receipt.json").write_text("{}", encoding="utf-8")
            (case_dir / "response.md").write_text("这是一段无关但非空的回答。", encoding="utf-8")
            result = {
                "case_id": case_id,
                "status": "completed",
                "model_environment": {
                    "runner": "test",
                    "model": "test",
                    "isolation": self.module.EXPECTED_ISOLATION,
                },
                "input_sha256": self.module.expected_input_sha256(case_id, frozen),
                "raw_input_path": "input.json",
                "raw_output_path": "response.md",
                "artifact_paths": ["casefile.json"],
                "receipt_paths": ["receipt.json"],
            }
            (case_dir / "case-result.json").write_text(
                json.dumps(result, ensure_ascii=False), encoding="utf-8"
            )
            audited = self.module.audit_case_result(root, case_id, frozen)
        codes = {item["code"] for item in audited["errors"]}
        self.assertIn("RAW_OUTPUT_NOT_DETERMINISTIC_RENDER", codes)

    def test_long_anchor_rejects_dropped_negation(self):
        data = self.load("long-narrative-exact-anchor/casefile.json")
        for claim in data["claims"]:
            if claim.get("source_ref") == "S5":
                claim["exact_quote"] = "老板说过“你能力不行”。"
        errors = self.module.semantic_errors("long-narrative-exact-anchor", data)
        self.assertTrue(any(item["code"] == "NEGATION_DROPPED" for item in errors))


if __name__ == "__main__":
    unittest.main()
