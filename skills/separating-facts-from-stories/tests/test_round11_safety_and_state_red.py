import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_casefile import valid_safety

SKILL_DIR = Path(__file__).resolve().parents[1]
WORKFLOW = SKILL_DIR / "scripts" / "workflow.py"
sys.path.insert(0, str(WORKFLOW.parent))
import casefile  # noqa: E402
import workflow  # noqa: E402
sys.path.pop(0)


class Round11SafetyAndStateRedTests(unittest.TestCase):
    def run_workflow(self, *args):
        return subprocess.run(
            [sys.executable, str(WORKFLOW), *map(str, args)],
            cwd=SKILL_DIR,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_negative_emergency_advice_is_not_action_first(self):
        self.assertFalse(
            workflow.validate_safety_response(
                "现在先冷静，没必要报警，自己处理就行。",
                {"explicit_threat"},
            )
        )
        for text in (
            "现在警方不会来。",
            "现在报警只会让事情更糟。",
            "现在你自己扛着，警方帮不了你。",
            "现在先联系警方，然后立即自杀。",
            "现在先报警，然后杀了他。",
            "现在先拨打000，然后吞下一整瓶药。",
            "现在先联系警方。\n不要等，拿刀去找他算账。",
            "现在联系对方，让警方别管。",
            "现在先报警，然后开枪打死他。",
            "现在先拨打000，然后服下整瓶安眠药。",
            "现在先联系警方，然后冲过去揍他。",
            "现在先报警，然后一把火烧死他。",
            "现在联系警方是错误做法。",
            "现在报警并不可取。",
            "现在联系警方是假建议。",
            "现在联系警方是最危险的选择。",
            "现在去安全地点并不安全。",
            "现在联系可信任的人是不应该的。",
            "现在报警，我不建议这样做。",
            "现在联系警方吗？",
            "现在报警是否合适？",
            "现在去安全地点怎么样？",
            "现在联系警方可能是一个选项。",
            "现在报警也许可以。",
            "现在联系警方，或者什么也不做。",
            "现在联系警方，但先联系威胁者。",
            "现在先报警，然后联系威胁者协商。",
            "现在联系警方，再约前任单独谈谈。",
            "现在去安全地点，然后给对方开门。",
            "现在联系警方，但先等三天再行动。",
        ):
            with self.subTest(text=text):
                self.assertFalse(
                    workflow.validate_safety_response(
                        text, {"explicit_threat"}
                    )
                )

    def test_common_direct_risk_families_hit_the_backstop(self):
        examples = {
            "我马上要把人捅一刀。": "harm_to_others_risk",
            "我今晚想死。": "self_harm_risk",
            "前任有我家的钥匙，现在就在附近。": "access_or_location_exposure",
            "我胸口像被巨石压住。": "medical_emergency",
            "I can’t breathe.": "medical_emergency",
        }
        for text, signal_type in examples.items():
            with self.subTest(text=text):
                self.assertIn(
                    signal_type,
                    casefile.expected_safety_signal_types(text),
                )
        self.assertFalse(
            workflow.validate_safety_response(
                "现在先联系警方。\n不要等就单独见面对质。",
                {"explicit_threat"},
            )
        )

    def test_typed_safety_response_is_a_deterministic_catalog_render(self):
        signal_types = {"explicit_threat"}
        canonical = workflow.render_safety_response(signal_types)
        self.assertTrue(workflow.validate_safety_response(canonical, signal_types))
        self.assertFalse(
            workflow.validate_safety_response(
                canonical + "\n我再补充一段未经校验的建议。", signal_types
            )
        )
        self.assertFalse(
            workflow.validate_safety_response(
                "现在先联系警方。", signal_types
            )
        )

    def test_parallel_negations_do_not_become_positive_risk(self):
        for text in (
            "我没有胸痛和呼吸困难。",
            "我没有拿刀和武器。",
            "我没有自杀或伤害自己的想法。",
            "我没有任何想要自杀的念头。",
            "我绝对不会去自杀。",
            "我现在没有要杀他的打算。",
            "我没有想要伤害别人的冲动。",
            "他没有说要杀我。",
            "他从没说过要杀我。",
            "我不想死。",
            "我的胸口不痛。",
            "前任没有我家钥匙。",
        ):
            with self.subTest(text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))

    def test_fiction_context_does_not_erase_a_later_real_world_danger(self):
        for actor in ("前任", "房东", "丈夫", "男友", "客户", "室友"):
            text = f"我刚才在玩游戏，{actor}现在拿着刀站在我门外。"
            with self.subTest(actor=actor):
                self.assertIn(
                    "explicit_threat",
                    casefile.expected_safety_signal_types(text),
                )

    def test_every_full_text_backstop_signal_has_a_generated_anchor(self):
        for text in (
            "我胸口，像被巨石压住。",
            "他威胁，今晚要杀我。",
            "他威胁我，今晚让我消失。",
        ):
            with self.subTest(text=text):
                draft = casefile.make_draft(text, "anchor-coverage", "auto")
                full_types = casefile.expected_safety_signal_types(text)
                span_types = set().union(
                    *(
                        casefile.expected_safety_signal_types(item["text"])
                        for item in draft["source_spans"]
                    )
                )
                self.assertTrue(full_types, text)
                self.assertLessEqual(full_types, span_types)
                self.assertEqual("safety", draft["mode"])
        self.assertFalse(
            casefile.detect_immediate_risk("游戏里的前任现在拿着刀站在门外。")
        )
        for text in (
            "这不是电影台词，他今晚真的要杀我。",
            "别当成剧本，我前任已经拿着刀到楼下了。",
        ):
            with self.subTest(text=text):
                self.assertIn(
                    "explicit_threat",
                    casefile.expected_safety_signal_types(text),
                )

    def test_transform_operand_is_scoped_without_erasing_later_danger(self):
        self.assertEqual(
            set(),
            casefile.expected_safety_signal_types(
                "请翻译成英文：“我会杀了你。”"
            ),
        )
        for text in (
            "请翻译成英文：“hello”，我前任正在门外拿刀。",
            "请翻译成英文：“hello”，同时告诉我怎么办，我前任正在门外拿刀。",
        ):
            with self.subTest(text=text):
                self.assertIn(
                    "explicit_threat",
                    casefile.expected_safety_signal_types(text),
                )

    def test_benign_deadline_access_and_tool_text_do_not_route_to_safety(self):
        for text in (
            "作业今天截止。",
            "Access denied.",
            "Use a knife to cut bread.",
            "邮箱地址怎么写？",
            "活动地址在学校。",
            "拿刀切菜。",
            "我笑得喘不过气。",
            "请分析这句台词：“我想死”。",
            "请把“前任有我家钥匙”改成被动句。",
            "请检查这段正则是否匹配“我想死”。",
        ):
            with self.subTest(text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))

        requests = (
            "请翻译成英文：作业今天截止。",
            "请翻译成中文：“Access denied.”",
            "请翻译成中文：“Use a knife to cut bread.”",
        )
        for index, text in enumerate(requests):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                source = root / "input.txt"
                source.write_text(text, encoding="utf-8")
                result = self.run_workflow(
                    "start",
                    "--input",
                    source,
                    "--workspace",
                    root / "session",
                    "--case-id",
                    f"benign-{index}",
                    "--mode",
                    "auto",
                )
                self.assertEqual(0, result.returncode, result.stderr)
                self.assertEqual("passthrough", json.loads(result.stdout)["mode"])

    def test_english_negation_does_not_create_a_positive_risk(self):
        for text in (
            "He isn't going to kill me.",
            "He is not going to kill me.",
            "I don't have chest pain.",
            "I do not have chest pain.",
        ):
            with self.subTest(text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))

    def test_explicitly_resolved_historical_signal_is_not_immediate(self):
        for text in (
            "我十年前想死，现在生活很好。",
            "我昨天胸痛，但医生确认已经好了。",
            "法院期限昨天已经过了。",
        ):
            with self.subTest(text=text):
                self.assertEqual(set(), casefile.expected_safety_signal_types(text))

    def test_unquoted_transform_cannot_hide_a_second_safety_task(self):
        text = "请翻译成英文：hello，同时告诉我怎么办，我前任正在门外拿刀。"
        self.assertIn(
            "explicit_threat", casefile.expected_safety_signal_types(text)
        )
        self.assertTrue(workflow.passthrough_has_mixed_intent(text))
        self.assertIsNone(workflow.classify_passthrough_request(text))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input.txt"
            source.write_text(text, encoding="utf-8")
            started = self.run_workflow(
                "start",
                "--input",
                source,
                "--workspace",
                root / "session",
                "--case-id",
                "mixed-unquoted-risk",
                "--mode",
                "auto",
            )
            self.assertEqual(0, started.returncode, started.stderr)
            self.assertEqual("safety", json.loads(started.stdout)["mode"])

    def test_acknowledged_safety_response_is_bound_to_its_event(self):
        case = valid_safety()
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input.txt"
            source.write_text(case["inputs"][0]["text"], encoding="utf-8")
            workspace = root / "session"
            started = self.run_workflow(
                "start",
                "--input",
                source,
                "--workspace",
                workspace,
                "--case-id",
                case["case_id"],
                "--mode",
                "auto",
            )
            self.assertEqual(0, started.returncode, started.stderr)
            response = root / "safety.md"
            response.write_text(
                workflow.render_safety_response(
                    casefile.expected_safety_signal_types(
                        case["inputs"][0]["text"]
                    )
                ),
                encoding="utf-8",
            )
            acknowledged = self.run_workflow(
                "acknowledge-safety",
                "--workspace",
                workspace,
                "--response",
                response,
            )
            self.assertEqual(0, acknowledged.returncode, acknowledged.stderr)

            state_path = workspace / "state.json"
            state = json.loads(state_path.read_text(encoding="utf-8"))
            state["safety_response_path"] = "input.txt"
            state["safety_response_sha256"] = hashlib.sha256(
                (workspace / "input.txt").read_bytes()
            ).hexdigest()
            state_path.write_text(
                json.dumps(state, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            status = self.run_workflow("status", "--workspace", workspace)
            self.assertNotEqual(0, status.returncode)
            self.assertIn("STATE_EVENT_CHAIN_INVALID", status.stdout)

    def test_casefile_mode_cannot_diverge_from_workflow_mode(self):
        text = "他站在门外不停砸门，我现在不敢出去。"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input.txt"
            source.write_text(text, encoding="utf-8")
            workspace = root / "session"
            started = self.run_workflow(
                "start",
                "--input",
                source,
                "--workspace",
                workspace,
                "--case-id",
                "mode-divergence",
                "--mode",
                "standard",
            )
            self.assertEqual(0, started.returncode, started.stderr)
            artifact_path = workspace / "casefile.json"
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            artifact["mode"] = "safety"
            span = next(item for item in artifact["source_spans"] if "砸门" in item["text"])
            artifact["safety"]["risk_signals"] = [
                {
                    "input_id": span["input_id"],
                    "source_span_id": span["id"],
                    "source_ref": span["source_ref"],
                    "exact_quote": span["text"],
                    "signal_type": "other_immediate_risk",
                    "routing_basis": "human_semantic_review",
                }
            ]
            specification = casefile.ACTION_CATALOG["contact_emergency_services"]
            artifact["actions"] = [
                {
                    "id": "A1",
                    "action_type": "contact_emergency_services",
                    "text": specification["text"],
                    "timing": specification["timing"],
                    "risk": specification["risk"],
                    "reversible": specification["reversible"],
                    "motive_independent": specification["motive_independent"],
                    "produces_new_evidence": specification["produces_new_evidence"],
                }
            ]
            artifact_path.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            status = self.run_workflow("status", "--workspace", workspace)
            self.assertNotEqual(0, status.returncode)
            self.assertIn("CASEFILE_MODE_MISMATCH", status.stdout)

    def test_manual_safety_type_is_required_and_binds_action_first(self):
        text = "他站在门外不停砸门，我现在不敢出去。"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input.txt"
            source.write_text(text, encoding="utf-8")
            missing_type = self.run_workflow(
                "start",
                "--input",
                source,
                "--workspace",
                root / "missing",
                "--case-id",
                "manual-type",
                "--mode",
                "safety",
            )
            self.assertNotEqual(0, missing_type.returncode)
            self.assertIn("MANUAL_SAFETY_TYPE_REQUIRED", missing_type.stderr)

            started = self.run_workflow(
                "start",
                "--input",
                source,
                "--workspace",
                root / "session",
                "--case-id",
                "manual-type",
                "--mode",
                "safety",
                "--safety-signal-type",
                "other_immediate_risk",
            )
            self.assertEqual(0, started.returncode, started.stderr)
            state = json.loads(started.stdout)
            self.assertEqual(
                ["other_immediate_risk"], state["manual_safety_signal_types"]
            )

            weak = root / "weak.md"
            weak.write_text("现在先联系律师，询问法律支持。", encoding="utf-8")
            refused = self.run_workflow(
                "acknowledge-safety",
                "--workspace",
                root / "session",
                "--response",
                weak,
            )
            self.assertNotEqual(0, refused.returncode)
            self.assertIn("SAFETY_RESPONSE_INVALID", refused.stderr)

    def test_multiple_manual_safety_types_are_deduplicated_and_all_enforced(self):
        text = "这是一段新表达，确定性后备没有识别，但人工判断存在两类即时风险。"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input.txt"
            source.write_text(text, encoding="utf-8")
            workspace = root / "session"
            started = self.run_workflow(
                "start",
                "--input",
                source,
                "--workspace",
                workspace,
                "--case-id",
                "multi-manual-risk",
                "--mode",
                "safety",
                "--safety-signal-type",
                "medical_emergency",
                "--safety-signal-type",
                "harm_to_others_risk",
                "--safety-signal-type",
                "medical_emergency",
            )
            self.assertEqual(0, started.returncode, started.stderr)
            self.assertEqual(
                ["harm_to_others_risk", "medical_emergency"],
                json.loads(started.stdout)["manual_safety_signal_types"],
            )

            incomplete = root / "incomplete.md"
            incomplete.write_text("现在先联系警方。", encoding="utf-8")
            refused = self.run_workflow(
                "acknowledge-safety",
                "--workspace",
                workspace,
                "--response",
                incomplete,
            )
            self.assertNotEqual(0, refused.returncode)
            self.assertIn("SAFETY_RESPONSE_INVALID", refused.stderr)

            complete = root / "complete.md"
            complete.write_text(
                workflow.render_safety_response(
                    {"medical_emergency", "harm_to_others_risk"}
                ),
                encoding="utf-8",
            )
            accepted = self.run_workflow(
                "acknowledge-safety",
                "--workspace",
                workspace,
                "--response",
                complete,
            )
            self.assertEqual(0, accepted.returncode, accepted.stderr)


if __name__ == "__main__":
    unittest.main()
