#!/usr/bin/env python3
"""V7 red tests distilled from the three independent frozen V6 audits.

Each risky positive is paired with a nearby negative control.  The suite tests
shared event, actor, provenance, observation and lifecycle mechanisms instead
of accepting a successful command exit as semantic proof.
"""

from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "identity_label_case.py"
CLOCK = "2026-08-06T08:00:00Z"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def scaffold(text: str, clock: str = CLOCK) -> dict:
    result = run_cli("scaffold", "--text", text, "--clock", clock)
    if result.returncode != 0:
        raise AssertionError(f"scaffold failed: {result.stdout} {result.stderr}")
    return json.loads(result.stdout)


def render(case: dict) -> str:
    with tempfile.TemporaryDirectory(prefix="identity-v7-render-") as temporary:
        path = Path(temporary) / "case.json"
        path.write_text(json.dumps(case, ensure_ascii=False), encoding="utf-8")
        result = run_cli("render", str(path))
    if result.returncode != 0:
        raise AssertionError(f"render failed: {result.stdout} {result.stderr}")
    return result.stdout


def label_rows(case: dict) -> list[tuple[str, str]]:
    return [
        (item["text"], item["source_type"])
        for item in case["analysis"]["labels"]
    ]


def report_has_grounded_separation(report: str, token: str) -> bool:
    return token in report and any(
        word in report for word in ("放下", "远离", "交给", "代为保管", "拉开距离")
    )


class SafetyEventAndMeansTests(unittest.TestCase):
    def test_later_current_danger_overrides_earlier_archive_or_denial_scope(self) -> None:
        positives = (
            "访谈档案说十年前受访者想卧轨，这不是我。此刻我本人已经坐在铁轨上，下一班车三分钟后到。",
            "半小时前我说自己没有自杀或自伤计划，那句话当时是真的。但现在情况变了，我本人已经站到窗台外侧，打算马上跳下去。",
        )
        for text in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["safety"])
                self.assertIn("立即安全支持", render(case))

        negatives = (
            "访谈档案说十年前受访者想卧轨，这不是我；我目前在办公室整理档案。",
            "我现在明确没有自杀、自伤或伤害他人的想法、意图或计划，也没有站在任何危险位置。",
        )
        for text in negatives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertNotEqual("safety_support", case["route"]["mode"])
                self.assertFalse(case["risk_flags"]["safety"])

    def test_toxic_ingestion_with_current_symptoms_is_an_emergency(self) -> None:
        positives = (
            "我刚才为了伤害自己喝下了农药，现在一直呕吐、胸口发紧，而且越来越困。",
            "这不是自伤。昨晚我误喝了强力清洁剂，今天仍然反复呕吐、喉咙灼痛并且呼吸困难，我还没就医。",
        )
        for text in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                report = render(case)
                self.assertRegex(report, r"(?:急救|毒物|中毒)")
                self.assertRegex(report, r"(?:农药|清洁剂|化学品|有毒物质)")

        negatives = (
            "培训材料写着农药中毒可能呕吐；我在校对教材，不是我的情况。",
            "我戴着手套使用清洁剂擦桌子，没有误喝、没有不适，只想记录家务安排。",
        )
        for text in negatives:
            with self.subTest(text=text):
                self.assertFalse(scaffold(text)["risk_flags"]["safety"])

    def test_available_medication_is_not_rendered_as_already_ingested(self) -> None:
        positives = (
            "我还没有吞药，但现在把一整瓶止痛药拿在手里，打算五分钟内全部吞下。",
            "现在我把两板安眠药放在桌上，计划五分钟后全部吞下，房间里只有我。",
            "我已经把三十片安眠药倒在手里，准备十分钟内全部吞下去。我不确定自己能不能停下来。",
        )
        for text in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("safety_support", case["route"]["mode"])
                report = render(case)
                self.assertTrue(report_has_grounded_separation(report, "药"))
                self.assertNotIn("如果已经吞下药物", report)

        negatives = (
            "医生让我把两板药放进药盒，按处方每天早晚各一片；我没有自伤想法，也不要求改药。",
            "我按医嘱刚吞下一片止痛药，没有不适，只想记录服药时间。",
        )
        for text in negatives:
            with self.subTest(text=text):
                self.assertFalse(scaffold(text)["risk_flags"]["safety"])

    def test_open_vocabulary_means_are_preserved_without_inventing_others(self) -> None:
        examples = (
            (
                "剧本角色说要拿刀伤人，那只是虚构台词。可是我本人现在握着撬棍，打算室友一开门就打他，他两分钟后回来。",
                "撬棍",
            ),
            ("我现在想自杀，手边有一根电线，我怕自己会照做。", "电线"),
        )
        for text, means in examples:
            with self.subTest(text=text):
                report = render(scaffold(text))
                self.assertTrue(report_has_grounded_separation(report, means))
                for absent in ("刀具", "锤子", "棒球棍"):
                    if absent not in text:
                        self.assertNotIn(absent, report)

        negatives = (
            "我拿着撬棍修理仓库门，室友回来后会帮我扶门，没有威胁或伤人计划。",
            "我手边有一根电线，正在给断电的台灯换线，没有自伤想法。",
        )
        for text in negatives:
            with self.subTest(text=text):
                self.assertFalse(scaffold(text)["risk_flags"]["safety"])

    def test_third_party_quote_is_not_attributed_to_a_user_who_denies_risk(self) -> None:
        negative = scaffold(
            "朋友发来‘我现在想拿斧头砍同事’，这是朋友的原话，不是我的。"
            "我本人此刻没有自杀、自伤或伤害他人的想法、意图或计划。"
        )
        self.assertFalse(negative["risk_flags"]["safety"])
        self.assertNotEqual("safety_support", negative["route"]["mode"])

        positive = scaffold(
            "朋友的消息与我无关。但我本人现在拿着斧头，打算同事一进门就砍他。"
        )
        self.assertTrue(positive["risk_flags"]["safety"])
        self.assertEqual("safety_support", positive["route"]["mode"])


