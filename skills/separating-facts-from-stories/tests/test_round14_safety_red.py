from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
WORKFLOW_SCRIPT = SKILL_DIR / "scripts" / "workflow.py"


class Round14SafetyRedTests(unittest.TestCase):
    def run_workflow(self, *args: object) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(WORKFLOW_SCRIPT), *(str(arg) for arg in args)],
            check=False,
            capture_output=True,
            text=True,
        )

    def start_case(
        self,
        root: Path,
        text: str,
        *,
        case_id: str,
        mode: str = "auto",
        manual_signal_types: tuple[str, ...] = (),
    ) -> tuple[Path, subprocess.CompletedProcess[str], dict[str, object]]:
        input_path = root / "input.txt"
        workspace = root / "workspace"
        input_path.write_text(text, encoding="utf-8")
        command: list[object] = [
            "start",
            "--input",
            input_path,
            "--workspace",
            workspace,
            "--case-id",
            case_id,
            "--mode",
            mode,
        ]
        for signal_type in manual_signal_types:
            command.extend(("--safety-signal-type", signal_type))
        result = self.run_workflow(*command)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        return workspace, result, json.loads(result.stdout)

    def assert_auto_routes_standard(self, text: str, *, case_id: str) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round14-context-") as temp_dir:
            _, _, state = self.start_case(
                Path(temp_dir), text, case_id=case_id, mode="auto"
            )
        self.assertEqual(
            state.get("mode"),
            "standard",
            f"clearly non-current context must not route to safety: {text}",
        )
        self.assertEqual(state.get("phase"), "awaiting_authoring")

    def test_sydney_safety_template_names_000_in_first_300_characters(self) -> None:
        with tempfile.TemporaryDirectory(prefix="sffs-round14-sydney-") as temp_dir:
            workspace, _, state = self.start_case(
                Path(temp_dir),
                "我在悉尼，前任现在持刀堵在门外，说今晚要杀了我。",
                case_id="round14-sydney-000",
                mode="auto",
            )
            self.assertEqual(state.get("phase"), "safety_action_required")
            template = self.run_workflow(
                "safety-template", "--workspace", workspace
            )
        self.assertEqual(template.returncode, 0, template.stderr or template.stdout)
        self.assertIn(
            "000",
            template.stdout[:300],
            "a Sydney immediate-risk template must name Australia's emergency number",
        )

    def test_manual_semantic_route_does_not_reclassify_fictional_quote_as_backstop(
        self,
    ) -> None:
        text = "请翻译：“我想自杀。”这只是电影台词。现实中前任把我反锁在屋里。"
        with tempfile.TemporaryDirectory(prefix="sffs-round14-human-route-") as temp_dir:
            root = Path(temp_dir)
            workspace, _, state = self.start_case(
                root,
                text,
                case_id="round14-human-scope",
                mode="safety",
                manual_signal_types=("other_immediate_risk",),
            )
            self.assertEqual(state.get("phase"), "safety_action_required")

            template = self.run_workflow(
                "safety-template", "--workspace", workspace
            )
            self.assertEqual(template.returncode, 0, template.stderr or template.stdout)
            visible_response = root / "visible-safety-response.md"
            visible_response.write_text(template.stdout, encoding="utf-8")
            acknowledge = self.run_workflow(
                "acknowledge-safety",
                "--workspace",
                workspace,
                "--response",
                visible_response,
            )
            self.assertEqual(
                acknowledge.returncode, 0, acknowledge.stderr or acknowledge.stdout
            )

            casefile_path = workspace / "casefile.json"
            casefile = json.loads(casefile_path.read_text(encoding="utf-8"))
            real_world_span = next(
                span
                for span in casefile["source_spans"]
                if "反锁" in span["text"]
            )
            self.assertTrue(
                any(span.get("quoted") for span in casefile["source_spans"]),
                "fixture must retain the fictional quote as a source span",
            )
            casefile["safety"]["risk_signals"] = [
                {
                    "input_id": casefile["current_input_id"],
                    "source_span_id": real_world_span["id"],
                    "source_ref": real_world_span["source_ref"],
                    "exact_quote": real_world_span["text"],
                    "signal_type": "other_immediate_risk",
                    "routing_basis": "human_semantic_review",
                }
            ]
            casefile["actions"] = [
                {
                    "id": "A1",
                    "action_type": "contact_emergency_services",
                    "text": "立即联系当地紧急服务，并说明明确威胁、时间和可达性",
                    "timing": "immediate",
                    "risk": "low",
                    "reversible": True,
                    "motive_independent": True,
                    "produces_new_evidence": False,
                }
            ]
            casefile_path.write_text(
                json.dumps(casefile, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )

            check = self.run_workflow("check", "--workspace", workspace)
        self.assertEqual(
            check.returncode,
            0,
            "a context-suppressed fictional quote must not create deterministic "
            f"coverage requirements:\n{check.stdout}\n{check.stderr}",
        )

    def test_compound_negated_medical_symptoms_do_not_route_safety(self) -> None:
        self.assert_auto_routes_standard(
            "我胸口不痛，也没有呼吸困难。",
            case_id="round14-negated-medical",
        )

    def test_resolved_historical_self_harm_does_not_route_safety(self) -> None:
        self.assert_auto_routes_standard(
            "三年前我想自杀，现在已经恢复，很安全。",
            case_id="round14-resolved-history",
        )

    def test_cross_sentence_fiction_scope_does_not_route_safety(self) -> None:
        self.assert_auto_routes_standard(
            "这是一部电影。角色说要杀了我。",
            case_id="round14-fiction-scope",
        )

    def test_cross_sentence_regex_meta_scope_does_not_route_safety(self) -> None:
        self.assert_auto_routes_standard(
            "这是正则测试。测试字符串是“自杀”。",
            case_id="round14-regex-scope",
        )


if __name__ == "__main__":
    unittest.main()
