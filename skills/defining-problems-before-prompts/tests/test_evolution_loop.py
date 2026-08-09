from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVOLVER = ROOT / "scripts" / "dpbp-evolve"
ZERO_HASH = "0" * 64


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


class EvolutionLoopContract(unittest.TestCase):
    maxDiff = None

    def run_cli(
        self,
        *args: str,
        payload: object | str = "",
    ) -> subprocess.CompletedProcess[str]:
        self.assertTrue(
            EVOLVER.is_file(),
            "scripts/dpbp-evolve is missing; failure-driven evolution is not implemented",
        )
        raw = payload if isinstance(payload, str) else canonical_json(payload)
        return subprocess.run(
            [str(EVOLVER), *args],
            input=raw,
            text=True,
            capture_output=True,
            cwd=ROOT,
            check=False,
        )

    def parsed(self, result: subprocess.CompletedProcess[str]) -> dict[str, Any]:
        self.assertEqual("", result.stderr)
        value = json.loads(result.stdout)
        self.assertIsInstance(value, dict)
        return value

    def make_workspace(
        self,
        root: Path,
        *,
        suite_id: str = "CUSTOM-EVOLUTION-SUITE",
        max_iterations: int = 3,
        saturation_window: int = 2,
        minimum_improvement: float = 0.05,
    ) -> dict[str, Any]:
        cases = root / "cases"
        sealed = root / "sealed"
        cases.mkdir(parents=True)
        sealed.mkdir(parents=True)

        regression_input = "自定义回归输入，不允许由工具硬编码。"
        holdout_marker = "TOP-SECRET-HOLDOUT-CONTENT"
        regression_path = cases / "CUSTOM-REGRESSION.json"
        holdout_path = sealed / "CUSTOM-HOLDOUT.json"
        regression_path.write_text(
            canonical_json({"input": regression_input}) + "\n",
            encoding="utf-8",
        )
        holdout_path.write_text(
            canonical_json({"input": holdout_marker}) + "\n",
            encoding="utf-8",
        )

        manifest = {
            "schema_version": "1.0",
            "suite_id": suite_id,
            "suite_version": "2026-08-06-red",
            "partitions": {
                "regression": [
                    {
                        "case_id": "CUSTOM-REGRESSION",
                        "input_file": "cases/CUSTOM-REGRESSION.json",
                        "input_sha256": sha256_bytes(regression_path.read_bytes()),
                    }
                ],
                "sealed_holdout": [
                    {
                        "case_id": "CUSTOM-HOLDOUT",
                        "sealed_file": "sealed/CUSTOM-HOLDOUT.json",
                        "sealed_sha256": sha256_bytes(holdout_path.read_bytes()),
                    }
                ],
            },
            "policy": {
                "max_iterations": max_iterations,
                "saturation_window": saturation_window,
                "minimum_improvement": minimum_improvement,
                "required_roles": ["author", "reproducer", "reviewer"],
            },
        }
        manifest_path = root / "suite-manifest.json"
        manifest_path.write_text(canonical_json(manifest) + "\n", encoding="utf-8")
        return {
            "manifest": manifest,
            "manifest_path": manifest_path,
            "manifest_sha256": sha256_bytes(manifest_path.read_bytes()),
            "case_input_sha256": {
                "regression": {
                    "CUSTOM-REGRESSION": sha256_bytes(regression_path.read_bytes()),
                },
                "sealed_holdout": {
                    "CUSTOM-HOLDOUT": sha256_bytes(holdout_path.read_bytes()),
                },
            },
            "state_path": root / "evolution-state.json",
            "ledger_path": root / "evolution-ledger.jsonl",
            "holdout_marker": holdout_marker,
            "holdout_path": holdout_path,
            "holdout_sha256": sha256_bytes(holdout_path.read_bytes()),
            "observed_failure_receipts": {},
        }

    def init(self, workspace: dict[str, Any]) -> dict[str, Any]:
        result = self.init_command(workspace)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return self.parsed(result)

    def init_command(
        self,
        workspace: dict[str, Any],
        *,
        state_path: Path | None = None,
        ledger_path: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            "init",
            "--manifest",
            str(workspace["manifest_path"]),
            "--state",
            str(state_path or workspace["state_path"]),
            "--ledger",
            str(ledger_path or workspace["ledger_path"]),
        )

    def command(
        self,
        name: str,
        workspace: dict[str, Any],
        *,
        payload: object | str = "",
    ) -> subprocess.CompletedProcess[str]:
        return self.run_cli(
            name,
            "--state",
            str(workspace["state_path"]),
            "--ledger",
            str(workspace["ledger_path"]),
            payload=payload,
        )

    def receipt(
        self,
        workspace: dict[str, Any],
        *,
        receipt_id: str,
        case_id: str = "CUSTOM-REGRESSION",
        partition: str = "regression",
        variant: str,
        outcome: str,
        actor_id: str,
        candidate_sha256: str,
        failure_codes: list[str] | None = None,
        raw_input_sha256: str | None = None,
    ) -> dict[str, Any]:
        if raw_input_sha256 is None:
            try:
                raw_input_sha256 = workspace["case_input_sha256"][partition][case_id]
            except KeyError as error:
                raise AssertionError(
                    f"test receipt needs an explicit input hash for {partition}:{case_id}"
                ) from error
        return {
            "schema_version": "1.0",
            "receipt_id": receipt_id,
            "suite_id": workspace["manifest"]["suite_id"],
            "suite_version": workspace["manifest"]["suite_version"],
            "suite_manifest_sha256": workspace["manifest_sha256"],
            "case_id": case_id,
            "partition": partition,
            "variant": variant,
            "outcome": outcome,
            "actor_id": actor_id,
            "candidate_sha256": candidate_sha256,
            "failure_codes": failure_codes or [],
            "raw_input_sha256": raw_input_sha256,
            "raw_output_sha256": sha256_text(
                f"output:{receipt_id}:{outcome}:{candidate_sha256}"
            ),
            "environment": {
                "runner": "black-box-contract-runner",
                "model": "fixture-model",
                "offline": True,
            },
        }

    def failure_event(
        self,
        workspace: dict[str, Any],
        *,
        event_id: str,
        case_id: str = "CUSTOM-REGRESSION",
    ) -> dict[str, Any]:
        base_sha = sha256_text(f"base:{event_id}")
        return {
            "event_id": event_id,
            "event_type": "failure_observed",
            "actor": {"id": "author-A", "role": "author"},
            "case_id": case_id,
            "partition": "regression",
            "failure_codes": ["generic_list"],
            "receipt": self.receipt(
                workspace,
                receipt_id=f"receipt-{event_id}",
                case_id=case_id,
                variant="base",
                outcome="fail",
                actor_id="author-A",
                candidate_sha256=base_sha,
                failure_codes=["generic_list"],
            ),
        }

    def record_failure(
        self,
        workspace: dict[str, Any],
        *,
        event_id: str,
    ) -> dict[str, Any]:
        event = self.failure_event(workspace, event_id=event_id)
        result = self.command(
            "record",
            workspace,
            payload=event,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        workspace["observed_failure_receipts"][event_id] = copy.deepcopy(event["receipt"])
        return self.parsed(result)

    def cycle_payload(
        self,
        workspace: dict[str, Any],
        *,
        cycle_id: str,
        failure_event_id: str,
        author_id: str = "author-A",
        reproducer_id: str = "reproducer-B",
        reviewer_id: str = "reviewer-C",
        candidate_outcome: str = "pass",
        improvement: float = 1.0,
        case_id: str = "CUSTOM-REGRESSION",
        partition: str = "regression",
        raw_input_sha256: str | None = None,
    ) -> dict[str, Any]:
        candidate_sha = sha256_text(f"candidate:{cycle_id}")
        candidate_failures = [] if candidate_outcome == "pass" else ["generic_list"]
        try:
            base_receipt = copy.deepcopy(
                workspace["observed_failure_receipts"][failure_event_id]
            )
        except KeyError as error:
            raise AssertionError(
                f"cycle needs the observed RED receipt for {failure_event_id}"
            ) from error
        return {
            "cycle_id": cycle_id,
            "failure_event_id": failure_event_id,
            "candidate_sha256": candidate_sha,
            "roles": {
                "author": author_id,
                "reproducer": reproducer_id,
                "reviewer": reviewer_id,
            },
            "base_receipt": base_receipt,
            "candidate_receipt": self.receipt(
                workspace,
                receipt_id=f"{cycle_id}-candidate",
                case_id=case_id,
                partition=partition,
                variant="candidate",
                outcome=candidate_outcome,
                actor_id=author_id,
                candidate_sha256=candidate_sha,
                failure_codes=candidate_failures,
                raw_input_sha256=raw_input_sha256,
            ),
            "reproduction_receipt": self.receipt(
                workspace,
                receipt_id=f"{cycle_id}-reproduction",
                case_id=case_id,
                partition=partition,
                variant="candidate",
                outcome=candidate_outcome,
                actor_id=reproducer_id,
                candidate_sha256=candidate_sha,
                failure_codes=candidate_failures,
                raw_input_sha256=raw_input_sha256,
            ),
            "review": {
                "actor_id": reviewer_id,
                "approved": candidate_outcome == "pass",
            },
            "improvement": improvement,
        }

    def close_cycle(
        self,
        workspace: dict[str, Any],
        *,
        cycle_id: str,
        failure_event_id: str,
        candidate_outcome: str = "pass",
        improvement: float = 1.0,
        case_id: str = "CUSTOM-REGRESSION",
        partition: str = "regression",
        raw_input_sha256: str | None = None,
    ) -> dict[str, Any]:
        result = self.command(
            "close-cycle",
            workspace,
            payload=self.cycle_payload(
                workspace,
                cycle_id=cycle_id,
                failure_event_id=failure_event_id,
                candidate_outcome=candidate_outcome,
                improvement=improvement,
                case_id=case_id,
                partition=partition,
                raw_input_sha256=raw_input_sha256,
            ),
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return self.parsed(result)

    def promote(
        self,
        workspace: dict[str, Any],
        *,
        event_id: str,
        cycle_id: str,
    ) -> subprocess.CompletedProcess[str]:
        return self.command(
            "promote",
            workspace,
            payload=self.promotion_payload(event_id=event_id, cycle_id=cycle_id),
        )

    def promotion_payload(
        self,
        *,
        event_id: str,
        cycle_id: str,
    ) -> dict[str, Any]:
        return {
            "event_id": event_id,
            "cycle_id": cycle_id,
            "actor": {"id": "reviewer-C", "role": "reviewer"},
        }

    def status(self, workspace: dict[str, Any]) -> dict[str, Any]:
        result = self.command("status", workspace)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)
        return self.parsed(result)

    def ready_workspace(self, root: Path) -> dict[str, Any]:
        workspace = self.make_workspace(root)
        self.init(workspace)
        self.record_failure(workspace, event_id="failure-derived-state")
        self.close_cycle(
            workspace,
            cycle_id="cycle-derived-state",
            failure_event_id="failure-derived-state",
        )
        return workspace

    def stopped_workspace(self, root: Path) -> dict[str, Any]:
        workspace = self.make_workspace(root, max_iterations=1, saturation_window=9)
        self.init(workspace)
        for suffix in ("one", "two", "three"):
            self.record_failure(workspace, event_id=f"failure-terminal-{suffix}")
        close_payloads: dict[str, dict[str, Any]] = {}
        for suffix in ("one", "two"):
            payload = self.cycle_payload(
                workspace,
                cycle_id=f"cycle-terminal-{suffix}",
                failure_event_id=f"failure-terminal-{suffix}",
            )
            result = self.command("close-cycle", workspace, payload=payload)
            self.assertEqual(0, result.returncode, result.stdout + result.stderr)
            close_payloads[suffix] = payload
        promotion_payload = self.promotion_payload(
            event_id="promotion-terminal-one",
            cycle_id="cycle-terminal-one",
        )
        promoted = self.command("promote", workspace, payload=promotion_payload)
        self.assertEqual(0, promoted.returncode, promoted.stdout + promoted.stderr)
        workspace["terminal_fixtures"] = {
            "close_payloads": close_payloads,
            "promotion_payload": promotion_payload,
            "promotion_result": self.parsed(promoted),
        }
        self.assertEqual("stopped", self.status(workspace)["phase"])
        return workspace

    def tamper_derived_state(
        self,
        workspace: dict[str, Any],
        field: str,
    ) -> None:
        state = json.loads(workspace["state_path"].read_text(encoding="utf-8"))
        if field == "budget":
            state["budget"]["iterations_used"] = 999
        elif field == "stop":
            state["stop"] = {"reason": "forged_stop", "stopped": True}
        elif field == "roles":
            state["cycles"]["cycle-derived-state"]["roles"]["reviewer"] = "forged-reviewer"
        elif field == "cycle":
            state["cycles"]["cycle-derived-state"]["status"] = "promoted"
        else:
            raise AssertionError(f"unsupported test tamper field: {field}")
        workspace["state_path"].write_text(
            canonical_json(state) + "\n",
            encoding="utf-8",
        )

    def test_init_reads_the_single_suite_manifest_as_source_of_truth(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_workspace(
                Path(temp_dir), suite_id="NOT-A-HARDCODED-SUITE"
            )
            initialized = self.init(workspace)
            self.assertEqual("NOT-A-HARDCODED-SUITE", initialized["suite"]["suite_id"])
            self.assertEqual("2026-08-06-red", initialized["suite"]["suite_version"])
            self.assertEqual(
                workspace["manifest_sha256"],
                initialized["suite"]["manifest_sha256"],
            )
            self.assertEqual(
                ["CUSTOM-REGRESSION"], initialized["suite"]["regression_case_ids"]
            )
            self.assertEqual(
                ["CUSTOM-HOLDOUT"], initialized["suite"]["holdout_case_ids"]
            )
            self.assertEqual("self_attested", initialized["assurance"]["actor_identity"])
            self.assertEqual("hash_declared", initialized["assurance"]["run_artifacts"])

    def test_init_rejects_state_and_ledger_paths_that_alias_the_same_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            workspace = self.make_workspace(root / "workspace")
            scenarios: list[tuple[str, Path, Path, bytes | None]] = []

            literal = root / "literal.json"
            scenarios.append(("literal", literal, literal, None))

            normalized_parent = root / "normalized"
            (normalized_parent / "child").mkdir(parents=True)
            normalized = normalized_parent / "shared.json"
            scenarios.append(
                (
                    "normalized",
                    normalized,
                    normalized_parent / "child" / ".." / "shared.json",
                    None,
                )
            )

            real_parent = root / "real-parent"
            real_parent.mkdir()
            linked_parent = root / "linked-parent"
            linked_parent.symlink_to(real_parent, target_is_directory=True)
            scenarios.append(
                (
                    "symlink-parent",
                    real_parent / "shared.json",
                    linked_parent / "shared.json",
                    None,
                )
            )

            inode_state = root / "inode-state.json"
            inode_ledger = root / "inode-ledger.jsonl"
            inode_bytes = b'{"legacy":"same-inode"}\n'
            inode_state.write_bytes(inode_bytes)
            os.link(inode_state, inode_ledger)
            scenarios.append(("existing-inode", inode_state, inode_ledger, inode_bytes))

            for name, state_path, ledger_path, original in scenarios:
                with self.subTest(alias=name):
                    result = self.init_command(
                        workspace,
                        state_path=state_path,
                        ledger_path=ledger_path,
                    )

                    self.assertEqual(5, result.returncode)
                    self.assertEqual(
                        "STATE_LEDGER_PATH_ALIAS",
                        self.parsed(result)["error"]["code"],
                    )
                    if original is None:
                        self.assertFalse(state_path.exists())
                        self.assertFalse(ledger_path.exists())
                    else:
                        self.assertEqual(original, state_path.read_bytes())
                        self.assertEqual(original, ledger_path.read_bytes())

    def test_manifest_numeric_policy_rejects_nan_and_infinity(self) -> None:
        for field in ("minimum_improvement", "max_iterations"):
            for value in (float("nan"), float("inf")):
                with self.subTest(field=field, value=str(value)):
                    with tempfile.TemporaryDirectory() as temp_dir:
                        workspace = self.make_workspace(Path(temp_dir))
                        manifest = copy.deepcopy(workspace["manifest"])
                        manifest["policy"][field] = value
                        workspace["manifest_path"].write_text(
                            canonical_json(manifest) + "\n",
                            encoding="utf-8",
                        )

                        result = self.init_command(workspace)

                        self.assertNotEqual(0, result.returncode)
                        self.assertEqual("MANIFEST_INVALID", self.parsed(result)["error"]["code"])
                        self.assertFalse(workspace["state_path"].exists())
                        self.assertFalse(workspace["ledger_path"].exists())

    def test_improvement_rejects_json_nan_and_nonfinite_exponents_without_writing(self) -> None:
        for encoding, expected_code, expected_exit in (
            ("NaN", "INVALID_JSON", 2),
            ("1e400", "IMPROVEMENT_INVALID", 5),
        ):
            with self.subTest(improvement=encoding):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = self.make_workspace(Path(temp_dir))
                    self.init(workspace)
                    self.record_failure(workspace, event_id="failure-nonfinite-improvement")
                    cycle = self.cycle_payload(
                        workspace,
                        cycle_id="cycle-nonfinite-improvement",
                        failure_event_id="failure-nonfinite-improvement",
                    )
                    raw = canonical_json(cycle).replace('"improvement":1.0', f'"improvement":{encoding}')
                    ledger_before = workspace["ledger_path"].read_bytes()
                    state_before = workspace["state_path"].read_bytes()

                    result = self.command("close-cycle", workspace, payload=raw)

                    self.assertEqual(expected_exit, result.returncode)
                    self.assertEqual(expected_code, self.parsed(result)["error"]["code"])
                    self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())
                    self.assertEqual(state_before, workspace["state_path"].read_bytes())

    def test_repeated_init_is_idempotent_only_after_full_checkpoint_validation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_workspace(Path(temp_dir))
            initialized = self.init(workspace)
            state_before = workspace["state_path"].read_bytes()
            ledger_before = workspace["ledger_path"].read_bytes()

            repeated = self.run_cli(
                "init",
                "--manifest",
                str(workspace["manifest_path"]),
                "--state",
                str(workspace["state_path"]),
                "--ledger",
                str(workspace["ledger_path"]),
            )

            self.assertEqual(0, repeated.returncode, repeated.stdout + repeated.stderr)
            self.assertEqual(initialized, self.parsed(repeated))
            self.assertEqual(state_before, workspace["state_path"].read_bytes())
            self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

            self.tamper_derived_state(workspace, "budget")
            rejected = self.run_cli(
                "init",
                "--manifest",
                str(workspace["manifest_path"]),
                "--state",
                str(workspace["state_path"]),
                "--ledger",
                str(workspace["ledger_path"]),
            )

            self.assertEqual(5, rejected.returncode)
            self.assertEqual(
                "STATE_DERIVATION_MISMATCH",
                self.parsed(rejected)["error"]["code"],
            )
            self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

    def test_ledger_is_append_only_hash_chained_and_deduplicates_event_ids(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_workspace(Path(temp_dir))
            self.init(workspace)
            ledger = workspace["ledger_path"]
            before = ledger.read_bytes()
            event = self.failure_event(workspace, event_id="event-once")

            first_result = self.command("record", workspace, payload=event)
            self.assertEqual(0, first_result.returncode, first_result.stdout + first_result.stderr)
            first = self.parsed(first_result)
            self.assertFalse(first["deduplicated"])
            after_first = ledger.read_bytes()
            self.assertTrue(after_first.startswith(before))
            self.assertGreater(len(after_first), len(before))

            duplicate_result = self.command("record", workspace, payload=event)
            self.assertEqual(
                0, duplicate_result.returncode, duplicate_result.stdout + duplicate_result.stderr
            )
            duplicate = self.parsed(duplicate_result)
            self.assertTrue(duplicate["deduplicated"])
            self.assertEqual(after_first, ledger.read_bytes())

            entries = [json.loads(line) for line in ledger.read_text().splitlines()]
            previous = ZERO_HASH
            for sequence, entry in enumerate(entries):
                with self.subTest(sequence=sequence):
                    self.assertEqual(sequence, entry["sequence"])
                    self.assertEqual(previous, entry["previous_hash"])
                    body = {key: value for key, value in entry.items() if key != "event_hash"}
                    expected = sha256_text(canonical_json(body))
                    self.assertEqual(expected, entry["event_hash"])
                    previous = entry["event_hash"]

    def test_record_and_promote_reject_reserved_internal_event_namespaces(self) -> None:
        for event_id in ("evolution:external", "cycle:external"):
            with self.subTest(command="record", event_id=event_id):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = self.make_workspace(Path(temp_dir))
                    self.init(workspace)
                    ledger_before = workspace["ledger_path"].read_bytes()
                    event = self.failure_event(workspace, event_id=event_id)

                    result = self.command("record", workspace, payload=event)

                    self.assertEqual(5, result.returncode)
                    self.assertEqual("EVENT_ID_RESERVED", self.parsed(result)["error"]["code"])
                    self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

            with self.subTest(command="promote", event_id=event_id):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = self.ready_workspace(Path(temp_dir))
                    ledger_before = workspace["ledger_path"].read_bytes()
                    payload = self.promotion_payload(
                        event_id=event_id,
                        cycle_id="cycle-derived-state",
                    )

                    result = self.command("promote", workspace, payload=payload)

                    self.assertEqual(5, result.returncode)
                    self.assertEqual("EVENT_ID_RESERVED", self.parsed(result)["error"]["code"])
                    self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

    def test_all_mutation_event_ids_must_be_nonempty_strings(self) -> None:
        for invalid in (None, ""):
            with self.subTest(command="record", event_id=invalid):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = self.make_workspace(Path(temp_dir))
                    self.init(workspace)
                    event = self.failure_event(workspace, event_id="valid-placeholder")
                    event["event_id"] = invalid
                    ledger_before = workspace["ledger_path"].read_bytes()
                    result = self.command("record", workspace, payload=event)
                    self.assertEqual(5, result.returncode)
                    self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

            with self.subTest(command="close-cycle", cycle_id=invalid):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = self.make_workspace(Path(temp_dir))
                    self.init(workspace)
                    self.record_failure(workspace, event_id="failure-invalid-cycle-id")
                    cycle = self.cycle_payload(
                        workspace,
                        cycle_id="valid-cycle-placeholder",
                        failure_event_id="failure-invalid-cycle-id",
                    )
                    cycle["cycle_id"] = invalid
                    ledger_before = workspace["ledger_path"].read_bytes()
                    result = self.command("close-cycle", workspace, payload=cycle)
                    self.assertEqual(5, result.returncode)
                    self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

            with self.subTest(command="promote", event_id=invalid):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = self.ready_workspace(Path(temp_dir))
                    payload = self.promotion_payload(
                        event_id="valid-promotion-placeholder",
                        cycle_id="cycle-derived-state",
                    )
                    payload["event_id"] = invalid
                    ledger_before = workspace["ledger_path"].read_bytes()
                    result = self.command("promote", workspace, payload=payload)
                    self.assertEqual(5, result.returncode)
                    self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

    def test_close_cycle_rejects_a_legacy_global_event_id_collision_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_workspace(Path(temp_dir))
            self.init(workspace)
            self.record_failure(workspace, event_id="legacy-failure")

            entries = [
                json.loads(line)
                for line in workspace["ledger_path"].read_text(encoding="utf-8").splitlines()
            ]
            entries[-1]["event_id"] = "cycle:collision"
            body = {key: value for key, value in entries[-1].items() if key != "event_hash"}
            entries[-1]["event_hash"] = sha256_text(canonical_json(body))
            workspace["ledger_path"].write_text(
                "".join(canonical_json(entry) + "\n" for entry in entries),
                encoding="utf-8",
            )
            state = json.loads(workspace["state_path"].read_text(encoding="utf-8"))
            state["ledger_head"] = entries[-1]["event_hash"]
            workspace["state_path"].write_text(canonical_json(state) + "\n", encoding="utf-8")
            self.assertEqual("collecting_failures", self.status(workspace)["phase"])

            cycle = self.cycle_payload(
                workspace,
                cycle_id="collision",
                failure_event_id="legacy-failure",
            )
            ledger_before = workspace["ledger_path"].read_bytes()
            result = self.command("close-cycle", workspace, payload=cycle)

            self.assertEqual(5, result.returncode)
            self.assertEqual("EVENT_ID_CONFLICT", self.parsed(result)["error"]["code"])
            self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())
            self.assertEqual("collecting_failures", self.status(workspace)["phase"])

    def test_promotion_event_id_cannot_collide_with_an_existing_record_event(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_workspace(Path(temp_dir))
            self.init(workspace)
            self.record_failure(workspace, event_id="shared-event-id")
            self.close_cycle(
                workspace,
                cycle_id="cycle-shared-event",
                failure_event_id="shared-event-id",
            )
            ledger_before = workspace["ledger_path"].read_bytes()

            result = self.command(
                "promote",
                workspace,
                payload=self.promotion_payload(
                    event_id="shared-event-id",
                    cycle_id="cycle-shared-event",
                ),
            )

            self.assertEqual(5, result.returncode)
            self.assertEqual("EVENT_ID_CONFLICT", self.parsed(result)["error"]["code"])
            self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

    def test_red_base_and_green_candidate_close_a_traceable_failure_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_workspace(Path(temp_dir))
            self.init(workspace)
            self.record_failure(workspace, event_id="failure-red-green")
            closed = self.close_cycle(
                workspace,
                cycle_id="cycle-red-green",
                failure_event_id="failure-red-green",
            )
            self.assertEqual("ready_for_promotion", closed["phase"])
            cycle = closed["cycle"]
            self.assertEqual(
                workspace["observed_failure_receipts"]["failure-red-green"],
                cycle["evidence"]["base"],
            )
            self.assertEqual("fail", cycle["evidence"]["base"]["outcome"])
            self.assertEqual("pass", cycle["evidence"]["candidate"]["outcome"])
            self.assertEqual("pass", cycle["evidence"]["reproduction"]["outcome"])
            self.assertEqual("failure-red-green", cycle["failure_event_id"])
            self.assertRegex(cycle["evidence_digest"], r"^[a-f0-9]{64}$")

            promoted_result = self.promote(
                workspace,
                event_id="promotion-red-green",
                cycle_id="cycle-red-green",
            )
            self.assertEqual(
                0,
                promoted_result.returncode,
                promoted_result.stdout + promoted_result.stderr,
            )
            promoted = self.parsed(promoted_result)
            self.assertEqual("promoted", promoted["cycle"]["status"])
            self.assertEqual(1, promoted["budget"]["iterations_used"])

    def test_cycle_rejects_any_replacement_of_the_observed_red_receipt(self) -> None:
        replacements: dict[str, Any] = {
            "receipt_id": "replacement-receipt",
            "candidate_sha256": sha256_text("replacement base candidate"),
            "raw_output_sha256": sha256_text("replacement base output"),
            "failure_codes": ["replacement_failure"],
        }
        for field, replacement in replacements.items():
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = self.make_workspace(Path(temp_dir))
                    self.init(workspace)
                    self.record_failure(workspace, event_id="failure-observed-red")
                    cycle = self.cycle_payload(
                        workspace,
                        cycle_id="cycle-replaced-red",
                        failure_event_id="failure-observed-red",
                    )
                    cycle["base_receipt"][field] = replacement
                    ledger_before = workspace["ledger_path"].read_bytes()

                    result = self.command("close-cycle", workspace, payload=cycle)

                    self.assertEqual(5, result.returncode)
                    self.assertEqual(
                        "BASE_RECEIPT_MISMATCH",
                        self.parsed(result)["error"]["code"],
                    )
                    self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

    def test_close_cycle_replay_is_idempotent_only_for_an_identical_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_workspace(Path(temp_dir))
            self.init(workspace)
            self.record_failure(workspace, event_id="failure-cycle-replay")
            cycle = self.cycle_payload(
                workspace,
                cycle_id="cycle-replay",
                failure_event_id="failure-cycle-replay",
            )

            first = self.command("close-cycle", workspace, payload=cycle)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            ledger_after = workspace["ledger_path"].read_bytes()

            identical = self.command("close-cycle", workspace, payload=cycle)
            self.assertEqual(0, identical.returncode, identical.stdout + identical.stderr)
            self.assertEqual(ledger_after, workspace["ledger_path"].read_bytes())

            replacement = copy.deepcopy(cycle)
            replacement["base_receipt"]["receipt_id"] = "replacement-on-replay"
            conflict = self.command("close-cycle", workspace, payload=replacement)

            self.assertEqual(5, conflict.returncode)
            self.assertEqual(
                "CYCLE_ID_CONFLICT",
                self.parsed(conflict)["error"]["code"],
            )
            self.assertEqual(ledger_after, workspace["ledger_path"].read_bytes())

    def test_failure_receipt_input_hash_must_match_manifest_case(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_workspace(Path(temp_dir))
            self.init(workspace)
            event = self.failure_event(workspace, event_id="failure-wrong-input")
            event["receipt"]["raw_input_sha256"] = sha256_text("different input")
            ledger_before = workspace["ledger_path"].read_bytes()

            result = self.command("record", workspace, payload=event)

            self.assertEqual(5, result.returncode)
            self.assertEqual("RECEIPT_INPUT_MISMATCH", self.parsed(result)["error"]["code"])
            self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

    def test_failure_record_requires_bound_actor_receipt_id_and_failure_codes(self) -> None:
        scenarios = {
            "empty-event-failure-codes": "FAILURE_CODES_INVALID",
            "mismatched-failure-codes": "FAILURE_CODES_MISMATCH",
            "invalid-receipt-failure-codes": "RECEIPT_INVALID",
            "empty-receipt-id": "RECEIPT_INVALID",
            "actor-id-mismatch": "ACTOR_BINDING_MISMATCH",
            "actor-role-mismatch": "ACTOR_BINDING_MISMATCH",
        }
        for scenario, expected_code in scenarios.items():
            with self.subTest(scenario=scenario):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = self.make_workspace(Path(temp_dir))
                    self.init(workspace)
                    event = self.failure_event(workspace, event_id=f"failure-{scenario}")
                    if scenario == "empty-event-failure-codes":
                        event["failure_codes"] = []
                    elif scenario == "mismatched-failure-codes":
                        event["failure_codes"] = ["different_failure"]
                    elif scenario == "invalid-receipt-failure-codes":
                        event["failure_codes"] = [""]
                        event["receipt"]["failure_codes"] = [""]
                    elif scenario == "empty-receipt-id":
                        event["receipt"]["receipt_id"] = ""
                    elif scenario == "actor-id-mismatch":
                        event["actor"]["id"] = "different-author"
                    elif scenario == "actor-role-mismatch":
                        event["actor"]["role"] = "reviewer"
                    ledger_before = workspace["ledger_path"].read_bytes()

                    result = self.command("record", workspace, payload=event)

                    self.assertEqual(5, result.returncode)
                    self.assertEqual(expected_code, self.parsed(result)["error"]["code"])
                    self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

    def test_pass_and_fail_receipts_enforce_failure_code_polarity(self) -> None:
        for outcome, invalid_codes in (("pass", ["unexpected_failure"]), ("fail", [])):
            for receipt_name in ("candidate_receipt", "reproduction_receipt"):
                with self.subTest(outcome=outcome, receipt=receipt_name):
                    with tempfile.TemporaryDirectory() as temp_dir:
                        workspace = self.make_workspace(Path(temp_dir))
                        self.init(workspace)
                        self.record_failure(workspace, event_id="failure-code-polarity")
                        cycle = self.cycle_payload(
                            workspace,
                            cycle_id="cycle-code-polarity",
                            failure_event_id="failure-code-polarity",
                            candidate_outcome=outcome,
                        )
                        cycle[receipt_name]["failure_codes"] = invalid_codes
                        ledger_before = workspace["ledger_path"].read_bytes()

                        result = self.command("close-cycle", workspace, payload=cycle)

                        self.assertEqual(5, result.returncode)
                        self.assertEqual("RECEIPT_INVALID", self.parsed(result)["error"]["code"])
                        self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

    def test_holdout_record_actor_must_match_the_receipt_reproducer(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_workspace(Path(temp_dir))
            self.init(workspace)
            receipt = self.receipt(
                workspace,
                receipt_id="holdout-actor-binding",
                case_id="CUSTOM-HOLDOUT",
                partition="sealed_holdout",
                variant="candidate",
                outcome="pass",
                actor_id="reproducer-B",
                candidate_sha256=sha256_text("candidate:holdout-actor"),
            )
            ledger_before = workspace["ledger_path"].read_bytes()
            result = self.command(
                "record",
                workspace,
                payload={
                    "event_id": "holdout-actor-mismatch",
                    "event_type": "holdout_result",
                    "actor": {"id": "author-A", "role": "author"},
                    "case_id": "CUSTOM-HOLDOUT",
                    "partition": "sealed_holdout",
                    "receipt": receipt,
                },
            )

            self.assertEqual(5, result.returncode)
            self.assertEqual("ACTOR_BINDING_MISMATCH", self.parsed(result)["error"]["code"])
            self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

    def test_cycle_receipts_must_share_the_manifest_bound_input(self) -> None:
        for receipt_name in ("base_receipt", "candidate_receipt", "reproduction_receipt"):
            with self.subTest(receipt=receipt_name):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = self.make_workspace(Path(temp_dir))
                    self.init(workspace)
                    self.record_failure(workspace, event_id="failure-cycle-input")
                    cycle = self.cycle_payload(
                        workspace,
                        cycle_id="cycle-wrong-input",
                        failure_event_id="failure-cycle-input",
                    )
                    cycle[receipt_name]["raw_input_sha256"] = sha256_text(
                        f"different input:{receipt_name}"
                    )
                    ledger_before = workspace["ledger_path"].read_bytes()

                    result = self.command("close-cycle", workspace, payload=cycle)

                    self.assertEqual(5, result.returncode)
                    self.assertEqual(
                        "RECEIPT_INPUT_MISMATCH",
                        self.parsed(result)["error"]["code"],
                    )
                    self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

    def test_status_rejects_derived_state_tampering_without_a_ledger_change(self) -> None:
        for field in ("budget", "stop", "roles", "cycle"):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = self.ready_workspace(Path(temp_dir))
                    ledger_before = workspace["ledger_path"].read_bytes()
                    self.tamper_derived_state(workspace, field)

                    result = self.command("status", workspace)

                    self.assertEqual(5, result.returncode)
                    self.assertEqual(
                        "STATE_DERIVATION_MISMATCH",
                        self.parsed(result)["error"]["code"],
                    )
                    self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

    def test_promote_rejects_derived_state_tampering_without_a_ledger_change(self) -> None:
        for field in ("budget", "stop", "roles", "cycle"):
            with self.subTest(field=field):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = self.ready_workspace(Path(temp_dir))
                    ledger_before = workspace["ledger_path"].read_bytes()
                    self.tamper_derived_state(workspace, field)

                    result = self.promote(
                        workspace,
                        event_id=f"promotion-after-{field}-tamper",
                        cycle_id="cycle-derived-state",
                    )

                    self.assertEqual(5, result.returncode)
                    self.assertEqual(
                        "STATE_DERIVATION_MISMATCH",
                        self.parsed(result)["error"]["code"],
                    )
                    self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

    def test_author_reproducer_and_reviewer_must_be_three_people(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_workspace(Path(temp_dir))
            self.init(workspace)
            self.record_failure(workspace, event_id="failure-role-conflict")
            ledger_before = workspace["ledger_path"].read_bytes()
            invalid = self.cycle_payload(
                workspace,
                cycle_id="cycle-role-conflict",
                failure_event_id="failure-role-conflict",
                author_id="same-person",
                reproducer_id="same-person",
                reviewer_id="reviewer-C",
            )
            result = self.command("close-cycle", workspace, payload=invalid)
            self.assertEqual(5, result.returncode)
            error = self.parsed(result)["error"]
            self.assertEqual("ROLE_SEPARATION_REQUIRED", error["code"])
            self.assertEqual(ledger_before, workspace["ledger_path"].read_bytes())

    def test_sealed_holdout_is_hidden_until_consumed_and_then_becomes_spent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_workspace(Path(temp_dir))
            self.init(workspace)

            before_result = self.command("status", workspace)
            self.assertEqual(0, before_result.returncode, before_result.stdout + before_result.stderr)
            self.assertNotIn(workspace["holdout_marker"], before_result.stdout)
            self.assertNotIn("sealed/CUSTOM-HOLDOUT.json", before_result.stdout)
            before = self.parsed(before_result)
            self.assertEqual(
                [
                    {
                        "case_id": "CUSTOM-HOLDOUT",
                        "sealed_sha256": workspace["holdout_sha256"],
                        "status": "sealed",
                    }
                ],
                before["holdouts"],
            )

            holdout_receipt = self.receipt(
                workspace,
                receipt_id="holdout-receipt-1",
                case_id="CUSTOM-HOLDOUT",
                partition="sealed_holdout",
                variant="candidate",
                outcome="pass",
                actor_id="reproducer-B",
                candidate_sha256=sha256_text("candidate:holdout"),
            )
            consumed_result = self.command(
                "record",
                workspace,
                payload={
                    "event_id": "holdout-consumption-1",
                    "event_type": "holdout_result",
                    "actor": {"id": "reproducer-B", "role": "reproducer"},
                    "case_id": "CUSTOM-HOLDOUT",
                    "partition": "sealed_holdout",
                    "receipt": holdout_receipt,
                },
            )
            self.assertEqual(
                0,
                consumed_result.returncode,
                consumed_result.stdout + consumed_result.stderr,
            )
            after_result = self.command("status", workspace)
            self.assertEqual(0, after_result.returncode, after_result.stdout + after_result.stderr)
            self.assertNotIn(workspace["holdout_marker"], after_result.stdout)
            self.assertNotIn("sealed/CUSTOM-HOLDOUT.json", after_result.stdout)
            after = self.parsed(after_result)
            self.assertEqual("spent", after["holdouts"][0]["status"])
            self.assertEqual(
                "holdout-consumption-1", after["holdouts"][0]["consumed_by_event_id"]
            )

    def test_iteration_budget_and_saturation_are_terminal_promotion_stops(self) -> None:
        self.assertTrue(
            EVOLVER.is_file(),
            "scripts/dpbp-evolve is missing; failure-driven evolution is not implemented",
        )
        with self.subTest(stop="iteration_budget"):
            with tempfile.TemporaryDirectory() as temp_dir:
                workspace = self.make_workspace(
                    Path(temp_dir), max_iterations=1, saturation_window=9
                )
                self.init(workspace)
                for suffix in ("one", "two"):
                    self.record_failure(workspace, event_id=f"failure-budget-{suffix}")
                    self.close_cycle(
                        workspace,
                        cycle_id=f"cycle-budget-{suffix}",
                        failure_event_id=f"failure-budget-{suffix}",
                    )
                first = self.promote(
                    workspace,
                    event_id="promotion-budget-one",
                    cycle_id="cycle-budget-one",
                )
                self.assertEqual(0, first.returncode, first.stdout + first.stderr)
                status = self.status(workspace)
                self.assertTrue(status["stop"]["stopped"])
                self.assertEqual("iteration_budget_exhausted", status["stop"]["reason"])

                blocked = self.promote(
                    workspace,
                    event_id="promotion-budget-two",
                    cycle_id="cycle-budget-two",
                )
                self.assertEqual(5, blocked.returncode)
                error = self.parsed(blocked)["error"]
                self.assertEqual("EVOLUTION_STOPPED", error["code"])
                self.assertEqual("iteration_budget_exhausted", error["stop_reason"])

        with self.subTest(stop="saturation"):
            with tempfile.TemporaryDirectory() as temp_dir:
                workspace = self.make_workspace(
                    Path(temp_dir),
                    max_iterations=9,
                    saturation_window=2,
                    minimum_improvement=0.10,
                )
                self.init(workspace)
                for suffix in ("one", "two"):
                    self.record_failure(workspace, event_id=f"failure-flat-{suffix}")
                    self.close_cycle(
                        workspace,
                        cycle_id=f"cycle-flat-{suffix}",
                        failure_event_id=f"failure-flat-{suffix}",
                        candidate_outcome="fail",
                        improvement=0.0,
                    )
                status = self.status(workspace)
                self.assertTrue(status["stop"]["stopped"])
                self.assertEqual("saturation_reached", status["stop"]["reason"])
                blocked = self.promote(
                    workspace,
                    event_id="promotion-after-saturation",
                    cycle_id="cycle-flat-two",
                )
                self.assertEqual(5, blocked.returncode)
                error = self.parsed(blocked)["error"]
                self.assertEqual("EVOLUTION_STOPPED", error["code"])
                self.assertEqual("saturation_reached", error["stop_reason"])

    def test_committed_promotion_replay_precedes_iteration_budget_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_workspace(
                Path(temp_dir), max_iterations=2, saturation_window=9
            )
            self.init(workspace)
            promotion_results: list[dict[str, Any]] = []
            promotion_payloads: list[dict[str, Any]] = []
            for index in (1, 2):
                failure_id = f"failure-budget-replay-{index}"
                cycle_id = f"cycle-budget-replay-{index}"
                self.record_failure(workspace, event_id=failure_id)
                self.close_cycle(
                    workspace,
                    cycle_id=cycle_id,
                    failure_event_id=failure_id,
                )
                payload = self.promotion_payload(
                    event_id=f"promotion-budget-replay-{index}",
                    cycle_id=cycle_id,
                )
                promoted = self.command("promote", workspace, payload=payload)
                self.assertEqual(0, promoted.returncode, promoted.stdout + promoted.stderr)
                promotion_payloads.append(payload)
                promotion_results.append(self.parsed(promoted))

            self.assertEqual(1, promotion_results[0]["budget"]["iterations_used"])
            self.assertEqual(2, promotion_results[1]["budget"]["iterations_used"])
            self.assertEqual("iteration_budget_exhausted", self.status(workspace)["stop"]["reason"])
            ledger_after_stop = workspace["ledger_path"].read_bytes()

            replay = self.command("promote", workspace, payload=promotion_payloads[0])

            self.assertEqual(0, replay.returncode, replay.stdout + replay.stderr)
            self.assertEqual(promotion_results[0], self.parsed(replay))
            self.assertEqual(ledger_after_stop, workspace["ledger_path"].read_bytes())

            new_event = copy.deepcopy(promotion_payloads[0])
            new_event["event_id"] = "promotion-after-budget-stop"
            stopped = self.command("promote", workspace, payload=new_event)
            self.assertEqual(5, stopped.returncode)
            self.assertEqual("EVOLUTION_STOPPED", self.parsed(stopped)["error"]["code"])

            changed_payload = copy.deepcopy(promotion_payloads[0])
            changed_payload["actor"]["id"] = "different-reviewer"
            stopped = self.command("promote", workspace, payload=changed_payload)
            self.assertEqual(5, stopped.returncode)
            self.assertEqual("EVOLUTION_STOPPED", self.parsed(stopped)["error"]["code"])
            self.assertEqual(ledger_after_stop, workspace["ledger_path"].read_bytes())

    def test_committed_promotion_replay_precedes_later_saturation_stop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_workspace(
                Path(temp_dir), max_iterations=9, saturation_window=1, minimum_improvement=0.10
            )
            self.init(workspace)
            self.record_failure(workspace, event_id="failure-before-saturation")
            self.close_cycle(
                workspace,
                cycle_id="cycle-before-saturation",
                failure_event_id="failure-before-saturation",
                improvement=1.0,
            )
            promotion = self.promotion_payload(
                event_id="promotion-before-saturation",
                cycle_id="cycle-before-saturation",
            )
            first = self.command("promote", workspace, payload=promotion)
            self.assertEqual(0, first.returncode, first.stdout + first.stderr)
            first_result = self.parsed(first)

            self.record_failure(workspace, event_id="failure-trigger-saturation")
            self.close_cycle(
                workspace,
                cycle_id="cycle-trigger-saturation",
                failure_event_id="failure-trigger-saturation",
                candidate_outcome="fail",
                improvement=0.0,
            )
            self.assertEqual("saturation_reached", self.status(workspace)["stop"]["reason"])
            ledger_after_stop = workspace["ledger_path"].read_bytes()

            replay = self.command("promote", workspace, payload=promotion)

            self.assertEqual(0, replay.returncode, replay.stdout + replay.stderr)
            self.assertEqual(first_result, self.parsed(replay))
            self.assertEqual(ledger_after_stop, workspace["ledger_path"].read_bytes())

            new_event = copy.deepcopy(promotion)
            new_event["event_id"] = "promotion-after-saturation-stop"
            stopped = self.command("promote", workspace, payload=new_event)
            self.assertEqual(5, stopped.returncode)
            self.assertEqual("EVOLUTION_STOPPED", self.parsed(stopped)["error"]["code"])

    def test_close_cycle_reports_the_persisted_stopped_phase_when_saturation_fires(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_workspace(
                Path(temp_dir), max_iterations=9, saturation_window=1, minimum_improvement=0.10
            )
            self.init(workspace)
            self.record_failure(workspace, event_id="failure-phase-stop")

            result = self.close_cycle(
                workspace,
                cycle_id="cycle-phase-stop",
                failure_event_id="failure-phase-stop",
                improvement=0.0,
            )
            persisted = json.loads(workspace["state_path"].read_text(encoding="utf-8"))

            self.assertEqual("ready_for_promotion", result["cycle"]["status"])
            self.assertEqual("stopped", persisted["phase"])
            self.assertEqual(persisted["phase"], result["phase"])
            self.assertEqual("saturation_reached", persisted["stop"]["reason"])

    def test_terminal_stop_allows_only_exact_replays_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.stopped_workspace(Path(temp_dir))
            fixtures = workspace["terminal_fixtures"]
            state_after_stop = workspace["state_path"].read_bytes()
            ledger_after_stop = workspace["ledger_path"].read_bytes()

            record_replay = self.command(
                "record",
                workspace,
                payload=self.failure_event(workspace, event_id="failure-terminal-one"),
            )
            close_replay = self.command(
                "close-cycle",
                workspace,
                payload=fixtures["close_payloads"]["one"],
            )
            promote_replay = self.command(
                "promote",
                workspace,
                payload=fixtures["promotion_payload"],
            )

            self.assertEqual(0, record_replay.returncode, record_replay.stdout + record_replay.stderr)
            self.assertEqual(0, close_replay.returncode, close_replay.stdout + close_replay.stderr)
            self.assertEqual(0, promote_replay.returncode, promote_replay.stdout + promote_replay.stderr)
            self.assertEqual(fixtures["promotion_result"], self.parsed(promote_replay))
            self.assertEqual(state_after_stop, workspace["state_path"].read_bytes())
            self.assertEqual(ledger_after_stop, workspace["ledger_path"].read_bytes())
            self.assertEqual("stopped", self.status(workspace)["phase"])

    def test_terminal_stop_rejects_new_record_close_and_promotion_mutations(self) -> None:
        for mutation in ("record", "close-cycle", "promote"):
            with self.subTest(mutation=mutation):
                with tempfile.TemporaryDirectory() as temp_dir:
                    workspace = self.stopped_workspace(Path(temp_dir))
                    fixtures = workspace["terminal_fixtures"]
                    state_after_stop = workspace["state_path"].read_bytes()
                    ledger_after_stop = workspace["ledger_path"].read_bytes()

                    if mutation == "record":
                        payload = self.failure_event(
                            workspace,
                            event_id="failure-after-terminal-stop",
                        )
                    elif mutation == "close-cycle":
                        payload = self.cycle_payload(
                            workspace,
                            cycle_id="cycle-terminal-three",
                            failure_event_id="failure-terminal-three",
                        )
                    else:
                        payload = self.promotion_payload(
                            event_id="promotion-terminal-two",
                            cycle_id="cycle-terminal-two",
                        )

                    result = self.command(mutation, workspace, payload=payload)

                    self.assertEqual(5, result.returncode)
                    error = self.parsed(result)["error"]
                    self.assertEqual("EVOLUTION_STOPPED", error["code"])
                    self.assertEqual("iteration_budget_exhausted", error["stop_reason"])
                    self.assertEqual(state_after_stop, workspace["state_path"].read_bytes())
                    self.assertEqual(ledger_after_stop, workspace["ledger_path"].read_bytes())
                    self.assertEqual("stopped", self.status(workspace)["phase"])

    def test_new_failure_produces_an_explicit_manifest_proposal_not_a_false_auto_update(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = self.make_workspace(Path(temp_dir))
            self.init(workspace)
            candidate_case = {
                "case_id": "NEW-FAILURE-001",
                "input_sha256": sha256_text("new failure input"),
                "contract_sha256": sha256_text("new failure expectation"),
            }
            failure = {
                "event_id": "new-failure-observed",
                "event_type": "failure_observed",
                "actor": {"id": "author-A", "role": "author"},
                "case_id": "NEW-FAILURE-001",
                "partition": "candidate_failure",
                "failure_codes": ["new_bypass"],
                "regression_candidate": candidate_case,
                "receipt": self.receipt(
                    workspace,
                    receipt_id="new-failure-receipt",
                    case_id="NEW-FAILURE-001",
                    partition="candidate_failure",
                    variant="base",
                    outcome="fail",
                    actor_id="author-A",
                    candidate_sha256=sha256_text("base:new-failure"),
                    failure_codes=["new_bypass"],
                    raw_input_sha256=candidate_case["input_sha256"],
                ),
            }
            recorded = self.command("record", workspace, payload=failure)
            self.assertEqual(0, recorded.returncode, recorded.stdout + recorded.stderr)
            workspace["observed_failure_receipts"][failure["event_id"]] = copy.deepcopy(
                failure["receipt"]
            )
            closed = self.close_cycle(
                workspace,
                cycle_id="cycle-new-failure",
                failure_event_id="new-failure-observed",
                case_id="NEW-FAILURE-001",
                partition="candidate_failure",
                raw_input_sha256=candidate_case["input_sha256"],
            )
            self.assertEqual("ready_for_promotion", closed["phase"])
            before_manifest = workspace["manifest_path"].read_bytes()
            promoted = self.promote(
                workspace,
                event_id="promote-new-failure",
                cycle_id="cycle-new-failure",
            )
            self.assertEqual(0, promoted.returncode, promoted.stdout + promoted.stderr)
            result = self.parsed(promoted)
            self.assertEqual("manifest_update_required", result["cycle"]["status"])
            self.assertEqual("add_regression_case", result["manifest_proposal"]["operation"])
            self.assertEqual(candidate_case, result["manifest_proposal"]["value"])
            self.assertEqual(before_manifest, workspace["manifest_path"].read_bytes())


if __name__ == "__main__":
    unittest.main()
