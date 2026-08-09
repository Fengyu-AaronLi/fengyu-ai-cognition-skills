from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[1]
WORKFLOW = REPO_ROOT / "workflows" / "separating-facts-loop.yaml"
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import improvement_loop  # noqa: E402
import test_round29_improvement_loop_red as round29  # noqa: E402


EXPECTED_GRAPH = [
    {"id": "preflight_snapshot", "depends_on": []},
    {"id": "adversarial_review", "depends_on": ["preflight_snapshot"]},
    {"id": "red_green_fix", "depends_on": ["adversarial_review"]},
    {"id": "deterministic_gate", "depends_on": ["red_green_fix"]},
    {"id": "independent_recheck", "depends_on": ["deterministic_gate"]},
    {"id": "source_freeze", "depends_on": ["independent_recheck"]},
    {"id": "frozen_eval_prepare", "depends_on": ["source_freeze"]},
    {"id": "isolated_eval", "depends_on": ["frozen_eval_prepare"]},
    {"id": "eval_audit", "depends_on": ["isolated_eval"]},
    {"id": "clean_install", "depends_on": ["eval_audit"]},
    {"id": "rollback_validation", "depends_on": ["clean_install"]},
    {"id": "evidence_gate", "depends_on": ["rollback_validation"]},
    {"id": "loop_decision", "depends_on": ["evidence_gate"]},
]


class Round85WorkflowExecutionGraphRedTests(unittest.TestCase):
    """The controller must enforce the workflow DAG, not merely hash its prose."""

    def test_real_workflow_exposes_the_exact_execution_graph(self) -> None:
        policy = improvement_loop.parse_workflow_policy(WORKFLOW)
        self.assertEqual(EXPECTED_GRAPH, policy["execution_graph"])
        self.assertEqual(
            "loop_decision -> preflight_snapshot", policy["back_edge"]
        )

    def test_missing_wrong_dependency_and_cycle_fail_closed(self) -> None:
        original = WORKFLOW.read_text(encoding="utf-8")
        start = original.index("  - id: red_green_fix\n")
        end = original.index("  - id: deterministic_gate\n")
        variants = {
            "missing_step": original[:start] + original[end:],
            "wrong_dependency": original.replace(
                "  - id: red_green_fix\n"
                "    role: \"engineering/engineering-senior-developer\"\n"
                "    depends_on: [adversarial_review]",
                "  - id: red_green_fix\n"
                "    role: \"engineering/engineering-senior-developer\"\n"
                "    depends_on: [preflight_snapshot]",
                1,
            ),
            "cycle": original.replace(
                "  - id: red_green_fix\n"
                "    role: \"engineering/engineering-senior-developer\"\n"
                "    depends_on: [adversarial_review]",
                "  - id: red_green_fix\n"
                "    role: \"engineering/engineering-senior-developer\"\n"
                "    depends_on: [loop_decision]",
                1,
            ),
        }
        with tempfile.TemporaryDirectory(prefix="sffs-round85-graph-") as temp_dir:
            for name, text in variants.items():
                with self.subTest(name=name):
                    path = Path(temp_dir) / f"{name}.yaml"
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaises(improvement_loop.LoopError) as raised:
                        improvement_loop.parse_workflow_policy(path)
                    self.assertEqual(
                        "WORKFLOW_POLICY_INVALID", raised.exception.code
                    )

    def test_start_persists_the_validated_execution_graph(self) -> None:
        helper = round29.Round29ImprovementLoopRedTests()
        with tempfile.TemporaryDirectory(prefix="sffs-round85-state-") as temp_dir:
            paths = helper.make_candidate(Path(temp_dir))
            state = helper.start(paths)
            self.assertEqual(EXPECTED_GRAPH, state["workflow_policy"]["execution_graph"])
            self.assertEqual(
                "preflight_snapshot",
                state["iterations"][0]["next_step"],
            )


if __name__ == "__main__":
    unittest.main()
