from __future__ import annotations

import copy
import hashlib
import io
import json
import socket
import subprocess
import sys
import tempfile
import unittest
import zlib
from pathlib import Path
from unittest import mock

from test_claim_audit import BASE_INPUT, RUNTIME_PATH, attach_source_and_evidence, base_claim, base_ledger, load_runtime, refresh_countercheck


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def make_complete_workspace(
    runtime, root: Path, *, attest: bool = True
) -> tuple[Path, dict, dict]:
    workspace = root / "audit-run"
    (workspace / "receipts").mkdir(parents=True)
    (workspace / "artifacts").mkdir()
    (workspace / "input.txt").write_text(BASE_INPUT, encoding="utf-8")

    ledger = base_ledger()
    runtime.initialize_runtime_attestations(workspace, ledger["audit_id"])
    claim = base_claim()
    claim.update(status="confirmed", source_identity_gate="pass", content_support_gate="pass")
    receipts = attach_source_and_evidence(runtime, ledger, claim)
    ledger["claims"] = [claim]
    ledger["sources"][0]["freshness_status"] = "current"

    raw = b"<html><body>The named paper exists.</body></html>"
    parsed = b"The named paper exists."
    (workspace / "artifacts" / "S1.bin").write_bytes(raw)
    (workspace / "artifacts" / "S1.txt").write_bytes(parsed)

    receipt = receipts["S1"]
    receipt.update(
        runtime_version="3.1.0",
        artifact="artifacts/S1.bin",
        bytes_read=len(raw),
        content_sha256=hashlib.sha256(raw).hexdigest(),
        parsed_text="artifacts/S1.txt",
        parsed_text_sha256=hashlib.sha256(parsed).hexdigest(),
        retrieval_complete=True,
        support_eligible=True,
        acquisition_type="runtime_fetch",
    )
    receipt["receipt_sha256"] = runtime.compute_receipt_sha256(receipt)

    for evidence in claim["evidence"]:
        evidence["excerpt"] = parsed.decode("utf-8")
        evidence["selector"] = {
            "start": 0,
            "end": len(parsed.decode("utf-8")),
            "quote_sha256": hashlib.sha256(parsed).hexdigest(),
        }
    refresh_countercheck(claim, ["S1"])

    write_json(workspace / "ledger.json", ledger)
    write_json(workspace / "receipts" / "S1.json", receipt)
    if attest:
        runtime.attest_runtime_receipt(workspace, ledger["audit_id"], receipt)
    return workspace, ledger, receipts


