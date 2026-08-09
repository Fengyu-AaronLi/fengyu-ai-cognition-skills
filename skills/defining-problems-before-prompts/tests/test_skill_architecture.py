from __future__ import annotations

import json
import os
import stat
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SkillArchitectureContract(unittest.TestCase):
    def test_runtime_assets_exist(self) -> None:
        required = [
            "scripts/dpbp",
            "schemas/request-envelope.schema.json",
            "schemas/problem-spec.schema.json",
            "schemas/problem-state.schema.json",
            "runtime/routes.json",
            "references/core.md",
            "references/high-risk.md",
            "references/field-semantics.md",
            "references/playbooks/ai-efficiency.md",
            "references/playbooks/ai-product.md",
            "references/playbooks/career-exit.md",
            "adapters/standalone-prompt.md",
        ]
        missing = [path for path in required if not (ROOT / path).is_file()]
        self.assertEqual([], missing, f"missing runtime assets: {missing}")

    def test_skill_is_a_progressive_dispatcher(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertLessEqual(
            len(skill.splitlines()),
            120,
            "SKILL.md should dispatch to runtime and references, not carry the whole policy",
        )
        for required in (
            "scripts/dpbp gate",
            "scripts/dpbp init",
            "scripts/dpbp validate",
            "scripts/dpbp render",
            "references/core.md",
            "resources",
            "gate_receipt",
            "expected_revision",
        ):
            self.assertIn(required, skill)
        self.assertNotIn("zero-threshold-prompt.md", skill)

    def test_cli_is_executable_and_offline_only(self) -> None:
        cli = ROOT / "scripts" / "dpbp"
        self.assertTrue(cli.is_file(), "scripts/dpbp does not exist")
        self.assertTrue(cli.stat().st_mode & stat.S_IXUSR, "scripts/dpbp is not executable")
        source = cli.read_text(encoding="utf-8")
        self.assertIn("runtime/routes.json", source)
        forbidden_imports = (
            "import requests",
            "import urllib",
            "import httpx",
            "import socket",
            "from requests",
            "from urllib",
        )
        for forbidden in forbidden_imports:
            self.assertNotIn(forbidden, source)

    def test_schemas_and_routes_are_valid_json(self) -> None:
        for relative in (
            "schemas/request-envelope.schema.json",
            "schemas/problem-spec.schema.json",
            "schemas/problem-state.schema.json",
            "runtime/routes.json",
        ):
            path = ROOT / relative
            self.assertTrue(path.is_file(), f"missing {relative}")
            with path.open(encoding="utf-8") as handle:
                parsed = json.load(handle)
            self.assertIsInstance(parsed, dict)

    def test_problem_dimensions_and_progressive_career_route_are_structural(self) -> None:
        spec_schema = json.loads(
            (ROOT / "schemas" / "problem-spec.schema.json").read_text(encoding="utf-8")
        )
        categories = {
            "desired_outcome",
            "current_bottleneck",
            "measurement_source",
            "target_user",
            "recurring_pain",
            "payment_evidence",
            "resources",
            "success_criteria",
            "financial_capacity",
            "alternatives",
            "health_status",
            "risk_tolerance",
            "decision_target",
            "other",
        }
        unknown_item = spec_schema["properties"]["decisive_unknowns"]["items"]
        self.assertIn("id", unknown_item["required"])
        self.assertIn("category", unknown_item["required"])
        self.assertEqual("^u[1-9][0-9]*$", unknown_item["properties"]["id"]["pattern"])
        self.assertEqual("\\S", unknown_item["properties"]["value"]["pattern"])
        self.assertEqual(categories, set(unknown_item["properties"]["category"]["enum"]))

        question_item = spec_schema["properties"]["questions"]["items"]
        self.assertIn("addresses", question_item["required"])
        self.assertEqual(1, question_item["properties"]["addresses"]["minItems"])
        self.assertEqual(
            "^u[1-9][0-9]*$",
            question_item["properties"]["addresses"]["items"]["pattern"],
        )
        self.assertEqual("\\S", question_item["properties"]["question"]["pattern"])

        self.assertIn("request_envelope", spec_schema["required"])
        self.assertIn("gate_receipt", spec_schema["required"])
        next_test = spec_schema["properties"]["next_test"]
        for field in ("action_type", "evidence_only", "solution_commitment"):
            self.assertIn(field, next_test["required"])
        self.assertEqual(
            {
                "evidence_collection",
                "solution_design",
                "implementation",
                "decision",
                "communication",
            },
            set(next_test["properties"]["action_type"]["enum"]),
        )

        state_schema = json.loads(
            (ROOT / "schemas" / "problem-state.schema.json").read_text(encoding="utf-8")
        )
        pending_item = state_schema["properties"]["pending_questions"]["items"]
        self.assertIn("addresses", pending_item["required"])

        routes = json.loads((ROOT / "runtime" / "routes.json").read_text(encoding="utf-8"))
        self.assertEqual(
            [
                "references/core.md",
                "references/high-risk.md",
                "references/playbooks/career-exit.md",
            ],
            routes["resources"]["defer_to_user"]["career"],
        )
        self.assertEqual(
            ["references/core.md", "references/high-risk.md"],
            routes["resources"]["defer_to_user"]["default"],
        )

    def test_prompt_bridge_is_explicitly_non_core(self) -> None:
        adapter = ROOT / "adapters" / "standalone-prompt.md"
        self.assertTrue(adapter.is_file(), "standalone prompt adapter is missing")
        text = adapter.read_text(encoding="utf-8")
        self.assertIn("兼容", text)
        self.assertIn("不是 Skill 本体", text)


if __name__ == "__main__":
    unittest.main()
