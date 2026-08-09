from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_claim_audit import load_runtime


SKILL_DIR = Path(__file__).resolve().parents[1]
INSTALLER_PATH = SKILL_DIR / "scripts" / "install.py"


def read(relative: str) -> str:
    return (SKILL_DIR / relative).read_text(encoding="utf-8")


def read_json(relative: str) -> dict:
    return json.loads(read(relative))


def load_installer():
    spec = importlib.util.spec_from_file_location(
        "auditing_ai_claims_v31_installer_contract", INSTALLER_PATH
    )
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load installer")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReleaseContractV31RedTests(unittest.TestCase):
    def test_runtime_policy_and_public_contract_are_versioned_as_v31(self):
        runtime = load_runtime()
        self.assertEqual(runtime.RUNTIME_VERSION, "3.1.0")
        self.assertEqual(runtime.POLICY_VERSION, "3.1.0")
        self.assertIn("适用版本：3.1.0", read("references/runtime-contract.md"))

    def test_skill_entrypoint_requires_safe_file_loop_and_countercheck(self):
        skill = read("SKILL.md")
        required = (
            "--candidates-file",
            "--candidate-id",
            "claim --file",
            "countercheck",
            "claim_countercheck",
            "summarize --file",
            "cli_subcommand",
            "required_inputs",
        )
        missing = [token for token in required if token not in skill]
        self.assertEqual(missing, [])

    def test_readme_and_workflow_show_the_actual_v31_state_order(self):
        for relative in ("README.md", "references/workflow-loop.md"):
            with self.subTest(relative=relative):
                content = read(relative)
                diagrams = re.findall(r"```text\n(.*?)```", content, flags=re.DOTALL)
                diagram = next(
                    (
                        block
                        for block in diagrams
                        if all(
                            stage in block
                            for stage in (
                                "claim_assessment",
                                "claim_countercheck",
                                "audit_summary",
                            )
                        )
                    ),
                    "",
                )
                assessment = diagram.find("claim_assessment")
                countercheck = diagram.find("claim_countercheck")
                summary = diagram.find("audit_summary")
                self.assertGreaterEqual(assessment, 0)
                self.assertGreater(countercheck, assessment)
                self.assertGreater(summary, countercheck)
                for token in (
                    "--candidates-file",
                    "--file",
                ):
                    self.assertIn(token, content)
                self.assertRegex(
                    content,
                    r"countercheck(?: --workspace [^\n`]+)? --file",
                )
                self.assertRegex(
                    content,
                    r"summarize(?: --workspace [^\n`]+)? --file",
                )
                if relative == "references/workflow-loop.md":
                    self.assertIn("--candidate-id", content)

    def test_runtime_contract_covers_transactions_deadline_and_safe_next(self):
        contract = read("references/runtime-contract.md")
        required = (
            ".runtime-init.json",
            ".runtime-key",
            "runtime-attestations.json",
            "source-transactions/",
            "prepared",
            "receipt_saved",
            "attested",
            "committed",
            "aborted",
            "abort-source-transaction",
            "总时限",
            "60",
            "claim_countercheck",
            "cli_subcommand",
            "required_inputs",
            "missing_evidence_purposes",
            "--candidates-file",
            "--candidate-id",
            "summarize --file",
        )
        missing = [token for token in required if token not in contract]
        self.assertEqual(missing, [])

    def test_claim_ledger_schema_matches_candidate_id_and_countercheck_records(self):
        schema = read_json("schemas/claim-ledger.schema.json")
        exclusion = schema["$defs"]["candidate_exclusion"]
        self.assertIn("candidate_id", exclusion["required"])
        self.assertEqual(
            exclusion["properties"]["candidate_id"]["pattern"], "^U[0-9]{3,}$"
        )

        claim = schema["$defs"]["claim"]
        self.assertIn("countercheck", claim["properties"])
        self.assertNotIn(
            "countercheck",
            claim["required"],
            "an in-progress assessed claim is valid before the countercheck stage",
        )
        countercheck = claim["properties"]["countercheck"]
        if "$ref" in countercheck:
            countercheck = schema["$defs"][countercheck["$ref"].rsplit("/", 1)[-1]]
        self.assertFalse(countercheck["additionalProperties"])
        self.assertEqual(
            set(countercheck["required"]),
            {
                "falsifier",
                "checked_source_ids",
                "result",
                "stop_reason",
                "checked_at",
                "basis_hash",
            },
        )
        self.assertEqual(
            set(countercheck["properties"]["result"]["enum"]),
            {
                "no_conflict_found",
                "conflict_found",
                "scope_narrowed",
                "inconclusive",
            },
        )

    def test_claim_file_schema_is_caller_input_not_a_final_ledger_claim(self):
        schema = read_json("schemas/claim.schema.json")
        template = read_json("templates/claim.json")
        required = {
            "claim_id",
            "text",
            "claim_type",
            "temporal_sensitivity",
            "criteria",
            "requires_independent_evidence",
            "risk_domain",
            "causal_basis",
            "evidence",
            "source_identity_gate",
            "content_support_gate",
            "action_applicability_gate",
            "conflicts",
            "status",
            "confidence_reason",
            "next_step",
            "input_candidates",
        }
        self.assertNotIn("$ref", schema)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), required)
        self.assertEqual(set(template), required | {"as_of"})
        runtime_owned = {"assessment_recorded", "unknowns", "countercheck"}
        self.assertTrue(runtime_owned.isdisjoint(schema["properties"]))
        self.assertTrue(runtime_owned.isdisjoint(template))
        self.assertNotIn("as_of", schema["required"])

    def test_workflow_next_schema_matches_v31_runtime_payload(self):
        schema = read_json("schemas/workflow-next.schema.json")
        stages = set(schema["properties"]["stage"]["enum"])
        self.assertIn("claim_countercheck", stages)

        variants = schema["$defs"]["next_step"]["oneOf"]
        action_variants = {
            variant["properties"]["action"].get("const"):
            variant
            for variant in variants
            if "const" in variant.get("properties", {}).get("action", {})
        }
        for action in (
            "add_claim",
            "classify_candidate",
            "assess",
            "countercheck",
            "summarize",
            "repair_gate",
            "abort_source_transaction",
            "finish",
        ):
            self.assertIn(action, action_variants)
            required = set(action_variants[action]["required"])
            self.assertTrue(
                {"action", "cli_subcommand", "required_inputs", "why"}.issubset(
                    required
                )
            )
        assess = action_variants["assess"]
        self.assertIn("claim_id", assess["required"])
        self.assertIn("missing_evidence_purposes", assess["required"])

    def test_all_safe_file_inputs_have_schema_template_and_install_entry(self):
        expected = {
            "schemas/candidates.schema.json": "templates/candidates.json",
            "schemas/claim.schema.json": "templates/claim.json",
            "schemas/evidence.schema.json": "templates/evidence.json",
            "schemas/assessment.schema.json": "templates/assessment.json",
            "schemas/countercheck.schema.json": "templates/countercheck.json",
            "schemas/summary.schema.json": "templates/summary.json",
        }
        installer = load_installer()
        allowlist = set(installer.INSTALL_ALLOWLIST)
        missing_files = [
            relative
            for pair in expected.items()
            for relative in pair
            if not (SKILL_DIR / relative).is_file()
        ]
        self.assertEqual(missing_files, [])
        self.assertTrue(set(expected).issubset(allowlist))
        self.assertTrue(set(expected.values()).issubset(allowlist))

        candidates = read_json("templates/candidates.json")
        countercheck = read_json("templates/countercheck.json")
        summary = read_json("templates/summary.json")
        self.assertEqual(set(candidates), {"candidates"})
        self.assertEqual(
            set(countercheck),
            {"claim_id", "falsifier", "checked_source_ids", "result", "stop_reason"},
        )
        self.assertEqual(set(summary), {"unknowns", "next_action"})

    def test_runtime_owned_transaction_schema_is_installed_without_a_caller_template(self):
        installer = load_installer()
        allowlist = set(installer.INSTALL_ALLOWLIST)
        schema_path = "schemas/source-transaction.schema.json"
        self.assertTrue((SKILL_DIR / schema_path).is_file())
        self.assertIn(schema_path, allowlist)
        self.assertNotIn("templates/source-transaction.json", allowlist)
        schema = read_json(schema_path)
        self.assertEqual(
            set(schema["properties"]["status"]["enum"]),
            {
                "prepared",
                "artifacts_saved",
                "receipt_saved",
                "attested",
                "committed",
                "aborted",
            },
        )

    def test_installed_bundle_contains_every_v31_protocol_artifact(self):
        expected = {
            "schemas/candidates.schema.json",
            "schemas/claim.schema.json",
            "schemas/countercheck.schema.json",
            "schemas/evidence.schema.json",
            "schemas/source-transaction.schema.json",
            "schemas/summary.schema.json",
            "templates/candidates.json",
            "templates/countercheck.json",
            "templates/summary.json",
        }
        with tempfile.TemporaryDirectory() as tmp:
            target_root = Path(tmp) / "skills"
            installed = subprocess.run(
                [
                    sys.executable,
                    str(INSTALLER_PATH),
                    "--target-root",
                    str(target_root),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(installed.returncode, 0, installed.stderr)
            target = target_root / "auditing-ai-claims"
            missing = [relative for relative in sorted(expected) if not (target / relative).is_file()]
            self.assertEqual(missing, [])

    def test_openai_agent_metadata_is_accurate_and_does_not_claim_release(self):
        metadata = read("agents/openai.yaml")
        self.assertIn('display_name: "AI 主张审计"', metadata)
        self.assertIn("$auditing-ai-claims", metadata)
        self.assertIn("allow_implicit_invocation: true", metadata)
        self.assertNotIn("已发布", metadata)
        self.assertNotIn("绝对正确", metadata)


if __name__ == "__main__":
    unittest.main()
