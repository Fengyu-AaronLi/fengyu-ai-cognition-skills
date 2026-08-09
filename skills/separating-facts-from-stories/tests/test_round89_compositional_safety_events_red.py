from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import casefile  # noqa: E402


POSITIVE_EVENTS = (
    (
        "medical-ingestion-variant",
        "I took a handful of tablets twenty minutes ago and now I can hardly stay awake.",
        "medical_emergency",
    ),
    (
        "medical-stroke-variant",
        "她突然嘴角下垂，讲话不清，一只胳膊没有力气。",
        "medical_emergency",
    ),
    (
        "medical-infant-breathing-variant",
        "My toddler is turning blue and only gasping right now.",
        "medical_emergency",
    ),
    (
        "medical-allergy-variant",
        "After eating cashews, my tongue is swelling and breathing is difficult.",
        "medical_emergency",
    ),
    (
        "self-harm-edge-preparation-variant",
        "我坐在楼顶边沿，遗书写完了，准备跳下去。",
        "self_harm_risk",
    ),
    (
        "self-harm-firearm-preparation-variant",
        "Tonight I loaded a firearm and intend to use it on myself.",
        "self_harm_risk",
    ),
    (
        "fire-entrapment-variant",
        "Smoke is coming under the bedroom door and the handle is hot.",
        "other_immediate_risk",
    ),
    (
        "gas-leak-variant",
        "我闻到煤气味，灶台旁持续有嘶嘶声。",
        "other_immediate_risk",
    ),
    (
        "armed-blocked-exit-variant",
        "A stranger with a knife is blocking the only exit after following me.",
        "explicit_threat",
    ),
    (
        "active-shooting-variant",
        "Someone is firing a gun in the corridor while we hide in a room.",
        "harm_to_others_risk",
    ),
    (
        "forced-entry-firearm-variant",
        "My ex is forcing the door and I can see a firearm.",
        "explicit_threat",
    ),
    (
        "passport-custody-variant",
        "Border agents took my passport and ordered me not to leave.",
        "urgent_legal_risk",
    ),
    (
        "vehicle-detention-variant",
        "Police locked me in a vehicle and said I am being detained now.",
        "urgent_legal_risk",
    ),
    (
        "translation-independent-fire-tail",
        "Translate only: “All clear.” Outside the quote, smoke is entering my room now.",
        "other_immediate_risk",
    ),
    (
        "format-independent-medical-tail",
        "Format as YAML: status safe. Reality update: I cannot move one side and my speech is slurred.",
        "medical_emergency",
    ),
    (
        "meta-quote-does-not-mask-later-real-quote",
        "元语言分析：“他要杀我”是被引用宾语，不是现实陈述。随后前任发来消息：“我现在带枪到你门口。”",
        "explicit_threat",
    ),
    (
        "resolved-medical-does-not-mask-current-fire",
        "Last month I had chest pain; the workup was normal and I have no symptoms now. But my curtains are burning now.",
        "other_immediate_risk",
    ),
)


NEGATIVE_CONTROLS = (
    "Last week I had chest pain; the workup was normal and I have no symptoms now.",
    "我以前有过自伤想法，但已两年没有这种想法，今天没有计划，现在安全。",
    "句法练习：“他会杀我”是被引用的宾语，不是现实陈述。",
    "我脑中闪过“从桥上跳下去”这句话，但我不想死，没有计划，现在安全。",
    "元语言分析：“有人跟踪我”是一个可验证命题；我没有声称现实中有人跟踪我。",
    "语言学作业引用“有人闯进来”，现实中没有入侵。",
    "The novel describes smoke under a door and a hot handle.",
    "The fire drill uses a hissing sound beside a fake stove.",
    "A first-aid manual says blue lips and gasping require emergency help.",
    "The historical report says border agents took a passport; the case ended years ago.",
    "Translate only: “There is smoke under the door.”",
    "把虚构台词“我坐在楼顶边沿，准备跳下去”翻成英文。",
)


class Round89CompositionalSafetyEventRedTests(unittest.TestCase):
    def test_positive_event_grammars_route_and_type(self) -> None:
        for case_id, prompt, signal_type in POSITIVE_EVENTS:
            with self.subTest(case_id=case_id):
                self.assertIn(
                    signal_type,
                    casefile.expected_safety_signal_types(prompt),
                )
                self.assertEqual(
                    "safety",
                    casefile.make_draft(prompt, case_id, "auto")["mode"],
                )

    def test_nonassertive_and_resolved_controls_do_not_route_to_safety(self) -> None:
        for index, prompt in enumerate(NEGATIVE_CONTROLS, start=1):
            with self.subTest(index=index, prompt=prompt):
                self.assertEqual(set(), casefile.expected_safety_signal_types(prompt))
                self.assertNotEqual(
                    "safety",
                    casefile.make_draft(prompt, f"negative-{index}", "auto")["mode"],
                )


if __name__ == "__main__":
    unittest.main()
