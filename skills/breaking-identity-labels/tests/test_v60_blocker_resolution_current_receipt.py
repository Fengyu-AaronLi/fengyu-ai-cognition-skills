#!/usr/bin/env python3
"""V60 contract: operational blocker resolution cannot use legacy audit receipts."""

from __future__ import annotations

import json
import unittest

from test_v14_evolution_lineage_and_governance import result_payload, write_json
import test_v47_blocker_resolution_loop as v47


class CurrentBlockerResolutionReceiptTests(v47.BlockerResolutionLoopTests):
    def test_legacy_v11_receipt_cannot_close_a_current_blocker(self) -> None:
        relative, _ = self.make_receipt(name="legacy-current-resolution")
        resolution_path = self.fixture.root / relative
        resolution = json.loads(resolution_path.read_text(encoding="utf-8"))
        audit_path = self.fixture.root / resolution["verification"]["audit_receipt"]["path"]
        audit = json.loads(audit_path.read_text(encoding="utf-8"))
        audit["schema_version"] = "1.1"
        for command in audit["commands"]:
            command.pop("script_path", None)
            command.pop("script_sha256", None)
            command.pop("input_snapshot", None)
        write_json(audit_path, audit)
        from test_v14_evolution_lineage_and_governance import digest

        resolution["verification"]["audit_receipt"]["sha256"] = digest(audit_path)
        write_json(resolution_path, resolution)

        result, _ = self.advance_with_resolution(relative, name="v60-legacy-r3")

        self.assertEqual(3, result.returncode, result.stdout + result.stderr)
        self.assertIn(
            "evolution_blocker_resolution_verification_invalid",
            set(result_payload(result).get("errors", [])),
        )


if __name__ == "__main__":
    unittest.main()
