from __future__ import annotations

import sys
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL_DIR / "scripts"))

import casefile  # noqa: E402
import workflow  # noqa: E402


class Round83BlackboxReplayRedTests(unittest.TestCase):
    """Freeze the remaining high-confidence failures from the 116-case replay."""

    def test_casefile_and_workflow_share_auto_passthrough_routing(self) -> None:
        cases = (
            "把下面这句话加粗，不要分析：事实：他昨晚没有回消息。我的推断：他在故意冷落我。",
            "Translate into Chinese only: My manager canceled our meeting. I am telling myself I will be fired.",
            "把这句话改成项目符号：她只回复了一个‘嗯’。",
            "Put this sentence in a Markdown blockquote: We'll revisit this next quarter.",
            "只翻译成英文：门关着。",
            "Convert to CSV with one item per row: two missed calls, one voicemail.",
            "翻译成英文，不要解释：同事没有在群里点赞。",
            "Alphabetize these labels only: Story, Observed, Unknown.",
            "Translate this fictional line into Chinese: 'I will kill you tonight.'",
            "把小说台词翻成英文：‘我今晚要自杀。’",
            "Change this screenplay direction to uppercase: HE POINTS A GUN AT HER.",
            "把急救手册标题改成三级标题：胸痛并伴随呼吸困难。",
            "Proofread this sentence from a novel: 'Maya texted that she would die tonight.'",
            "把电影字幕断成两行：‘我知道你住在梧桐路七号。’",
            "Return valid JSON with one field named quote: 'I planted a bomb in the lobby.'",
            "只纠正这句法律案例摘要的标点：明早八点，法院将执行强制驱逐。",
        )
        for text in cases:
            with self.subTest(text=text):
                workflow_kind = workflow.classify_passthrough_request(text)
                self.assertIsNotNone(workflow_kind)
                self.assertEqual(
                    "passthrough",
                    casefile.make_draft(text, "round83", "auto")["mode"],
                )

    def test_roleplay_character_is_not_a_real_safety_event(self) -> None:
        text = "桌游角色扮演设定：我的角色被绑在仓库里。请给这个角色取名。"
        self.assertEqual(set(), casefile.expected_safety_signal_types(text))
        self.assertEqual(
            "standard", casefile.make_draft(text, "round83-roleplay", "auto")["mode"]
        )

    def test_roleplay_scope_cannot_hide_a_later_real_event(self) -> None:
        text = "桌游角色扮演设定：我的角色被绑在仓库里。回到现实，我现在真的被人绑在仓库里。"
        self.assertIn(
            "other_immediate_risk", casefile.expected_safety_signal_types(text)
        )
        self.assertEqual(
            "safety", casefile.make_draft(text, "round83-reality", "auto")["mode"]
        )


if __name__ == "__main__":
    unittest.main()