class ArtifactAndReplayTests(unittest.TestCase):
    def test_html_extraction_keeps_visible_text_and_drops_script_content(self):
        runtime = load_runtime()
        payload = (
            b"<html><head><script>ignore hallucination</script></head>"
            b"<body><p>Models <strong>hallucinate</strong>.</p>"
            b"<style>.hidden{display:none}</style><p>Evidence &amp; scope.</p></body></html>"
        )
        text, parser_name = runtime.extract_text(payload, "text/html; charset=utf-8")
        self.assertEqual(text, "Models hallucinate. Evidence & scope.")
        self.assertEqual(parser_name, "html.parser")

    def test_pdf_without_a_text_parser_is_not_extractable_evidence(self):
        runtime = load_runtime()
        text, parser_name = runtime.extract_text(b"%PDF-1.7\nnot parsed", "application/pdf")
        self.assertIsNone(text)
        self.assertIsNone(parser_name)

    def test_complete_workspace_passes_artifact_and_quote_checks(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _, _ = make_complete_workspace(runtime, Path(tmp))
            gate = runtime.validate_workspace(workspace)
            self.assertEqual(gate["verdict"], "PASS", gate)

    def test_raw_artifact_tampering_is_detected(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _, _ = make_complete_workspace(runtime, Path(tmp))
            (workspace / "artifacts" / "S1.bin").write_bytes(b"changed")
            gate = runtime.validate_workspace(workspace)
            self.assertIn("ARTIFACT_HASH_MISMATCH", {error["code"] for error in gate["errors"]})

    def test_parsed_text_tampering_is_detected(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _, _ = make_complete_workspace(runtime, Path(tmp))
            (workspace / "artifacts" / "S1.txt").write_text("changed", encoding="utf-8")
            gate = runtime.validate_workspace(workspace)
            codes = {error["code"] for error in gate["errors"]}
            self.assertIn("PARSED_TEXT_HASH_MISMATCH", codes)

    def test_exact_quote_must_match_saved_text_selector(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace, ledger, _ = make_complete_workspace(runtime, Path(tmp))
            ledger["claims"][0]["evidence"][0]["excerpt"] = "A different sentence."
            write_json(workspace / "ledger.json", ledger)
            gate = runtime.validate_workspace(workspace)
            self.assertIn("QUOTE_MISMATCH", {error["code"] for error in gate["errors"]})

    def test_search_snippet_cannot_be_used_as_confirming_evidence(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(status="confirmed", source_identity_gate="pass", content_support_gate="pass")
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        receipts["S1"].update(acquisition_type="search_snippet", support_eligible=False)
        receipts["S1"]["receipt_sha256"] = runtime.compute_receipt_sha256(receipts["S1"])
        ledger["claims"] = [claim]
        gate = runtime.validate_bundle(ledger, receipts)
        self.assertIn("SEARCH_SNIPPET_NOT_EVIDENCE", {error["code"] for error in gate["errors"]})

    def test_high_temporal_confirmation_requires_freshness_assessment(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        claim.update(
            temporal_sensitivity="high",
            status="confirmed",
            source_identity_gate="pass",
            content_support_gate="pass",
        )
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        ledger["sources"][0]["freshness_status"] = "unknown"
        ledger["claims"] = [claim]
        gate = runtime.validate_bundle(ledger, receipts)
        self.assertIn("FRESHNESS_NOT_ESTABLISHED", {error["code"] for error in gate["errors"]})

    def test_unreviewed_claims_block_a_complete_audit(self):
        runtime = load_runtime()
        ledger = base_ledger()
        ledger["scope"]["unreviewed_claims"] = ["C9: decisive quantitative claim"]
        gate = runtime.validate_bundle(ledger, {})
        self.assertIn("UNREVIEWED_CLAIMS_BLOCK_COMPLETION", {error["code"] for error in gate["errors"]})

    def test_manifest_hash_is_canonical(self):
        runtime = load_runtime()
        first = {"b": 2, "a": {"y": 1, "x": 0}}
        second = {"a": {"x": 0, "y": 1}, "b": 2}
        self.assertEqual(runtime.compute_manifest_sha256(first), runtime.compute_manifest_sha256(second))

    def test_render_requires_a_current_gate_file(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace, _, _ = make_complete_workspace(runtime, Path(tmp))
            result = subprocess.run(
                [sys.executable, str(RUNTIME_PATH), "render", "--workspace", str(workspace)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("gate", result.stderr.lower())

    def test_ledger_mutation_invalidates_a_previous_gate(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace, ledger, _ = make_complete_workspace(runtime, Path(tmp))
            checked = subprocess.run(
                [sys.executable, str(RUNTIME_PATH), "check", "--workspace", str(workspace)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(checked.returncode, 0, checked.stderr)
            ledger["claims"][0]["text"] = "The named paper definitely exists."
            write_json(workspace / "ledger.json", ledger)
            rendered = subprocess.run(
                [sys.executable, str(RUNTIME_PATH), "render", "--workspace", str(workspace)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertNotEqual(rendered.returncode, 0)
            self.assertIn("stale", rendered.stderr.lower())


class NetworkBoundaryTests(unittest.TestCase):
    def test_redirect_target_is_resolved_once_and_receipt_records_the_pinned_ip(self):
        runtime = load_runtime()
        resolver_calls: dict[str, int] = {}

        def resolver(host, port, type=None):
            resolver_calls[host] = resolver_calls.get(host, 0) + 1
            addresses = {
                "first.example": ["93.184.216.34"],
                "second.example": ["1.1.1.1", "8.8.8.8"],
            }
            choices = addresses[host]
            address = choices[min(resolver_calls[host] - 1, len(choices) - 1)]
            return [
                (
                    socket.AF_INET,
                    socket.SOCK_STREAM,
                    6,
                    "",
                    (address, port),
                )
            ]

        class FakeResponse:
            def __init__(self, status, headers, body=b""):
                self.status = status
                self._headers = headers
                self._body = io.BytesIO(body)

            def getheaders(self):
                return list(self._headers)

            def read(self, size=-1):
                return self._body.read(size)

        class FakePinnedHTTPSConnection:
            instances = []

            def __init__(self, hostname, pinned_ip, port, timeout):
                self.hostname = hostname
                self.pinned_ip = pinned_ip
                self.port = port
                self.timeout = timeout
                self.__class__.instances.append(self)

            def request(self, method, path, headers):
                self.method = method
                self.path = path
                self.headers = headers

            def getresponse(self):
                if self.hostname == "first.example":
                    return FakeResponse(
                        302,
                        [("Location", "https://second.example/final")],
                    )
                return FakeResponse(
                    200,
                    [("Content-Type", "text/plain; charset=utf-8")],
                    b"opened primary source",
                )

            def close(self):
                return None

        with mock.patch.object(
            runtime,
            "_PinnedHTTPSConnection",
            FakePinnedHTTPSConnection,
        ):
            result = runtime.fetch_public_url(
                "https://first.example/start",
                resolver=resolver,
            )

        self.assertEqual(len(FakePinnedHTTPSConnection.instances), 2)
        first_connection, final_connection = FakePinnedHTTPSConnection.instances
        self.assertEqual(
            result["redirect_chain"][0]["from_resolved_ip"],
            first_connection.pinned_ip,
        )
        self.assertEqual(
            result["redirect_chain"][0]["to_resolved_ip"],
            final_connection.pinned_ip,
        )
        self.assertEqual(result["resolved_ip"], final_connection.pinned_ip)
        self.assertEqual(resolver_calls, {"first.example": 1, "second.example": 1})

    def test_runtime_receipt_requires_redirect_ip_continuity_and_final_match(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        ledger["claims"] = [claim]
        receipt = receipts["S1"]
        receipt.update(
            requested_url="https://example.com/start",
            final_url="https://example.com/final",
            resolved_ip="8.8.8.8",
            redirect_chain=[
                {
                    "from": "https://example.com/start",
                    "from_query_sha256": None,
                    "to": "https://example.com/middle",
                    "to_query_sha256": None,
                    "http_status": 302,
                    "from_resolved_ip": "93.184.216.34",
                    "to_resolved_ip": "1.1.1.1",
                },
                {
                    "from": "https://example.com/middle",
                    "from_query_sha256": None,
                    "to": "https://example.com/final",
                    "to_query_sha256": None,
                    "http_status": 302,
                    "from_resolved_ip": "9.9.9.9",
                    "to_resolved_ip": "8.8.4.4",
                },
            ],
        )
        receipt["receipt_sha256"] = runtime.compute_receipt_sha256(receipt)

        gate = runtime.validate_bundle(ledger, receipts)
        codes = {error["code"] for error in gate["errors"]}

        self.assertIn("RECEIPT_REDIRECT_IP_DISCONTINUOUS", codes)
        self.assertIn("RECEIPT_REDIRECT_FINAL_IP_MISMATCH", codes)

    def test_receipt_redirect_chain_rejects_an_intermediate_private_url(self):
        runtime = load_runtime()
        ledger = base_ledger()
        claim = base_claim()
        receipts = attach_source_and_evidence(runtime, ledger, claim)
        ledger["claims"] = [claim]
        receipt = receipts["S1"]
        receipt.update(
            requested_url="https://example.com/start",
            final_url="https://example.com/final",
            redirect_chain=[
                {
                    "from": "https://example.com/start",
                    "from_query_sha256": None,
                    "to": "http://127.0.0.1/internal",
                    "to_query_sha256": None,
                    "http_status": 302,
                },
                {
                    "from": "http://127.0.0.1/internal",
                    "from_query_sha256": None,
                    "to": "https://example.com/final",
                    "to_query_sha256": None,
                    "http_status": 302,
                },
            ],
        )
        receipt["receipt_sha256"] = runtime.compute_receipt_sha256(receipt)

        gate = runtime.validate_bundle(ledger, receipts)

        self.assertEqual(gate["verdict"], "FAIL", gate)
        self.assertIn(
            "RECEIPT_REDIRECT_URL_UNSAFE",
            {error["code"] for error in gate["errors"]},
        )

    def test_malformed_gzip_and_deflate_are_normalized_to_audit_errors(self):
        runtime = load_runtime()
        malformed_payloads = {
            "gzip": b"not-a-gzip-stream",
            "deflate": b"not-a-deflate-stream",
        }

        for encoding, payload in malformed_payloads.items():
            with self.subTest(encoding=encoding):
                try:
                    runtime._decompress_limited(payload, encoding, 1024)
                except Exception as exc:
                    self.assertIsInstance(exc, runtime.AuditError)
                else:
                    self.fail(f"malformed {encoding} data was accepted")

    def test_truncated_compressed_sources_are_rejected(self):
        runtime = load_runtime()
        compressor = zlib.compressobj(wbits=16 + zlib.MAX_WBITS)
        complete = compressor.compress(b"verified source body") + compressor.flush()

        with self.assertRaises(ValueError):
            runtime._decompress_limited(complete[:-4], "gzip", 1024)

    def test_concatenated_compressed_members_are_not_silently_dropped(self):
        runtime = load_runtime()

        def gzip_member(payload: bytes) -> bytes:
            compressor = zlib.compressobj(wbits=16 + zlib.MAX_WBITS)
            return compressor.compress(payload) + compressor.flush()

        concatenated = gzip_member(b"first source body") + gzip_member(b"hidden second body")
        with self.assertRaises(ValueError):
            runtime._decompress_limited(concatenated, "gzip", 1024)

    def test_ipv6_loopback_and_mapped_private_addresses_are_blocked(self):
        runtime = load_runtime()

        def resolver_for(address):
            def resolver(host, port, type=None):
                family = socket.AF_INET6 if ":" in address else socket.AF_INET
                target = (address, port, 0, 0) if family == socket.AF_INET6 else (address, port)
                return [(family, socket.SOCK_STREAM, 6, "", target)]

            return resolver

        for address in ("::1", "fe80::1", "::ffff:127.0.0.1"):
            with self.subTest(address=address), self.assertRaises(ValueError):
                runtime.assert_public_url("https://blocked.example/path", resolver=resolver_for(address))

    def test_credentials_and_unapproved_ports_are_blocked(self):
        runtime = load_runtime()
        with self.assertRaises(ValueError):
            runtime.assert_public_url("https://user:pass@example.com/")
        with self.assertRaises(ValueError):
            runtime.assert_public_url("https://example.com:8443/")


if __name__ == "__main__":
    unittest.main()
