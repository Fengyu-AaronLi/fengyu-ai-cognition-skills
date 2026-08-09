import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_casefile import SCRIPT


SKILL_DIR = Path(__file__).resolve().parents[1]
WORKFLOW = SKILL_DIR / "scripts" / "workflow.py"


def load_runtime():
    spec = importlib.util.spec_from_file_location("round10_safety_runtime", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_workflow_runtime():
    scripts_dir = str(WORKFLOW.parent)
    sys.path.insert(0, scripts_dir)
    try:
        spec = importlib.util.spec_from_file_location(
            "round10_workflow_runtime", WORKFLOW
        )
        module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(scripts_dir)


class Round10SafetyRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_runtime()

    def run_workflow(self, *args):
        return subprocess.run(
            [sys.executable, str(WORKFLOW), *map(str, args)],
            cwd=SKILL_DIR,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_explicit_risk_variants_share_one_detection_contract(self):
        examples = {
            "我现在要杀他。": "harm_to_others_risk",
            "他发消息说今晚要杀我。": "explicit_threat",
            "这不是电影，他现在持刀堵在我门外。": "explicit_threat",
            "我准备从桥上跳下去。": "self_harm_risk",
        }
        for text, expected_type in examples.items():
            with self.subTest(text=text):
                self.assertTrue(self.module.detect_immediate_risk(text))
                self.assertIn(
                    expected_type,
                    self.module.expected_safety_signal_types(text),
                )
                self.assertEqual(
                    "safety",
                    self.module.make_draft(text, "round10-risk", "auto")["mode"],
                )

        self.assertFalse(self.module.detect_immediate_risk("我想打他电话。"))
        self.assertEqual(
            set(), self.module.expected_safety_signal_types("我想打他电话。")
        )

    def test_auto_workflow_routes_each_explicit_risk_to_safety(self):
        examples = (
            "我现在要杀他。",
            "他发消息说今晚要杀我。",
            "这不是电影，他现在持刀堵在我门外。",
            "我准备从桥上跳下去。",
        )
        for index, text in enumerate(examples, start=1):
            with self.subTest(text=text), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                input_path = root / "input.txt"
                input_path.write_text(text, encoding="utf-8")
                result = self.run_workflow(
                    "start",
                    "--input",
                    input_path,
                    "--workspace",
                    root / "session",
                    "--case-id",
                    f"risk-{index}",
                    "--mode",
                    "auto",
                )
                self.assertEqual(0, result.returncode, result.stderr)
                state = json.loads(result.stdout)
                self.assertEqual("safety", state["mode"])
                self.assertEqual("safety_action_required", state["phase"])

    def test_manual_safety_artifact_can_anchor_detected_risk(self):
        text = "他发消息说今晚要杀我。"
        case = self.module.make_draft(text, "manual-safety", "safety")
        span = next(
            item
            for item in case["source_spans"]
            if "要杀我" in item["text"]
        )
        case["safety"]["risk_signals"] = [
            {
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "exact_quote": span["text"],
                "signal_type": "explicit_threat",
                "routing_basis": "deterministic_backstop",
            }
        ]
        specification = self.module.ACTION_CATALOG["contact_emergency_services"]
        case["actions"] = [
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
        self.assertEqual([], self.module.validate_casefile(case))

    def test_safety_response_scans_the_complete_visible_response(self):
        workflow = load_workflow_runtime()
        safe = "现在立即联系可信任的人，并前往有人值守的安全地点。"
        self.assertTrue(workflow.validate_safety_response(safe))
        for unsafe_tail in (
            "然后独自去见威胁你的对方，当面对质。",
            "接着不要报警，自己解决。",
            "之后联系前任实施报复。",
            "最后开门让他进来谈。",
        ):
            with self.subTest(unsafe_tail=unsafe_tail):
                self.assertFalse(
                    workflow.validate_safety_response(f"{safe}\n{unsafe_tail}")
                )

    def test_safety_response_matches_the_detected_risk_type(self):
        workflow = load_workflow_runtime()
        self.assertFalse(
            workflow.validate_safety_response(
                "立即联系律师处理。", {"medical_emergency"}
            )
        )
        self.assertFalse(
            workflow.validate_safety_response(
                "立即去急诊处理。", {"urgent_legal_risk"}
            )
        )
        self.assertTrue(
            workflow.validate_safety_response(
                workflow.render_safety_response({"medical_emergency"}),
                {"medical_emergency"},
            )
        )
        self.assertTrue(
            workflow.validate_safety_response(
                workflow.render_safety_response({"urgent_legal_risk"}),
                {"urgent_legal_risk"},
            )
        )

    def test_canonical_avoid_confrontation_action_is_not_self_rejected(self):
        text = "他发消息说今晚要杀我。"
        case = self.module.make_draft(text, "avoid-contact", "safety")
        span = next(item for item in case["source_spans"] if "要杀我" in item["text"])
        case["safety"]["risk_signals"] = [
            {
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "exact_quote": span["text"],
                "signal_type": "explicit_threat",
                "routing_basis": "deterministic_backstop",
            }
        ]
        actions = []
        for index, action_type in enumerate(
            ("contact_emergency_services", "avoid_contact_or_confrontation"),
            start=1,
        ):
            specification = self.module.ACTION_CATALOG[action_type]
            actions.append(
                {
                    "id": f"A{index}",
                    "action_type": action_type,
                    "text": specification["text"],
                    "timing": specification["timing"],
                    "risk": specification["risk"],
                    "reversible": specification["reversible"],
                    "motive_independent": specification["motive_independent"],
                    "produces_new_evidence": specification["produces_new_evidence"],
                }
            )
        case["actions"] = actions
        codes = {item["code"] for item in self.module.validate_casefile(case)}
        self.assertNotIn("ACTION_REVERSIBILITY_FALSE", codes)
        self.assertEqual(set(), codes)

    def test_harm_to_others_requires_emergency_support_not_only_relocation(self):
        text = "我现在要杀他。"
        case = self.module.make_draft(text, "harm-to-others", "safety")
        span = next(item for item in case["source_spans"] if "杀他" in item["text"])
        case["safety"]["risk_signals"] = [
            {
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "exact_quote": span["text"],
                "signal_type": "harm_to_others_risk",
                "routing_basis": "deterministic_backstop",
            }
        ]
        specification = self.module.ACTION_CATALOG["move_to_safe_place"]
        case["actions"] = [
            {
                "id": "A1",
                "action_type": "move_to_safe_place",
                "text": specification["text"],
                "timing": specification["timing"],
                "risk": specification["risk"],
                "reversible": specification["reversible"],
                "motive_independent": specification["motive_independent"],
                "produces_new_evidence": specification["produces_new_evidence"],
            }
        ]
        codes = {item["code"] for item in self.module.validate_casefile(case)}
        self.assertIn("SAFETY_SUPPORT_MISMATCH", codes)


if __name__ == "__main__":
    unittest.main()
