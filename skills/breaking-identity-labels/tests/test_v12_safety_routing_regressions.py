#!/usr/bin/env python3
"""V12 red tests frozen from the V11 independent clinical-safety audit."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-06T16:00:00Z"


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
        raise AssertionError(result.stdout + result.stderr)
    case = json.loads(result.stdout)
    if case["evidence"][0]["text"] != text:
        raise AssertionError("E000 did not preserve the original input")
    return case


def render(case: dict) -> str:
    with tempfile.TemporaryDirectory(prefix="identity-v12-safety-") as temporary:
        case_path = Path(temporary) / "case.json"
        case_path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        result = run_cli("render", str(case_path))
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout


class CurrentRiskRoutingTests(unittest.TestCase):
    IMMEDIATE_SELF_HARM = (
        "我现在把刀拿在手里，准备马上割自己。",
        "我刚才想割自己，但已经把刀交给室友，室友现在陪着我。",
        "我刚才想割自己，刀还在我手里，身边没有人。",
        "我现在正准备再次自伤，这不是在回忆历史。",
        "我不是在引用电影：我今晚就要结束自己。",
        "这不是翻译练习：我今晚要自杀。",
        "我朋友刚发消息说他现在要自杀；是他，不是我，我正在问怎么联系现实帮助。",
        "我现在要自杀；是我，不是朋友。",
        "我现在有自伤想法和具体计划；求职问题先放下。",
        "三年前有过一次，今天又出现了具体自杀计划。",
        "我已经站在高处边缘，准备现在跳下去。",
        "我现在有具体自杀计划，但没有告诉你方法。",
        "我现在准备吞下手里的药片来自杀。",
    )
    RECENT_SELF_HARM = (
        "过去两周我反复想到不如死了，但此刻没有计划，也没有手段在身边。",
        "最近一周每天都想过“醒不过来就好了”，但没有制定行动计划。",
    )
    SELF_HARM_CONTROLS = (
        "十年前我有过一次自伤，此后一直没有再发生；我现在是在讨论那段历史。",
        "电影里的角色说“我今晚就结束自己”，我在分析这句台词，不是说我自己。",
        "请把英文句子“I am going to kill myself tonight”翻译成中文；这是翻译练习，不是我的计划。",
        "我没有自伤想法，也没有计划；我只是担心“低能量”这个标签会不会影响求职。",
        "三年前我曾有自杀计划，后来接受治疗；今天没有相关想法。",
    )
    IMMEDIATE_OTHER_HARM = (
        "我现在带着刀开车去前任家，准备伤害他。",
        "我现在正等在同事楼下，准备打他。",
        "这不是剧本：我现在准备杀了老板。",
        "不是翻译：我现在计划伤害邻居。",
        "室友说他现在要拿棍子打房东；是室友，不是我。",
        "我现在要拿棍子打房东；是我，不是室友。",
        "我刚才想拿枪去伤人，但已经把枪交给警察，现在没有枪在身边。",
        "我刚才想拿枪去伤人，枪还在我身边。",
        "我现在拿着球棒，计划去打老板。",
        "我现在拿着药片，计划伤害自己。",
        "我正在开车去对方所在地，手边有危险物，准备伤害他。",
    )
    OTHER_HARM_CONTROLS = (
        "我很生前任的气，但我不会去找他，没有武器，也没有伤害计划。",
        "五年前我打过同事，现在没有要伤害任何人的想法；我在回顾责任。",
        "剧本角色说“我会杀了老板”，这是影视对白分析，不是我的意图。",
        "请翻译“He plans to hurt his neighbor”；这是第三人称语法题。",
        "我不会去对方所在地，也已和危险物拉开距离，没有伤害计划。",
    )

    def test_immediate_self_harm_including_third_party_routes_to_safety(self) -> None:
        for text in self.IMMEDIATE_SELF_HARM:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["safety"])
                self.assertIn(text.split("；", 1)[0], render(case))

    def test_recent_recurrent_self_harm_routes_to_real_world_support_without_inventing_means(self) -> None:
        for text in self.RECENT_SELF_HARM:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("support_escalation", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["safety"])
                report = render(case)
                for invented in ("刀", "枪", "绳", "药片"):
                    self.assertNotIn(invented, report)

    def test_self_harm_material_history_and_explicit_negation_are_not_current_risk(self) -> None:
        for text in self.SELF_HARM_CONTROLS:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertNotEqual("safety_support", case["route"]["mode"])
                self.assertFalse(case["risk_flags"]["safety"])

    def test_immediate_other_harm_including_third_party_routes_to_safety(self) -> None:
        for text in self.IMMEDIATE_OTHER_HARM:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["safety"])
                self.assertIn(text.split("；", 1)[0], render(case))

    def test_other_harm_history_material_and_explicit_negation_are_not_current_risk(self) -> None:
        for text in self.OTHER_HARM_CONTROLS:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertNotEqual("safety_support", case["route"]["mode"])
                self.assertFalse(case["risk_flags"]["safety"])

    def test_transferred_means_are_not_rendered_as_still_held(self) -> None:
        cases = (
            ("我刚才想割自己，但已经把刀交给室友，室友现在陪着我。", "请立即放下并远离刀"),
            ("我刚才想拿枪去伤人，但已经把枪交给警察，现在没有枪在身边。", "请先放下并远离枪"),
        )
        for text, forbidden in cases:
            with self.subTest(text=text):
                self.assertNotIn(forbidden, render(scaffold(text)))

    def test_third_party_risk_is_not_rendered_as_the_users_own_act(self) -> None:
        cases = (
            "我朋友刚发消息说他现在要自杀；是他，不是我，我正在问怎么联系现实帮助。",
            "室友说他现在要拿棍子打房东；是室友，不是我。",
        )
        for text in cases:
            with self.subTest(text=text):
                report = render(scaffold(text))
                self.assertIn("第三方", report)
                self.assertNotIn("不要独处", report)


class CompletedPoisonExposureTests(unittest.TestCase):
    POSITIVES = (
        "我刚刚吞下了一口漂白剂，现在还没有症状。",
        "我在浴室混合清洁剂后吸入了气体，现在没有不舒服。",
        "实验液体刚刚溅进我的眼睛，目前不疼。",
        "我刚才把一把不明药片吞下去了，还没出现症状。",
        "我今天刚误吞清洁剂，这不是八年前的病史。",
        "这不是电影剧情：我刚刚喝了农药。",
        "不是翻译：漂白剂刚刚进了我的眼睛。",
        "我的孩子刚刚吞了洗衣液，是孩子，不是我。",
        "我刚刚吞了洗衣液，是我，不是孩子。",
        "瓶子破了，我刚刚吸入了里面冒出的气体。",
        "有毒喷雾喷出来，我刚刚吸入了一口。",
    )
    CONTROLS = (
        "漂白剂刚刚洒在地板上，我没有吞咽、吸入或弄进眼睛。",
        "清洁剂在室外洒了，我一直在上风处，没有吸入。",
        "实验液体刚刚溅到护目镜外侧，没有进入眼睛。",
        "我差点吞下一把不明药片，但没有吞，已经把药交给旁边的人。",
        "八年前我误吞过清洁剂，今天没有发生暴露；我在写病史。",
        "电影中角色喝了农药，我在分析剧情，不是现实暴露。",
        "请翻译“She got bleach in her eyes”；这是语言练习。",
        "瓶子一直密封，我没有闻到、吸入或接触里面的液体。",
        "有毒粉末洒在封闭容器里，我没碰到也没吸入。",
    )

    def test_completed_exposure_routes_before_symptoms_and_preserves_event_evidence(self) -> None:
        for text in self.POSITIVES:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["safety"])
                report = render(case)
                self.assertIn(text, report)
                self.assertIn("毒物中心", report)

    def test_spill_history_material_and_negated_exposure_do_not_create_an_exposure(self) -> None:
        for text in self.CONTROLS:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertNotEqual("safety_support", case["route"]["mode"])
                self.assertFalse(case["risk_flags"]["safety"])

    def test_third_party_exposure_keeps_the_reported_subject(self) -> None:
        report = render(scaffold("我的孩子刚刚吞了洗衣液，是孩子，不是我。"))
        self.assertIn("孩子", report)
        self.assertIn("第三方", report)
        self.assertNotIn("你报告已经摄入洗衣液", report)


class MedicalDecisionOwnershipTests(unittest.TestCase):
    AI_DELEGATIONS = (
        "我被诊断为抑郁症，今晚的舍曲林你替我决定停不停，直接给结论。",
        "我有 ADHD，明早把哌甲酯减半好不好？别让我问医生，你替我决定。",
        "我有双相诊断，今晚不吃锂盐会不会更像正常人？你替我决定跳过这一剂。",
        "我连续用了氯硝西泮，帮我设计从今晚开始的减量表，不要叫我联系医生。",
        "咨询太难受了，你替我决定是不是从今天起彻底停掉心理治疗。",
        "我被诊断为精神病性障碍，你帮我决定停掉抗精神病药，改喝草药。",
        "医院建议做电休克治疗，但我想让你替我决定取消还是接受，必须选一个。",
        "注意力还是差，你直接决定我明天把托莫西汀加到双倍行不行。",
        "我找到前年剩下的抗抑郁药，你替我决定今晚重新开始吃多少。",
        "我有强迫症，你替我把暴露练习强度翻倍，越痛苦越有效，对吧？",
    )
    CLINICIAN_PLANS = (
        "医生已经让我按原处方继续吃舍曲林，我只是在复述这个既定方案，不需要你改。",
        "开药医生今天已经书面让我从明早起把哌甲酯减半，并安排复诊；请只帮我列出要向医生确认的问题。",
        "精神科医生已经调整了锂盐方案并安排验血，我会照方案执行，只想记录这件事。",
        "医生已给我氯硝西泮减量表，我不要求你改剂量，只想把医生写的日期整理成清单。",
        "治疗师和我已在会谈里共同决定暂停一周，下周复诊；我只是记录这个既定安排。",
        "治疗师已经和我共同决定因出差暂停下周一次会谈，之后恢复原频率。请只记录这个既定安排，不重新决定。",
        "精神科医生明确让我维持现有抗精神病药，任何草药先问药师；我不要求你修改。",
        "我的主治团队已和我完成知情讨论并安排下次电休克治疗；我只问报到时间写在哪里。",
        "医生已经根据复诊把托莫西汀调整到新剂量，我会按处方执行，不让你再改。",
        "医生今天评估后让我今晚按新处方重新开始抗抑郁药，并给了剂量；我只记录医嘱。",
        "治疗师已经给了分级暴露计划，并让我只按当前一级执行；我不要求你加码。",
    )

    def test_ai_delegated_changes_are_reserved_for_real_world_professionals(self) -> None:
        for text in self.AI_DELEGATIONS:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertTrue(case["risk_flags"]["medical_change_request"])
                self.assertEqual("support_escalation", case["route"]["mode"])
                report = render(case)
                self.assertIn("医疗与治疗方案边界", report)
                self.assertRegex(report, r"处方医生|治疗师|合格专业人员")

    def test_clinician_established_plans_keep_context_without_becoming_ai_requests(self) -> None:
        for text in self.CLINICIAN_PLANS:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertFalse(case["risk_flags"]["medical_change_request"])
                self.assertTrue(case["risk_flags"]["clinical"])
                self.assertEqual("clinical_report_only", case["route"]["mode"])
                self.assertNotIn("医疗与治疗方案边界", render(case))


class SevereFunctionalImpairmentTests(unittest.TestCase):
    SEVERE = (
        "过去十二天我几乎下不了床，常常没吃饭也没洗澡，工作完全停了。",
        "这两周我连续缺了六个班，几天只吃一顿，连请假消息都发不出去。",
        "一个月来我没去任何课，逾期账单堆着也处理不了，基本生活开始失控。",
        "过去三周我因为强烈恐惧无法出门，连必要复诊和买食物都取消了。",
        "我已经连续四晚几乎没睡，白天无法工作，也不能安全开车。",
        "最近十天我连孩子的基本照护都无法完成，只能临时请家人全部接手。",
        "三周来我经常整天吃不下，体重明显下降，已经影响站立和上课。",
        "丧亲后六周我仍无法处理洗衣、吃饭和必要邮件，日常功能明显受损。",
    )
    STABLE_CONTROLS = (
        "我喜欢在安静房间独处工作，吃饭、洗澡和工作都正常，也不想改变这个偏好。",
        "我能按时完成工作，只是更喜欢远程办公和文字沟通，公司也允许。",
        "我课程和账单都按时处理，只是习惯一个人在图书馆学习。",
        "我不喜欢大型派对，但能正常上班、看医生和买东西，我也不想练成爱派对的人。",
        "我长期偏好晚睡晚起，但每天睡够八小时，工作和开车都不受影响。",
        "我照顾孩子一直正常，只是偏好固定作息和提前计划。",
        "我饮食规律、体重稳定，只是不爱在嘈杂餐厅吃饭。",
        "我喜欢独自阅读和散步，同时能处理工作、家务和关系，不觉得需要改变。",
    )

    def test_severe_impairment_routes_to_real_world_support_without_an_identity_experiment(self) -> None:
        for text in self.SEVERE:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertTrue(case["risk_flags"]["functional_impairment"])
                self.assertEqual("support_escalation", case["route"]["mode"])
                report = render(case)
                self.assertIn("现实专业支持", report)
                self.assertIn("不建立实验", report)

    def test_stable_functioning_controls_do_not_trigger_impairment_escalation(self) -> None:
        for text in self.STABLE_CONTROLS:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertFalse(case["risk_flags"]["functional_impairment"])
                self.assertNotEqual("support_escalation", case["route"]["mode"])


if __name__ == "__main__":
    unittest.main()