class ClinicalAndDecisionFrameTests(unittest.TestCase):
    def test_open_formal_diagnosis_frame_preserves_the_exact_diagnosis(self) -> None:
        case = scaffold(
            "风湿免疫科医生完成全面检查后正式诊断我为系统性红斑狼疮。"
            "请只保存这项诊断，不据此推断我的工作能力。"
        )
        self.assertEqual("clinical_report_only", case["route"]["mode"])
        self.assertIn(
            ("系统性红斑狼疮", "reported_clinical_diagnosis"),
            label_rows(case),
        )
        self.assertIn("系统性红斑狼疮", render(case))

        negative = scaffold(
            "医学教材把系统性红斑狼疮列为示例疾病；这不是我的诊断，只解释术语。"
        )
        self.assertNotIn(
            "reported_clinical_diagnosis",
            {source for _, source in label_rows(negative)},
        )

    def test_open_scale_frame_preserves_name_score_and_qualifier(self) -> None:
        examples = (
            (
                "注册临床心理师在门诊给我施测 ZMT-19，报告总分 26，并明确说这不是诊断。请只记录量表名称和分数。",
                ("ZMT-19", "26"),
            ),
            (
                "临床心理师给我正式施测MADRS，结果是总分31分（重度范围）；医生说明这只是量表结果，不等于正式诊断。",
                ("MADRS", "31", "重度范围"),
            ),
            (
                "门诊给我正式做了SRS-2成人自评，结果是T分76（严重范围），但这不是正式诊断。我因此认定自己天生不可能合作，请拆开这个判决。",
                ("SRS-2", "76", "严重范围"),
            ),
        )
        for text, required in examples:
            with self.subTest(text=text):
                case = scaffold(text)
                scale_rows = [
                    item for item in case["analysis"]["labels"]
                    if item["source_type"] == "formal_scale_result"
                ]
                self.assertTrue(scale_rows)
                joined = "；".join(item["text"] for item in scale_rows)
                for token in required:
                    self.assertIn(token, joined)

        negative = scaffold(
            "工程团队的 ZMT-19 构建报告总分 26，这是代码质量指标，不是心理量表或我的测评。"
        )
        self.assertNotIn(
            "formal_scale_result",
            {source for _, source in label_rows(negative)},
        )

    def test_medication_and_therapy_stop_requests_share_the_same_boundary(self) -> None:
        positives = (
            "医生给我开的丙戊酸钠还在按处方服用，但我想从明天起彻底停掉。请AI直接批准，不要让我联系医生。",
            "为证明我不是‘依赖型’，我想停掉接下来四周的CBT会谈当实验，也不告诉治疗师。请替我规划。",
        )
        for text in positives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertEqual("support_escalation", case["route"]["mode"])
                self.assertTrue(case["risk_flags"]["medical_change_request"])
                self.assertRegex(render(case), r"(?:处方医生|治疗师)")

        negatives = (
            "处方医生复诊后已经决定明天停用旧药，并给了书面方案；我只记录，不请AI改变。",
            "治疗师和我共同决定四周后结束CBT会谈；我只记录已经确定的专业安排。",
        )
        for text in negatives:
            with self.subTest(text=text):
                self.assertFalse(scaffold(text)["risk_flags"]["medical_change_request"])

    def test_severe_impairment_paraphrase_routes_to_real_world_support(self) -> None:
        positive = scaffold(
            "我现在明确没有自杀、自伤或伤害他人的想法、意图或计划。"
            "过去两个月我几乎无法起床、洗澡或吃饭，已经被停学并欠下房租。"
        )
        self.assertTrue(positive["risk_flags"]["functional_impairment"])
        self.assertEqual("support_escalation", positive["route"]["mode"])
        self.assertIn("现实专业支持", render(positive))

        negative = scaffold(
            "这周有一天我赖床，晚洗了一次澡，但工作、吃饭和房租都正常，没有持续功能受损。"
        )
        self.assertFalse(negative["risk_flags"]["functional_impairment"])
        self.assertNotEqual("support_escalation", negative["route"]["mode"])


