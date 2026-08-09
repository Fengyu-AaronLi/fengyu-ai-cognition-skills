#!/usr/bin/env python3
"""Round 154 RED: the declared loop edge must match runtime transition."""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SKILL_DIR.parents[1]
LOOP_PATH = SKILL_DIR / "scripts" / "improvement_loop.py"
WORKFLOW_PATH = REPO_ROOT / "workflows" / "separating-facts-loop.yaml"


def load_loop():
    spec = importlib.util.spec_from_file_location("round154_loop", LOOP_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load improvement loop")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Round154BackEdgeTruthRedTests(unittest.TestCase):
    def test_declared_back_edge_equals_the_next_round_first_step(self) -> None:
        loop = load_loop()
        snapshot = {"sha256": "a" * 64}
        iteration = loop.next_iteration(2, snapshot, [])
        policy = loop.parse_workflow_policy(WORKFLOW_PATH)
        self.assertEqual(
            f"loop_decision -> {iteration['next_step']}",
            policy["back_edge"],
        )


if __name__ == "__main__":
    unittest.main()
