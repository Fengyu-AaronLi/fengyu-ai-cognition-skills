from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402
import workflow  # noqa: E402


def auto_route(text: str) -> str:
    if casefile.expected_safety_signal_types(text):
        return "safety"
    if workflow.classify_passthrough_request(text) is not None:
        return "passthrough"
    return "standard"


class Round78ResolvedRiskScopeRedTests(unittest.TestCase):
    """Resolved, negated, hypothetical, and old reported events are not current."""

    def test_blind_review_noncurrent_controls_remain_standard(self) -> None:
        cases = (
            "上个月他持刀威胁过我。警方已处理，他目前被拘留，我现在安全，也没有新的接触。",
            "两年前我有过自杀念头，后来持续治疗。现在没有自伤念头，也没有计划。",
            "My sister attempted suicide years ago. She completed treatment and told me today she has no thoughts or plan to harm herself.",
            "去年有人泄露过我的住址。我已经搬家并更换门锁，此后没有人跟踪或联系我。",
            "I had severe chest pain yesterday, was evaluated in the ER, and the doctor discharged me. I have no symptoms now.",
            "她刚才没有说要杀我，也不在我附近。",
            "没有陌生人知道我的住址，也没有人跟踪我。",
            "以前他砸过门，但今天没有再来，也没有联系我。",
            "假设有人说“我今晚要死”，应该如何区分修辞、玩笑和真实风险？",
            "母亲转述说邻居昨晚胸痛，后来急救人员检查过了。邻居现在无症状并在家休息。",
            "十年前的日记里我写过“我不想活了”。那是过去的记录，我现在安全且没有这种想法。",
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))
                self.assertEqual("standard", auto_route(text))


if __name__ == "__main__":
    unittest.main()
