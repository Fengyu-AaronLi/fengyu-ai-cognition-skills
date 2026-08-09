from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from test_claim_audit import base_claim, load_runtime


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def initialize_workspace(runtime, root: Path) -> Path:
    input_path = root / "answer.txt"
    input_path.write_text("test input", encoding="utf-8")
    workspace = root / "audit"
    result = runtime.cmd_init(
        argparse.Namespace(
            input=str(input_path),
            workspace=str(workspace),
            as_of="2026-08-06",
            audit_id="audit-pdf-test",
        )
    )
    if result != 0:
        raise AssertionError("workspace initialization failed")
    return workspace


def fetched_pdf() -> dict:
    return {
        "requested_url": "https://example.com/paper.pdf",
        "final_url": "https://example.com/paper.pdf",
        "resolved_ip": "93.184.216.34",
        "http_status": 200,
        "headers": [("Content-Type", "application/pdf")],
        "content_type": "application/pdf",
        "body": b"%PDF-1.7\nraw-pdf-bytes\n%%EOF\n",
        "redirect_chain": [],
    }


def fetch_args(workspace: Path) -> argparse.Namespace:
    return argparse.Namespace(
        workspace=str(workspace),
        source_id="PDF1",
        url="https://example.com/paper.pdf",
        tier="A1",
        role="original_record",
        published="2026-08-01",
        origin_id="doi:10.0000/example",
        freshness="current",
        freshness_rationale="Opened during this audit.",
        max_bytes=5 * 1024 * 1024,
        timeout=20.0,
        max_redirects=5,
    )


