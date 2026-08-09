import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from test_casefile import valid_standard


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = SKILL_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))
import casefile  # noqa: E402
import workflow  # noqa: E402
sys.path.pop(0)


class Round11HumanRoutingAndScopeRedTests(unittest.TestCase):
    def run_workflow(self, *args):
        return subprocess.run(
            [sys.executable, str(SCRIPTS_DIR / "workflow.py"), *map(str, args)],
            cwd=SKILL_DIR,
            text=True,
            capture_output=True,
            check=False,
        )

    def canonical_action(self, action_type="contact_emergency_services"):
        specification = casefile.ACTION_CATALOG[action_type]
        return {
            "id": "A1",
            "action_type": action_type,
            "text": specification["text"],
            "timing": specification["timing"],
            "risk": specification["risk"],
            "reversible": specification["reversible"],
            "motive_independent": specification["motive_independent"],
            "produces_new_evidence": specification["produces_new_evidence"],
        }

    def test_negated_harm_to_others_intent_is_not_a_positive_signal(self):
        text = "我不想杀他。"
        self.assertEqual(set(), casefile.expected_safety_signal_types(text))
        self.assertFalse(casefile.detect_immediate_risk(text))

    def test_negated_reported_threat_is_not_a_positive_signal(self):
        text = "他发消息说不会杀我。"
        self.assertEqual(set(), casefile.expected_safety_signal_types(text))
        self.assertFalse(casefile.detect_immediate_risk(text))

    def test_analysis_after_quoted_translation_payload_is_not_passthrough(self):
        text = "请把这句“他没回”翻译成英文，并告诉我他是不是不爱我。"
        self.assertEqual("translation", workflow.passthrough_candidate_kind(text))
        self.assertTrue(workflow.passthrough_has_mixed_intent(text))
        self.assertIsNone(workflow.classify_passthrough_request(text))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "input.txt"
            source.write_text(text, encoding="utf-8")
            automatic = self.run_workflow(
                "start",
                "--input",
                source,
                "--workspace",
                root / "auto",
                "--case-id",
                "quoted-mixed",
                "--mode",
                "auto",
            )
            self.assertEqual(0, automatic.returncode, automatic.stderr)
            self.assertEqual("standard", json.loads(automatic.stdout)["mode"])

            forced = self.run_workflow(
                "start",
                "--input",
                source,
                "--workspace",
                root / "forced",
                "--case-id",
                "quoted-mixed",
                "--mode",
                "passthrough",
            )
            self.assertNotEqual(0, forced.returncode)
            self.assertIn("PASSTHROUGH_MIXED_INTENT", forced.stderr)

    def test_human_semantic_review_can_anchor_a_novel_immediate_risk(self):
        text = "他站在门外不停砸门，我现在不敢出去。"
        self.assertEqual(set(), casefile.expected_safety_signal_types(text))
        artifact = casefile.make_draft(text, "manual-review", "safety")
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
        artifact["actions"] = [self.canonical_action()]
        self.assertEqual([], casefile.validate_casefile(artifact))

    def test_human_review_basis_cannot_relabel_a_detected_signal(self):
        text = "我现在胸痛。"
        artifact = casefile.make_draft(text, "manual-relabel", "safety")
        span = next(item for item in artifact["source_spans"] if "胸痛" in item["text"])
        artifact["safety"]["risk_signals"] = [
            {
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "exact_quote": span["text"],
                "signal_type": "medical_emergency",
                "routing_basis": "human_semantic_review",
            }
        ]
        artifact["actions"] = [self.canonical_action()]
        codes = {item["code"] for item in casefile.validate_casefile(artifact)}
        self.assertIn("SAFETY_ROUTING_BASIS_MISMATCH", codes)

    def test_deterministic_signal_declares_its_routing_basis(self):
        text = "他发消息说今晚要杀我。"
        artifact = casefile.make_draft(text, "deterministic-basis", "safety")
        span = next(item for item in artifact["source_spans"] if "要杀我" in item["text"])
        artifact["safety"]["risk_signals"] = [
            {
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "exact_quote": span["text"],
                "signal_type": "explicit_threat",
                "routing_basis": "deterministic_backstop",
            }
        ]
        artifact["actions"] = [self.canonical_action()]
        self.assertEqual([], casefile.validate_casefile(artifact))

    def test_start_update_accepts_explicit_human_safety_routing(self):
        previous = valid_standard()
        new_text = "他站在门外不停砸门，我现在不敢出去。"
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            history = root / "revision-1.json"
            history.write_text(
                json.dumps(previous, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            source = root / "input.txt"
            source.write_text(new_text, encoding="utf-8")
            result = self.run_workflow(
                "start-update",
                "--history",
                history,
                "--input",
                source,
                "--workspace",
                root / "session",
                "--mode",
                "safety",
                "--safety-signal-type",
                "other_immediate_risk",
            )
            self.assertEqual(0, result.returncode, result.stderr)
            state = json.loads(result.stdout)
            self.assertEqual("safety", state["mode"])
            self.assertEqual("safety_action_required", state["phase"])

            response = root / "safety.md"
            response.write_text(
                workflow.render_safety_response({"other_immediate_risk"}),
                encoding="utf-8",
            )
            acknowledged = self.run_workflow(
                "acknowledge-safety",
                "--workspace",
                root / "session",
                "--response",
                response,
            )
            self.assertEqual(0, acknowledged.returncode, acknowledged.stderr)
            artifact_path = root / "session" / "casefile.json"
            artifact = json.loads(artifact_path.read_text(encoding="utf-8"))
            span = next(
                item
                for item in artifact["source_spans"]
                if item["input_id"] == artifact["current_input_id"]
                and "砸门" in item["text"]
            )
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
            artifact["actions"] = [self.canonical_action()]
            artifact_path.write_text(
                json.dumps(artifact, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            checked = self.run_workflow(
                "check", "--workspace", root / "session"
            )
            self.assertEqual(0, checked.returncode, checked.stderr)
            self.assertTrue(json.loads(checked.stdout)["valid"])

    def test_human_review_can_add_a_missed_type_on_a_mixed_risk_span(self):
        text = "我胸痛而且我担心自己马上会失控伤到别人。"
        artifact = casefile.make_draft(text, "mixed-risk", "safety")
        span = next(item for item in artifact["source_spans"] if "胸痛" in item["text"])
        artifact["safety"]["risk_signals"] = [
            {
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "exact_quote": span["text"],
                "signal_type": "medical_emergency",
                "routing_basis": "deterministic_backstop",
            },
            {
                "input_id": span["input_id"],
                "source_span_id": span["id"],
                "source_ref": span["source_ref"],
                "exact_quote": span["text"],
                "signal_type": "harm_to_others_risk",
                "routing_basis": "human_semantic_review",
            },
        ]
        artifact["actions"] = [
            self.canonical_action("contact_emergency_services"),
            {
                **self.canonical_action("seek_medical_support"),
                "id": "A2",
            },
        ]
        self.assertEqual([], casefile.validate_casefile(artifact))


if __name__ == "__main__":
    unittest.main()
