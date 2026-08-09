from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402


NONASSERTED_SPEECH = tuple(
    f"我{verb}他会说：‘手机送修，刚拿回来’。"
    for verb in ("猜", "估计", "怀疑", "预测", "觉得", "认为")
)

SECONDHAND_PUNCTUATION_VARIANTS = (
    "同事告诉我老板说：‘手机送修，刚拿回来’。",
    "同事告知我老板说：‘手机送修，刚拿回来’。",
    "同事跟我说老板说：‘手机送修，刚拿回来’。",
    "同事对我说老板说：‘手机送修，刚拿回来’。",
    "朋友给我说老板说：‘手机送修，刚拿回来’。",
    "朋友跟我讲老板说：‘手机送修，刚拿回来’。",
    "朋友告诉我他原话是：‘手机送修，刚拿回来’。",
    "同事告诉我，老板说：‘手机送修，刚拿回来’。",
)

ARTIFACT_VARIANTS = (
    "新闻报道中，老板说：‘手机送修，刚拿回来’。",
    "会议纪要里写着老板说：‘手机送修，刚拿回来’。",
    "[录音] 老板说：‘手机送修，刚拿回来’。",
    "[邮件] 老板说：‘手机送修，刚拿回来’。",
)

DIRECT_SOURCE_RESETS = (
    "据说项目要停，但老板当面告诉我：‘手机送修，刚拿回来’。",
    "我先听同事转述了一遍，后来老板又当面告诉我：‘手机送修，刚拿回来’。",
    "截图显示项目要停，但老板当面告诉我：‘手机送修，刚拿回来’。",
    "我先看了截图，后来老板又当面告诉我：‘手机送修，刚拿回来’。",
    "录音内容不清楚，不过老板随后亲口说：‘手机送修，刚拿回来’。",
    "邮件写着项目取消，但老板当面说：‘手机送修，刚拿回来’。",
)

DIRECT_HUMAN_GRAMMAR = (
    "她解释道：‘手机送修，刚拿回来’。",
    "经理回应：‘手机送修，刚拿回来’。",
    "老师澄清：‘手机送修，刚拿回来’。",
    "他承认：‘手机送修，刚拿回来’。",
    "她宣布：‘手机送修，刚拿回来’。",
    "张伟说：‘手机送修，刚拿回来’。",
    "欧阳娜娜说：‘手机送修，刚拿回来’。",
    "王总说：‘手机送修，刚拿回来’。",
    "产品负责人说：‘手机送修，刚拿回来’。",
    "我亲口告诉他：‘手机送修，刚拿回来’。",
    "我告诉老板：‘手机送修，刚拿回来’。",
    "我回复老板：‘手机送修，刚拿回来’。",
    "我笑着说：‘手机送修，刚拿回来’。",
    "他在视频通话中说：‘手机送修，刚拿回来’。",
    "他在语音通话中说：‘手机送修，刚拿回来’。",
)

PASSTHROUGH_TASKS = (
    "请整理他说的：‘手机送修，刚拿回来’。",
    "请给这句已经标注来源的话改格式：他说：‘手机送修，刚拿回来’。",
    "只整理格式，不分析内容。他说：‘手机送修，刚拿回来’。",
    "请按时间线整理这条有来源的事件：老板说：‘手机送修，刚拿回来’。",
)


def _full_quote_span(draft: dict[str, Any]) -> dict[str, Any]:
    return max(
        (item for item in draft["source_spans"] if item.get("quoted") is True),
        key=lambda item: len(item["text"]),
    )


def _derive(text: str) -> str | None:
    draft = casefile.make_draft(text, "round136-derive", "standard")
    quoted = [item for item in draft["source_spans"] if item.get("quoted") is True]
    if not quoted:
        return None
    span = max(quoted, key=lambda item: len(item["text"]))
    return casefile.derive_claim_kind_for_span(span["text"], span, text)


def _forced_attribution_errors(text: str) -> set[str]:
    draft = casefile.make_draft(text, "round136-validate", "standard")
    quoted = [item for item in draft["source_spans"] if item.get("quoted") is True]
    if not quoted:
        return {"QUOTE_NOT_GENERATED"}
    span = max(quoted, key=lambda item: len(item["text"]))
    draft["claims"].append(
        {
            "id": "C1",
            "kind": "attributed_statement",
            "text": span["text"],
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "direct_quote",
            "exact_quote": span["text"],
            "epistemic_status": "directly_stated",
            "diagnostic_boundary": False,
        }
    )
    draft["evidence"].append(
        {
            "id": "E1",
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "source_type": "direct_quote",
            "exact_quote": span["text"],
            "can_establish": ["C1"],
            "cannot_establish": [],
            "limitations": ["single_party_report"],
        }
    )
    draft["evidence_links"].append(
        {
            "proposition_id": "C1",
            "evidence_ref": "E1",
            "relation": "supports",
            "strength": "direct",
            "reason": "anchor_matches_report",
        }
    )
    draft["unknowns"] = [
        {
            "id": "U1",
            "unknown_type": "event_cause_or_context",
            "text": casefile.UNKNOWN_CATALOG["event_cause_or_context"],
            "status": "open",
            "resolved_by_evidence_refs": [],
        }
    ]
    action = {
        key: value
        for key, value in casefile.ACTION_CATALOG["neutral_check"].items()
        if key != "modes"
    }
    draft["actions"] = [{"id": "A1", "action_type": "neutral_check", **action}]
    draft["user_decisions"] = ["evidence_threshold"]
    return {item["code"] for item in casefile.validate_casefile(draft)}


class Round136AssertionProvenanceMetamorphicRedTests(unittest.TestCase):
    def test_nonfactive_attitudes_cannot_become_direct_attribution(self) -> None:
        for text in NONASSERTED_SPEECH:
            with self.subTest(text=text):
                self.assertNotEqual("attributed_statement", _derive(text))
                self.assertTrue(_forced_attribution_errors(text))

    def test_secondhand_chain_is_invariant_to_punctuation(self) -> None:
        for text in SECONDHAND_PUNCTUATION_VARIANTS:
            with self.subTest(text=text):
                self.assertNotEqual("attributed_statement", _derive(text))
                self.assertTrue(_forced_attribution_errors(text))

    def test_inline_and_bracketed_artifacts_are_equally_non_direct(self) -> None:
        for text in ARTIFACT_VARIANTS:
            with self.subTest(text=text):
                self.assertNotEqual("attributed_statement", _derive(text))
                self.assertTrue(_forced_attribution_errors(text))

    def test_explicit_later_direct_encounter_resets_prior_source(self) -> None:
        for text in DIRECT_SOURCE_RESETS:
            with self.subTest(text=text):
                self.assertEqual("attributed_statement", _derive(text))
        self.assertNotEqual(
            "attributed_statement",
            _derive("据同事转述，老板亲口说：‘手机送修，刚拿回来’。"),
        )

    def test_common_direct_human_speech_grammar_is_supported(self) -> None:
        for text in DIRECT_HUMAN_GRAMMAR:
            with self.subTest(text=text):
                self.assertEqual("attributed_statement", _derive(text))

    def test_transform_and_timeline_requests_remain_passthrough(self) -> None:
        for text in PASSTHROUGH_TASKS:
            with self.subTest(text=text):
                self.assertEqual(
                    "passthrough",
                    casefile.make_draft(text, "round136-route", "auto")["mode"],
                )


if __name__ == "__main__":
    unittest.main()
