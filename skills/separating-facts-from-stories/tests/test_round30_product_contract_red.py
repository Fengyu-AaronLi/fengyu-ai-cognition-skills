import copy
import importlib.util
import json
import re
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
CASEFILE_SCRIPT = SKILL_DIR / "scripts" / "casefile.py"
SCHEMA_PATH = SKILL_DIR / "schemas" / "casefile.schema.json"


def load_casefile_module():
    spec = importlib.util.spec_from_file_location(
        "round30_product_casefile", CASEFILE_SCRIPT
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


casefile = load_casefile_module()


UNCLASSIFIED_OBSERVATIONS = (
    "他昨天把杯子摔碎了。",
    "她今天没有来上班。",
    "老板把我的任务交给了同事。",
    "他连续三天很晚回家。",
    "我看到他和同事一起吃饭。",
    "系统里我的名字不见了。",
    "他把我们的合照从主页撤下了。",
)


def human_render_fixture() -> dict:
    """Small renderer fixture with deliberately visible machine audit fields."""
    return {
        "mode": "standard",
        "claims": [
            {
                "id": "C1",
                "kind": "observable_fact",
                "observation_type": "participation_or_schedule_event",
                "exact_quote": "老板连续两次没让我参加会议。",
                "source_ref": "input",
                "source_type": "user_direct_observation",
                "epistemic_status": "reported",
            },
            {
                "id": "C2",
                "kind": "interpretation",
                "exact_quote": "我认为他在架空我。",
                "source_ref": "input",
                "source_type": "user_report",
                "epistemic_status": "unverified",
            },
        ],
        "evidence": [
            {
                "id": "E1",
                "source_ref": "input",
                "source_type": "user_direct_observation",
                "exact_quote": "老板连续两次没让我参加会议。",
                "can_establish": ["C1"],
                "cannot_establish": ["C2"],
                "limitations": ["single_party_report", "limited_sample"],
            }
        ],
        "evidence_links": [
            {
                "proposition_id": "C1",
                "evidence_ref": "E1",
                "relation": "supports",
                "strength": "direct",
                "reason": "anchor_matches_report",
            },
            {
                "proposition_id": "C2",
                "evidence_ref": "E1",
                "relation": "does_not_establish",
                "strength": "none",
                "reason": "source_scope_limit",
            },
        ],
        "unknowns": [
            {
                "id": "U1",
                "text": "正式职责、参与范围或审批权限是否发生变化",
                "status": "open",
            }
        ],
        "hypotheses": [],
        "discriminator": {
            "question": "我目前的正式职责、决策参与范围或审批权限是否发生变化？"
        },
        "actions": [{"id": "A1", "action_type": "neutral_check"}],
        "user_decisions": ["employment_continuation"],
    }


class Round30ProductContractRedTests(unittest.TestCase):
    def test_human_response_hides_machine_ids_and_audit_codes(self) -> None:
        artifact = human_render_fixture()
        before = copy.deepcopy(artifact)

        response = casefile.render_markdown(artifact)

        # Machine identifiers and enum/reason codes belong in casefile.json,
        # never in the human-facing response.md.
        self.assertIsNone(
            re.search(r"(?<![A-Za-z0-9_])(?:C|E|H|U|SP)[0-9]+(?![A-Za-z0-9_])", response),
            response,
        )
        for internal_token in (
            "does_not_establish",
            "source_scope_limit",
            "anchor_matches_report",
            "user_direct_observation",
            "user_report",
            "single_party_report",
            "limited_sample",
            "reported",
            "unverified",
        ):
            with self.subTest(internal_token=internal_token):
                self.assertNotIn(internal_token, response)

        # The human response keeps the actual meaning and uncertainty boundary.
        self.assertIn("老板连续两次没让我参加会议", response)
        self.assertIn("我认为他在架空我", response)
        self.assertIn("不能证明", response)

        # Rendering must not achieve privacy by deleting the audit trail.
        self.assertEqual(before, artifact)
        machine_audit = json.dumps(artifact, ensure_ascii=False, sort_keys=True)
        for retained_token in (
            '"id": "C1"',
            '"id": "E1"',
            '"relation": "does_not_establish"',
            '"reason": "source_scope_limit"',
        ):
            with self.subTest(retained_token=retained_token):
                self.assertIn(retained_token, machine_audit)

    def test_schema_requires_a_machine_audited_unclassified_channel(self) -> None:
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        field = "unclassified_observation_candidates"

        self.assertIn(field, schema.get("required", []))
        self.assertIn(field, schema.get("properties", {}))

    def test_make_draft_retains_seven_unclassified_daily_observations(self) -> None:
        for index, text in enumerate(UNCLASSIFIED_OBSERVATIONS, start=1):
            with self.subTest(text=text):
                self.assertIsNone(casefile.derive_observation_type(text))
                draft = casefile.make_draft(
                    text, f"round30-unclassified-{index}", "standard"
                )
                candidates = draft.get("unclassified_observation_candidates", [])
                self.assertEqual(1, len(candidates), draft)

                candidate = candidates[0]
                self.assertEqual("OC1", candidate.get("id"))
                self.assertEqual("I1", candidate.get("input_id"))
                self.assertEqual("input", candidate.get("source_ref"))
                self.assertEqual(text, candidate.get("exact_quote"))
                self.assertEqual(
                    "pending_confirmation", candidate.get("status")
                )
                self.assertEqual(
                    "finite_observation_grammar_no_match",
                    candidate.get("reason"),
                )
                bound_span = next(
                    (
                        span
                        for span in draft["source_spans"]
                        if span["id"] == candidate.get("source_span_id")
                    ),
                    None,
                )
                self.assertIsNotNone(bound_span)
                self.assertEqual(bound_span["text"], candidate["exact_quote"])
                self.assertFalse(
                    any(
                        claim.get("kind") == "observable_fact"
                        for claim in draft["claims"]
                    )
                )

    def test_observation_plus_story_tail_preserves_only_observation_candidate(self) -> None:
        text = "我看到他和同事一起吃饭，所以他一定出轨了。"
        draft = casefile.make_draft(text, "round30-story-tail", "standard")
        candidates = draft.get("unclassified_observation_candidates", [])

        self.assertEqual(1, len(candidates), draft)
        candidate = candidates[0]
        self.assertIn("我看到他和同事一起吃饭", candidate.get("exact_quote", ""))
        self.assertNotIn("出轨", candidate.get("exact_quote", ""))
        bound_span = next(
            (
                span
                for span in draft["source_spans"]
                if span["id"] == candidate.get("source_span_id")
            ),
            None,
        )
        self.assertIsNotNone(bound_span)
        self.assertEqual(bound_span["text"], candidate["exact_quote"])
        self.assertIn(
            "USER_STORY_CLAIM_MISSING",
            {item["code"] for item in casefile.validate_casefile(draft)},
        )

    def test_candidate_binding_is_validated_as_part_of_casefile_audit(self) -> None:
        draft = casefile.make_draft(
            UNCLASSIFIED_OBSERVATIONS[0], "round30-binding", "standard"
        )
        candidates = draft.get("unclassified_observation_candidates", [])
        self.assertEqual(1, len(candidates), draft)

        good_errors = casefile.validate_casefile(draft)
        self.assertFalse(
            any(
                item["code"] == "SOURCE_SPAN_MISMATCH"
                and item["path"].startswith(
                    "/unclassified_observation_candidates/"
                )
                for item in good_errors
            ),
            good_errors,
        )

        tampered = copy.deepcopy(draft)
        tampered["unclassified_observation_candidates"][0]["exact_quote"] = (
            "用户从未说过的事件"
        )
        bad_errors = casefile.validate_casefile(tampered)
        self.assertTrue(
            any(
                item["code"] == "SOURCE_SPAN_MISMATCH"
                and item["path"].startswith(
                    "/unclassified_observation_candidates/"
                )
                for item in bad_errors
            ),
            bad_errors,
        )

    def test_candidate_is_visible_as_pending_but_not_rendered_as_fact(self) -> None:
        text = UNCLASSIFIED_OBSERVATIONS[0]
        draft = casefile.make_draft(text, "round30-visible-pending", "standard")
        self.assertEqual(
            1, len(draft.get("unclassified_observation_candidates", [])), draft
        )

        response = casefile.render_markdown(draft)
        self.assertIn("## 1B. 待确认的观察（未进入事实层）", response)
        self.assertIn(text, response)
        fact_section = response.split("## 1. 可观察事实", maxsplit=1)[1].split(
            "## 1A.", maxsplit=1
        )[0]
        self.assertNotIn(text, fact_section)
        self.assertNotIn("OC1", response)
        self.assertNotIn("finite_observation_grammar_no_match", response)

    def test_recognized_observation_is_not_duplicated_as_pending(self) -> None:
        text = "她发来消息。"
        self.assertIsNotNone(casefile.derive_observation_type(text))
        draft = casefile.make_draft(text, "round30-recognized-control", "standard")
        self.assertEqual([], draft.get("unclassified_observation_candidates", []))


if __name__ == "__main__":
    unittest.main()
