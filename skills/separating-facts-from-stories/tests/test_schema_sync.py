import importlib.util
import json
import unittest
from pathlib import Path


SKILL_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SKILL_DIR / "scripts" / "casefile.py"
SCHEMA = SKILL_DIR / "schemas" / "casefile.schema.json"


class SchemaSyncTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("casefile_schema_sync", SCRIPT)
        cls.module = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(cls.module)
        cls.schema = json.loads(SCHEMA.read_text(encoding="utf-8"))

    def test_schema_and_runtime_versions_match(self):
        properties = self.schema["properties"]
        self.assertEqual(self.module.SCHEMA_VERSION, properties["schema_version"]["const"])
        self.assertEqual(self.module.SKILL_VERSION, properties["skill_version"]["const"])

    def test_root_required_and_allowed_fields_match(self):
        self.assertEqual(self.module.REQUIRED_ROOT_KEYS, set(self.schema["required"]))
        self.assertEqual(self.module.ROOT_KEYS, set(self.schema["properties"]))

    def test_source_relation_strength_and_reason_enums_match(self):
        defs = self.schema["$defs"]
        self.assertEqual(self.module.SOURCE_TYPES, set(defs["source_type"]["enum"]))
        link = defs["evidence_link"]["properties"]
        self.assertEqual(self.module.RELATIONS, set(link["relation"]["enum"]))
        self.assertEqual(self.module.STRENGTHS, set(link["strength"]["enum"]))
        self.assertEqual(self.module.REASON_CODES, set(link["reason"]["enum"]))

    def test_claim_fields_and_observation_catalog_match(self):
        claim = self.schema["$defs"]["claim"]
        self.assertEqual(self.module.CLAIM_KEYS, set(claim["properties"]))
        self.assertEqual(
            self.module.OBSERVATION_TYPES,
            set(claim["properties"]["observation_type"]["enum"]),
        )

    def test_change_log_fields_match_runtime_contract(self):
        change = self.schema["$defs"]["change"]
        self.assertEqual(self.module.CHANGE_KEYS, set(change["properties"]))

    def test_supersession_field_is_conditionally_required_and_forbidden(self):
        change = self.schema["$defs"]["change"]
        conditional = change["allOf"][0]
        self.assertEqual(
            {"properties": {"to_status": {"const": "superseded"}}},
            conditional["if"],
        )
        self.assertEqual(
            {"required": ["superseded_by_claim_id"]},
            conditional["then"],
        )
        self.assertEqual(
            {"not": {"required": ["superseded_by_claim_id"]}},
            conditional["else"],
        )

    def test_action_and_discriminator_catalogs_match(self):
        defs = self.schema["$defs"]
        self.assertEqual(
            set(self.module.ACTION_CATALOG),
            set(defs["action"]["properties"]["action_type"]["enum"]),
        )
        self.assertEqual(
            set(self.module.DISCRIMINATOR_QUESTION_TYPES),
            set(defs["discriminator"]["properties"]["question_type"]["enum"]),
        )

    def test_unknown_and_hypothesis_request_contracts_match(self):
        defs = self.schema["$defs"]
        self.assertEqual(
            set(self.module.UNKNOWN_CATALOG),
            set(defs["unknown"]["properties"]["unknown_type"]["enum"]),
        )
        self.assertEqual(self.module.UNKNOWN_KEYS, set(defs["unknown"]["required"]))
        self.assertEqual(
            self.module.HYPOTHESIS_REQUEST_KEYS,
            set(defs["hypothesis_request"]["required"]),
        )
        self.assertEqual(
            self.module.HYPOTHESIS_REQUEST_KEYS,
            set(defs["hypothesis_request"]["properties"]),
        )


if __name__ == "__main__":
    unittest.main()
