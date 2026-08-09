from __future__ import annotations

import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class RuntimeLoopArchitectureContract(unittest.TestCase):
    def test_skill_is_a_compact_loop_dispatcher_not_a_prompt(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        body = text.split("---", 2)[-1]
        words = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]", body)
        self.assertLessEqual(len(words), 500)
        for command in ("start", "resume", "advance", "amend", "status", "decide"):
            self.assertIn(f"scripts/dpbp {command}", text)
        self.assertIn("references/runtime-loop.md", text)
        self.assertNotIn("万能提示词", text)

    def test_discovery_metadata_has_positive_and_negative_trigger_boundaries(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        description = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
        self.assertIsNotNone(description)
        value = description.group(1).lower()
        self.assertIn("use when", value)
        self.assertIn("not for", value)
        self.assertIn("translation", value)

    def test_runtime_loop_reference_and_install_contract_are_aligned(self) -> None:
        reference = ROOT / "references" / "runtime-loop.md"
        self.assertTrue(reference.is_file())
        text = reference.read_text(encoding="utf-8")
        for phase in ("awaiting_answers", "needs_reassessment", "ready_for_answer", "budget_exhausted"):
            self.assertIn(phase, text)
        manifest = json.loads((ROOT / "install-manifest.json").read_text(encoding="utf-8"))
        self.assertIn("references/runtime-loop.md", manifest["files"])
        self.assertNotIn("scripts/dpbp-evolve", manifest["files"], "maintainer evolution tooling must stay outside the lean install bundle")

    def test_evolution_workflow_is_source_only_and_auditable(self) -> None:
        self.assertTrue((ROOT / "scripts" / "dpbp-evolve").is_file())
        self.assertTrue((ROOT / "evals" / "suite-manifest.json").is_file())
        workflow = ROOT / "evals" / "evolution" / "README.md"
        self.assertTrue(workflow.is_file())
        text = workflow.read_text(encoding="utf-8")
        for term in ("failure_observed", "close-cycle", "promote", "sealed_holdout", "saturation"):
            self.assertIn(term, text)


if __name__ == "__main__":
    unittest.main()
