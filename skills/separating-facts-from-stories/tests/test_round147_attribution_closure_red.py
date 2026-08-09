from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))
sys.path.insert(0, str(SKILL_DIR / "tests"))

import casefile  # noqa: E402
from test_round136_assertion_provenance_metamorphic_red import (  # noqa: E402
    _forced_attribution_errors,
)


def _derived_kind(text: str) -> str | None:
    draft = casefile.make_draft(text, "round147-attribution", "standard")
    quotes = [item for item in draft["source_spans"] if item.get("quoted") is True]
    if not quotes:
        return None
    span = max(quotes, key=lambda item: len(item["text"]))
    return casefile.derive_claim_kind_for_span(span["text"], span, text)


class Round147AttributionClosureRedTests(unittest.TestCase):
    def assert_rejected_as_direct(self, text: str) -> None:
        self.assertNotEqual("attributed_statement", _derived_kind(text), text)
        self.assertTrue(_forced_attribution_errors(text), text)

    def test_document_container_variants_keep_artifact_provenance(self) -> None:
        for text in (
            "白皮书里老板说：‘手机送修，刚拿回来’。",
            "备忘录里老板说：‘手机送修，刚拿回来’。",
            "电子表格里老板说：‘手机送修，刚拿回来’。",
        ):
            with self.subTest(text=text):
                self.assert_rejected_as_direct(text)

    def test_future_and_wait_condition_are_not_completed_speech(self) -> None:
        for text in (
            "过两天老板会说：‘手机送修，刚拿回来’。",
            "等他到场，老板会说：‘手机送修，刚拿回来’。",
            "假使他到场，老板会说：‘手机送修，刚拿回来’。",
        ):
            with self.subTest(text=text):
                self.assert_rejected_as_direct(text)

    def test_summary_labels_cannot_claim_verbatim_direct_quote(self) -> None:
        for text in (
            "[大意] 老板说：‘手机送修，刚拿回来’。",
            "[摘要] 老板说：‘手机送修，刚拿回来’。",
        ):
            with self.subTest(text=text):
                self.assert_rejected_as_direct(text)

    def test_direct_user_received_control_remains_supported(self) -> None:
        text = "老板当面告诉我：‘手机送修，刚拿回来’。"
        self.assertEqual("attributed_statement", _derived_kind(text))
        self.assertFalse(_forced_attribution_errors(text))


if __name__ == "__main__":
    unittest.main()
