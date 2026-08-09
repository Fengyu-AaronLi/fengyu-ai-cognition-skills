from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
RUNNER_PATH = SKILL_DIR / "scripts" / "run_evals.py"


def load_runner():
    spec = importlib.util.spec_from_file_location("round69_run_evals", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load run_evals.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class Round69EvalExecutionIdentityRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.runner = load_runner()

    def environment(self, index: int) -> dict[str, str]:
        return {
            "runner": f"/root/eval-v30-{index:02d}",
            "model": "OpenAI Codex agent; exact backend identifier unavailable",
            "isolation": self.runner.EXPECTED_ISOLATION,
            "reasoning_effort": "inherited; exact setting unavailable",
            "execution_id": f"eval-v30-{index:02d}",
        }

    def test_environment_requires_execution_id_and_reasoning_effort(self) -> None:
        environment = self.environment(1)
        self.assertEqual([], self.runner.model_environment_errors(environment))
        for missing in ("execution_id", "reasoning_effort"):
            with self.subTest(missing=missing):
                incomplete = dict(environment)
                incomplete.pop(missing)
                codes = {
                    item["code"]
                    for item in self.runner.model_environment_errors(incomplete)
                }
                self.assertIn("MODEL_ENVIRONMENT_MISSING", codes)

    def test_all_cases_require_distinct_runner_and_execution_id(self) -> None:
        records = [
            {"case_id": f"case-{index:02d}", "model_environment": self.environment(index)}
            for index in range(18)
        ]
        expected = {item["case_id"] for item in records}
        self.assertEqual(
            [], self.runner.execution_identity_errors(records, expected)
        )

        records[17]["model_environment"]["execution_id"] = records[0][
            "model_environment"
        ]["execution_id"]
        records[16]["model_environment"]["runner"] = records[1][
            "model_environment"
        ]["runner"]
        codes = {
            item["code"]
            for item in self.runner.execution_identity_errors(records, expected)
        }
        self.assertEqual(
            {"MODEL_EXECUTION_ID_REUSED", "MODEL_RUNNER_REUSED"}, codes
        )

    def test_missing_case_identity_makes_the_suite_incomplete(self) -> None:
        records = [
            {"case_id": "case-a", "model_environment": self.environment(1)}
        ]
        codes = {
            item["code"]
            for item in self.runner.execution_identity_errors(
                records, {"case-a", "case-b"}
            )
        }
        self.assertIn("MODEL_EXECUTION_LEDGER_INCOMPLETE", codes)


if __name__ == "__main__":
    unittest.main()