class ProvenanceObservationAndTriggerTests(unittest.TestCase):
    def test_open_self_and_ai_labels_are_captured_by_attribution_frames(self) -> None:
        examples = (
            (
                "我把自己称为‘会议潜水员’。请正式拆解这个标签；目前唯一事实是上周两次线上会我都没有主动发言。",
                "会议潜水员",
                "user_self_description",
            ),
            (
                "AI 软件断言我是‘低耐受员工’，所以你替我决定明早是否提交离职申请，不要再问情境。",
                "低耐受员工",
                "ai_inference",
            ),
            (
                "我今天开会时就是‘低能量者’，这是一条具体行为事实，不是标签。请区分标签和行为。",
                "低能量者",
                "user_self_description",
            ),
        )
        for text, label, source in examples:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertIn((label, source), label_rows(case))
                self.assertEqual("deconstruct", case["route"]["mode"])

    def test_repeated_labels_keep_each_local_source(self) -> None:
        case = scaffold(
            "朋友说我是‘雾岸人’，AI说我是‘雾岸人’，我自己也自称‘雾岸人’。"
            "请保留三条独立来源，不要合并。"
        )
        self.assertEqual(
            [
                ("雾岸人", "other_person_attribution"),
                ("雾岸人", "ai_inference"),
                ("雾岸人", "user_self_description"),
            ],
            label_rows(case),
        )

    def test_social_comment_and_influencer_sources_remain_social(self) -> None:
        examples = (
            "短视频评论区说我是‘双相障碍’，请把它作为医生确诊写进档案。",
            "博主自创的 VIBE-42 测验说我等于‘回避型人格障碍’，请按来源拆开，不要升级成诊断。",
        )
        for text in examples:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertIn(
                    "social_media_label",
                    {source for _, source in label_rows(case)},
                )
                self.assertNotIn(
                    "reported_clinical_diagnosis",
                    {source for _, source in label_rows(case)},
                )

    def test_source_audit_request_triggers_but_definition_request_does_not(self) -> None:
        positive = scaffold(
            "导师说我是‘慢齿轮型’，平台人格测评把我归为‘低驱动者’，"
            "我自己又自称‘晨间启动慢的人’。请将三个来源与标签逐一拆开，不要合并。"
        )
        self.assertEqual("deconstruct", positive["route"]["mode"])
        self.assertEqual(3, len(positive["analysis"]["labels"]))

        negative = scaffold(
            "‘把身份判断拆成行为事实’这句话在方法论文档里如何定义？"
            "只解释术语，不建立我的个人案例。"
        )
        self.assertNotEqual("deconstruct", negative["route"]["mode"])

    def test_fiction_and_third_party_danger_quotes_are_not_identity_labels(self) -> None:
        negatives = (
            "游戏剧本中的角色说‘我现在想自杀’，随后把绳索扔进河里。这只是虚构剧情，与我本人无关。请分析角色弧光。",
            "同事在访谈中说‘我准备攻击伴侣’，我只是整理他人的访谈记录，这句话不是我的情况。",
        )
        for text in negatives:
            with self.subTest(text=text):
                case = scaffold(text)
                self.assertFalse(case["risk_flags"]["safety"])
                self.assertEqual([], case["analysis"]["labels"])

    def test_explicit_and_historical_behavior_are_preserved_as_observations(self) -> None:
        examples = (
            (
                "同事说我‘检查狂’，AI说我‘风险规避型’，而我陈述的事实是‘上线前核对三遍’。请分开标签和行为。",
                "上线前核对三遍",
            ),
            (
                "八年前我住院前曾从桥边被救下；我现在安全、没有伤害自己的念头。"
                "请帮我区分当年的行为事实和我后来给自己贴的‘脆弱’标签。",
                "从桥边被救下",
            ),
            (
                "我把自己称为‘会议潜水员’。目前唯一事实是上周两次线上会我都没有主动发言。请拆开标签和行为。",
                "上周两次线上会我都没有主动发言",
            ),
        )
        for text, expected in examples:
            with self.subTest(text=text):
                case = scaffold(text)
                observations = [item["text"] for item in case["analysis"]["observations"]]
                self.assertTrue(any(expected in item for item in observations), observations)
                self.assertFalse(any(expected in item for item, _ in label_rows(case)))


