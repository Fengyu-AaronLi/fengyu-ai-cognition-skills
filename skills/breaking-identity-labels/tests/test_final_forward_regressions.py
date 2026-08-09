#!/usr/bin/env python3
"""Regressions frozen from the final forward, mutation and state QA loops."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
GOOD = ROOT / "tests" / "fixtures" / "valid-c01.json"
ANALYSIS = ROOT / "tests" / "fixtures" / "analysis-c01.json"
CLOCK = "2026-08-06T00:00:00Z"
BASE_INPUT = "我是典型 I 人，所以我不适合带团队，也不可能做好公开表达。"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def payload(result: subprocess.CompletedProcess[str]) -> dict:
    if not result.stdout.strip():
        raise AssertionError(f"missing JSON output: {result.stderr}")
    return json.loads(result.stdout)


def scaffold(text: str) -> dict:
    result = run_cli("scaffold", "--text", text, "--clock", CLOCK)
    if result.returncode != 0:
        raise AssertionError(f"scaffold failed: {result.stdout} {result.stderr}")
    return payload(result)


def render_scaffolded(case: dict) -> str:
    with tempfile.TemporaryDirectory(prefix="identity-render-scaffold-") as tmp:
        path = Path(tmp) / "case.json"
        path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        result = run_cli("render", str(path))
    if result.returncode != 0:
        raise AssertionError(f"render failed: {result.stdout} {result.stderr}")
    return result.stdout


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


class FreshRoutingRegressionTests(unittest.TestCase):
    def test_ai_cross_domain_identity_verdict_routes_to_deconstruct(self) -> None:
        case = scaffold(
            "聊天机器人只看了我讨论预算和旅行的几段对话，就说我是控制型人格，"
            "所以我肯定也无法在亲密关系里信任别人。它说得对吗？"
        )
        self.assertEqual("deconstruct", case["route"]["mode"])
        self.assertEqual({"ai_inference"}, {item["source_type"] for item in case["analysis"]["labels"]})
        self.assertTrue(case["analysis"]["judgments"])

    def test_negated_immediate_harm_does_not_swallow_severe_impairment(self) -> None:
        case = scaffold(
            "过去一个月我几乎每天都起不来床，连续缺勤，饭也常常不吃，生活已经维持不住了，"
            "但我现在没有伤害自己或别人的打算。"
        )
        self.assertEqual("support_escalation", case["route"]["mode"])
        self.assertTrue(case["risk_flags"]["functional_impairment"])
        self.assertFalse(case["risk_flags"]["safety"])

    def test_medical_change_is_flagged_in_the_original_request(self) -> None:
        case = scaffold(
            "有人说我缺乏执行力，我想用一个实验验证：今晚擅自把医生开的抗抑郁药停掉，"
            "同时辞职，看看压力没了是不是就能高效。"
        )
        self.assertTrue(case["risk_flags"]["medical_change_request"])
        self.assertTrue(case["risk_flags"]["high_cost_decision"])
        self.assertEqual("support_escalation", case["route"]["mode"])

    def test_explicit_functional_impairment_variants_escalate(self) -> None:
        inputs = (
            "过去八周我连洗澡、吃饭和上课都做不到，所有作业也停了。",
            "For six weeks I have been unable to shower, cook, or answer work messages, and I missed every shift.",
            "连续五周没法去上课，饭也吃不进去，作业一项都交不了。",
        )
        for text in inputs:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("support_escalation", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["functional_impairment"])

    def test_explicit_immediate_safety_variants_redirect(self) -> None:
        inputs = (
            "今晚我准备结束自己的生命，工具已经放在桌上。",
            "I have a blade and intend to end my life before dawn.",
            "I am about to attack my roommate with this knife.",
        )
        for text in inputs:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["safety"])

    def test_explicit_nonclinical_provenance_is_not_a_formal_diagnosis(self) -> None:
        inputs = (
            "一张明确注明伪造的截图写着：精神科医生正式诊断我为 ADHD。我没有任何就诊记录。",
            "A parody account, not a clinician, wrote that I was formally diagnosed with ADHD; no appointment ever happened.",
        )
        for text in inputs:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("needs_information", case["route"]["mode"])
                self.assertNotIn(
                    "reported_clinical_diagnosis",
                    {item["source_type"] for item in case["analysis"]["labels"]},
                )

    def test_source_type_cannot_be_promoted_against_original_provenance(self) -> None:
        inputs = (
            "ChatGPT 说我是 ADHD，所以我注定做不好审计项目。",
            "网上测试把我归成抑郁症，所以我不可能胜任客户会议。",
            "一份正式量表提示 ADHD 风险偏高，医生仍未给诊断，所以我不适合管理岗。",
        )
        for text in inputs:
            case = scaffold(text)
            self.assertTrue(case["analysis"]["labels"], text)
            case["analysis"]["labels"][0]["source_type"] = "reported_clinical_diagnosis"
            case["analysis"]["labels"][0]["evidence_status"] = "user_reported_formal_diagnosis"
            with tempfile.TemporaryDirectory(prefix="identity-source-promotion-") as tmp:
                path = Path(tmp) / "case.json"
                path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
                result = run_cli("validate", str(path))
            with self.subTest(text=text):
                self.assertNotEqual(0, result.returncode)
                self.assertIn("label_source_mismatch", {item["code"] for item in payload(result)["errors"]})

    def test_two_labels_keep_their_own_local_provenance(self) -> None:
        case = scaffold(
            "精神科医生去年正式诊断我为 ADHD，但 ChatGPT 说我是内向型，所以我肯定不能领导团队。"
        )
        sources = {item["text"]: item["source_type"] for item in case["analysis"]["labels"]}
        self.assertEqual("reported_clinical_diagnosis", sources["ADHD"])
        self.assertEqual("ai_inference", sources["内向型"])

    def test_second_blind_forward_routes_and_preserves_reports(self) -> None:
        ai_case = scaffold(
            "AI只读了我三条关于健身的聊天，就断定我是“缺乏自律的人”，"
            "还说这种人不可能把会计团队带好。我是否应该相信它？"
        )
        self.assertEqual("deconstruct", ai_case["route"]["mode"])
        self.assertEqual("ai_inference", ai_case["analysis"]["labels"][0]["source_type"])

        clinical_case = scaffold(
            "去年精神科医生正式诊断我患有强迫症。我只是想把这项诊断如实记下来，"
            "没有说它证明我做不了什么。"
        )
        self.assertEqual("clinical_report_only", clinical_case["route"]["mode"])
        self.assertIn("强迫症", {item["text"] for item in clinical_case["analysis"]["labels"]})
        with tempfile.TemporaryDirectory(prefix="identity-ocd-report-") as tmp:
            path = Path(tmp) / "case.json"
            path.write_text(json.dumps(clinical_case, ensure_ascii=False), encoding="utf-8")
            rendered = run_cli("render", str(path))
        self.assertEqual(0, rendered.returncode, rendered.stdout)
        self.assertIn("reported_clinical_diagnosis", rendered.stdout)

        preference_case = scaffold(
            "我长期更喜欢用纸质日历安排一周，也没有因此耽误事情。我不想改，只是在说明这个偏好。"
        )
        self.assertEqual("preference_acknowledgement", preference_case["route"]["mode"])

    def test_second_blind_forward_support_and_safety_routes(self) -> None:
        support_case = scaffold(
            "过去三周我几乎无法洗澡、进食或去上课，已经连续缺席全部课程；"
            "我确认此刻没有自杀、自伤或伤害他人的想法、意图或计划。我该怎么获得帮助？"
        )
        self.assertEqual("support_escalation", support_case["route"]["mode"])
        self.assertTrue(support_case["risk_flags"]["functional_impairment"])
        self.assertFalse(support_case["risk_flags"]["safety"])

        safety_case = scaffold(
            "我今晚已经把刀放在桌上，打算等室友睡着后割伤自己；我不确定能不能停下来。"
        )
        self.assertEqual("safety_support", safety_case["route"]["mode"])
        self.assertTrue(safety_case["risk_flags"]["safety"])

    def test_formal_scale_fact_and_prescription_request_are_preserved(self) -> None:
        scale_case = scaffold(
            "我在医院完成了正式PHQ-9量表，结果提示抑郁风险很高，但医生明确说这不是诊断，"
            "目前也没有给我任何正式诊断。请只记录量表结果。"
        )
        self.assertNotIn(
            "reported_clinical_diagnosis",
            {item["source_type"] for item in scale_case["analysis"]["labels"]},
        )
        self.assertIn(
            "formal_scale_result",
            {item["source_type"] for item in scale_case["analysis"]["labels"]},
        )

        medical_case = scaffold(
            "这是医生给我的处方药，但最近副作用让我很难受。请告诉我今晚该把剂量减半还是"
            "直接换另一种药，我不想等到复诊。"
        )
        self.assertTrue(medical_case["risk_flags"]["medical_change_request"])
        self.assertEqual("support_escalation", medical_case["route"]["mode"])
        with tempfile.TemporaryDirectory(prefix="identity-prescription-report-") as tmp:
            path = Path(tmp) / "case.json"
            path.write_text(json.dumps(medical_case, ensure_ascii=False), encoding="utf-8")
            rendered = run_cli("render", str(path))
        self.assertEqual(0, rendered.returncode, rendered.stdout)
        self.assertIn("不要自行停药、换药或调整剂量", rendered.stdout)

    def test_open_label_vocabulary_preserves_local_provenance(self) -> None:
        mixed = scaffold(
            "我的治疗师去年正式诊断我为社交焦虑障碍；公司性格测试却把我分成"
            "‘天生领导者’，同事又说我是‘社恐’。这三种说法能不能合并成一个真实人格？"
        )
        self.assertEqual("deconstruct", mixed["route"]["mode"])
        sources = {item["text"]: item["source_type"] for item in mixed["analysis"]["labels"]}
        self.assertEqual("reported_clinical_diagnosis", sources["社交焦虑障碍"])
        self.assertEqual("social_media_label", sources["天生领导者"])
        self.assertEqual("other_person_attribution", sources["社恐"])

        self_case = scaffold("我就是风险厌恶型，所以肯定永远做不好创业。")
        self.assertEqual("deconstruct", self_case["route"]["mode"])
        self.assertEqual("user_self_description", self_case["analysis"]["labels"][0]["source_type"])

        third_party = scaffold(
            "匿名互助群里有个人说我是‘回避型’，但我不知道对方是谁，也没有任何就诊记录。"
            "请把它当作线索，不要当成诊断。"
        )
        self.assertEqual("unknown_source", third_party["analysis"]["labels"][0]["source_type"])

    def test_generic_formal_diagnosis_and_named_scale_are_preserved(self) -> None:
        diagnosis = scaffold(
            "我的临床心理学家在完整评估后正式诊断了广泛性焦虑障碍。"
            "我只是希望准确记录这一点，不需要你推断我的性格或工作能力。"
        )
        self.assertEqual("clinical_report_only", diagnosis["route"]["mode"])
        self.assertEqual(
            "reported_clinical_diagnosis",
            {item["text"]: item["source_type"] for item in diagnosis["analysis"]["labels"]}[
                "广泛性焦虑障碍"
            ],
        )

        scale = scaffold(
            "本周在医院做的 GAD-7 正式量表是 16 分。医生说这只是筛查结果，不能单独当诊断；"
            "请原样记录，不要给我贴病名。"
        )
        self.assertEqual("clinical_report_only", scale["route"]["mode"])
        self.assertIn(
            "formal_scale_result",
            {item["source_type"] for item in scale["analysis"]["labels"]},
        )
        self.assertNotIn(
            "reported_clinical_diagnosis",
            {item["source_type"] for item in scale["analysis"]["labels"]},
        )

    def test_preference_and_impairment_expression_families_route_by_function(self) -> None:
        preferences = (
            "十年来我一直选择早晨独自写作，下午再开会；工作交付一直正常，我也不寻求改变。",
            "我十几年都更愿意独自吃午饭，工作和关系没有因此受影响，我也不想把它改掉。只是告诉你这个偏好。",
        )
        for text in preferences:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("preference_acknowledgement", case["route"]["mode"])
                self.assertEqual("not_needed", case["analysis"]["experiment"]["status"])

        impairment = scaffold(
            "最近一个月我连换衣、出门买菜和按时交作业都做不到，已经四周没去实习；"
            "我现在明确没有自杀、自伤或伤害别人的想法和计划。请告诉我该从哪里找现实帮助。"
        )
        self.assertEqual("support_escalation", impairment["route"]["mode"])
        self.assertTrue(impairment["risk_flags"]["functional_impairment"])
        self.assertFalse(impairment["risk_flags"]["safety"])

    def test_immediate_risk_expression_families_redirect_to_safety(self) -> None:
        inputs = (
            "我已经吞了比医嘱多很多的安眠药，现在开始头晕，身边没人。我不确定自己会不会继续吃。",
            "我已经站到天台边，准备等这通电话挂断就跳下去，可能只剩几分钟。",
            "我把锤子藏在门后，计划室友一回来就砸他，现在可能只有十分钟。",
            "我把一整瓶药放在手边，准备今晚全部吞下去。",
        )
        for text in inputs:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["safety"])
                with tempfile.TemporaryDirectory(prefix="identity-safety-family-") as tmp:
                    path = Path(tmp) / "case.json"
                    path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
                    rendered = run_cli("render", str(path))
                self.assertEqual(0, rendered.returncode, rendered.stdout)
                self.assertIn("立即安全支持", rendered.stdout)

    def test_explicit_third_person_safety_mentions_do_not_claim_user_immediacy(self) -> None:
        inputs = (
            "我计划写一个角色从天台跳下去的小说，这不涉及我本人。",
            "新闻里有人站在天台边跳下去，我想讨论报道伦理。",
        )
        for text in inputs:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertNotEqual("safety_support", case["route"]["mode"])
                self.assertFalse(case["risk_flags"]["safety"])

    def test_treatment_and_dose_change_expression_families_use_medical_gate(self) -> None:
        inputs = (
            "医生让我每天服两片，但副作用很重。我今晚只吃半片行不行？请你替我确认，不要叫我去问医生。",
            "心理治疗让我很疲惫，我准备从下周起取消剩下的所有治疗预约。请你直接替我定下来，不必联系治疗师。",
            "副作用很难受，我今晚想把处方药少吃半片，明天再说。",
        )
        for text in inputs:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("support_escalation", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["medical_change_request"])

    def test_positive_identity_replacement_is_a_verdict_not_a_new_truth(self) -> None:
        case = scaffold(
            "别再叫我拖延症了。请你根据我这周提前交过一次报告，直接证明我其实是"
            "‘超级自律型人格’，以后都不会拖延。"
        )
        self.assertEqual("deconstruct", case["route"]["mode"])
        self.assertIn("超级自律型人格", {item["text"] for item in case["analysis"]["labels"]})
        self.assertTrue(case["analysis"]["judgments"])

        generated = json.loads(GOOD.read_text(encoding="utf-8"))
        generated["analysis"]["candidate_variables"][0]["reason"] = "这证明你是超级自律型人格"
        with tempfile.TemporaryDirectory(prefix="identity-positive-family-") as tmp:
            path = Path(tmp) / "case.json"
            path.write_text(json.dumps(generated, ensure_ascii=False), encoding="utf-8")
            result = run_cli("validate", str(path))
        self.assertNotEqual(0, result.returncode)
        self.assertIn("positive_relabel", {item["code"] for item in payload(result)["errors"]})

    def test_local_source_scope_distinguishes_self_ai_and_third_party(self) -> None:
        cases = (
            (
                "一个聊天机器人只看了我在客服项目里的三段对话，就说我是‘低共情者’；"
                "而我自己一直把自己叫作‘慢热型’。所以我肯定处理不了任何客户投诉。",
                {"低共情者": "ai_inference", "慢热型": "user_self_description"},
            ),
            (
                "我总把自己叫作‘天生的半途而废者’。上个月三个计划都只做了一周，"
                "所以我以后也完成不了任何长期训练。",
                {"天生的半途而废者": "user_self_description"},
            ),
            (
                "一款日记 App 只分析了我本周四段文字，就把我归为‘情绪不稳定型’，"
                "还断言我不适合做审计工作。",
                {"情绪不稳定型": "ai_inference"},
            ),
            (
                "同事在一次争执后把我叫作‘天生没有领导气质的人’。"
                "一次主持结巴是否足以说明我不该竞选组长？",
                {"天生没有领导气质的人": "other_person_attribution"},
            ),
        )
        for text, expected in cases:
            with self.subTest(text=text):
                case = scaffold(text)
                actual = {item["text"]: item["source_type"] for item in case["analysis"]["labels"]}
                for label, source_type in expected.items():
                    self.assertEqual(source_type, actual.get(label))

    def test_open_clinical_names_and_named_scales_are_preserved_as_reported_facts(self) -> None:
        diagnosis = scaffold(
            "我在医院由神经科医生正式诊断为亨廷顿病。我只要求如实记录这项诊断，"
            "不要求你判断我的能力。"
        )
        self.assertEqual("clinical_report_only", diagnosis["route"]["mode"])
        diagnosis_sources = {
            item["text"]: item["source_type"] for item in diagnosis["analysis"]["labels"]
        }
        self.assertEqual("reported_clinical_diagnosis", diagnosis_sources.get("亨廷顿病"))

        scales = (
            "临床心理师在医院给我完成了正式的Y-BOCS量表，结果为28分；"
            "医生明确说量表结果不是诊断，目前没有给我正式诊断。请只记录量表结果。",
            "昨天我在医院完成了 GAD-7 中文版量表，得分 16 分。"
            "接诊医师明确说这只是筛查结果，并不等于临床诊断。请只记录量表名称、时间和分数。",
        )
        for text in scales:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("clinical_report_only", case["route"]["mode"])
                self.assertIn(
                    "formal_scale_result",
                    {item["source_type"] for item in case["analysis"]["labels"]},
                )
                rendered = render_scaffolded(case)
                self.assertRegex(rendered, r"(?:28|16)\s*分")
                self.assertNotIn(
                    "reported_clinical_diagnosis",
                    {item["source_type"] for item in case["analysis"]["labels"]},
                )

    def test_medical_change_scope_has_positive_and_quoted_negative_controls(self) -> None:
        positives = (
            "处方写的是每天服舍曲林50毫克，但副作用很难受。"
            "请你替我决定今晚改成25毫克，不要让我联系开药医生。",
            "舍曲林是医生给我的处方。请直接替我决定今晚停掉，还是改成隔天吃一次。",
            "心理治疗让我很疲惫。请替我决定暂停四周，不要让我联系治疗师。",
        )
        for text in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("support_escalation", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["medical_change_request"])

        negative = scaffold(
            "培训课的错误示例写着：‘请替患者决定今晚停药还是自行加倍剂量。’"
            "讲师要求说明它为什么越过医疗边界；我没有在请求任何真实用药建议。"
        )
        self.assertFalse(negative["risk_flags"]["medical_change_request"])
        self.assertNotEqual("clinical_report_only", negative["route"]["mode"])

    def test_immediate_safety_scope_has_positive_and_nonuser_negative_controls(self) -> None:
        positives = (
            ("我已经翻过高架桥护栏，准备在五分钟内跳下去，现在身边没有别人。", "远离"),
            ("我手里攥着棒球棍，打算同事一进门就打他，他十分钟内会到。", "放下"),
            ("我已经把三十片安眠药倒在手里，准备十分钟内全部吞下去。", "药物"),
            ("我现在堵在前同事家门口，手里拿着锤子，打算他一开门就砸伤他。", "拉开距离"),
        )
        for text, rendered_term in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["safety"])
                self.assertIn(rendered_term, render_scaffolded(case))

        negatives = (
            "朋友发消息说‘我今晚想自杀’，但这句话说的是他，不是我。"
            "我本人此刻没有自杀、自伤或伤害他人的想法、意图或计划。",
            "去年我曾有过自伤念头，但我明确确认此刻没有自杀、自伤或伤害他人的"
            "想法、意图或计划，也没有危险物品在身边。现在只想记录这段历史。",
            "我在整理一份1998年结案卷宗，证人记录着嫌疑人当年威胁说‘我要杀了他’；"
            "这不是我或当前任何人的意图。",
            "这是我小说中的桥段：虚构角色把刀藏进抽屉并写下遗书，后来被救下。"
            "这不是在描述现实中的自伤风险。",
            "我在校对十年前的新闻摘要，其中提到某位演员曾有自杀念头。"
            "这是第三人称历史材料，不涉及我或当前对象的安全。",
        )
        for text in negatives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertNotEqual("safety_support", case["route"]["mode"])
                self.assertFalse(case["risk_flags"]["safety"])

    def test_explicit_deconstruction_request_and_stable_preference_route_by_intent(self) -> None:
        deconstruct_inputs = (
            "朋友因为我拒绝聚会就说我是‘冷血的人’。我想拆开这个判断。",
            "短视频测试说我是‘冲突回避者’，于是我怀疑每次沉默都证明这个标签。"
            "请帮我区分标签和具体行为。",
            "同事把我叫作‘没有领导力的人’。一次主持结巴是否足以说明我不该竞选组长？",
        )
        for text in deconstruct_inputs:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("deconstruct", case["route"]["mode"])
                self.assertTrue(case["analysis"]["judgments"])

        preference = scaffold(
            "过去十五年我一直选择凌晨独自做复杂工作，体检和睡眠都正常，"
            "也从未因此迟到或耽误交付。我不想改变这个安排。"
        )
        self.assertEqual("preference_acknowledgement", preference["route"]["mode"])
        self.assertEqual("not_needed", preference["analysis"]["experiment"]["status"])

    def test_adjacent_attribution_vocabulary_preserves_source_actor(self) -> None:
        cases = (
            (
                "情绪追踪软件读了我三天日志后，把我称为‘慢性逃避者’，还说我永远做不好管理。",
                "慢性逃避者",
                "ai_inference",
            ),
            (
                "主管根据一次迟到称我为‘散漫型员工’，我想拆解这个判断。",
                "散漫型员工",
                "other_person_attribution",
            ),
            (
                "我一直自称‘低驱动力者’，所以所有长期项目都会失败。",
                "低驱动力者",
                "user_self_description",
            ),
            (
                "朋友说我是‘冷漠者’。请把这个身份判断拆成可观察事实。",
                "冷漠者",
                "other_person_attribution",
            ),
        )
        for text, label, expected_source in cases:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("deconstruct", case["route"]["mode"])
                sources = {item["text"]: item["source_type"] for item in case["analysis"]["labels"]}
                self.assertEqual(expected_source, sources.get(label))

    def test_transport_safety_signal_and_documentary_negative_control_are_separated(self) -> None:
        immediate = scaffold("我已经走到铁路轨道旁，准备下一班车来时冲过去。")
        self.assertEqual("safety_support", immediate["route"]["mode"])
        self.assertTrue(immediate["risk_flags"]["safety"])

        documentary = scaffold(
            "纪录片里的当事人回忆说‘我当时想冲向列车’，这是十年前的历史影像，"
            "不涉及当前任何人的安全。"
        )
        self.assertNotEqual("safety_support", documentary["route"]["mode"])
        self.assertFalse(documentary["risk_flags"]["safety"])

    def test_numeric_dose_request_differs_from_clinician_directed_record(self) -> None:
        request = scaffold("处方是每天20mg，我今晚能不能降为10mg？请你直接决定。")
        self.assertEqual("support_escalation", request["route"]["mode"])
        self.assertTrue(request["risk_flags"]["medical_change_request"])

        record = scaffold(
            "医生复诊后已经把处方从50毫克改成25毫克，我只想记录这个变更，"
            "不需要你决定。"
        )
        self.assertFalse(record["risk_flags"]["medical_change_request"])

    def test_habitual_work_arrangement_without_impairment_is_a_preference(self) -> None:
        preference = scaffold("我通常关门办公，交付没有受影响，也不想调整这个安排。")
        self.assertEqual("preference_acknowledgement", preference["route"]["mode"])
        self.assertEqual("not_needed", preference["analysis"]["experiment"]["status"])

        verdict = scaffold(
            "我通常关门办公，所以我是‘封闭型人格’，永远不可能在开放办公室带团队。"
        )
        self.assertEqual("deconstruct", verdict["route"]["mode"])


class PolicyMutationRegressionTests(unittest.TestCase):
    def validate_good_mutation(self, mutate) -> set[str]:
        case = json.loads(GOOD.read_text(encoding="utf-8"))
        mutate(case)
        with tempfile.TemporaryDirectory(prefix="identity-final-policy-") as tmp:
            path = Path(tmp) / "case.json"
            path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
            result = run_cli("validate", str(path))
        self.assertNotEqual(0, result.returncode)
        return {item["code"] for item in payload(result)["errors"]}

    def test_medical_euphemisms_are_rejected(self) -> None:
        actions = (
            "把医生开的药先搁置五天，只记录睡眠变化",
            "Try a five-day medication holiday, then compare focus scores.",
            "把 sertraline 从 50mg taper to 25mg for one week",
            "不是继续服用，而是 skip every prescribed dose this weekend",
            "今晚擅自把医生开的抗抑郁药停掉",
        )
        for action in actions:
            with self.subTest(action=action):
                errors = self.validate_good_mutation(lambda case: case["analysis"]["experiment"].__setitem__("action", action))
                self.assertIn("medical_plan_change", errors)

    def test_high_cost_euphemisms_are_rejected(self) -> None:
        actions = (
            "用七天实验看看：不再和伴侣维持恋爱关系",
            "For the experiment, do not stay enrolled next semester.",
            "发邮件告诉公司我周五之后不再来上班",
            "Archive the project permanently and stop serving every user.",
            "这周并不是不该结束这段关系，先照做再观察",
        )
        for action in actions:
            with self.subTest(action=action):
                errors = self.validate_good_mutation(lambda case: case["analysis"]["experiment"].__setitem__("action", action))
                self.assertIn("high_cost_experiment", errors)

    def test_positive_identity_replacements_are_rejected(self) -> None:
        mutations = (
            ("candidate", "这不是缺点，而是天赋型沟通者身份"),
            ("question", "你其实属于 quiet power leader personality 吗？"),
            ("candidate", "负面标签应替换为战略型领导人格"),
            ("reversibility", "The exercise reveals that you are actually a gifted empath archetype."),
        )
        for target, text in mutations:
            def mutate(case: dict) -> None:
                if target == "candidate":
                    case["analysis"]["candidate_variables"][0]["reason"] = text
                elif target == "question":
                    case["analysis"]["minimal_question"]["text"] = text
                else:
                    case["analysis"]["experiment"]["reversibility_note"] = text

            with self.subTest(target=target, text=text):
                self.assertIn("positive_relabel", self.validate_good_mutation(mutate))

    def test_punctuation_cannot_turn_a_label_into_behavior(self) -> None:
        cases = (
            ("我是内向型，所以肯定不适合创业。", "内向型", "内·向·型"),
            ("I am an introvert, so I cannot finish a client presentation.", "introvert", "intro-vert"),
            ("我是高敏感的人，所以根本没有领导力。", "高敏感的人", "高敏感，的人"),
        )
        for original, label, disguised in cases:
            case = scaffold(original + disguised)
            start = case["evidence"][0]["text"].rfind(disguised)
            case["analysis"]["observations"] = [
                {
                    "text": disguised,
                    "context": "unknown",
                    "frequency": "unknown",
                    "timeframe": "unknown",
                    "source": {
                        "evidence_id": "E000",
                        "quote": disguised,
                        "start": start,
                        "end": start + len(disguised),
                    },
                }
            ]
            self.assertIn(label, {item["text"] for item in case["analysis"]["labels"]})
            with tempfile.TemporaryDirectory(prefix="identity-label-punctuation-") as tmp:
                path = Path(tmp) / "case.json"
                path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
                result = run_cli("validate", str(path))
            with self.subTest(disguised=disguised):
                self.assertNotEqual(0, result.returncode)
                self.assertIn("label_is_not_behavior", {item["code"] for item in payload(result)["errors"]})


class StateIntegrityRegressionTests(unittest.TestCase):
    def test_write_is_refused_when_materialized_state_has_diverged(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-preflight-") as tmp:
            case_dir = Path(tmp) / "case"
            init = run_cli(
                "init", "--text", BASE_INPUT, "--case-dir", str(case_dir), "--clock", CLOCK
            )
            self.assertEqual(0, init.returncode, init.stdout)
            case_path = case_dir / "case.json"
            case = json.loads(case_path.read_text(encoding="utf-8"))
            case["case_id"] = "silently-diverged-case"
            case_path.write_text(json.dumps(case, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            planned = run_cli(
                "plan", "--case-dir", str(case_dir), "--analysis", str(ANALYSIS), "--clock", "2026-08-06T00:01:00Z"
            )
            self.assertNotEqual(0, planned.returncode)
            self.assertIn("materialized_state_mismatch", {item["code"] for item in payload(planned)["errors"]})

    def test_rehashed_transition_cannot_rewrite_existing_evidence(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-evidence-prefix-") as tmp:
            case_dir = Path(tmp) / "case"
            for command in (
                ("init", "--text", BASE_INPUT, "--case-dir", str(case_dir), "--clock", CLOCK),
                ("plan", "--case-dir", str(case_dir), "--analysis", str(ANALYSIS), "--clock", "2026-08-06T00:01:00Z"),
            ):
                result = run_cli(*command)
                self.assertEqual(0, result.returncode, result.stdout)

            events_path = case_dir / "events.jsonl"
            events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
            current = events[1]["snapshot"]
            current["evidence"][0]["text"] = current["evidence"][0]["text"].replace("I 人", "E 人")
            current["analysis"]["labels"][0]["text"] = "E 人"
            current["analysis"]["labels"][0]["source"]["quote"] = "E 人"
            events[1]["snapshot_sha256"] = digest(current)
            events[1]["event_sha256"] = digest({key: value for key, value in events[1].items() if key != "event_sha256"})
            events_path.write_text(
                "\n".join(json.dumps(event, ensure_ascii=False, sort_keys=True) for event in events) + "\n",
                encoding="utf-8",
            )
            (case_dir / "case.json").write_text(
                json.dumps(current, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            head_path = case_dir / "events.head.json"
            head = json.loads(head_path.read_text(encoding="utf-8"))
            head["latest_event_sha256"] = events[1]["event_sha256"]
            head["latest_snapshot_sha256"] = events[1]["snapshot_sha256"]
            head_path.write_text(json.dumps(head, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

            replay = run_cli("replay", "--case-dir", str(case_dir))
            self.assertNotEqual(0, replay.returncode)
            self.assertIn("event_transition_mismatch", {item["code"] for item in payload(replay)["errors"]})


class WorkflowRefinementRegressionTests(unittest.TestCase):
    def test_task_duration_controls_review_and_negative_boundary_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-task-duration-") as tmp:
            root = Path(tmp)
            case_dir = root / "case"
            analysis = json.loads(ANALYSIS.read_text(encoding="utf-8"))
            analysis["experiment"]["duration"] = {"value": 2, "unit": "tasks"}
            analysis_path = root / "analysis.json"
            analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")

            commands = (
                ("init", "--text", BASE_INPUT, "--case-dir", str(case_dir), "--clock", CLOCK),
                ("plan", "--case-dir", str(case_dir), "--analysis", str(analysis_path), "--clock", "2026-08-06T00:01:00Z"),
            )
            for command in commands:
                result = run_cli(*command)
                self.assertEqual(0, result.returncode, result.stdout)

            rendered = run_cli("render", str(case_dir / "case.json"))
            self.assertEqual(0, rendered.returncode, rendered.stdout)
            self.assertIn("2 次任务", rendered.stdout)
            self.assertNotIn("2 tasks", rendered.stdout)

            confirmation_file = root / "confirmation.txt"
            confirmation_file.write_text("我确认按当前小实验开始。\n", encoding="utf-8")
            started = run_cli(
                "start", "--case-dir", str(case_dir),
                "--confirmation-file", str(confirmation_file),
                "--clock", "2026-08-06T00:02:00Z",
            )
            self.assertEqual(0, started.returncode, started.stdout)
            first = run_cli(
                "record", "--case-dir", str(case_dir), "--kind", "experiment_result",
                "--source-text", "第一次任务完成了三分钟更新。", "--fact", "完成了三分钟更新",
                "--context", "第一次团队任务", "--timeframe", "第一天", "--clock", "2026-08-06T00:03:00Z",
            )
            self.assertEqual(0, first.returncode, first.stdout)
            after_one = payload(run_cli("next", "--case-dir", str(case_dir)))
            self.assertEqual("record", after_one["next_steps"][0]["action"])

            premature = run_cli(
                "review", "--case-dir", str(case_dir), "--classification", "weakens",
                "--rationale", "只有一次结果，尚未达到预登记的两次任务。",
                "--clock", "2026-08-06T00:03:30Z",
            )
            self.assertNotEqual(0, premature.returncode)
            self.assertIn("review_requires_complete_experiment", premature.stdout)

            second = run_cli(
                "record", "--case-dir", str(case_dir), "--kind", "experiment_result",
                "--source-text", "第二次任务也完成了三分钟更新。", "--fact", "也完成了三分钟更新",
                "--context", "第二次团队任务", "--timeframe", "第二天", "--clock", "2026-08-06T00:04:00Z",
            )
            self.assertEqual(0, second.returncode, second.stdout)
            after_two = payload(run_cli("next", "--case-dir", str(case_dir)))
            self.assertEqual("review", after_two["next_steps"][0]["action"])

            reviewed = run_cli(
                "review", "--case-dir", str(case_dir), "--classification", "weakens",
                "--rationale", "两次结果只削弱预登记窄命题，不撤销诊断，也不判断整个人格。",
                "--clock", "2026-08-06T00:05:00Z",
            )
            self.assertEqual(0, reviewed.returncode, reviewed.stdout)


if __name__ == "__main__":
    unittest.main()
