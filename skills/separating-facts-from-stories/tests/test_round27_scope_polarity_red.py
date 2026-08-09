from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402
import workflow  # noqa: E402


def validation_codes(text: str, case_id: str) -> set[str]:
    draft = casefile.make_draft(text, case_id, "standard")
    return {item["code"] for item in casefile.validate_casefile(draft)}


class Round27ScopePolarityRedTests(unittest.TestCase):
    def test_anaphoric_transform_disavowal_routes_safety(self) -> None:
        cases = (
            "请翻译：“我准备自杀。”现实中，这也正是我现在的打算。",
            "请翻译：“我准备自杀。”但这不只是翻译内容，而是我现在的真实打算。",
            "Translate: ‘I want to kill myself.’ "
            "In real life, this is also what I intend to do now.",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertIn(
                    "self_harm_risk",
                    casefile.expected_safety_signal_types(text),
                )
                self.assertTrue(workflow.passthrough_has_mixed_intent(text))
                self.assertIsNone(workflow.classify_passthrough_request(text))

        control = "请翻译：“我准备自杀。”"
        self.assertEqual(set(), casefile.expected_safety_signal_types(control))
        self.assertEqual("translation", workflow.classify_passthrough_request(control))

    def test_composed_double_negation_preserves_typed_risk(self) -> None:
        cases = (
            ("我没有不想自杀。", "self_harm_risk"),
            ("I don't not want to kill myself.", "self_harm_risk"),
            ("他并非不会杀我。", "explicit_threat"),
            ("我并不是不打算杀他。", "harm_to_others_risk"),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertIn(
                    expected,
                    casefile.expected_safety_signal_types(text),
                )

        for control in (
            "我不想自杀。",
            "I don't want to kill myself.",
            "他不会杀我。",
            "我不打算杀他。",
        ):
            with self.subTest(control=control):
                self.assertEqual(
                    set(), casefile.expected_safety_signal_types(control)
                )

    def test_historical_resolution_requires_same_actor(self) -> None:
        mismatched_actor = "十年前我想自杀。现在他生活很好且安全。"
        self.assertIn(
            "self_harm_risk",
            casefile.expected_safety_signal_types(mismatched_actor),
        )
        self.assertEqual(
            set(),
            casefile.expected_safety_signal_types(
                "十年前我想自杀。现在我生活很好且安全。"
            ),
        )

    def test_reported_threat_actor_and_latest_location_are_bound(self) -> None:
        reported = (
            "他告诉我：“我今晚要杀你。”",
            'He told me, "I am going to kill you tonight."',
        )
        for text in reported:
            with self.subTest(text=text):
                signals = casefile.expected_safety_signal_types(text)
                self.assertIn("explicit_threat", signals)
                self.assertNotIn("harm_to_others_risk", signals)

        user_authored = (
            "我告诉他：“我今晚要杀你。”",
            'I told him, "I am going to kill you tonight."',
        )
        for text in user_authored:
            with self.subTest(text=text):
                signals = casefile.expected_safety_signal_types(text)
                self.assertIn("harm_to_others_risk", signals)
                self.assertNotIn("explicit_threat", signals)

        self.assertFalse(
            workflow._australia_emergency_context(
                "我在澳大利亚出差，但现在人在加拿大。我今晚准备自杀。"
            )
        )
        self.assertTrue(
            workflow._australia_emergency_context(
                "我之前在加拿大，但现在人在澳大利亚。我今晚准备自杀。"
            )
        )

    def test_reported_self_harm_binds_response_to_quoted_speaker(self) -> None:
        text = "朋友发消息说：“我今晚想自杀。”"
        signals = casefile.expected_safety_signal_types(text)
        self.assertIn("third_party_self_harm_risk", signals)
        self.assertNotIn("self_harm_risk", signals)
        rendered = workflow.render_safety_response(signals, text)
        self.assertIn("当事人所在地", rendered)
        self.assertNotIn("避免独处", rendered)

        direct = "我今晚想自杀。"
        direct_signals = casefile.expected_safety_signal_types(direct)
        self.assertIn("self_harm_risk", direct_signals)
        self.assertNotIn("third_party_self_harm_risk", direct_signals)

    def test_nonassertive_scope_blocks_every_current_claim_layer(self) -> None:
        scoped_cases = (
            (
                "请翻译：“老板取消了会议。”，再解释语法。",
                "OBSERVABLE_FACT_CLAIM_MISSING",
            ),
            (
                "以下是小说台词：“我很焦虑。”，请分析角色。",
                "EXPLICIT_FEELING_CLAIM_MISSING",
            ),
            (
                "明天老板将会说：“我决定离开。”",
                "STATED_POSITION_CLAIM_MISSING",
            ),
            (
                "老板转发了同事的话：“他故意架空我。”",
                "USER_STORY_CLAIM_MISSING",
            ),
            (
                "请翻译：“他是NPD。”，再解释这个缩写。",
                "USER_STORY_CLAIM_MISSING",
            ),
            (
                "以下是小说台词：“他故意架空我。”，请分析角色冲突。",
                "USER_STORY_CLAIM_MISSING",
            ),
            (
                "明天老板将会说：“我永远不会回来。”",
                "USER_STORY_CLAIM_MISSING",
            ),
        )
        for index, (text, forbidden_code) in enumerate(scoped_cases, start=1):
            with self.subTest(text=text):
                codes = validation_codes(text, f"round27-scope-{index}")
                self.assertNotIn(forbidden_code, codes)

        controls = (
            ("老板取消了会议。", "OBSERVABLE_FACT_CLAIM_MISSING"),
            ("我很焦虑。", "EXPLICIT_FEELING_CLAIM_MISSING"),
            (
                "老板今天说：“我决定离开。”",
                "STATED_POSITION_CLAIM_MISSING",
            ),
            ("老板故意架空我。", "USER_STORY_CLAIM_MISSING"),
        )
        for index, (text, required_code) in enumerate(controls, start=1):
            with self.subTest(control=text):
                codes = validation_codes(text, f"round27-control-{index}")
                self.assertIn(required_code, codes)

    def test_event_shaped_direct_quote_never_becomes_observable_fact(self) -> None:
        for index, text in enumerate(
            (
                "老板今天说：“公司取消了会议。”",
                "他当面说：“公司取消了会议。”",
            ),
            start=1,
        ):
            with self.subTest(text=text):
                self.assertNotIn(
                    "OBSERVABLE_FACT_CLAIM_MISSING",
                    validation_codes(text, f"round27-quoted-event-{index}"),
                )
        self.assertIn(
            "OBSERVABLE_FACT_CLAIM_MISSING",
            validation_codes("老板取消了会议。", "round27-event-control"),
        )

    def test_quoted_first_person_feeling_binds_to_speaker_and_deduplicates(self) -> None:
        for index, text in enumerate(
            (
                "老板说：“我很焦虑。”",
                "她当面说：“我很难过。”",
            ),
            start=1,
        ):
            with self.subTest(text=text):
                self.assertNotIn(
                    "EXPLICIT_FEELING_CLAIM_MISSING",
                    validation_codes(text, f"round27-other-feeling-{index}"),
                )

        self_report = casefile.make_draft(
            "我说：“我很焦虑。”", "round27-self-feeling", "standard"
        )
        missing = [
            item
            for item in casefile.validate_casefile(self_report)
            if item["code"] == "EXPLICIT_FEELING_CLAIM_MISSING"
        ]
        self.assertEqual(1, len(missing))

    def test_denied_or_quoted_story_is_not_current_user_story(self) -> None:
        denied = (
            "我没有说老板故意架空我。",
            "“他是NPD”不是我的判断。",
            "我只是引用“老板故意架空我”，不代表我这么认为。",
        )
        for index, text in enumerate(denied, start=1):
            with self.subTest(text=text):
                self.assertNotIn(
                    "USER_STORY_CLAIM_MISSING",
                    validation_codes(text, f"round27-denied-{index}"),
                )

        for index, text in enumerate(
            ("老板故意架空我。", "他是NPD。"), start=1
        ):
            with self.subTest(control=text):
                self.assertIn(
                    "USER_STORY_CLAIM_MISSING",
                    validation_codes(text, f"round27-story-control-{index}"),
                )

    def test_observation_and_feeling_require_predicate_and_self_report(self) -> None:
        discovered = casefile.make_draft(
            "她发现我很焦虑。", "round27-discovered", "standard"
        )
        self.assertNotIn(
            "她发", {item["text"] for item in discovered["source_spans"]}
        )
        discovered_codes = {
            item["code"] for item in casefile.validate_casefile(discovered)
        }
        self.assertNotIn("OBSERVABLE_FACT_CLAIM_MISSING", discovered_codes)
        self.assertNotIn("EXPLICIT_FEELING_CLAIM_MISSING", discovered_codes)

        for index, text in enumerate(
            (
                "[测评截图] 测评结果显示我很焦虑。",
                "她观察到我很焦虑。",
                "她说：“我很焦虑。”这句话不是我的感受。",
            ),
            start=1,
        ):
            with self.subTest(text=text):
                self.assertNotIn(
                    "EXPLICIT_FEELING_CLAIM_MISSING",
                    validation_codes(text, f"round27-feeling-source-{index}"),
                )

        self.assertIn(
            "EXPLICIT_FEELING_CLAIM_MISSING",
            validation_codes("我很焦虑。", "round27-feeling-control"),
        )
        self.assertIn(
            "OBSERVABLE_FACT_CLAIM_MISSING",
            validation_codes("她发来消息。", "round27-observation-control"),
        )

    def test_role_evidence_requires_same_organizational_unit(self) -> None:
        claim = {
            "kind": "interpretation",
            "source_ref": "P1",
            "exact_quote": "我认为第一事业部在架空我。",
        }
        different_unit = {
            "source_ref": "E1",
            "source_type": "user_direct_observation",
            "source_label": "第二事业部记录",
            "exact_quote": "第二事业部系统今天仍允许我审批项目支出。",
        }
        self.assertEqual(
            {"does_not_establish"},
            casefile._allowed_relation_for_claim_evidence(
                claim, different_unit
            ),
        )

        same_unit = dict(different_unit)
        same_unit["source_label"] = "第一事业部记录"
        same_unit["exact_quote"] = (
            "第一事业部系统今天仍允许我审批项目支出。"
        )
        self.assertIn(
            "conflicts",
            casefile._allowed_relation_for_claim_evidence(claim, same_unit),
        )


if __name__ == "__main__":
    unittest.main()
