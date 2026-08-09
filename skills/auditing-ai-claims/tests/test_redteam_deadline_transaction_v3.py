from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_claim_audit import RUNTIME_PATH, load_runtime, valid_receipt


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(RUNTIME_PATH), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def start_workspace(root: Path) -> Path:
    input_path = root / "answer.txt"
    input_text = "A named source exists."
    input_path.write_text(input_text, encoding="utf-8")
    workspace = root / "audit"
    result = run_cli(
        "start",
        "--input",
        str(input_path),
        "--workspace",
        str(workspace),
        "--reason",
        "named external claim",
        "--candidate",
        input_text,
    )
    if result.returncode != 0:
        raise AssertionError(result.stderr)
    return workspace


class _SlowDripResponse:
    status = 200

    def __init__(self, chunks: int = 6, delay: float = 0.02):
        self.remaining = chunks
        self.delay = delay

    def getheaders(self):
        return [("Content-Type", "text/plain"), ("Content-Encoding", "identity")]

    def read(self, _size: int = -1) -> bytes:
        if self.remaining <= 0:
            return b""
        time.sleep(self.delay)
        self.remaining -= 1
        return b"x"


class _SlowDripConnection:
    def __init__(self, _hostname, _ip, _port, timeout):
        self.timeout = timeout
        self.response = _SlowDripResponse()

    def request(self, *_args, **_kwargs):
        return None

    def getresponse(self):
        return self.response

    def close(self):
        return None


