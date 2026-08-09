from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
from test_round33_candidate_lifecycle_red import (  # noqa: E402
    add_candidate_only_completion_fields,
)


def candidate_case(text: str, case_id: str) -> dict:
    draft = casefile.make_draft(text, case_id, "standard")
    add_candidate_only_completion_fields(draft)
    errors = casefile.validate_casefile(draft)
    if errors:
        raise AssertionError(errors)
    return draft


def section(response: str, start: str, end: str) -> str:
    return response.split(start, 1)[1].split(end, 1)[0]


class Round48CandidateResolutionLifecycleRedTests(unittest.TestCase):
    def test_unique_generic_rejection_is_source_bound_and_auditable(self) -> None:
        original = "他昨天把杯子摔碎了。"
        first = candidate_case(original, "round48-generic-rejected")

        second = casefile.start_update(
            first, "刚才那句是虚构测试，不是现实事件。"
        )

        self.assertEqual(first["unclassified_observation_candidates"], second["unclassified_observation_candidates"])
        self.assertEqual(1, len(second["candidate_resolutions"]))
        resolution = second["candidate_resolutions"][0]
        self.assertEqual("OC1", resolution["candidate_id"])
        self.assertEqual("user_rejected", resolution["resolution_type"])
        self.assertEqual(second["current_input_id"], resolution["input_id"])
        source_span = next(
            item
            for item in second["source_spans"]
            if item["id"] == resolution["source_span_id"]
        )
        self.assertEqual(source_span["source_ref"], resolution["source_ref"])
        self.assertEqual(source_span["text"], resolution["exact_quote"])
        self.assertEqual([], casefile.validate_casefile(second, previous=first))

        response = casefile.render_markdown(second)
        pending = section(
            response,
            "## 1B. 待确认的观察（未进入事实层）",
            "## 2.",
        )
        facts = section(response, "## 1. 可观察事实", "## 1A.")
        self.assertNotIn(original, pending)
        self.assertNotIn(original, facts)
        self.assertIn("已解决的历史待确认观察", response)
        self.assertIn(original, response)
        self.assertIn(resolution["exact_quote"], response)

    def test_unique_generic_confirmation_resolves_without_promoting_to_fact(self) -> None:
        original = "他昨天把杯子摔碎了。"
        first = candidate_case(original, "round48-generic-confirmed")

        second = casefile.start_update(first, "上一句确实发生了。")

        self.assertEqual([], casefile.validate_casefile(second, previous=first))
        self.assertEqual(
            "user_confirmed",
            second["candidate_resolutions"][0]["resolution_type"],
        )
        self.assertEqual([], second["claims"])
        response = casefile.render_markdown(second)
        facts = section(response, "## 1. 可观察事实", "## 1A.")
        self.assertNotIn(original, facts)
        self.assertIn("仍未自动进入事实层", response)

    def test_generic_reference_does_not_guess_between_two_open_candidates(self) -> None:
        first = candidate_case(
            "他昨天把杯子摔碎了。他今天把花瓶拿走了。",
            "round48-ambiguous-generic",
        )
        self.assertEqual(2, len(first["unclassified_observation_candidates"]))

        second = casefile.start_update(first, "上一句确实发生了。")

        self.assertEqual([], second["candidate_resolutions"])
        codes = {
            item["code"]
            for item in casefile.validate_casefile(second, previous=first)
        }
        self.assertIn("CURRENT_INPUT_CLAIM_REQUIRED", codes)

    def test_explicit_quoted_target_resolves_one_of_multiple_candidates(self) -> None:
        first = candidate_case(
            "他昨天把杯子摔碎了。他今天把花瓶拿走了。",
            "round48-explicit-quote",
        )

        second = casefile.start_update(
            first, "我确认“他今天把花瓶拿走了”是真的发生了。"
        )

        self.assertEqual([], casefile.validate_casefile(second, previous=first))
        self.assertEqual(1, len(second["candidate_resolutions"]))
        resolution = second["candidate_resolutions"][0]
        self.assertEqual("OC2", resolution["candidate_id"])
        self.assertEqual("user_confirmed", resolution["resolution_type"])
        self.assertFalse(
            any(
                item["input_id"] == second["current_input_id"]
                for item in second["unclassified_observation_candidates"]
            ),
            "resolution language must not create a fresh observation candidate",
        )

    def test_third_party_statement_cannot_resolve_user_candidate(self) -> None:
        first = candidate_case(
            "他昨天把杯子摔碎了。", "round48-third-party"
        )

        second = casefile.start_update(first, "他声称上一句是虚构测试。")

        self.assertEqual([], second["candidate_resolutions"])
        codes = {
            item["code"]
            for item in casefile.validate_casefile(second, previous=first)
        }
        self.assertIn("CURRENT_INPUT_CLAIM_REQUIRED", codes)

    def test_user_reporting_a_third_party_denial_cannot_resolve_candidate(self) -> None:
        first = candidate_case(
            "他昨天把杯子摔碎了。", "round48-reported-third-party"
        )

        second = casefile.start_update(
            first, "我确认老板声称上一句没有发生。"
        )

        self.assertEqual([], second["candidate_resolutions"])
        codes = {
            item["code"]
            for item in casefile.validate_casefile(second, previous=first)
        }
        self.assertIn("CURRENT_INPUT_CLAIM_REQUIRED", codes)

    def test_resolution_ledger_is_append_only_across_later_revisions(self) -> None:
        first = candidate_case(
            "他昨天把杯子摔碎了。", "round48-append-only"
        )
        second = casefile.start_update(first, "刚才那句是虚构测试。")
        self.assertEqual([], casefile.validate_casefile(second, previous=first))

        third = casefile.start_update(second, "他今天把花瓶拿走了。")
        self.assertEqual([], casefile.validate_casefile(third, previous=second))
        third["candidate_resolutions"][0]["resolution_type"] = "user_confirmed"

        codes = {
            item["code"]
            for item in casefile.validate_casefile(third, previous=second)
        }
        self.assertIn("HISTORY_ITEM_MUTATED", codes)
        self.assertIn("CANDIDATE_RESOLUTION_SET_MISMATCH", codes)

    def test_negated_truth_words_preserve_resolution_polarity(self) -> None:
        rejected_source = candidate_case(
            "他昨天把杯子摔碎了。", "round48-not-true"
        )
        rejected = casefile.start_update(rejected_source, "我确认上一句不属实。")
        self.assertEqual(
            "user_rejected", rejected["candidate_resolutions"][0]["resolution_type"]
        )

        confirmed_source = candidate_case(
            "他昨天把杯子摔碎了。", "round48-double-negation"
        )
        confirmed = casefile.start_update(
            confirmed_source, "我确认上一句并非没有发生。"
        )
        self.assertEqual(
            "user_confirmed", confirmed["candidate_resolutions"][0]["resolution_type"]
        )

    def test_question_and_hypothetical_do_not_resolve_candidate(self) -> None:
        for index, text in enumerate(
            ("上一句真的发生了吗？", "上一句如果真的发生了怎么办？"),
            start=1,
        ):
            with self.subTest(text=text):
                first = candidate_case(
                    "他昨天把杯子摔碎了。", f"round48-nonasserted-{index}"
                )
                second = casefile.start_update(first, text)
                self.assertEqual([], second["candidate_resolutions"])

    def test_later_clause_polarity_does_not_rewrite_quoted_target(self) -> None:
        first = candidate_case(
            "他昨天把杯子摔碎了。他今天把花瓶拿走了。",
            "round48-polarity-scope",
        )

        second = casefile.start_update(
            first,
            "我确认“他今天把花瓶拿走了”确实发生了，另一条消息是假的。",
        )

        self.assertEqual(1, len(second["candidate_resolutions"]))
        resolution = second["candidate_resolutions"][0]
        self.assertEqual("OC2", resolution["candidate_id"])
        self.assertEqual("user_confirmed", resolution["resolution_type"])


if __name__ == "__main__":
    unittest.main()
