#!/usr/bin/env python3
"""V8 red tests distilled from the three frozen V7 independent audits.

The tests deliberately pair adjacent positive and negative inputs.  They assert
actor, discourse scope, source, evidence span and event state so that widening
a keyword list cannot make the suite pass by itself.
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
CLOCK = "2026-08-06T12:00:00Z"


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
    return json.loads(result.stdout)


def render(case: dict) -> str:
    with tempfile.TemporaryDirectory(prefix="identity-v8-render-") as temporary:
        case_path = Path(temporary) / "case.json"
        case_path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        result = run_cli("render", str(case_path))
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout


def rows(case: dict) -> list[tuple[str, str]]:
    return [(item["text"], item["source_type"]) for item in case["analysis"]["labels"]]


def assert_exact_sources(test: unittest.TestCase, case: dict) -> None:
    evidence = {item["id"]: item["text"] for item in case["evidence"]}
    for field in ("labels", "judgments", "observations", "counterexamples"):
        for item in case["analysis"][field]:
            source = item["source"]
            original = evidence[source["evidence_id"]]
            test.assertEqual(source["quote"], original[source["start"] : source["end"]])


class DiscourseScopeAndIdentityGraphTests(unittest.TestCase):
    def test_open_labels_and_global_verdicts_build_an_identity_claim_graph(self) -> None:
        examples = (
            (
                "我明确给自己贴的标签是“跨组哑巴”，所以我肯定做不了跨部门协调。",
                "跨组哑巴",
                "user_self_description",
                "capability_verdict",
            ),
            (
                "我认定自己就是“社交断电者”，以后任何需要寒暄的岗位我都胜任不了。",
                "社交断电者",
                "user_self_description",
                "future_verdict",
            ),
            (
                "聊天机器人给我的人格标签是“低容错搭档”，它说这说明我永远带不好新人。",
                "低容错搭档",
                "ai_inference",
                "future_verdict",
            ),
            (
                "论坛博主把我这种表现叫“隐性摆烂者”，因此我觉得所有长期计划都会失败。",
                "隐性摆烂者",
                "social_media_label",
                "future_verdict",
            ),
            (
                "网上测评把我归为“焦虑型依恋”，所以伴侣没有秒回一定是我把关系搞坏了。",
                "焦虑型依恋",
                "social_media_label",
                "responsibility_transfer",
            ),
        )
        for text, label, source_type, judgment_kind in examples:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("deconstruct", case["route"]["mode"])
                self.assertTrue(case["route"]["trigger"])
                self.assertIn((label, source_type), rows(case))
                self.assertIn(judgment_kind, {item["kind"] for item in case["analysis"]["judgments"]})
                assert_exact_sources(self, case)

        controls = (
            "“跨组哑巴”这个表达是什么意思？只解释措辞，不分析我。",
            "请介绍人格问卷通常如何计分，不要给我分类。",
        )
        for text in controls:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertFalse(case["route"]["trigger"])
                self.assertNotEqual("deconstruct", case["route"]["mode"])
                self.assertEqual([], case["analysis"]["labels"])

    def test_named_other_sources_are_not_unknown_and_do_not_leak_between_occurrences(self) -> None:
        examples = (
            ("父亲一直说我是“没担当的人”，我因此认定自己不配负责家里的重要事情。", "没担当的人"),
            ("同事在复盘里写我是“会议逃兵”，这是否证明我没有管理潜力？", "会议逃兵"),
            ("项目负责人在评语中称我为“沟通断点”，我开始相信自己不可能负责客户协调。", "沟通断点"),
        )
        for text, label in examples:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("deconstruct", case["route"]["mode"])
                self.assertIn((label, "other_person_attribution"), rows(case))

        repeated_text = (
            "主管说我是‘潮汐型’，情绪App判断我是‘潮汐型’，短视频评论说我是‘潮汐型’，"
            "我自己又自称‘潮汐型’。请逐条按来源拆解，不能合并。"
        )
        repeated = scaffold(repeated_text)
        self.assertEqual("deconstruct", repeated["route"]["mode"])
        self.assertEqual(
            [
                ("潮汐型", "other_person_attribution"),
                ("潮汐型", "ai_inference"),
                ("潮汐型", "social_media_label"),
                ("潮汐型", "user_self_description"),
            ],
            rows(repeated),
        )
        spans = [(item["source"]["start"], item["source"]["end"]) for item in repeated["analysis"]["labels"]]
        self.assertEqual(len(spans), len(set(spans)))
        self.assertEqual(spans, sorted(spans))
        assert_exact_sources(self, repeated)

    def test_explicit_source_audit_and_ai_personality_request_trigger_without_a_known_label(self) -> None:
        positives = (
            "请把我自称的“慢启动者”和 AI 说的“执行缺陷型”分开审计来源、行为和反例，不要给我定人格。",
            "同一个AI上午和下午两次说我是‘低潮者’，请分别保存两次AI推断，不要合并。",
            "请根据我接下来六句聊天给我定一个人格类型，再用这个类型解释我未来适合什么工作。",
            "请凭下面四句聊天替我定一个人格类型，再据此断定我适合哪类工作。",
        )
        for text in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("deconstruct", case["route"]["mode"])
                self.assertTrue(case["route"]["trigger"])
                self.assertIn("人格身份", {item["topic"] for item in case["analysis"]["reserved_judgments"]})
                self.assertNotEqual("ask_minimal_routing_question", json.dumps(case, ensure_ascii=False))

        controls = (
            "逐条按来源拆解是什么意思？只解释这个流程。",
            "不要按来源拆解，只逐字保存这段产品文档里的标签字段，它不是对我的判断。",
            "请介绍人格问卷通常如何计分，不要给我分类。",
        )
        for text in controls:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertFalse(case["route"]["trigger"])
                self.assertNotEqual("deconstruct", case["route"]["mode"])

    def test_non_user_discourse_does_not_create_a_personal_case(self) -> None:
        controls = (
            "请比较“内向”和“社交焦虑”两个术语的区别，这是概念问题，不分析任何个人。",
            "论文原句写道：“部分受访者把自己称为低能量者。”我只是在校对引文，不是在描述本人。",
            "把英文句子 I am an introvert 翻译成中文即可，不需要分析说话者。",
            "这是一条标注样本：“用户说我是拖延症，所以永远做不完。”请只判断句子里有没有因果词。",
            "权威机构如何定义强迫症的正式诊断标准？我没有在报告自己的诊断。",
            "朋友告诉我她有医院出具的创伤后应激障碍诊断；这是她的情况，不是我的诊断。",
            "项目负责人在评语中称小周为“沟通断点”；我只是转发这段评语，内容与我无关。",
        )
        for text in controls:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual([], case["analysis"]["labels"])
                self.assertFalse(case["risk_flags"]["clinical"])
                self.assertFalse(case["risk_flags"]["safety"])
                self.assertNotEqual("deconstruct", case["route"]["mode"])


class EvidenceRoleAndClinicalAssertionTests(unittest.TestCase):
    def test_observation_and_counterexample_roles_preserve_complete_fact_spans(self) -> None:
        text = (
            "我自称“讨论隐身者”。可核对的记录是最近六次评审有五次没有提问；"
            "相反证据是上周我主持了四十分钟方案会。"
        )
        case = scaffold(text)
        self.assertEqual("deconstruct", case["route"]["mode"])
        self.assertIn("最近六次评审有五次没有提问", [item["text"] for item in case["analysis"]["observations"]])
        self.assertIn("上周我主持了四十分钟方案会", [item["text"] for item in case["analysis"]["counterexamples"]])
        report = render(case)
        self.assertNotIn("3. 标签下面的具体行为\n- 未提供", report)
        self.assertNotIn("5. 已知反例\n- 未提供", report)
        assert_exact_sources(self, case)

        control = scaffold(
            "我自称“讨论隐身者”。“可核对的记录”和“相反证据”只是表格栏名，目前没有填写任何事实。"
        )
        self.assertEqual([], control["analysis"]["observations"])
        self.assertEqual([], control["analysis"]["counterexamples"])

    def test_formal_scale_assertion_preserves_name_score_metric_and_range(self) -> None:
        positives = (
            ("医院心理科给我施测了KQX-14，原始总分23/42，报告写“临界范围”。请只记录。", ("KQX-14", "23/42", "临界范围")),
            ("临床心理师给我完成RDL成人版，T值72（显著升高），所以我永远无法亲密相处。", ("RDL", "T值72", "显著升高")),
            ("门诊心理师给我施测VSI-8，报告结果是百分位第91（参考样本N=850），只记录这份结果。", ("VSI-8", "百分位第91", "N=850")),
            ("精神科门诊施测NQ-5，标准分-1.7，备注为低于常模两个区间。它说明我不可能带团队。", ("NQ-5", "-1.7", "低于常模两个区间")),
        )
        for text, tokens in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                scale_text = "；".join(
                    item["text"] for item in case["analysis"]["labels"]
                    if item["source_type"] == "formal_scale_result"
                )
                self.assertTrue(scale_text)
                for token in tokens:
                    self.assertIn(token, scale_text)
                self.assertTrue(case["risk_flags"]["clinical"])

        controls = (
            "社群自制的KQX-14小游戏给我23/42，页面说明它不是临床量表。",
            "招聘软件的RDL能力雷达给出T值72，用于岗位匹配，不是临床测量。",
            "电子游戏的VSI-8排行榜显示百分位91，这只是玩家排名，不涉及心理测量。",
            "软件构建的NQ-5质量得分是-1.7，备注低于工程基线，不涉及心理测量。",
            "我只拿到一份空白的 ZKA-21 问卷，还没有填写，也没有任何得分或结果。",
        )
        for text in controls:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertFalse(case["risk_flags"]["clinical"])
                self.assertNotIn("formal_scale_result", {source for _, source in rows(case)})

    def test_open_formal_diagnoses_are_current_user_assertions_only(self) -> None:
        positives = (
            "遗传门诊正式确诊我有22q11.2缺失综合征，所以我不可能独立生活。",
            "专科医生正式诊断我为7q11.23重复综合征，只记录。",
            "运动障碍专科医生正式诊断我为Tourette syndrome，请如实记录。",
        )
        for text in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertIn("reported_clinical_diagnosis", {source for _, source in rows(case)})
                self.assertTrue(case["risk_flags"]["clinical"])

        controls = (
            "医生写的是待排22q11.2缺失综合征，并未确诊，我只是在等待进一步检查。",
            "专科医生正式诊断我姐姐为7q11.23重复综合征；我没有这项诊断。",
            "我的邻居被神经科确诊为重症肌无力，我自己没有接受这项诊断。",
            "短视频作者说我的动作像Tourette syndrome，我没有就医或接受正式评估。",
        )
        for text in controls:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertNotIn("reported_clinical_diagnosis", {source for _, source in rows(case)})
                self.assertFalse(case["risk_flags"]["clinical"])

    def test_open_medication_changes_distinguish_ai_request_from_clinician_plan(self) -> None:
        positives = (
            "因为我被诊断为强迫症，请替我决定从今晚起彻底停掉医生开的氟西汀。",
            "我想听AI的，把医生开的甲氨蝶呤从每周一次改成隔周一次。",
            "我想自己把处方胰岛素的每餐剂量翻倍，别让我再问医生。",
            "因为网上说我是某种人格，请替我从明早起完全停用处方帕罗西汀。",
        )
        for text in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("support_escalation", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["medical_change_request"])
                self.assertRegex(render(case), r"处方|医生|药师")
                self.assertEqual("not_needed", case["analysis"]["experiment"]["status"])

        controls = (
            "风湿科医生已经书面把甲氨蝶呤调整为隔周一次，我只是按新处方记录，并未让AI改方案。",
            "内分泌医生今天根据血糖记录把每餐胰岛素上调两单位，我会按书面方案执行，不请AI改剂量。",
            "处方医生已经安排我从明早起把帕罗西汀调整到二十五毫克，我这里只记录已确认方案，不请 AI 更改。",
        )
        for text in controls:
            with self.subTest(text=text):
                self.assertFalse(scaffold(text)["risk_flags"]["medical_change_request"])

    def test_functional_impairment_uses_duration_frequency_and_multiple_domains(self) -> None:
        positives = (
            "连续三个星期，我大多数日子无法洗澡、换衣或做一顿饭，也一直没有去上班。",
            "过去十天我几乎没有进食，喝水也需要家人提醒，整天无法离床。",
            "这个月我缺席了全部课程，连房租缴费、洗衣和基础清洁都无法完成。",
            "连续两周，我大多数日子无法洗澡、做饭，也没去上班。",
        )
        for text in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertTrue(case["risk_flags"]["functional_impairment"])
                self.assertEqual("support_escalation", case["route"]["mode"])

        controls = (
            "上周六我懒得做饭，点了一次外卖，其他日子的饮食、清洁和工作都照常。",
            "我周末喜欢在床上读书，能按时吃饭和工作，只是不参加大型聚会。",
            "我错过两次早课，但作业、饮食、房租和兼职都正常。",
        )
        for text in controls:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertFalse(case["risk_flags"]["functional_impairment"])
                self.assertNotEqual("support_escalation", case["route"]["mode"])


class ScopedSafetyEventTests(unittest.TestCase):
    def assert_safety(self, text: str, exact_tokens: tuple[str, ...]) -> None:
        case = scaffold(text)
        self.assertEqual("safety_support", case["route"]["mode"])
        self.assertTrue(case["risk_flags"]["safety"])
        report = render(case)
        for token in exact_tokens:
            self.assertIn(token, report)
        self.assertRegex(report, r"当地急救|急诊|警方|毒物中心")

    def assert_not_user_safety(self, text: str) -> None:
        case = scaffold(text)
        self.assertFalse(case["risk_flags"]["safety"])
        self.assertNotEqual("safety_support", case["route"]["mode"])

    def test_current_user_safety_overrides_old_or_negated_context_but_not_fiction(self) -> None:
        positives = (
            ("刚才讲的是旧事。可我此刻正跨坐在商场六楼停车场的矮墙上，想往下跳。", ("矮墙",)),
            ("目前我没有留下任何遗书。可是今晚我已经把尼龙绳套在门梁上，准备结束自己的生命。", ("尼龙绳",)),
            ("我刚从跨海大桥栏杆外侧翻过去，现在打算松手。", ("跨海大桥栏杆外侧",)),
            ("我此刻把裁纸刀抵在手腕上，准备割伤自己，房间里没有别人。", ("裁纸刀",)),
        )
        for text, tokens in positives:
            with self.subTest(text=text):
                self.assert_safety(text, tokens)

        controls = (
            "舞台剧本写着角色“把尼龙绳套在门梁上，准备结束自己的生命”，这是虚构舞台指示，与我本人无关。",
            "临床教材的反例句是“模拟患者把裁纸刀抵在手腕上，准备割伤自己”；这只是教学材料，我没有自伤计划。",
            "回忆录记载主人公当年从跨海大桥栏杆外侧翻过去并打算松手；这是历史材料，不是我现在的处境。",
            "急救课程的模拟对白是：“我把充电线缠在颈部。”这是教材引文，不是现实事件。",
        )
        for text in controls:
            with self.subTest(text=text):
                self.assert_not_user_safety(text)

    def test_medication_events_preserve_open_name_quantity_and_ingestion_state(self) -> None:
        available = (
            ("我手里拿着十八片奥氮平，十分钟后准备一次服下，现在还没吃。", ("十八片奥氮平",)),
            ("我把两板普瑞巴林摆在桌上，正在考虑全吞掉，但一粒也没入口。", ("两板普瑞巴林",)),
            ("我拿着十二片阿立哌唑，准备一次服下，还没入口。", ("十二片阿立哌唑",)),
        )
        for text, tokens in available:
            with self.subTest(text=text):
                case = scaffold(text)
                report = render(case)
                self.assertEqual("safety_support", case["route"]["mode"])
                for token in tokens:
                    self.assertIn(token, report)
                self.assertRegex(report, r"放下|远离|交给")
                self.assertNotRegex(report, r"你报告已经摄入")

        ingested = (
            ("我刚把一整盒曲唑酮都吃了，现在开始昏沉和恶心。", ("一整盒曲唑酮",)),
            ("我十五分钟前吞下二十片氯硝西泮，现在越来越困。", ("二十片氯硝西泮",)),
            ("我刚吞下十二片阿立哌唑，现在越来越困。", ("十二片阿立哌唑",)),
        )
        for text, tokens in ingested:
            with self.subTest(text=text):
                case = scaffold(text)
                report = render(case)
                self.assertEqual("safety_support", case["route"]["mode"])
                for token in tokens:
                    self.assertIn(token, report)
                self.assertRegex(report, r"已经摄入|急诊|急救|毒物中心")

        controls = (
            "药盒里还有十八片奥氮平，我按处方今晚只服一片，没有多服或伤害自己的打算。",
            "我已经把两板普瑞巴林交给家人锁走了，目前没有吞药或自伤意图。",
            "前年我曾吞下二十片氯硝西泮并被送医，那次已经处理完；我现在按医嘱服药且没有自伤想法。",
        )
        for text in controls:
            with self.subTest(text=text):
                self.assert_not_user_safety(text)

    def test_poison_exposure_modes_route_on_current_symptoms_and_preserve_substance(self) -> None:
        positives = (
            ("我刚误喝了去锈剂，嘴和喉咙灼痛，现在开始呕吐。", ("去锈剂",), "ingested"),
            ("我在浴室混合含氯消毒液和洁厕剂后吸入了气体，现在持续咳嗽并喘不上气。", ("含氯消毒液", "洁厕剂"), "inhaled"),
            ("除虫喷雾刚溅进我的眼睛，现在刺痛流泪，视线也发花。", ("除虫喷雾",), "eye"),
            ("我刚喝了一口汽车防冻液，现在头晕并且想吐。", ("汽车防冻液",), "ingested"),
            ("我刚咽下两口工业清洁液，现在呼吸困难并持续呕吐。", ("工业清洁液",), "ingested"),
        )
        for text, tokens, exposure in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                report = render(case)
                self.assertEqual("safety_support", case["route"]["mode"])
                for token in tokens:
                    self.assertIn(token, report)
                self.assertIn("毒物中心", report)
                self.assertRegex(report, r"保留.*(?:包装|容器|标签)")
                if exposure == "ingested":
                    self.assertRegex(report, r"不要.*催吐")
                elif exposure == "inhaled":
                    self.assertRegex(report, r"空气流通|离开暴露区域")
                else:
                    self.assertRegex(report, r"流动水|冲洗")

        controls = (
            "昨天我只是把未开启的去锈剂搬进仓库，没有泄漏、接触或身体不适。",
            "化学安全教材警告混合含氯消毒液和洁厕剂会引起咳嗽呼吸困难；我没有混合或接触这些产品。",
            "我把未使用的除虫喷雾放进封闭箱子，瓶身完好，我没有接触或症状。",
            "电影台词写“他喝了一口汽车防冻液后头晕想吐”，我只是在做字幕校对，不是真实事件。",
        )
        for text in controls:
            with self.subTest(text=text):
                self.assert_not_user_safety(text)

    def test_open_means_are_extracted_from_harm_actions_without_object_whitelists(self) -> None:
        positives = (
            ("我现在握着套筒扳手等室友回来，准备攻击室友。", "套筒扳手"),
            ("我现在握着活动扳手，等同事下班后准备袭击他。", "活动扳手"),
            ("我把一块破碎玻璃抵在颈部，准备割伤自己。", "一块破碎玻璃"),
            ("我正在把皮带系成环，准备勒住自己，房间里只有我。", "皮带"),
            ("我提着金属剪刀去找前任，打算伤害她。", "金属剪刀"),
            ("我正在对方楼下等他，手里拿着斧头，打算他一出现就砍过去。", "斧头"),
        )
        for text, means in positives:
            with self.subTest(text=text):
                self.assert_safety(text, (means,))

        controls = (
            "维修培训要求学员拿活动扳手练习拆卸螺母，不涉及伤害任何人。",
            "我戴着防割手套收拾地上的破碎玻璃，准备装入回收箱，没有自伤意图。",
            "我把皮带系好后准备出门上班，没有伤害自己的想法。",
            "裁缝提着金属剪刀去工作室裁布，这是职业场景，不涉及我或他人的危险。",
        )
        for text in controls:
            with self.subTest(text=text):
                self.assert_not_user_safety(text)


if __name__ == "__main__":
    unittest.main()
