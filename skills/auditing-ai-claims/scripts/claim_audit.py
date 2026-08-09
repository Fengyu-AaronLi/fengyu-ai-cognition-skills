#!/usr/bin/env python3
"""Executable evidence ledger for auditing externally verifiable AI claims.

The language model proposes claims and semantic support. This runtime owns
retrieval receipts, integrity checks, policy gates, and deterministic rendering.
It intentionally uses only the Python standard library.
"""

from __future__ import annotations

import argparse
import contextlib
import copy
import datetime as dt
import fcntl
import hashlib
import hmac
import http.client
import ipaddress
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import uuid
import zlib
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, BinaryIO, Callable, Iterable
from urllib.parse import urljoin, urlsplit, urlunsplit


RUNTIME_VERSION = "3.1.0"
POLICY_VERSION = "3.1.0"
RECEIPT_VERSION = "1.0"
ATTESTATION_VERSION = "1.0"
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_TIMEOUT = 20.0
MAX_TOTAL_TIMEOUT = 60.0
MAX_COUNTERCHECK_TEXT = 16 * 1024
MAX_COUNTERCHECK_SOURCES = 256
MAX_ABORT_REASON = 16 * 1024
MAX_REDIRECTS = 5
PDF_PARSE_TIMEOUT = 20.0
PDF_VERSION_TIMEOUT = 5.0
PDF_MAX_TEXT_BYTES = 5 * 1024 * 1024
ALLOWED_PORTS = {80, 443}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
SAFE_SOURCE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
CONFIRMING_STATUSES = {"confirmed", "partially_supported", "refuted"}
ALLOWED_STATUSES = {
    "confirmed",
    "partially_supported",
    "refuted",
    "unverifiable",
    "current_unknown",
}
ALLOWED_CLAIM_TYPES = {
    "existence_identity",
    "quantitative_comparison",
    "product_capability",
    "objective_performance",
    "research_finding",
    "causal",
    "law_policy",
    "quotation_attribution",
    "prediction_commitment",
}
ALLOWED_EVIDENCE_PURPOSES = {
    "substantive",
    "study_design",
    "source_identity",
    "currentness",
}
ALLOWED_COUNTERCHECK_RESULTS = {
    "no_conflict_found",
    "conflict_found",
    "scope_narrowed",
    "inconclusive",
}
ALLOWED_SOURCE_TRANSACTION_STATUSES = {
    "prepared",
    "artifacts_saved",
    "receipt_saved",
    "attested",
    "committed",
    "aborted",
}
ALLOWED_EXCLUSION_CLASSES = {
    "opinion",
    "metaphor",
    "creative_writing",
    "personal_feeling",
    "instruction",
    "relationship_motive",
    "other_nonfactual",
}
ALLOWED_TEMPORAL_SENSITIVITY = {"low", "medium", "high"}
ALLOWED_SOURCE_TIERS = {"A1", "A2", "B", "C"}
ALLOWED_EVIDENCE_ROLES = {
    "original_record",
    "subject_self_report",
    "independent_replication",
    "regulatory_record",
    "professional_analysis",
    "secondary_report",
    "lead_only",
}
ALLOWED_FRESHNESS = {"current", "stale", "unknown"}
ALLOWED_CAUSAL_BASIS_VALUES = {
    "not_applicable",
    "none",
    "correlational",
    "cross_sectional_self_report",
    "randomized_controlled_trial",
    "natural_experiment",
    "quasi_experimental",
    "longitudinal_with_identification",
    "systematic_review_of_causal_studies",
}
STATUS_LABELS = {
    "confirmed": "已确认",
    "partially_supported": "部分支持",
    "refuted": "被反驳",
    "unverifiable": "无法核验",
    "current_unknown": "当前未知",
}
ALLOWED_CAUSAL_BASES = {
    "randomized_controlled_trial",
    "natural_experiment",
    "quasi_experimental",
    "longitudinal_with_identification",
    "systematic_review_of_causal_studies",
}
HIGH_RISK_DOMAINS = {"medical", "legal", "financial"}
INDEPENDENT_ROLES = {
    "original_record",
    "independent_replication",
    "regulatory_record",
    "professional_analysis",
}
TEXT_MEDIA_TYPES = {
    "application/json",
    "application/ld+json",
    "application/xml",
    "application/xhtml+xml",
    "text/csv",
    "text/html",
    "text/markdown",
    "text/plain",
    "text/xml",
}
HTML_MEDIA_TYPES = {"text/html", "application/xhtml+xml"}
HTML_BLOCK_TAGS = {
    "address",
    "article",
    "aside",
    "blockquote",
    "br",
    "dd",
    "div",
    "dl",
    "dt",
    "figcaption",
    "figure",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "li",
    "main",
    "nav",
    "ol",
    "p",
    "pre",
    "section",
    "table",
    "td",
    "th",
    "tr",
    "ul",
}
HTML_IGNORED_TAGS = {"head", "noscript", "script", "style", "svg", "template"}


class AuditError(ValueError):
    """Expected input, policy, or integrity error."""


class _VisibleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized = tag.lower()
        if normalized in HTML_IGNORED_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth == 0 and normalized in HTML_BLOCK_TAGS:
            self._parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        if normalized in HTML_IGNORED_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth == 0 and normalized in HTML_BLOCK_TAGS:
            self._parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._ignored_depth == 0:
            self._parts.append(data)

    def text(self) -> str:
        return re.sub(r"\s+", " ", "".join(self._parts)).strip()


class _PinnedHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host: str, ip: str, port: int, timeout: float):
        super().__init__(host, port=port, timeout=timeout)
        self._pinned_ip = ip

    def connect(self) -> None:
        self.sock = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address
        )


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, ip: str, port: int, timeout: float):
        context = ssl.create_default_context()
        super().__init__(host, port=port, timeout=timeout, context=context)
        self._pinned_ip = ip

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self._pinned_ip, self.port), self.timeout, self.source_address
        )
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def today_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def parse_iso_date(value: Any) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def parse_iso_datetime(value: Any) -> dt.datetime | None:
    if not isinstance(value, str):
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = dt.datetime.fromisoformat(normalized)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def compute_receipt_sha256(receipt: dict[str, Any]) -> str:
    payload = {key: value for key, value in receipt.items() if key != "receipt_sha256"}
    return sha256_bytes(canonical_json(payload))


def compute_manifest_sha256(manifest: Any) -> str:
    """Return a key-order-independent digest for a JSON-compatible manifest."""
    return sha256_bytes(canonical_json(manifest))


def sanitize_url_for_receipt(url: str) -> tuple[str, str | None]:
    parsed = urlsplit(url)
    query_hash = sha256_bytes(parsed.query.encode("utf-8")) if parsed.query else None
    sanitized = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return sanitized, query_hash