class DeadlineSizeAndSourceTransactionRedTests(unittest.TestCase):
    def test_fetch_timeout_is_a_total_deadline_not_a_per_read_idle_timeout(self):
        """Bytes arriving just under the idle timeout must not extend fetch forever."""

        runtime = load_runtime()
        original_connection = runtime._PinnedHTTPConnection
        runtime._PinnedHTTPConnection = _SlowDripConnection
        resolver = lambda *_args, **_kwargs: [
            (runtime.socket.AF_INET, runtime.socket.SOCK_STREAM, 6, "", ("93.184.216.34", 80))
        ]
        try:
            started = time.monotonic()
            with self.assertRaises(
                runtime.AuditError,
                msg=(
                    "fetch_public_url accepted a slow-drip body whose individual reads "
                    "arrived before the socket timeout but whose total duration exceeded it"
                ),
            ):
                runtime.fetch_public_url(
                    "http://example.com/source",
                    timeout=0.03,
                    max_bytes=128,
                    resolver=resolver,
                )
            elapsed = time.monotonic() - started
            self.assertLess(
                elapsed,
                0.10,
                "the total deadline was noticed only after most of the slow-drip body arrived",
            )
        finally:
            runtime._PinnedHTTPConnection = original_connection

    def test_cli_cannot_raise_the_frozen_response_byte_ceiling(self):
        """The CLI flag may lower a limit, but must not raise the runtime ceiling."""

        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_workspace(root)
            source = root / "source.html"
            source.write_text("<p>tiny local capture</p>", encoding="utf-8")

            result = run_cli(
                "capture",
                "--workspace",
                str(workspace),
                "--source-id",
                "S1",
                "--file",
                str(source),
                "--requested-url",
                "https://example.com/source",
                "--final-url",
                "https://example.com/source",
                "--http-status",
                "200",
                "--content-type",
                "text/html; charset=utf-8",
                "--tier",
                "A1",
                "--role",
                "original_record",
                "--published",
                "2026-08-06",
                "--origin-id",
                "example:source",
                "--acquisition-type",
                "browser_export",
                "--max-bytes",
                str(runtime.DEFAULT_MAX_BYTES * 100),
            )

            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(
                ledger["sources"],
                [],
                "an over-ceiling CLI value was accepted and source registration began",
            )
            self.assertFalse(
                (workspace / "receipts" / "S1.json").exists(),
                "an over-ceiling CLI value produced a receipt instead of being rejected",
            )
            self.assertFalse(
                (workspace / "artifacts" / "S1.bin").exists(),
                "an over-ceiling CLI value produced an artifact instead of being rejected",
            )

    def test_receipt_then_ledger_crash_can_retry_the_same_source_id(self):
        """A crash in the commit gap must not leave a permanently orphaned source ID."""

        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_workspace(root)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            receipt = valid_receipt(runtime, source_id="S1", origin="example:source")

            original_write_json = runtime._write_json

            def crash_before_ledger_commit(path: Path, value):
                if Path(path).name == "ledger.json":
                    raise RuntimeError("simulated crash after receipt write")
                return original_write_json(path, value)

            runtime._write_json = crash_before_ledger_commit
            try:
                with self.assertRaisesRegex(RuntimeError, "simulated crash"):
                    runtime._register_source(
                        workspace,
                        ledger,
                        receipt,
                        tier="A1",
                        role="original_record",
                        published="2026-08-06",
                        origin_id="example:source",
                        freshness_status="current",
                        freshness_rationale="same-day publisher record",
                    )
            finally:
                runtime._write_json = original_write_json

            self.assertTrue(
                (workspace / "receipts" / "S1.json").is_file(),
                "the fixture did not reach the intended receipt-written commit gap",
            )
            crashed_ledger = json.loads(
                (workspace / "ledger.json").read_text(encoding="utf-8")
            )
            self.assertEqual(crashed_ledger["sources"], [])

            retry_ledger = json.loads(
                (workspace / "ledger.json").read_text(encoding="utf-8")
            )
            runtime._register_source(
                workspace,
                retry_ledger,
                receipt,
                tier="A1",
                role="original_record",
                published="2026-08-06",
                origin_id="example:source",
                freshness_status="current",
                freshness_rationale="same-day publisher record",
            )

            recovered = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            registered = [
                source
                for source in recovered["sources"]
                if source.get("source_id") == "S1"
            ]
            self.assertEqual(
                len(registered),
                1,
                "retry did not atomically reconcile the orphan receipt into one ledger source",
            )

    def test_capture_artifact_gap_is_journaled_blocked_and_resumable(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_workspace(root)
            source = root / "source.txt"
            source.write_text("A named source exists.", encoding="utf-8")
            args = runtime.build_parser().parse_args(
                [
                    "capture",
                    "--workspace",
                    str(workspace),
                    "--source-id",
                    "S1",
                    "--file",
                    str(source),
                    "--requested-url",
                    "https://example.com/source",
                    "--final-url",
                    "https://example.com/source",
                    "--http-status",
                    "200",
                    "--content-type",
                    "text/plain",
                    "--tier",
                    "A1",
                    "--role",
                    "original_record",
                    "--published",
                    "2026-08-06",
                    "--origin-id",
                    "example:source",
                    "--acquisition-type",
                    "browser_export",
                ]
            )
            original_register = runtime._register_source

            def crash_after_artifacts(*_args, **_kwargs):
                raise RuntimeError("simulated crash after immutable artifacts")

            runtime._register_source = crash_after_artifacts
            try:
                with self.assertRaisesRegex(RuntimeError, "immutable artifacts"):
                    runtime.cmd_capture(args)
            finally:
                runtime._register_source = original_register

            gate = runtime.validate_workspace(workspace)
            self.assertIn(
                "SOURCE_TRANSACTION_INCOMPLETE",
                {error["code"] for error in gate["errors"]},
            )

            resumed = runtime.cmd_capture(args)
            self.assertEqual(resumed, 1, "external capture remains support-ineligible")
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertEqual(
                [source["source_id"] for source in ledger["sources"]], ["S1"]
            )
            transaction = json.loads(
                (workspace / "source-transactions" / "S1.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(transaction["status"], "committed")

    def test_ledger_commit_gap_is_resumable_without_duplicate_source(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            workspace = start_workspace(root)
            ledger = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            receipt = valid_receipt(runtime, source_id="S1", origin="example:source")
            original_advance = runtime._advance_source_transaction

            def crash_before_committed(path, transaction, status):
                if status == "committed":
                    raise RuntimeError("simulated crash after ledger commit")
                return original_advance(path, transaction, status)

            runtime._advance_source_transaction = crash_before_committed
            try:
                with self.assertRaisesRegex(RuntimeError, "after ledger commit"):
                    runtime._register_source(
                        workspace,
                        ledger,
                        receipt,
                        tier="A1",
                        role="original_record",
                        published="2026-08-06",
                        origin_id="example:source",
                        freshness_status="current",
                        freshness_rationale="same-day publisher record",
                    )
            finally:
                runtime._advance_source_transaction = original_advance

            reloaded = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            runtime._register_source(
                workspace,
                reloaded,
                receipt,
                tier="A1",
                role="original_record",
                published="2026-08-06",
                origin_id="example:source",
                freshness_status="current",
                freshness_rationale="same-day publisher record",
            )
            final = json.loads((workspace / "ledger.json").read_text(encoding="utf-8"))
            self.assertEqual(
                len([item for item in final["sources"] if item["source_id"] == "S1"]),
                1,
            )


if __name__ == "__main__":
    unittest.main()