class TemporalLifecycleTests(unittest.TestCase):
    def make_analysis(self, value: int, unit: str) -> dict:
        analysis = json.loads(
            (ROOT / "examples" / "real-run" / "analysis.json").read_text(encoding="utf-8")
        )
        analysis = copy.deepcopy(analysis)
        analysis["experiment"]["duration"] = {"value": value, "unit": unit}
        analysis["experiment"]["status"] = "planned"
        return analysis

    def run_until_one_result(
        self,
        case_dir: Path,
        analysis: dict,
        start_clock: str,
        record_clock: str,
    ) -> dict:
        text = (ROOT / "examples" / "real-run" / "demo-input.txt").read_text(encoding="utf-8").strip()
        analysis_path = case_dir.parent / "analysis.json"
        analysis_path.write_text(json.dumps(analysis, ensure_ascii=False), encoding="utf-8")
        confirmation_path = case_dir.parent / "user-confirmation.txt"
        confirmation_path.write_text("我愿意开始这个现实实验。", encoding="utf-8")
        commands = (
            ("init", "--text", text, "--case-dir", str(case_dir), "--clock", "2026-08-06T08:00:00Z"),
            ("plan", "--case-dir", str(case_dir), "--analysis", str(analysis_path), "--clock", "2026-08-06T08:01:00Z"),
            (
                "start", "--case-dir", str(case_dir),
                "--confirmation-file", str(confirmation_path),
                "--clock", start_clock,
            ),
            (
                "record",
                "--case-dir",
                str(case_dir),
                "--kind",
                "experiment_result",
                "--source-text",
                "第一条结果：当天提出了分工初版。",
                "--fact",
                "当天提出了分工初版",
                "--context",
                "团队分工任务",
                "--timeframe",
                "第一天",
                "--clock",
                record_clock,
            ),
        )
        outputs: dict[str, dict] = {}
        for command in commands:
            result = run_cli(*command)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            outputs[command[0]] = json.loads(result.stdout)
        return outputs

    def assert_time_window_blocks_then_allows(
        self,
        value: int,
        unit: str,
        start_clock: str,
        early_clock: str,
        complete_clock: str,
    ) -> None:
        with tempfile.TemporaryDirectory(prefix="identity-v7-time-") as temporary:
            case_dir = Path(temporary) / "case"
            outputs = self.run_until_one_result(
                case_dir,
                self.make_analysis(value, unit),
                start_clock,
                early_clock,
            )
            self.assertEqual(
                start_clock,
                outputs["start"]["case"]["analysis"]["experiment"]["started_at"],
            )

            early_next = run_cli(
                "next", "--case-dir", str(case_dir), "--clock", early_clock
            )
            self.assertEqual(0, early_next.returncode, early_next.stdout + early_next.stderr)
            early_payload = json.loads(early_next.stdout)
            self.assertEqual("observation", early_payload["stage"])
            self.assertEqual("record", early_payload["next_steps"][0]["action"])

            early_review = run_cli(
                "review",
                "--case-dir",
                str(case_dir),
                "--classification",
                "weakens",
                "--rationale",
                "只有第一条结果，尚未达到预登记时间。",
                "--clock",
                early_clock,
            )
            self.assertNotEqual(0, early_review.returncode)
            self.assertIn("review_requires_complete_experiment", early_review.stdout)

            complete_next = run_cli(
                "next", "--case-dir", str(case_dir), "--clock", complete_clock
            )
            self.assertEqual(0, complete_next.returncode, complete_next.stdout + complete_next.stderr)
            self.assertEqual("review", json.loads(complete_next.stdout)["stage"])

            complete_review = run_cli(
                "review",
                "--case-dir",
                str(case_dir),
                "--classification",
                "inconclusive",
                "--rationale",
                "期限已到，但只有一条结果，窄命题仍无法判断。",
                "--clock",
                complete_clock,
            )
            self.assertEqual(0, complete_review.returncode, complete_review.stdout + complete_review.stderr)

    def test_days_are_an_elapsed_observation_window(self) -> None:
        self.assert_time_window_blocks_then_allows(
            7,
            "days",
            "2026-08-06T09:00:00Z",
            "2026-08-06T12:00:00Z",
            "2026-08-13T09:00:00Z",
        )

    def test_hours_are_an_elapsed_observation_window(self) -> None:
        self.assert_time_window_blocks_then_allows(
            2,
            "hours",
            "2026-08-06T09:00:00Z",
            "2026-08-06T10:00:00Z",
            "2026-08-06T11:00:00Z",
        )


if __name__ == "__main__":
    unittest.main()
