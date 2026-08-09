from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
WORKFLOW_SCRIPT = SCRIPTS_DIR / "workflow.py"
sys.path.insert(0, str(SCRIPTS_DIR))

import casefile  # noqa: E402
import workflow  # noqa: E402


def _valid_self_harm_case() -> dict[str, Any]:
    text = "我现在要自杀。"
    draft = casefile.make_draft(text, "round18-safety-history", "safety")
    action = {
        key: value
        for key, value in casefile.ACTION_CATALOG["seek_medical_support"].items()
        if key != "modes"
    }
    draft["actions"] = [
        {"id": "A1", "action_type": "seek_medical_support", **action}
    ]
    span = next(
        item
        for item in draft["source_spans"]
        if item["start"] == 0 and item["end"] == len(text)
    )
    draft["safety"] = {
        "risk_signals": [
            {
                "input_id": "I1",
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "exact_quote": text,
                "signal_type": "self_harm_risk",
                "routing_basis": "deterministic_backstop",
            }
        ]
    }
    return draft


class Round18SafetyRoutingRedTests(unittest.TestCase):
    def run_workflow(self, *args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(WORKFLOW_SCRIPT), *map(str, args)],
            cwd=SKILL_DIR,
            text=True,
            capture_output=True,
            check=False,
        )

    def test_disowned_transform_operand_routes_to_safety(self) -> None:
        text = (
            "请把“hello”和“我今晚要杀她”都翻译成英文。"
            "第二句不是翻译素材，而是我本人现在真实的计划。"
        )
        self.assertIn(
            "harm_to_others_risk",
            casefile.expected_safety_signal_types(text),
        )
        self.assertTrue(workflow.passthrough_has_mixed_intent(text))
        self.assertIsNone(workflow.classify_passthrough_request(text))

    def test_negated_australian_location_never_forces_000(self) -> None:
        text = "我不在澳大利亚，也不在悉尼。前任持刀堵在门外。"
        self.assertFalse(workflow._australia_emergency_context(text))
        rendered = workflow.render_safety_response({"explicit_threat"}, text)
        self.assertNotIn("000", rendered)
        self.assertIn("当地", rendered)

    def test_double_negation_preserves_self_harm_signal(self) -> None:
        self.assertIn(
            "self_harm_risk",
            casefile.expected_safety_signal_types(
                "我不是不会自杀，我今晚就会做。"
            ),
        )

    def test_discourse_prefixed_reality_reset_ends_fiction_scope(self) -> None:
        self.assertIn(
            "explicit_threat",
            casefile.expected_safety_signal_types(
                "这是小说。顺便说一句，现实中我的前任正持刀堵在我门外。"
            ),
        )

    def test_resolved_history_and_current_recurrence_are_distinguished(self) -> None:
        self.assertEqual(
            set(),
            casefile.expected_safety_signal_types(
                "十年前我想死。现在我生活很好，也很安全。"
            ),
        )
        self.assertIn(
            "medical_emergency",
            casefile.expected_safety_signal_types(
                "我昨天胸痛，但医生确认已经好了。"
                "现在同样的痛又出现了，而且越来越重。"
            ),
        )

    def test_reflexive_killing_is_self_harm_not_only_external_threat(self) -> None:
        signal_types = casefile.expected_safety_signal_types(
            "我现在要杀了自己。"
        )
        self.assertIn("self_harm_risk", signal_types)
        rendered = workflow.render_safety_response(signal_types, "")
        self.assertRegex(rendered, r"急救|医疗|危机|可信任")

    def test_safety_history_update_has_a_completable_safety_template(self) -> None:
        previous = _valid_self_harm_case()
        self.assertEqual([], casefile.validate_casefile(previous))
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            previous_path = root / "revision-1.json"
            previous_path.write_text(
                json.dumps(previous, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            input_path = root / "update.txt"
            input_path.write_text(
                "危机已经解除。我现在安全，也没有任何自伤想法。",
                encoding="utf-8",
            )
            workspace = root / "workspace"
            started = self.run_workflow(
                "start-update",
                "--history",
                previous_path,
                "--input",
                input_path,
                "--workspace",
                workspace,
            )
            self.assertEqual(0, started.returncode, started.stderr)
            state = json.loads(started.stdout)
            self.assertEqual("safety_action_required", state["phase"])

            template = self.run_workflow(
                "safety-template", "--workspace", workspace
            )
            self.assertEqual(0, template.returncode, template.stderr)
            self.assertRegex(template.stdout, r"急救|医疗|危机|可信任")


if __name__ == "__main__":
    unittest.main()