class RestrictedPdfParserTests(unittest.TestCase):
    def test_adapter_discovers_local_pdftotext_and_records_exact_version(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "pdftotext"
            executable.write_bytes(b"local executable placeholder")
            executable.chmod(0o700)
            calls: list[tuple[list[str], dict]] = []

            def fake_runner(command, **kwargs):
                calls.append((list(command), dict(kwargs)))
                if command[1:] == ["-v"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=b"",
                        stderr=b"pdftotext version 24.02.0\n",
                    )
                Path(command[-1]).write_text(
                    "The study reports an association.\n",
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess(
                    command,
                    0,
                    stdout=b"",
                    stderr=b"",
                )

            result = runtime.parse_pdf_text(
                b"%PDF-1.7\nfixture\n%%EOF\n",
                executable_finder=lambda name: str(executable),
                runner=fake_runner,
            )

        self.assertEqual(result["text"], "The study reports an association.\n")
        self.assertEqual(result["parser_name"], "pdftotext")
        self.assertEqual(result["parser_version"], "24.02.0")
        self.assertIsNone(result["error"])
        self.assertEqual(calls[0][0], [str(executable.resolve()), "-v"])
        self.assertEqual(
            calls[1][0][1:5],
            ["-enc", "UTF-8", "-nopgbrk", calls[1][0][4]],
        )
        self.assertEqual(calls[1][0][-1].endswith(".txt"), True)
        self.assertIs(calls[0][1]["shell"], False)
        self.assertIs(calls[1][1]["shell"], False)
        self.assertLessEqual(calls[1][1]["timeout"], 30.0)

    def test_missing_pdftotext_fails_closed_without_fallback(self):
        runtime = load_runtime()
        result = runtime.parse_pdf_text(
            b"%PDF-1.7\nfixture\n%%EOF\n",
            executable_finder=lambda name: None,
            runner=lambda *args, **kwargs: self.fail("runner must not be called"),
        )

        self.assertIsNone(result["text"])
        self.assertEqual(result["parser_name"], "pdftotext")
        self.assertEqual(result["parser_version"], "unavailable")
        self.assertIn("not available", result["error"])

    def test_pdftotext_failure_fails_closed_and_does_not_keep_partial_text(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            executable = Path(tmp) / "pdftotext"
            executable.write_bytes(b"local executable placeholder")
            executable.chmod(0o700)

            def fake_runner(command, **kwargs):
                if command[1:] == ["-v"]:
                    return subprocess.CompletedProcess(
                        command,
                        0,
                        stdout=b"",
                        stderr=b"pdftotext version 24.02.0\n",
                    )
                Path(command[-1]).write_text("partial", encoding="utf-8")
                return subprocess.CompletedProcess(
                    command,
                    1,
                    stdout=b"",
                    stderr=b"Syntax Error: malformed PDF",
                )

            result = runtime.parse_pdf_text(
                b"%PDF-1.7\nmalformed\n",
                executable_finder=lambda name: str(executable),
                runner=fake_runner,
            )

        self.assertIsNone(result["text"])
        self.assertEqual(result["parser_version"], "24.02.0")
        self.assertIn("malformed PDF", result["error"])


class PdfReceiptIntegrationTests(unittest.TestCase):
    def test_runtime_fetch_preserves_pdf_and_parsed_text_with_two_hashes(self):
        runtime = load_runtime()
        parsed_text = "The study reports an association.\n"
        with tempfile.TemporaryDirectory() as tmp:
            workspace = initialize_workspace(runtime, Path(tmp))
            with mock.patch.object(
                runtime,
                "fetch_public_url",
                return_value=fetched_pdf(),
            ), mock.patch.object(
                runtime,
                "parse_pdf_text",
                return_value={
                    "text": parsed_text,
                    "parser_name": "pdftotext",
                    "parser_version": "24.02.0",
                    "error": None,
                },
            ):
                result = runtime.cmd_fetch(fetch_args(workspace))

            self.assertEqual(result, 0)
            receipt = json.loads(
                (workspace / "receipts" / "PDF1.json").read_text(encoding="utf-8")
            )
            raw = (workspace / receipt["artifact"]).read_bytes()
            parsed = (workspace / receipt["parsed_text"]).read_bytes()

        self.assertEqual(raw, fetched_pdf()["body"])
        self.assertEqual(parsed, parsed_text.encode("utf-8"))
        self.assertEqual(receipt["content_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(
            receipt["parsed_text_sha256"], hashlib.sha256(parsed).hexdigest()
        )
        self.assertTrue(receipt["support_eligible"])
        self.assertEqual(receipt["parser_name"], "pdftotext")
        self.assertEqual(receipt["parser_version"], "24.02.0")

    def test_missing_pdf_parser_preserves_raw_pdf_but_blocks_evidence_binding(self):
        runtime = load_runtime()
        with tempfile.TemporaryDirectory() as tmp:
            workspace = initialize_workspace(runtime, Path(tmp))
            runtime._record_claim(workspace, base_claim())
            with mock.patch.object(
                runtime,
                "fetch_public_url",
                return_value=fetched_pdf(),
            ), mock.patch.object(
                runtime,
                "parse_pdf_text",
                return_value={
                    "text": None,
                    "parser_name": "pdftotext",
                    "parser_version": "unavailable",
                    "error": "pdftotext is not available",
                },
            ):
                result = runtime.cmd_fetch(fetch_args(workspace))

            receipt = json.loads(
                (workspace / "receipts" / "PDF1.json").read_text(encoding="utf-8")
            )
            ledger_before = (workspace / "ledger.json").read_bytes()
            with self.assertRaisesRegex(runtime.AuditError, "not eligible"):
                runtime._record_evidence(
                    workspace,
                    {
                        "claim_id": "C1",
                        "source_id": "PDF1",
                        "support": "context",
                        "evidence_purpose": "substantive",
                        "support_scope": "the claimed result",
                        "locator": "",
                        "excerpt": "",
                        "inference_span": 0,
                    },
                )
            ledger_after = (workspace / "ledger.json").read_bytes()
            raw = (workspace / receipt["artifact"]).read_bytes()

            tampered_ledger = json.loads(ledger_after.decode("utf-8"))
            tampered_ledger["claims"][0]["evidence"].append(
                {
                    "source_id": "PDF1",
                    "support": "context",
                    "evidence_purpose": "substantive",
                    "support_scope": "manually inserted PDF context",
                    "locator": "",
                    "excerpt": "",
                    "inference_span": 0,
                }
            )
            write_json(workspace / "ledger.json", tampered_ledger)
            tampered_gate = runtime.validate_workspace(workspace)

        self.assertEqual(result, 1)
        self.assertFalse(receipt["support_eligible"])
        self.assertEqual(receipt["parser_name"], "pdftotext")
        self.assertEqual(receipt["parser_version"], "unavailable")
        self.assertIsNone(receipt["parsed_text"])
        self.assertIn("pdftotext is not available", receipt["ineligibility_reason"])
        self.assertEqual(receipt["content_sha256"], hashlib.sha256(raw).hexdigest())
        self.assertEqual(ledger_before, ledger_after)
        self.assertIn(
            "PDF_TEXT_UNAVAILABLE",
            {item["code"] for item in tampered_gate["errors"]},
        )


if __name__ == "__main__":
    unittest.main()
