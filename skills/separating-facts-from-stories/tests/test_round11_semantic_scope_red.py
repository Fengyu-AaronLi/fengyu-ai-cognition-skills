import sys
import unittest
from pathlib import Path

from test_casefile import valid_standard

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import casefile  # noqa: E402
sys.path.pop(0)


class Round11SemanticScopeRedTests(unittest.TestCase):
    def codes(self, artifact):
        return {item["code"] for item in casefile.validate_casefile(artifact)}

    def claim_case(self, text, anchor, kind, source_type):
        artifact = casefile.make_draft(text, "round11-semantic", "standard")
        span = next(
            item
            for item in artifact["source_spans"]
            if item["text"] == anchor and item["quoted"] == (source_type == "direct_quote")
        )
        observation_type = (
            casefile.derive_observation_type(span["text"], span)
            if kind == "observable_fact"
            else None
        )
        artifact["claims"] = [
            {
                "id": "C1",
                "kind": kind,
                "observation_type": observation_type,
                "text": span["text"],
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": source_type,
                "exact_quote": span["text"],
                "epistemic_status": (
                    "reported" if kind == "observable_fact" else "directly_stated"
                ),
                "diagnostic_boundary": False,
            }
        ]
        limitations = ["single_party_report"]
        if source_type == "secondhand":
            limitations.append("secondhand")
        artifact["evidence"] = [
            {
                "id": "E1",
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "source_type": source_type,
                "exact_quote": span["text"],
                "can_establish": ["C1"],
                "cannot_establish": [],
                "limitations": limitations,
            }
        ]
        artifact["evidence_links"] = [
            {
                "proposition_id": "C1",
                "evidence_ref": "E1",
                "relation": "supports",
                "strength": "direct",
                "reason": (
                    "direct_current_statement_only"
                    if kind == "stated_position"
                    else "anchor_matches_report"
                ),
            }
        ]
        baseline = valid_standard()
        artifact["unknowns"] = baseline["unknowns"]
        artifact["actions"] = baseline["actions"]
        artifact["user_decisions"] = baseline["user_decisions"]
        return artifact

    def test_question_suffix_cannot_be_cut_off_from_an_observation(self):
        spans = casefile.generate_source_spans("I1", "老板取消了会议吗？")
        self.assertFalse(
            any(
                casefile.derive_observation_type(item["text"], item) is not None
                for item in spans
            ),
            spans,
        )

    def test_truth_denial_cannot_be_cut_off_from_an_observation(self):
        spans = casefile.generate_source_spans(
            "I1", "老板取消了会议并不属实。"
        )
        self.assertFalse(
            any(
                casefile.derive_observation_type(item["text"], item) is not None
                for item in spans
            ),
            spans,
        )

    def test_unquoted_report_inherits_secondhand_provenance_structurally(self):
        artifact = self.claim_case(
            "老婆告诉我，老板取消了会议。",
            "老板取消了会议。",
            "observable_fact",
            "user_direct_observation",
        )
        span = next(
            item for item in artifact["source_spans"] if item["text"] == "老板取消了会议。"
        )
        self.assertEqual("secondhand", casefile._expected_source_type_for_span(span))
        self.assertIn("SOURCE_TYPE_MISMATCH", self.codes(artifact))

    def test_denied_question_proxy_and_superseded_quotes_are_not_current_positions(self):
        examples = (
            ("他说的不是“我会留下”，而是“我明天就走”。", "我会留下"),
            ("他问了一句：“我会留下”。", "我会留下"),
            ("老板读出前任的原话：“我会留下”。", "我会留下"),
            ("他说“我会留下”。随后他改口了。", "我会留下"),
        )
        for text, quote in examples:
            with self.subTest(text=text):
                artifact = self.claim_case(
                    text,
                    quote,
                    "stated_position",
                    "direct_quote",
                )
                self.assertTrue(
                    {
                        "DIRECT_QUOTE_NOT_ASSERTED",
                        "DIRECT_QUOTE_SUPERSEDED",
                        "SOURCE_TYPE_MISMATCH",
                    }
                    & self.codes(artifact)
                )

    def test_story_prediction_and_speculation_inside_quotes_are_not_positions(self):
        examples = (
            "老板取消会议就是为了报复我",
            "老板下周一定会开除我",
            "老板取消了会议",
        )
        frames = (
            "他说：“老板取消会议就是为了报复我”。",
            "他说：“老板下周一定会开除我”。",
            "他猜测：“老板取消了会议”。",
        )
        for text, quote in zip(frames, examples):
            with self.subTest(text=text):
                spans = casefile.generate_source_spans("I1", text)
                if not any(
                    item["quoted"] and item["text"] == quote
                    for item in spans
                ):
                    continue
                artifact = self.claim_case(
                    text,
                    quote,
                    "stated_position",
                    "direct_quote",
                )
                self.assertTrue(
                    {"STATED_POSITION_TYPE_UNSUPPORTED", "DIRECT_QUOTE_NOT_ASSERTED"}
                    & self.codes(artifact)
                )

    def test_bounded_current_commitment_remains_a_stated_position(self):
        artifact = self.claim_case(
            "他回答：“我会留下。”",
            "我会留下。",
            "stated_position",
            "direct_quote",
        )
        self.assertEqual([], casefile.validate_casefile(artifact))


if __name__ == "__main__":
    unittest.main()
