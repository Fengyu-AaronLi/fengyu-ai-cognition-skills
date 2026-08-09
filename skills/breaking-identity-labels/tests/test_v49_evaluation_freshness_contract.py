from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVALUATOR = ROOT / "evals" / "run_v2_evals.py"
RUNTIME = ROOT / "scripts" / "identity_label_case.py"
DATASETS = (
    "evals/heldout-cases.json",
    "evals/boundary-cases.json",
    "evals/cases.json",
    "evals/upgrade-cases.json",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class EvaluationFreshnessContractTests(unittest.TestCase):
    def expected_bindings(self) -> dict:
        return {
            "runtime_sha256": sha256(RUNTIME),
            "evaluator_sha256": sha256(EVALUATOR),
            "datasets": {
                relative: sha256(ROOT / relative)
                for relative in DATASETS
            },
        }

    def test_fresh_run_binds_runtime_evaluator_and_every_input_set(self) -> None:
        with tempfile.TemporaryDirectory(prefix="v49-eval-") as temporary:
            output = Path(temporary) / "results.json"
            result = subprocess.run(
                [sys.executable, str(EVALUATOR), "--output", str(output)],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(payload["artifact_bindings"], self.expected_bindings())

    def test_checked_in_result_is_bound_to_current_evaluation_candidate(self) -> None:
        payload = json.loads(
            (ROOT / "evals" / "v2-results.json").read_text(encoding="utf-8")
        )
        self.assertEqual(payload["artifact_bindings"], self.expected_bindings())


if __name__ == "__main__":
    unittest.main()
