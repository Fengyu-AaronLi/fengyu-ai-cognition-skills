from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
CASEFILE = SKILL_DIR / "scripts" / "casefile.py"


def load_casefile():
    spec = importlib.util.spec_from_file_location("round33_casefile", CASEFILE)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


casefile = load_casefile()


NON_ASSERTED_OBSERVATION_SURFACES = (
    "我猜他昨天把杯子摔碎了。",
    "他昨天可能把杯子摔碎了。",
    "也许他昨天把杯子摔碎了。",
    "假设他昨天把杯子摔碎了。",
    "他昨天把杯子摔碎了吗。",
    "请记录他昨天把杯子摔碎了。",
    "> 他昨天把杯子摔碎了。",
    "我很震惊他昨天把杯子摔碎了。",
)


def add_candidate_only_completion_fields(draft: dict) -> None:
    draft["unknowns"] = [
        {
            "id": "U1",
            "unknown_type": "event_cause_or_context",
            "text": casefile.UNKNOWN_CATALOG["event_cause_or_context"],
            "status": "open",
            "resolved_by_evidence_refs": [],
        }
    ]
    action = dict(casefile.ACTION_CATALOG["neutral_check"])
    action.pop("modes")
    draft["actions"] = [
        {"id": "A1", "action_type": "neutral_check", **action}
    ]
    draft["user_decisions"] = ["evidence_threshold"]


class Round33CandidateLifecycleRedTests(unittest.TestCase):
    def test_nonasserted_or_transformed_text_never_becomes_pending_observation(self) -> None:
        for index, text in enumerate(NON_ASSERTED_OBSERVATION_SURFACES, start=1):
            with self.subTest(text=text):
                draft = casefile.make_draft(text, f"round33-scope-{index}", "standard")
                self.assertEqual(
                    [],
                    draft["unclassified_observation_candidates"],
                    "a pending observation needs a present, asserted event report",
                )

    def test_candidate_only_case_has_a_valid_non_fact_completion_state(self) -> None:
        text = "他昨天把杯子摔碎了。"
        draft = casefile.make_draft(text, "round33-candidate-only", "standard")
        self.assertEqual(1, len(draft["unclassified_observation_candidates"]))
        add_candidate_only_completion_fields(draft)

        errors = casefile.validate_casefile(draft)
        self.assertEqual([], errors)
        response = casefile.render_markdown(draft)
        self.assertIn("待确认的观察（未进入事实层）", response)
        self.assertIn(text, response)
        fact_section = response.split("## 1. 可观察事实", 1)[1].split(
            "## 1A.", 1
        )[0]
        self.assertNotIn(text, fact_section)

    def test_historical_pending_candidate_is_not_presented_as_current_after_update(self) -> None:
        first = casefile.make_draft(
            "他昨天把杯子摔碎了。", "round33-history", "standard"
        )
        add_candidate_only_completion_fields(first)
        self.assertEqual([], casefile.validate_casefile(first))

        second = casefile.start_update(first, "刚才那句是虚构测试，不是现实事件。")
        response = casefile.render_markdown(second)
        pending_section = response.split(
            "## 1B. 待确认的观察（未进入事实层）", 1
        )[1].split("## 2.", 1)[0]
        self.assertNotIn("他昨天把杯子摔碎了", pending_section)


if __name__ == "__main__":
    unittest.main()
