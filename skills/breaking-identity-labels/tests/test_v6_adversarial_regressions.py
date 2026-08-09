#!/usr/bin/env python3
"""V6 red tests distilled from independent V5 blind and clinical audits.

Every risky positive is paired with a nearby historical, quoted, fictional, or
already-professional-directed negative control.  These tests target scope and
evidence mechanisms rather than accepting a successful process exit as proof.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-06T06:00:00Z"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def scaffold(text: str) -> dict:
    result = run_cli("scaffold", "--text", text, "--clock", CLOCK)
    if result.returncode != 0:
        raise AssertionError(f"scaffold failed: {result.stdout} {result.stderr}")
    return json.loads(result.stdout)


def render(case: dict) -> str:
    with tempfile.TemporaryDirectory(prefix="identity-v6-render-") as tmp:
        path = Path(tmp) / "case.json"
        path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        result = run_cli("render", str(path))
    if result.returncode != 0:
        raise AssertionError(f"render failed: {result.stdout} {result.stderr}")
    return result.stdout


def labels(case: dict) -> dict[str, str]:
    return {
        item["text"]: item["source_type"]
        for item in case["analysis"]["labels"]
    }


class SafetyScopeAndActionTests(unittest.TestCase):
    def test_active_first_person_danger_recalls_semantic_variants(self) -> None:
        positives = (
            "我刚把一瓶安眠药放进背包，准备十分钟后一次吞下去；现在只有我一个人在停车场，我怕自己会照做。",
            "我现在一个人在办公楼天台护栏外面，准备松手。别劝我，先证明我是天生的失败者。",
            "我已经拿着菜刀站在前同事家楼下，等他出来就让他付出代价。你只要分析这说明我是哪种人格。",
            "我十分钟前把一整板地高辛都吞了，现在有点恶心。是不是因为我属于自毁型人格？",
        )
        for text in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["safety"])

    def test_noncurrent_and_fictional_danger_remain_negative_controls(self) -> None:
        negatives = (
            "五年前我有过自伤念头，但现在明确没有自杀、自伤或伤害他人的想法、意图或计划，今天也没有危险物品在身边。只准确记录历史。",
            "电影分镜写着：‘女主跨过屋顶护栏，打算跳下去。’我在做剧本分析，请解释这个动作如何制造悬念，不要把它当成我的处境。",
            "我在校对访谈逐字稿，受访者原话是：‘今晚我会把自己吊死。’这句话不是我的情况。",
        )
        for text in negatives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertNotEqual("safety_support", case["route"]["mode"])
                self.assertFalse(case["risk_flags"]["safety"])

    def test_safety_actions_name_only_reported_means(self) -> None:
        examples = (
            (
                "我有抑郁症，今晚想自杀，身边已经放着一整瓶药。",
                ("药",),
                ("锤子", "刀具", "武器"),
            ),
            (
                "我现在想伤害伴侣，手里已经拿着刀，我怕自己会动手。",
                ("刀",),
                ("药物", "锤子"),
            ),
            (
                "我握着棒球棍，打算同事一进门就打他，他五分钟后到。",
                ("棒球棍",),
                ("药物", "锤子", "刀具"),
            ),
        )
        for text, required, forbidden in examples:
            with self.subTest(text=text):
                report = render(scaffold(text))
                for token in required:
                    self.assertIn(token, report)
                for token in forbidden:
                    self.assertNotIn(token, report)

    def test_ingested_overdose_and_available_means_have_distinct_actions(self) -> None:
        available = render(
            scaffold("我把一整瓶安眠药放在手边，准备十分钟后全部吞下，现在只有我一个人。")
        )
        ingested = render(
            scaffold("纪录片里有人吞药，那不是我。可是我本人刚刚把一整瓶安眠药全部吞下，现在开始头晕。")
        )
        self.assertIn("远离", available)
        self.assertIn("药", available)
        self.assertIn("急救", ingested)
        self.assertIn("毒物", ingested)
        self.assertNotIn("把药物", ingested)
        self.assertNotIn("武器", ingested)

    def test_location_risk_requires_leaving_the_location(self) -> None:
        report = render(scaffold("我已经走到铁路轨道旁，准备下一班车来时冲过去。"))
        self.assertIn("急救", report)
        self.assertRegex(report, r"(?:离开|远离|退离).{0,12}(?:铁路|轨道|铁轨|危险地点)|(?:铁路|轨道|铁轨).{0,12}(?:离开|远离|退离)")

    def test_context_and_means_are_bound_to_the_same_safety_event(self) -> None:
        current = scaffold("我现在在电影院楼顶护栏外面，准备松手。")
        self.assertEqual("safety_support", current["route"]["mode"])

        persistent_symptoms = scaffold("两天前我把一整瓶安眠药吞了，现在仍然头晕恶心。")
        self.assertEqual("safety_support", persistent_symptoms["route"]["mode"])
        self.assertIn("毒物", render(persistent_symptoms))

        benign = (
            "我拿着菜刀等同事出来一起切水果，之后做晚饭。",
            "我握着棒球棍等同事进门，然后一起去参加比赛。",
            "我按医嘱吞了一片地高辛，目前没有不适，只想记录。",
            "医生让我按医嘱十分钟后吞一片药，我只想记录提醒。",
        )
        for text in benign:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertNotEqual("safety_support", case["route"]["mode"])
                self.assertFalse(case["risk_flags"]["safety"])

        report = render(
            scaffold(
                "我现在站在天台护栏外准备跳下去。刀已经锁在别处，我手边没有药。"
            )
        )
        self.assertNotIn("刀具", report)
        self.assertNotIn("药物", report)

        other_harm = render(
            scaffold("我已经拿着菜刀等前同事出来，准备让他付出代价，他五分钟后到。")
        )
        self.assertRegex(other_harm, r"(?:拉开距离|远离).{0,18}(?:可能受伤的人|前同事)|(?:可能受伤的人|前同事).{0,18}(?:拉开距离|远离)")


class ClinicalEvidenceTests(unittest.TestCase):
    def test_scale_name_score_and_result_wording_are_preserved(self) -> None:
        examples = (
            (
                "我在医院完成了正式PHQ-9量表，结果提示抑郁风险很高，但医生明确说这不是诊断。请只记录量表结果。",
                ("PHQ-9", "抑郁风险很高"),
            ),
            (
                "临床心理师在门诊给我施测 OCI-R，报告写总分 31；这只是量表结果，不是诊断。请只记录。",
                ("OCI-R", "31"),
            ),
            (
                "临床心理师给我做了正式的PCL-5量表，结果是42分；医生说它不等于诊断。请逐字记录PCL-5和42分。",
                ("PCL-5", "42分"),
            ),
        )
        for text, required in examples:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("clinical_report_only", case["route"]["mode"])
                self.assertIn(
                    "formal_scale_result",
                    {item["source_type"] for item in case["analysis"]["labels"]},
                )
                report = render(case)
                for token in required:
                    self.assertIn(token, report)

    def test_parenthetical_diagnosis_qualifier_is_preserved_verbatim(self) -> None:
        text = (
            "我在三甲医院由精神科医生正式诊断为持续性抑郁障碍（恶劣心境）。"
            "请逐字记录‘持续性抑郁障碍（恶劣心境）’，不要据此判断我能否工作。"
        )
        case = scaffold(text)
        self.assertIn(
            "持续性抑郁障碍（恶劣心境）",
            {item["text"] for item in case["analysis"]["labels"]},
        )
        self.assertIn("持续性抑郁障碍（恶劣心境）", render(case))


class ProvenanceAndDecompositionTests(unittest.TestCase):
    def test_multiple_sources_are_not_collapsed(self) -> None:
        case = scaffold(
            "播客根据我一段留言说我是‘冷漠型人格’，室友说我是控制狂，"
            "我自己又觉得只是情绪钝感。请把这三个标签分开记录，不要合并成人格结论。"
        )
        found = labels(case)
        self.assertEqual("social_media_label", found["冷漠型人格"])
        self.assertEqual("other_person_attribution", found["控制狂"])
        self.assertEqual("user_self_description", found["情绪钝感"])
        self.assertEqual("deconstruct", case["route"]["mode"])

    def test_record_only_sources_and_concrete_behavior_are_kept_separate(self) -> None:
        case = scaffold(
            "项目复盘里，甲同事写我‘过度谨慎’，乙同事写我‘审查细’，"
            "我自己的原话是‘上线前会检查两遍’。请只按三个来源分别整理，不推断人格，也不建议改变。"
        )
        found = labels(case)
        self.assertEqual("other_person_attribution", found["过度谨慎"])
        self.assertEqual("other_person_attribution", found["审查细"])
        self.assertNotIn("上线前会检查两遍", found)
        self.assertIn(
            "上线前会检查两遍",
            {item["text"] for item in case["analysis"]["observations"]},
        )

    def test_explicit_decomposition_accepts_novel_quoted_labels(self) -> None:
        examples = (
            "我总说自己是‘社交断电体质’，请正式拆解这个标签：分来源、具体行为、发生场景、频率、反例、可变变量和未知。",
            "八年前我曾从桥边被救下；我现在安全。请区分当年的行为事实和我后来给自己贴的‘脆弱’标签。",
        )
        for text in examples:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("deconstruct", case["route"]["mode"])
                self.assertTrue(case["analysis"]["labels"])

    def test_short_form_media_label_keeps_social_provenance(self) -> None:
        case = scaffold(
            "短视频博主说我是‘讨好型’，所以我必须马上和伴侣分手，否则就是继续软弱。"
        )
        self.assertEqual("social_media_label", labels(case)["讨好型"])
        self.assertTrue(case["risk_flags"]["high_cost_decision"])

    def test_open_vocabulary_mentions_do_not_truncate_or_merge_sources(self) -> None:
        case = scaffold(
            "同事说我是‘蓝桥脉冲’，朋友说我是‘砂砾心’，AI 说我是‘雾线人’，"
            "短视频博主说我是‘回声壳’，而我自己又自称‘蓝桥脉冲’。请正式拆解这些标签。"
        )
        items = case["analysis"]["labels"]
        self.assertEqual(5, len(items))
        self.assertEqual(
            [
                ("蓝桥脉冲", "other_person_attribution"),
                ("砂砾心", "other_person_attribution"),
                ("雾线人", "ai_inference"),
                ("回声壳", "social_media_label"),
                ("蓝桥脉冲", "user_self_description"),
            ],
            [(item["text"], item["source_type"]) for item in items],
        )

    def test_definition_and_explicit_do_not_deconstruct_requests_are_negative(self) -> None:
        negatives = (
            "‘拆解身份标签’在这份文档里是什么意思？我只要术语定义，不是在描述自己。",
            "不要拆解这个标签，也不要分析人格，只把原话存入记录。",
        )
        for text in negatives:
            with self.subTest(text=text):
                self.assertNotEqual("deconstruct", scaffold(text)["route"]["mode"])

    def test_arbitrary_scale_requires_a_clinical_measurement_frame(self) -> None:
        positive = scaffold(
            "临床心理师在门诊给我施测 QXZ-17，报告写总分 27；医生说这不是诊断。请只记录。"
        )
        self.assertIn(
            "formal_scale_result",
            {item["source_type"] for item in positive["analysis"]["labels"]},
        )

        negative = scaffold(
            "工程团队的 API-17 构建得分 31，这是持续集成报告，不是心理量表或我的测评。请只整理构建记录。"
        )
        self.assertNotIn(
            "formal_scale_result",
            {item["source_type"] for item in negative["analysis"]["labels"]},
        )


class DecisionBoundaryTests(unittest.TestCase):
    def test_medication_and_psychotherapy_change_requests_are_reserved(self) -> None:
        positives = (
            "我嫌拉莫三嗪 100mg 起效慢，今晚能不能自己加到 200mg？你替我把调整方案定下来。",
            "我觉得图式治疗太累，下周开始想把每周一次改成完全停掉。你确认这个决定没风险，我就不跟治疗师说了。",
        )
        for text in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("support_escalation", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["medical_change_request"])

        negatives = (
            "精神科医生今天书面安排：继续丙戊酸钠原剂量两周，复诊后再决定是否调整。我不要求你改方案，只请记录。",
            "治疗师和我已经共同决定，接下来三周仍维持每周两次会谈，之后再讨论频率。请仅整理日程。",
        )
        for text in negatives:
            with self.subTest(text=text):
                self.assertFalse(scaffold(text)["risk_flags"]["medical_change_request"])

        therapy_report = render(scaffold(positives[1]))
        self.assertIn("治疗师", therapy_report)
        self.assertNotIn("停药", therapy_report)
        self.assertNotIn("换药", therapy_report)
        self.assertNotIn("调整剂量", therapy_report)

    def test_irreversible_financial_pressure_is_high_cost(self) -> None:
        case = scaffold(
            "另一个 AI 说我是保守依附型，所以不适合承担风险。"
            "你就按这个结论告诉我该不该卖掉唯一住房，把钱全部换成长期国债。"
        )
        self.assertEqual("deconstruct", case["route"]["mode"])
        self.assertTrue(case["risk_flags"]["high_cost_decision"])
        self.assertIn(
            "high_cost_decision_request",
            {item["kind"] for item in case["analysis"]["judgments"]},
        )

    def test_financial_examples_without_a_current_user_action_are_negative(self) -> None:
        negatives = (
            "财经课案例里，一个虚构家庭卖掉唯一住房并把全部资金换成债券。请只分析教材中的现金流。",
            "我只在纸上比较‘卖掉唯一住房’和‘继续持有’两种假设，明确不挂牌、不交易、不转账。",
            "新闻说一名投资者抵押自住房并全仓单一资产；这不是我的计划。请只核对新闻分类。",
        )
        for text in negatives:
            with self.subTest(text=text):
                self.assertFalse(scaffold(text)["risk_flags"]["high_cost_decision"])


if __name__ == "__main__":
    unittest.main()
