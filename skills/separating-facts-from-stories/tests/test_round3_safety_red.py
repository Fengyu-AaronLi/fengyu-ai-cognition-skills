import importlib.util
import unittest

from test_casefile import SCRIPT, replace_first_input, valid_safety


def load_runtime():
    spec = importlib.util.spec_from_file_location("round3_safety_runtime", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class Round3SafetyRedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_runtime()

    def codes(self, case):
        return {item["code"] for item in self.module.validate_casefile(case)}

    def action(self, action_type, item_id="A1"):
        specification = self.module.ACTION_CATALOG[action_type]
        return {
            "id": item_id,
            "action_type": action_type,
            "text": specification["text"],
            "timing": specification["timing"],
            "risk": specification["risk"],
            "reversible": specification["reversible"],
            "motive_independent": specification["motive_independent"],
            "produces_new_evidence": specification["produces_new_evidence"],
        }

    def signal(self, case, phrase, signal_type):
        span = next(
            item
            for item in case["source_spans"]
            if item["text"] == phrase
        )
        return {
            "input_id": span["input_id"],
            "source_span_id": span["id"],
            "source_ref": span["source_ref"],
            "exact_quote": span["text"],
            "signal_type": signal_type,
            "routing_basis": "deterministic_backstop",
        }

    def test_self_harm_cannot_be_erased_by_unrelated_negation_scope(self):
        for text in (
            "没有人能阻止我自杀。",
            "我没有办法不自杀。",
            "我没有办法阻止自己自杀。",
        ):
            with self.subTest(text=text):
                self.assertTrue(self.module.detect_immediate_risk(text))
                self.assertEqual("safety", self.module.make_draft(text, "risk", "auto")["mode"])
                self.assertIn("self_harm_risk", self.module.expected_safety_signal_types(text))

    def test_actual_denials_and_fictional_mentions_do_not_trigger_safety(self):
        for text in (
            "他没有打我。",
            "我不会伤害自己，也没有伤害别人的计划。",
            "这部电影里说杀了他。",
        ):
            with self.subTest(text=text):
                self.assertFalse(self.module.detect_immediate_risk(text))

    def test_nonrisk_span_cannot_impersonate_a_safety_signal(self):
        case = valid_safety()
        text = "今天开会。后来我胸痛。"
        replace_first_input(case, text)
        case["safety"] = {
            "risk_signals": [
                self.signal(case, "今天开会。", "other_immediate_risk")
            ]
        }
        case["actions"] = [self.action("contact_trusted_person")]
        codes = self.codes(case)
        self.assertIn("SAFETY_SIGNAL_NOT_PRESENT", codes)
        self.assertIn("SAFETY_SIGNAL_COVERAGE_MISSING", codes)
        self.assertIn("SAFETY_SUPPORT_MISMATCH", codes)

    def test_every_current_risk_type_requires_a_real_anchor_and_action(self):
        case = valid_safety()
        text = "他持刀在门外。我胸痛。"
        replace_first_input(case, text)
        case["safety"] = {
            "risk_signals": [
                self.signal(case, "他持刀在门外。", "explicit_threat")
            ]
        }
        case["actions"] = [self.action("move_to_safe_place")]
        codes = self.codes(case)
        self.assertIn("SAFETY_SIGNAL_COVERAGE_MISSING", codes)
        self.assertIn("SAFETY_SUPPORT_MISMATCH", codes)

    def test_self_harm_requires_emergency_or_medical_support(self):
        case = valid_safety()
        text = "我现在准备自杀。"
        replace_first_input(case, text)
        case["safety"] = {
            "risk_signals": [
                self.signal(case, text, "self_harm_risk")
            ]
        }
        case["actions"] = [self.action("contact_trusted_person")]
        self.assertIn("SAFETY_SUPPORT_MISMATCH", self.codes(case))


if __name__ == "__main__":
    unittest.main()
