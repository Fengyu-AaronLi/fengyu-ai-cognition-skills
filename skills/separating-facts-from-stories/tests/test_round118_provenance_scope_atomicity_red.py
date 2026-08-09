from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
CASEFILE_PATH = SKILL_DIR / "scripts" / "casefile.py"
SPEC = importlib.util.spec_from_file_location("round118_casefile", CASEFILE_PATH)
assert SPEC is not None and SPEC.loader is not None
CASEFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CASEFILE)


class Round118ProvenanceScopeAtomicityRedTests(unittest.TestCase):
    def _artifact_with_only_first_observation(self, text: str) -> dict:
        artifact = CASEFILE.make_draft(text, "ROUND118-BLIND", "standard")
        recognized: list[tuple[dict, str]] = []
        for span in artifact["source_spans"]:
            semantic_text = CASEFILE._semantic_text_for_span(
                text, span, span["text"]
            )
            observation_type = CASEFILE.derive_observation_type(
                semantic_text, span
            )
            if observation_type is not None:
                recognized.append((span, observation_type))
        self.assertTrue(recognized, "fixture must contain one control observation")
        span, observation_type = recognized[0]

        artifact["claims"] = [
            {
                "id": "C1",
                "kind": "observable_fact",
                "observation_type": observation_type,
                "text": span["text"],
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "user_direct_observation",
                "exact_quote": span["text"],
                "epistemic_status": "reported",
                "diagnostic_boundary": False,
            }
        ]
        artifact["evidence"] = [
            {
                "id": "E1",
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": "user_direct_observation",
                "exact_quote": span["text"],
                "can_establish": ["C1"],
                "cannot_establish": [],
                "limitations": ["single_party_report"],
            }
        ]
        artifact["evidence_links"] = [
            {
                "proposition_id": "C1",
                "evidence_ref": "E1",
                "relation": "supports",
                "strength": "direct",
                "reason": "anchor_matches_report",
            }
        ]
        artifact["unknowns"] = [
            {
                "id": "U1",
                "unknown_type": "event_cause_or_context",
                "text": CASEFILE.UNKNOWN_CATALOG["event_cause_or_context"],
                "status": "open",
                "resolved_by_evidence_refs": [],
            }
        ]
        action = CASEFILE.ACTION_CATALOG["record_pattern"]
        artifact["actions"] = [
            {
                "id": "A1",
                "action_type": "record_pattern",
                "text": action["text"],
                "timing": action["timing"],
                "risk": action["risk"],
                "reversible": action["reversible"],
                "motive_independent": action["motive_independent"],
                "produces_new_evidence": action["produces_new_evidence"],
            }
        ]
        artifact["user_decisions"] = ["communication_boundary"]
        return artifact

    @staticmethod
    def _error_codes(artifact: dict) -> set[str]:
        return {item["code"] for item in CASEFILE.validate_casefile(artifact)}

    def test_users_quoted_current_feeling_is_not_owned_by_the_recipient(self):
        text = "我回复了消息。我现在对老板说：“我很害怕。”"
        artifact = self._artifact_with_only_first_observation(text)

        self.assertIn(
            "EXPLICIT_FEELING_CLAIM_MISSING",
            self._error_codes(artifact),
            "the recipient in ‘我对老板说’ must not become the quote speaker; "
            "the user's current first-person feeling must remain required",
        )

    def test_first_person_judgment_after_comma_ends_prior_hearsay_scope(self):
        text = (
            "我回复了消息。"
            "同事说老板要开除我，但我认为，他只是故意吓我。"
        )
        artifact = self._artifact_with_only_first_observation(text)
        story_span = next(
            span
            for span in artifact["source_spans"]
            if span["text"] == "他只是故意吓我。"
        )

        self.assertNotEqual(
            "secondhand",
            CASEFILE._expected_source_type_for_span(story_span),
            "‘我认为，’ owns its complement and must reset the preceding "
            "colleague-report scope",
        )
        self.assertIn(
            "USER_STORY_CLAIM_MISSING",
            self._error_codes(artifact),
            "once ownership is correct, omitting the user's own motive story "
            "must fail validation",
        )

    def test_meta_negation_does_not_assert_the_denied_motive_story(self):
        artifact = self._artifact_with_only_first_observation(
            "我回复了消息。这不等于他故意排挤我。"
        )

        self.assertNotIn(
            "USER_STORY_CLAIM_MISSING",
            self._error_codes(artifact),
            "‘不等于’ governs the embedded motive proposition and must not "
            "turn it into the user's asserted story",
        )

    def test_only_if_scope_does_not_create_a_current_story_or_quote(self):
        cases = (
            (
                "我回复了消息。只有在他再次回复消息时，我才会认为他在乎我。",
                "USER_STORY_CLAIM_MISSING",
            ),
            (
                "我回复了消息。只有老板说：“我决定离开”，我才辞职。",
                "STATED_POSITION_CLAIM_MISSING",
            ),
        )
        for text, forbidden_code in cases:
            with self.subTest(text=text):
                artifact = self._artifact_with_only_first_observation(text)
                self.assertNotIn(
                    forbidden_code,
                    self._error_codes(artifact),
                    "a 只有…才 conditional neither asserts its embedded story "
                    "nor proves that the quoted speech act occurred",
                )

    def test_second_atomic_event_is_neither_dropped_nor_silently_ignored(self):
        text = "他回复了消息，而且他参加了会议。"
        artifact = CASEFILE.make_draft(text, "ROUND118-ATOMIC", "standard")
        second_span = next(
            span
            for span in artifact["source_spans"]
            if span["text"] == "而且他参加了会议。"
        )
        semantic_text = CASEFILE._semantic_text_for_span(
            text, second_span, second_span["text"]
        )
        observation_type = CASEFILE.derive_observation_type(
            semantic_text, second_span
        )
        pending_span_ids = {
            item["source_span_id"]
            for item in artifact["unclassified_observation_candidates"]
        }

        self.assertTrue(
            observation_type == "participation_or_schedule_event"
            or second_span["id"] in pending_span_ids,
            "the complete second event must reach either the finite fact "
            "grammar or the pending-observation channel",
        )


if __name__ == "__main__":
    unittest.main()