def sanitize_redirect_chain(chain: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sanitized: list[dict[str, Any]] = []
    for item in chain:
        source, source_query_hash = sanitize_url_for_receipt(str(item.get("from", "")))
        target, target_query_hash = sanitize_url_for_receipt(str(item.get("to", "")))
        sanitized.append(
            {
                "from": source,
                "from_query_sha256": source_query_hash,
                "to": target,
                "to_query_sha256": target_query_hash,
                "http_status": item.get("http_status"),
                "from_resolved_ip": item.get("from_resolved_ip"),
                "to_resolved_ip": item.get("to_resolved_ip"),
            }
        )
    return sanitized


def safe_fetch_error_message(error: BaseException) -> str:
    """Return a stable diagnostic that cannot echo a signed URL or query secret."""
    message = str(error)
    safe_exact = {
        "only http and https sources are allowed",
        "URLs containing credentials are not allowed",
        "source URL has no hostname",
        "local hostnames are not allowed",
        "invalid source URL port",
    }
    if message in safe_exact:
        return message
    if re.fullmatch(r"(?:response|decoded response) exceeds \d+ bytes", message):
        return message
    cause = error.__cause__
    category = type(cause).__name__ if cause is not None else type(error).__name__
    return f"source fetch failed or was rejected before a usable body was saved ({category})"


def build_candidate_inventory(
    input_text: str, candidates: Iterable[str], *, origin: str = "declared"
) -> list[dict[str, Any]]:
    """Bind every declared candidate to exact character spans in the input."""

    inventory: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_candidate in enumerate(candidates, start=1):
        if not isinstance(raw_candidate, str) or not raw_candidate.strip():
            raise AuditError("candidate factual clauses must be non-empty strings")
        candidate = raw_candidate
        if candidate in seen:
            raise AuditError(f"duplicate candidate factual clause: {candidate}")
        seen.add(candidate)
        spans: list[dict[str, int]] = []
        cursor = 0
        while True:
            start = input_text.find(candidate, cursor)
            if start < 0:
                break
            spans.append({"start": start, "end": start + len(candidate)})
            cursor = start + max(1, len(candidate))
        if not spans:
            raise AuditError(
                "candidate factual clause is not an exact span of the original input: "
                + candidate
            )
        if len(spans) > 1:
            raise AuditError(
                "candidate factual clause is not unique in the original input; "
                "include enough surrounding context to identify one occurrence: "
                + candidate
            )
        inventory.append(
            {
                "candidate_id": f"U{index:03d}",
                "text": candidate,
                "origin": origin,
                "sha256": sha256_bytes(candidate.encode("utf-8")),
                "spans": spans,
            }
        )
    declared_ranges = sorted(
        (
            item["spans"][0]["start"],
            item["spans"][0]["end"],
            item["text"],
        )
        for item in inventory
    )
    for index, (start, end, text) in enumerate(declared_ranges):
        for other_start, other_end, other_text in declared_ranges[index + 1 :]:
            if other_start >= end:
                break
            if max(start, other_start) < min(end, other_end):
                raise AuditError(
                    "declared candidate spans overlap; declare the encompassing clause "
                    f"once and split it into atomic claims later: {text!r} / {other_text!r}"
                )
    if not inventory:
        raise AuditError("a triggered audit requires at least one candidate factual clause")
    return inventory


def discover_input_units(input_text: str) -> list[dict[str, Any]]:
    """Split the full input into exact review units without claiming they are facts."""

    raw_spans: list[tuple[int, int]] = []
    segment_start = 0
    length = len(input_text)
    for index, character in enumerate(input_text):
        boundary = character in "。！？!?；;\n"
        if character == ".":
            next_index = index + 1
            while next_index < length and input_text[next_index].isspace():
                next_index += 1
            previous = input_text[index - 1] if index > 0 else ""
            following = input_text[next_index] if next_index < length else ""
            decimal_point = previous.isdigit() and following.isdigit()
            boundary = not decimal_point and (
                next_index >= length
                or following.isupper()
                or "\u3400" <= following <= "\u9fff"
                or following in '"“‘([#-*'
            )
        if boundary:
            raw_spans.append((segment_start, index + 1))
            segment_start = index + 1
    if segment_start < length:
        raw_spans.append((segment_start, length))

    units: list[dict[str, Any]] = []
    for start, end in raw_spans:
        while start < end and input_text[start].isspace():
            start += 1
        while end > start and input_text[end - 1].isspace():
            end -= 1
        if start >= end:
            continue
        text = input_text[start:end]
        units.append(
            {
                "text": text,
                "origin": "auto_gap",
                "sha256": sha256_bytes(text.encode("utf-8")),
                "spans": [{"start": start, "end": end}],
            }
        )
    return units


def build_complete_candidate_inventory(
    input_text: str, declared_candidates: Iterable[str]
) -> list[dict[str, Any]]:
    """Merge declared spans with every untouched character range in each review unit."""

    inventory = build_candidate_inventory(input_text, declared_candidates)
    declared_spans = [
        (span["start"], span["end"])
        for candidate in inventory
        for span in candidate["spans"]
    ]
    for unit in discover_input_units(input_text):
        unit_span = unit["spans"][0]
        uncovered = [(unit_span["start"], unit_span["end"])]
        for declared_start, declared_end in declared_spans:
            remaining: list[tuple[int, int]] = []
            for start, end in uncovered:
                if declared_end <= start or declared_start >= end:
                    remaining.append((start, end))
                    continue
                if start < declared_start:
                    remaining.append((start, min(end, declared_start)))
                if declared_end < end:
                    remaining.append((max(start, declared_end), end))
            uncovered = remaining

        for start, end in uncovered:
            while start < end and input_text[start].isspace():
                start += 1
            while end > start and input_text[end - 1].isspace():
                end -= 1
            if start >= end:
                continue
            text = input_text[start:end]
            if not text.strip(".,;:!?，。；：！？、()[]{}\"'“”‘’"):
                continue
            fragment_span = {"start": start, "end": end}
            existing = next(
                (candidate for candidate in inventory if candidate["text"] == text),
                None,
            )
            if existing is None:
                inventory.append(
                    {
                        "text": text,
                        "origin": "auto_gap",
                        "sha256": sha256_bytes(text.encode("utf-8")),
                        "spans": [fragment_span],
                    }
                )
            elif fragment_span not in existing["spans"]:
                raise AuditError(
                    "runtime-discovered candidate text repeats in multiple input locations; "
                    "declare a larger unique contextual clause for each occurrence: "
                    + text
                )
    for index, candidate in enumerate(inventory, start=1):
        candidate["candidate_id"] = f"U{index:03d}"
    return inventory


def _candidate_remainder_is_meaningful(value: str) -> bool:
    """Return whether uncovered candidate text still contains factual content.

    Whitespace, punctuation, and narrow connective words may sit between two
    atomic claim subspans. Everything else must remain visible to the gate.
    """

    normalized = value.casefold()
    normalized = re.sub(
        r"\b(?:and|or|but|also|then|while|whereas|which|that|who|as\s+well\s+as)\b",
        " ",
        normalized,
    )
    for connector in ("而且", "并且", "以及", "同时", "但是", "然而", "和", "与", "及", "且", "并", "而", "但"):
        normalized = normalized.replace(connector, " ")
    return re.search(r"[a-z0-9\u3400-\u9fff]", normalized) is not None


def safe_workspace_path(workspace: Path | str, relative_path: str | Path) -> Path:
    root = Path(workspace).resolve()
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise AuditError("workspace artifact path must be relative")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise AuditError("workspace artifact path escapes the audit directory") from exc
    return resolved


@contextlib.contextmanager
def workspace_lock(workspace: Path | str, *, exclusive: bool):
    """Serialize workspace reads and writes across cooperating processes."""

    root = Path(workspace).resolve()
    if not root.is_dir():
        raise AuditError(f"audit workspace does not exist: {root}")
    lock_path = safe_workspace_path(root, ".runtime.lock")
    descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        fcntl.flock(descriptor, operation)
        yield
    finally:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        finally:
            os.close(descriptor)


def validate_source_id(source_id: Any) -> str:
    if not isinstance(source_id, str) or SAFE_SOURCE_ID.fullmatch(source_id) is None:
        raise AuditError(
            "source_id must be 1-64 safe filename characters and start with a letter or digit"
        )
    return source_id


def safe_report_output_path(workspace: Path | str, relative_path: str | Path) -> Path:
    root = Path(workspace).resolve()
    resolved = safe_workspace_path(root, relative_path)
    relative = resolved.relative_to(root)
    reserved_files = {
        ".gitignore",
        ".runtime-key",
        ".runtime-init.json",
        "input.txt",
        "ledger.json",
        "gate.json",
        "state.json",
        "events.jsonl",
        "runtime-attestations.json",
    }
    if str(relative) in reserved_files:
        raise AuditError("report output cannot overwrite a reserved workspace file")
    if relative.parts and relative.parts[0] in {
        "receipts",
        "artifacts",
        "source-transactions",
    }:
        raise AuditError("report output cannot be written inside evidence directories")
    if resolved.suffix.lower() != ".md":
        raise AuditError("report output must be a Markdown file")
    return resolved


def _normalized_ip(raw: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address:
    address = ipaddress.ip_address(raw.split("%", 1)[0])
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def assert_http_url_syntax(url: str) -> dict[str, Any]:
    parsed = urlsplit(url)
    if parsed.scheme not in {"http", "https"}:
        raise AuditError("only http and https sources are allowed")
    if parsed.username is not None or parsed.password is not None:
        raise AuditError("URLs containing credentials are not allowed")
    if not parsed.hostname:
        raise AuditError("source URL has no hostname")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise AuditError("local hostnames are not allowed")

    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError as exc:
        raise AuditError("invalid source URL port") from exc
    if port not in ALLOWED_PORTS:
        raise AuditError("only ports 80 and 443 are allowed")

    try:
        literal_address = _normalized_ip(hostname)
    except ValueError:
        literal_address = None
    if literal_address is not None and not literal_address.is_global:
        raise AuditError(f"source URL contains a non-public address: {literal_address}")

    return {
        "scheme": parsed.scheme,
        "hostname": hostname,
        "port": port,
        "path": urlunsplit(("", "", parsed.path or "/", parsed.query, "")),
    }


def assert_public_url(
    url: str,
    resolver: Callable[..., Iterable[Any]] = socket.getaddrinfo,
) -> dict[str, Any]:
    target = assert_http_url_syntax(url)
    hostname = target["hostname"]
    port = target["port"]

    try:
        records = list(resolver(hostname, port, type=socket.SOCK_STREAM))
    except (OSError, socket.gaierror) as exc:
        raise AuditError(f"source hostname did not resolve: {hostname}") from exc
    if not records:
        raise AuditError(f"source hostname did not resolve: {hostname}")

    addresses: list[str] = []
    for record in records:
        try:
            raw_ip = record[4][0]
            address = _normalized_ip(raw_ip)
        except (IndexError, TypeError, ValueError) as exc:
            raise AuditError("resolver returned an invalid address") from exc
        if not address.is_global:
            raise AuditError(f"source resolves to a non-public address: {address}")
        rendered = str(address)
        if rendered not in addresses:
            addresses.append(rendered)

    target["addresses"] = addresses
    return target


def _validate_fetch_limits(max_bytes: int, timeout: float | None = None) -> None:
    if not isinstance(max_bytes, int) or max_bytes <= 0:
        raise AuditError("max_bytes must be a positive integer")
    if max_bytes > DEFAULT_MAX_BYTES:
        raise AuditError(
            f"max_bytes cannot exceed the frozen runtime ceiling of {DEFAULT_MAX_BYTES} bytes"
        )
    if timeout is not None:
        if timeout <= 0:
            raise AuditError("timeout must be positive")
        if timeout > MAX_TOTAL_TIMEOUT:
            raise AuditError(
                f"timeout cannot exceed the frozen runtime ceiling of {MAX_TOTAL_TIMEOUT:g} seconds"
            )


def _remaining_before_deadline(
    deadline: float, clock: Callable[[], float]
) -> float:
    remaining = deadline - clock()
    if remaining <= 0:
        raise AuditError("source fetch exceeded the total deadline")
    return remaining


def read_limited(
    stream: BinaryIO,
    max_bytes: int = DEFAULT_MAX_BYTES,
    *,
    deadline: float | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> bytes:
    if max_bytes <= 0:
        raise AuditError("max_bytes must be positive")
    chunks: list[bytes] = []
    total = 0
    while True:
        if deadline is not None:
            _remaining_before_deadline(deadline, clock)
        chunk = stream.read(min(64 * 1024, max_bytes - total + 1))
        if deadline is not None:
            _remaining_before_deadline(deadline, clock)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise AuditError(f"response exceeds {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _decompress_limited(payload: bytes, encoding: str, max_bytes: int) -> bytes:
    if encoding in {"", "identity"}:
        if len(payload) > max_bytes:
            raise AuditError(f"response exceeds {max_bytes} bytes")
        return payload
    if encoding == "gzip":
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
    elif encoding == "deflate":
        decoder = zlib.decompressobj()
    else:
        raise AuditError(f"unsupported content encoding: {encoding}")

    output = bytearray()
    try:
        for start in range(0, len(payload), 64 * 1024):
            remaining = max_bytes - len(output)
            if remaining < 0:
                raise AuditError(f"decoded response exceeds {max_bytes} bytes")
            output.extend(
                decoder.decompress(payload[start : start + 64 * 1024], remaining + 1)
            )
            if len(output) > max_bytes or decoder.unconsumed_tail:
                raise AuditError(f"decoded response exceeds {max_bytes} bytes")
        output.extend(decoder.flush(max_bytes - len(output) + 1))
    except zlib.error as exc:
        raise AuditError(f"invalid {encoding} response") from exc
    if len(output) > max_bytes:
        raise AuditError(f"decoded response exceeds {max_bytes} bytes")
    if not decoder.eof:
        raise AuditError(f"truncated or incomplete {encoding} response")
    if decoder.unused_data:
        raise AuditError(f"concatenated or trailing {encoding} data is not accepted")
    return bytes(output)


def _header_hash(headers: list[tuple[str, str]]) -> str:
    normalized = sorted((name.lower().strip(), value.strip()) for name, value in headers)
    return sha256_bytes(canonical_json(normalized))


def _parse_media_type(content_type: str) -> tuple[str, str | None]:
    parts = [part.strip() for part in content_type.split(";")]
    media_type = parts[0].lower() if parts and parts[0] else "application/octet-stream"
    charset = None
    for part in parts[1:]:
        if part.lower().startswith("charset="):
            charset = part.split("=", 1)[1].strip('"\' ')
    return media_type, charset


def _decode_text(payload: bytes, content_type: str) -> tuple[str | None, str | None]:
    media_type, charset = _parse_media_type(content_type)
    if not (media_type.startswith("text/") or media_type in TEXT_MEDIA_TYPES):
        return None, None
    attempted = charset or "utf-8"
    try:
        return payload.decode(attempted), attempted
    except (LookupError, UnicodeDecodeError):
        try:
            return payload.decode("utf-8", errors="replace"), "utf-8-replace"
        except UnicodeDecodeError:
            return None, None


def extract_text(payload: bytes, content_type: str) -> tuple[str | None, str | None]:
    """Extract stable visible text for evidence selectors without executing page code."""
    decoded, decoder = _decode_text(payload, content_type)
    if decoded is None:
        return None, None
    media_type, _ = _parse_media_type(content_type)
    if media_type in HTML_MEDIA_TYPES:
        parser = _VisibleHTMLParser()
        try:
            parser.feed(decoded)
            parser.close()
        except Exception as exc:
            raise AuditError(f"HTML parser failed: {exc}") from exc
        visible = parser.text()
        return (visible if visible else None), "html.parser"
    return decoded, decoder or "text.decoder"


def _pdf_parse_result(
    *,
    text: str | None,
    version: str,
    error: str | None,
) -> dict[str, str | None]:
    return {
        "text": text,
        "parser_name": "pdftotext",
        "parser_version": version,
        "error": error,
    }


def _subprocess_error_text(payload: bytes | str | None) -> str:
    if isinstance(payload, bytes):
        value = payload.decode("utf-8", errors="replace")
    elif isinstance(payload, str):
        value = payload
    else:
        value = ""
    return " ".join(value.split())[:240]


def _payload_looks_like_pdf(payload: bytes) -> bool:
    """Treat a PDF magic header in the first KiB as authoritative over MIME."""

    return b"%PDF-" in payload[:1024]


def parse_pdf_text(
    payload: bytes,
    *,
    executable_finder: Callable[[str], str | None] | None = None,
    runner: Callable[..., Any] | None = None,
    timeout: float = PDF_PARSE_TIMEOUT,
    max_output_bytes: int = PDF_MAX_TEXT_BYTES,
) -> dict[str, str | None]:
    """Extract PDF text with a bounded, local, version-recorded adapter.

    The adapter never downloads a parser or invokes a shell. It discovers one
    local ``pdftotext`` executable, resolves its absolute path, records the
    reported version, uses fixed arguments, and fails closed on every error.
    """

    if not _payload_looks_like_pdf(payload):
        return _pdf_parse_result(
            text=None,
            version="unavailable",
            error="payload does not begin with a PDF header",
        )
    if type(max_output_bytes) is not int or max_output_bytes <= 0:
        raise AuditError("PDF text byte limit must be a positive integer")
    if not isinstance(timeout, (int, float)) or timeout <= 0:
        raise AuditError("PDF parser timeout must be positive")

    find_executable = executable_finder or shutil.which
    run_process = runner or subprocess.run
    discovered = find_executable("pdftotext")
    if not discovered:
        return _pdf_parse_result(
            text=None,
            version="unavailable",
            error="pdftotext is not available on the local PATH",
        )
    try:
        executable = Path(discovered).expanduser().resolve(strict=True)
    except (OSError, RuntimeError):
        return _pdf_parse_result(
            text=None,
            version="unavailable",
            error="the discovered pdftotext path is unavailable",
        )
    if not executable.is_file() or not os.access(executable, os.X_OK):
        return _pdf_parse_result(
            text=None,
            version="unavailable",
            error="the discovered pdftotext path is not an executable file",
        )

    fixed_executable = str(executable)
    try:
        version_process = run_process(
            [fixed_executable, "-v"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=min(float(timeout), PDF_VERSION_TIMEOUT),
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return _pdf_parse_result(
            text=None,
            version="unavailable",
            error="pdftotext version check timed out",
        )
    except OSError as exc:
        return _pdf_parse_result(
            text=None,
            version="unavailable",
            error=f"pdftotext version check failed: {type(exc).__name__}",
        )
    if version_process.returncode != 0:
        detail = _subprocess_error_text(version_process.stderr)
        suffix = f": {detail}" if detail else ""
        return _pdf_parse_result(
            text=None,
            version="unavailable",
            error=f"pdftotext version check exited with status {version_process.returncode}{suffix}",
        )
    version_output = b"\n".join(
        value
        for value in (version_process.stdout, version_process.stderr)
        if isinstance(value, bytes)
    )
    version_match = re.search(
        rb"\bpdftotext version\s+([0-9][A-Za-z0-9._+~-]{0,63})\b",
        version_output,
        flags=re.IGNORECASE,
    )
    if version_match is None:
        return _pdf_parse_result(
            text=None,
            version="unavailable",
            error="pdftotext did not report a recognizable version",
        )
    parser_version = version_match.group(1).decode("ascii")

    try:
        with tempfile.TemporaryDirectory(prefix="claim-audit-pdf-") as temporary:
            temporary_root = Path(temporary)
            input_path = temporary_root / "input.pdf"
            output_path = temporary_root / "output.txt"
            input_path.write_bytes(payload)
            os.chmod(input_path, 0o600)
            process = run_process(
                [
                    fixed_executable,
                    "-enc",
                    "UTF-8",
                    "-nopgbrk",
                    str(input_path),
                    str(output_path),
                ],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=float(timeout),
                check=False,
                shell=False,
            )
            if process.returncode != 0:
                detail = _subprocess_error_text(process.stderr)
                suffix = f": {detail}" if detail else ""
                return _pdf_parse_result(
                    text=None,
                    version=parser_version,
                    error=f"pdftotext exited with status {process.returncode}{suffix}",
                )
            if not output_path.is_file():
                return _pdf_parse_result(
                    text=None,
                    version=parser_version,
                    error="pdftotext produced no text artifact",
                )
            if output_path.stat().st_size > max_output_bytes:
                return _pdf_parse_result(
                    text=None,
                    version=parser_version,
                    error=f"pdftotext output exceeded {max_output_bytes} bytes",
                )
            with output_path.open("rb") as handle:
                output = read_limited(handle, max_bytes=max_output_bytes)
    except subprocess.TimeoutExpired:
        return _pdf_parse_result(
            text=None,
            version=parser_version,
            error=f"pdftotext timed out after {float(timeout):g} seconds",
        )
    except (AuditError, OSError) as exc:
        return _pdf_parse_result(
            text=None,
            version=parser_version,
            error=f"pdftotext output could not be read: {type(exc).__name__}",
        )
    try:
        text = output.decode("utf-8")
    except UnicodeDecodeError:
        return _pdf_parse_result(
            text=None,
            version=parser_version,
            error="pdftotext output was not valid UTF-8",
        )
    if not text.strip():
        return _pdf_parse_result(
            text=None,
            version=parser_version,
            error="pdftotext produced no non-whitespace text",
        )
    return _pdf_parse_result(text=text, version=parser_version, error=None)


def extract_evidence_text(payload: bytes, content_type: str) -> dict[str, str | None]:
    """Extract text plus the exact parser identity used for a receipt."""

    media_type, _ = _parse_media_type(content_type)
    if media_type == "application/pdf" or _payload_looks_like_pdf(payload):
        return parse_pdf_text(payload)
    text, parser_name = extract_text(payload, content_type)
    return {
        "text": text,
        "parser_name": parser_name,
        "parser_version": RUNTIME_VERSION if parser_name else None,
        "error": None if text is not None else "unsupported media type or empty text",
    }


def fetch_public_url(
    url: str,
    *,
    max_bytes: int = DEFAULT_MAX_BYTES,
    timeout: float = DEFAULT_TIMEOUT,
    max_redirects: int = MAX_REDIRECTS,
    resolver: Callable[..., Iterable[Any]] = socket.getaddrinfo,
    clock: Callable[[], float] = time.monotonic,
) -> dict[str, Any]:
    """GET a public URL while pinning each validated DNS result per redirect hop."""
    _validate_fetch_limits(max_bytes, timeout)
    if not isinstance(max_redirects, int) or not 0 <= max_redirects <= MAX_REDIRECTS:
        raise AuditError(
            f"max_redirects must be between 0 and the frozen ceiling of {MAX_REDIRECTS}"
        )
    deadline = clock() + timeout
    requested_url = url
    current_url = url
    redirect_chain: list[dict[str, Any]] = []
    prepared_target: dict[str, Any] | None = None

    for hop in range(max_redirects + 1):
        _remaining_before_deadline(deadline, clock)
        target = prepared_target or assert_public_url(current_url, resolver=resolver)
        remaining = _remaining_before_deadline(deadline, clock)
        prepared_target = None
        ip = target["addresses"][0]
        connection_type = _PinnedHTTPSConnection if target["scheme"] == "https" else _PinnedHTTPConnection
        connection = connection_type(target["hostname"], ip, target["port"], remaining)
        host_header = target["hostname"]
        default_port = 443 if target["scheme"] == "https" else 80
        if target["port"] != default_port:
            host_header = f"{host_header}:{target['port']}"

        try:
            connection.request(
                "GET",
                target["path"],
                headers={
                    "Accept": "text/html,application/xhtml+xml,application/json,text/plain,application/pdf;q=0.9,*/*;q=0.1",
                    "Accept-Encoding": "gzip, deflate",
                    "Host": host_header,
                    "User-Agent": f"auditing-ai-claims/{RUNTIME_VERSION} evidence-fetcher",
                },
            )
            response = connection.getresponse()
            status = int(response.status)
            headers = [(name, value) for name, value in response.getheaders()]
            header_map = {name.lower(): value for name, value in headers}

            if status in REDIRECT_STATUSES:
                location = header_map.get("location")
                if not location:
                    raise AuditError(f"redirect {status} has no Location header")
                if hop >= max_redirects:
                    raise AuditError(f"redirect limit exceeded after {max_redirects} hops")
                next_url = urljoin(current_url, location)
                next_target = assert_public_url(next_url, resolver=resolver)
                _remaining_before_deadline(deadline, clock)
                redirect_chain.append(
                    {
                        "from": current_url,
                        "to": next_url,
                        "http_status": status,
                        "from_resolved_ip": ip,
                        "to_resolved_ip": next_target["addresses"][0],
                    }
                )
                current_url = next_url
                prepared_target = next_target
                continue

            compressed = read_limited(
                response,
                max_bytes=max_bytes,
                deadline=deadline,
                clock=clock,
            )
            body = _decompress_limited(
                compressed,
                header_map.get("content-encoding", "").lower(),
                max_bytes,
            )
            return {
                "requested_url": requested_url,
                "final_url": current_url,
                "resolved_ip": ip,
                "http_status": status,
                "headers": headers,
                "content_type": header_map.get("content-type", "application/octet-stream"),
                "body": body,
                "redirect_chain": redirect_chain,
            }
        except (OSError, ssl.SSLError, http.client.HTTPException) as exc:
            raise AuditError(f"source fetch failed: {exc}") from exc
        finally:
            connection.close()

    raise AuditError("redirect loop did not terminate")


def _error(errors: list[dict[str, str]], code: str, path: str, message: str) -> None:
    errors.append({"code": code, "path": path, "message": message})


def _warning(warnings: list[dict[str, str]], code: str, path: str, message: str) -> None:
    warnings.append({"code": code, "path": path, "message": message})


def _receipt_parser_is_frozen(receipt: dict[str, Any]) -> bool:
    parser_name = receipt.get("parser_name")
    parser_version = receipt.get("parser_version")
    if not isinstance(parser_name, str) or not parser_name:
        return False
    if not isinstance(parser_version, str) or not parser_version:
        return False
    if parser_name == "pdftotext":
        return re.fullmatch(r"[0-9][A-Za-z0-9._+~-]{0,63}", parser_version) is not None
    return parser_version == RUNTIME_VERSION


def _pdf_text_binding_unavailable(receipt: dict[str, Any]) -> bool:
    media_type, _ = _parse_media_type(str(receipt.get("content_type") or ""))
    is_pdf = media_type == "application/pdf" or receipt.get("parser_name") == "pdftotext"
    return is_pdf and (
        bool(receipt.get("parser_error"))
        or not isinstance(receipt.get("parsed_text"), str)
        or not receipt.get("parsed_text")
        or receipt.get("parser_version") == "unavailable"
    )


def _receipt_is_usable(receipt: dict[str, Any]) -> bool:
    status = receipt.get("http_status")
    bytes_read = receipt.get("bytes_read")
    return (
        receipt.get("receipt_version") == RECEIPT_VERSION
        and receipt.get("runtime_version") == RUNTIME_VERSION
        and isinstance(status, int)
        and 200 <= status < 300
        and type(bytes_read) is int
        and bytes_read > 0
        and isinstance(receipt.get("content_sha256"), str)
        and bool(re.fullmatch(r"[a-f0-9]{64}", receipt["content_sha256"]))
        and isinstance(receipt.get("headers_sha256"), str)
        and bool(re.fullmatch(r"[a-f0-9]{64}", receipt["headers_sha256"]))
        and receipt.get("retrieval_complete") is True
        and receipt.get("support_eligible") is True
        and receipt.get("acquisition_type") == "runtime_fetch"
        and receipt.get("transport_attestation") == "dns_pinned_runtime"
        and isinstance(receipt.get("artifact"), str)
        and bool(receipt["artifact"])
        and isinstance(receipt.get("parsed_text"), str)
        and bool(receipt["parsed_text"])
        and isinstance(receipt.get("parsed_text_sha256"), str)
        and bool(re.fullmatch(r"[a-f0-9]{64}", receipt["parsed_text_sha256"]))
        and isinstance(receipt.get("parser_name"), str)
        and bool(receipt["parser_name"])
        and _receipt_parser_is_frozen(receipt)
    )


def _validate_receipt_contract(
    receipt: dict[str, Any],
    source_id: str,
    errors: list[dict[str, str]],
    *,
    allow_rejected_target: bool = False,
) -> None:
    path = f"receipts.{source_id}"
    try:
        validate_source_id(source_id)
    except AuditError:
        _error(
            errors,
            "RECEIPT_SOURCE_ID_UNSAFE",
            f"{path}.source_id",
            "source_id is not safe for use as a receipt filename",
        )
    if receipt.get("receipt_version") != RECEIPT_VERSION:
        _error(errors, "RECEIPT_VERSION_MISMATCH", f"{path}.receipt_version", "receipt version is not supported")
    if receipt.get("runtime_version") != RUNTIME_VERSION:
        _error(errors, "RECEIPT_RUNTIME_VERSION_MISMATCH", f"{path}.runtime_version", "receipt was not produced by the frozen runtime version")

    acquisition_type = receipt.get("acquisition_type")
    if acquisition_type not in {
        "runtime_fetch",
        "browser_export",
        "trusted_local_copy",
        "user_supplied",
        "search_snippet",
    }:
        _error(errors, "RECEIPT_ACQUISITION_TYPE_INVALID", f"{path}.acquisition_type", "receipt acquisition type is not allowed")

    status = receipt.get("http_status")
    if status is not None and (not isinstance(status, int) or not 100 <= status <= 599):
        _error(errors, "RECEIPT_HTTP_STATUS_INVALID", f"{path}.http_status", "HTTP status must be null or an integer from 100 to 599")
    bytes_read = receipt.get("bytes_read")
    if type(bytes_read) is not int or bytes_read < 0:
        _error(errors, "RECEIPT_BYTES_INVALID", f"{path}.bytes_read", "bytes_read must be a non-negative integer")
    for field in ("retrieval_complete", "support_eligible"):
        if not isinstance(receipt.get(field), bool):
            _error(errors, "RECEIPT_FLAG_INVALID", f"{path}.{field}", f"{field} must be boolean")
    for field in ("content_sha256", "headers_sha256"):
        value = receipt.get(field)
        if not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None:
            _error(errors, "RECEIPT_HASH_INVALID", f"{path}.{field}", f"{field} must be a SHA-256 digest")
    if not isinstance(receipt.get("redirect_chain"), list):
        _error(errors, "RECEIPT_REDIRECT_CHAIN_INVALID", f"{path}.redirect_chain", "redirect_chain must be an array")
    if not isinstance(receipt.get("origin_id"), str) or not receipt.get("origin_id"):
        _error(errors, "RECEIPT_ORIGIN_ID_INVALID", f"{path}.origin_id", "origin_id must be a non-empty string")

    for field in ("requested_url", "final_url"):
        value = receipt.get(field)
        try:
            parsed = urlsplit(value) if isinstance(value, str) else None
        except ValueError:
            parsed = None
        if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.netloc:
            _error(errors, "RECEIPT_URL_INVALID", f"{path}.{field}", "receipt URL must be a sanitized HTTP(S) URL")
        elif parsed.query or parsed.fragment:
            _error(errors, "RECEIPT_URL_NOT_SANITIZED", f"{path}.{field}", "receipt URL must not persist query or fragment text")
        else:
            try:
                target = assert_http_url_syntax(value)
                try:
                    literal = _normalized_ip(target["hostname"])
                except ValueError:
                    literal = None
                if literal is not None and not literal.is_global:
                    raise AuditError("literal IP is not public")
            except AuditError:
                runtime_rejected = (
                    allow_rejected_target
                    and acquisition_type == "runtime_fetch"
                    and receipt.get("retrieval_complete") is False
                    and receipt.get("support_eligible") is False
                    and receipt.get("transport_attestation") == "runtime_rejected"
                )
                if runtime_rejected:
                    continue
                _error(errors, "RECEIPT_URL_UNSAFE", f"{path}.{field}", "receipt URL violates the runtime public-network boundary")

    for field in ("requested_url_query_sha256", "final_url_query_sha256"):
        value = receipt.get(field)
        if value is not None and (
            not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None
        ):
            _error(errors, "RECEIPT_QUERY_HASH_INVALID", f"{path}.{field}", "query hash must be null or a SHA-256 digest")

    redirect_chain = receipt.get("redirect_chain")
    if isinstance(redirect_chain, list):
        expected_from = receipt.get("requested_url")
        previous_to_ip: str | None = None
        for index, hop in enumerate(redirect_chain):
            hop_path = f"{path}.redirect_chain[{index}]"
            if not isinstance(hop, dict):
                _error(errors, "RECEIPT_REDIRECT_ITEM_INVALID", hop_path, "redirect item must be an object")
                continue
            for field in ("from", "to"):
                value = hop.get(field)
                try:
                    parsed = urlsplit(value) if isinstance(value, str) else None
                except ValueError:
                    parsed = None
                if parsed is None or parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    _error(errors, "RECEIPT_REDIRECT_URL_INVALID", f"{hop_path}.{field}", "redirect URL must be HTTP(S)")
                elif parsed.query or parsed.fragment:
                    _error(errors, "RECEIPT_REDIRECT_URL_NOT_SANITIZED", f"{hop_path}.{field}", "redirect URL must not persist query or fragment text")
                else:
                    try:
                        assert_http_url_syntax(value)
                    except AuditError:
                        _error(
                            errors,
                            "RECEIPT_REDIRECT_URL_UNSAFE",
                            f"{hop_path}.{field}",
                            "redirect URL violates the runtime public-network boundary",
                        )
            for field in ("from_query_sha256", "to_query_sha256"):
                value = hop.get(field)
                if value is not None and (
                    not isinstance(value, str)
                    or re.fullmatch(r"[a-f0-9]{64}", value) is None
                ):
                    _error(errors, "RECEIPT_REDIRECT_QUERY_HASH_INVALID", f"{hop_path}.{field}", "redirect query hash must be null or SHA-256")
            if acquisition_type == "runtime_fetch" and receipt.get("retrieval_complete") is True:
                hop_ips: dict[str, str] = {}
                for field in ("from_resolved_ip", "to_resolved_ip"):
                    value = hop.get(field)
                    try:
                        address = _normalized_ip(value) if isinstance(value, str) else None
                    except ValueError:
                        address = None
                    if address is None or not address.is_global:
                        _error(
                            errors,
                            "RECEIPT_REDIRECT_IP_INVALID",
                            f"{hop_path}.{field}",
                            "completed runtime redirects require a public resolved IP for every hop boundary",
                        )
                    else:
                        hop_ips[field] = str(address)
                current_from_ip = hop_ips.get("from_resolved_ip")
                current_to_ip = hop_ips.get("to_resolved_ip")
                if (
                    previous_to_ip is not None
                    and current_from_ip is not None
                    and current_from_ip != previous_to_ip
                ):
                    _error(
                        errors,
                        "RECEIPT_REDIRECT_IP_DISCONTINUOUS",
                        f"{hop_path}.from_resolved_ip",
                        "redirect hop IP does not match the IP pinned for the preceding target",
                    )
                if current_to_ip is not None:
                    previous_to_ip = current_to_ip
            if hop.get("http_status") not in REDIRECT_STATUSES:
                _error(errors, "RECEIPT_REDIRECT_STATUS_INVALID", f"{hop_path}.http_status", "redirect status is not allowed")
            if isinstance(expected_from, str) and hop.get("from") != expected_from:
                _error(errors, "RECEIPT_REDIRECT_CHAIN_DISCONTINUOUS", f"{hop_path}.from", "redirect chain does not start from the preceding sanitized URL")
            expected_from = hop.get("to")
        if redirect_chain and expected_from != receipt.get("final_url"):
            _error(errors, "RECEIPT_REDIRECT_FINAL_MISMATCH", f"{path}.final_url", "final URL does not match the end of the redirect chain")
        if (
            redirect_chain
            and acquisition_type == "runtime_fetch"
            and receipt.get("retrieval_complete") is True
            and previous_to_ip is not None
        ):
            try:
                final_resolved_ip = _normalized_ip(receipt.get("resolved_ip"))
            except (TypeError, ValueError):
                final_resolved_ip = None
            if final_resolved_ip is None or str(final_resolved_ip) != previous_to_ip:
                _error(
                    errors,
                    "RECEIPT_REDIRECT_FINAL_IP_MISMATCH",
                    f"{path}.resolved_ip",
                    "final resolved IP does not match the IP pinned for the last redirect target",
                )

    if acquisition_type == "runtime_fetch" and receipt.get("retrieval_complete") is True:
        if receipt.get("transport_attestation") != "dns_pinned_runtime":
            _error(errors, "RUNTIME_TRANSPORT_ATTESTATION_INVALID", f"{path}.transport_attestation", "successful runtime fetch requires DNS-pinned runtime attestation")
        if not isinstance(receipt.get("artifact"), str) or not receipt.get("artifact"):
            _error(errors, "RUNTIME_ARTIFACT_REQUIRED", f"{path}.artifact", "completed runtime fetch requires a saved raw artifact")
        resolved_ip = receipt.get("resolved_ip")
        try:
            resolved_address = _normalized_ip(resolved_ip) if isinstance(resolved_ip, str) else None
        except ValueError:
            resolved_address = None
        if resolved_address is None or not resolved_address.is_global:
            _error(errors, "RUNTIME_RESOLVED_IP_INVALID", f"{path}.resolved_ip", "completed runtime fetch requires a public resolved IP")

    if acquisition_type == "runtime_fetch" and receipt.get("retrieval_complete") is False:
        if receipt.get("transport_attestation") != "runtime_rejected":
            _error(errors, "RUNTIME_REJECTION_ATTESTATION_INVALID", f"{path}.transport_attestation", "failed runtime fetch requires runtime_rejected attestation")

    if acquisition_type == "runtime_fetch" and receipt.get("support_eligible") is True:
        if not isinstance(receipt.get("parsed_text"), str) or not receipt.get("parsed_text"):
            _error(errors, "RUNTIME_PARSED_TEXT_REQUIRED", f"{path}.parsed_text", "eligible runtime evidence requires saved parsed text")
        parsed_hash = receipt.get("parsed_text_sha256")
        if not isinstance(parsed_hash, str) or re.fullmatch(r"[a-f0-9]{64}", parsed_hash) is None:
            _error(errors, "RUNTIME_PARSED_TEXT_HASH_REQUIRED", f"{path}.parsed_text_sha256", "eligible runtime evidence requires a parsed-text SHA-256")
        if not isinstance(receipt.get("parser_name"), str) or not receipt.get("parser_name"):
            _error(errors, "RUNTIME_PARSER_REQUIRED", f"{path}.parser_name", "eligible runtime evidence requires a parser identity")
        if not _receipt_parser_is_frozen(receipt):
            _error(
                errors,
                "RUNTIME_PARSER_VERSION_MISMATCH",
                f"{path}.parser_version",
                "eligible runtime evidence requires a recorded, frozen parser identity and version",
            )


def _source_can_support_core(source: dict[str, Any], claim: dict[str, Any]) -> bool:
    if source.get("source_tier") == "C" or source.get("evidence_role") == "lead_only":
        return False
    if (
        source.get("evidence_role") == "subject_self_report"
        and claim.get("claim_type") != "quotation_attribution"
    ):
        return False
    if claim.get("claim_type") == "objective_performance" and (
        source.get("source_tier") == "A2"
        or source.get("evidence_role") == "subject_self_report"
    ):
        return False
    return True


def _origin_is_known(origin_id: Any) -> bool:
    if not isinstance(origin_id, str) or not origin_id.strip():
        return False
    normalized = origin_id.strip().casefold()
    patterns = (
        r"doi:10\.\d{4,9}/\S+",
        r"pmid:\d+",
        r"nct:nct\d+",
        r"filing:[a-z0-9.-]+:[a-z0-9._-]+",
        r"regulation:[a-z0-9.-]+:[a-z0-9._-]+",
        r"court:[a-z0-9.-]+:[a-z0-9._-]+",
        r"dataset:[a-z0-9.-]+:[a-z0-9._/-]+",
        r"commit:[a-f0-9]{7,64}",
    )
    return any(re.fullmatch(pattern, normalized) is not None for pattern in patterns)


def _same_evidence_record(
    left_source: dict[str, Any], right_source: dict[str, Any]
) -> bool:
    """Allow purpose binding only within one source or one verified record root."""

    if left_source.get("source_id") == right_source.get("source_id"):
        return True
    left_origin = left_source.get("origin_id")
    right_origin = right_source.get("origin_id")
    return (
        left_origin == right_origin
        and _origin_is_known(left_origin)
        and _origin_is_known(right_origin)
    )


def _purpose_covers_decisive_records(
    decisive: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
    purpose_evidence: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
) -> bool:
    return bool(decisive) and all(
        any(_same_evidence_record(source, purpose_source) for _, purpose_source, _ in purpose_evidence)
        for _, source, _ in decisive
    )


def _validate_high_temporal_evidence(
    claim: dict[str, Any],
    claim_path: str,
    claim_as_of: dt.date | None,
    candidates: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]],
    errors: list[dict[str, str]],
) -> None:
    if claim.get("temporal_sensitivity") != "high":
        return
    current = [
        (source, receipt)
        for _, source, receipt in candidates
        if source.get("freshness_status") == "current"
    ]
    if not current:
        _error(
            errors,
            "FRESHNESS_NOT_ESTABLISHED",
            claim_path,
            "a non-unknown current decision requires eligible evidence assessed as current",
        )
        return
    if any(
        not isinstance(source.get("freshness_rationale"), str)
        or not source.get("freshness_rationale", "").strip()
        for source, _ in current
    ):
        _error(
            errors,
            "FRESHNESS_RATIONALE_REQUIRED",
            claim_path,
            "current evidence requires a non-empty freshness rationale",
        )
    if claim_as_of is not None and any(
        (accessed := parse_iso_datetime(receipt.get("accessed_at"))) is None
        or abs((accessed.date() - claim_as_of).days) > 1
        for _, receipt in current
    ):
        _error(
            errors,
            "CURRENT_SOURCE_ACCESS_DATE_MISMATCH",
            claim_path,
            "current evidence must have been accessed on or within one day of the claim as_of date",
        )


def validate_bundle(
    ledger: dict[str, Any], receipts: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if ledger.get("schema_version") != "3.1":
        _error(errors, "SCHEMA_VERSION_UNSUPPORTED", "schema_version", "expected schema version 3.1")
    verification_date = parse_iso_date(ledger.get("verification_date"))
    if verification_date is None:
        _error(
            errors,
            "VERIFICATION_DATE_INVALID",
            "verification_date",
            "verification_date must be an ISO YYYY-MM-DD date",
        )

    scope = ledger.get("scope")
    if not isinstance(scope, dict) or not isinstance(scope.get("triggered"), bool):
        _error(errors, "SCOPE_INVALID", "scope", "scope.triggered must be boolean")
        scope = {
            "triggered": True,
            "unreviewed_claims": [],
            "candidate_inventory": [],
        }

    candidate_inventory = (
        scope.get("candidate_inventory", []) if isinstance(scope, dict) else []
    )
    candidate_texts: set[str] = set()
    candidate_ids: set[str] = set()
    candidate_origins: dict[str, str] = {}
    candidate_span_records: list[tuple[int, int, str]] = []
    if scope.get("triggered") is True:
        if not isinstance(candidate_inventory, list) or not candidate_inventory:
            _error(
                errors,
                "CANDIDATE_BINDING_REQUIRED",
                "scope.candidate_inventory",
                "a triggered audit must bind every frozen candidate to original-input selectors",
            )
            candidate_inventory = []
        for candidate_index, candidate in enumerate(candidate_inventory):
            candidate_path = f"scope.candidate_inventory[{candidate_index}]"
            if not isinstance(candidate, dict):
                _error(
                    errors,
                    "CANDIDATE_BINDING_INVALID",
                    candidate_path,
                    "candidate binding must be an object",
                )
                continue
            text = candidate.get("text")
            candidate_id = candidate.get("candidate_id")
            spans = candidate.get("spans")
            digest = candidate.get("sha256")
            origin = candidate.get("origin", "declared")
            if not isinstance(candidate_id, str) or not re.fullmatch(
                r"U[0-9]{3,}", candidate_id
            ):
                _error(
                    errors,
                    "CANDIDATE_ID_INVALID",
                    f"{candidate_path}.candidate_id",
                    "candidate_id must match U followed by at least three digits",
                )
            elif candidate_id in candidate_ids:
                _error(
                    errors,
                    "DUPLICATE_CANDIDATE_ID",
                    f"{candidate_path}.candidate_id",
                    "candidate_id must be unique",
                )
            else:
                candidate_ids.add(candidate_id)
            if not isinstance(text, str) or not text:
                _error(
                    errors,
                    "CANDIDATE_TEXT_INVALID",
                    f"{candidate_path}.text",
                    "candidate text must be non-empty",
                )
                continue
            if text in candidate_texts:
                _error(
                    errors,
                    "DUPLICATE_CANDIDATE_BINDING",
                    f"{candidate_path}.text",
                    "candidate text must be unique",
                )
            candidate_texts.add(text)
            if origin not in {"declared", "auto_gap"}:
                _error(
                    errors,
                    "CANDIDATE_ORIGIN_INVALID",
                    f"{candidate_path}.origin",
                    "candidate origin must be declared or auto_gap",
                )
            else:
                candidate_origins[text] = origin
            if digest != sha256_bytes(text.encode("utf-8")):
                _error(
                    errors,
                    "CANDIDATE_HASH_MISMATCH",
                    f"{candidate_path}.sha256",
                    "candidate hash does not match its text",
                )
            if not isinstance(spans, list) or not spans:
                _error(
                    errors,
                    "CANDIDATE_SPANS_REQUIRED",
                    f"{candidate_path}.spans",
                    "candidate requires at least one input span",
                )
            else:
                if origin == "declared" and len(spans) != 1:
                    _error(
                        errors,
                        "DECLARED_CANDIDATE_SPAN_COUNT_INVALID",
                        f"{candidate_path}.spans",
                        "a declared candidate must bind exactly one unique input span",
                    )
                seen_spans: set[tuple[int, int]] = set()
                for span_index, span in enumerate(spans):
                    span_path = f"{candidate_path}.spans[{span_index}]"
                    if not isinstance(span, dict):
                        _error(
                            errors,
                            "CANDIDATE_SPAN_INVALID",
                            span_path,
                            "candidate span must be an object with integer start and end",
                        )
                        continue
                    start = span.get("start")
                    end = span.get("end")
                    valid_integers = (
                        isinstance(start, int)
                        and not isinstance(start, bool)
                        and isinstance(end, int)
                        and not isinstance(end, bool)
                    )
                    if not valid_integers or start < 0 or end <= start:
                        _error(
                            errors,
                            "CANDIDATE_SPAN_INVALID",
                            span_path,
                            "candidate span requires integers with 0 <= start < end",
                        )
                        continue
                    span_key = (start, end)
                    if span_key in seen_spans:
                        _error(
                            errors,
                            "DUPLICATE_CANDIDATE_SPAN",
                            span_path,
                            "candidate spans must be unique",
                        )
                        continue
                    seen_spans.add(span_key)
                    if isinstance(text, str) and end - start != len(text):
                        _error(
                            errors,
                            "CANDIDATE_SPAN_LENGTH_MISMATCH",
                            span_path,
                            "candidate span length must equal the bound text length",
                        )
                    candidate_span_records.append((start, end, candidate_path))

        ordered_spans = sorted(candidate_span_records, key=lambda item: (item[0], item[1]))
        for index, (start, end, owner) in enumerate(ordered_spans):
            for other_start, other_end, other_owner in ordered_spans[index + 1 :]:
                if other_start >= end:
                    break
                if max(start, other_start) < min(end, other_end):
                    _error(
                        errors,
                        "CANDIDATE_SPAN_OVERLAP",
                        "scope.candidate_inventory",
                        f"candidate spans overlap between {owner} and {other_owner}",
                    )

    claims = ledger.get("claims")
    sources = ledger.get("sources")
    if not isinstance(claims, list):
        _error(errors, "CLAIMS_INVALID", "claims", "claims must be a list")
        claims = []
    if not isinstance(sources, list):
        _error(errors, "SOURCES_INVALID", "sources", "sources must be a list")
        sources = []

    source_map: dict[str, dict[str, Any]] = {}
    retired_source_ids: set[str] = set()
    source_ids_casefolded: dict[str, str] = {}
    for index, source in enumerate(sources):
        path = f"sources[{index}]"
        if not isinstance(source, dict):
            _error(errors, "SOURCE_INVALID", path, "source must be an object")
            continue
        source_id = source.get("source_id")
        if not isinstance(source_id, str) or not source_id:
            _error(errors, "SOURCE_ID_MISSING", f"{path}.source_id", "source_id is required")
            continue
        if source_id in source_map:
            _error(errors, "DUPLICATE_SOURCE_ID", f"{path}.source_id", f"duplicate source_id {source_id}")
            continue
        folded_source_id = source_id.casefold()
        if folded_source_id in source_ids_casefolded:
            _error(
                errors,
                "DUPLICATE_SOURCE_ID_CASEFOLD",
                f"{path}.source_id",
                f"source_id collides case-insensitively with {source_ids_casefolded[folded_source_id]}",
            )
            continue
        source_ids_casefolded[folded_source_id] = source_id
        try:
            validate_source_id(source_id)
        except AuditError:
            _error(
                errors,
                "SOURCE_ID_UNSAFE",
                f"{path}.source_id",
                "source_id is not safe for use as a receipt filename",
            )
        expected_receipt_path = f"receipts/{source_id}.json"
        if source.get("receipt") != expected_receipt_path:
            _error(
                errors,
                "SOURCE_RECEIPT_PATH_INVALID",
                f"{path}.receipt",
                "receipt path must be the canonical path for this source_id",
            )
        if source.get("source_tier") not in ALLOWED_SOURCE_TIERS:
            _error(errors, "SOURCE_TIER_INVALID", f"{path}.source_tier", "source tier is not allowed")
        if source.get("evidence_role") not in ALLOWED_EVIDENCE_ROLES:
            _error(errors, "EVIDENCE_ROLE_INVALID", f"{path}.evidence_role", "evidence role is not allowed")
        if source.get("freshness_status") not in ALLOWED_FRESHNESS:
            _error(errors, "FRESHNESS_STATUS_INVALID", f"{path}.freshness_status", "freshness status is not allowed")
        receipt = receipts.get(source_id)
        if receipt is None:
            _error(errors, "SOURCE_RECEIPT_MISSING", f"{path}.receipt", f"no receipt loaded for {source_id}")
            continue
        is_retired = source.get("active") is False
        if is_retired:
            retired_source_ids.add(source_id)
            if not isinstance(source.get("retirement_reason"), str) or not source.get(
                "retirement_reason", ""
            ).strip():
                _error(
                    errors,
                    "RETIRED_SOURCE_REASON_REQUIRED",
                    f"{path}.retirement_reason",
                    "retired source must preserve a non-empty retirement reason",
                )
            if parse_iso_datetime(source.get("retired_at")) is None:
                _error(
                    errors,
                    "RETIRED_SOURCE_TIME_INVALID",
                    f"{path}.retired_at",
                    "retired source must record a timezone-aware retirement time",
                )
        else:
            source_map[source_id] = source
        _validate_receipt_contract(
            receipt,
            source_id,
            errors,
            allow_rejected_target=is_retired,
        )
        expected_hash = compute_receipt_sha256(receipt)
        if receipt.get("receipt_sha256") != expected_hash:
            _error(errors, "RECEIPT_HASH_MISMATCH", f"receipts.{source_id}", "receipt content changed after hashing")
        if receipt.get("source_id") != source_id:
            _error(errors, "RECEIPT_SOURCE_ID_MISMATCH", f"receipts.{source_id}.source_id", "receipt belongs to another source")
        if source.get("origin_id") and receipt.get("origin_id") != source.get("origin_id"):
            _error(errors, "ORIGIN_ID_MISMATCH", f"receipts.{source_id}.origin_id", "source and receipt origin differ")
        if not source.get("publication_date"):
            _warning(warnings, "SOURCE_DATE_MISSING", f"{path}.publication_date", "source publication date is unknown")
        publication_value = source.get("publication_date")
        publication_date = None
        if publication_value != "unknown":
            publication_date = parse_iso_date(publication_value)
            if publication_date is None:
                _error(
                    errors,
                    "SOURCE_DATE_INVALID",
                    f"{path}.publication_date",
                    "source publication date must be YYYY-MM-DD or unknown",
                )
        accessed_at = parse_iso_datetime(receipt.get("accessed_at"))
        if accessed_at is None:
            _error(
                errors,
                "ACCESSED_AT_INVALID",
                f"receipts.{source_id}.accessed_at",
                "receipt accessed_at must be an ISO timezone-aware timestamp",
            )
        elif publication_date is not None and publication_date > accessed_at.date():
            _error(
                errors,
                "SOURCE_DATE_AFTER_ACCESS",
                f"{path}.publication_date",
                "source publication date cannot be after its recorded access time",
            )

    for source_id in receipts:
        if source_id not in source_map and source_id not in retired_source_ids:
            _warning(warnings, "ORPHAN_RECEIPT", f"receipts.{source_id}", "receipt is not registered in the ledger")

    covered_candidate_texts: set[str] = set()
    claim_ids: set[str] = set()
    claim_subspans: dict[str, list[tuple[int, int]]] = {}
    for index, claim in enumerate(claims):
        path = f"claims[{index}]"
        if not isinstance(claim, dict):
            _error(errors, "CLAIM_INVALID", path, "claim must be an object")
            continue
        claim_id = claim.get("claim_id")
        if not isinstance(claim_id, str) or not claim_id.strip():
            _error(
                errors,
                "CLAIM_ID_INVALID",
                f"{path}.claim_id",
                "claim_id must be a non-empty string",
            )
            claim_id = f"index-{index}"
        elif claim_id in claim_ids:
            _error(
                errors,
                "DUPLICATE_CLAIM_ID",
                f"{path}.claim_id",
                "claim_id must be unique within an audit",
            )
        else:
            claim_ids.add(claim_id)
        claim_path = f"{path}({claim_id})"
        input_candidates = claim.get("input_candidates")
        if not isinstance(input_candidates, list) or len(input_candidates) != 1:
            _error(
                errors,
                "ATOMIC_CANDIDATE_COVERAGE_REQUIRED",
                f"{claim_path}.input_candidates",
                "each atomic claim must cover exactly one frozen candidate",
            )
        elif candidate_texts and input_candidates[0] not in candidate_texts:
            _error(
                errors,
                "CLAIM_CANDIDATE_NOT_FROZEN",
                f"{claim_path}.input_candidates[0]",
                "claim coverage does not resolve to the frozen candidate inventory",
            )
        else:
            candidate_text = input_candidates[0]
            covered_candidate_texts.add(candidate_text)
            claim_text = claim.get("text")
            if not isinstance(claim_text, str) or claim_text not in candidate_text:
                _error(
                    errors,
                    "CLAIM_TEXT_NOT_BOUND_TO_CANDIDATE",
                    f"{claim_path}.text",
                    "atomic claim text must be an exact subspan of its frozen input candidate",
                )
            else:
                starts: list[int] = []
                cursor = 0
                while True:
                    found = candidate_text.find(claim_text, cursor)
                    if found < 0:
                        break
                    starts.append(found)
                    cursor = found + max(1, len(claim_text))
                if len(starts) != 1:
                    _error(
                        errors,
                        "CLAIM_TEXT_BINDING_AMBIGUOUS",
                        f"{claim_path}.text",
                        "atomic claim text must resolve to exactly one subspan inside its candidate",
                    )
                else:
                    claim_subspans.setdefault(candidate_text, []).append(
                        (starts[0], starts[0] + len(claim_text))
                    )
        if claim.get("claim_type") not in ALLOWED_CLAIM_TYPES:
            _error(errors, "CLAIM_TYPE_INVALID", f"{claim_path}.claim_type", "claim type is not allowed")
        if claim.get("temporal_sensitivity") not in ALLOWED_TEMPORAL_SENSITIVITY:
            _error(
                errors,
                "TEMPORAL_SENSITIVITY_INVALID",
                f"{claim_path}.temporal_sensitivity",
                "temporal sensitivity is not allowed",
            )
        if claim.get("risk_domain") not in HIGH_RISK_DOMAINS | {"none"}:
            _error(errors, "RISK_DOMAIN_INVALID", f"{claim_path}.risk_domain", "risk domain is not allowed")
        if claim.get("causal_basis") not in ALLOWED_CAUSAL_BASIS_VALUES:
            _error(errors, "CAUSAL_BASIS_INVALID", f"{claim_path}.causal_basis", "causal basis is not allowed")
        status = claim.get("status")
        if status not in ALLOWED_STATUSES:
            _error(errors, "STATUS_INVALID", f"{claim_path}.status", "claim status is not allowed")
        if claim.get("assessment_recorded") is not True:
            _error(
                errors,
                "CLAIM_ASSESSMENT_REQUIRED",
                f"{claim_path}.assessment_recorded",
                "every claim must pass through decide or assess after its latest evidence change",
            )
        countercheck = claim.get("countercheck")
        if not isinstance(countercheck, dict):
            _error(
                errors,
                "COUNTERCHECK_REQUIRED",
                f"{claim_path}.countercheck",
                "every assessed claim requires an explicit current falsification check",
            )
        else:
            for field in ("falsifier", "stop_reason", "checked_at", "basis_hash"):
                if not isinstance(countercheck.get(field), str) or not countercheck.get(
                    field, ""
                ).strip():
                    _error(
                        errors,
                        "COUNTERCHECK_FIELD_INVALID",
                        f"{claim_path}.countercheck.{field}",
                        f"countercheck {field} must be a non-empty string",
                    )
            for field in ("falsifier", "stop_reason"):
                value = countercheck.get(field)
                if isinstance(value, str) and len(value.encode("utf-8")) > MAX_COUNTERCHECK_TEXT:
                    _error(
                        errors,
                        "COUNTERCHECK_FIELD_TOO_LARGE",
                        f"{claim_path}.countercheck.{field}",
                        f"countercheck {field} exceeds the size limit",
                    )
            checked_at = parse_iso_datetime(countercheck.get("checked_at"))
            if checked_at is None:
                _error(
                    errors,
                    "COUNTERCHECK_TIME_INVALID",
                    f"{claim_path}.countercheck.checked_at",
                    "countercheck checked_at must be a timezone-aware ISO timestamp",
                )
            elif checked_at > dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=5):
                _error(
                    errors,
                    "COUNTERCHECK_TIME_IN_FUTURE",
                    f"{claim_path}.countercheck.checked_at",
                    "countercheck checked_at cannot be in the future",
                )
            checked_source_ids = countercheck.get("checked_source_ids")
            if (
                not isinstance(checked_source_ids, list)
                or any(
                    not isinstance(source_id, str) or not source_id
                    for source_id in checked_source_ids
                )
                or len(checked_source_ids) != len(set(checked_source_ids or []))
            ):
                _error(
                    errors,
                    "COUNTERCHECK_SOURCES_INVALID",
                    f"{claim_path}.countercheck.checked_source_ids",
                    "countercheck checked_source_ids must be a unique source list",
                )
            else:
                if len(checked_source_ids) > MAX_COUNTERCHECK_SOURCES:
                    _error(
                        errors,
                        "COUNTERCHECK_SOURCES_TOO_LARGE",
                        f"{claim_path}.countercheck.checked_source_ids",
                        "countercheck source list exceeds the size limit",
                    )
                if status in CONFIRMING_STATUSES and not checked_source_ids:
                    _error(
                        errors,
                        "COUNTERCHECK_SOURCE_REQUIRED",
                        f"{claim_path}.countercheck.checked_source_ids",
                        "a decisive status requires at least one actually checked source",
                    )
                for source_id in checked_source_ids:
                    if source_id in retired_source_ids:
                        _error(
                            errors,
                            "COUNTERCHECK_SOURCE_RETIRED",
                            f"{claim_path}.countercheck.checked_source_ids",
                            f"countercheck must be rerun after source retirement: {source_id}",
                        )
                    elif source_id not in source_map:
                        _error(
                            errors,
                            "COUNTERCHECK_SOURCE_UNAVAILABLE",
                            f"{claim_path}.countercheck.checked_source_ids",
                            f"countercheck source is unknown or unavailable: {source_id}",
                        )
                if countercheck.get("result") != "inconclusive":
                    for source_id in checked_source_ids:
                        if not _receipt_is_usable(receipts.get(source_id, {})):
                            _error(
                                errors,
                                "COUNTERCHECK_SOURCE_INELIGIBLE",
                                f"{claim_path}.countercheck.checked_source_ids",
                                f"conclusive countercheck result relies on an ineligible source: {source_id}",
                            )
            if countercheck.get("result") not in ALLOWED_COUNTERCHECK_RESULTS:
                _error(
                    errors,
                    "COUNTERCHECK_RESULT_INVALID",
                    f"{claim_path}.countercheck.result",
                    "countercheck result is not allowed",
                )
            if countercheck.get("result") == "conflict_found" and not any(
                isinstance(item, dict)
                and item.get("support") == "conflict"
                and item.get("source_id") in (checked_source_ids or [])
                for item in claim.get("evidence", [])
            ):
                _error(
                    errors,
                    "COUNTERCHECK_CONFLICT_UNBOUND",
                    f"{claim_path}.countercheck.result",
                    "conflict_found requires conflict evidence bound to a checked source",
                )
            if countercheck.get("result") == "scope_narrowed":
                _error(
                    errors,
                    "COUNTERCHECK_REASSESSMENT_REQUIRED",
                    f"{claim_path}.countercheck.result",
                    "scope_narrowed must be resolved by reassessment and a new countercheck",
                )
            if countercheck.get("basis_hash") != countercheck_basis_hash(claim):
                _error(
                    errors,
                    "COUNTERCHECK_STALE",
                    f"{claim_path}.countercheck.basis_hash",
                    "claim, evidence, or assessment changed after the countercheck",
                )
        claim_as_of = parse_iso_date(claim.get("as_of"))
        if claim.get("temporal_sensitivity") == "high":
            if claim_as_of is None:
                _error(
                    errors,
                    "HIGH_TEMPORAL_WITHOUT_AS_OF",
                    f"{claim_path}.as_of",
                    "high-temporal claim requires a valid ISO verification date",
                )
            elif verification_date is not None and claim_as_of != verification_date:
                _error(
                    errors,
                    "AS_OF_VERIFICATION_DATE_MISMATCH",
                    f"{claim_path}.as_of",
                    "a current claim as_of date must match the audit verification date",
                )

        evidence = claim.get("evidence", [])
        if not isinstance(evidence, list):
            _error(errors, "EVIDENCE_INVALID", f"{claim_path}.evidence", "evidence must be a list")
            evidence = []

        usable_located: list[tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = []
        for evidence_index, item in enumerate(evidence):
            evidence_path = f"{claim_path}.evidence[{evidence_index}]"
            if not isinstance(item, dict):
                _error(errors, "EVIDENCE_ITEM_INVALID", evidence_path, "evidence item must be an object")
                continue
            source_id = item.get("source_id")
            source = source_map.get(source_id)
            receipt = receipts.get(source_id)
            if source is None or receipt is None:
                _error(errors, "EVIDENCE_SOURCE_UNAVAILABLE", f"{evidence_path}.source_id", "evidence does not resolve to a registered receipt")
                continue
            if _pdf_text_binding_unavailable(receipt):
                _error(
                    errors,
                    "PDF_TEXT_UNAVAILABLE",
                    evidence_path,
                    "PDF evidence cannot be bound until local text extraction completes successfully",
                )
            if (
                receipt.get("acquisition_type") == "search_snippet"
                and item.get("support") in {"direct", "partial", "conflict"}
            ):
                _error(
                    errors,
                    "SEARCH_SNIPPET_NOT_EVIDENCE",
                    evidence_path,
                    "search-result snippets are locators, not opened source evidence",
                )
            if item.get("support") in {"direct", "partial", "conflict"}:
                if not item.get("locator") or not item.get("excerpt"):
                    _error(errors, "EVIDENCE_NOT_LOCATED", evidence_path, "supporting or conflicting evidence requires a locator and excerpt")
                if not isinstance(item.get("support_scope"), str) or not item.get(
                    "support_scope", ""
                ).strip():
                    _error(
                        errors,
                        "EVIDENCE_SUPPORT_SCOPE_REQUIRED",
                        f"{evidence_path}.support_scope",
                        "decisive evidence requires a non-empty statement of its narrowest support scope",
                    )
                if _receipt_is_usable(receipt):
                    usable_located.append((item, source, receipt))
            inference_span = item.get("inference_span")
            if type(inference_span) is not int or not 0 <= inference_span <= 3:
                _error(errors, "INFERENCE_SPAN_INVALID", f"{evidence_path}.inference_span", "inference_span must be an integer from 0 to 3")
            purpose = item.get("evidence_purpose", "substantive")
            if purpose not in ALLOWED_EVIDENCE_PURPOSES:
                _error(
                    errors,
                    "EVIDENCE_PURPOSE_INVALID",
                    f"{evidence_path}.evidence_purpose",
                    "evidence purpose is not allowed",
                )

        identity_evidence = [
            triple
            for triple in usable_located
            if triple[0].get("support") == "direct"
            and triple[0].get("evidence_purpose") == "source_identity"
            and triple[0].get("inference_span", 99) <= 1
        ]
        substantive_direct = [
            triple
            for triple in usable_located
            if triple[0].get("support") == "direct"
            and triple[0].get("evidence_purpose", "substantive") == "substantive"
        ]
        substantive_partial = [
            triple
            for triple in usable_located
            if triple[0].get("support") in {"direct", "partial"}
            and triple[0].get("evidence_purpose", "substantive") == "substantive"
        ]
        substantive_conflicts = [
            triple
            for triple in usable_located
            if triple[0].get("support") == "conflict"
            and triple[0].get("evidence_purpose", "substantive") == "substantive"
        ]
        decisive_evidence: list[
            tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
        ] = []
        design_evidence: list[
            tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
        ] = []
        currentness_evidence: list[
            tuple[dict[str, Any], dict[str, Any], dict[str, Any]]
        ] = []
        if status in CONFIRMING_STATUSES and claim.get("source_identity_gate") == "pass":
            if not identity_evidence:
                _error(
                    errors,
                    "SOURCE_IDENTITY_EVIDENCE_REQUIRED",
                    claim_path,
                    "a passing source identity gate requires an exact opened-source identity excerpt",
                )

        if status == "confirmed":
            direct_candidates = substantive_direct
            confirming = [
                triple for triple in direct_candidates if _source_can_support_core(triple[1], claim)
            ]
            if direct_candidates and not confirming:
                if any(
                    source.get("source_tier") == "C" or source.get("evidence_role") == "lead_only"
                    for _, source, _ in direct_candidates
                ):
                    _error(
                        errors,
                        "LEAD_ONLY_CANNOT_CONFIRM",
                        claim_path,
                        "tier C or lead-only material cannot confirm a core external fact",
                    )
                if any(
                    source.get("evidence_role") == "subject_self_report"
                    for _, source, _ in direct_candidates
                ) and claim.get("claim_type") != "quotation_attribution":
                    _error(
                        errors,
                        "SELF_REPORT_CANNOT_CONFIRM_CORE_FACT",
                        claim_path,
                        "a subject self-report can confirm the statement was made, not the objective core fact",
                    )
                if claim.get("claim_type") == "objective_performance" and any(
                    source.get("source_tier") == "A2"
                    or source.get("evidence_role") == "subject_self_report"
                    for _, source, _ in direct_candidates
                ):
                    _error(
                        errors,
                        "VENDOR_SELF_REPORT_CANNOT_CONFIRM_OBJECTIVE_PERFORMANCE",
                        claim_path,
                        "A2 or subject-controlled material cannot independently confirm objective performance",
                    )
            if not confirming:
                _error(errors, "SUBSTANTIVE_EVIDENCE_REQUIRED", claim_path, "confirmed status requires usable direct substantive evidence from an opened source")
            decisive_evidence = confirming
            if claim.get("source_identity_gate") != "pass" or claim.get("content_support_gate") != "pass":
                _error(errors, "CONFIRMED_WITHOUT_PASSING_GATES", claim_path, "confirmed status requires identity and support gates to pass")
            if any(item.get("inference_span", 99) > 1 for item, _, _ in confirming):
                _error(errors, "CONFIRMED_WITH_EXCESSIVE_INFERENCE", claim_path, "confirmed evidence exceeds the permitted inference span")
            _validate_high_temporal_evidence(
                claim, claim_path, claim_as_of, confirming, errors
            )
            if claim.get("conflicts") or any(
                item.get("support") == "conflict" for item, _, _ in usable_located
            ):
                _error(
                    errors,
                    "CONFIRMED_DESPITE_CONFLICT",
                    claim_path,
                    "confirmed status cannot ignore a registered or directly evidenced conflict",
                )

        if status == "partially_supported":
            partial_evidence = [
                triple
                for triple in substantive_partial
                if triple[0].get("support") in {"direct", "partial"}
                and _source_can_support_core(triple[1], claim)
                and triple[0].get("inference_span", 99) <= 2
            ]
            if not partial_evidence:
                _error(
                    errors,
                    "PARTIAL_WITHOUT_USABLE_EVIDENCE",
                    claim_path,
                    "partially supported status requires usable located evidence for the narrower supported scope",
                )
            decisive_evidence = partial_evidence
            if claim.get("source_identity_gate") != "pass":
                _error(
                    errors,
                    "PARTIAL_WITHOUT_PASSING_IDENTITY_GATE",
                    claim_path,
                    "partially supported status requires the source identity gate to pass",
                )
            if claim.get("content_support_gate") not in {"partial", "pass"}:
                _error(
                    errors,
                    "PARTIAL_WITHOUT_CONTENT_SUPPORT",
                    claim_path,
                    "partially supported status requires a partial or passing content support gate",
                )
            _validate_high_temporal_evidence(
                claim, claim_path, claim_as_of, partial_evidence, errors
            )
            if claim.get("conflicts") or any(
                item.get("support") == "conflict" for item, _, _ in usable_located
            ):
                _error(
                    errors,
                    "PARTIAL_DESPITE_UNRESOLVED_CONFLICT",
                    claim_path,
                    "partially supported cannot hide unresolved conflict in the same audited claim; split the narrower claim or remain unknown",
                )

        if status == "refuted":
            conflicts = claim.get("conflicts")
            conflict_candidates = [
                (item, source, receipt)
                for item, source, receipt in substantive_conflicts
                if item.get("support") == "conflict" and _source_can_support_core(source, claim)
            ]
            if any(item.get("inference_span", 99) > 1 for item, _, _ in conflict_candidates):
                _error(
                    errors,
                    "REFUTED_WITH_EXCESSIVE_INFERENCE",
                    claim_path,
                    "refutation evidence exceeds the permitted inference span",
                )
            direct_conflict = any(
                item.get("inference_span", 99) <= 1 for item, _, _ in conflict_candidates
            )
            decisive_evidence = conflict_candidates
            if not isinstance(conflicts, list) or not conflicts or not direct_conflict:
                _error(errors, "REFUTED_WITHOUT_CONFLICT", claim_path, "refuted status requires located direct conflict evidence")
            if claim.get("source_identity_gate") != "pass" or claim.get("content_support_gate") != "fail":
                _error(
                    errors,
                    "REFUTED_WITHOUT_PASSING_GATES",
                    claim_path,
                    "refuted status requires a passing source identity gate and failing content support gate",
                )
            direct_support = [
                triple
                for triple in substantive_direct
                if triple[0].get("support") == "direct"
                and _source_can_support_core(triple[1], claim)
                and triple[0].get("inference_span", 99) <= 1
            ]
            if direct_support:
                _error(
                    errors,
                    "REFUTED_DESPITE_DIRECT_SUPPORT",
                    claim_path,
                    "refuted status cannot ignore eligible direct support for the audited claim",
                )
            _validate_high_temporal_evidence(
                claim, claim_path, claim_as_of, conflict_candidates, errors
            )

        if claim.get("requires_independent_evidence") and status == "confirmed":
            independent = [
                (source, receipt)
                for item, source, receipt in substantive_direct
                if item.get("support") == "direct"
                and source.get("evidence_role") in INDEPENDENT_ROLES
                and _source_can_support_core(source, claim)
            ]
            unverified_origins = {
                source.get("origin_id")
                for source, _ in independent
                if not _origin_is_known(source.get("origin_id"))
            }
            if unverified_origins:
                _error(
                    errors,
                    "INDEPENDENT_ORIGIN_UNVERIFIED",
                    claim_path,
                    "caller-supplied origin labels without a recognized persistent identifier cannot establish independence",
                )
            independent_origins = {
                source.get("origin_id")
                for source, _ in independent
                if _origin_is_known(source.get("origin_id"))
            }
            if len(independent_origins) < 2:
                _error(errors, "INDEPENDENCE_NOT_ESTABLISHED", claim_path, "fewer than two independent evidence roots were established")
            if len(independent) >= 2 and (
                len({receipt.get("final_url") for _, receipt in independent}) < 2
                or len({receipt.get("content_sha256") for _, receipt in independent}) < 2
            ):
                _error(
                    errors,
                    "INDEPENDENT_TRANSPORT_ROOTS_NOT_ESTABLISHED",
                    claim_path,
                    "different origin labels resolve to the same final URL or identical saved content",
                )

        if claim.get("claim_type") == "causal" and status in {
            "confirmed",
            "partially_supported",
            "refuted",
        }:
            if claim.get("causal_basis") not in ALLOWED_CAUSAL_BASES:
                _error(errors, "CAUSALITY_NOT_ESTABLISHED", f"{claim_path}.causal_basis", "the recorded design cannot establish the proposed causal claim")
            design_evidence = [
                (item, source, receipt)
                for item, source, receipt in usable_located
                if item.get("support") == "direct"
                and item.get("evidence_purpose") == "study_design"
                and item.get("inference_span", 99) <= 1
            ]
            if not design_evidence:
                _error(
                    errors,
                    "CAUSAL_DESIGN_EVIDENCE_REQUIRED",
                    claim_path,
                    "a causal conclusion requires an exact opened-source excerpt identifying the eligible study design",
                )

        if claim.get("temporal_sensitivity") == "high" and status in CONFIRMING_STATUSES:
            currentness_evidence = [
                triple
                for triple in usable_located
                if triple[0].get("support") == "direct"
                and triple[0].get("evidence_purpose") == "currentness"
                and triple[0].get("inference_span", 99) <= 1
            ]
            if not currentness_evidence:
                _error(
                    errors,
                    "CURRENTNESS_EVIDENCE_REQUIRED",
                    claim_path,
                    "a time-sensitive decisive status requires an exact currentness excerpt or dated current record",
                )

        if status in CONFIRMING_STATUSES and decisive_evidence:
            required_purposes = [("source_identity", identity_evidence)]
            if claim.get("claim_type") == "causal":
                required_purposes.append(("study_design", design_evidence))
            if claim.get("temporal_sensitivity") == "high":
                required_purposes.append(("currentness", currentness_evidence))
            for purpose, purpose_items in required_purposes:
                if not _purpose_covers_decisive_records(
                    decisive_evidence, purpose_items
                ):
                    _error(
                        errors,
                        "SOURCE_PURPOSE_BINDING_MISMATCH",
                        f"{claim_path}.evidence",
                        f"{purpose} evidence must bind every decisive substantive source or verified record root",
                    )

        if claim.get("risk_domain") in HIGH_RISK_DOMAINS:
            if claim.get("action_applicability_gate") not in {"professional_review", "insufficient"}:
                _error(errors, "PROFESSIONAL_BOUNDARY_REQUIRED", f"{claim_path}.action_applicability_gate", "high-risk action applicability requires professional review or an insufficient-evidence boundary")

        criteria = claim.get("criteria")
        if not isinstance(criteria, dict) or criteria.get("defined") is not True:
            _warning(warnings, "CRITERIA_UNDEFINED", f"{claim_path}.criteria", "confirmation criteria were not explicitly defined")
        claim_unknowns = claim.get("unknowns")
        if (
            not isinstance(claim_unknowns, list)
            or not claim_unknowns
            or any(not isinstance(item, str) or not item.strip() for item in claim_unknowns)
        ):
            _error(
                errors,
                "CLAIM_UNKNOWNS_REQUIRED",
                f"{claim_path}.unknowns",
                "every assessed claim must state at least one current unknown or an explicit none statement",
            )
        if not isinstance(claim.get("confidence_reason"), str) or not claim.get(
            "confidence_reason", ""
        ).strip():
            _error(errors, "CONFIDENCE_REASON_REQUIRED", f"{claim_path}.confidence_reason", "confidence reason is required")
        if not isinstance(claim.get("next_step"), str) or not claim.get(
            "next_step", ""
        ).strip():
            _error(errors, "NEXT_STEP_REQUIRED", f"{claim_path}.next_step", "claim-level next action is required")

    for candidate_text in covered_candidate_texts:
        spans = sorted(claim_subspans.get(candidate_text, []))
        merged: list[tuple[int, int]] = []
        for start, end in spans:
            if not merged or start > merged[-1][1]:
                merged.append((start, end))
            else:
                merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        cursor = 0
        uncovered_parts: list[str] = []
        for start, end in merged:
            if cursor < start:
                uncovered_parts.append(candidate_text[cursor:start])
            cursor = max(cursor, end)
        if cursor < len(candidate_text):
            uncovered_parts.append(candidate_text[cursor:])
        uncovered = " ".join(uncovered_parts)
        if _candidate_remainder_is_meaningful(uncovered):
            _error(
                errors,
                "CANDIDATE_ATOMIC_COVERAGE_INCOMPLETE",
                "scope.candidate_inventory",
                "claim subspans leave meaningful candidate text unaudited: " + uncovered.strip(),
            )

    unreviewed = scope.get("unreviewed_claims", []) if isinstance(scope, dict) else []
    unreviewed_texts: set[str] = set()
    if not isinstance(unreviewed, list):
        _error(
            errors,
            "UNREVIEWED_CLAIMS_INVALID",
            "scope.unreviewed_claims",
            "unreviewed_claims must be a list",
        )
        unreviewed = []
    for index, candidate in enumerate(unreviewed):
        path = f"scope.unreviewed_claims[{index}]"
        if not isinstance(candidate, str) or not candidate:
            _error(
                errors,
                "UNREVIEWED_CANDIDATE_INVALID",
                path,
                "unreviewed candidate must be a non-empty frozen candidate string",
            )
            continue
        if candidate not in candidate_texts:
            _error(
                errors,
                "UNREVIEWED_CANDIDATE_NOT_FROZEN",
                path,
                "unreviewed candidate is absent from the frozen inventory",
            )
        if candidate in unreviewed_texts:
            _error(
                errors,
                "DUPLICATE_UNREVIEWED_CANDIDATE",
                path,
                "unreviewed candidate must be unique",
            )
        unreviewed_texts.add(candidate)

    excluded = scope.get("excluded_candidates", []) if isinstance(scope, dict) else []
    excluded_texts: set[str] = set()
    if not isinstance(excluded, list):
        _error(
            errors,
            "EXCLUDED_CANDIDATES_INVALID",
            "scope.excluded_candidates",
            "excluded_candidates must be a list",
        )
        excluded = []
    for index, item in enumerate(excluded):
        path = f"scope.excluded_candidates[{index}]"
        if not isinstance(item, dict):
            _error(errors, "EXCLUDED_CANDIDATE_INVALID", path, "exclusion must be an object")
            continue
        candidate = item.get("candidate")
        classification = item.get("classification")
        reason = item.get("reason")
        if not isinstance(candidate, str) or candidate not in candidate_texts:
            _error(
                errors,
                "EXCLUDED_CANDIDATE_NOT_FROZEN",
                f"{path}.candidate",
                "excluded candidate must resolve to the frozen inventory",
            )
            continue
        if candidate in excluded_texts:
            _error(
                errors,
                "DUPLICATE_EXCLUDED_CANDIDATE",
                f"{path}.candidate",
                "candidate may be excluded only once",
            )
        excluded_texts.add(candidate)
        if candidate_origins.get(candidate) != "auto_gap":
            _error(
                errors,
                "EXCLUSION_ORIGIN_FORBIDDEN",
                f"{path}.candidate",
                "only runtime-discovered auto_gap candidates may be excluded",
            )
        if classification not in ALLOWED_EXCLUSION_CLASSES:
            _error(
                errors,
                "EXCLUSION_CLASS_INVALID",
                f"{path}.classification",
                "exclusion classification is not allowed",
            )
        if not isinstance(reason, str) or not reason.strip():
            _error(
                errors,
                "EXCLUSION_REASON_REQUIRED",
                f"{path}.reason",
                "excluded candidate requires a non-empty audit reason",
            )
        if parse_iso_datetime(item.get("excluded_at")) is None:
            _error(
                errors,
                "EXCLUSION_TIME_INVALID",
                f"{path}.excluded_at",
                "excluded candidate requires a timezone-aware timestamp",
            )

    dispositions = {
        "unreviewed": unreviewed_texts,
        "covered": covered_candidate_texts,
        "excluded": excluded_texts,
    }
    for candidate in candidate_texts:
        memberships = [name for name, values in dispositions.items() if candidate in values]
        if not memberships:
            _error(
                errors,
                "CANDIDATE_DISPOSITION_MISSING",
                "scope.candidate_inventory",
                f"frozen candidate has no review disposition: {candidate}",
            )
        elif len(memberships) > 1:
            _error(
                errors,
                "CANDIDATE_DISPOSITION_CONFLICT",
                "scope",
                f"candidate appears in multiple dispositions ({', '.join(memberships)}): {candidate}",
            )
    if scope.get("triggered") is True and not claims:
        _error(
            errors,
            "NO_CLAIMS_RECORDED",
            "claims",
            "a triggered audit must record at least one atomic claim",
        )
    if scope.get("triggered") is True and scope.get("candidate_inventory_recorded") is not True:
        _error(
            errors,
            "CANDIDATE_INVENTORY_REQUIRED",
            "scope.candidate_inventory_recorded",
            "a triggered audit must freeze its candidate factual clauses before evidence collection",
        )
    if scope.get("triggered") is True and unreviewed:
        _error(
            errors,
            "UNREVIEWED_CLAIMS_BLOCK_COMPLETION",
            "scope.unreviewed_claims",
            "candidate claims remain outside the completed ledger",
        )
    if scope.get("triggered") is True and claims:
        if ledger.get("summary_recorded") is not True:
            _error(
                errors,
                "AUDIT_SUMMARY_REQUIRED",
                "summary_recorded",
                "multi-claim or mutated audits require an explicit current unknowns and next-action summary",
            )
        unknowns = ledger.get("unknowns")
        if (
            not isinstance(unknowns, list)
            or not unknowns
            or any(not isinstance(item, str) or not item.strip() for item in unknowns)
        ):
            _error(
                errors,
                "GLOBAL_UNKNOWNS_REQUIRED",
                "unknowns",
                "a completed audit must explicitly record current unknowns, including an explicit none statement",
            )
        next_action = ledger.get("next_action")
        if not isinstance(next_action, str) or not next_action.strip():
            _error(
                errors,
                "GLOBAL_NEXT_ACTION_REQUIRED",
                "next_action",
                "a completed audit must explicitly record the highest-value next action",
            )

    return {
        "gate_version": POLICY_VERSION,
        "checked_at": utc_now(),
        "verdict": "FAIL" if errors else "PASS",
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "claims": len(claims),
            "sources": len(sources),
            "receipts": len(receipts),
        },
    }


def _workspace_manifest(
    workspace: Path,
    ledger: dict[str, Any],
    receipts: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    input_info = ledger.get("input") if isinstance(ledger.get("input"), dict) else {}
    input_relative = input_info.get("path")
    input_sha256 = "missing"
    if isinstance(input_relative, str) and input_relative:
        try:
            input_path = safe_workspace_path(workspace, input_relative)
            if input_path.is_file():
                input_sha256 = sha256_file(input_path)
        except AuditError:
            input_sha256 = "invalid-path"
    manifest: dict[str, Any] = {
        "runtime_version": RUNTIME_VERSION,
        "policy_version": POLICY_VERSION,
        "input_sha256": input_sha256,
        "ledger_sha256": sha256_file(safe_workspace_path(workspace, "ledger.json")),
        "runtime_attestations_sha256": (
            sha256_file(
                safe_workspace_path(workspace, "runtime-attestations.json")
            )
            if safe_workspace_path(
                workspace, "runtime-attestations.json"
            ).is_file()
            else "missing"
        ),
        "receipts": {},
        "artifacts": {},
        "source_transactions": {},
    }
    transaction_root = safe_workspace_path(workspace, "source-transactions")
    if transaction_root.is_dir():
        for transaction_path in sorted(transaction_root.iterdir()):
            if transaction_path.is_file() and transaction_path.suffix == ".json":
                manifest["source_transactions"][transaction_path.name] = sha256_file(
                    transaction_path
                )
    for source in ledger.get("sources", []):
        if not isinstance(source, dict) or not source.get("source_id"):
            continue
        source_id = source["source_id"]
        receipt_path = source.get("receipt")
        if receipt_path:
            resolved_receipt = safe_workspace_path(workspace, receipt_path)
            manifest["receipts"][source_id] = (
                sha256_file(resolved_receipt) if resolved_receipt.is_file() else "missing"
            )
        receipt = receipts.get(source_id, {})
        for field in ("artifact", "parsed_text"):
            relative = receipt.get(field)
            if not relative:
                continue
            resolved = safe_workspace_path(workspace, relative)
            manifest["artifacts"][relative] = sha256_file(resolved) if resolved.is_file() else "missing"
    return manifest


def compute_workspace_manifest_sha256(workspace: Path | str) -> str:
    root = Path(workspace).resolve()
    ledger, receipts = _load_workspace(root)
    return compute_manifest_sha256(_workspace_manifest(root, ledger, receipts))


def validate_workspace(workspace: Path | str) -> dict[str, Any]:
    """Replay receipts, saved artifacts, and exact-quote selectors in a workspace."""
    root = Path(workspace).resolve()
    ledger, receipts = _load_workspace(root)
    gate = validate_bundle(ledger, receipts)
    errors = gate["errors"]
    warnings = gate["warnings"]

    transaction_root = safe_workspace_path(root, "source-transactions")
    ledger_sources = {
        source.get("source_id"): source
        for source in ledger.get("sources", [])
        if isinstance(source, dict) and isinstance(source.get("source_id"), str)
    }
    if transaction_root.exists() and not transaction_root.is_dir():
        _error(
            errors,
            "SOURCE_TRANSACTION_STORE_INVALID",
            "source-transactions",
            "source transaction store must be a directory",
        )
    elif transaction_root.is_dir():
        for transaction_path in sorted(transaction_root.iterdir()):
            relative_path = f"source-transactions/{transaction_path.name}"
            if not transaction_path.is_file() or transaction_path.suffix != ".json":
                _error(
                    errors,
                    "SOURCE_TRANSACTION_FILE_INVALID",
                    relative_path,
                    "source transaction store contains an unexpected entry",
                )
                continue
            try:
                transaction = _read_json(transaction_path)
            except AuditError as exc:
                _error(
                    errors,
                    "SOURCE_TRANSACTION_INVALID",
                    relative_path,
                    str(exc),
                )
                continue
            source_id = transaction.get("source_id")
            expected_name = f"{source_id}.json" if isinstance(source_id, str) else None
            if (
                transaction.get("transaction_version") != "1.0"
                or expected_name != transaction_path.name
                or transaction.get("status")
                not in ALLOWED_SOURCE_TRANSACTION_STATUSES
                or not isinstance(transaction.get("source_record"), dict)
                or not isinstance(transaction.get("receipt_snapshot"), dict)
            ):
                _error(
                    errors,
                    "SOURCE_TRANSACTION_INVALID",
                    relative_path,
                    "source transaction journal fields or filename are invalid",
                )
                continue
            snapshot = transaction["receipt_snapshot"]
            if (
                snapshot.get("source_id") != source_id
                or snapshot.get("receipt_sha256") != transaction.get("receipt_sha256")
                or compute_receipt_sha256(snapshot) != transaction.get("receipt_sha256")
            ):
                _error(
                    errors,
                    "SOURCE_TRANSACTION_RECEIPT_MISMATCH",
                    relative_path,
                    "source transaction receipt snapshot no longer matches its frozen hash",
                )
            status = transaction.get("status")
            if status == "aborted":
                abort_reason = transaction.get("abort_reason")
                aborted_at = parse_iso_datetime(transaction.get("aborted_at"))
                if (
                    not isinstance(abort_reason, str)
                    or not abort_reason.strip()
                    or len(abort_reason.encode("utf-8")) > MAX_ABORT_REASON
                    or aborted_at is None
                ):
                    _error(
                        errors,
                        "SOURCE_TRANSACTION_ABORT_INVALID",
                        relative_path,
                        "aborted source transaction requires a bounded reason and valid timestamp",
                    )
                if source_id in ledger_sources:
                    _error(
                        errors,
                        "SOURCE_TRANSACTION_ABORT_LEDGER_CONFLICT",
                        relative_path,
                        "an aborted transaction cannot retain a registered ledger source",
                    )
                for artifact_field, hash_field in (
                    ("artifact", "content_sha256"),
                    ("parsed_text", "parsed_text_sha256"),
                ):
                    artifact_rel = snapshot.get(artifact_field)
                    if not artifact_rel:
                        continue
                    try:
                        artifact_path = safe_workspace_path(root, artifact_rel)
                    except AuditError:
                        _error(
                            errors,
                            "SOURCE_TRANSACTION_ABORT_ARTIFACT_INVALID",
                            relative_path,
                            f"aborted transaction contains an invalid {artifact_field} path",
                        )
                        continue
                    if artifact_path.exists() and (
                        not artifact_path.is_file()
                        or sha256_file(artifact_path) != snapshot.get(hash_field)
                    ):
                        _error(
                            errors,
                            "SOURCE_TRANSACTION_ABORT_ARTIFACT_MISMATCH",
                            relative_path,
                            f"preserved aborted {artifact_field} no longer matches its snapshot",
                        )
                receipt_path = safe_workspace_path(root, f"receipts/{source_id}.json")
                if receipt_path.exists():
                    try:
                        saved_receipt = _read_json(receipt_path)
                    except AuditError:
                        saved_receipt = None
                    if saved_receipt != snapshot:
                        _error(
                            errors,
                            "SOURCE_TRANSACTION_ABORT_RECEIPT_MISMATCH",
                            relative_path,
                            "preserved aborted receipt no longer matches its snapshot",
                        )
                _warning(
                    warnings,
                    "SOURCE_TRANSACTION_ABORTED",
                    relative_path,
                    "source acquisition was explicitly closed without ledger registration; the failure trace is preserved",
                )
                continue
            if status != "committed":
                _error(
                    errors,
                    "SOURCE_TRANSACTION_INCOMPLETE",
                    relative_path,
                    "source collection stopped before ledger commit; retry the exact source command or explicitly abort the transaction if reproduction is impossible",
                )
                continue
            ledger_source = ledger_sources.get(source_id)
            frozen_source = transaction.get("source_record")
            stable_source_fields = (
                "source_id",
                "receipt",
                "source_tier",
                "evidence_role",
                "publication_date",
                "freshness_status",
                "freshness_rationale",
                "origin_id",
            )
            if not isinstance(ledger_source, dict) or any(
                ledger_source.get(field) != frozen_source.get(field)
                for field in stable_source_fields
            ):
                _error(
                    errors,
                    "SOURCE_TRANSACTION_LEDGER_MISMATCH",
                    relative_path,
                    "committed source transaction does not match exactly one ledger source",
                )
            receipt_path = safe_workspace_path(root, f"receipts/{source_id}.json")
            try:
                saved_receipt = _read_json(receipt_path)
            except AuditError:
                saved_receipt = None
            if saved_receipt != snapshot:
                _error(
                    errors,
                    "SOURCE_TRANSACTION_SAVED_RECEIPT_MISMATCH",
                    relative_path,
                    "committed source transaction does not match the saved receipt",
                )

    input_info = ledger.get("input") if isinstance(ledger.get("input"), dict) else {}
    input_relative = input_info.get("path")
    expected_input_sha256 = input_info.get("sha256")
    try:
        if not isinstance(input_relative, str) or not input_relative:
            raise AuditError("input path is missing")
        input_path = safe_workspace_path(root, input_relative)
        actual_input_sha256 = sha256_file(input_path)
        input_text = input_path.read_text(encoding="utf-8")
    except (AuditError, FileNotFoundError):
        actual_input_sha256 = "missing"
        input_text = ""
    except UnicodeDecodeError:
        actual_input_sha256 = "invalid-utf8"
        input_text = ""
    if actual_input_sha256 != expected_input_sha256:
        _error(
            errors,
            "INPUT_HASH_MISMATCH",
            "input",
            "saved audit input does not match the hash frozen at initialization",
        )

    scope = ledger.get("scope") if isinstance(ledger.get("scope"), dict) else {}
    inventory = scope.get("candidate_inventory")
    if isinstance(inventory, list):
        for index, candidate in enumerate(inventory):
            if not isinstance(candidate, dict):
                continue
            text = candidate.get("text")
            spans = candidate.get("spans")
            if not isinstance(text, str) or not isinstance(spans, list):
                continue
            expected_spans: list[dict[str, int]] = []
            cursor = 0
            while True:
                start = input_text.find(text, cursor)
                if start < 0:
                    break
                expected_spans.append({"start": start, "end": start + len(text)})
                cursor = start + max(1, len(text))
            if spans != expected_spans or not expected_spans:
                _error(
                    errors,
                    "CANDIDATE_INPUT_BINDING_MISMATCH",
                    f"scope.candidate_inventory[{index}]",
                    "candidate selectors no longer resolve to the frozen original input",
                )

    for source_id, receipt in receipts.items():
        if receipt.get("acquisition_type") == "runtime_fetch" and not runtime_receipt_is_attested(
            root, ledger.get("audit_id"), receipt
        ):
            _error(
                errors,
                "RECEIPT_PROVENANCE_UNATTESTED",
                f"receipts.{source_id}",
                "runtime_fetch receipt lacks a valid workspace runtime provenance attestation",
            )
        artifact = receipt.get("artifact")
        if artifact:
            try:
                artifact_path = safe_workspace_path(root, artifact)
                actual = sha256_file(artifact_path)
                actual_bytes = artifact_path.stat().st_size
            except (AuditError, FileNotFoundError):
                actual = "missing"
                actual_bytes = -1
            if actual != receipt.get("content_sha256"):
                _error(
                    errors,
                    "ARTIFACT_HASH_MISMATCH",
                    f"receipts.{source_id}.artifact",
                    "saved source bytes do not match the receipt",
                )
            if actual_bytes != receipt.get("bytes_read"):
                _error(
                    errors,
                    "ARTIFACT_SIZE_MISMATCH",
                    f"receipts.{source_id}.bytes_read",
                    "saved source byte count does not match the receipt",
                )

        parsed_text = receipt.get("parsed_text")
        if parsed_text:
            try:
                parsed_path = safe_workspace_path(root, parsed_text)
                actual = sha256_file(parsed_path)
            except (AuditError, FileNotFoundError):
                actual = "missing"
            if actual != receipt.get("parsed_text_sha256"):
                _error(
                    errors,
                    "PARSED_TEXT_HASH_MISMATCH",
                    f"receipts.{source_id}.parsed_text",
                    "saved parsed text does not match the receipt",
                )

    for claim_index, claim in enumerate(ledger.get("claims", [])):
        if not isinstance(claim, dict):
            continue
        for evidence_index, evidence in enumerate(claim.get("evidence", [])):
            if not isinstance(evidence, dict) or evidence.get("support") not in {"direct", "partial", "conflict"}:
                continue
            source_id = evidence.get("source_id")
            receipt = receipts.get(source_id, {})
            parsed_rel = receipt.get("parsed_text")
            selector = evidence.get("selector")
            evidence_path = f"claims[{claim_index}].evidence[{evidence_index}]"
            if receipt.get("acquisition_type") == "runtime_fetch" and not isinstance(selector, dict):
                _error(
                    errors,
                    "QUOTE_SELECTOR_REQUIRED",
                    f"{evidence_path}.selector",
                    "runtime-fetched text evidence requires a reproducible character selector",
                )
                continue
            if not parsed_rel or not isinstance(selector, dict):
                continue
            try:
                parsed_bytes = safe_workspace_path(root, parsed_rel).read_bytes()
                parsed = parsed_bytes.decode("utf-8")
                start = selector.get("start")
                end = selector.get("end")
                if type(start) is not int or type(end) is not int or start < 0 or end < start:
                    raise AuditError("selector bounds are invalid")
                selected = parsed[start:end]
                quote_hash = sha256_bytes(selected.encode("utf-8"))
                if (
                    selected != evidence.get("excerpt")
                    or quote_hash != selector.get("quote_sha256")
                ):
                    raise AuditError("selector does not reproduce the recorded excerpt")
            except (AuditError, FileNotFoundError, UnicodeDecodeError):
                _error(
                    errors,
                    "QUOTE_MISMATCH",
                    evidence_path,
                    "the saved text selector does not reproduce the recorded quotation",
                )

    gate["verdict"] = "FAIL" if errors else "PASS"
    gate["bundle_sha256"] = compute_manifest_sha256(_workspace_manifest(root, ledger, receipts))
    return gate


def _md(value: Any) -> str:
    rendered = "" if value is None else str(value)
    rendered = (
        rendered.replace("\\", "\\\\")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", "\\|")
        .replace("\r", " ")
        .replace("\n", " ")
    )
    for character in ("`", "[", "]", "(", ")", "!", "~"):
        rendered = rendered.replace(character, "\\" + character)
    return rendered


def _source_label(source: dict[str, Any], receipt: dict[str, Any] | None) -> str:
    if not receipt:
        return _md(source.get("source_id", ""))
    target = str(receipt.get("final_url") or "")
    target = (
        target.replace("\\", "%5C")
        .replace(" ", "%20")
        .replace("(", "%28")
        .replace(")", "%29")
        .replace("<", "%3C")
        .replace(">", "%3E")
    )
    if not target:
        return _md(source.get("source_id", ""))
    return f"[{_md(source.get('source_id'))}]({target})"


def render_markdown(
    ledger: dict[str, Any],
    receipts: dict[str, dict[str, Any]],
    gate: dict[str, Any],
) -> str:
    if gate.get("verdict") != "PASS":
        raise AuditError("validation failed; final report rendering is blocked")

    scope = ledger.get("scope", {})
    if scope.get("triggered") is False:
        return (
            "# AI 主张审计\n\n"
            "结论：不触发事实审计。\n\n"
            f"原因：{scope.get('reason') or '输入不包含需要核验的外部事实主张。'}\n"
        )

    sources = {source.get("source_id"): source for source in ledger.get("sources", [])}
    lines = [
        "# AI 主张审计",
        "",
        "## 主张账本",
        "",
        "| ID | 原子主张 | 状态 | 关键理由 | 当前未知 | 下一步 |",
        "|---|---|---|---|---|---|",
    ]
    for claim in ledger.get("claims", []):
        evidence = claim.get("evidence", [])
        labels = []
        seen_source_ids = set()
        direct = []
        scopes = []
        spans = []
        for item in evidence:
            source_id = item.get("source_id")
            source = sources.get(source_id, {"source_id": source_id})
            if source_id not in seen_source_ids:
                labels.append(_source_label(source, receipts.get(source_id)))
                seen_source_ids.add(source_id)
            direct.append(item.get("support", "unknown"))
            if item.get("support_scope"):
                scopes.append(item["support_scope"])
            if item.get("inference_span") is not None:
                spans.append(str(item["inference_span"]))
        conflicts = claim.get("conflicts") or []
        gates = (
            f"来源身份门={claim.get('source_identity_gate', 'unknown')}；"
            f"内容支持门={claim.get('content_support_gate', 'unknown')}；"
            f"行动适用门={claim.get('action_applicability_gate', 'unknown')}"
        )
        status = claim.get("status")
        status_label = f"{STATUS_LABELS.get(status, status)} ({status})"
        linked_conflicts = [
            item.get("support_scope") or item.get("excerpt")
            for item in evidence
            if item.get("support") == "conflict"
        ]
        all_conflicts = [*map(str, conflicts), *filter(None, linked_conflicts)]
        reason_parts = []
        if labels:
            reason_parts.append("证据：" + ", ".join(labels))
        if scopes:
            reason_parts.append("支持范围：" + _md("; ".join(scopes)))
        if all_conflicts:
            reason_parts.append("冲突：" + _md("; ".join(all_conflicts)))
        countercheck = claim.get("countercheck") or {}
        if countercheck:
            reason_parts.append(
                "反证："
                + _md(
                    f"{countercheck.get('result', '未记录')}；{countercheck.get('stop_reason', '未记录')}"
                )
            )
        reason_parts.append(_md(claim.get("confidence_reason") or "未记录"))
        lines.append(
            "| "
            + " | ".join(
                (
                    _md(claim.get("claim_id")),
                    _md(claim.get("text")),
                    _md(status_label),
                    "；".join(reason_parts),
                    _md("; ".join(claim.get("unknowns") or []) or "未记录"),
                    _md(claim.get("next_step")),
                )
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## 审计元数据",
            "",
            f"审计 ID：{_md(ledger.get('audit_id', '未记录'))}",
            "",
            f"核验日期：{ledger.get('verification_date', '未记录')}",
            "",
            "运行时结构门：PASS",
            "",
            f"证据 bundle SHA-256：{_md(gate.get('bundle_sha256') or '未记录')}",
            "",
            f"运行时版本：{RUNTIME_VERSION}；Policy 版本：{POLICY_VERSION}",
            "",
            "说明：PASS 只表示已声明账本满足结构、回执与完整性门，不表示程序自动证明了事实语义。",
        ]
    )

    lines.extend(
        [
            "",
            "## 技术账本",
            "",
            "| ID | 候选覆盖 | 类型 | 时效性 | 来源 | 支持 | 支持范围 | 推断跨度 | 三道门 | 冲突 | 因果依据 | 状态 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for claim in ledger.get("claims", []):
        evidence = claim.get("evidence", [])
        labels = []
        seen_source_ids = set()
        supports = []
        scopes = []
        spans = []
        linked_conflicts = []
        for item in evidence:
            source_id = item.get("source_id")
            source = sources.get(source_id, {"source_id": source_id})
            if source_id not in seen_source_ids:
                labels.append(_source_label(source, receipts.get(source_id)))
                seen_source_ids.add(source_id)
            supports.append(
                f"{item.get('support', 'unknown')}:{item.get('evidence_purpose', 'substantive')}"
            )
            if item.get("support_scope"):
                scopes.append(item["support_scope"])
            if item.get("inference_span") is not None:
                spans.append(str(item["inference_span"]))
            if item.get("support") == "conflict":
                linked_conflicts.append(item.get("support_scope") or item.get("excerpt"))
        conflicts = [*map(str, claim.get("conflicts") or []), *filter(None, linked_conflicts)]
        gates = (
            f"来源身份门={claim.get('source_identity_gate', 'unknown')}；"
            f"内容支持门={claim.get('content_support_gate', 'unknown')}；"
            f"行动适用门={claim.get('action_applicability_gate', 'unknown')}"
        )
        status = claim.get("status")
        status_label = f"{STATUS_LABELS.get(status, status)} ({status})"
        lines.append(
            "| "
            + " | ".join(
                (
                    _md(claim.get("claim_id")),
                    _md("; ".join(claim.get("input_candidates") or []) or "未记录"),
                    _md(claim.get("claim_type")),
                    _md(claim.get("temporal_sensitivity")),
                    ", ".join(labels) or "无",
                    _md(", ".join(supports) or "无"),
                    _md("; ".join(scopes) or "未建立"),
                    _md(", ".join(spans) or "未记录"),
                    _md(gates),
                    _md("; ".join(conflicts) or "无"),
                    _md(claim.get("causal_basis") or "not_applicable"),
                    _md(status_label),
                )
            )
            + " |"
        )

    lines.extend(
        [
            "",
            "## 反证检查",
            "",
            "| 主张 | 可推翻条件 | 已检查来源 | 结果 | 停止理由 | 检查时间 | 基线哈希 |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for claim in ledger.get("claims", []):
        countercheck = claim.get("countercheck") or {}
        lines.append(
            "| "
            + " | ".join(
                (
                    _md(claim.get("claim_id")),
                    _md(countercheck.get("falsifier") or "未记录"),
                    _md(", ".join(countercheck.get("checked_source_ids") or []) or "无"),
                    _md(countercheck.get("result") or "未记录"),
                    _md(countercheck.get("stop_reason") or "未记录"),
                    _md(countercheck.get("checked_at") or "未记录"),
                    _md(countercheck.get("basis_hash") or "未记录"),
                )
            )
            + " |"
        )

    excluded = scope.get("excluded_candidates", [])
    lines.extend(["", "## 审计排除项", ""])
    if isinstance(excluded, list) and excluded:
        inventory_by_text = {
            item.get("text"): item
            for item in scope.get("candidate_inventory", [])
            if isinstance(item, dict)
        }
        lines.extend(
            [
                "| 原文片段 | 分类 | 排除理由 | 来源 | 原文位置 | 排除时间 |",
                "|---|---|---|---|---|---|",
            ]
        )
        for item in excluded:
            candidate = item.get("candidate")
            binding = inventory_by_text.get(candidate, {})
            spans = ", ".join(
                f"{span.get('start')}:{span.get('end')}"
                for span in binding.get("spans", [])
                if isinstance(span, dict)
            )
            lines.append(
                "| "
                + " | ".join(
                    (
                        _md(candidate),
                        _md(item.get("classification")),
                        _md(item.get("reason")),
                        _md(binding.get("origin", "unknown")),
                        _md(spans or "未记录"),
                        _md(item.get("excluded_at")),
                    )
                )
                + " |"
            )
    else:
        lines.append("无。")

    lines.extend(["", "## 来源回执", ""])
    if receipts:
        lines.extend(
            [
                "| 来源 | 层级 | 证据角色 | 来源日期 | 当前性 | 新鲜度理由 | 可用于支持 | 获取方式 | 传输声明 | 获取说明 | 最终 URL | 访问时间 | HTTP | 内容哈希 | 回执哈希 |",
                "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
            ]
        )
        for source_id in sorted(receipts):
            receipt = receipts[source_id]
            source = sources.get(source_id, {})
            support_eligible = receipt.get("support_eligible")
            eligibility_label = (
                "是"
                if support_eligible is True
                else "否"
                if support_eligible is False
                else "未记录"
            )
            acquisition_note = (
                receipt.get("fetch_error")
                or receipt.get("error")
                or receipt.get("ineligibility_reason")
                or ("成功" if support_eligible is not False else "未记录失败原因")
            )
            source_link = _source_label(
                source or {"source_id": source_id}, receipt
            )
            final_url_link = (
                f"[打开原文]({str(receipt.get('final_url')).replace(' ', '%20').replace('(', '%28').replace(')', '%29')})"
                if receipt.get("final_url")
                else "未记录"
            )
            lines.append(
                "| "
                + " | ".join(
                    (
                        source_link,
                        _md(source.get("source_tier")),
                        _md(source.get("evidence_role")),
                        _md(source.get("publication_date")),
                        _md(source.get("freshness_status", "未记录")),
                        _md(source.get("freshness_rationale", "未记录")),
                        _md(eligibility_label),
                        _md(receipt.get("acquisition_type", "未记录")),
                        _md(receipt.get("transport_attestation", "未记录")),
                        _md(acquisition_note),
                        final_url_link,
                        _md(receipt.get("accessed_at")),
                        _md(receipt.get("http_status")),
                        _md(receipt.get("content_sha256")),
                        _md(receipt.get("receipt_sha256")),
                    )
                )
                + " |"
            )
    else:
        lines.append("无来源回执。")

    lines.extend(["", "## 证据附录", ""])
    evidence_rows = 0
    lines.extend(
        [
            "| 主张 | 来源 | 支持关系 | 精确引文 | 定位 | 选择器哈希 | 支持范围 | 推断跨度 | 获取方式 | 可用于硬门 |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
    )
    for claim in ledger.get("claims", []):
        for item in claim.get("evidence", []):
            source_id = item.get("source_id")
            receipt = receipts.get(source_id, {})
            source = sources.get(source_id, {"source_id": source_id})
            evidence_rows += 1
            lines.append(
                "| "
                + " | ".join(
                    (
                        _md(claim.get("claim_id")),
                        _source_label(source, receipt),
                        _md(
                            f"{item.get('support')}:{item.get('evidence_purpose', 'substantive')}"
                        ),
                        _md(item.get("excerpt") or "未记录"),
                        _md(item.get("locator") or "未记录"),
                        _md((item.get("selector") or {}).get("quote_sha256", "未记录")),
                        _md(item.get("support_scope") or "未记录"),
                        _md(item.get("inference_span")),
                        _md(receipt.get("acquisition_type", "未记录")),
                        "是" if _receipt_is_usable(receipt) else "否",
                    )
                )
                + " |"
            )
    if evidence_rows == 0:
        lines.append("| 无 | 无 | 无 | 无 | 无 | 无 | 无 | 无 | 无 | 否 |")

    lines.extend(["", "## Gate 警告", ""])
    warnings = gate.get("warnings") or []
    if warnings:
        lines.extend(
            f"- `{_md(item.get('code', 'WARNING'))}` {_md(item.get('path', ''))}: {_md(item.get('message', ''))}"
            for item in warnings
        )
    else:
        lines.append("无。")

    unknowns = ledger.get("unknowns") or ["未记录"]
    lines.extend(["", "## 当前未知", ""])
    lines.extend(f"- {_md(item)}" for item in unknowns)
    lines.extend(
        [
            "",
            "## 最有效的下一步",
            "",
            _md(ledger.get("next_action") or "未记录"),
            "",
            "## 边界",
            "",
            "本报告证明已声明账本、回执和结构性门槛在核验时一致。原子主张是否遗漏、来源角色是否标对、引文是否支持转述，仍需语义审查；本地哈希证明工件未变，不证明发布者天然可信。",
            "",
        ]
    )
    return "\n".join(lines)


def _write_private_bytes(path: Path, payload: bytes) -> None:
    """Atomically persist a workspace artifact with owner-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _write_private_text(path: Path, value: str) -> None:
    _write_private_bytes(path, value.encode("utf-8"))


def _write_new_private_bytes(path: Path, payload: bytes) -> None:
    """Atomically create, but never replace, a source-owned artifact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary_path, path, follow_symlinks=False)
        except FileExistsError as exc:
            raise AuditError(f"source artifact already exists: {path.name}") from exc
        os.chmod(path, 0o600)
        temporary_path.unlink()
        temporary_path = None
    except Exception:
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _write_new_or_verify_private_bytes(path: Path, payload: bytes) -> None:
    """Create an immutable source artifact or verify an identical retry."""

    if path.exists():
        if not path.is_file() or sha256_file(path) != sha256_bytes(payload):
            raise AuditError(f"source artifact conflicts with transaction retry: {path.name}")
        return
    _write_new_private_bytes(path, payload)


def _write_json(path: Path, value: Any) -> None:
    _write_private_text(
        path,
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
    )


def _write_new_json(path: Path, value: Any) -> None:
    _write_new_private_bytes(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def initialize_runtime_attestations(workspace: Path, audit_id: str) -> None:
    """Create a workspace-local provenance key and empty receipt registry.

    This detects caller-authored receipts and ordinary file tampering. The key
    lives on the same host, so it is not an external signature and does not
    protect against a process that can read the key and deliberately forge a
    new MAC.
    """

    if not isinstance(audit_id, str) or not audit_id:
        raise AuditError("audit_id is required for runtime attestation")
    _write_new_private_bytes(
        safe_workspace_path(workspace, ".runtime-key"), os.urandom(32)
    )
    _write_new_json(
        safe_workspace_path(workspace, "runtime-attestations.json"),
        {
            "attestation_version": ATTESTATION_VERSION,
            "audit_id": audit_id,
            "receipts": {},
        },
    )


def _attestation_key(workspace: Path) -> bytes:
    path = safe_workspace_path(workspace, ".runtime-key")
    try:
        key = path.read_bytes()
    except FileNotFoundError as exc:
        raise AuditError("runtime attestation key is missing") from exc
    if len(key) != 32:
        raise AuditError("runtime attestation key is invalid")
    return key


def _attestation_payload(
    audit_id: str, receipt: dict[str, Any], issued_at: str
) -> dict[str, Any]:
    return {
        "attestation_version": ATTESTATION_VERSION,
        "audit_id": audit_id,
        "source_id": receipt.get("source_id"),
        "receipt_sha256": receipt.get("receipt_sha256"),
        "content_sha256": receipt.get("content_sha256"),
        "parsed_text_sha256": receipt.get("parsed_text_sha256"),
        "acquisition_type": receipt.get("acquisition_type"),
        "issued_at": issued_at,
    }


def attest_runtime_receipt(
    workspace: Path, audit_id: str, receipt: dict[str, Any]
) -> None:
    """Bind a runtime-created receipt to the workspace provenance registry."""

    source_id = validate_source_id(receipt.get("source_id"))
    store_path = safe_workspace_path(workspace, "runtime-attestations.json")
    store = _read_json(store_path)
    if (
        store.get("attestation_version") != ATTESTATION_VERSION
        or store.get("audit_id") != audit_id
        or not isinstance(store.get("receipts"), dict)
    ):
        raise AuditError("runtime attestation registry is invalid")
    if source_id in store["receipts"]:
        if runtime_receipt_is_attested(workspace, audit_id, receipt):
            return
        raise AuditError(f"runtime receipt attestation conflicts with retry: {source_id}")
    issued_at = utc_now()
    payload = _attestation_payload(audit_id, receipt, issued_at)
    record = dict(payload)
    record["hmac_sha256"] = hmac.new(
        _attestation_key(workspace), canonical_json(payload), hashlib.sha256
    ).hexdigest()
    store["receipts"][source_id] = record
    _write_json(store_path, store)


def runtime_receipt_is_attested(
    workspace: Path, audit_id: Any, receipt: dict[str, Any]
) -> bool:
    """Verify the workspace-local provenance MAC for one runtime receipt."""

    if not isinstance(audit_id, str) or not audit_id:
        return False
    source_id = receipt.get("source_id")
    if not isinstance(source_id, str):
        return False
    try:
        store = _read_json(
            safe_workspace_path(workspace, "runtime-attestations.json")
        )
        if (
            store.get("attestation_version") != ATTESTATION_VERSION
            or store.get("audit_id") != audit_id
            or not isinstance(store.get("receipts"), dict)
        ):
            return False
        record = store["receipts"].get(source_id)
        if not isinstance(record, dict):
            return False
        issued_at = record.get("issued_at")
        if parse_iso_datetime(issued_at) is None:
            return False
        payload = _attestation_payload(audit_id, receipt, issued_at)
        expected_record = dict(payload)
        expected_record["hmac_sha256"] = hmac.new(
            _attestation_key(workspace), canonical_json(payload), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(
            canonical_json(record), canonical_json(expected_record)
        )
    except (AuditError, KeyError, OSError):
        return False


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise AuditError(f"required file is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise AuditError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AuditError(f"expected JSON object in {path}")
    return value


def _append_event(workspace: Path, event: str, details: dict[str, Any] | None = None) -> None:
    record = {"at": utc_now(), "event": event, "details": details or {}}
    event_path = safe_workspace_path(workspace, "events.jsonl")
    descriptor = os.open(event_path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.fchmod(descriptor, 0o600)
        os.write(
            descriptor,
            (json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"),
        )
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _archive_report_pointer(state: dict[str, Any]) -> None:
    report = state.get("report")
    report_sha256 = state.get("report_sha256")
    if isinstance(report, str) and isinstance(report_sha256, str):
        archived = {
            "report": report,
            "report_sha256": report_sha256,
            "report_bundle_sha256": state.get("report_bundle_sha256"),
            "staled_at": utc_now(),
        }
        stale_reports = state.setdefault("stale_reports", [])
        if not stale_reports or any(
            stale_reports[-1].get(field) != archived.get(field)
            for field in ("report", "report_sha256", "report_bundle_sha256")
        ):
            stale_reports.append(archived)
    state.pop("report", None)
    state.pop("report_sha256", None)
    state.pop("report_bundle_sha256", None)


def _gate_integrity_status(workspace: Path, state: dict[str, Any]) -> str:
    gate_path = safe_workspace_path(workspace, "gate.json")
    if not gate_path.is_file():
        return "NOT_PRESENT"
    expected = state.get("gate_sha256")
    if not isinstance(expected, str) or re.fullmatch(r"[a-f0-9]{64}", expected) is None:
        return "FAIL"
    try:
        return "PASS" if sha256_file(gate_path) == expected else "FAIL"
    except (AuditError, FileNotFoundError, OSError):
        return "FAIL"


def _update_state(
    workspace: Path,
    *,
    stage: str,
    verdict: str | None = None,
    bundle_sha256: str | None = None,
    gate_sha256: str | None = None,
) -> None:
    state_path = safe_workspace_path(workspace, "state.json")
    if state_path.exists():
        state = _read_json(state_path)
    else:
        state = {"runtime_version": RUNTIME_VERSION, "created_at": utc_now()}
    state.update(stage=stage, updated_at=utc_now())
    if verdict is not None:
        state["verdict"] = verdict
        state["gate_current"] = True
        if gate_sha256 is not None:
            state["gate_sha256"] = gate_sha256
        if stage == "gated":
            report_is_current = (
                verdict == "PASS"
                and isinstance(bundle_sha256, str)
                and state.get("report_bundle_sha256") == bundle_sha256
            )
            if state.get("report") and not report_is_current:
                _archive_report_pointer(state)
    else:
        if "verdict" in state or "report" in state or "report_sha256" in state:
            state["verdict"] = "STALE"
        state["gate_current"] = False
        _archive_report_pointer(state)
    ledger_path = safe_workspace_path(workspace, "ledger.json")
    if ledger_path.exists():
        state["ledger_sha256"] = sha256_file(ledger_path)
    _write_json(state_path, state)


def _load_workspace(workspace: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    ledger_path = safe_workspace_path(workspace, "ledger.json")
    ledger = _read_json(ledger_path)
    receipts: dict[str, dict[str, Any]] = {}
    for index, source in enumerate(ledger.get("sources", [])):
        if not isinstance(source, dict):
            continue
        source_id = source.get("source_id")
        receipt_path = source.get("receipt")
        if not source_id or not receipt_path:
            continue
        try:
            receipts[source_id] = _read_json(safe_workspace_path(workspace, receipt_path))
        except AuditError as exc:
            receipts[source_id] = {
                "source_id": source_id,
                "load_error": str(exc),
                "receipt_sha256": "",
            }
    return ledger, receipts


def cmd_init(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        raise AuditError(f"input file does not exist: {input_path}")
    workspace = Path(args.workspace).resolve()
    if workspace.exists() and any(workspace.iterdir()):
        raise AuditError(f"workspace must be new or empty: {workspace}")
    workspace.mkdir(parents=True, exist_ok=True)
    os.chmod(workspace, 0o700)
    audit_id = args.audit_id or f"audit-{uuid.uuid4().hex[:12]}"
    _write_new_json(
        safe_workspace_path(workspace, ".runtime-init.json"),
        {
            "runtime_version": RUNTIME_VERSION,
            "audit_id": audit_id,
            "started_at": utc_now(),
        },
    )
    receipts_dir = safe_workspace_path(workspace, "receipts")
    artifacts_dir = safe_workspace_path(workspace, "artifacts")
    receipts_dir.mkdir(exist_ok=True)
    artifacts_dir.mkdir(exist_ok=True)
    os.chmod(receipts_dir, 0o700)
    os.chmod(artifacts_dir, 0o700)
    _write_private_text(safe_workspace_path(workspace, ".gitignore"), "*\n!.gitignore\n")

    payload = input_path.read_bytes()
    input_copy = safe_workspace_path(workspace, "input.txt")
    _write_private_bytes(input_copy, payload)
    now = utc_now()
    ledger = {
        "schema_version": "3.1",
        "audit_id": audit_id,
        "created_at": now,
        "verification_date": args.as_of or today_utc(),
        "input": {"path": "input.txt", "sha256": sha256_bytes(payload)},
        "scope": {
            "triggered": True,
            "reason": "awaiting claim extraction",
            "unreviewed_claims": [],
            "candidate_inventory": [],
            "candidate_inventory_recorded": False,
        },
        "sources": [],
        "claims": [],
        "unknowns": ["claim extraction not completed"],
        "next_action": "extract atomic externally verifiable claims into ledger.json",
        "summary_recorded": False,
    }
    _write_json(safe_workspace_path(workspace, "ledger.json"), ledger)
    initialize_runtime_attestations(workspace, ledger["audit_id"])
    _update_state(workspace, stage="initialized")
    _append_event(workspace, "initialized", {"input_sha256": ledger["input"]["sha256"]})
    print(workspace)
    return 0


def cmd_start(args: argparse.Namespace) -> int:
    """Initialize and positively scope an audit in one mandatory first step."""
    input_path = Path(args.input).resolve()
    if not input_path.is_file():
        raise AuditError(f"input file does not exist: {input_path}")
    try:
        input_text = input_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise AuditError("audit input must be valid UTF-8 text") from exc
    if args.candidates_file:
        payload = _read_json(Path(args.candidates_file).resolve())
        if set(payload) != {"candidates"} or not isinstance(
            payload.get("candidates"), list
        ):
            raise AuditError(
                "candidates file must contain exactly one candidates array"
            )
        declared_candidates = payload["candidates"]
    else:
        declared_candidates = list(args.candidate or [])
    candidate_inventory = build_complete_candidate_inventory(
        input_text, declared_candidates
    )
    init_args = argparse.Namespace(
        input=args.input,
        workspace=args.workspace,
        as_of=args.as_of,
        audit_id=args.audit_id,
    )
    result = cmd_init(init_args)
    if result != 0:
        return result
    scope_args = argparse.Namespace(
        workspace=args.workspace,
        triggered=True,
        reason=args.reason,
        unreviewed=[item["text"] for item in candidate_inventory],
        candidate_inventory=candidate_inventory,
    )
    return cmd_scope(scope_args)


def cmd_scope(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    ledger, receipts = _load_workspace(workspace)
    existing_scope = ledger.get("scope")
    if (
        isinstance(existing_scope, dict)
        and existing_scope.get("candidate_inventory_recorded") is True
    ):
        raise AuditError(
            "candidate inventory is frozen; create a new audit instead of replacing scope"
        )
    triggered = bool(args.triggered)
    if not triggered and (ledger.get("claims") or ledger.get("sources")):
        raise AuditError("cannot mark a populated audit as non-triggered")
    candidate_inventory: list[dict[str, Any]] = []
    if triggered:
        candidate_inventory = getattr(args, "candidate_inventory", None) or []
        if not candidate_inventory:
            input_info = ledger.get("input") if isinstance(ledger.get("input"), dict) else {}
            input_relative = input_info.get("path")
            if not isinstance(input_relative, str) or not input_relative:
                raise AuditError("saved audit input path is missing")
            try:
                input_text = safe_workspace_path(workspace, input_relative).read_text(
                    encoding="utf-8"
                )
            except UnicodeDecodeError as exc:
                raise AuditError("audit input must be valid UTF-8 text") from exc
            candidate_inventory = build_complete_candidate_inventory(
                input_text, list(args.unreviewed or [])
            )
    ledger["scope"] = {
        "triggered": triggered,
        "reason": args.reason,
        "unreviewed_claims": list(args.unreviewed or []),
        "candidate_inventory": candidate_inventory,
        "excluded_candidates": [],
        "candidate_inventory_recorded": (not triggered) or bool(args.unreviewed),
    }
    if not triggered:
        ledger["unknowns"] = []
        ledger["next_action"] = "none"
        ledger["summary_recorded"] = True
    _write_json(safe_workspace_path(workspace, "ledger.json"), ledger)
    _update_state(workspace, stage="scoped")
    _append_event(workspace, "scope_set", {"triggered": triggered, "reason": args.reason})
    print("triggered" if triggered else "not-triggered")
    return 0


def cmd_exclude_candidate(args: argparse.Namespace) -> int:
    """Classify one frozen review unit as outside factual-audit scope."""

    workspace = Path(args.workspace).resolve()
    reason = args.reason.strip() if isinstance(args.reason, str) else ""
    if not reason:
        raise AuditError("candidate exclusion reason must be a non-empty string")
    if args.classification not in ALLOWED_EXCLUSION_CLASSES:
        raise AuditError(f"unsupported exclusion classification: {args.classification}")

    ledger, _ = _load_workspace(workspace)
    scope = ledger.get("scope")
    if not isinstance(scope, dict) or scope.get("triggered") is not True:
        raise AuditError("candidate exclusion requires a triggered audit")
    inventory = scope.get("candidate_inventory")
    if args.candidate_id:
        inventory_by_id = {
            item.get("candidate_id"): item
            for item in inventory or []
            if isinstance(item, dict)
        }
        selected = inventory_by_id.get(args.candidate_id)
        if selected is None:
            raise AuditError("candidate_id is absent from the frozen inventory")
        candidate_text = selected.get("text")
    else:
        candidate_text = args.candidate
    inventory_item = next(
        (
            item
            for item in inventory or []
            if isinstance(item, dict) and item.get("text") == candidate_text
        ),
        None,
    )
    if not isinstance(inventory, list) or inventory_item is None:
        raise AuditError("candidate is absent from the frozen inventory")
    if inventory_item.get("origin", "declared") != "auto_gap":
        raise AuditError(
            "a candidate explicitly declared factual cannot be reclassified as non-factual"
        )
    if any(
        candidate_text in claim.get("input_candidates", [])
        for claim in ledger.get("claims", [])
        if isinstance(claim, dict)
    ):
        raise AuditError("candidate is already covered by a recorded claim")
    unreviewed = scope.get("unreviewed_claims")
    if not isinstance(unreviewed, list) or candidate_text not in unreviewed:
        raise AuditError("candidate is not currently awaiting classification")
    excluded = scope.setdefault("excluded_candidates", [])
    if not isinstance(excluded, list):
        raise AuditError("excluded_candidates ledger field is invalid")
    if any(
        isinstance(item, dict) and item.get("candidate") == candidate_text
        for item in excluded
    ):
        raise AuditError("candidate was already excluded")

    unreviewed.remove(candidate_text)
    excluded.append(
        {
            "candidate_id": inventory_item.get("candidate_id"),
            "candidate": candidate_text,
            "classification": args.classification,
            "reason": reason,
            "excluded_at": utc_now(),
        }
    )
    ledger["summary_recorded"] = False
    ledger["next_action"] = "continue classifying frozen candidates"
    _write_json(safe_workspace_path(workspace, "ledger.json"), ledger)
    _update_state(workspace, stage="candidate_excluded")
    _append_event(
        workspace,
        "candidate_excluded",
        {
            "candidate_id": inventory_item.get("candidate_id"),
            "candidate_sha256": sha256_bytes(candidate_text.encode("utf-8")),
            "classification": args.classification,
        },
    )
    print(inventory_item.get("candidate_id"))
    return 0


def _validate_claim_payload(claim: dict[str, Any]) -> None:
    required = {
        "claim_id",
        "text",
        "claim_type",
        "temporal_sensitivity",
        "criteria",
        "requires_independent_evidence",
        "risk_domain",
        "causal_basis",
        "evidence",
        "source_identity_gate",
        "content_support_gate",
        "action_applicability_gate",
        "conflicts",
        "status",
        "confidence_reason",
        "next_step",
        "input_candidates",
    }
    missing = sorted(required - set(claim))
    if missing:
        raise AuditError(f"claim is missing required fields: {', '.join(missing)}")
    if not isinstance(claim["claim_id"], str) or not claim["claim_id"].strip():
        raise AuditError("claim_id must be a non-empty string")
    if not isinstance(claim["text"], str) or not claim["text"].strip():
        raise AuditError("claim text must be a non-empty string")
    if not isinstance(claim["confidence_reason"], str) or not claim[
        "confidence_reason"
    ].strip():
        raise AuditError("claim confidence_reason must be a non-empty string")
    if not isinstance(claim["next_step"], str) or not claim["next_step"].strip():
        raise AuditError("claim next_step must be a non-empty string")
    if claim["claim_type"] not in ALLOWED_CLAIM_TYPES:
        raise AuditError(f"unsupported claim_type: {claim['claim_type']}")
    if claim["temporal_sensitivity"] not in ALLOWED_TEMPORAL_SENSITIVITY:
        raise AuditError(
            f"unsupported temporal_sensitivity: {claim['temporal_sensitivity']}"
        )
    if claim["risk_domain"] not in HIGH_RISK_DOMAINS | {"none"}:
        raise AuditError(f"unsupported risk_domain: {claim['risk_domain']}")
    if claim["causal_basis"] not in ALLOWED_CAUSAL_BASIS_VALUES:
        raise AuditError(f"unsupported causal_basis: {claim['causal_basis']}")
    if claim["status"] not in ALLOWED_STATUSES:
        raise AuditError(f"unsupported claim status: {claim['status']}")
    if not isinstance(claim["evidence"], list) or not isinstance(claim["conflicts"], list):
        raise AuditError("claim evidence and conflicts must be lists")
    if (
        not isinstance(claim["input_candidates"], list)
        or not claim["input_candidates"]
        or any(not isinstance(item, str) or not item.strip() for item in claim["input_candidates"])
    ):
        raise AuditError("claim input_candidates must be a non-empty list of candidate clauses")


def _record_claim(
    workspace: Path,
    claim: dict[str, Any],
    *,
    replace: bool = False,
    close_candidates: bool = True,
) -> int:
    _validate_claim_payload(claim)
    claim = copy.deepcopy(claim)
    claim.pop("countercheck", None)
    claim["assessment_recorded"] = False
    claim["unknowns"] = []
    ledger, _ = _load_workspace(workspace)
    if len(claim["input_candidates"]) != 1:
        raise AuditError(
            "each atomic claim must cover exactly one frozen candidate; split unrelated candidates into separate claims"
        )
    claims = ledger.setdefault("claims", [])
    existing_index = next(
        (index for index, item in enumerate(claims) if item.get("claim_id") == claim["claim_id"]),
        None,
    )
    if existing_index is not None and not replace:
        raise AuditError(f"claim_id already exists: {claim['claim_id']}; use --replace explicitly")
    unreviewed = ledger.setdefault("scope", {}).setdefault("unreviewed_claims", [])
    inventory_recorded = ledger.get("scope", {}).get("candidate_inventory_recorded") is True
    if existing_index is None and inventory_recorded:
        missing_candidates = [
            candidate for candidate in claim["input_candidates"] if candidate not in unreviewed
        ]
        if missing_candidates:
            raise AuditError(
                "claim covers candidates that are absent from the frozen inventory: "
                + "; ".join(missing_candidates)
            )
        candidate_text = claim["input_candidates"][0]
        if claim["text"] not in candidate_text:
            raise AuditError(
                "atomic claim text must be an exact subspan of its frozen input candidate"
            )
        if close_candidates:
            for candidate in claim["input_candidates"]:
                unreviewed.remove(candidate)
    elif existing_index is not None:
        prior_candidates = claims[existing_index].get("input_candidates", [])
        if sorted(prior_candidates) != sorted(claim["input_candidates"]):
            raise AuditError("replacement claims must preserve their original candidate coverage")
    if existing_index is None:
        claims.append(claim)
        event = "claim_added"
    else:
        claims[existing_index] = claim
        event = "claim_replaced"
    ledger["unknowns"] = [
        value for value in ledger.get("unknowns", []) if value != "claim extraction not completed"
    ]
    ledger["next_action"] = "collect and link the highest-value primary source"
    ledger["summary_recorded"] = False
    _write_json(safe_workspace_path(workspace, "ledger.json"), ledger)
    _update_state(workspace, stage="claims_recorded")
    _append_event(workspace, event, {"claim_id": claim["claim_id"]})
    print(claim["claim_id"])
    return 0


def cmd_claim(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    claim = _read_json(Path(args.file).resolve())
    return _record_claim(workspace, claim, replace=args.replace)


def cmd_add_claim(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    conditions = list(args.criterion or [])
    claim = {
        "claim_id": args.claim_id,
        "text": args.text,
        "claim_type": args.claim_type,
        "temporal_sensitivity": args.temporal,
        "as_of": args.as_of or "",
        "criteria": {
            "defined": bool(conditions and args.failure_condition),
            "conditions": conditions,
            "failure_condition": args.failure_condition,
        },
        "requires_independent_evidence": bool(args.requires_independent_evidence),
        "risk_domain": args.risk_domain,
        "causal_basis": args.causal_basis,
        "evidence": [],
        "source_identity_gate": "unknown",
        "content_support_gate": "unknown",
        "action_applicability_gate": (
            "professional_review" if args.risk_domain in HIGH_RISK_DOMAINS else "not_applicable"
        ),
        "conflicts": [],
        "status": "current_unknown" if args.temporal == "high" else "unverifiable",
        "confidence_reason": "No eligible opened source is linked yet.",
        "next_step": args.next_step,
        "assessment_recorded": False,
        "unknowns": [],
        "input_candidates": list(args.covers),
    }
    return _record_claim(
        workspace,
        claim,
        replace=args.replace,
        close_candidates=not args.keep_candidate_open,
    )


def _record_evidence(workspace: Path, payload: dict[str, Any]) -> int:
    claim_id = payload.get("claim_id")
    source_id = payload.get("source_id")
    if not isinstance(claim_id, str) or not claim_id:
        raise AuditError("evidence claim_id is required")
    if not isinstance(source_id, str) or not source_id:
        raise AuditError("evidence source_id is required")
    ledger, receipts = _load_workspace(workspace)
    source_ids = {source.get("source_id") for source in ledger.get("sources", [])}
    if source_id not in source_ids:
        raise AuditError(f"unknown source: {source_id}")
    receipt = receipts.get(source_id)
    if isinstance(receipt, dict):
        if _pdf_text_binding_unavailable(receipt):
            raise AuditError(
                f"source {source_id} is not eligible for evidence binding because PDF text extraction did not complete"
            )
    claim = next(
        (item for item in ledger.get("claims", []) if item.get("claim_id") == claim_id),
        None,
    )
    if claim is None:
        raise AuditError(f"unknown claim: {claim_id}")
    support = payload.get("support")
    if support not in {"direct", "partial", "conflict", "context", "none"}:
        raise AuditError("evidence support must be direct, partial, conflict, context, or none")
    inference_span = payload.get("inference_span")
    if not isinstance(inference_span, int) or not 0 <= inference_span <= 3:
        raise AuditError("evidence inference_span must be an integer from 0 to 3")
    if support in {"direct", "partial", "conflict"} and (
        not payload.get("locator") or not payload.get("excerpt")
    ):
        raise AuditError("direct, partial, or conflict evidence requires locator and excerpt")
    if support in {"direct", "partial", "conflict"} and (
        not isinstance(payload.get("support_scope"), str)
        or not payload.get("support_scope", "").strip()
    ):
        raise AuditError(
            "direct, partial, or conflict evidence requires a non-empty support_scope"
        )
    purpose = payload.get("evidence_purpose", "substantive")
    if purpose not in ALLOWED_EVIDENCE_PURPOSES:
        raise AuditError("evidence_purpose is not allowed")
    payload["evidence_purpose"] = purpose
    evidence = {key: copy.deepcopy(value) for key, value in payload.items() if key != "claim_id"}
    claim.setdefault("evidence", []).append(evidence)
    claim["assessment_recorded"] = False
    claim.pop("countercheck", None)
    ledger["summary_recorded"] = False
    _write_json(safe_workspace_path(workspace, "ledger.json"), ledger)
    _update_state(workspace, stage="evidence_linked")
    _append_event(
        workspace,
        "evidence_linked",
        {"claim_id": claim_id, "source_id": source_id, "support": support},
    )
    print(f"{claim_id}:{source_id}")
    return 0


def cmd_evidence(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    payload = _read_json(Path(args.file).resolve())
    return _record_evidence(workspace, payload)


def _record_assessment(workspace: Path, payload: dict[str, Any]) -> int:
    required = {
        "claim_id",
        "source_identity_gate",
        "content_support_gate",
        "action_applicability_gate",
        "status",
        "confidence_reason",
        "conflicts",
        "next_step",
        "unknowns",
        "next_action",
    }
    missing = sorted(required - set(payload))
    if missing:
        raise AuditError(f"assessment is missing required fields: {', '.join(missing)}")
    if payload["status"] not in ALLOWED_STATUSES:
        raise AuditError(f"unsupported assessment status: {payload['status']}")
    if payload["source_identity_gate"] not in {"pass", "fail", "unknown"}:
        raise AuditError("source_identity_gate must be pass, fail, or unknown")
    if payload["content_support_gate"] not in {"pass", "partial", "fail", "unknown"}:
        raise AuditError("content_support_gate must be pass, partial, fail, or unknown")
    if payload["action_applicability_gate"] not in {
        "pass",
        "insufficient",
        "professional_review",
        "not_applicable",
        "unknown",
    }:
        raise AuditError("action_applicability_gate has an unsupported value")
    if not isinstance(payload["conflicts"], list):
        raise AuditError("assessment conflicts must be a list")
    if not isinstance(payload["confidence_reason"], str) or not payload[
        "confidence_reason"
    ].strip():
        raise AuditError("assessment confidence_reason must be non-empty")
    if not isinstance(payload["next_step"], str) or not payload["next_step"].strip():
        raise AuditError("assessment next_step must be non-empty")
    if not isinstance(payload["next_action"], str) or not payload[
        "next_action"
    ].strip():
        raise AuditError("assessment next_action must be non-empty")
    if (
        not isinstance(payload["unknowns"], list)
        or not payload["unknowns"]
        or any(
            not isinstance(item, str) or not item.strip()
            for item in payload["unknowns"]
        )
    ):
        raise AuditError(
            "assessment unknowns must contain at least one non-empty item or explicit none statement"
        )

    ledger, receipts = _load_workspace(workspace)
    claim = next(
        (item for item in ledger.get("claims", []) if item.get("claim_id") == payload["claim_id"]),
        None,
    )
    if claim is None:
        raise AuditError(f"unknown claim: {payload['claim_id']}")
    for field in (
        "source_identity_gate",
        "content_support_gate",
        "action_applicability_gate",
        "status",
        "confidence_reason",
        "conflicts",
        "next_step",
    ):
        claim[field] = copy.deepcopy(payload[field])
    claim["assessment_recorded"] = True
    claim.pop("countercheck", None)
    if "causal_basis" in payload:
        claim["causal_basis"] = payload["causal_basis"]
    if "as_of" in payload:
        claim["as_of"] = payload["as_of"]
    claim["unknowns"] = copy.deepcopy(payload["unknowns"])
    if len(ledger.get("claims", [])) == 1:
        ledger["unknowns"] = copy.deepcopy(payload["unknowns"])
        ledger["next_action"] = str(payload["next_action"])
        ledger["summary_recorded"] = True
    else:
        ledger["summary_recorded"] = False
    _write_json(safe_workspace_path(workspace, "ledger.json"), ledger)
    _update_state(workspace, stage="assessed")
    _append_event(
        workspace,
        "claim_assessed",
        {"claim_id": payload["claim_id"], "proposed_status": payload["status"]},
    )
    print(payload["claim_id"])
    return 0


def cmd_assess(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    payload = _read_json(Path(args.file).resolve())
    return _record_assessment(workspace, payload)


def cmd_decide(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {
        "claim_id": args.claim_id,
        "source_identity_gate": args.identity_gate,
        "content_support_gate": args.content_gate,
        "action_applicability_gate": args.action_gate,
        "status": args.status,
        "confidence_reason": args.confidence_reason,
        "conflicts": list(args.conflict or []),
        "next_step": args.next_step,
    }
    if args.causal_basis is not None:
        payload["causal_basis"] = args.causal_basis
    if args.as_of is not None:
        payload["as_of"] = args.as_of
    payload["unknowns"] = list(args.unknown)
    payload["next_action"] = args.next_action
    return _record_assessment(Path(args.workspace).resolve(), payload)


def countercheck_basis_hash(claim: dict[str, Any]) -> str:
    """Bind a countercheck to the exact claim, evidence, and assessment state."""

    basis = copy.deepcopy(claim)
    basis.pop("countercheck", None)
    return sha256_bytes(canonical_json(basis))


def _countercheck_is_current(claim: dict[str, Any]) -> bool:
    record = claim.get("countercheck")
    return (
        isinstance(record, dict)
        and record.get("basis_hash") == countercheck_basis_hash(claim)
    )


def cmd_countercheck(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    payload = _read_json(Path(args.file).resolve())
    required = {
        "claim_id",
        "falsifier",
        "checked_source_ids",
        "result",
        "stop_reason",
    }
    missing = sorted(required - set(payload))
    extra = sorted(set(payload) - required)
    if missing:
        raise AuditError(
            "countercheck is missing required fields: " + ", ".join(missing)
        )
    if extra:
        raise AuditError(
            "countercheck contains runtime-owned or unknown fields: " + ", ".join(extra)
        )
    claim_id = payload.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id.strip():
        raise AuditError("countercheck claim_id must be a non-empty string")
    for field in ("falsifier", "stop_reason"):
        value = payload.get(field)
        if not isinstance(value, str) or not value.strip():
            raise AuditError(f"countercheck {field} must be a non-empty string")
        if len(value.encode("utf-8")) > MAX_COUNTERCHECK_TEXT:
            raise AuditError(
                f"countercheck {field} exceeds the {MAX_COUNTERCHECK_TEXT}-byte size limit"
            )
    result = payload.get("result")
    if result not in ALLOWED_COUNTERCHECK_RESULTS:
        raise AuditError(
            "countercheck result must be one of: "
            + ", ".join(sorted(ALLOWED_COUNTERCHECK_RESULTS))
        )
    checked_source_ids = payload.get("checked_source_ids")
    if (
        not isinstance(checked_source_ids, list)
        or any(not isinstance(item, str) or not item for item in checked_source_ids)
        or len(checked_source_ids) != len(set(checked_source_ids))
    ):
        raise AuditError(
            "countercheck checked_source_ids must be a unique list of source IDs"
        )
    if len(checked_source_ids) > MAX_COUNTERCHECK_SOURCES:
        raise AuditError(
            f"countercheck checked_source_ids exceeds the {MAX_COUNTERCHECK_SOURCES}-source limit"
        )

    ledger, receipts = _load_workspace(workspace)
    claim = next(
        (
            item
            for item in ledger.get("claims", [])
            if isinstance(item, dict) and item.get("claim_id") == claim_id
        ),
        None,
    )
    if claim is None:
        raise AuditError(f"unknown claim: {claim_id}")
    if claim.get("assessment_recorded") is not True:
        raise AuditError("countercheck requires a current recorded assessment")
    if claim.get("status") in CONFIRMING_STATUSES and not checked_source_ids:
        raise AuditError(
            "a decisive claim status requires at least one actually checked source"
        )
    source_ids = {
        source.get("source_id")
        for source in ledger.get("sources", [])
        if isinstance(source, dict) and source.get("active") is not False
    }
    unknown_source_ids = sorted(set(checked_source_ids) - source_ids)
    if unknown_source_ids:
        raise AuditError(
            "countercheck references unknown or retired sources: "
            + ", ".join(unknown_source_ids)
        )
    if result != "inconclusive":
        unusable_source_ids = [
            source_id
            for source_id in checked_source_ids
            if not _receipt_is_usable(receipts.get(source_id, {}))
        ]
        if unusable_source_ids:
            raise AuditError(
                "a conclusive countercheck result cannot rely on failed or ineligible sources: "
                + ", ".join(unusable_source_ids)
            )
    if result == "conflict_found" and not any(
        isinstance(item, dict)
        and item.get("support") == "conflict"
        and item.get("source_id") in checked_source_ids
        for item in claim.get("evidence", [])
    ):
        raise AuditError(
            "countercheck conflict_found requires conflict evidence bound to a checked source"
        )
    if result == "scope_narrowed":
        raise AuditError(
            "countercheck scope_narrowed requires reassessment before a new countercheck"
        )
    record = {
        "falsifier": payload["falsifier"].strip(),
        "checked_source_ids": list(checked_source_ids),
        "result": result,
        "stop_reason": payload["stop_reason"].strip(),
        "checked_at": utc_now(),
        "basis_hash": countercheck_basis_hash(claim),
    }
    claim["countercheck"] = record
    ledger["summary_recorded"] = False
    _write_json(safe_workspace_path(workspace, "ledger.json"), ledger)
    _update_state(workspace, stage="counterchecked")
    _append_event(
        workspace,
        "claim_counterchecked",
        {
            "claim_id": claim_id,
            "result": result,
            "checked_source_count": len(checked_source_ids),
            "basis_hash": record["basis_hash"],
        },
    )
    print(claim_id)
    return 0


def cmd_summarize(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    ledger, _ = _load_workspace(workspace)
    claims = ledger.get("claims", [])
    if not claims:
        raise AuditError("cannot summarize an audit with no claims")
    if any(claim.get("assessment_recorded") is not True for claim in claims):
        raise AuditError("all claims must be assessed before the audit summary")
    if any(not _countercheck_is_current(claim) for claim in claims):
        raise AuditError(
            "all claims require a current countercheck before the audit summary"
        )
    if args.file:
        if args.unknown or args.next_action:
            raise AuditError(
                "summarize --file cannot be combined with --unknown or --next-action"
            )
        summary_payload = _read_json(Path(args.file).resolve())
        if set(summary_payload) != {"unknowns", "next_action"}:
            raise AuditError(
                "summary file must contain exactly unknowns and next_action"
            )
        unknowns = summary_payload.get("unknowns")
        next_action = summary_payload.get("next_action")
    else:
        unknowns = list(args.unknown or [])
        next_action = args.next_action
    if not isinstance(unknowns, list):
        raise AuditError("summary unknowns must be a list")
    if not unknowns or any(
        not isinstance(item, str) or not item.strip() for item in unknowns
    ):
        raise AuditError("summary requires at least one explicit unknown or none statement")
    if not isinstance(next_action, str) or not next_action.strip():
        raise AuditError("summary next action must be non-empty")
    ledger["unknowns"] = unknowns
    ledger["next_action"] = next_action
    ledger["summary_recorded"] = True
    _write_json(safe_workspace_path(workspace, "ledger.json"), ledger)
    _update_state(workspace, stage="summarized")
    _append_event(
        workspace,
        "audit_summarized",
        {"unknowns": len(unknowns), "next_action": next_action},
    )
    print("summarized")
    return 0


def cmd_quote(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    _, receipts = _load_workspace(workspace)
    receipt = receipts.get(args.source_id)
    if receipt is None:
        raise AuditError(f"unknown source: {args.source_id}")
    parsed_rel = receipt.get("parsed_text")
    if not parsed_rel:
        raise AuditError(f"source {args.source_id} has no parsed text artifact")
    parsed = safe_workspace_path(workspace, parsed_rel).read_text(encoding="utf-8")
    exact = args.exact
    starts: list[int] = []
    cursor = 0
    while True:
        found = parsed.find(exact, cursor)
        if found < 0:
            break
        starts.append(found)
        cursor = found + max(1, len(exact))
    if not starts:
        raise AuditError("exact quotation was not found in the saved parsed text")
    if len(starts) > 1 and args.occurrence is None:
        raise AuditError(
            f"exact quotation occurs {len(starts)} times; choose --occurrence explicitly"
        )
    occurrence = args.occurrence or 1
    if occurrence < 1 or occurrence > len(starts):
        raise AuditError(f"occurrence must be between 1 and {len(starts)}")
    start = starts[occurrence - 1]
    selected = parsed[start : start + len(exact)]
    selector = {
        "start": start,
        "end": start + len(selected),
        "quote_sha256": sha256_bytes(selected.encode("utf-8")),
    }
    print(json.dumps(selector, ensure_ascii=False, indent=2))
    return 0


def _locate_exact_quote(
    workspace: Path,
    source_id: str,
    exact: str,
    occurrence: int | None = None,
) -> dict[str, Any]:
    _, receipts = _load_workspace(workspace)
    receipt = receipts.get(source_id)
    if receipt is None:
        raise AuditError(f"unknown source: {source_id}")
    parsed_rel = receipt.get("parsed_text")
    if not parsed_rel:
        raise AuditError(f"source {source_id} has no parsed text artifact")
    parsed = safe_workspace_path(workspace, parsed_rel).read_text(encoding="utf-8")
    starts: list[int] = []
    cursor = 0
    while True:
        found = parsed.find(exact, cursor)
        if found < 0:
            break
        starts.append(found)
        cursor = found + max(1, len(exact))
    if not starts:
        raise AuditError("exact quotation was not found in the saved parsed text")
    if len(starts) > 1 and occurrence is None:
        raise AuditError(
            f"exact quotation occurs {len(starts)} times; choose --occurrence explicitly"
        )
    selected_occurrence = occurrence or 1
    if selected_occurrence < 1 or selected_occurrence > len(starts):
        raise AuditError(f"occurrence must be between 1 and {len(starts)}")
    start = starts[selected_occurrence - 1]
    selected = parsed[start : start + len(exact)]
    return {
        "start": start,
        "end": start + len(selected),
        "quote_sha256": sha256_bytes(selected.encode("utf-8")),
    }


def cmd_link(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    selector: dict[str, Any] | None = None
    excerpt = args.exact or args.excerpt or ""
    locator = args.locator or ""
    if args.exact:
        selector = _locate_exact_quote(
            workspace,
            args.source_id,
            args.exact,
            occurrence=args.occurrence,
        )
        locator = locator or f"chars {selector['start']}:{selector['end']}"
    if args.support in {"direct", "partial", "conflict"} and not args.exact:
        raise AuditError(
            "direct, partial, or conflict evidence requires --exact from saved parsed text"
        )
    payload: dict[str, Any] = {
        "claim_id": args.claim_id,
        "source_id": args.source_id,
        "support": args.support,
        "evidence_purpose": args.purpose,
        "support_scope": args.support_scope,
        "locator": locator,
        "excerpt": excerpt,
        "inference_span": args.inference_span,
    }
    if selector is not None:
        payload["selector"] = selector
    return _record_evidence(workspace, payload)


def _ensure_new_source_id(ledger: dict[str, Any], source_id: str) -> None:
    validate_source_id(source_id)
    folded = source_id.casefold()
    if any(
        isinstance(source.get("source_id"), str)
        and source["source_id"].casefold() == folded
        for source in ledger.get("sources", [])
        if isinstance(source, dict)
    ):
        raise AuditError(f"source_id already exists: {source_id}")


def _ensure_source_paths_available(workspace: Path, source_id: str) -> None:
    validate_source_id(source_id)
    expected = {
        "receipts": {f"{source_id}.json".casefold()},
        "artifacts": {
            f"{source_id}.bin".casefold(),
            f"{source_id}.txt".casefold(),
        },
    }
    for directory, protected_names in expected.items():
        root = safe_workspace_path(workspace, directory)
        if not root.is_dir():
            raise AuditError(f"required source directory is missing: {directory}")
        for child in root.iterdir():
            if child.name.casefold() in protected_names:
                raise AuditError(
                    f"source_id collides with an existing {directory} file: {source_id}"
                )


def _source_transaction_path(workspace: Path, source_id: str) -> Path:
    validate_source_id(source_id)
    return safe_workspace_path(workspace, f"source-transactions/{source_id}.json")


def _source_ledger_record(
    source_id: str,
    receipt_rel: str,
    *,
    tier: str,
    role: str,
    published: str,
    origin_id: str,
    freshness_status: str,
    freshness_rationale: str,
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "active": True,
        "receipt": receipt_rel,
        "source_tier": tier,
        "evidence_role": role,
        "publication_date": published,
        "freshness_status": freshness_status,
        "freshness_rationale": freshness_rationale,
        "origin_id": origin_id,
    }


def _source_transaction_payload(
    source_record: dict[str, Any], receipt: dict[str, Any]
) -> dict[str, Any]:
    return {
        "transaction_version": "1.0",
        "source_id": source_record["source_id"],
        "status": "prepared",
        "source_record": copy.deepcopy(source_record),
        "receipt_sha256": receipt["receipt_sha256"],
        "receipt_snapshot": copy.deepcopy(receipt),
        "created_at": utc_now(),
        "updated_at": utc_now(),
    }


def _begin_or_resume_source_transaction(
    workspace: Path,
    source_record: dict[str, Any],
    receipt: dict[str, Any],
) -> tuple[Path, dict[str, Any]]:
    path = _source_transaction_path(workspace, source_record["source_id"])
    expected = _source_transaction_payload(source_record, receipt)
    if path.exists():
        transaction = _read_json(path)
        if transaction.get("status") == "aborted":
            raise AuditError(
                f"source transaction was aborted and source_id cannot be reused: {source_record['source_id']}"
            )
        comparable = {
            "transaction_version": transaction.get("transaction_version"),
            "source_id": transaction.get("source_id"),
            "source_record": transaction.get("source_record"),
            "receipt_sha256": transaction.get("receipt_sha256"),
            "receipt_snapshot": transaction.get("receipt_snapshot"),
        }
        expected_comparable = {
            "transaction_version": expected["transaction_version"],
            "source_id": expected["source_id"],
            "source_record": expected["source_record"],
            "receipt_sha256": expected["receipt_sha256"],
            "receipt_snapshot": expected["receipt_snapshot"],
        }
        if comparable != expected_comparable:
            raise AuditError(
                f"source transaction retry does not match the frozen source record: {source_record['source_id']}"
            )
        return path, transaction
    path.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(path.parent, 0o700)
    _write_new_json(path, expected)
    return path, expected


def _advance_source_transaction(
    path: Path, transaction: dict[str, Any], status: str
) -> None:
    transaction["status"] = status
    transaction["updated_at"] = utc_now()
    _write_json(path, transaction)


def _load_source_transaction(
    workspace: Path, source_id: str
) -> dict[str, Any] | None:
    path = _source_transaction_path(workspace, source_id)
    if not path.exists():
        return None
    transaction = _read_json(path)
    if (
        transaction.get("transaction_version") != "1.0"
        or transaction.get("source_id") != source_id
        or transaction.get("status") not in ALLOWED_SOURCE_TRANSACTION_STATUSES
        or not isinstance(transaction.get("source_record"), dict)
        or not isinstance(transaction.get("receipt_snapshot"), dict)
    ):
        raise AuditError(f"source transaction journal is invalid: {source_id}")
    if transaction.get("status") == "aborted" and (
        not isinstance(transaction.get("abort_reason"), str)
        or not transaction.get("abort_reason", "").strip()
        or not isinstance(transaction.get("aborted_at"), str)
        or parse_iso_datetime(transaction.get("aborted_at")) is None
    ):
        raise AuditError(f"aborted source transaction journal is invalid: {source_id}")
    return transaction


def _transaction_artifacts_complete(
    workspace: Path, receipt: dict[str, Any]
) -> bool:
    artifact_rel = receipt.get("artifact")
    if artifact_rel:
        artifact_path = safe_workspace_path(workspace, artifact_rel)
        if (
            not artifact_path.is_file()
            or sha256_file(artifact_path) != receipt.get("content_sha256")
        ):
            return False
    parsed_rel = receipt.get("parsed_text")
    if parsed_rel:
        parsed_path = safe_workspace_path(workspace, parsed_rel)
        if (
            not parsed_path.is_file()
            or sha256_file(parsed_path) != receipt.get("parsed_text_sha256")
        ):
            return False
    return True


def _resume_pending_source_registration(
    workspace: Path,
    ledger: dict[str, Any],
    source_id: str,
    *,
    tier: str,
    role: str,
    published: str,
    origin_id: str,
    freshness_status: str,
    freshness_rationale: str,
) -> dict[str, Any] | None:
    """Commit a complete journaled source without repeating acquisition."""

    transaction = _load_source_transaction(workspace, source_id)
    if transaction is None or transaction.get("status") == "committed":
        return None
    if transaction.get("status") == "aborted":
        raise AuditError(
            f"source transaction was aborted and source_id cannot be reused: {source_id}"
        )
    receipt = transaction["receipt_snapshot"]
    expected_record = _source_ledger_record(
        source_id,
        f"receipts/{source_id}.json",
        tier=tier,
        role=role,
        published=published,
        origin_id=origin_id,
        freshness_status=freshness_status,
        freshness_rationale=freshness_rationale,
    )
    if transaction.get("source_record") != expected_record:
        raise AuditError(
            f"source retry metadata conflicts with the frozen transaction: {source_id}"
        )
    if not _transaction_artifacts_complete(workspace, receipt):
        return None
    _register_source(
        workspace,
        ledger,
        receipt,
        tier=tier,
        role=role,
        published=published,
        origin_id=origin_id,
        freshness_status=freshness_status,
        freshness_rationale=freshness_rationale,
    )
    return receipt


def _register_source(
    workspace: Path,
    ledger: dict[str, Any],
    receipt: dict[str, Any],
    *,
    tier: str,
    role: str,
    published: str,
    origin_id: str,
    freshness_status: str,
    freshness_rationale: str,
) -> str:
    source_id = validate_source_id(receipt["source_id"])
    if receipt.get("origin_id") != origin_id:
        raise AuditError("receipt origin_id does not match source registration metadata")
    receipt["receipt_sha256"] = compute_receipt_sha256(receipt)
    receipt_rel = f"receipts/{source_id}.json"
    source_record = _source_ledger_record(
        source_id,
        receipt_rel,
        tier=tier,
        role=role,
        published=published,
        origin_id=origin_id,
        freshness_status=freshness_status,
        freshness_rationale=freshness_rationale,
    )
    transaction_path, transaction = _begin_or_resume_source_transaction(
        workspace, source_record, receipt
    )
    receipt_path = safe_workspace_path(workspace, receipt_rel)
    if receipt_path.exists():
        existing_receipt = _read_json(receipt_path)
        if canonical_json(existing_receipt) != canonical_json(receipt):
            raise AuditError(f"source receipt conflicts with retry: {source_id}")
    else:
        _write_new_json(receipt_path, receipt)
    _advance_source_transaction(transaction_path, transaction, "receipt_saved")
    attest_runtime_receipt(workspace, str(ledger.get("audit_id") or ""), receipt)
    _advance_source_transaction(transaction_path, transaction, "attested")
    existing_sources = [
        item
        for item in ledger.setdefault("sources", [])
        if isinstance(item, dict) and item.get("source_id") == source_id
    ]
    if existing_sources:
        if len(existing_sources) != 1 or existing_sources[0] != source_record:
            raise AuditError(f"ledger source conflicts with transaction retry: {source_id}")
    else:
        ledger["sources"].append(source_record)
        _write_json(safe_workspace_path(workspace, "ledger.json"), ledger)
    _advance_source_transaction(transaction_path, transaction, "committed")
    return receipt_rel


def cmd_abort_source_transaction(args: argparse.Namespace) -> int:
    """Close an unrecoverable partial source transaction without erasing it."""

    workspace = Path(args.workspace).resolve()
    source_id = validate_source_id(args.source_id)
    reason = args.reason.strip() if isinstance(args.reason, str) else ""
    if not reason:
        raise AuditError("source transaction abort reason must be non-empty")
    if len(reason.encode("utf-8")) > MAX_ABORT_REASON:
        raise AuditError(
            f"source transaction abort reason exceeds the {MAX_ABORT_REASON}-byte size limit"
        )

    ledger, _ = _load_workspace(workspace)
    transaction = _load_source_transaction(workspace, source_id)
    if transaction is None:
        raise AuditError(f"unknown source transaction: {source_id}")
    status = transaction.get("status")
    if status == "aborted":
        raise AuditError(f"source transaction is already aborted: {source_id}")
    if status == "committed":
        raise AuditError(
            f"committed source transaction cannot be aborted; retire the source instead: {source_id}"
        )
    if any(
        isinstance(source, dict) and source.get("source_id") == source_id
        for source in ledger.get("sources", [])
    ):
        raise AuditError(
            f"source already entered the ledger and must be resumed, not aborted: {source_id}"
        )

    snapshot = transaction.get("receipt_snapshot")
    if (
        not isinstance(snapshot, dict)
        or snapshot.get("source_id") != source_id
        or compute_receipt_sha256(snapshot) != transaction.get("receipt_sha256")
    ):
        raise AuditError(
            f"source transaction snapshot integrity failed before abort: {source_id}"
        )

    now = utc_now()
    transaction["status"] = "aborted"
    transaction["abort_reason"] = reason
    transaction["aborted_at"] = now
    transaction["updated_at"] = now
    _write_json(_source_transaction_path(workspace, source_id), transaction)
    _update_state(workspace, stage="source_transaction_aborted")
    _append_event(
        workspace,
        "source_transaction_aborted",
        {
            "source_id": source_id,
            "prior_status": status,
            "receipt_sha256": transaction.get("receipt_sha256"),
        },
    )
    print(source_id)
    return 0


def cmd_retire_source(args: argparse.Namespace) -> int:
    """Retire an unusable unlinked source while preserving its receipt trace."""

    workspace = Path(args.workspace).resolve()
    ledger, _ = _load_workspace(workspace)
    source = next(
        (
            item
            for item in ledger.get("sources", [])
            if isinstance(item, dict) and item.get("source_id") == args.source_id
        ),
        None,
    )
    if source is None:
        raise AuditError(f"unknown source: {args.source_id}")
    if source.get("active") is False:
        raise AuditError(f"source is already retired: {args.source_id}")
    linked_claims = [
        claim.get("claim_id")
        for claim in ledger.get("claims", [])
        if isinstance(claim, dict)
        and any(
            isinstance(item, dict) and item.get("source_id") == args.source_id
            for item in claim.get("evidence", [])
        )
    ]
    if linked_claims:
        raise AuditError(
            "cannot retire a source linked to claims: " + ", ".join(map(str, linked_claims))
        )
    if not args.reason.strip():
        raise AuditError("source retirement requires a non-empty reason")
    source["active"] = False
    source["retired_at"] = utc_now()
    source["retirement_reason"] = args.reason
    _write_json(safe_workspace_path(workspace, "ledger.json"), ledger)
    _update_state(workspace, stage="source_retired")
    _append_event(
        workspace,
        "source_retired",
        {"source_id": args.source_id, "reason": args.reason},
    )
    print(args.source_id)
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    _validate_fetch_limits(args.max_bytes)
    workspace = Path(args.workspace).resolve()
    ledger, _ = _load_workspace(workspace)
    existing_transaction = _load_source_transaction(workspace, args.source_id)
    recovered = _resume_pending_source_registration(
        workspace,
        ledger,
        args.source_id,
        tier=args.tier,
        role=args.role,
        published=args.published,
        origin_id=args.origin_id,
        freshness_status=args.freshness,
        freshness_rationale=args.freshness_rationale or "",
    )
    if recovered is not None:
        _update_state(workspace, stage="evidence_collected")
        _append_event(
            workspace,
            "source_transaction_recovered",
            {"source_id": args.source_id, "receipt_sha256": recovered["receipt_sha256"]},
        )
        print(f"receipts/{args.source_id}.json")
        return 0 if recovered.get("support_eligible") else 1
    _ensure_new_source_id(ledger, args.source_id)
    if existing_transaction is None:
        _ensure_source_paths_available(workspace, args.source_id)
    assert_http_url_syntax(args.requested_url)
    assert_http_url_syntax(args.final_url)

    source_path = Path(args.file).resolve()
    if not source_path.is_file():
        raise AuditError(f"captured source file does not exist: {source_path}")
    with source_path.open("rb") as handle:
        body = read_limited(handle, max_bytes=args.max_bytes)
    artifact_rel = f"artifacts/{args.source_id}.bin"
    extraction = extract_evidence_text(body, args.content_type)
    text = extraction["text"]
    parser_name = extraction["parser_name"]
    parser_version = extraction["parser_version"]
    parser_error = extraction["error"]
    parsed_rel = None
    parsed_hash = None
    if text is not None:
        parsed_rel = f"artifacts/{args.source_id}.txt"
        parsed_bytes = text.encode("utf-8")
        parsed_hash = sha256_bytes(parsed_bytes)

    # A caller-supplied file cannot prove its own URL/content binding. Preserve it
    # for context and later provenance work, but never let it satisfy a hard
    # confirmation or refutation gate without a future independently verifiable
    # connector attestation.
    support_eligible = False
    capture_ineligibility = (
        "external capture has no runtime-verifiable URL/content binding; "
        "it may be used only as contextual or pending material"
    )
    if parser_error:
        capture_ineligibility += f"; text extraction failed: {parser_error}"
    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "source_id": args.source_id,
        "requested_url": sanitize_url_for_receipt(args.requested_url)[0],
        "requested_url_query_sha256": sanitize_url_for_receipt(args.requested_url)[1],
        "final_url": sanitize_url_for_receipt(args.final_url)[0],
        "final_url_query_sha256": sanitize_url_for_receipt(args.final_url)[1],
        "resolved_ip": None,
        "accessed_at": (
            existing_transaction.get("receipt_snapshot", {}).get("accessed_at")
            if existing_transaction is not None
            else args.accessed_at or utc_now()
        ),
        "http_status": args.http_status,
        "content_type": args.content_type,
        "content_encoding": "identity",
        "bytes_read": len(body),
        "content_sha256": sha256_bytes(body),
        "headers_sha256": sha256_bytes(canonical_json([])),
        "redirect_chain": [],
        "origin_id": args.origin_id,
        "retrieval_complete": True,
        "support_eligible": support_eligible,
        "ineligibility_reason": capture_ineligibility,
        "acquisition_type": args.acquisition_type,
        "transport_attestation": "caller_attested_import_unverified",
        "artifact": artifact_rel,
        "parsed_text": parsed_rel,
        "parsed_text_sha256": parsed_hash,
        "parser_name": parser_name,
        "parser_version": parser_version,
        "parser_error": parser_error,
    }
    receipt["receipt_sha256"] = compute_receipt_sha256(receipt)
    source_record = _source_ledger_record(
        args.source_id,
        f"receipts/{args.source_id}.json",
        tier=args.tier,
        role=args.role,
        published=args.published,
        origin_id=args.origin_id,
        freshness_status=args.freshness,
        freshness_rationale=args.freshness_rationale or "",
    )
    transaction_path, transaction = _begin_or_resume_source_transaction(
        workspace, source_record, receipt
    )
    _write_new_or_verify_private_bytes(
        safe_workspace_path(workspace, artifact_rel), body
    )
    if text is not None and parsed_rel is not None:
        _write_new_or_verify_private_bytes(
            safe_workspace_path(workspace, parsed_rel), text.encode("utf-8")
        )
    _advance_source_transaction(transaction_path, transaction, "artifacts_saved")
    receipt_rel = _register_source(
        workspace,
        ledger,
        receipt,
        tier=args.tier,
        role=args.role,
        published=args.published,
        origin_id=args.origin_id,
        freshness_status=args.freshness,
        freshness_rationale=args.freshness_rationale or "",
    )
    _update_state(workspace, stage="evidence_collected")
    _append_event(
        workspace,
        "source_captured",
        {
            "source_id": args.source_id,
            "acquisition_type": args.acquisition_type,
            "receipt_sha256": receipt["receipt_sha256"],
        },
    )
    print(receipt_rel)
    return 0 if support_eligible else 1


def cmd_fetch(args: argparse.Namespace) -> int:
    _validate_fetch_limits(args.max_bytes, args.timeout)
    if not 0 <= args.max_redirects <= MAX_REDIRECTS:
        raise AuditError(
            f"max_redirects must be between 0 and the frozen ceiling of {MAX_REDIRECTS}"
        )
    workspace = Path(args.workspace).resolve()
    ledger, _ = _load_workspace(workspace)
    existing_transaction = _load_source_transaction(workspace, args.source_id)
    recovered = _resume_pending_source_registration(
        workspace,
        ledger,
        args.source_id,
        tier=args.tier,
        role=args.role,
        published=args.published,
        origin_id=args.origin_id,
        freshness_status=args.freshness,
        freshness_rationale=args.freshness_rationale or "",
    )
    if recovered is not None:
        _update_state(workspace, stage="evidence_collected")
        _append_event(
            workspace,
            "source_transaction_recovered",
            {"source_id": args.source_id, "receipt_sha256": recovered["receipt_sha256"]},
        )
        print(f"receipts/{args.source_id}.json")
        return 0 if recovered.get("support_eligible") else 1
    _ensure_new_source_id(ledger, args.source_id)
    if existing_transaction is None:
        _ensure_source_paths_available(workspace, args.source_id)

    try:
        result = fetch_public_url(
            args.url,
            max_bytes=args.max_bytes,
            timeout=args.timeout,
            max_redirects=args.max_redirects,
        )
    except AuditError as exc:
        if existing_transaction is not None:
            raise AuditError(
                f"pending source transaction could not resume acquisition: {args.source_id}"
            ) from exc
        sanitized_url, query_hash = sanitize_url_for_receipt(args.url)
        safe_error = safe_fetch_error_message(exc)
        failure_receipt = {
            "receipt_version": RECEIPT_VERSION,
            "runtime_version": RUNTIME_VERSION,
            "source_id": args.source_id,
            "requested_url": sanitized_url,
            "requested_url_query_sha256": query_hash,
            "final_url": sanitized_url,
            "final_url_query_sha256": query_hash,
            "resolved_ip": None,
            "accessed_at": utc_now(),
            "http_status": None,
            "content_type": None,
            "content_encoding": None,
            "bytes_read": 0,
            "content_sha256": sha256_bytes(b""),
            "headers_sha256": sha256_bytes(canonical_json([])),
            "redirect_chain": [],
            "origin_id": args.origin_id,
            "retrieval_complete": False,
            "support_eligible": False,
            "ineligibility_reason": "fetch failed before a usable source body was saved",
            "fetch_error": safe_error,
            "artifact": None,
            "parsed_text": None,
            "parsed_text_sha256": None,
            "parser_name": None,
            "parser_version": RUNTIME_VERSION,
            "acquisition_type": "runtime_fetch",
            "transport_attestation": "runtime_rejected",
        }
        receipt_rel = _register_source(
            workspace,
            ledger,
            failure_receipt,
            tier=args.tier,
            role=args.role,
            published=args.published,
            origin_id=args.origin_id,
            freshness_status="unknown",
            freshness_rationale="fetch failed; currentness was not established",
        )
        _update_state(workspace, stage="evidence_blocked")
        _append_event(
            workspace,
            "source_fetch_failed",
            {"source_id": args.source_id, "error": safe_error},
        )
        print(receipt_rel)
        print(f"ERROR: {safe_error}", file=sys.stderr)
        return 1
    body: bytes = result.pop("body")
    accessed_at = (
        existing_transaction.get("receipt_snapshot", {}).get("accessed_at")
        if existing_transaction is not None
        else utc_now()
    )
    artifact_rel = f"artifacts/{args.source_id}.bin"
    artifact_path = safe_workspace_path(workspace, artifact_rel)

    extraction = extract_evidence_text(body, result["content_type"])
    text = extraction["text"]
    parser_name = extraction["parser_name"]
    parser_version = extraction["parser_version"]
    parser_error = extraction["error"]
    parsed_rel = None
    parsed_hash = None
    if text is not None:
        parsed_rel = f"artifacts/{args.source_id}.txt"
        parsed_bytes = text.encode("utf-8")
        parsed_hash = sha256_bytes(parsed_bytes)

    support_eligible = (
        200 <= result["http_status"] < 300
        and bool(body)
        and text is not None
        and parser_error is None
    )
    if support_eligible:
        ineligibility_reason = None
    elif not 200 <= result["http_status"] < 300:
        ineligibility_reason = f"HTTP status {result['http_status']} is not successful"
    elif not body:
        ineligibility_reason = "source body is empty"
    elif parser_error:
        ineligibility_reason = f"text extraction failed: {parser_error}"
    else:
        ineligibility_reason = "unsupported media type or empty parsed text"
    requested_url, requested_query_hash = sanitize_url_for_receipt(result["requested_url"])
    final_url, final_query_hash = sanitize_url_for_receipt(result["final_url"])
    receipt = {
        "receipt_version": RECEIPT_VERSION,
        "runtime_version": RUNTIME_VERSION,
        "source_id": args.source_id,
        "requested_url": requested_url,
        "requested_url_query_sha256": requested_query_hash,
        "final_url": final_url,
        "final_url_query_sha256": final_query_hash,
        "resolved_ip": result["resolved_ip"],
        "accessed_at": accessed_at,
        "http_status": result["http_status"],
        "content_type": result["content_type"],
        "content_encoding": dict((k.lower(), v) for k, v in result["headers"]).get("content-encoding", "identity"),
        "bytes_read": len(body),
        "content_sha256": sha256_bytes(body),
        "headers_sha256": _header_hash(result["headers"]),
        "redirect_chain": sanitize_redirect_chain(result["redirect_chain"]),
        "origin_id": args.origin_id,
        "retrieval_complete": True,
        "support_eligible": support_eligible,
        "ineligibility_reason": ineligibility_reason,
        "artifact": artifact_rel,
        "parsed_text": parsed_rel,
        "parsed_text_sha256": parsed_hash,
        "parser_name": parser_name,
        "parser_version": parser_version,
        "parser_error": parser_error,
        "acquisition_type": "runtime_fetch",
        "transport_attestation": "dns_pinned_runtime",
    }
    receipt["receipt_sha256"] = compute_receipt_sha256(receipt)
    source_record = _source_ledger_record(
        args.source_id,
        f"receipts/{args.source_id}.json",
        tier=args.tier,
        role=args.role,
        published=args.published,
        origin_id=args.origin_id,
        freshness_status=args.freshness,
        freshness_rationale=args.freshness_rationale or "",
    )
    transaction_path, transaction = _begin_or_resume_source_transaction(
        workspace, source_record, receipt
    )
    _write_new_or_verify_private_bytes(artifact_path, body)
    if text is not None and parsed_rel is not None:
        _write_new_or_verify_private_bytes(
            safe_workspace_path(workspace, parsed_rel), text.encode("utf-8")
        )
    _advance_source_transaction(transaction_path, transaction, "artifacts_saved")
    receipt_rel = _register_source(
        workspace,
        ledger,
        receipt,
        tier=args.tier,
        role=args.role,
        published=args.published,
        origin_id=args.origin_id,
        freshness_status=args.freshness,
        freshness_rationale=args.freshness_rationale or "",
    )
    _update_state(workspace, stage="evidence_collected")
    _append_event(
        workspace,
        "source_fetched",
        {
            "source_id": args.source_id,
            "final_url": receipt["final_url"],
            "receipt_sha256": receipt["receipt_sha256"],
        },
    )
    print(receipt_rel)
    return 0 if support_eligible else 1


def cmd_check(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    gate = validate_workspace(workspace)
    gate_path = safe_workspace_path(workspace, "gate.json")
    _write_json(gate_path, gate)
    _update_state(
        workspace,
        stage="gated",
        verdict=gate["verdict"],
        bundle_sha256=gate.get("bundle_sha256"),
        gate_sha256=sha256_file(gate_path),
    )
    _append_event(workspace, "checked", {"verdict": gate["verdict"], "errors": len(gate["errors"])})
    print(json.dumps(gate, ensure_ascii=False, indent=2))
    return 0 if gate["verdict"] == "PASS" else 1


def cmd_render(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    ledger, _ = _load_workspace(workspace)
    scope = ledger.get("scope") if isinstance(ledger.get("scope"), dict) else {}
    if scope.get("triggered") is False:
        raise AuditError(
            "not-triggered inputs do not produce audit reports; use next to record the routing result"
        )
    gate_path = safe_workspace_path(workspace, "gate.json")
    if not gate_path.is_file():
        raise AuditError("a current gate.json is required; run check before render")
    state = _read_json(safe_workspace_path(workspace, "state.json"))
    if _gate_integrity_status(workspace, state) != "PASS":
        raise AuditError("saved gate integrity failed; run check again before render")
    prior_gate = _read_json(gate_path)
    if prior_gate.get("verdict") != "PASS":
        raise AuditError("the saved gate did not pass; run check after fixing the ledger")
    current_bundle_sha256 = compute_workspace_manifest_sha256(workspace)
    if prior_gate.get("bundle_sha256") != current_bundle_sha256:
        raise AuditError("the saved gate is stale because the ledger or evidence changed; run check again")

    ledger, receipts = _load_workspace(workspace)
    gate = validate_workspace(workspace)
    if gate["verdict"] != "PASS":
        _write_json(safe_workspace_path(workspace, "gate.json"), gate)
        _update_state(
            workspace,
            stage="gated",
            verdict=gate["verdict"],
            bundle_sha256=gate.get("bundle_sha256"),
            gate_sha256=sha256_file(gate_path),
        )
        raise AuditError("current bundle does not pass validation; report was not rendered")
    report = render_markdown(ledger, receipts, gate)
    output_rel = args.output or "report.md"
    output_path = safe_report_output_path(workspace, output_rel)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_private_text(output_path, report)
    _update_state(
        workspace,
        stage="rendered",
        verdict="PASS",
        bundle_sha256=gate.get("bundle_sha256"),
        gate_sha256=sha256_file(gate_path),
    )
    state = _read_json(safe_workspace_path(workspace, "state.json"))
    state["report"] = output_rel
    state["report_sha256"] = sha256_file(output_path)
    state["report_bundle_sha256"] = gate.get("bundle_sha256")
    _write_json(safe_workspace_path(workspace, "state.json"), state)
    _append_event(workspace, "rendered", {"output": output_rel, "report_sha256": state["report_sha256"]})
    print(output_path)
    return 0


def cmd_finish(args: argparse.Namespace) -> int:
    """Run the deterministic gate and render only when the current bundle passes."""
    workspace = Path(args.workspace).resolve()
    ledger, _ = _load_workspace(workspace)
    scope = ledger.get("scope") if isinstance(ledger.get("scope"), dict) else {}
    if scope.get("triggered") is False:
        raise AuditError(
            "not-triggered inputs do not produce audit reports; use next to record the routing result"
        )
    check_result = cmd_check(argparse.Namespace(workspace=args.workspace))
    if check_result != 0:
        return check_result
    return cmd_render(argparse.Namespace(workspace=args.workspace, output=args.output))


def _report_is_current(
    workspace: Path, state: dict[str, Any], bundle_sha256: str
) -> bool:
    gate_path = safe_workspace_path(workspace, "gate.json")
    if _gate_integrity_status(workspace, state) != "PASS" or not gate_path.is_file():
        return False
    try:
        gate = _read_json(gate_path)
        if gate.get("verdict") != "PASS" or gate.get("bundle_sha256") != bundle_sha256:
            return False
        report_rel = state.get("report")
        report_hash = state.get("report_sha256")
        if not isinstance(report_rel, str) or not isinstance(report_hash, str):
            return False
        return (
            state.get("report_bundle_sha256") == bundle_sha256
            and sha256_file(safe_workspace_path(workspace, report_rel)) == report_hash
        )
    except (AuditError, FileNotFoundError):
        return False


def _missing_evidence_purposes(claim: dict[str, Any]) -> list[str]:
    required = {"substantive", "source_identity"}
    if claim.get("claim_type") in {"causal", "research_finding"}:
        required.add("study_design")
    if claim.get("temporal_sensitivity") == "high":
        required.add("currentness")
    present = {
        item.get("evidence_purpose", "substantive")
        for item in claim.get("evidence", [])
        if isinstance(item, dict)
        and item.get("support") in {"direct", "partial", "conflict"}
    }
    return sorted(required - present)


def build_next_payload(workspace: Path) -> dict[str, Any]:
    """Return one read-only, structured workflow transition.

    The payload deliberately contains no shell command strings. Candidate and
    claim text are data fields only, so callers can choose their own safe
    argument transport instead of evaluating generated code.
    """

    ledger, receipts = _load_workspace(workspace)
    scope = ledger.get("scope") if isinstance(ledger.get("scope"), dict) else {}
    claims = [item for item in ledger.get("claims", []) if isinstance(item, dict)]
    base: dict[str, Any] = {
        "workflow_version": "1.0",
        "runtime_version": RUNTIME_VERSION,
        "audit_id": ledger.get("audit_id"),
        "complete": False,
        "stage": "unknown",
        "next_steps": [],
    }

    if scope.get("triggered") is False:
        base.update(complete=True, stage="not_triggered")
        return base

    unreviewed = scope.get("unreviewed_claims")
    if not isinstance(unreviewed, list):
        unreviewed = []
    if unreviewed or not claims:
        base["stage"] = "claim_extraction"
        inventory_by_text = {
            item.get("text"): item
            for item in scope.get("candidate_inventory", [])
            if isinstance(item, dict)
        }
        next_steps: list[dict[str, Any]] = []
        for candidate_text in unreviewed:
            candidate = inventory_by_text.get(candidate_text, {})
            origin = candidate.get("origin", "declared")
            if origin == "auto_gap":
                next_steps.append(
                    {
                        "action": "classify_candidate",
                        "cli_subcommand": "exclude-candidate",
                        "required_inputs": [
                            "--workspace",
                            "--candidate-id",
                            "--classification",
                            "--reason",
                        ],
                        "why": "The runtime found an untouched input unit. If it is factual, use claim --file; exclude it only when it is genuinely outside factual-audit scope.",
                        "candidate_id": candidate.get("candidate_id"),
                        "candidate_sha256": candidate.get("sha256"),
                        "candidate_origin": origin,
                        "factual_alternative": {
                            "cli_subcommand": "claim",
                            "required_inputs": ["--workspace", "--file"],
                        },
                        "allowed_exclusions": sorted(ALLOWED_EXCLUSION_CLASSES),
                    }
                )
            else:
                next_steps.append(
                    {
                        "action": "add_claim",
                        "cli_subcommand": "claim",
                        "required_inputs": ["--workspace", "--file"],
                        "why": "Every declared factual candidate must map to at least one atomic claim supplied through a JSON file.",
                        "candidate_id": candidate.get("candidate_id"),
                        "candidate_sha256": candidate.get("sha256"),
                        "candidate_origin": origin,
                        "missing_fields": [
                            "claim_id",
                            "text",
                            "claim_type",
                            "temporal_sensitivity",
                            "criteria",
                            "requires_independent_evidence",
                            "risk_domain",
                            "causal_basis",
                            "next_step",
                            "input_candidates",
                        ],
                    }
                )
        if not next_steps:
            next_steps.append(
                {
                    "action": "add_claim",
                    "cli_subcommand": "claim",
                    "required_inputs": ["--workspace", "--file"],
                    "why": "A triggered audit requires at least one atomic claim.",
                    "candidate_id": None,
                }
            )
        base["next_steps"] = next_steps
        return base

    pending_claims = [
        claim for claim in claims if claim.get("assessment_recorded") is not True
    ]
    if pending_claims:
        base["stage"] = "claim_assessment"
        next_steps: list[dict[str, Any]] = []
        for claim in pending_claims:
            evidence = claim.get("evidence")
            has_linked_evidence = isinstance(evidence, list) and bool(evidence)
            next_steps.append(
                {
                    "action": "assess",
                    "cli_subcommand": "assess",
                    "required_inputs": ["--workspace", "--file"],
                    "why": (
                        "Linked evidence changed or has not been assessed."
                        if has_linked_evidence
                        else "No linked eligible evidence exists; open the highest-value source or record an honest unknown."
                    ),
                    "claim_id": claim.get("claim_id"),
                    "missing_evidence_purposes": _missing_evidence_purposes(claim),
                    "suggested_action": claim.get("next_step") or "Record the highest-information next verification action.",
                    "source_count": len(receipts),
                }
            )
        base["next_steps"] = next_steps
        return base

    pending_counterchecks = [
        claim for claim in claims if not _countercheck_is_current(claim)
    ]
    if pending_counterchecks:
        base["stage"] = "claim_countercheck"
        base["next_steps"] = [
            {
                "action": "countercheck",
                "cli_subcommand": "countercheck",
                "required_inputs": ["--workspace", "--file"],
                "required_options": ["--workspace", "--file"],
                "why": "Freeze the strongest practical falsifier and what was actually checked before summarizing the claim.",
                "claim_id": claim.get("claim_id"),
                "missing_fields": [
                    "falsifier",
                    "checked_source_ids",
                    "result",
                    "stop_reason",
                ],
                "runtime_generated_fields": ["checked_at", "basis_hash"],
            }
            for claim in pending_counterchecks
        ]
        return base

    if ledger.get("summary_recorded") is not True:
        base["stage"] = "audit_summary"
        base["next_steps"] = [
            {
                "action": "summarize",
                "cli_subcommand": "summarize",
                "required_inputs": ["--workspace", "--file"],
                "why": "All claims are assessed, but the current cross-claim unknowns and highest-value next action are not frozen.",
                "claim_ids": [claim.get("claim_id") for claim in claims],
            }
        ]
        return base

    gate = validate_workspace(workspace)
    if gate.get("verdict") != "PASS":
        linked_source_ids = {
            item.get("source_id")
            for claim in claims
            for item in claim.get("evidence", [])
            if isinstance(item, dict)
        }
        recoverable_sources = [
            source.get("source_id")
            for source in ledger.get("sources", [])
            if isinstance(source, dict)
            and source.get("active") is not False
            and source.get("source_id") not in linked_source_ids
            and receipts.get(source.get("source_id"), {}).get("support_eligible") is False
        ]
        abortable_transactions: list[str] = []
        transaction_root = safe_workspace_path(workspace, "source-transactions")
        if transaction_root.is_dir():
            registered_source_ids = {
                source.get("source_id")
                for source in ledger.get("sources", [])
                if isinstance(source, dict)
            }
            for transaction_path in sorted(transaction_root.glob("*.json")):
                try:
                    transaction = _read_json(transaction_path)
                except AuditError:
                    continue
                source_id = transaction.get("source_id")
                if (
                    isinstance(source_id, str)
                    and source_id not in registered_source_ids
                    and transaction.get("status")
                    in ALLOWED_SOURCE_TRANSACTION_STATUSES - {"committed", "aborted"}
                ):
                    abortable_transactions.append(source_id)
        base["stage"] = "gate_repair"
        base["next_steps"] = [
            {
                "action": "repair_gate",
                "cli_subcommand": "check",
                "required_inputs": ["--workspace"],
                "why": "Deterministic integrity or policy gates still fail.",
                "errors": copy.deepcopy(gate.get("errors", [])),
                "recoverable_sources": recoverable_sources,
                "abortable_transactions": abortable_transactions,
            }
        ]
        base["next_steps"].extend(
            {
                "action": "abort_source_transaction",
                "cli_subcommand": "abort-source-transaction",
                "required_inputs": ["--workspace", "--source-id", "--reason"],
                "why": "Use only when the exact frozen source acquisition can no longer be reproduced; the journal and any saved bytes remain preserved.",
                "source_id": source_id,
            }
            for source_id in abortable_transactions
        )
        return base

    bundle_sha256 = str(gate.get("bundle_sha256"))
    state = _read_json(safe_workspace_path(workspace, "state.json"))
    if _report_is_current(workspace, state, bundle_sha256):
        base.update(complete=True, stage="complete")
        return base

    base["stage"] = "ready_to_finish"
    base["next_steps"] = [
        {
            "action": "finish",
            "cli_subcommand": "finish",
            "required_inputs": ["--workspace"],
            "why": "The current bundle passes policy gates but is not bound to a current rendered report.",
            "bundle_sha256": bundle_sha256,
        }
    ]
    return base


def cmd_next(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    print(json.dumps(build_next_payload(workspace), ensure_ascii=False, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    state = _read_json(safe_workspace_path(workspace, "state.json"))
    payload = copy.deepcopy(state)
    payload["workflow"] = build_next_payload(workspace)
    gate_path = safe_workspace_path(workspace, "gate.json")
    gate_current = False
    gate_integrity = _gate_integrity_status(workspace, state)
    payload["gate_integrity"] = gate_integrity
    if gate_path.is_file() and gate_integrity == "PASS":
        try:
            gate = _read_json(gate_path)
            gate_current = gate.get("bundle_sha256") == compute_workspace_manifest_sha256(
                workspace
            )
            if gate_current:
                payload["verdict"] = gate.get("verdict")
        except (AuditError, FileNotFoundError):
            gate_current = False
    payload["gate_current"] = gate_current
    if not gate_current and gate_path.exists():
        payload["verdict"] = "STALE"
        payload.pop("report", None)
        payload.pop("report_sha256", None)
    report_rel = state.get("report")
    report_hash = state.get("report_sha256")
    report_bundle_hash = state.get("report_bundle_sha256")
    if gate_current and isinstance(report_rel, str) and isinstance(report_hash, str):
        try:
            report_current = (
                sha256_file(safe_workspace_path(workspace, report_rel)) == report_hash
                and report_bundle_hash == gate.get("bundle_sha256")
            )
        except (AuditError, FileNotFoundError):
            report_current = False
        payload["report_current"] = report_current
        if not report_current:
            payload["verdict"] = "STALE"
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    stale_gate = gate_path.exists() and not gate_current
    return 1 if stale_gate or payload.get("report_current") is False else 0


def cmd_replay(args: argparse.Namespace) -> int:
    workspace = Path(args.workspace).resolve()
    gate = validate_workspace(workspace)
    errors = list(gate["errors"])
    state = _read_json(safe_workspace_path(workspace, "state.json"))
    saved_gate_integrity = _gate_integrity_status(workspace, state)
    saved_gate_current = False
    if saved_gate_integrity == "FAIL":
        _error(
            errors,
            "GATE_HASH_MISMATCH",
            "gate.json",
            "saved gate no longer matches the state record",
        )
    elif saved_gate_integrity == "PASS":
        try:
            saved_gate = _read_json(safe_workspace_path(workspace, "gate.json"))
            saved_gate_current = saved_gate.get("bundle_sha256") == gate.get(
                "bundle_sha256"
            )
        except (AuditError, FileNotFoundError):
            saved_gate_current = False
        if not saved_gate_current:
            _error(
                errors,
                "GATE_STALE",
                "gate.json.bundle_sha256",
                "saved gate does not bind the current input and evidence bundle",
            )
    report_rel = state.get("report")
    report_hash = state.get("report_sha256")
    report_bundle_hash = state.get("report_bundle_sha256")
    report_integrity = "NOT_RENDERED"
    if isinstance(report_rel, str) and isinstance(report_hash, str):
        try:
            report_path = safe_workspace_path(workspace, report_rel)
            report_integrity = (
                "PASS"
                if sha256_file(report_path) == report_hash
                and report_bundle_hash == gate.get("bundle_sha256")
                else "FAIL"
            )
        except (AuditError, FileNotFoundError):
            report_integrity = "FAIL"
        if report_integrity == "FAIL":
            _error(
                errors,
                "REPORT_HASH_MISMATCH",
                "report",
                "rendered report no longer matches the state record",
            )
        elif report_integrity == "PASS":
            try:
                ledger, receipts = _load_workspace(workspace)
                saved_gate = _read_json(
                    safe_workspace_path(workspace, "gate.json")
                )
                canonical_report = render_markdown(ledger, receipts, saved_gate)
                if report_path.read_text(encoding="utf-8") != canonical_report:
                    report_integrity = "FAIL"
                    _error(
                        errors,
                        "REPORT_CANONICAL_MISMATCH",
                        "report",
                        "saved report is not the deterministic rendering of the current ledger, receipts, and gate",
                    )
            except (AuditError, FileNotFoundError, UnicodeDecodeError):
                report_integrity = "FAIL"
                _error(
                    errors,
                    "REPORT_CANONICAL_MISMATCH",
                    "report",
                    "saved report could not be reproduced from the current audit bundle",
                )
    elif isinstance(state.get("stale_reports"), list) and state["stale_reports"]:
        stale_report = state["stale_reports"][-1]
        stale_rel = stale_report.get("report")
        stale_hash = stale_report.get("report_sha256")
        if isinstance(stale_rel, str) and isinstance(stale_hash, str):
            try:
                stale_hash_matches = (
                    sha256_file(safe_workspace_path(workspace, stale_rel)) == stale_hash
                )
            except (AuditError, FileNotFoundError):
                stale_hash_matches = False
            report_integrity = "STALE" if stale_hash_matches else "FAIL"
            if not stale_hash_matches:
                _error(
                    errors,
                    "STALE_REPORT_HASH_MISMATCH",
                    "stale_reports[-1]",
                    "archived stale report no longer matches its recorded hash",
                )
        else:
            report_integrity = "STALE"
    elif safe_workspace_path(workspace, "report.md").exists():
        report_integrity = "STALE_UNTRACKED"
    historical_integrity = "PASS" if not errors else "FAIL"
    payload = {
        "replayed_at": utc_now(),
        "historical_integrity": historical_integrity,
        "evidence_bundle_integrity": "PASS" if gate["verdict"] == "PASS" else "FAIL",
        "saved_gate_integrity": saved_gate_integrity,
        "saved_gate_current": saved_gate_current,
        "report_integrity": report_integrity,
        "bundle_sha256": gate.get("bundle_sha256"),
        "current_freshness_rechecked": False,
        "boundary": "Replay verifies saved observations and policy consistency; it does not refresh current facts.",
        "errors": errors,
        "warnings": gate["warnings"],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if historical_integrity == "PASS" else 1


def cmd_doctor(_: argparse.Namespace) -> int:
    pdf_tool = shutil.which("pdftotext")
    print(
        json.dumps(
            {
                "runtime_version": RUNTIME_VERSION,
                "policy_version": POLICY_VERSION,
                "python": sys.version.split()[0],
                "standard_library_only": True,
                "python_dependencies": "standard library only",
                "workspace_locking": "fcntl advisory lock",
                "pdf_parser": str(pdf_tool) if pdf_tool else None,
                "pdf_support": "available" if pdf_tool else "fail_closed_unavailable",
                "network_policy": "public HTTP(S), ports 80/443, DNS-pinned per hop",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claim_audit.py",
        description="Create an evidence-backed, machine-gated AI claim audit.",
    )
    parser.add_argument("--version", action="version", version=RUNTIME_VERSION)
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="create a resumable audit workspace")
    init_parser.add_argument("--input", required=True, help="AI answer or claim text file")
    init_parser.add_argument("--workspace", required=True, help="new audit workspace directory")
    init_parser.add_argument("--as-of", help="verification date in YYYY-MM-DD")
    init_parser.add_argument("--audit-id", help="stable audit identifier")
    init_parser.set_defaults(func=cmd_init)

    start_parser = subparsers.add_parser(
        "start", help="initialize and positively scope an audit in one command"
    )
    start_parser.add_argument("--input", required=True, help="AI answer or claim text file")
    start_parser.add_argument("--workspace", required=True, help="new audit workspace directory")
    start_parser.add_argument("--as-of", help="verification date in YYYY-MM-DD")
    start_parser.add_argument("--audit-id", help="stable audit identifier")
    start_parser.add_argument("--reason", required=True, help="why factual auditing triggered")
    start_candidates = start_parser.add_mutually_exclusive_group(required=True)
    start_candidates.add_argument(
        "--candidate",
        action="append",
        help="one atomic factual clause to account for; repeat for every candidate",
    )
    start_candidates.add_argument(
        "--candidates-file",
        help="JSON object containing a candidates array; preferred for untrusted text",
    )
    start_parser.set_defaults(func=cmd_start)

    scope_parser = subparsers.add_parser("scope", help="record whether factual auditing is triggered")
    scope_parser.add_argument("--workspace", required=True)
    scope_group = scope_parser.add_mutually_exclusive_group(required=True)
    scope_group.add_argument("--triggered", action="store_true")
    scope_group.add_argument("--not-triggered", dest="triggered", action="store_false")
    scope_parser.add_argument("--reason", required=True)
    scope_parser.add_argument(
        "--candidate",
        dest="unreviewed",
        action="append",
        help="candidate factual clause not yet entered",
    )
    scope_parser.set_defaults(func=cmd_scope)

    exclude_parser = subparsers.add_parser(
        "exclude-candidate",
        help="classify a frozen review unit as non-factual and preserve the reason",
    )
    exclude_parser.add_argument("--workspace", required=True)
    exclude_target = exclude_parser.add_mutually_exclusive_group(required=True)
    exclude_target.add_argument("--candidate")
    exclude_target.add_argument(
        "--candidate-id", help="frozen candidate identifier; preferred over raw text"
    )
    exclude_parser.add_argument(
        "--classification",
        choices=sorted(ALLOWED_EXCLUSION_CLASSES),
        required=True,
    )
    exclude_parser.add_argument("--reason", required=True)
    exclude_parser.set_defaults(func=cmd_exclude_candidate)

    claim_parser = subparsers.add_parser("claim", help="add or explicitly replace one structured claim")
    claim_parser.add_argument("--workspace", required=True)
    claim_parser.add_argument("--file", required=True, help="claim JSON object")
    claim_parser.add_argument("--replace", action="store_true")
    claim_parser.set_defaults(func=cmd_claim)

    add_claim_parser = subparsers.add_parser(
        "add-claim", help="add one atomic claim without an intermediate JSON file"
    )
    add_claim_parser.add_argument("--workspace", required=True)
    add_claim_parser.add_argument("--claim-id", required=True)
    add_claim_parser.add_argument("--text", required=True)
    add_claim_parser.add_argument(
        "--type", dest="claim_type", choices=sorted(ALLOWED_CLAIM_TYPES), required=True
    )
    add_claim_parser.add_argument("--temporal", choices=["low", "medium", "high"], required=True)
    add_claim_parser.add_argument("--as-of")
    add_claim_parser.add_argument("--criterion", action="append", required=True)
    add_claim_parser.add_argument("--failure-condition", required=True)
    add_claim_parser.add_argument("--requires-independent-evidence", action="store_true")
    add_claim_parser.add_argument(
        "--risk-domain", choices=["none", "medical", "legal", "financial"], default="none"
    )
    add_claim_parser.add_argument(
        "--causal-basis", choices=sorted(ALLOWED_CAUSAL_BASIS_VALUES), default="not_applicable"
    )
    add_claim_parser.add_argument("--next-step", required=True)
    add_claim_parser.add_argument(
        "--covers",
        action="append",
        required=True,
        help="the one exact frozen input candidate covered by this atomic claim",
    )
    add_claim_parser.add_argument(
        "--keep-candidate-open",
        action="store_true",
        help="keep a compound candidate open while adding more atomic claims",
    )
    add_claim_parser.add_argument("--replace", action="store_true")
    add_claim_parser.set_defaults(func=cmd_add_claim)

    evidence_parser = subparsers.add_parser("evidence", help="link a registered source to a claim")
    evidence_parser.add_argument("--workspace", required=True)
    evidence_parser.add_argument("--file", required=True, help="evidence-link JSON object")
    evidence_parser.set_defaults(func=cmd_evidence)

    link_parser = subparsers.add_parser(
        "link", help="link evidence and bind an exact saved quote in one command"
    )
    link_parser.add_argument("--workspace", required=True)
    link_parser.add_argument("--claim-id", required=True)
    link_parser.add_argument("--source-id", required=True)
    link_parser.add_argument(
        "--support", choices=["direct", "partial", "conflict", "context", "none"], required=True
    )
    link_parser.add_argument(
        "--purpose",
        choices=sorted(ALLOWED_EVIDENCE_PURPOSES),
        default="substantive",
        help="what this exact excerpt is evidence for",
    )
    link_parser.add_argument("--support-scope", required=True)
    link_parser.add_argument("--exact")
    link_parser.add_argument("--excerpt")
    link_parser.add_argument("--locator")
    link_parser.add_argument("--occurrence", type=int)
    link_parser.add_argument("--inference-span", type=int, required=True)
    link_parser.set_defaults(func=cmd_link)

    assess_parser = subparsers.add_parser(
        "assess", help="update decision fields without replacing claims or linked evidence"
    )
    assess_parser.add_argument("--workspace", required=True)
    assess_parser.add_argument("--file", required=True, help="assessment JSON object")
    assess_parser.set_defaults(func=cmd_assess)

    decide_parser = subparsers.add_parser(
        "decide", help="set decision gates and status without an intermediate JSON file"
    )
    decide_parser.add_argument("--workspace", required=True)
    decide_parser.add_argument("--claim-id", required=True)
    decide_parser.add_argument(
        "--identity-gate", choices=["pass", "fail", "unknown"], required=True
    )
    decide_parser.add_argument(
        "--content-gate", choices=["pass", "partial", "fail", "unknown"], required=True
    )
    decide_parser.add_argument(
        "--action-gate",
        choices=["pass", "insufficient", "professional_review", "not_applicable", "unknown"],
        required=True,
    )
    decide_parser.add_argument("--status", choices=sorted(ALLOWED_STATUSES), required=True)
    decide_parser.add_argument("--confidence-reason", required=True)
    decide_parser.add_argument("--conflict", action="append")
    decide_parser.add_argument("--next-step", required=True)
    decide_parser.add_argument("--unknown", action="append", required=True)
    decide_parser.add_argument("--next-action", required=True)
    decide_parser.add_argument("--causal-basis")
    decide_parser.add_argument("--as-of")
    decide_parser.set_defaults(func=cmd_decide)

    countercheck_parser = subparsers.add_parser(
        "countercheck",
        help="record an explicit falsification attempt bound to the current claim state",
    )
    countercheck_parser.add_argument("--workspace", required=True)
    countercheck_parser.add_argument(
        "--file", required=True, help="countercheck JSON object"
    )
    countercheck_parser.set_defaults(func=cmd_countercheck)

    summarize_parser = subparsers.add_parser(
        "summarize", help="write the explicit cross-claim unknowns and next action"
    )
    summarize_parser.add_argument("--workspace", required=True)
    summarize_parser.add_argument("--file", help="summary JSON object")
    summarize_parser.add_argument("--unknown", action="append")
    summarize_parser.add_argument("--next-action")
    summarize_parser.set_defaults(func=cmd_summarize)

    quote_parser = subparsers.add_parser(
        "quote", help="locate an exact excerpt and compute its reproducible selector"
    )
    quote_parser.add_argument("--workspace", required=True)
    quote_parser.add_argument("--source-id", required=True)
    quote_parser.add_argument("--exact", required=True)
    quote_parser.add_argument("--occurrence", type=int)
    quote_parser.set_defaults(func=cmd_quote)

    capture_parser = subparsers.add_parser(
        "capture", help="capture source bytes opened by an external browser or trusted local tool"
    )
    capture_parser.add_argument("--workspace", required=True)
    capture_parser.add_argument("--source-id", required=True)
    capture_parser.add_argument("--file", required=True)
    capture_parser.add_argument("--requested-url", required=True)
    capture_parser.add_argument("--final-url", required=True)
    capture_parser.add_argument("--http-status", type=int, required=True)
    capture_parser.add_argument("--content-type", required=True)
    capture_parser.add_argument("--accessed-at")
    capture_parser.add_argument("--tier", required=True, choices=["A1", "A2", "B", "C"])
    capture_parser.add_argument(
        "--role",
        required=True,
        choices=[
            "original_record",
            "subject_self_report",
            "independent_replication",
            "regulatory_record",
            "professional_analysis",
            "secondary_report",
            "lead_only",
        ],
    )
    capture_parser.add_argument("--published", required=True)
    capture_parser.add_argument("--origin-id", required=True)
    capture_parser.add_argument(
        "--acquisition-type",
        required=True,
        choices=["browser_export", "trusted_local_copy", "user_supplied"],
    )
    capture_parser.add_argument(
        "--freshness", choices=["current", "stale", "unknown"], default="unknown"
    )
    capture_parser.add_argument(
        "--freshness-rationale", help="why this source is current, stale, or unknown"
    )
    capture_parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    capture_parser.set_defaults(func=cmd_capture)

    fetch_parser = subparsers.add_parser("fetch", help="open a public source and create a receipt")
    fetch_parser.add_argument("--workspace", required=True)
    fetch_parser.add_argument("--source-id", required=True)
    fetch_parser.add_argument("--url", required=True)
    fetch_parser.add_argument("--tier", required=True, choices=["A1", "A2", "B", "C"])
    fetch_parser.add_argument(
        "--role",
        required=True,
        choices=[
            "original_record",
            "subject_self_report",
            "independent_replication",
            "regulatory_record",
            "professional_analysis",
            "secondary_report",
            "lead_only",
        ],
    )
    fetch_parser.add_argument("--published", required=True, help="publication date or 'unknown'")
    fetch_parser.add_argument("--origin-id", required=True, help="root evidence origin, not merely this URL")
    fetch_parser.add_argument(
        "--freshness", choices=["current", "stale", "unknown"], default="unknown"
    )
    fetch_parser.add_argument(
        "--freshness-rationale", help="why this source is current, stale, or unknown"
    )
    fetch_parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    fetch_parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)
    fetch_parser.add_argument("--max-redirects", type=int, default=MAX_REDIRECTS)
    fetch_parser.set_defaults(func=cmd_fetch)

    retire_source_parser = subparsers.add_parser(
        "retire-source",
        help="retire an unusable unlinked source while preserving its receipt",
    )
    retire_source_parser.add_argument("--workspace", required=True)
    retire_source_parser.add_argument("--source-id", required=True)
    retire_source_parser.add_argument("--reason", required=True)
    retire_source_parser.set_defaults(func=cmd_retire_source)

    abort_transaction_parser = subparsers.add_parser(
        "abort-source-transaction",
        help="close an unrecoverable partial source transaction without deleting its trace",
    )
    abort_transaction_parser.add_argument("--workspace", required=True)
    abort_transaction_parser.add_argument("--source-id", required=True)
    abort_transaction_parser.add_argument("--reason", required=True)
    abort_transaction_parser.set_defaults(func=cmd_abort_source_transaction)

    check_parser = subparsers.add_parser("check", help="run deterministic integrity and policy gates")
    check_parser.add_argument("--workspace", required=True)
    check_parser.set_defaults(func=cmd_check)

    render_parser = subparsers.add_parser("render", help="render only a currently passing ledger")
    render_parser.add_argument("--workspace", required=True)
    render_parser.add_argument("--output", help="relative report path inside the workspace")
    render_parser.set_defaults(func=cmd_render)

    finish_parser = subparsers.add_parser(
        "finish", help="run the gate and render only when the current bundle passes"
    )
    finish_parser.add_argument("--workspace", required=True)
    finish_parser.add_argument("--output", help="relative report path inside the workspace")
    finish_parser.set_defaults(func=cmd_finish)

    next_parser = subparsers.add_parser(
        "next", help="show the next safe workflow transition without mutating the audit"
    )
    next_parser.add_argument("--workspace", required=True)
    next_parser.set_defaults(func=cmd_next)

    status_parser = subparsers.add_parser("status", help="show resumable run state")
    status_parser.add_argument("--workspace", required=True)
    status_parser.set_defaults(func=cmd_status)

    replay_parser = subparsers.add_parser("replay", help="verify saved evidence without claiming current freshness")
    replay_parser.add_argument("--workspace", required=True)
    replay_parser.set_defaults(func=cmd_replay)

    doctor_parser = subparsers.add_parser("doctor", help="show runtime capabilities")
    doctor_parser.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        workspace = getattr(args, "workspace", None)
        if workspace and args.command not in {"init", "start"}:
            read_only = args.command in {"next", "status", "replay", "quote"}
            with workspace_lock(workspace, exclusive=not read_only):
                return int(args.func(args))
        return int(args.func(args))
    except AuditError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
