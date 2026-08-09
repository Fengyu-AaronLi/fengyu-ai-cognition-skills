#!/usr/bin/env python3
"""Execute the blocker-driven evolution loop and enforce the local release gate.

The controller separates two questions:

1. Is the recorded gate structurally honest and bound to the current artifacts?
2. Is this exact artifact set eligible to be called a local candidate?

Development checks may return success for an honestly blocked or invalidated
iteration. A strict release check succeeds only for zero blockers and four
current, passing internal isolated audits. The legacy `independent_*` audit IDs
do not establish third-party review or actor identity. This command never
publishes anything.
"""

from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import zipfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable, Iterator


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_AUDIT_IDS = (
    "independent_attribution_audit",
    "independent_clinical_safety_audit",
    "independent_state_integrity_audit",
    "release_package_audit",
)
DEMO_FILES = (
    ".case.lock",
    "analysis.json",
    "case.json",
    "demo-input.txt",
    "events.head.json",
    "events.jsonl",
    "report.md",
    "run-manifest.json",
)
SHA256_KEYS = (
    "runtime_sha256",
    "schema_tree_sha256",
    "tests_tree_sha256",
    "demo_tree_sha256",
    "package_tree_sha256",
)
GOVERNANCE_SHA256_KEYS = (
    "governance_tree_sha256",
    "workflow_sha256",
)
GOVERNANCE_FILES = (
    "scripts/run_evolution.py",
    "scripts/build_package.py",
    "scripts/build_demo.py",
    "evals/validate.py",
)
SHA256_HEX = set("0123456789abcdef")
CONTROLLED_COMMAND_ENV = {"PYTHONHASHSEED": "0"}
REPOSITORY_INPUT_PREFIX = "@repository/"


class GateError(RuntimeError):
    """A stable, machine-readable controller failure."""

    def __init__(self, *codes: str) -> None:
        self.codes = list(codes) or ["evolution_gate_error"]
        super().__init__(", ".join(self.codes))


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and set(value).issubset(SHA256_HEX)
    )


def tree_digest(root: Path, paths: Iterable[Path]) -> str:
    records = []
    for path in sorted(paths):
        if not path.is_file() or path.is_symlink():
            raise GateError(f"artifact_not_regular_file:{path}")
        records.append(
            {
                "bytes": path.stat().st_size,
                "path": path.relative_to(root).as_posix(),
                "sha256": sha256_file(path),
            }
        )
    payload = json.dumps(
        records,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256_bytes(payload)


def read_json(path: Path, code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise GateError(f"{code}_missing") from error
    except (OSError, json.JSONDecodeError) as error:
        raise GateError(f"{code}_invalid_json") from error
    if not isinstance(value, dict):
        raise GateError(f"{code}_not_object")
    return value


_SCHEMA_CACHE: dict[str, dict] = {}

SCHEMA_KEYWORDS = {
    "$defs",
    "$id",
    "$ref",
    "$schema",
    "additionalProperties",
    "allOf",
    "const",
    "enum",
    "format",
    "items",
    "maxItems",
    "minItems",
    "minLength",
    "minProperties",
    "minimum",
    "oneOf",
    "pattern",
    "properties",
    "required",
    "title",
    "type",
    "uniqueItems",
}


def schema_definition_errors(schema: object, location: str = "$") -> list[str]:
    """Inventory every schema keyword before applying the local subset."""

    if not isinstance(schema, dict):
        return [f"{location}:schema_not_object"]
    errors: list[str] = []
    for key in schema:
        if key not in SCHEMA_KEYWORDS:
            errors.append(f"{location}:schema_keyword_unknown:{key}")
    for key in ("$schema", "$id", "$ref", "title"):
        if key in schema and (not isinstance(schema[key], str) or not schema[key]):
            errors.append(f"{location}:schema_keyword_value_invalid:{key}")
    reference = schema.get("$ref")
    if isinstance(reference, str) and not reference.startswith("#"):
        target_file, _, fragment = reference.partition("#")
        if (
            re.fullmatch(r"[A-Za-z0-9._-]+\.json", target_file) is None
            or (fragment and not fragment.startswith("/"))
        ):
            errors.append(f"{location}:schema_keyword_value_invalid:$ref")
    expected_type = schema.get("type")
    if expected_type is not None:
        type_values = expected_type if isinstance(expected_type, list) else [expected_type]
        allowed_types = {"object", "array", "string", "integer", "number", "boolean", "null"}
        if (
            not type_values
            or any(not isinstance(value, str) or value not in allowed_types for value in type_values)
            or len(type_values) != len(set(type_values))
        ):
            errors.append(f"{location}:schema_keyword_value_invalid:type")
    required = schema.get("required")
    if required is not None and (
        not isinstance(required, list)
        or any(not isinstance(value, str) or not value for value in required)
        or len(required) != len(set(required))
    ):
        errors.append(f"{location}:schema_keyword_value_invalid:required")
    enum = schema.get("enum")
    if enum is not None and (not isinstance(enum, list) or not enum):
        errors.append(f"{location}:schema_keyword_value_invalid:enum")
    for key in ("minItems", "maxItems", "minLength", "minProperties"):
        if key in schema and (type(schema[key]) is not int or schema[key] < 0):
            errors.append(f"{location}:schema_keyword_value_invalid:{key}")
    if (
        type(schema.get("minItems")) is int
        and type(schema.get("maxItems")) is int
        and schema["maxItems"] < schema["minItems"]
    ):
        errors.append(f"{location}:schema_keyword_value_invalid:maxItems")
    minimum = schema.get("minimum")
    if minimum is not None and (
        not isinstance(minimum, (int, float)) or isinstance(minimum, bool)
    ):
        errors.append(f"{location}:schema_keyword_value_invalid:minimum")
    if "uniqueItems" in schema and not isinstance(schema["uniqueItems"], bool):
        errors.append(f"{location}:schema_keyword_value_invalid:uniqueItems")
    pattern = schema.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str):
            errors.append(f"{location}:schema_keyword_value_invalid:pattern")
        else:
            try:
                re.compile(pattern)
            except re.error:
                errors.append(f"{location}:schema_keyword_value_invalid:pattern")
    if "format" in schema and schema["format"] != "date-time":
        errors.append(f"{location}:schema_keyword_value_invalid:format")
    if "items" in schema and not isinstance(schema["items"], dict):
        errors.append(f"{location}:schema_keyword_value_invalid:items")
    additional = schema.get("additionalProperties")
    if additional is not None and not isinstance(additional, (bool, dict)):
        errors.append(f"{location}:schema_keyword_value_invalid:additionalProperties")
    for container_key in ("properties", "$defs"):
        container = schema.get(container_key)
        if container is None:
            continue
        if not isinstance(container, dict):
            errors.append(f"{location}:{container_key}_invalid")
            continue
        for name, subschema in container.items():
            errors.extend(
                schema_definition_errors(
                    subschema,
                    f"{location}.{container_key}.{name}",
                )
            )
    for child_key in ("items", "additionalProperties"):
        child = schema.get(child_key)
        if isinstance(child, dict):
            errors.extend(
                schema_definition_errors(child, f"{location}.{child_key}")
            )
    for branch_key in ("allOf", "oneOf"):
        branches = schema.get(branch_key)
        if branches is None:
            continue
        if not isinstance(branches, list) or not branches:
            errors.append(f"{location}:{branch_key}_invalid")
            continue
        for index, branch in enumerate(branches):
            errors.extend(
                schema_definition_errors(
                    branch,
                    f"{location}.{branch_key}[{index}]",
                )
            )
    return sorted(set(errors))


def json_value_equal(left: object, right: object) -> bool:
    """Compare JSON values without Python's bool-equals-int coercion."""

    if (
        isinstance(left, (int, float))
        and not isinstance(left, bool)
        and isinstance(right, (int, float))
        and not isinstance(right, bool)
    ):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            json_value_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            json_value_equal(left_item, right_item)
            for left_item, right_item in zip(left, right, strict=True)
        )
    return left == right


def schema_document(name: str) -> dict:
    if name not in _SCHEMA_CACHE:
        path = DEFAULT_ROOT / "schemas" / name
        _SCHEMA_CACHE[name] = read_json(path, f"schema_{Path(name).stem}")
    return _SCHEMA_CACHE[name]


def schema_pointer(document: dict, fragment: str) -> object:
    value: object = document
    if fragment in {"", "#"}:
        return value
    pointer = fragment.removeprefix("#")
    if not pointer.startswith("/"):
        raise GateError("schema_reference_invalid")
    for encoded in pointer[1:].split("/"):
        key = encoded.replace("~1", "/").replace("~0", "~")
        if not isinstance(value, dict) or key not in value:
            raise GateError("schema_reference_invalid")
        value = value[key]
    return value


def json_type_matches(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def schema_validation_errors(instance: object, schema_name: str) -> list[str]:
    """Validate the JSON-Schema subset used by this repository.

    The project remains standard-library only.  This validator intentionally
    supports exactly the keywords inventoried in ``schemas/*.json``; unknown
    assertion keywords fail closed instead of being silently ignored.
    """

    document = schema_document(schema_name)
    definition_errors = schema_definition_errors(document)
    if definition_errors:
        return definition_errors

    def validate(
        value: object,
        schema: object,
        current_name: str,
        current_document: dict,
        location: str,
    ) -> list[str]:
        if not isinstance(schema, dict):
            return [f"{location}:schema_not_object"]
        errors: list[str] = []
        reference = schema.get("$ref")
        if reference is not None:
            if not isinstance(reference, str):
                return [f"{location}:ref_invalid"]
            if reference.startswith("#"):
                target_name = current_name
                target_document = current_document
                fragment = reference
            else:
                target_file, separator, suffix = reference.partition("#")
                target_name = target_file
                target_document = schema_document(target_file)
                fragment = f"#{suffix}" if separator else "#"
            target = schema_pointer(target_document, fragment)
            errors.extend(
                validate(
                    value,
                    target,
                    target_name,
                    target_document,
                    location,
                )
            )

        all_of = schema.get("allOf")
        if all_of is not None:
            if not isinstance(all_of, list):
                errors.append(f"{location}:allOf_invalid")
            else:
                for branch in all_of:
                    errors.extend(
                        validate(value, branch, current_name, current_document, location)
                    )

        one_of = schema.get("oneOf")
        if one_of is not None:
            if not isinstance(one_of, list):
                errors.append(f"{location}:oneOf_invalid")
            else:
                matches = sum(
                    not validate(value, branch, current_name, current_document, location)
                    for branch in one_of
                )
                if matches != 1:
                    errors.append(f"{location}:oneOf")

        expected_type = schema.get("type")
        if expected_type is not None:
            type_options = (
                expected_type if isinstance(expected_type, list) else [expected_type]
            )
            if not all(isinstance(item, str) for item in type_options) or not any(
                json_type_matches(value, item) for item in type_options
            ):
                errors.append(f"{location}:type")
                return errors
        if "const" in schema and not json_value_equal(value, schema["const"]):
            errors.append(f"{location}:const")
        enum = schema.get("enum")
        if enum is not None and (
            not isinstance(enum, list)
            or not any(json_value_equal(value, member) for member in enum)
        ):
            errors.append(f"{location}:enum")

        if isinstance(value, dict):
            required = schema.get("required", [])
            if isinstance(required, list):
                for key in required:
                    if key not in value:
                        errors.append(f"{location}.{key}:required")
            else:
                errors.append(f"{location}:required_invalid")
            properties = schema.get("properties", {})
            if not isinstance(properties, dict):
                errors.append(f"{location}:properties_invalid")
                properties = {}
            for key, subschema in properties.items():
                if key in value:
                    errors.extend(
                        validate(
                            value[key],
                            subschema,
                            current_name,
                            current_document,
                            f"{location}.{key}",
                        )
                    )
            additional = schema.get("additionalProperties", True)
            extra_keys = set(value) - set(properties)
            if additional is False and extra_keys:
                errors.append(f"{location}:additionalProperties")
            elif isinstance(additional, dict):
                for key in extra_keys:
                    errors.extend(
                        validate(
                            value[key],
                            additional,
                            current_name,
                            current_document,
                            f"{location}.{key}",
                        )
                    )
            minimum_properties = schema.get("minProperties")
            if isinstance(minimum_properties, int) and len(value) < minimum_properties:
                errors.append(f"{location}:minProperties")

        if isinstance(value, list):
            minimum_items = schema.get("minItems")
            maximum_items = schema.get("maxItems")
            if isinstance(minimum_items, int) and len(value) < minimum_items:
                errors.append(f"{location}:minItems")
            if isinstance(maximum_items, int) and len(value) > maximum_items:
                errors.append(f"{location}:maxItems")
            if schema.get("uniqueItems") is True:
                if any(
                    json_value_equal(value[left], value[right])
                    for left in range(len(value))
                    for right in range(left + 1, len(value))
                ):
                    errors.append(f"{location}:uniqueItems")
            item_schema = schema.get("items")
            if item_schema is not None:
                for index, item in enumerate(value):
                    errors.extend(
                        validate(
                            item,
                            item_schema,
                            current_name,
                            current_document,
                            f"{location}[{index}]",
                        )
                    )

        if isinstance(value, str):
            minimum_length = schema.get("minLength")
            if isinstance(minimum_length, int) and len(value) < minimum_length:
                errors.append(f"{location}:minLength")
            pattern = schema.get("pattern")
            if isinstance(pattern, str) and re.search(pattern, value) is None:
                errors.append(f"{location}:pattern")
            if schema.get("format") == "date-time":
                if re.fullmatch(
                    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})",
                    value,
                ) is None:
                    errors.append(f"{location}:date-time")
                else:
                    try:
                        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                        if parsed.tzinfo is None:
                            errors.append(f"{location}:date-time")
                    except ValueError:
                        errors.append(f"{location}:date-time")

        minimum = schema.get("minimum")
        if (
            isinstance(minimum, (int, float))
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value < minimum
        ):
            errors.append(f"{location}:minimum")
        return errors

    return sorted(set(validate(instance, document, schema_name, document, "$")))


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    with tempfile.NamedTemporaryFile(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, delete=False
    ) as handle:
        staging = Path(handle.name)
        handle.write(payload)
        handle.flush()
    try:
        staging.replace(path)
    finally:
        if staging.exists():
            staging.unlink()


def write_immutable_bytes(path: Path, payload: bytes, code: str) -> None:
    """Create one evidence snapshot without permitting an in-place rewrite."""

    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as error:
        raise GateError(f"{code}_refuses_overwrite") from error
    except OSError as error:
        raise GateError(f"{code}_write_failed") from error
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


def workflow_snapshot_path(run_dir: Path) -> Path:
    return run_dir / "snapshots" / "workflow.json"


def command_script_snapshot_path(run_dir: Path, step_id: str) -> Path:
    return run_dir / "snapshots" / "commands" / step_id / "script.py"


def command_input_snapshot_path(run_dir: Path, step_id: str, index: int) -> Path:
    return run_dir / "snapshots" / "commands" / step_id / "inputs" / f"{index:04d}.bin"


@contextmanager
def evolution_run_lock(
    run_dir: Path,
    *,
    exclusive: bool,
    create_parent: bool = False,
) -> Iterator[None]:
    """Serialize cooperating readers and writers for one evolution run."""

    parent = run_dir.parent
    if create_parent:
        parent.mkdir(parents=True, exist_ok=True)
    if not parent.is_dir() or parent.is_symlink():
        raise GateError("evolution_run_lock_invalid")
    lock_path = parent / f".{run_dir.name}.evolution.lock"
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise GateError("evolution_run_lock_invalid") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise GateError("evolution_run_lock_invalid")
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise GateError("evolution_run_locked") from error
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


@contextmanager
def release_state_lock(
    state_path: Path,
    *,
    exclusive: bool,
    create_parent: bool = False,
) -> Iterator[None]:
    """Serialize every cooperating read or mutation of one release state.

    The lock is anchored beside the canonical state path instead of on the
    state inode itself because ``write_json`` publishes through atomic replace.
    Locking the replaceable inode would allow two writers to hold locks on
    different generations and both report success.
    """

    state_path = state_path.expanduser().resolve()
    parent = state_path.parent
    if create_parent:
        parent.mkdir(parents=True, exist_ok=True)
    if not parent.is_dir() or parent.is_symlink() or state_path.is_symlink():
        raise GateError("release_state_lock_invalid")
    lock_path = parent / f".{state_path.name}.release.lock"
    flags = os.O_RDWR | os.O_CREAT
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as error:
        raise GateError("release_state_lock_invalid") from error
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise GateError("release_state_lock_invalid")
        operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
        try:
            fcntl.flock(descriptor, operation | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise GateError("release_state_locked") from error
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def controlled_command_environment() -> dict[str, str]:
    return dict(CONTROLLED_COMMAND_ENV)


def resolve_within(root: Path, value: str, code: str) -> Path:
    pure = PurePosixPath(value)
    if pure.is_absolute() or ".." in pure.parts:
        raise GateError(f"{code}_unsafe_path")
    target = (root / pure).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as error:
        raise GateError(f"{code}_unsafe_path") from error
    return target


def resolve_scoped_input(root: Path, value: str, code: str) -> Path:
    """Resolve a Skill input or an explicitly scoped candidate-repository input."""

    if not isinstance(value, str):
        raise GateError(f"{code}_unsafe_path")
    if not value.startswith(REPOSITORY_INPUT_PREFIX):
        return resolve_within(root, value, code)
    relative = value[len(REPOSITORY_INPUT_PREFIX) :]
    repository_root = root.resolve().parents[1]
    return resolve_within(repository_root, relative, code)


def scoped_input_reference(root: Path, path: Path, code: str) -> str:
    """Return the stable receipt reference for a Skill or repository input."""

    target = path.resolve()
    try:
        return target.relative_to(root.resolve()).as_posix()
    except ValueError:
        repository_root = root.resolve().parents[1]
        try:
            relative = target.relative_to(repository_root)
        except ValueError as error:
            raise GateError(f"{code}_unsafe_path") from error
        return REPOSITORY_INPUT_PREFIX + relative.as_posix()


def package_tree_digest(root: Path) -> str:
    builder = root / "scripts" / "build_package.py"
    if not builder.is_file():
        raise GateError("package_builder_missing")
    with tempfile.TemporaryDirectory(prefix="identity-evolution-package-") as temp:
        output = Path(temp) / "candidate-package"
        result = subprocess.run(
            [sys.executable, str(builder), "build", "--out", str(output)],
            cwd=root,
            text=True,
            capture_output=True,
            check=False,
        )
    if result.returncode != 0:
        raise GateError("package_snapshot_failed")
    try:
        summary = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise GateError("package_snapshot_invalid_json") from error
    digest = summary.get("tree_sha256")
    if not is_sha256(digest):
        raise GateError("package_snapshot_missing_hash")
    return digest


def collect_snapshot(
    root: Path,
    workflow_path: Path | None = None,
    *,
    strict: bool = True,
) -> dict[str, str]:
    root = root.expanduser().resolve()
    runtime = root / "scripts" / "identity_label_case.py"
    runtime_available = runtime.is_file() and not runtime.is_symlink()
    if strict and not runtime_available:
        raise GateError("runtime_missing")
    schemas = sorted((root / "schemas").glob("*.json"))
    tests = test_inventory_paths(root)
    demo = [root / "examples" / "real-run" / name for name in DEMO_FILES]
    errors = []
    if strict and not schemas:
        errors.append("schema_inventory_empty")
    if strict and not tests:
        errors.append("test_inventory_empty")
    missing_demo = [path.name for path in demo if not path.is_file()]
    if strict and missing_demo:
        errors.append("demo_inventory_missing:" + ",".join(missing_demo))
    if errors:
        raise GateError(*errors)
    snapshot = {
        "runtime_sha256": (
            sha256_file(runtime)
            if runtime_available
            else sha256_bytes(b"missing:scripts/identity_label_case.py")
        ),
        "schema_tree_sha256": tree_digest(root, schemas),
        "tests_tree_sha256": tree_digest(root, tests),
        "demo_tree_sha256": tree_digest(
            root,
            [path for path in demo if path.is_file() and not path.is_symlink()],
        ),
    }
    try:
        snapshot["package_tree_sha256"] = package_tree_digest(root)
    except GateError:
        if strict:
            raise
        builder = root / "scripts" / "build_package.py"
        snapshot["package_tree_sha256"] = (
            sha256_file(builder)
            if builder.is_file() and not builder.is_symlink()
            else sha256_bytes(b"missing:scripts/build_package.py")
        )
    if workflow_path is not None:
        workflow = load_evolution_workflow(root, workflow_path)
        snapshot_run_dir = root / "evals" / ".evolution-snapshot"
        preflight_evolution_commands(root, snapshot_run_dir, workflow)
        command_scripts = [
            Path(expand_evolution_argv(root, snapshot_run_dir, step)[1])
            for step in workflow["steps"]
            if step["kind"] == "command"
        ]
        governance = list(
            dict.fromkeys(
                [root / relative for relative in GOVERNANCE_FILES]
                + command_scripts
            )
        )
        missing_governance = [
            relative
            for relative, path in zip(
                GOVERNANCE_FILES,
                governance[: len(GOVERNANCE_FILES)],
                strict=True,
            )
            if not path.is_file() or path.is_symlink()
        ]
        if strict and missing_governance:
            raise GateError(
                "governance_inventory_missing:" + ",".join(missing_governance)
            )
        if not workflow_path.is_file() or workflow_path.is_symlink():
            raise GateError("evolution_workflow_missing")
        snapshot.update(
            {
                "governance_tree_sha256": tree_digest(
                    root,
                    [
                        path
                        for path in governance
                        if path.is_file() and not path.is_symlink()
                    ],
                ),
                "workflow_sha256": sha256_file(workflow_path),
            }
        )
    return snapshot


def generation_for(path: str) -> str:
    name = PurePosixPath(path).name
    match = re.match(r"test_(v[1-9][0-9]*)_", name)
    if match:
        return match.group(1)
    return "core"


def test_inventory_paths(root: Path) -> list[Path]:
    """Return every regular byte that can influence the registered test suite."""

    tests_root = root / "tests"
    return sorted(
        path
        for path in tests_root.rglob("*")
        if path.is_file()
        and not path.is_symlink()
        and "__pycache__" not in path.parts
        and path.suffix != ".pyc"
    )


def current_test_support_records(root: Path) -> list[dict]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in test_inventory_paths(root)
        if not (
            path.parent == root / "tests"
            and path.name.startswith("test_")
            and path.suffix == ".py"
        )
    ]


def current_test_records(root: Path) -> list[dict]:
    return [
        {
            "generation": generation_for(path.relative_to(root).as_posix()),
            "path": path.relative_to(root).as_posix(),
            "sha256": sha256_file(path),
        }
        for path in sorted((root / "tests").glob("test_*.py"))
        if path.is_file() and not path.is_symlink()
    ]


def validate_manifest_migration_history(
    root: Path,
    manifest: dict,
    *,
    pending_receipts: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    records = manifest.get("files", [])
    if not isinstance(records, list):
        return ["test_migration_history_invalid"]

    allowed_hashes_by_test: dict[str, set[str]] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            continue
        allowed = allowed_hashes_by_test.setdefault(record["path"], set())
        if is_sha256(record.get("sha256")):
            allowed.add(record["sha256"])
        history = record.get("migration_history", [])
        if isinstance(history, list):
            for entry in history:
                if not isinstance(entry, dict):
                    continue
                for field in ("from_sha256", "to_sha256"):
                    if is_sha256(entry.get(field)):
                        allowed.add(entry[field])

    referenced_receipts: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        history = record.get("migration_history", [])
        if not isinstance(history, list):
            errors.append("test_migration_history_invalid")
            continue
        previous_to: str | None = None
        for entry in history:
            if not isinstance(entry, dict):
                errors.append("test_migration_history_invalid")
                continue
            relative = entry.get("receipt_path")
            expected_hash = entry.get("receipt_sha256")
            if not isinstance(relative, str) or not relative.startswith(
                "evals/test-migrations/"
            ) or not relative.endswith(".json"):
                errors.append("test_migration_receipt_missing")
                continue
            if relative in referenced_receipts:
                errors.append("test_migration_receipt_reused")
            referenced_receipts.add(relative)
            try:
                path = resolve_within(root, relative, "test_migration_receipt")
            except (GateError, TypeError):
                errors.append("test_migration_receipt_missing")
                continue
            if not path.is_file() or path.is_symlink():
                errors.append("test_migration_receipt_missing")
            elif not is_sha256(expected_hash) or sha256_file(path) != expected_hash:
                errors.append("test_migration_receipt_hash_mismatch")
            else:
                try:
                    receipt = read_json(path, "test_migration_receipt")
                except GateError:
                    errors.append("test_migration_receipt_schema_invalid")
                else:
                    if schema_validation_errors(
                        receipt, "test-migration-receipt.schema.json"
                    ):
                        errors.append("test_migration_receipt_schema_invalid")
                    elif (
                        receipt.get("test_path") != record.get("path")
                        or receipt.get("from_sha256") != entry.get("from_sha256")
                        or receipt.get("to_sha256") != entry.get("to_sha256")
                    ):
                        errors.append("test_migration_receipt_semantic_mismatch")

                    for evidence in receipt.get("evidence", []):
                        if not isinstance(evidence, dict):
                            errors.append("test_migration_receipt_evidence_missing")
                            continue
                        try:
                            evidence_path = resolve_within(
                                root,
                                evidence.get("path"),
                                "test_migration_receipt_evidence",
                            )
                        except (GateError, TypeError):
                            errors.append("test_migration_receipt_evidence_missing")
                            continue
                        if not evidence_path.is_file() or evidence_path.is_symlink():
                            errors.append("test_migration_receipt_evidence_missing")
                        elif (
                            not is_sha256(evidence.get("sha256"))
                            or sha256_file(evidence_path) != evidence.get("sha256")
                        ):
                            errors.append(
                                "test_migration_receipt_evidence_hash_mismatch"
                            )

                    for replacement in receipt.get("replacement_tests", []):
                        if not isinstance(replacement, dict):
                            errors.append("test_migration_receipt_replacement_missing")
                            continue
                        replacement_relative = replacement.get("path")
                        try:
                            replacement_path = resolve_within(
                                root,
                                replacement_relative,
                                "test_migration_receipt_replacement",
                            )
                        except (GateError, TypeError):
                            errors.append("test_migration_receipt_replacement_missing")
                            continue
                        if (
                            not replacement_path.is_file()
                            or replacement_path.is_symlink()
                        ):
                            errors.append("test_migration_receipt_replacement_missing")
                            continue
                        declared_hash = replacement.get("sha256")
                        allowed_hashes = allowed_hashes_by_test.get(
                            replacement_relative, set()
                        )
                        if not is_sha256(declared_hash) or (
                            sha256_file(replacement_path) != declared_hash
                            and declared_hash not in allowed_hashes
                        ):
                            errors.append(
                                "test_migration_receipt_replacement_hash_mismatch"
                            )
            if previous_to is not None and entry.get("from_sha256") != previous_to:
                errors.append("test_migration_history_chain_invalid")
            previous_to = entry.get("to_sha256")
        if history and previous_to != record.get("sha256"):
            errors.append("test_migration_history_head_mismatch")

    receipt_dir = root / "evals" / "test-migrations"
    if receipt_dir.is_dir() and not receipt_dir.is_symlink():
        available_receipts = {
            path.relative_to(root).as_posix()
            for path in receipt_dir.glob("*.json")
            if path.is_file() and not path.is_symlink()
        }
        permitted_pending = pending_receipts or set()
        if available_receipts - referenced_receipts - permitted_pending:
            errors.append("test_migration_receipt_unreferenced")
    return sorted(set(errors))


def validate_test_manifest(
    root: Path,
    manifest: dict,
    *,
    permitted_pending_receipts: set[str] | None = None,
) -> list[str]:
    errors: list[str] = []
    if schema_validation_errors(manifest, "test-generation-manifest.schema.json"):
        errors.append("test_manifest_schema_invalid")
    errors.extend(
        validate_manifest_migration_history(
            root,
            manifest,
            pending_receipts=permitted_pending_receipts,
        )
    )
    if manifest.get("schema_version") != "1.0":
        errors.append("test_manifest_schema_version")
    records = manifest.get("files")
    if not isinstance(records, list):
        return errors + ["test_manifest_files_not_list"]

    declared: dict[str, dict] = {}
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            errors.append("test_manifest_invalid_record")
            continue
        relative = record["path"]
        if relative in declared:
            errors.append("test_manifest_duplicate_file")
            continue
        try:
            path = resolve_within(root, relative, "test_manifest")
        except GateError as error:
            errors.extend(error.codes)
            continue
        declared[relative] = record
        if not path.is_file() or path.is_symlink():
            errors.append("test_manifest_missing_file")
        elif record.get("sha256") != sha256_file(path):
            errors.append("test_manifest_hash_mismatch")
        if record.get("generation") != generation_for(relative):
            errors.append("test_manifest_generation_mismatch")

    actual = {
        path.relative_to(root).as_posix()
        for path in (root / "tests").glob("test_*.py")
        if path.is_file() and not path.is_symlink()
    }
    if actual - set(declared):
        errors.append("test_manifest_unregistered_file")
    if set(declared) - actual and "test_manifest_missing_file" not in errors:
        errors.append("test_manifest_missing_file")

    actual_support = {
        record["path"] for record in current_test_support_records(root)
    }
    support_records = manifest.get("support_files")
    if support_records is None and not actual_support:
        support_records = []
    elif not isinstance(support_records, list):
        errors.append("test_manifest_support_files_not_list")
        support_records = []
    declared_support: dict[str, dict] = {}
    for record in support_records:
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "sha256"}
            or not isinstance(record.get("path"), str)
            or not is_sha256(record.get("sha256"))
        ):
            errors.append("test_manifest_invalid_support_record")
            continue
        relative = record["path"]
        if relative in declared_support:
            errors.append("test_manifest_duplicate_support_file")
            continue
        try:
            path = resolve_within(root, relative, "test_manifest_support")
        except GateError as error:
            errors.extend(error.codes)
            continue
        declared_support[relative] = record
        if (
            not relative.startswith("tests/")
            or relative.startswith("tests/test_")
            or "__pycache__" in PurePosixPath(relative).parts
        ):
            errors.append("test_manifest_invalid_support_path")
        if not path.is_file() or path.is_symlink():
            errors.append("test_manifest_support_missing")
        elif sha256_file(path) != record["sha256"]:
            errors.append("test_manifest_support_hash_mismatch")
    if actual_support - set(declared_support):
        errors.append("test_manifest_unregistered_support_file")
    if set(declared_support) - actual_support:
        errors.append("test_manifest_support_missing")

    rules = manifest.get("generation_rules")
    if not isinstance(rules, list):
        errors.append("test_manifest_generation_rules_not_list")
    else:
        rule_generations: set[str] = set()
        for rule in rules:
            if not isinstance(rule, dict):
                errors.append("test_manifest_invalid_generation_rule")
                continue
            generation = rule.get("generation")
            pattern = rule.get("pattern")
            minimum = rule.get("minimum")
            if (
                not isinstance(generation, str)
                or not isinstance(pattern, str)
                or not isinstance(minimum, int)
                or minimum < 1
            ):
                errors.append("test_manifest_invalid_generation_rule")
                continue
            if generation in rule_generations:
                errors.append("test_manifest_duplicate_generation_rule")
            rule_generations.add(generation)
            count = sum(
                1
                for path in root.glob(pattern)
                if path.is_file() and not path.is_symlink()
            )
            if count < minimum:
                errors.append(f"test_generation_below_minimum:{generation}")
        declared_generations = {
            record.get("generation")
            for record in records
            if isinstance(record, dict)
            and isinstance(record.get("generation"), str)
            and record.get("generation") != "core"
        }
        for generation in sorted(declared_generations - rule_generations):
            errors.append(f"test_manifest_generation_rule_missing:{generation}")
    return sorted(set(errors))


def validate_artifact_hashes(
    value: object,
    prefix: str,
    *,
    require_governance: bool = False,
) -> list[str]:
    if not isinstance(value, dict):
        return [f"{prefix}_not_object"]
    errors = []
    required_keys = set(SHA256_KEYS)
    allowed_keys = required_keys | set(GOVERNANCE_SHA256_KEYS)
    if require_governance:
        required_keys = allowed_keys
    if not required_keys.issubset(value) or set(value) - allowed_keys:
        errors.append(f"{prefix}_keys")
    for key in required_keys:
        if not is_sha256(value.get(key)):
            errors.append(f"{prefix}_{key}")
    return errors


def validate_audit_receipt(
    root: Path,
    relative: object,
    expected_audit_id: str,
    state: dict,
    *,
    enforce_current_contract: bool = False,
) -> tuple[list[str], dict | None, Path | None]:
    """Validate one structured receipt and derive its status from blockers."""

    root = root.expanduser().resolve()
    if not isinstance(relative, str):
        return ["audit_receipt_required"], None, None
    try:
        path = resolve_within(root, relative, "audit_receipt")
    except GateError:
        return ["audit_receipt_required"], None, None
    try:
        receipt_root = (root / "evals" / "receipts").resolve()
        path.relative_to(receipt_root)
    except ValueError:
        return ["audit_receipt_required"], None, path
    if path.suffix.lower() != ".json" or not path.is_file() or path.is_symlink():
        return ["audit_receipt_required"], None, path
    try:
        receipt = read_json(path, "audit_receipt")
    except GateError:
        return ["audit_receipt_required"], None, path

    errors: list[str] = []
    if schema_validation_errors(receipt, "audit-receipt.schema.json"):
        errors.append("audit_receipt_schema_invalid")
    receipt_version = receipt.get("schema_version")
    if receipt_version not in {"1.0", "1.1", "1.2"}:
        errors.append("audit_receipt_schema_version")
    if enforce_current_contract and receipt_version != "1.2":
        errors.append("audit_receipt_current_schema_required")
    if not isinstance(receipt.get("receipt_id"), str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}",
        receipt["receipt_id"],
    ):
        errors.append("audit_receipt_id_invalid")
    if receipt.get("audit_id") != expected_audit_id:
        errors.append("audit_receipt_type_mismatch")
    candidate = receipt.get("candidate")
    if not isinstance(candidate, dict) or (
        candidate.get("candidate_id") != state.get("candidate_id")
        or candidate.get("artifacts") != state.get("artifacts")
        or candidate.get("test_manifest_sha256") != state.get("test_manifest_sha256")
    ):
        errors.append("audit_receipt_candidate_mismatch")
    expected_completed_run = state.get("completed_run")
    receipt_completed_run = receipt.get("completed_run")
    if expected_completed_run is not None and not isinstance(
        expected_completed_run, dict
    ):
        errors.append("audit_receipt_completed_run_state_invalid")
    elif isinstance(expected_completed_run, dict):
        if receipt_version not in {"1.1", "1.2"} or not isinstance(receipt_completed_run, dict):
            errors.append("audit_receipt_completed_run_required")
        else:
            if (
                receipt_completed_run.get("run_state_sha256")
                != expected_completed_run.get("run_state_sha256")
            ):
                errors.append("audit_receipt_run_state_hash_mismatch")
            if (
                receipt_completed_run.get("event_count")
                != expected_completed_run.get("event_count")
                or receipt_completed_run.get("event_head_sha256")
                != expected_completed_run.get("event_head_sha256")
            ):
                errors.append("audit_receipt_event_head_mismatch")
            if (
                receipt_completed_run.get("receipt_tree_sha256")
                != expected_completed_run.get("receipt_tree_sha256")
            ):
                errors.append("audit_receipt_receipt_tree_mismatch")
            if (
                receipt_completed_run.get("completed_artifacts")
                != expected_completed_run.get("completed_artifacts")
            ):
                errors.append("audit_receipt_completed_artifacts_mismatch")
            if receipt_completed_run != expected_completed_run:
                errors.append("audit_receipt_completed_run_mismatch")
            if (
                not isinstance(candidate, dict)
                or receipt_completed_run.get("candidate_id")
                != candidate.get("candidate_id")
                or receipt_completed_run.get("candidate_id")
                != state.get("candidate_id")
                or receipt_completed_run.get("completed_artifacts")
                != candidate.get("artifacts")
                or receipt_completed_run.get("completed_artifacts")
                != state.get("artifacts")
                or receipt_completed_run.get("workflow_sha256")
                != candidate.get("artifacts", {}).get("workflow_sha256")
            ):
                errors.append(
                    "audit_receipt_completed_run_cross_binding_mismatch"
                )
    elif receipt_version in {"1.1", "1.2"} or receipt_completed_run is not None:
        errors.append("audit_receipt_completed_run_required")
    receipt_evidence_root = (
        root / "evals" / "receipts" / str(receipt.get("receipt_id", "invalid"))
    ).resolve()

    def validate_file_reference(relative_value: object, hash_value: object) -> None:
        if not isinstance(relative_value, str) or not relative_value:
            errors.append("audit_receipt_evidence_path_invalid")
            return
        try:
            evidence_path = resolve_within(
                root,
                relative_value,
                "audit_receipt_evidence",
            )
            evidence_path.relative_to(receipt_evidence_root)
        except GateError:
            errors.append("audit_receipt_evidence_path_invalid")
            return
        except ValueError:
            errors.append("audit_receipt_evidence_scope_invalid")
            return
        if not evidence_path.is_file() or evidence_path.is_symlink():
            errors.append("audit_receipt_evidence_missing")
            return
        if not is_sha256(hash_value) or sha256_file(evidence_path) != hash_value:
            errors.append("audit_receipt_evidence_hash_mismatch")

    preregistration = receipt.get("preregistration")
    if not isinstance(preregistration, dict) or not is_sha256(preregistration.get("case_set_sha256")):
        errors.append("audit_receipt_preregistration_invalid")
    else:
        validate_file_reference(
            preregistration.get("path"),
            preregistration.get("case_set_sha256"),
        )
    environment = receipt.get("environment")
    if not isinstance(environment, dict) or not is_sha256(environment.get("sha256")):
        errors.append("audit_receipt_environment_invalid")
    else:
        validate_file_reference(environment.get("path"), environment.get("sha256"))
    commands = receipt.get("commands")
    if not isinstance(commands, list) or not commands:
        errors.append("audit_receipt_commands_invalid")
        commands = []
    for command in commands:
        if (
            not isinstance(command, dict)
            or not isinstance(command.get("argv"), list)
            or not command["argv"]
            or not all(isinstance(token, str) and token for token in command["argv"])
            or not isinstance(command.get("exit_code"), int)
            or not is_sha256(command.get("stdout_sha256"))
            or not is_sha256(command.get("stderr_sha256"))
        ):
            errors.append("audit_receipt_command_invalid")
            continue
        if receipt_version == "1.2":
            script_relative = command.get("script_path")
            script_sha256 = command.get("script_sha256")
            try:
                script_path = resolve_within(
                    root,
                    script_relative,
                    "audit_receipt_script",
                )
            except (GateError, TypeError):
                errors.append("audit_receipt_script_invalid")
                script_path = None
            if (
                script_path is None
                or not script_path.is_file()
                or script_path.is_symlink()
                or not is_sha256(script_sha256)
                or sha256_file(script_path) != script_sha256
                or len(command["argv"]) < 2
                or Path(command["argv"][1]).expanduser().resolve() != script_path
            ):
                errors.append("audit_receipt_script_hash_mismatch")

            snapshot = command.get("input_snapshot")
            if (
                not isinstance(snapshot, dict)
                or set(snapshot) != {"cwd", "environment", "files"}
                or snapshot.get("cwd") != "."
                or snapshot.get("environment") != controlled_command_environment()
                or not isinstance(snapshot.get("files"), list)
                or not snapshot["files"]
            ):
                errors.append("audit_receipt_input_snapshot_invalid")
            else:
                saved_paths: list[str] = []
                for item in snapshot["files"]:
                    if (
                        not isinstance(item, dict)
                        or set(item) != {"path", "sha256"}
                        or not isinstance(item.get("path"), str)
                        or not is_sha256(item.get("sha256"))
                    ):
                        errors.append("audit_receipt_input_snapshot_invalid")
                        continue
                    saved_paths.append(item["path"])
                    try:
                        input_path = resolve_scoped_input(
                            root,
                            item["path"],
                            "audit_receipt_input",
                        )
                    except GateError:
                        errors.append("audit_receipt_input_snapshot_invalid")
                        continue
                    if (
                        not input_path.is_file()
                        or input_path.is_symlink()
                        or sha256_file(input_path) != item["sha256"]
                    ):
                        errors.append("audit_receipt_input_hash_mismatch")
                if saved_paths != sorted(set(saved_paths)):
                    errors.append("audit_receipt_input_snapshot_invalid")
        validate_file_reference(
            command.get("stdout_path"),
            command.get("stdout_sha256"),
        )
        validate_file_reference(
            command.get("stderr_path"),
            command.get("stderr_sha256"),
        )
    if enforce_current_contract and receipt_version == "1.2":
        try:
            prereg_path = resolve_within(
                root,
                preregistration.get("path") if isinstance(preregistration, dict) else "",
                "audit_receipt_preregistration",
            )
            prereg_value = read_json(prereg_path, "audit_receipt_preregistration")
        except (GateError, TypeError):
            errors.append("audit_receipt_preregistration_invalid")
        else:
            required_preregistration_keys = {
                "schema_version",
                "audit_id",
                "candidate_id",
                "completed_run_sha256",
                "objective",
                "commands",
                "pass_condition",
                "live_model_called",
            }
            prereg_commands = prereg_value.get("commands")
            if (
                set(prereg_value) != required_preregistration_keys
                or prereg_value.get("schema_version") != "1.0"
                or prereg_value.get("audit_id") != expected_audit_id
                or prereg_value.get("candidate_id") != state.get("candidate_id")
                or prereg_value.get("completed_run_sha256")
                != state.get("completed_run", {}).get("run_state_sha256")
                or not isinstance(prereg_value.get("objective"), str)
                or not prereg_value["objective"].strip()
                or not isinstance(prereg_value.get("pass_condition"), str)
                or not prereg_value["pass_condition"].strip()
                or prereg_value.get("live_model_called") is not False
                or not isinstance(prereg_commands, list)
                or len(prereg_commands) != len(commands)
            ):
                errors.append("audit_receipt_preregistration_contract_invalid")
            else:
                for prereg_command, command in zip(
                    prereg_commands,
                    commands,
                    strict=True,
                ):
                    if (
                        not isinstance(prereg_command, dict)
                        or set(prereg_command) != {"argv", "input_files"}
                        or not isinstance(prereg_command.get("argv"), list)
                        or not prereg_command["argv"]
                        or not all(
                            isinstance(token, str) and token
                            for token in prereg_command["argv"]
                        )
                        or not isinstance(prereg_command.get("input_files"), list)
                        or not prereg_command["input_files"]
                        or not all(
                            isinstance(item, str) and item
                            for item in prereg_command["input_files"]
                        )
                    ):
                        errors.append("audit_receipt_preregistration_contract_invalid")
                        continue
                    rendered_argv = [
                        token.replace("{evidence_dir}", str(receipt_evidence_root))
                        for token in prereg_command["argv"]
                    ]
                    try:
                        expected_script = resolve_within(
                            root,
                            rendered_argv[0],
                            "audit_receipt_preregistered_script",
                        )
                    except GateError:
                        errors.append("audit_receipt_preregistered_command_mismatch")
                    else:
                        actual_argv = command.get("argv", [])
                        if (
                            len(actual_argv) != len(rendered_argv) + 1
                            or Path(actual_argv[1]).expanduser().resolve()
                            != expected_script
                            or actual_argv[2:] != rendered_argv[1:]
                            or command.get("script_path")
                            != expected_script.relative_to(root).as_posix()
                        ):
                            errors.append(
                                "audit_receipt_preregistered_command_mismatch"
                            )

                    expected_inputs: list[str] = []
                    for template in prereg_command["input_files"]:
                        rendered = template.replace(
                            "{evidence_dir}", str(receipt_evidence_root)
                        )
                        if "{" in rendered or "}" in rendered or "\x00" in rendered:
                            errors.append(
                                "audit_receipt_preregistered_input_mismatch"
                            )
                            continue
                        candidate_path = Path(rendered)
                        try:
                            if candidate_path.is_absolute():
                                input_path = candidate_path.expanduser().resolve()
                                scoped_input_reference(
                                    root,
                                    input_path,
                                    "audit_receipt_preregistered_input",
                                )
                            else:
                                input_path = resolve_scoped_input(
                                    root,
                                    rendered,
                                    "audit_receipt_preregistered_input",
                                )
                        except (GateError, ValueError):
                            errors.append(
                                "audit_receipt_preregistered_input_mismatch"
                            )
                            continue
                        expected_inputs.append(
                            scoped_input_reference(
                                root,
                                input_path,
                                "audit_receipt_preregistered_input",
                            )
                        )
                    snapshot = command.get("input_snapshot")
                    observed_inputs = (
                        [item.get("path") for item in snapshot.get("files", [])]
                        if isinstance(snapshot, dict)
                        and isinstance(snapshot.get("files"), list)
                        else []
                    )
                    if (
                        expected_inputs != list(dict.fromkeys(expected_inputs))
                        or sorted(expected_inputs) != observed_inputs
                    ):
                        errors.append("audit_receipt_preregistered_input_mismatch")
    if not is_sha256(receipt.get("raw_output_sha256")):
        errors.append("audit_receipt_raw_output_invalid")
    else:
        validate_file_reference(
            receipt.get("raw_output_path"),
            receipt.get("raw_output_sha256"),
        )
    if not isinstance(receipt.get("manual_findings"), list):
        errors.append("audit_receipt_findings_invalid")
    blockers = receipt.get("blockers")
    if not isinstance(blockers, list):
        errors.append("audit_receipt_blockers_invalid")
        blockers = []
    for blocker in blockers:
        if (
            not isinstance(blocker, dict)
            or blocker.get("severity") not in {"P0", "P1", "P2"}
            or not isinstance(blocker.get("id"), str)
            or not blocker["id"]
        ):
            errors.append("audit_receipt_blocker_invalid")
    derived_status = "passed" if not blockers else "blocked"
    if receipt.get("status") != derived_status:
        errors.append("audit_receipt_status_mismatch")
    if derived_status == "passed" and any(command.get("exit_code") != 0 for command in commands):
        errors.append("audit_receipt_passing_command_failed")
    return sorted(set(errors)), receipt, path


def expected_recorded_decision(state: dict) -> str:
    blocker_count = state.get("blocker_count")
    audits = state.get("audits")
    if isinstance(blocker_count, int) and blocker_count > 0:
        return "blocked"
    if not isinstance(audits, list):
        return "pending"
    statuses = {audit.get("status") for audit in audits if isinstance(audit, dict)}
    if statuses == {"passed"} and blocker_count == 0:
        return "candidate"
    if "blocked" in statuses:
        return "blocked"
    return "pending"


def completed_run_receipt_tree(root: Path, run_dir: Path) -> str:
    receipts_dir = run_dir / "receipts"
    receipts = sorted(
        path
        for path in receipts_dir.rglob("*.json")
        if path.is_file() and not path.is_symlink()
    )
    if not receipts:
        raise GateError("release_completed_run_receipts_missing")
    return tree_digest(root, receipts)


def completed_run_binding(root: Path, run_dir: Path, run_state: dict) -> dict:
    return {
        "run_dir": run_dir.relative_to(root).as_posix(),
        "run_id": run_state["run_id"],
        "candidate_id": run_state["candidate_id"],
        "workflow_id": run_state["workflow_id"],
        "workflow_path": run_state["workflow_path"],
        "workflow_sha256": run_state["workflow_sha256"],
        "run_state_sha256": sha256_file(run_dir / "run-state.json"),
        "event_count": run_state["event_count"],
        "event_head_sha256": run_state["event_head_sha256"],
        "receipt_tree_sha256": completed_run_receipt_tree(root, run_dir),
        "completed_artifacts": copy.deepcopy(run_state["completed_artifacts"]),
    }


def validate_carry_over_bindings(root: Path, state: dict) -> None:
    public = state.get("carry_over_blockers", [])
    bindings = state.get("carry_over_blocker_bindings", [])
    if not isinstance(public, list) or not isinstance(bindings, list):
        raise GateError("evolution_carry_over_binding_invalid")
    projected: list[dict] = []
    seen: set[str] = set()
    for binding in bindings:
        if (
            not isinstance(binding, dict)
            or set(binding)
            != {"id", "severity", "evidence", "evidence_sha256", "status"}
            or binding.get("status") != "open"
            or binding.get("severity") not in {"P0", "P1", "P2"}
            or not isinstance(binding.get("id"), str)
            or not binding["id"]
            or binding["id"] in seen
            or not isinstance(binding.get("evidence"), str)
            or not is_sha256(binding.get("evidence_sha256"))
        ):
            raise GateError("evolution_carry_over_binding_invalid")
        seen.add(binding["id"])
        evidence = resolve_within(
            root,
            binding["evidence"],
            "evolution_carry_over_evidence",
        )
        if (
            not evidence.is_file()
            or evidence.is_symlink()
            or sha256_file(evidence) != binding["evidence_sha256"]
        ):
            raise GateError("evolution_carry_over_evidence_hash_mismatch")
        projected.append(
            {
                "id": binding["id"],
                "severity": binding["severity"],
                "evidence": binding["evidence"],
            }
        )
    if public != projected:
        raise GateError("evolution_carry_over_binding_invalid")


def blocker_resolution_path(root: Path, value: object, code: str) -> tuple[Path, str]:
    if isinstance(value, Path):
        supplied = value
    elif isinstance(value, str) and value:
        supplied = Path(value)
    else:
        raise GateError(f"{code}_missing")
    path = resolve_supplied_path(root, supplied, code)
    try:
        relative = path.relative_to(root).as_posix()
    except ValueError as error:
        raise GateError(f"{code}_unsafe_path") from error
    return path, relative


def validate_resolution_evidence(
    root: Path,
    items: object,
    *,
    evidence_root: Path,
) -> set[str]:
    if not isinstance(items, list) or not items:
        raise GateError("evolution_blocker_resolution_evidence_missing")
    paths: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("path"), str):
            raise GateError("evolution_blocker_resolution_evidence_missing")
        evidence = resolve_within(
            root,
            item["path"],
            "evolution_blocker_resolution_evidence",
        )
        try:
            evidence.relative_to(evidence_root)
        except ValueError as error:
            raise GateError("evolution_blocker_resolution_evidence_scope_invalid") from error
        if not evidence.is_file() or evidence.is_symlink():
            raise GateError("evolution_blocker_resolution_evidence_missing")
        if not is_sha256(item.get("sha256")) or sha256_file(evidence) != item["sha256"]:
            raise GateError("evolution_blocker_resolution_evidence_hash_mismatch")
        if item["path"] in paths:
            raise GateError("evolution_blocker_resolution_evidence_duplicate")
        paths.add(item["path"])
    return paths


def derive_blocker_resolution_binding(
    root: Path,
    source_receipt: object,
    *,
    repaired_run_dir: Path,
    repaired_state: dict,
    repaired_run: dict,
    source_predecessor: dict,
    open_blockers: list[dict],
    target_run_id: str,
    target_candidate_id: str,
    target_workflow_sha256: str,
) -> tuple[dict, tuple[str, str]]:
    receipt_path, receipt_relative = blocker_resolution_path(
        root,
        source_receipt,
        "evolution_blocker_resolution_receipt",
    )
    try:
        receipt_path.relative_to((root / "evals" / "blocker-resolutions").resolve())
    except ValueError as error:
        raise GateError("evolution_blocker_resolution_receipt_scope_invalid") from error
    if receipt_path.suffix.lower() != ".json" or not receipt_path.is_file() or receipt_path.is_symlink():
        raise GateError("evolution_blocker_resolution_receipt_missing")
    receipt = read_json(receipt_path, "evolution_blocker_resolution_receipt")
    if schema_validation_errors(receipt, "blocker-resolution-receipt.schema.json"):
        raise GateError("evolution_blocker_resolution_receipt_schema_invalid")
    if receipt.get("source_predecessor") != source_predecessor:
        raise GateError("evolution_blocker_resolution_source_predecessor_mismatch")
    if receipt.get("repaired_run") != repaired_run:
        raise GateError("evolution_blocker_resolution_predecessor_mismatch")
    blocker = receipt.get("blocker")
    if not isinstance(blocker, dict) or blocker not in open_blockers:
        raise GateError("evolution_blocker_resolution_blocker_mismatch")

    original_evidence = resolve_within(
        root,
        blocker["evidence"],
        "evolution_blocker_resolution_original_evidence",
    )
    if (
        not original_evidence.is_file()
        or original_evidence.is_symlink()
        or sha256_file(original_evidence) != blocker.get("evidence_sha256")
    ):
        raise GateError("evolution_blocker_resolution_original_evidence_hash_mismatch")

    receipt_id = receipt["receipt_id"]
    resolution_root = (
        root / "evals" / "blocker-resolutions" / receipt_id
    ).resolve()
    implementation_items = receipt["resolution"]["evidence"]
    roles = {
        item.get("role") for item in implementation_items if isinstance(item, dict)
    }
    if roles != {"implementation", "regression_test"}:
        raise GateError("evolution_blocker_resolution_evidence_roles_invalid")
    implementation_paths = validate_resolution_evidence(
        root,
        implementation_items,
        evidence_root=resolution_root,
    )

    verification = receipt["verification"]
    audit_reference = verification["audit_receipt"]
    audit_path, audit_relative = blocker_resolution_path(
        root,
        audit_reference.get("path"),
        "evolution_blocker_resolution_verification_receipt",
    )
    try:
        audit_path.relative_to((root / "evals" / "receipts").resolve())
    except ValueError as error:
        raise GateError("evolution_blocker_resolution_verification_scope_invalid") from error
    if (
        audit_path.suffix.lower() != ".json"
        or not audit_path.is_file()
        or audit_path.is_symlink()
    ):
        raise GateError("evolution_blocker_resolution_verification_missing")
    audit_sha256 = sha256_file(audit_path)
    if not is_sha256(audit_reference.get("sha256")) or audit_sha256 != audit_reference["sha256"]:
        raise GateError("evolution_blocker_resolution_verification_hash_mismatch")
    audit_receipt = read_json(audit_path, "evolution_blocker_resolution_verification")
    if audit_receipt.get("completed_run") != repaired_run:
        raise GateError("evolution_blocker_resolution_verification_run_mismatch")
    manifest_path = root / "evals" / "test-generation-manifest.json"
    if not manifest_path.is_file() or manifest_path.is_symlink():
        raise GateError("evolution_blocker_resolution_manifest_missing")
    audit_state = {
        "candidate_id": repaired_state["candidate_id"],
        "artifacts": repaired_state["completed_artifacts"],
        "test_manifest_sha256": sha256_file(manifest_path),
        "completed_run": repaired_run,
    }
    audit_id = audit_receipt.get("audit_id")
    if audit_id not in DEFAULT_AUDIT_IDS:
        raise GateError("evolution_blocker_resolution_verification_invalid")
    audit_errors, validated_audit, _ = validate_audit_receipt(
        root,
        audit_relative,
        audit_id,
        audit_state,
        enforce_current_contract=True,
    )
    if audit_errors or validated_audit is None:
        raise GateError("evolution_blocker_resolution_verification_invalid")
    if validated_audit.get("status") != "passed" or validated_audit.get("blockers") != []:
        raise GateError("evolution_blocker_resolution_verification_not_passed")

    finding_id = verification["finding_id"]
    findings = [
        finding
        for finding in validated_audit.get("manual_findings", [])
        if isinstance(finding, dict) and finding.get("finding_id") == finding_id
    ]
    if len(findings) != 1:
        raise GateError("evolution_blocker_resolution_finding_invalid")
    finding = findings[0]
    if (
        set(finding)
        != {
            "finding_id",
            "blocker_id",
            "outcome",
            "summary",
            "verification_step_ids",
            "evidence",
        }
        or finding.get("blocker_id") != blocker["id"]
        or finding.get("outcome") != "resolved"
        or not isinstance(finding.get("summary"), str)
        or len(finding["summary"].strip()) < 20
        or not isinstance(finding.get("verification_step_ids"), list)
        or not finding["verification_step_ids"]
        or len(finding["verification_step_ids"])
        != len(set(finding["verification_step_ids"]))
    ):
        raise GateError("evolution_blocker_resolution_finding_invalid")
    audit_evidence_root = (
        root / "evals" / "receipts" / validated_audit["receipt_id"]
    ).resolve()
    verification_paths = validate_resolution_evidence(
        root,
        finding.get("evidence"),
        evidence_root=audit_evidence_root,
    )
    if implementation_paths & verification_paths:
        raise GateError("evolution_blocker_resolution_evidence_overlap")

    verification_steps: list[dict] = []
    audit_commands = validated_audit.get("commands", [])
    for step_id in finding["verification_step_ids"]:
        projection = repaired_state.get("steps", {}).get(step_id)
        if (
            not isinstance(step_id, str)
            or not isinstance(projection, dict)
            or projection.get("kind") != "command"
            or projection.get("status") != "completed"
            or not isinstance(projection.get("receipt_path"), str)
            or not is_sha256(projection.get("receipt_sha256"))
        ):
            raise GateError("evolution_blocker_resolution_verification_step_invalid")
        evolution_receipt_path = resolve_within(
            root,
            projection["receipt_path"],
            "evolution_blocker_resolution_step_receipt",
        )
        if (
            not evolution_receipt_path.is_file()
            or evolution_receipt_path.is_symlink()
            or sha256_file(evolution_receipt_path) != projection["receipt_sha256"]
        ):
            raise GateError("evolution_blocker_resolution_step_receipt_invalid")
        evolution_receipt = read_json(
            evolution_receipt_path,
            "evolution_blocker_resolution_step_receipt",
        )
        comparable = {
            "argv": evolution_receipt.get("argv"),
            "exit_code": evolution_receipt.get("exit_code"),
            "stdout_sha256": evolution_receipt.get("stdout_sha256"),
            "stderr_sha256": evolution_receipt.get("stderr_sha256"),
        }
        if not any(
            all(command.get(key) == value for key, value in comparable.items())
            for command in audit_commands
            if isinstance(command, dict)
        ):
            raise GateError("evolution_blocker_resolution_audit_command_mismatch")
        verification_steps.append(
            {
                "step_id": step_id,
                "receipt_path": projection["receipt_path"],
                "receipt_sha256": projection["receipt_sha256"],
            }
        )

    projection = {
        "id": blocker["id"],
        "severity": blocker["severity"],
        "source_receipt": receipt_relative,
        "source_receipt_sha256": sha256_file(receipt_path),
        "audit_receipt": audit_relative,
        "audit_receipt_sha256": audit_sha256,
        "source_blocker_sha256": sha256_bytes(canonical_json_bytes(blocker)),
        "source_predecessor_sha256": sha256_bytes(
            canonical_json_bytes(source_predecessor)
        ),
        "repaired_run_sha256": sha256_bytes(canonical_json_bytes(repaired_run)),
        "verification_step_receipts": sorted(
            verification_steps,
            key=lambda item: item["step_id"],
        ),
        "target_run_id": target_run_id,
        "target_candidate_id": target_candidate_id,
        "target_workflow_sha256": target_workflow_sha256,
        "derived_status": "resolved",
    }
    return projection, (audit_sha256, finding_id)


def validate_resolved_blocker_bindings(root: Path, state: dict) -> None:
    bindings = state.get("resolved_blocker_bindings", [])
    if not isinstance(bindings, list):
        raise GateError("evolution_blocker_resolution_binding_invalid")
    if not bindings:
        return
    predecessor_binding = state.get("predecessor_binding")
    if not isinstance(predecessor_binding, dict):
        raise GateError("evolution_blocker_resolution_binding_invalid")
    predecessor_dir = resolve_within(
        root,
        predecessor_binding["run_dir"],
        "evolution_blocker_resolution_predecessor",
    )
    predecessor_state, _, _ = load_loop_state(
        root,
        predecessor_dir,
        verify_candidate_current=False,
    )
    source_predecessor = predecessor_state.get("predecessor_binding")
    if not isinstance(source_predecessor, dict):
        raise GateError("evolution_blocker_resolution_source_predecessor_mismatch")
    open_blockers = predecessor_state.get("carry_over_blocker_bindings", [])
    seen_ids: set[str] = set()
    seen_findings: set[tuple[str, str]] = set()
    for binding in bindings:
        if not isinstance(binding, dict) or not isinstance(binding.get("source_receipt"), str):
            raise GateError("evolution_blocker_resolution_binding_invalid")
        derived, finding_key = derive_blocker_resolution_binding(
            root,
            binding["source_receipt"],
            repaired_run_dir=predecessor_dir,
            repaired_state=predecessor_state,
            repaired_run=predecessor_binding,
            source_predecessor=source_predecessor,
            open_blockers=open_blockers,
            target_run_id=state["run_id"],
            target_candidate_id=state["candidate_id"],
            target_workflow_sha256=state["workflow_sha256"],
        )
        if derived != binding:
            raise GateError("evolution_blocker_resolution_binding_invalid")
        if binding["id"] in seen_ids or finding_key in seen_findings:
            raise GateError("evolution_blocker_resolution_reused")
        seen_ids.add(binding["id"])
        seen_findings.add(finding_key)


def validate_predecessor_binding(root: Path, state: dict) -> None:
    binding = state.get("predecessor_binding")
    if binding is None:
        if state.get("predecessor_run_id") is not None or state.get("predecessor_candidate_id") is not None:
            raise GateError("evolution_predecessor_binding_required")
        return
    required = {
        "run_dir",
        "run_id",
        "candidate_id",
        "workflow_id",
        "workflow_path",
        "workflow_sha256",
        "run_state_sha256",
        "event_count",
        "event_head_sha256",
        "receipt_tree_sha256",
        "completed_artifacts",
    }
    if not isinstance(binding, dict) or set(binding) != required:
        raise GateError("evolution_predecessor_binding_invalid")
    if (
        binding.get("run_id") != state.get("predecessor_run_id")
        or binding.get("candidate_id") != state.get("predecessor_candidate_id")
        or not isinstance(binding.get("run_dir"), str)
    ):
        raise GateError("evolution_predecessor_binding_invalid")
    predecessor_dir = resolve_within(
        root,
        binding["run_dir"],
        "evolution_predecessor_run",
    )
    predecessor, _, predecessor_workflow = load_loop_state(
        root,
        predecessor_dir,
        verify_candidate_current=False,
    )
    if predecessor.get("status") not in {"complete", "failed"}:
        raise GateError("evolution_predecessor_not_terminal")
    if (
        binding.get("run_id") != predecessor.get("run_id")
        or binding.get("candidate_id") != predecessor.get("candidate_id")
        or binding.get("workflow_id") != predecessor.get("workflow_id")
        or binding.get("workflow_path") != predecessor.get("workflow_path")
        or binding.get("workflow_sha256") != predecessor.get("workflow_sha256")
        or predecessor_workflow.relative_to(root).as_posix() != binding.get("workflow_path")
        or binding.get("completed_artifacts") != predecessor.get("completed_artifacts")
    ):
        raise GateError("evolution_predecessor_binding_mismatch")
    if sha256_file(predecessor_dir / "run-state.json") != binding.get("run_state_sha256"):
        raise GateError("evolution_predecessor_state_hash_mismatch")
    if (
        binding.get("event_count") != predecessor.get("event_count")
        or binding.get("event_head_sha256") != predecessor.get("event_head_sha256")
    ):
        raise GateError("evolution_predecessor_event_head_mismatch")
    if completed_run_receipt_tree(root, predecessor_dir) != binding.get("receipt_tree_sha256"):
        raise GateError("evolution_predecessor_receipt_tree_mismatch")


def validate_completed_run_binding(root: Path, state: dict) -> list[str]:
    binding = state.get("completed_run")
    required = {
        "run_dir",
        "run_id",
        "candidate_id",
        "workflow_id",
        "workflow_path",
        "workflow_sha256",
        "run_state_sha256",
        "event_count",
        "event_head_sha256",
        "receipt_tree_sha256",
        "completed_artifacts",
    }
    if not isinstance(binding, dict):
        return ["release_completed_run_required"]
    if set(binding) != required:
        return ["release_completed_run_binding_invalid"]
    if not isinstance(binding.get("run_dir"), str):
        return ["release_completed_run_binding_invalid"]
    try:
        run_dir = resolve_within(
            root,
            binding["run_dir"],
            "release_completed_run",
        )
        run_state, _, workflow_path = load_loop_state(
            root,
            run_dir,
            verify_candidate_current=False,
        )
    except GateError as error:
        return sorted(set(["release_completed_run_invalid", *error.codes]))
    errors: list[str] = []
    if run_state.get("status") != "complete":
        errors.append("release_completed_run_not_complete")
    if (
        binding.get("run_id") != run_state.get("run_id")
        or binding.get("candidate_id") != run_state.get("candidate_id")
        or binding.get("workflow_id") != run_state.get("workflow_id")
        or binding.get("workflow_path") != run_state.get("workflow_path")
        or binding.get("workflow_sha256") != run_state.get("workflow_sha256")
    ):
        errors.append("release_completed_run_binding_mismatch")
    state_artifacts = state.get("artifacts")
    state_workflow_sha256 = (
        state_artifacts.get("workflow_sha256")
        if isinstance(state_artifacts, dict)
        else None
    )
    if (
        binding.get("candidate_id") != state.get("candidate_id")
        or state.get("workflow_path") != binding.get("workflow_path")
        or state_workflow_sha256 != binding.get("workflow_sha256")
        or workflow_path.relative_to(root).as_posix() != binding.get("workflow_path")
    ):
        errors.append("release_completed_run_candidate_mismatch")
    completed_artifacts = run_state.get("completed_artifacts")
    if (
        validate_artifact_hashes(
            binding.get("completed_artifacts"),
            "release_completed_run_artifacts",
            require_governance=True,
        )
        or binding.get("completed_artifacts") != completed_artifacts
        or binding.get("completed_artifacts") != state_artifacts
    ):
        errors.append("release_completed_run_artifact_mismatch")
    run_state_path = run_dir / "run-state.json"
    if (
        not is_sha256(binding.get("run_state_sha256"))
        or sha256_file(run_state_path) != binding.get("run_state_sha256")
    ):
        errors.append("release_completed_run_state_hash_mismatch")
    if (
        binding.get("event_count") != run_state.get("event_count")
        or binding.get("event_head_sha256") != run_state.get("event_head_sha256")
    ):
        errors.append("release_completed_run_event_head_mismatch")
    if state.get("blocker_resolutions", []) != run_state.get(
        "resolved_blocker_bindings", []
    ):
        errors.append("release_state_blocker_resolution_mismatch")
    try:
        receipt_tree = completed_run_receipt_tree(root, run_dir)
    except GateError as error:
        errors.extend(error.codes)
    else:
        if (
            not is_sha256(binding.get("receipt_tree_sha256"))
            or binding.get("receipt_tree_sha256") != receipt_tree
        ):
            errors.append("release_completed_run_receipt_tree_mismatch")
    return sorted(set(errors))


def validate_state(root: Path, state: dict, manifest_path: Path) -> list[str]:
    errors: list[str] = []
    if schema_validation_errors(state, "release-gate.schema.json"):
        errors.append("release_gate_schema_invalid")
    if state.get("schema_version") != "1.0":
        errors.append("release_state_schema_version")
    if state.get("workflow_id") != "breaking-identity-labels-v2-evolution":
        errors.append("release_state_workflow_id")
    if not isinstance(state.get("iteration"), int) or state["iteration"] < 1:
        errors.append("release_state_iteration")
    if not isinstance(state.get("candidate_id"), str) or not state["candidate_id"]:
        errors.append("release_state_candidate_id")
    if state.get("distribution_status") != "local_unpublished":
        errors.append("release_state_distribution_status")
    if state.get("publication_actions_performed") is not False:
        errors.append("release_state_publication_action")
    errors.extend(validate_completed_run_binding(root, state))
    workflow_relative = state.get("workflow_path")
    has_governance_binding = workflow_relative is not None
    errors.extend(
        validate_artifact_hashes(
            state.get("artifacts"),
            "candidate_artifacts",
            require_governance=has_governance_binding,
        )
    )
    if has_governance_binding:
        if not isinstance(workflow_relative, str):
            errors.append("release_state_workflow_path")
        else:
            try:
                workflow_path = resolve_within(
                    root, workflow_relative, "release_state_workflow"
                )
                if not workflow_path.is_file() or workflow_path.is_symlink():
                    errors.append("release_state_workflow_missing")
            except GateError as error:
                errors.extend(error.codes)
        if state.get("governance_files") != list(GOVERNANCE_FILES):
            errors.append("release_state_governance_inventory")
    if not is_sha256(state.get("test_manifest_sha256")):
        errors.append("release_state_test_manifest_hash")
    elif manifest_path.is_file() and state["test_manifest_sha256"] != sha256_file(manifest_path):
        errors.append("release_state_test_manifest_drift")

    blockers = state.get("blockers")
    blocker_count = state.get("blocker_count")
    if not isinstance(blockers, list):
        errors.append("release_state_blockers_not_list")
        blockers = []
    if not isinstance(blocker_count, int) or blocker_count < 0:
        errors.append("release_state_blocker_count")
    elif blocker_count != len(blockers):
        errors.append("release_state_blocker_count_mismatch")
    for blocker in blockers:
        if not isinstance(blocker, dict):
            errors.append("release_state_invalid_blocker")
            continue
        if blocker.get("severity") not in {"P0", "P1", "P2"}:
            errors.append("release_state_blocker_severity")
        evidence = blocker.get("evidence")
        if not isinstance(evidence, str):
            errors.append("release_state_blocker_evidence")
        else:
            try:
                evidence_path = resolve_within(root, evidence, "release_state_evidence")
                if not evidence_path.is_file():
                    errors.append("release_state_blocker_evidence_missing")
                saved_evidence_sha256 = blocker.get("evidence_sha256")
                if saved_evidence_sha256 is not None and (
                    not is_sha256(saved_evidence_sha256)
                    or not evidence_path.is_file()
                    or evidence_path.is_symlink()
                    or sha256_file(evidence_path) != saved_evidence_sha256
                ):
                    errors.append("release_state_blocker_evidence_hash_mismatch")
            except GateError as error:
                errors.extend(error.codes)

    audits = state.get("audits")
    if not isinstance(audits, list):
        errors.append("release_state_audits_not_list")
        audits = []
    ids = [audit.get("audit_id") for audit in audits if isinstance(audit, dict)]
    if set(ids) != set(DEFAULT_AUDIT_IDS) or len(ids) != len(DEFAULT_AUDIT_IDS):
        errors.append("release_state_audit_inventory")
    used_receipts: set[str] = set()
    for audit in audits:
        if not isinstance(audit, dict):
            errors.append("release_state_invalid_audit")
            continue
        status = audit.get("status")
        count = audit.get("blocker_count")
        if status not in {"pending", "passed", "blocked", "invalid_run"}:
            errors.append("release_state_audit_status")
        if not isinstance(count, int) or count < 0:
            errors.append("release_state_audit_blocker_count")
        elif status == "passed" and count != 0:
            errors.append("release_state_passing_audit_has_blockers")
        elif status == "blocked" and count < 1:
            errors.append("release_state_blocked_audit_without_blocker")
        bound = audit.get("artifact_sha256")
        if status in {"passed", "blocked"}:
            errors.extend(
                validate_artifact_hashes(
                    bound,
                    "audit_artifacts",
                    require_governance=has_governance_binding,
                )
            )
            if bound != state.get("artifacts"):
                errors.append("release_state_audit_candidate_mismatch")
            evidence = audit.get("evidence")
            if not isinstance(evidence, list) or not evidence:
                errors.append("release_state_audit_evidence_empty")
            else:
                for relative in evidence:
                    if not isinstance(relative, str):
                        errors.append("release_state_audit_evidence_invalid")
                        continue
                    try:
                        path = resolve_within(root, relative, "release_state_evidence")
                        if not path.is_file():
                            errors.append("release_state_audit_evidence_missing")
                    except GateError as error:
                        errors.extend(error.codes)
                if len(evidence) != 1:
                    errors.append("audit_receipt_required")
                else:
                    relative = evidence[0]
                    if isinstance(relative, str):
                        if relative in used_receipts:
                            errors.append("audit_receipt_reused")
                        used_receipts.add(relative)
                    receipt_errors, receipt, receipt_path = validate_audit_receipt(
                        root,
                        relative,
                        str(audit.get("audit_id", "")),
                        state,
                        enforce_current_contract=True,
                    )
                    errors.extend(receipt_errors)
                    saved_hash = audit.get("receipt_sha256")
                    if (
                        receipt_path is None
                        or not receipt_path.is_file()
                        or not is_sha256(saved_hash)
                        or sha256_file(receipt_path) != saved_hash
                    ):
                        errors.append("audit_receipt_hash_mismatch")
                    if receipt is not None:
                        receipt_blockers = receipt.get("blockers", [])
                        derived_status = "passed" if not receipt_blockers else "blocked"
                        if status != derived_status or count != len(receipt_blockers):
                            errors.append("audit_receipt_state_mismatch")
        elif bound is not None:
            errors.append("release_state_inactive_audit_has_artifacts")
        elif audit.get("receipt_sha256") is not None:
            errors.append("release_state_inactive_audit_has_receipt")

    expected = expected_recorded_decision(state)
    if state.get("decision") != expected:
        errors.append("release_state_decision_mismatch")
    return sorted(set(errors))


def evaluate_gate(
    root: Path,
    state: dict,
    manifest: dict,
    manifest_path: Path,
) -> dict:
    errors = validate_test_manifest(root, manifest)
    errors.extend(validate_state(root, state, manifest_path))
    errors = sorted(set(errors))
    if errors:
        return {
            "schema_version": "1.0",
            "valid": False,
            "effective_decision": "invalid_run",
            "release_eligible": False,
            "errors": errors,
        }

    workflow_path = None
    if isinstance(state.get("workflow_path"), str):
        workflow_path = resolve_within(
            root, state["workflow_path"], "release_state_workflow"
        )
    current = collect_snapshot(root, workflow_path)
    frozen = state["artifacts"]
    invalidations = [
        key.removesuffix("_sha256") + "_sha256_drift"
        for key in frozen
        if current[key] != frozen[key]
    ]
    effective_decision = state["decision"] if not invalidations else "invalid_run"
    audits = []
    for audit in state["audits"]:
        effective_status = audit["status"]
        if invalidations and audit["status"] in {"passed", "blocked"}:
            effective_status = "invalid_run"
        audits.append(
            {
                "audit_id": audit["audit_id"],
                "recorded_status": audit["status"],
                "effective_status": effective_status,
                "blocker_count": audit["blocker_count"],
            }
        )
    release_eligible = (
        effective_decision == "candidate"
        and state["blocker_count"] == 0
        and {audit["effective_status"] for audit in audits} == {"passed"}
        and len(audits) == len(DEFAULT_AUDIT_IDS)
    )
    return {
        "schema_version": "1.0",
        "valid": True,
        "candidate_id": state["candidate_id"],
        "iteration": state["iteration"],
        "recorded_decision": state["decision"],
        "effective_decision": effective_decision,
        "distribution_status": "local_unpublished",
        "publication_actions_performed": False,
        "blocker_count": state["blocker_count"],
        "release_eligible": release_eligible,
        "invalidations": sorted(invalidations),
        "artifacts": {"frozen": frozen, "current": current},
        "audits": audits,
        "errors": [],
    }


def parse_blocker(value: str) -> dict:
    parts = value.split(":", 2)
    if len(parts) != 3 or parts[1] not in {"P0", "P1", "P2"}:
        raise argparse.ArgumentTypeError("blocker must be ID:P0|P1|P2:EVIDENCE_PATH")
    return {"id": parts[0], "severity": parts[1], "evidence": parts[2]}


def pending_audits() -> list[dict]:
    return [
        {
            "audit_id": audit_id,
            "artifact_sha256": None,
            "blocker_count": 0,
            "evidence": [],
            "receipt_sha256": None,
            "status": "pending",
        }
        for audit_id in DEFAULT_AUDIT_IDS
    ]


def release_state_has_open_blockers(state: dict) -> bool:
    """Return whether a release projection requires lineage, not a root run."""

    blockers = state.get("blockers")
    audits = state.get("audits")
    return bool(
        (isinstance(blockers, list) and blockers)
        or (isinstance(state.get("blocker_count"), int) and state["blocker_count"] > 0)
        or state.get("decision") == "blocked"
        or (
            isinstance(audits, list)
            and any(
                isinstance(audit, dict) and audit.get("status") == "blocked"
                for audit in audits
            )
        )
    )


def bound_release_blockers(root: Path, state: dict) -> list[dict]:
    """Validate and hash-bind every blocker remembered by a release state."""

    blockers = state.get("blockers")
    if not isinstance(blockers, list):
        raise GateError("release_state_blockers_not_list")
    bound: list[dict] = []
    seen: set[str] = set()
    for blocker in blockers:
        if (
            not isinstance(blocker, dict)
            or not isinstance(blocker.get("id"), str)
            or not blocker["id"]
            or blocker["id"] in seen
            or blocker.get("severity") not in {"P0", "P1", "P2"}
            or not isinstance(blocker.get("evidence"), str)
        ):
            raise GateError("release_state_invalid_blocker")
        seen.add(blocker["id"])
        evidence = resolve_within(root, blocker["evidence"], "release_state_evidence")
        if not evidence.is_file() or evidence.is_symlink():
            raise GateError("release_state_blocker_evidence_missing")
        current_hash = sha256_file(evidence)
        saved_hash = blocker.get("evidence_sha256")
        if saved_hash is not None and saved_hash != current_hash:
            raise GateError("release_state_blocker_evidence_hash_mismatch")
        bound.append(
            {
                "id": blocker["id"],
                "severity": blocker["severity"],
                "evidence": blocker["evidence"],
                "evidence_sha256": current_hash,
                "status": "open",
            }
        )
    return bound


def _command_check_unlocked(args: argparse.Namespace) -> int:
    root = args.root.expanduser().resolve()
    manifest_path = args.test_manifest.expanduser().resolve()
    state = read_json(args.state.expanduser().resolve(), "release_state")
    manifest = read_json(manifest_path, "test_manifest")
    result = evaluate_gate(root, state, manifest, manifest_path)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if not result["valid"]:
        return 3
    if args.strict_release and not result["release_eligible"]:
        return 2
    return 0


def command_check(args: argparse.Namespace) -> int:
    state_path = args.state.expanduser().resolve()
    with release_state_lock(state_path, exclusive=False):
        return _command_check_unlocked(args)


def _command_freeze_unlocked(args: argparse.Namespace) -> int:
    root = args.root.expanduser().resolve()
    state_path = args.state.expanduser().resolve()
    manifest_path = args.test_manifest.expanduser().resolve()
    if args.completed_run_dir is None:
        raise GateError("release_completed_run_required")
    run_dir = resolve_supplied_path(
        root,
        args.completed_run_dir,
        "release_completed_run",
    )
    run_state, workflow, workflow_path = load_loop_state(root, run_dir)
    if run_state.get("status") != "complete":
        raise GateError("release_completed_run_not_complete")
    if run_state.get("candidate_id") != args.candidate_id:
        raise GateError("release_completed_run_candidate_mismatch")
    if args.workflow is not None:
        supplied_workflow = resolve_supplied_path(
            root,
            args.workflow,
            "evolution_workflow",
        )
        if supplied_workflow != workflow_path:
            raise GateError("release_completed_run_workflow_mismatch")
    preflight_evolution_commands(
        root,
        root / "evals" / ".evolution-preflight",
        workflow,
    )
    strict_artifacts = collect_snapshot(root, workflow_path, strict=True)
    if strict_artifacts != run_state.get("completed_artifacts"):
        raise GateError("evolution_candidate_snapshot_mismatch")
    workflow_relative = workflow_path.relative_to(root).as_posix()
    manifest = read_json(manifest_path, "test_manifest")
    manifest_errors = validate_test_manifest(root, manifest)
    if manifest_errors:
        raise GateError(*manifest_errors)
    requested_blockers = list(args.blocker or [])
    run_open_bindings = [
        binding
        for binding in run_state.get("carry_over_blocker_bindings", [])
        if binding.get("status") == "open"
    ]
    previous_iteration = 0
    if state_path.is_file():
        previous = read_json(state_path, "release_state")
        value = previous.get("iteration")
        if isinstance(value, int) and value > 0:
            previous_iteration = value
        if release_state_has_open_blockers(previous):
            previous_bound = bound_release_blockers(root, previous)
            previous_ids = {binding["id"] for binding in previous_bound}
            current_binding = completed_run_binding(root, run_dir, run_state)
            if current_binding == previous.get("completed_run"):
                # Re-freezing the exact same run may refresh timestamps but cannot
                # make an unresolved blocker disappear.
                run_open_bindings = previous_bound
            else:
                if run_state.get("predecessor_binding") != previous.get("completed_run"):
                    raise GateError("release_state_open_blockers_require_next_iteration")
                accounted_ids = {
                    binding.get("id") for binding in run_open_bindings
                } | {
                    binding.get("id")
                    for binding in run_state.get("resolved_blocker_bindings", [])
                }
                if not previous_ids.issubset(accounted_ids):
                    raise GateError("release_state_open_blockers_require_next_iteration")
    requested_blockers.extend(
        {
            "id": binding["id"],
            "severity": binding["severity"],
            "evidence": binding["evidence"],
        }
        for binding in run_open_bindings
    )
    blockers: list[dict] = []
    blocker_ids: set[str] = set()
    for blocker in requested_blockers:
        if blocker["id"] in blocker_ids:
            raise GateError("release_state_blocker_duplicate")
        blocker_ids.add(blocker["id"])
        evidence = resolve_within(root, blocker["evidence"], "release_state_evidence")
        if not evidence.is_file() or evidence.is_symlink():
            raise GateError("release_state_blocker_evidence_missing")
        blockers.append({**blocker, "evidence_sha256": sha256_file(evidence)})
    artifacts = strict_artifacts
    state = {
        "schema_version": "1.0",
        "workflow_id": "breaking-identity-labels-v2-evolution",
        "iteration": previous_iteration + 1,
        "frozen_at": args.clock,
        "candidate_id": args.candidate_id,
        "artifacts": artifacts,
        "test_manifest_sha256": sha256_file(manifest_path),
        "audits": pending_audits(),
        "blockers": blockers,
        "blocker_resolutions": copy.deepcopy(
            run_state.get("resolved_blocker_bindings", [])
        ),
        "blocker_count": len(blockers),
        "decision": "blocked" if blockers else "pending",
        "distribution_status": "local_unpublished",
        "publication_actions_performed": False,
        "completed_run": completed_run_binding(root, run_dir, run_state),
    }
    state["workflow_path"] = workflow_relative
    state["governance_files"] = list(GOVERNANCE_FILES)
    write_json(state_path, state)
    print(
        json.dumps(
            {
                "status": "frozen",
                "candidate_id": args.candidate_id,
                "iteration": state["iteration"],
                "decision": state["decision"],
                "blocker_count": state["blocker_count"],
                "artifacts": artifacts,
                "state": str(state_path),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def command_freeze(args: argparse.Namespace) -> int:
    root = args.root.expanduser().resolve()
    state_path = args.state.expanduser().resolve()
    if args.completed_run_dir is None:
        with release_state_lock(state_path, exclusive=True, create_parent=True):
            return _command_freeze_unlocked(args)
    run_dir = resolve_supplied_path(
        root,
        args.completed_run_dir,
        "release_completed_run",
    )
    # All multi-resource controller paths acquire release state before run
    # locks. Keeping one order prevents cooperating processes from deadlocking.
    with release_state_lock(state_path, exclusive=True, create_parent=True):
        with evolution_run_lock(run_dir, exclusive=False):
            return _command_freeze_unlocked(args)


def _command_record_audit_unlocked(args: argparse.Namespace) -> int:
    root = args.root.expanduser().resolve()
    state_path = args.state.expanduser().resolve()
    manifest_path = args.test_manifest.expanduser().resolve()
    state = read_json(state_path, "release_state")
    manifest = read_json(manifest_path, "test_manifest")
    preflight = evaluate_gate(root, state, manifest, manifest_path)
    if not preflight["valid"]:
        raise GateError(*preflight["errors"])
    if preflight["invalidations"]:
        raise GateError("audit_candidate_drift")
    receipt_relative = args.receipt
    if (
        not receipt_relative
        and len(args.evidence) == 1
        and isinstance(args.evidence[0], str)
        and args.evidence[0].lower().endswith(".json")
    ):
        receipt_relative = args.evidence[0]
    if not receipt_relative:
        raise GateError("audit_receipt_required")
    receipt_path = resolve_within(root, receipt_relative, "audit_receipt")
    if receipt_path.suffix.lower() != ".json" or not receipt_path.is_file():
        raise GateError("audit_receipt_required")
    receipt_preview = read_json(receipt_path, "audit_receipt")
    audit_id = args.audit_id or receipt_preview.get("audit_id")
    if audit_id not in DEFAULT_AUDIT_IDS:
        raise GateError("audit_id_unknown")
    receipt_errors, receipt, validated_path = validate_audit_receipt(
        root,
        receipt_relative,
        audit_id,
        state,
        enforce_current_contract=True,
    )
    if receipt_errors or receipt is None or validated_path is None:
        raise GateError(*receipt_errors)
    if any(
        audit.get("evidence") == [receipt_relative]
        and audit.get("audit_id") != audit_id
        for audit in state["audits"]
    ):
        raise GateError("audit_receipt_reused")
    receipt_blockers = receipt["blockers"]
    status = "passed" if not receipt_blockers else "blocked"
    blocker_count = len(receipt_blockers)

    selected_audit = None
    for audit in state["audits"]:
        if audit["audit_id"] == audit_id:
            selected_audit = audit
            if audit.get("status") != "pending":
                raise GateError("audit_result_terminal")
            audit.update(
                {
                    "status": status,
                    "blocker_count": blocker_count,
                    "artifact_sha256": dict(state["artifacts"]),
                    "evidence": [receipt_relative],
                    "receipt_sha256": sha256_file(validated_path),
                }
            )
            break
    if selected_audit is None:
        raise GateError("audit_id_unknown")
    prefix = audit_id + ":"
    state["blockers"] = [
        blocker for blocker in state["blockers"] if not blocker["id"].startswith(prefix)
    ]
    if status == "blocked":
        for index, blocker in enumerate(receipt_blockers):
            state["blockers"].append(
                {
                    "id": f"{audit_id}:{blocker.get('id', f'blocker-{index + 1}')}",
                    "severity": blocker["severity"],
                    "evidence": receipt_relative,
                }
            )
    state["blocker_count"] = len(state["blockers"])
    state["decision"] = expected_recorded_decision(state)
    write_json(state_path, state)
    print(
        json.dumps(
            {
                "status": "audit_recorded",
                "audit_id": audit_id,
                "receipt_sha256": sha256_file(validated_path),
                "decision": state["decision"],
                "blocker_count": state["blocker_count"],
                "state": str(state_path),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def command_record_audit(args: argparse.Namespace) -> int:
    state_path = args.state.expanduser().resolve()
    with release_state_lock(state_path, exclusive=True):
        return _command_record_audit_unlocked(args)


def command_migrate_test(args: argparse.Namespace) -> int:
    root = args.root.expanduser().resolve()
    manifest_path = args.test_manifest.expanduser().resolve()
    raw_receipt_path = args.receipt.expanduser()
    receipt_path = raw_receipt_path.resolve() if raw_receipt_path.is_absolute() else (root / raw_receipt_path).resolve()
    try:
        relative_receipt = receipt_path.relative_to(root).as_posix()
    except ValueError as error:
        raise GateError("test_migration_receipt_unsafe_path") from error
    if not receipt_path.is_file() or receipt_path.is_symlink() or receipt_path.suffix.lower() != ".json":
        raise GateError("test_migration_receipt_missing")
    permitted_pending: set[str] = set()
    for supplied in args.permit_pending_receipt or []:
        candidate = supplied.expanduser()
        candidate = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        try:
            relative = candidate.relative_to(root).as_posix()
        except ValueError as error:
            raise GateError("test_migration_receipt_unsafe_path") from error
        if not candidate.is_file() or candidate.is_symlink() or candidate.suffix.lower() != ".json":
            raise GateError("test_migration_receipt_missing")
        permitted_pending.add(relative)
    receipt = read_json(receipt_path, "test_migration_receipt")
    if schema_validation_errors(receipt, "test-migration-receipt.schema.json"):
        raise GateError("test_migration_receipt_schema_invalid")
    required = {
        "schema_version",
        "receipt_id",
        "test_path",
        "from_sha256",
        "to_sha256",
        "reason",
        "replacement_tests",
        "evidence",
        "reviewed_by",
        "reviewed_at",
    }
    if set(receipt) != required or receipt.get("schema_version") != "1.0":
        raise GateError("test_migration_receipt_schema")
    if not all(
        isinstance(receipt.get(field), str) and receipt[field].strip()
        for field in ("receipt_id", "test_path", "reason", "reviewed_by", "reviewed_at")
    ):
        raise GateError("test_migration_receipt_metadata")
    if not is_sha256(receipt.get("from_sha256")) or not is_sha256(receipt.get("to_sha256")):
        raise GateError("test_migration_receipt_hash")
    manifest = read_json(manifest_path, "test_manifest")
    history_errors = validate_manifest_migration_history(
        root,
        manifest,
        pending_receipts={relative_receipt, *permitted_pending},
    )
    if history_errors:
        raise GateError(*history_errors)
    records = manifest.get("files", [])
    record = next(
        (
            item
            for item in records
            if isinstance(item, dict) and item.get("path") == receipt["test_path"]
        ),
        None,
    )
    if record is None:
        raise GateError("test_migration_path_unregistered")
    test_path = resolve_within(root, receipt["test_path"], "test_migration_test")
    if not test_path.is_file() or test_path.is_symlink():
        raise GateError("test_migration_test_missing")
    if record.get("sha256") != receipt["from_sha256"]:
        raise GateError("test_migration_from_hash_mismatch")
    if sha256_file(test_path) != receipt["to_sha256"]:
        raise GateError("test_migration_to_hash_mismatch")

    replacement_records: list[dict] = []
    replacements = receipt.get("replacement_tests")
    if not isinstance(replacements, list) or not replacements:
        raise GateError("test_migration_replacement_missing")
    for replacement in replacements:
        if not isinstance(replacement, dict) or set(replacement) != {"path", "sha256"}:
            raise GateError("test_migration_replacement_invalid")
        replacement_path = resolve_within(root, replacement["path"], "test_migration_replacement")
        if (
            replacement["path"] == receipt["test_path"]
            or not replacement_path.is_file()
            or replacement_path.is_symlink()
            or sha256_file(replacement_path) != replacement.get("sha256")
        ):
            raise GateError("test_migration_replacement_invalid")
        replacement_records.append(
            {
                "generation": generation_for(replacement["path"]),
                "path": replacement["path"],
                "sha256": replacement["sha256"],
            }
        )

    evidence = receipt.get("evidence")
    if not isinstance(evidence, list) or not evidence:
        raise GateError("test_migration_evidence_missing")
    for item in evidence:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise GateError("test_migration_evidence_invalid")
        evidence_path = resolve_within(root, item["path"], "test_migration_evidence")
        if not evidence_path.is_file() or evidence_path.is_symlink() or sha256_file(evidence_path) != item.get("sha256"):
            raise GateError("test_migration_evidence_invalid")

    history = record.setdefault("migration_history", [])
    history.append(
        {
            "receipt_path": relative_receipt,
            "receipt_sha256": sha256_file(receipt_path),
            "from_sha256": receipt["from_sha256"],
            "to_sha256": receipt["to_sha256"],
        }
    )
    record["sha256"] = receipt["to_sha256"]
    known_paths = {item.get("path") for item in records if isinstance(item, dict)}
    records.extend(item for item in replacement_records if item["path"] not in known_paths)
    rules = manifest.setdefault("generation_rules", [])
    known_rules = {
        item.get("generation") for item in rules if isinstance(item, dict)
    }
    for replacement in replacement_records:
        generation = replacement["generation"]
        if generation != "core" and generation not in known_rules:
            rules.append(
                {
                    "generation": generation,
                    "minimum": 1,
                    "pattern": f"tests/test_{generation}_*.py",
                }
            )
            known_rules.add(generation)
    records.sort(key=lambda item: item["path"])
    rules.sort(
        key=lambda item: (0, int(item["generation"][1:]))
        if re.fullmatch(r"v[1-9][0-9]*", str(item.get("generation")))
        else (1, str(item.get("generation")))
    )
    errors = validate_test_manifest(
        root,
        manifest,
        permitted_pending_receipts=permitted_pending,
    )
    migration_window_errors = {
        "test_manifest_hash_mismatch",
        "test_manifest_unregistered_file",
    }
    blocking_errors = [error for error in errors if error not in migration_window_errors]
    if blocking_errors:
        raise GateError(*blocking_errors)
    write_json(manifest_path, manifest)
    print(
        json.dumps(
            {
                "status": "test_migrated",
                "test_path": receipt["test_path"],
                "from_sha256": receipt["from_sha256"],
                "to_sha256": receipt["to_sha256"],
                "receipt_sha256": sha256_file(receipt_path),
                "manifest_sha256": sha256_file(manifest_path),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def command_sync_tests(args: argparse.Namespace) -> int:
    root = args.root.expanduser().resolve()
    path = args.test_manifest.expanduser().resolve()
    current = current_test_records(root)
    current_support = current_test_support_records(root)
    if not current:
        raise GateError("test_inventory_empty")
    old_paths: set[str] = set()
    existing_records: dict[str, dict] = {}
    existing_support: dict[str, dict] = {}
    rules: list[dict] = []
    if path.is_file():
        existing = read_json(path, "test_manifest")
        history_errors = validate_manifest_migration_history(root, existing)
        if history_errors:
            raise GateError(*history_errors)
        records = existing.get("files", [])
        if isinstance(records, list):
            existing_records = {
                record["path"]: record
                for record in records
                if isinstance(record, dict) and isinstance(record.get("path"), str)
            }
            old_paths = set(existing_records)
        rules_value = existing.get("generation_rules")
        if isinstance(rules_value, list):
            rules = rules_value
        support_value = existing.get("support_files", [])
        if isinstance(support_value, list):
            existing_support = {
                record["path"]: record
                for record in support_value
                if isinstance(record, dict) and isinstance(record.get("path"), str)
            }
    current_paths = {record["path"] for record in current}
    missing = sorted(old_paths - current_paths)
    if missing:
        raise GateError("test_manifest_refuses_generation_deletion")
    current_by_path = {record["path"]: record for record in current}
    changed = sorted(
        relative
        for relative, record in existing_records.items()
        if current_by_path[relative]["sha256"] != record.get("sha256")
    )
    if changed:
        raise GateError(*(f"test_manifest_refuses_hash_change:{relative}" for relative in changed))
    current_support_by_path = {
        record["path"]: record for record in current_support
    }
    removed_support = sorted(set(existing_support) - set(current_support_by_path))
    if removed_support:
        raise GateError("test_manifest_refuses_support_deletion")
    changed_support = sorted(
        relative
        for relative, record in existing_support.items()
        if current_support_by_path[relative]["sha256"] != record.get("sha256")
    )
    if changed_support:
        raise GateError(
            *(f"test_manifest_refuses_support_hash_change:{relative}" for relative in changed_support)
        )
    generations = sorted(
        {record["generation"] for record in current if record["generation"] != "core"},
        key=lambda value: int(value[1:]),
    )
    existing_rules = {
        rule.get("generation"): rule
        for rule in rules
        if isinstance(rule, dict) and isinstance(rule.get("generation"), str)
    }
    for generation in generations:
        existing_rules.setdefault(
            generation,
            {
                "generation": generation,
                "minimum": 1,
                "pattern": f"tests/test_{generation}_*.py",
            },
        )
    rules = [
        existing_rules[generation]
        for generation in sorted(
            existing_rules,
            key=lambda value: (0, int(value[1:]))
            if re.fullmatch(r"v[1-9][0-9]*", value)
            else (1, value),
        )
    ]
    records = [existing_records[relative] for relative in sorted(existing_records)]
    records.extend(
        current_by_path[relative]
        for relative in sorted(current_paths - old_paths)
    )
    manifest = {
        "schema_version": "1.0",
        "generation_rules": rules,
        "files": records,
        "support_files": current_support,
    }
    errors = validate_test_manifest(root, manifest)
    if errors:
        raise GateError(*errors)
    write_json(path, manifest)
    print(
        json.dumps(
            {
                "status": "test_manifest_synced",
                "file_count": len(current),
                "manifest_sha256": sha256_file(path),
                "path": str(path),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


def resolve_supplied_path(root: Path, value: Path, code: str) -> Path:
    """Resolve a CLI path while keeping every evolution artifact under root."""

    candidate = value.expanduser()
    target = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
    try:
        target.relative_to(root)
    except ValueError as error:
        raise GateError(f"{code}_unsafe_path") from error
    return target


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def validate_evolution_workflow(workflow: dict) -> list[str]:
    """Validate the executable DAG before any run directory is created."""

    errors: list[str] = []
    allowed_top = {"schema_version", "workflow_id", "description", "steps"}
    if set(workflow) - allowed_top:
        errors.append("evolution_workflow_unknown_field")
    if workflow.get("schema_version") != "1.0":
        errors.append("evolution_workflow_schema_version")
    workflow_id = workflow.get("workflow_id")
    if not isinstance(workflow_id, str) or not re.fullmatch(
        r"[a-z][a-z0-9_-]{0,95}", workflow_id
    ):
        errors.append("evolution_workflow_id_invalid")
    steps = workflow.get("steps")
    if not isinstance(steps, list) or not steps:
        return sorted(set(errors + ["evolution_workflow_steps_invalid"]))

    identifiers: list[str] = []
    dependencies: dict[str, list[str]] = {}
    for step in steps:
        if not isinstance(step, dict):
            errors.append("evolution_step_invalid")
            continue
        allowed_step = {
            "id",
            "kind",
            "depends_on",
            "argv",
            "expected",
            "input_files",
            "description",
        }
        if set(step) - allowed_step:
            errors.append("evolution_step_unknown_field")
        step_id = step.get("id")
        if not isinstance(step_id, str) or not re.fullmatch(
            r"[a-z][a-z0-9_-]{0,63}", step_id
        ):
            errors.append("evolution_step_id_invalid")
            continue
        if step_id in identifiers:
            errors.append("evolution_step_id_duplicate")
        identifiers.append(step_id)
        depends_on = step.get("depends_on")
        if (
            not isinstance(depends_on, list)
            or len(depends_on) != len(set(depends_on))
            or not all(isinstance(item, str) and item for item in depends_on)
        ):
            errors.append("evolution_step_dependencies_invalid")
            depends_on = []
        dependencies[step_id] = depends_on
        kind = step.get("kind")
        if kind == "command":
            argv = step.get("argv")
            if (
                not isinstance(argv, list)
                or len(argv) < 2
                or not all(isinstance(token, str) and token for token in argv)
            ):
                errors.append("evolution_argv_invalid")
            if step.get("expected") not in {"red", "exit_zero"}:
                errors.append("evolution_expected_invalid")
            input_files = step.get("input_files", [])
            if (
                not isinstance(input_files, list)
                or not all(isinstance(item, str) and item for item in input_files)
            ):
                errors.append("evolution_input_files_invalid")
        elif kind == "external":
            if "argv" in step or "expected" in step or "input_files" in step:
                errors.append("evolution_external_step_has_command")
        else:
            errors.append("evolution_step_kind_invalid")

    identifier_set = set(identifiers)
    for step_id, parents in dependencies.items():
        if step_id in parents or any(parent not in identifier_set for parent in parents):
            errors.append("evolution_step_dependency_unknown")

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(step_id: str) -> None:
        if step_id in visited:
            return
        if step_id in visiting:
            errors.append("evolution_workflow_cycle")
            return
        visiting.add(step_id)
        for parent in dependencies.get(step_id, []):
            if parent in identifier_set:
                visit(parent)
        visiting.remove(step_id)
        visited.add(step_id)

    for identifier in identifiers:
        visit(identifier)
    return sorted(set(errors))


def expand_evolution_argv(
    root: Path,
    run_dir: Path,
    step: dict,
    *,
    require_available: bool = True,
) -> list[str]:
    """Expand a static argv template and reject shell or dynamic-code escape hatches."""

    argv = step.get("argv")
    if not isinstance(argv, list) or len(argv) < 2:
        raise GateError("evolution_argv_invalid")
    placeholders = {
        "{python}": sys.executable,
        "{root}": str(root),
        "{run_dir}": str(run_dir),
    }
    expanded: list[str] = []
    shell_tokens = {";", "&&", "||", "|", ">", ">>", "<", "<<"}
    for token in argv:
        if (
            not isinstance(token, str)
            or not token
            or token in shell_tokens
            or "\n" in token
            or "\r" in token
            or "`" in token
            or "$(" in token
        ):
            raise GateError("evolution_argv_unsafe")
        rendered = token
        for placeholder, replacement in placeholders.items():
            rendered = rendered.replace(placeholder, replacement)
        if re.search(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", rendered):
            raise GateError("evolution_argv_unknown_placeholder")
        expanded.append(rendered)
    if argv[0] != "{python}" or expanded[0] != sys.executable:
        raise GateError("evolution_argv_unsafe")
    if expanded[1] in {"-c", "-m"} or expanded[1].startswith("-"):
        raise GateError("evolution_argv_unsafe")
    script = Path(expanded[1]).expanduser().resolve()
    try:
        script.relative_to(root)
    except ValueError as error:
        raise GateError("evolution_argv_unsafe") from error
    if script.suffix != ".py" or (
        require_available and (not script.is_file() or script.is_symlink())
    ):
        raise GateError("evolution_argv_unsafe")
    expanded[1] = str(script)
    return expanded


def expand_evolution_input_files(
    root: Path,
    run_dir: Path,
    step: dict,
    *,
    require_available: bool,
) -> list[Path]:
    """Resolve the command's declared file inputs without shell expansion."""

    values = step.get("input_files", [])
    if (
        not isinstance(values, list)
        or not all(isinstance(value, str) and value for value in values)
    ):
        raise GateError("evolution_input_files_invalid")
    placeholders = {
        "{root}": str(root),
        "{run_dir}": str(run_dir),
    }
    paths: list[Path] = []
    seen: set[Path] = set()
    for value in values:
        if (
            "\n" in value
            or "\r" in value
            or "\x00" in value
            or (Path(value).is_absolute() and not value.startswith(("{root}", "{run_dir}")))
        ):
            raise GateError("evolution_input_file_unsafe_path")
        rendered = value
        for placeholder, replacement in placeholders.items():
            rendered = rendered.replace(placeholder, replacement)
        if re.search(r"\{[a-zA-Z_][a-zA-Z0-9_]*\}", rendered):
            raise GateError("evolution_input_file_unsafe_path")
        if rendered.startswith(REPOSITORY_INPUT_PREFIX):
            target = resolve_scoped_input(
                root,
                rendered,
                "evolution_input_file",
            )
            base = root.resolve().parents[1]
        else:
            candidate = Path(rendered).expanduser()
            if not candidate.is_absolute():
                candidate = root / candidate
            target = candidate.resolve()
            try:
                target.relative_to(root)
            except ValueError as error:
                raise GateError("evolution_input_file_unsafe_path") from error
            base = root
        relative = target.relative_to(base)
        cursor = base
        has_symlink = False
        for part in relative.parts:
            cursor = cursor / part
            if cursor.is_symlink():
                has_symlink = True
                break
        if target in seen:
            raise GateError("evolution_input_files_invalid")
        seen.add(target)
        if require_available and (has_symlink or not target.is_file()):
            raise GateError("evolution_command_input_unavailable")
        paths.append(target)
        if target == (root / "evals" / "regression-dependency-manifest.json").resolve():
            for dependency in regression_dependency_paths(
                root,
                target,
                require_available=require_available,
            ):
                if dependency in seen:
                    continue
                seen.add(dependency)
                paths.append(dependency)
        if target == (root / "evals" / "red-evidence-manifest.json").resolve():
            for dependency in red_evidence_dependency_paths(
                root,
                target,
                require_available=require_available,
            ):
                if dependency in seen:
                    continue
                seen.add(dependency)
                paths.append(dependency)
    return sorted(
        paths,
        key=lambda path: scoped_input_reference(
            root,
            path,
            "evolution_input_file",
        ),
    )


def regression_dependency_paths(
    root: Path,
    manifest_path: Path,
    *,
    require_available: bool,
) -> list[Path]:
    """Resolve and optionally hash-check the full-regression dependency closure."""

    manifest = read_json(manifest_path, "evolution_regression_dependency_manifest")
    if set(manifest) != {"schema_version", "files"} or manifest.get("schema_version") != "1.0":
        raise GateError("evolution_regression_dependency_manifest_invalid")
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise GateError("evolution_regression_dependency_manifest_invalid")
    identities: list[tuple[str, str]] = []
    paths: list[Path] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {"scope", "path", "sha256"}:
            raise GateError("evolution_regression_dependency_manifest_invalid")
        scope, relative, expected = record.get("scope"), record.get("path"), record.get("sha256")
        if scope not in {"skill", "repository"} or not isinstance(relative, str) or not is_sha256(expected):
            raise GateError("evolution_regression_dependency_manifest_invalid")
        reference = relative if scope == "skill" else REPOSITORY_INPUT_PREFIX + relative
        target = resolve_scoped_input(
            root,
            reference,
            "evolution_regression_dependency_manifest",
        )
        if require_available and (
            not target.is_file()
            or target.is_symlink()
            or sha256_file(target) != expected
        ):
            raise GateError("evolution_regression_dependency_hash_mismatch")
        identities.append((scope, relative))
        paths.append(target)
    if identities != sorted(set(identities)) or len(paths) != len(set(paths)):
        raise GateError("evolution_regression_dependency_manifest_invalid")
    return paths


def red_evidence_dependency_paths(
    root: Path,
    manifest_path: Path,
    *,
    require_available: bool,
) -> list[Path]:
    """Expand current files plus receipt-backed history read by the red verifier."""

    manifest = read_json(manifest_path, "evolution_red_evidence_manifest")
    if (
        set(manifest) != {"schema_version", "append_only", "records", "sealed_prefix"}
        or manifest.get("schema_version") != "1.0"
        or manifest.get("append_only") is not True
        or not isinstance(manifest.get("records"), list)
    ):
        raise GateError("evolution_red_evidence_manifest_invalid")
    test_manifest_path = (root / "evals" / "test-generation-manifest.json").resolve()
    test_manifest = read_json(
        test_manifest_path,
        "evolution_red_evidence_test_manifest",
    )
    if (
        test_manifest.get("schema_version") != "1.0"
        or not isinstance(test_manifest.get("files"), list)
    ):
        raise GateError("evolution_red_evidence_test_manifest_invalid")
    if validate_manifest_migration_history(root, test_manifest):
        raise GateError("evolution_red_evidence_test_migration_invalid")

    test_records: dict[str, dict] = {}
    for record in test_manifest["files"]:
        if not isinstance(record, dict) or not isinstance(record.get("path"), str):
            raise GateError("evolution_red_evidence_test_manifest_invalid")
        relative = record["path"]
        if relative in test_records or not is_sha256(record.get("sha256")):
            raise GateError("evolution_red_evidence_test_manifest_invalid")
        history = record.get("migration_history", [])
        if not isinstance(history, list):
            raise GateError("evolution_red_evidence_test_manifest_invalid")
        test_records[relative] = record

    paths: list[Path] = [test_manifest_path]
    identities: set[str] = {"evals/test-generation-manifest.json"}

    def add_dependency(relative: str, *, code: str) -> Path:
        target = resolve_within(root, relative, code)
        if require_available and (not target.is_file() or target.is_symlink()):
            raise GateError(code + "_missing")
        if relative not in identities:
            identities.add(relative)
            paths.append(target)
        return target

    migration_schema = "schemas/test-migration-receipt.schema.json"
    add_dependency(migration_schema, code="evolution_red_evidence_migration_schema")
    for test_record in test_records.values():
        for entry in test_record.get("migration_history", []):
            if not isinstance(entry, dict) or not isinstance(entry.get("receipt_path"), str):
                raise GateError("evolution_red_evidence_test_migration_invalid")
            receipt_relative = entry["receipt_path"]
            receipt_path = add_dependency(
                receipt_relative,
                code="evolution_red_evidence_migration_receipt",
            )
            receipt = read_json(
                receipt_path,
                "evolution_red_evidence_migration_receipt",
            )
            for field in ("evidence", "replacement_tests"):
                bindings = receipt.get(field)
                if not isinstance(bindings, list):
                    raise GateError("evolution_red_evidence_test_migration_invalid")
                for binding in bindings:
                    if not isinstance(binding, dict) or not isinstance(binding.get("path"), str):
                        raise GateError("evolution_red_evidence_test_migration_invalid")
                    add_dependency(
                        binding["path"],
                        code="evolution_red_evidence_migration_artifact",
                    )

    for record in manifest["records"]:
        if not isinstance(record, dict) or not isinstance(record.get("tests"), list):
            raise GateError("evolution_red_evidence_manifest_invalid")
        evidence = record.get("evidence")
        if (
            not isinstance(evidence, dict)
            or set(evidence) != {"path", "sha256"}
            or not isinstance(evidence.get("path"), str)
            or not is_sha256(evidence.get("sha256"))
        ):
            raise GateError("evolution_red_evidence_manifest_invalid")
        evidence_path = add_dependency(
            evidence["path"],
            code="evolution_red_evidence_artifact",
        )
        if require_available and sha256_file(evidence_path) != evidence["sha256"]:
            raise GateError("evolution_red_evidence_artifact_hash_mismatch")

        for binding in record["tests"]:
            if (
                not isinstance(binding, dict)
                or set(binding) != {"path", "sha256"}
                or not isinstance(binding.get("path"), str)
                or not is_sha256(binding.get("sha256"))
            ):
                raise GateError("evolution_red_evidence_manifest_invalid")
            test_record = test_records.get(binding["path"])
            if test_record is None:
                raise GateError("evolution_red_evidence_test_manifest_path_missing")
            allowed_hashes = {test_record["sha256"]}
            for entry in test_record.get("migration_history", []):
                if not isinstance(entry, dict):
                    raise GateError("evolution_red_evidence_test_migration_invalid")
                allowed_hashes.update(
                    value
                    for value in (entry.get("from_sha256"), entry.get("to_sha256"))
                    if is_sha256(value)
                )
            if binding["sha256"] not in allowed_hashes:
                raise GateError("evolution_red_evidence_artifact_hash_mismatch")
            target = add_dependency(
                binding["path"],
                code="evolution_red_evidence_artifact",
            )
            if require_available and (
                sha256_file(target) != test_record["sha256"]
            ):
                raise GateError("evolution_red_evidence_artifact_hash_mismatch")
    return paths


def command_input_snapshot(
    root: Path,
    run_dir: Path,
    step: dict,
    *,
    environment: dict[str, str],
) -> dict:
    paths = expand_evolution_input_files(
        root,
        run_dir,
        step,
        require_available=True,
    )
    return {
        "cwd": ".",
        "environment": dict(environment),
        "files": [
            {
                "path": scoped_input_reference(
                    root,
                    path,
                    "evolution_input_file",
                ),
                "sha256": sha256_file(path),
            }
            for path in paths
        ],
    }


def load_evolution_workflow(root: Path, workflow_path: Path) -> dict:
    if not workflow_path.is_file() or workflow_path.is_symlink():
        raise GateError("evolution_workflow_missing")
    workflow = read_json(workflow_path, "evolution_workflow")
    errors = validate_evolution_workflow(workflow)
    if errors:
        raise GateError(*errors)
    if schema_validation_errors(workflow, "evolution-workflow.schema.json"):
        raise GateError("evolution_workflow_schema_invalid")
    return workflow


def preflight_evolution_commands(
    root: Path,
    run_dir: Path,
    workflow: dict,
) -> None:
    for step in workflow["steps"]:
        if step["kind"] == "command":
            expand_evolution_argv(root, run_dir, step)
            expand_evolution_input_files(
                root,
                run_dir,
                step,
                require_available=False,
            )


def read_loop_events(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    events: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError
                events.append(value)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise GateError("evolution_event_log_invalid") from error
    return events


def verify_loop_event_chain(run_dir: Path, state: dict) -> None:
    events = read_loop_events(run_dir / "events.jsonl")
    previous: str | None = None
    for index, event in enumerate(events, start=1):
        if schema_validation_errors(event, "evolution-run-event.schema.json"):
            raise GateError("evolution_event_schema_invalid")
        saved_hash = event.get("event_sha256")
        unsigned = dict(event)
        unsigned.pop("event_sha256", None)
        if (
            event.get("event_id") != index
            or event.get("previous_event_sha256") != previous
            or not is_sha256(saved_hash)
            or sha256_bytes(canonical_json_bytes(unsigned)) != saved_hash
        ):
            raise GateError("evolution_event_chain_invalid")
        previous = saved_hash
    if state.get("event_count") != len(events) or state.get("event_head_sha256") != previous:
        raise GateError("evolution_event_projection_mismatch")


def replay_loop_events(run_dir: Path, state: dict, workflow: dict) -> None:
    """Replay the append-only log and compare its semantic projection to state.

    A valid hash chain only proves that the current lines agree with one
    another.  It does not prove that a command ran after its dependencies, a
    terminal event is unique, or a completed state was actually reached.
    This replay is deliberately independent from receipt validation so an
    attacker must satisfy both the event history and the file-backed evidence.
    """

    events = read_loop_events(run_dir / "events.jsonl")
    if not events:
        raise GateError("evolution_event_terminal_invalid")
    run_id = state.get("run_id")
    workflow_steps = {step["id"]: step for step in workflow["steps"]}
    replay_steps = {
        step_id: {
            "kind": step["kind"],
            "status": "pending",
            "receipt_sha256": None,
        }
        for step_id, step in workflow_steps.items()
    }
    allowed_types = {
        "run_started",
        "command_completed",
        "command_failed",
        "external_action_required",
        "external_action_completed",
        "run_completed",
        "run_failed",
    }
    replay_status = "running"
    replay_current_step: str | None = None
    replay_failure_code: str | None = None
    run_started_count = 0
    run_completed_count = 0
    run_failed_count = 0
    step_terminal_events: set[str] = set()
    active_external: str | None = None
    run_terminal_seen = False

    for index, event in enumerate(events):
        event_type = event.get("event_type")
        data = event.get("data")
        if (
            event.get("schema_version") != "1.0"
            or event_type not in allowed_types
            or not isinstance(data, dict)
            or not isinstance(event.get("recorded_at"), str)
        ):
            raise GateError("evolution_event_schema_invalid")
        if event.get("run_id") != run_id:
            raise GateError("evolution_event_run_binding_mismatch")
        if run_terminal_seen:
            raise GateError("evolution_event_terminal_invalid")

        if event_type == "run_started":
            run_started_count += 1
            expected_start_data = {
                "workflow_sha256": state.get("workflow_sha256"),
                "candidate_id": state.get("candidate_id"),
            }
            if isinstance(state.get("predecessor_binding"), dict):
                expected_start_data["predecessor_binding_sha256"] = sha256_bytes(
                    canonical_json_bytes(state["predecessor_binding"])
                )
                expected_start_data["carry_over_blockers_sha256"] = sha256_bytes(
                    canonical_json_bytes(
                        state.get("carry_over_blocker_bindings", [])
                    )
                )
                if state.get("resolved_blocker_bindings"):
                    expected_start_data["blocker_resolutions_sha256"] = sha256_bytes(
                        canonical_json_bytes(state["resolved_blocker_bindings"])
                    )
            if index != 0 or run_started_count != 1:
                raise GateError("evolution_event_terminal_invalid")
            if data != expected_start_data:
                raise GateError("evolution_event_run_binding_mismatch")
            continue

        if run_started_count != 1:
            raise GateError("evolution_event_sequence_invalid")

        if event_type in {"command_completed", "command_failed"}:
            step_id = data.get("step_id")
            step = workflow_steps.get(step_id)
            if step is None or step.get("kind") != "command":
                raise GateError("evolution_event_step_binding_invalid")
            if step_id in step_terminal_events or replay_steps[step_id]["status"] != "pending":
                raise GateError("evolution_event_terminal_invalid")
            if active_external is not None or any(
                replay_steps[parent]["status"] != "completed"
                for parent in step.get("depends_on", [])
            ):
                raise GateError("evolution_event_sequence_invalid")
            if (
                data.get("assertion") != step.get("expected")
                or not isinstance(data.get("exit_code"), int)
                or not is_sha256(data.get("receipt_sha256"))
            ):
                raise GateError("evolution_event_step_binding_invalid")
            step_terminal_events.add(step_id)
            replay_current_step = step_id
            replay_steps[step_id]["receipt_sha256"] = data["receipt_sha256"]
            if event_type == "command_completed":
                replay_steps[step_id]["status"] = "completed"
                replay_status = "running"
            else:
                replay_steps[step_id]["status"] = "failed"
                replay_status = "failed"
                replay_failure_code = f"evolution_command_assertion_failed:{step_id}"
                run_terminal_seen = True
            continue

        if event_type == "external_action_required":
            step_id = data.get("step_id")
            step = workflow_steps.get(step_id)
            if step is None or step.get("kind") != "external":
                raise GateError("evolution_event_step_binding_invalid")
            if (
                active_external is not None
                or replay_steps[step_id]["status"] != "pending"
                or step_id in step_terminal_events
            ):
                raise GateError("evolution_event_terminal_invalid")
            if any(
                replay_steps[parent]["status"] != "completed"
                for parent in step.get("depends_on", [])
            ):
                raise GateError("evolution_event_sequence_invalid")
            replay_steps[step_id]["status"] = "waiting"
            active_external = step_id
            replay_status = "awaiting_external_action"
            replay_current_step = step_id
            continue

        if event_type == "external_action_completed":
            step_id = data.get("step_id")
            step = workflow_steps.get(step_id)
            if step is None or step.get("kind") != "external":
                raise GateError("evolution_event_step_binding_invalid")
            if (
                active_external != step_id
                or replay_steps[step_id]["status"] != "waiting"
                or step_id in step_terminal_events
            ):
                raise GateError("evolution_event_sequence_invalid")
            if not is_sha256(data.get("receipt_sha256")):
                raise GateError("evolution_event_step_binding_invalid")
            step_terminal_events.add(step_id)
            replay_steps[step_id]["status"] = "completed"
            replay_steps[step_id]["receipt_sha256"] = data["receipt_sha256"]
            active_external = None
            replay_status = "running"
            replay_current_step = None
            continue

        if event_type == "run_completed":
            run_completed_count += 1
            completed_artifacts = state.get("completed_artifacts")
            completed_artifacts_sha256 = (
                sha256_bytes(canonical_json_bytes(completed_artifacts))
                if isinstance(completed_artifacts, dict)
                else None
            )
            if (
                run_completed_count != 1
                or run_failed_count
                or set(data) != {"completed_artifacts_sha256"}
                or data.get("completed_artifacts_sha256")
                != completed_artifacts_sha256
                or any(
                    projection["status"] != "completed"
                    for projection in replay_steps.values()
                )
                or index != len(events) - 1
            ):
                raise GateError("evolution_event_terminal_invalid")
            replay_status = "complete"
            replay_current_step = None
            run_terminal_seen = True
            continue

        if event_type == "run_failed":
            run_failed_count += 1
            code = data.get("code")
            incomplete = data.get("steps")
            expected_incomplete = [
                step_id
                for step_id, projection in replay_steps.items()
                if projection["status"] != "completed"
            ]
            if (
                run_failed_count != 1
                or run_completed_count
                or not isinstance(code, str)
                or not code
                or incomplete != expected_incomplete
                or index != len(events) - 1
            ):
                raise GateError("evolution_event_terminal_invalid")
            replay_status = "failed"
            replay_failure_code = code
            run_terminal_seen = True

    if run_started_count != 1:
        raise GateError("evolution_event_terminal_invalid")
    state_status = state.get("status")
    if state_status == "complete" and run_completed_count != 1:
        raise GateError("evolution_event_terminal_invalid")
    if state_status != "complete" and run_completed_count:
        raise GateError("evolution_event_terminal_invalid")
    if state_status == "failed" and not run_terminal_seen:
        raise GateError("evolution_event_terminal_invalid")
    if state_status == "awaiting_external_action" and (
        active_external is None or events[-1].get("event_type") != "external_action_required"
    ):
        raise GateError("evolution_event_terminal_invalid")

    saved_steps = state.get("steps")
    if not isinstance(saved_steps, dict) or set(saved_steps) != set(replay_steps):
        raise GateError("evolution_event_projection_mismatch")
    for step_id, projection in replay_steps.items():
        saved = saved_steps.get(step_id)
        if (
            not isinstance(saved, dict)
            or saved.get("kind") != projection["kind"]
            or saved.get("status") != projection["status"]
        ):
            raise GateError("evolution_event_projection_mismatch")
        if projection["receipt_sha256"] is not None and (
            saved.get("receipt_sha256") != projection["receipt_sha256"]
        ):
            raise GateError("evolution_event_projection_mismatch")
    if (
        state_status != replay_status
        or state.get("current_step") != replay_current_step
        or (
            replay_status == "failed"
            and state.get("failure_code") != replay_failure_code
        )
    ):
        raise GateError("evolution_event_projection_mismatch")


def append_loop_event(
    run_dir: Path,
    state: dict,
    event_type: str,
    data: dict,
) -> None:
    event = {
        "schema_version": "1.0",
        "event_id": state.get("event_count", 0) + 1,
        "run_id": state["run_id"],
        "event_type": event_type,
        "recorded_at": utc_now(),
        "previous_event_sha256": state.get("event_head_sha256"),
        "data": data,
    }
    event["event_sha256"] = sha256_bytes(canonical_json_bytes(event))
    path = run_dir / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(canonical_json_bytes(event) + b"\n")
        handle.flush()
        os.fsync(handle.fileno())
    state["event_count"] = event["event_id"]
    state["event_head_sha256"] = event["event_sha256"]


def verify_loop_receipts(
    root: Path,
    run_dir: Path,
    state: dict,
    workflow: dict,
    *,
    use_frozen_snapshots: bool = False,
) -> None:
    """Verify every terminal receipt and its projected workflow state.

    A failed command is evidence, not an ignorable partial result.  Completed
    and failed command receipts therefore receive the same hash, raw-output,
    assertion and event binding checks.  This prevents a caller from promoting
    a failed receipt to a completed step by editing only ``run-state.json``.
    """

    projections = state.get("steps")
    if not isinstance(projections, dict):
        raise GateError("evolution_step_projection_invalid")
    workflow_steps = {step["id"]: step for step in workflow["steps"]}
    if set(projections) != set(workflow_steps):
        raise GateError("evolution_step_projection_invalid")

    events = read_loop_events(run_dir / "events.jsonl")
    terminal_events: dict[str, dict] = {}
    waiting_events: set[str] = set()
    for event in events:
        data = event.get("data")
        if not isinstance(data, dict) or not isinstance(data.get("step_id"), str):
            continue
        step_id = data["step_id"]
        if event.get("event_type") in {
            "command_completed",
            "command_failed",
            "external_action_completed",
        }:
            terminal_events[step_id] = event
        elif event.get("event_type") == "external_action_required":
            waiting_events.add(step_id)

    for step_id, projection in projections.items():
        if not isinstance(projection, dict):
            raise GateError("evolution_step_projection_invalid")
        step = workflow_steps[step_id]
        if projection.get("kind") != step["kind"]:
            raise GateError("evolution_step_projection_invalid")
        status = projection.get("status")
        if status not in {"pending", "waiting", "completed", "failed"}:
            raise GateError("evolution_step_projection_invalid")
        if status == "waiting":
            if step["kind"] != "external" or step_id not in waiting_events:
                raise GateError("evolution_step_projection_invalid")
            if projection.get("receipt_path") is not None or projection.get("receipt_sha256") is not None:
                raise GateError("evolution_step_projection_invalid")
            continue
        if status == "pending":
            if projection.get("receipt_path") is not None or projection.get("receipt_sha256") is not None:
                raise GateError("evolution_step_projection_invalid")
            continue

        relative = projection.get("receipt_path")
        saved_hash = projection.get("receipt_sha256")
        if not isinstance(relative, str) or not is_sha256(saved_hash):
            raise GateError("evolution_receipt_projection_invalid")
        receipt_path = resolve_within(root, relative, "evolution_receipt")
        if (
            not receipt_path.is_file()
            or receipt_path.is_symlink()
            or sha256_file(receipt_path) != saved_hash
        ):
            raise GateError("evolution_receipt_hash_mismatch")
        receipt = read_json(receipt_path, "evolution_receipt")
        receipt_schema = (
            "evolution-command-receipt.schema.json"
            if step["kind"] == "command"
            else "evolution-stored-external-receipt.schema.json"
        )
        if schema_validation_errors(receipt, receipt_schema):
            raise GateError(
                "evolution_command_receipt_schema_invalid"
                if step["kind"] == "command"
                else "evolution_external_receipt_schema_invalid"
            )
        if (
            receipt.get("run_id") != state.get("run_id")
            or receipt.get("candidate_id") != state.get("candidate_id")
            or receipt.get("workflow_sha256") != state.get("workflow_sha256")
            or receipt.get("step_id") != step_id
            or receipt.get("kind") != step["kind"]
        ):
            raise GateError("evolution_receipt_binding_mismatch")
        if receipt.get("kind") == "command":
            expected_argv = expand_evolution_argv(
                root,
                run_dir,
                step,
                require_available=not use_frozen_snapshots,
            )
            expected_script = Path(expected_argv[1])
            expected_script_relative = expected_script.relative_to(root).as_posix()
            if (
                receipt.get("script_path") != expected_script_relative
                or not is_sha256(receipt.get("script_sha256"))
            ):
                raise GateError("evolution_command_script_binding_invalid")
            script_evidence = (
                command_script_snapshot_path(run_dir, step_id)
                if use_frozen_snapshots
                else expected_script
            )
            if (
                not script_evidence.is_file()
                or script_evidence.is_symlink()
                or sha256_file(script_evidence) != receipt["script_sha256"]
            ):
                raise GateError("evolution_command_script_hash_mismatch")

            input_snapshot = receipt.get("input_snapshot")
            declared_inputs = expand_evolution_input_files(
                root,
                run_dir,
                step,
                require_available=False,
            )
            expected_input_paths = [
                scoped_input_reference(
                    root,
                    path,
                    "evolution_input_file",
                )
                for path in declared_inputs
            ]
            if (
                not isinstance(input_snapshot, dict)
                or set(input_snapshot) != {"cwd", "environment", "files"}
                or input_snapshot.get("cwd") != "."
                or input_snapshot.get("environment")
                != controlled_command_environment()
                or not isinstance(input_snapshot.get("files"), list)
            ):
                raise GateError("evolution_command_input_binding_invalid")
            saved_input_files = input_snapshot["files"]
            if (
                any(
                    not isinstance(item, dict)
                    or set(item) != {"path", "sha256"}
                    or not isinstance(item.get("path"), str)
                    or not is_sha256(item.get("sha256"))
                    for item in saved_input_files
                )
                or [item["path"] for item in saved_input_files] != expected_input_paths
            ):
                raise GateError("evolution_command_input_binding_invalid")
            for index, (path, saved) in enumerate(
                zip(declared_inputs, saved_input_files, strict=True)
            ):
                input_evidence = (
                    command_input_snapshot_path(run_dir, step_id, index)
                    if use_frozen_snapshots
                    else path
                )
                if (
                    not input_evidence.is_file()
                    or input_evidence.is_symlink()
                    or sha256_file(input_evidence) != saved["sha256"]
                ):
                    raise GateError("evolution_command_input_hash_mismatch")

            raw_text: dict[str, str] = {}
            for stream in ("stdout", "stderr"):
                raw_relative = receipt.get(f"{stream}_path")
                expected = receipt.get(f"{stream}_sha256")
                if not isinstance(raw_relative, str) or not is_sha256(expected):
                    raise GateError("evolution_raw_output_invalid")
                raw_path = resolve_within(root, raw_relative, "evolution_raw_output")
                if not raw_path.is_file() or sha256_file(raw_path) != expected:
                    raise GateError("evolution_raw_output_hash_mismatch")
                raw_text[stream] = raw_path.read_text(encoding="utf-8")
            exit_code = receipt.get("exit_code")
            assertion = receipt.get("assertion")
            if (
                not isinstance(exit_code, int)
                or assertion != step.get("expected")
                or receipt.get("argv") != expected_argv
                or not isinstance(receipt.get("assertion_passed"), bool)
            ):
                raise GateError("evolution_receipt_assertion_invalid")
            assertion_passed = assertion_for_command(
                assertion,
                exit_code,
                raw_text["stdout"],
                raw_text["stderr"],
            )
            if receipt["assertion_passed"] != assertion_passed:
                raise GateError("evolution_receipt_assertion_invalid")
            projected_status = "completed" if assertion_passed else "failed"
            expected_event = "command_completed" if assertion_passed else "command_failed"
        else:
            if status == "failed":
                raise GateError("evolution_step_projection_invalid")
            evidence = receipt.get("evidence")
            if (
                receipt.get("status") != "completed"
                or not isinstance(receipt.get("summary"), str)
                or not receipt["summary"].strip()
                or not is_sha256(receipt.get("source_sha256"))
                or not isinstance(evidence, list)
                or not evidence
            ):
                raise GateError("evolution_external_evidence_binding_invalid")
            for item in evidence:
                if (
                    not isinstance(item, dict)
                    or set(item) != {"path", "sha256"}
                    or not isinstance(item.get("path"), str)
                    or not is_sha256(item.get("sha256"))
                ):
                    raise GateError("evolution_external_evidence_binding_invalid")
                evidence_path = resolve_within(
                    root,
                    item["path"],
                    "evolution_external_evidence",
                )
                if (
                    not evidence_path.is_file()
                    or evidence_path.is_symlink()
                    or sha256_file(evidence_path) != item["sha256"]
                ):
                    raise GateError("evolution_external_evidence_hash_mismatch")
            projected_status = "completed"
            expected_event = "external_action_completed"

        terminal_event = terminal_events.get(step_id)
        if (
            status != projected_status
            or terminal_event is None
            or terminal_event.get("event_type") != expected_event
            or terminal_event.get("data", {}).get("receipt_sha256") != saved_hash
        ):
            raise GateError("evolution_step_projection_invalid")

    statuses = {
        step_id: projection.get("status")
        for step_id, projection in projections.items()
    }
    run_status = state.get("status")
    if run_status == "complete" and (
        any(value != "completed" for value in statuses.values())
        or state.get("current_step") is not None
    ):
        raise GateError("evolution_step_projection_invalid")
    if run_status == "failed" and "failed" not in statuses.values():
        raise GateError("evolution_step_projection_invalid")
    if run_status == "awaiting_external_action":
        waiting = [step_id for step_id, value in statuses.items() if value == "waiting"]
        if len(waiting) != 1 or state.get("current_step") != waiting[0]:
            raise GateError("evolution_step_projection_invalid")


def load_loop_state(
    root: Path,
    run_dir: Path,
    *,
    verify_candidate_current: bool = True,
) -> tuple[dict, dict, Path]:
    state = read_json(run_dir / "run-state.json", "evolution_run_state")
    if schema_validation_errors(state, "evolution-run-state.schema.json"):
        raise GateError("evolution_run_state_schema_invalid")
    if state.get("schema_version") != "1.0":
        raise GateError("evolution_run_state_schema_version")
    workflow_relative = state.get("workflow_path")
    if not isinstance(workflow_relative, str):
        raise GateError("evolution_workflow_binding_invalid")
    workflow_path = resolve_within(root, workflow_relative, "evolution_workflow")
    frozen_workflow = workflow_snapshot_path(run_dir)
    if verify_candidate_current:
        workflow = load_evolution_workflow(root, workflow_path)
        if sha256_file(workflow_path) != state.get("workflow_sha256"):
            raise GateError("evolution_workflow_drift")
    else:
        workflow = load_evolution_workflow(root, frozen_workflow)
        if sha256_file(frozen_workflow) != state.get("workflow_sha256"):
            raise GateError("evolution_workflow_snapshot_mismatch")
    if workflow.get("workflow_id") != state.get("workflow_id"):
        raise GateError("evolution_workflow_binding_invalid")
    if verify_candidate_current:
        preflight_evolution_commands(root, run_dir, workflow)
    verify_loop_event_chain(run_dir, state)
    verify_loop_receipts(
        root,
        run_dir,
        state,
        workflow,
        use_frozen_snapshots=not verify_candidate_current,
    )
    replay_loop_events(run_dir, state, workflow)
    validate_carry_over_bindings(root, state)
    validate_predecessor_binding(root, state)
    validate_resolved_blocker_bindings(root, state)
    if state.get("status") in {"complete", "failed"} and verify_candidate_current:
        completed_artifacts = state.get("completed_artifacts")
        if validate_artifact_hashes(
            completed_artifacts,
            "evolution_completed_artifacts",
            require_governance=True,
        ):
            raise GateError("evolution_candidate_snapshot_invalid")
        current_artifacts = collect_snapshot(root, workflow_path, strict=False)
        if current_artifacts != completed_artifacts:
            raise GateError("evolution_candidate_snapshot_mismatch")
    return state, workflow, workflow_path


def assertion_for_command(expected: str, exit_code: int, stdout: str, stderr: str) -> bool:
    if expected == "exit_zero":
        return exit_code == 0
    combined = stdout + "\n" + stderr
    if expected != "red" or exit_code == 0:
        return False
    summary = re.search(r"^FAILED \(([^\n)]*)\)$", combined, re.MULTILINE)
    if summary is None or re.search(
        r"^Ran [1-9][0-9]* tests?(?:\s+in\s+[^\n]+)?$",
        combined,
        re.MULTILINE,
    ) is None:
        return False
    details = summary.group(1)
    failures = re.search(r"(?:^|,\s*)failures=([0-9]+)(?:,|$)", details)
    errors = re.search(r"(?:^|,\s*)errors=([0-9]+)(?:,|$)", details)
    return (
        failures is not None
        and int(failures.group(1)) > 0
        and (errors is None or int(errors.group(1)) == 0)
    )


def execute_evolution_command(
    root: Path,
    run_dir: Path,
    state: dict,
    step: dict,
) -> bool:
    step_id = step["id"]
    argv = expand_evolution_argv(root, run_dir, step)
    script_path = Path(argv[1])
    command_environment = controlled_command_environment()
    input_snapshot = command_input_snapshot(
        root,
        run_dir,
        step,
        environment=command_environment,
    )
    script_sha256 = sha256_file(script_path)
    write_immutable_bytes(
        command_script_snapshot_path(run_dir, step_id),
        script_path.read_bytes(),
        "evolution_command_script_snapshot",
    )
    for index, item in enumerate(input_snapshot["files"]):
        input_path = resolve_scoped_input(
            root,
            item["path"],
            "evolution_command_input_snapshot",
        )
        write_immutable_bytes(
            command_input_snapshot_path(run_dir, step_id, index),
            input_path.read_bytes(),
            "evolution_command_input_snapshot",
        )
    completed = subprocess.run(
        argv,
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
        env=command_environment,
    )
    raw_dir = run_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stdout_path = raw_dir / f"{step_id}.stdout.txt"
    stderr_path = raw_dir / f"{step_id}.stderr.txt"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    passed = assertion_for_command(
        step["expected"], completed.returncode, completed.stdout, completed.stderr
    )
    receipt = {
        "schema_version": "1.0",
        "run_id": state["run_id"],
        "candidate_id": state["candidate_id"],
        "workflow_sha256": state["workflow_sha256"],
        "step_id": step_id,
        "kind": "command",
        "argv": argv,
        "script_path": script_path.relative_to(root).as_posix(),
        "script_sha256": script_sha256,
        "input_snapshot": input_snapshot,
        "exit_code": completed.returncode,
        "assertion": step["expected"],
        "assertion_passed": passed,
        "stdout_path": stdout_path.relative_to(root).as_posix(),
        "stdout_sha256": sha256_file(stdout_path),
        "stderr_path": stderr_path.relative_to(root).as_posix(),
        "stderr_sha256": sha256_file(stderr_path),
        "recorded_at": utc_now(),
    }
    receipt_path = run_dir / "receipts" / f"{step_id}.json"
    if receipt_path.exists():
        raise GateError("evolution_receipt_refuses_overwrite")
    write_json(receipt_path, receipt)
    projection = state["steps"][step_id]
    projection.update(
        {
            "status": "completed" if passed else "failed",
            "receipt_path": receipt_path.relative_to(root).as_posix(),
            "receipt_sha256": sha256_file(receipt_path),
        }
    )
    append_loop_event(
        run_dir,
        state,
        "command_completed" if passed else "command_failed",
        {
            "step_id": step_id,
            "assertion": step["expected"],
            "exit_code": completed.returncode,
            "receipt_sha256": projection["receipt_sha256"],
        },
    )
    return passed


def save_loop_state(run_dir: Path, state: dict) -> None:
    state["updated_at"] = utc_now()
    write_json(run_dir / "run-state.json", state)


def print_loop_state(state: dict) -> None:
    print(
        json.dumps(
            {
                "schema_version": "1.0",
                "run_id": state["run_id"],
                "candidate_id": state["candidate_id"],
                "workflow_id": state["workflow_id"],
                "status": state["status"],
                "current_step": state.get("current_step"),
                "event_count": state["event_count"],
                "distribution_status": "local_unpublished",
                "publication_actions_performed": False,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def advance_evolution_loop(root: Path, run_dir: Path, state: dict, workflow: dict) -> int:
    if state.get("status") == "complete":
        print_loop_state(state)
        return 0
    if state.get("status") == "failed":
        print_loop_state(state)
        return 2
    if state.get("status") == "awaiting_external_action":
        print_loop_state(state)
        return 2

    by_id = {step["id"]: step for step in workflow["steps"]}
    while True:
        pending = [
            step
            for step in workflow["steps"]
            if state["steps"][step["id"]]["status"] == "pending"
            and all(
                state["steps"][parent]["status"] == "completed"
                for parent in step["depends_on"]
            )
        ]
        if not pending:
            incomplete = [
                step_id
                for step_id in by_id
                if state["steps"][step_id]["status"] != "completed"
            ]
            if incomplete:
                state["status"] = "failed"
                state["failure_code"] = "evolution_no_runnable_step"
                append_loop_event(
                    run_dir,
                    state,
                    "run_failed",
                    {"code": state["failure_code"], "steps": incomplete},
                )
                save_loop_state(run_dir, state)
                print_loop_state(state)
                return 2
            state["status"] = "complete"
            state["current_step"] = None
            workflow_path = resolve_within(
                root,
                state["workflow_path"],
                "evolution_workflow",
            )
            state["completed_artifacts"] = collect_snapshot(
                root,
                workflow_path,
                strict=False,
            )
            append_loop_event(
                run_dir,
                state,
                "run_completed",
                {
                    "completed_artifacts_sha256": sha256_bytes(
                        canonical_json_bytes(state["completed_artifacts"])
                    )
                },
            )
            save_loop_state(run_dir, state)
            print_loop_state(state)
            return 0

        step = pending[0]
        step_id = step["id"]
        state["current_step"] = step_id
        if step["kind"] == "external":
            state["steps"][step_id]["status"] = "waiting"
            state["status"] = "awaiting_external_action"
            append_loop_event(
                run_dir,
                state,
                "external_action_required",
                {"step_id": step_id},
            )
            save_loop_state(run_dir, state)
            print_loop_state(state)
            return 2

        state["status"] = "running"
        if not execute_evolution_command(root, run_dir, state, step):
            state["status"] = "failed"
            state["failure_code"] = f"evolution_command_assertion_failed:{step_id}"
            workflow_path = resolve_within(
                root,
                state["workflow_path"],
                "evolution_workflow",
            )
            state["completed_artifacts"] = collect_snapshot(
                root,
                workflow_path,
                strict=False,
            )
            save_loop_state(run_dir, state)
            print_loop_state(state)
            return 2
        save_loop_state(run_dir, state)


def _create_evolution_run_unlocked(
    root: Path,
    workflow_path: Path,
    run_dir: Path,
    run_id: str,
    candidate_id: str,
    *,
    lineage: dict | None = None,
) -> int:
    workflow = load_evolution_workflow(root, workflow_path)
    preflight_evolution_commands(root, run_dir, workflow)
    if run_dir.exists():
        raise GateError("evolution_run_dir_exists")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", run_id):
        raise GateError("evolution_run_id_invalid")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", candidate_id):
        raise GateError("evolution_candidate_id_invalid")
    run_dir.mkdir(parents=True)
    write_immutable_bytes(
        workflow_snapshot_path(run_dir),
        workflow_path.read_bytes(),
        "evolution_workflow_snapshot",
    )
    workflow_relative = workflow_path.relative_to(root).as_posix()
    state = {
        "schema_version": "1.0",
        "run_id": run_id,
        "candidate_id": candidate_id,
        "workflow_id": workflow["workflow_id"],
        "workflow_path": workflow_relative,
        "workflow_sha256": sha256_file(workflow_path),
        "status": "running",
        "current_step": None,
        "steps": {
            step["id"]: {
                "kind": step["kind"],
                "status": "pending",
                "receipt_path": None,
                "receipt_sha256": None,
            }
            for step in workflow["steps"]
        },
        "event_count": 0,
        "event_head_sha256": None,
        "created_at": utc_now(),
        "updated_at": utc_now(),
        "distribution_status": "local_unpublished",
        "publication_actions_performed": False,
    }
    if lineage is not None:
        state.update(copy.deepcopy(lineage))
    start_data = {
        "workflow_sha256": state["workflow_sha256"],
        "candidate_id": state["candidate_id"],
    }
    if isinstance(state.get("predecessor_binding"), dict):
        start_data["predecessor_binding_sha256"] = sha256_bytes(
            canonical_json_bytes(state["predecessor_binding"])
        )
        start_data["carry_over_blockers_sha256"] = sha256_bytes(
            canonical_json_bytes(state.get("carry_over_blocker_bindings", []))
        )
        if state.get("resolved_blocker_bindings"):
            start_data["blocker_resolutions_sha256"] = sha256_bytes(
                canonical_json_bytes(state["resolved_blocker_bindings"])
            )
    append_loop_event(
        run_dir,
        state,
        "run_started",
        start_data,
    )
    save_loop_state(run_dir, state)
    return advance_evolution_loop(root, run_dir, state, workflow)


def create_evolution_run(
    root: Path,
    workflow_path: Path,
    run_dir: Path,
    run_id: str,
    candidate_id: str,
    *,
    lineage: dict | None = None,
) -> int:
    with evolution_run_lock(run_dir, exclusive=True, create_parent=True):
        return _create_evolution_run_unlocked(
            root,
            workflow_path,
            run_dir,
            run_id,
            candidate_id,
            lineage=lineage,
        )


def command_run(args: argparse.Namespace) -> int:
    root = args.root.expanduser().resolve()
    workflow_path = resolve_supplied_path(root, args.workflow, "evolution_workflow")
    run_dir = resolve_supplied_path(root, args.run_dir, "evolution_run_dir")
    state_path = args.state.expanduser().resolve()
    with release_state_lock(state_path, exclusive=False, create_parent=True):
        if state_path.is_file():
            release_state = read_json(state_path, "release_state")
            if release_state_has_open_blockers(release_state):
                raise GateError("evolution_open_release_blockers_require_next_iteration")
        return create_evolution_run(
            root,
            workflow_path,
            run_dir,
            args.run_id,
            args.candidate_id,
        )


def command_resume(args: argparse.Namespace) -> int:
    root = args.root.expanduser().resolve()
    run_dir = resolve_supplied_path(root, args.run_dir, "evolution_run_dir")
    with evolution_run_lock(run_dir, exclusive=True):
        state, workflow, _ = load_loop_state(root, run_dir)
        return advance_evolution_loop(root, run_dir, state, workflow)


def command_loop_status(args: argparse.Namespace) -> int:
    root = args.root.expanduser().resolve()
    run_dir = resolve_supplied_path(root, args.run_dir, "evolution_run_dir")
    with evolution_run_lock(run_dir, exclusive=False):
        state, _, _ = load_loop_state(root, run_dir)
        print_loop_state(state)
        return 0


def _command_next_iteration_unlocked(args: argparse.Namespace) -> int:
    root = args.root.expanduser().resolve()
    previous_run_dir = resolve_supplied_path(
        root, args.previous_run_dir, "evolution_predecessor_run_dir"
    )
    target_run_dir = resolve_supplied_path(
        root, args.run_dir, "evolution_run_dir"
    )
    previous, _, previous_workflow_path = load_loop_state(
        root,
        previous_run_dir,
        verify_candidate_current=False,
    )
    if previous.get("status") not in {"complete", "failed"}:
        raise GateError("evolution_predecessor_not_terminal")
    if args.workflow is not None:
        workflow_path = resolve_supplied_path(
            root,
            args.workflow,
            "evolution_successor_workflow",
        )
    else:
        workflow_path = previous_workflow_path
        if (
            not workflow_path.is_file()
            or workflow_path.is_symlink()
            or sha256_file(workflow_path) != previous["workflow_sha256"]
        ):
            raise GateError("evolution_successor_workflow_required")
    successor_workflow = load_evolution_workflow(root, workflow_path)
    preflight_evolution_commands(root, target_run_dir, successor_workflow)
    successor_workflow_sha256 = sha256_file(workflow_path)
    if target_run_dir == previous_run_dir:
        raise GateError("evolution_predecessor_overwrite")
    if args.candidate_id == previous.get("candidate_id"):
        raise GateError("evolution_candidate_id_reused")
    if target_run_dir.exists():
        raise GateError("evolution_run_dir_exists")

    inherited_bindings = copy.deepcopy(previous.get("carry_over_blocker_bindings", []))
    release_state_path = args.state.expanduser().resolve()
    if release_state_path.is_file():
        release_state = read_json(release_state_path, "release_state")
        if release_state_has_open_blockers(release_state):
            previous_binding = completed_run_binding(root, previous_run_dir, previous)
            if release_state.get("completed_run") != previous_binding:
                raise GateError("evolution_release_predecessor_mismatch")
            inherited_by_id = {binding["id"]: binding for binding in inherited_bindings}
            for binding in bound_release_blockers(root, release_state):
                existing = inherited_by_id.get(binding["id"])
                if existing is not None and existing != binding:
                    raise GateError("evolution_carry_over_blocker_duplicate")
                if existing is None:
                    inherited_bindings.append(binding)
                    inherited_by_id[binding["id"]] = binding
    repaired_run = completed_run_binding(root, previous_run_dir, previous)
    source_predecessor = previous.get("predecessor_binding")
    resolved_bindings: list[dict] = []
    resolved_ids: set[str] = set()
    resolution_findings: set[tuple[str, str]] = set()
    if args.resolve_blocker and not isinstance(source_predecessor, dict):
        raise GateError("evolution_blocker_resolution_source_predecessor_mismatch")
    for receipt_path in args.resolve_blocker or []:
        binding, finding_key = derive_blocker_resolution_binding(
            root,
            receipt_path,
            repaired_run_dir=previous_run_dir,
            repaired_state=previous,
            repaired_run=repaired_run,
            source_predecessor=source_predecessor,
            open_blockers=inherited_bindings,
            target_run_id=args.run_id,
            target_candidate_id=args.candidate_id,
            target_workflow_sha256=successor_workflow_sha256,
        )
        if binding["id"] in resolved_ids or finding_key in resolution_findings:
            raise GateError("evolution_blocker_resolution_reused")
        resolved_ids.add(binding["id"])
        resolution_findings.add(finding_key)
        resolved_bindings.append(binding)

    blocker_bindings: list[dict] = [
        binding for binding in inherited_bindings if binding["id"] not in resolved_ids
    ]
    blocker_ids = {binding["id"] for binding in blocker_bindings}
    for blocker in args.carry_over_blocker or []:
        if blocker["id"] in blocker_ids:
            raise GateError("evolution_carry_over_blocker_duplicate")
        blocker_ids.add(blocker["id"])
        evidence = resolve_within(
            root, blocker["evidence"], "evolution_carry_over_evidence"
        )
        if not evidence.is_file() or evidence.is_symlink():
            raise GateError("evolution_carry_over_evidence_missing")
        blocker_bindings.append(
            {
                **blocker,
                "evidence_sha256": sha256_file(evidence),
                "status": "open",
            }
        )

    blockers = [
        {
            "id": binding["id"],
            "severity": binding["severity"],
            "evidence": binding["evidence"],
        }
        for binding in blocker_bindings
    ]

    lineage = {
        "predecessor_run_id": previous["run_id"],
        "predecessor_candidate_id": previous["candidate_id"],
        "predecessor_binding": completed_run_binding(
            root,
            previous_run_dir,
            previous,
        ),
        "carry_over_blockers": blockers,
        "carry_over_blocker_bindings": blocker_bindings,
        "resolved_blocker_bindings": resolved_bindings,
    }
    return create_evolution_run(
        root,
        workflow_path,
        target_run_dir,
        args.run_id,
        args.candidate_id,
        lineage=lineage,
    )


def command_next_iteration(args: argparse.Namespace) -> int:
    root = args.root.expanduser().resolve()
    state_path = args.state.expanduser().resolve()
    previous_run_dir = resolve_supplied_path(
        root,
        args.previous_run_dir,
        "evolution_predecessor_run_dir",
    )
    with release_state_lock(state_path, exclusive=False, create_parent=True):
        with evolution_run_lock(previous_run_dir, exclusive=False):
            return _command_next_iteration_unlocked(args)


def _command_complete_external_unlocked(args: argparse.Namespace) -> int:
    root = args.root.expanduser().resolve()
    run_dir = resolve_supplied_path(root, args.run_dir, "evolution_run_dir")
    state, workflow, _ = load_loop_state(root, run_dir)
    if state.get("status") != "awaiting_external_action":
        raise GateError("evolution_external_step_not_waiting")
    step = next((item for item in workflow["steps"] if item["id"] == args.step_id), None)
    if (
        step is None
        or step.get("kind") != "external"
        or state["steps"].get(args.step_id, {}).get("status") != "waiting"
        or state.get("current_step") != args.step_id
    ):
        raise GateError("evolution_external_step_not_waiting")
    source = resolve_supplied_path(root, args.receipt, "evolution_external_receipt")
    if not source.is_file() or source.is_symlink() or source.suffix.lower() != ".json":
        raise GateError("evolution_external_receipt_missing")
    receipt = read_json(source, "evolution_external_receipt")
    if schema_validation_errors(receipt, "evolution-external-receipt.schema.json"):
        raise GateError("evolution_external_receipt_schema_invalid")
    required = {"schema_version", "run_id", "step_id", "status", "summary", "evidence"}
    if (
        set(receipt) != required
        or receipt.get("schema_version") != "1.0"
        or receipt.get("run_id") != state["run_id"]
        or receipt.get("step_id") != args.step_id
        or receipt.get("status") != "completed"
        or not isinstance(receipt.get("summary"), str)
        or not receipt["summary"].strip()
        or not isinstance(receipt.get("evidence"), list)
        or not receipt["evidence"]
    ):
        raise GateError("evolution_external_receipt_invalid")
    for item in receipt["evidence"]:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise GateError("evolution_external_evidence_invalid")
        evidence_path = resolve_within(root, item["path"], "evolution_external_evidence")
        if (
            not evidence_path.is_file()
            or evidence_path.is_symlink()
            or not is_sha256(item.get("sha256"))
            or sha256_file(evidence_path) != item["sha256"]
        ):
            raise GateError("evolution_external_evidence_invalid")
    stored = {
        **receipt,
        "candidate_id": state["candidate_id"],
        "workflow_sha256": state["workflow_sha256"],
        "kind": "external",
        "source_sha256": sha256_file(source),
        "recorded_at": utc_now(),
    }
    stored_path = run_dir / "receipts" / f"{args.step_id}.external.json"
    if stored_path.exists():
        raise GateError("evolution_receipt_refuses_overwrite")
    write_json(stored_path, stored)
    projection = state["steps"][args.step_id]
    projection.update(
        {
            "status": "completed",
            "receipt_path": stored_path.relative_to(root).as_posix(),
            "receipt_sha256": sha256_file(stored_path),
        }
    )
    state["status"] = "running"
    state["current_step"] = None
    append_loop_event(
        run_dir,
        state,
        "external_action_completed",
        {
            "step_id": args.step_id,
            "receipt_sha256": projection["receipt_sha256"],
        },
    )
    save_loop_state(run_dir, state)
    print_loop_state(state)
    return 0


def command_complete_external(args: argparse.Namespace) -> int:
    root = args.root.expanduser().resolve()
    run_dir = resolve_supplied_path(root, args.run_dir, "evolution_run_dir")
    with evolution_run_lock(run_dir, exclusive=True):
        return _command_complete_external_unlocked(args)


def frozen_package_payloads(
    root: Path,
    run_dir: Path,
) -> tuple[dict[str, bytes], bytes, dict, dict]:
    """Authenticate and decode the package archive bound by a completed run.

    Historical verification deliberately uses the run's frozen workflow,
    scripts and input snapshots. It does not consult mutable package sources.
    """

    root = root.expanduser().resolve()
    run_dir = run_dir.expanduser().resolve()
    state, workflow, _ = load_loop_state(
        root,
        run_dir,
        verify_candidate_current=False,
    )
    if state.get("status") != "complete":
        raise GateError("frozen_package_run_not_complete")
    archive = run_dir / "breaking-identity-labels.zip"
    archive_reference = scoped_input_reference(
        root,
        archive,
        "frozen_package_archive",
    )
    bound_hash: str | None = None
    for step in reversed(workflow["steps"]):
        projection = state["steps"].get(step["id"], {})
        if step.get("kind") != "command" or projection.get("status") != "completed":
            continue
        receipt_relative = projection.get("receipt_path")
        if not isinstance(receipt_relative, str):
            continue
        receipt_path = resolve_within(root, receipt_relative, "frozen_package_receipt")
        receipt = read_json(receipt_path, "frozen_package_receipt")
        snapshot = receipt.get("input_snapshot")
        files = snapshot.get("files") if isinstance(snapshot, dict) else None
        if not isinstance(files, list):
            continue
        matches = [
            item
            for item in files
            if isinstance(item, dict) and item.get("path") == archive_reference
        ]
        if matches:
            candidate = matches[-1].get("sha256")
            if not is_sha256(candidate):
                raise GateError("frozen_package_archive_binding_invalid")
            bound_hash = candidate
            break
    if bound_hash is None:
        raise GateError("frozen_package_archive_binding_missing")
    if (
        not archive.is_file()
        or archive.is_symlink()
        or sha256_file(archive) != bound_hash
    ):
        raise GateError("frozen_package_archive_hash_mismatch")
    archive_bytes = archive.read_bytes()

    payloads: dict[str, bytes] = {}
    total_bytes = 0
    try:
        with zipfile.ZipFile(archive) as bundle:
            for member in bundle.infolist():
                pure = PurePosixPath(member.filename)
                if (
                    pure.is_absolute()
                    or ".." in pure.parts
                    or not pure.parts
                    or pure.parts[0] != "breaking-identity-labels"
                ):
                    raise GateError("frozen_package_archive_member_unsafe")
                if member.is_dir():
                    continue
                if len(pure.parts) < 2 or member.flag_bits & 0x1:
                    raise GateError("frozen_package_archive_member_unsafe")
                unix_mode = member.external_attr >> 16
                if unix_mode and stat.S_ISLNK(unix_mode):
                    raise GateError("frozen_package_archive_member_unsafe")
                if member.file_size > 5_000_000:
                    raise GateError("frozen_package_archive_size_limit")
                total_bytes += member.file_size
                if total_bytes > 20_000_000:
                    raise GateError("frozen_package_archive_size_limit")
                relative = PurePosixPath(*pure.parts[1:]).as_posix()
                if relative in payloads:
                    raise GateError("frozen_package_archive_duplicate_member")
                payload = bundle.read(member)
                if len(payload) != member.file_size:
                    raise GateError("frozen_package_archive_size_mismatch")
                payloads[relative] = payload
    except (OSError, zipfile.BadZipFile, RuntimeError) as error:
        raise GateError("frozen_package_archive_invalid") from error

    manifest_bytes = payloads.get("PACKAGE-MANIFEST.json")
    if manifest_bytes is None:
        raise GateError("frozen_package_manifest_missing")
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GateError("frozen_package_manifest_invalid") from error
    records = manifest.get("files") if isinstance(manifest, dict) else None
    if not isinstance(records, list):
        raise GateError("frozen_package_manifest_invalid")
    expected_payloads = {path for path in payloads if path != "PACKAGE-MANIFEST.json"}
    normalized: list[dict] = []
    declared: set[str] = set()
    for record in records:
        if (
            not isinstance(record, dict)
            or set(record) != {"path", "bytes", "sha256"}
            or not isinstance(record.get("path"), str)
            or not isinstance(record.get("bytes"), int)
            or not is_sha256(record.get("sha256"))
            or record["path"] in declared
        ):
            raise GateError("frozen_package_manifest_invalid")
        path = record["path"]
        payload = payloads.get(path)
        if (
            payload is None
            or len(payload) != record["bytes"]
            or sha256_bytes(payload) != record["sha256"]
        ):
            raise GateError("frozen_package_manifest_hash_mismatch")
        declared.add(path)
        normalized.append(
            {"path": path, "bytes": record["bytes"], "sha256": record["sha256"]}
        )
    if declared != expected_payloads:
        raise GateError("frozen_package_manifest_boundary_mismatch")
    calculated_tree = sha256_bytes(
        json.dumps(
            sorted(normalized, key=lambda item: item["path"]),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    if manifest.get("tree_sha256") != calculated_tree:
        raise GateError("frozen_package_manifest_tree_mismatch")
    if state.get("completed_artifacts", {}).get("package_tree_sha256") != calculated_tree:
        raise GateError("frozen_package_candidate_tree_mismatch")
    return payloads, archive_bytes, manifest, state


def export_completed_run_package(
    root: Path,
    run_dir: Path,
    out_dir: Path,
    out_zip: Path,
) -> dict:
    """Copy the authenticated package bytes from a completed run, once."""

    payloads, archive_bytes, manifest, state = frozen_package_payloads(root, run_dir)
    out_dir = out_dir.expanduser().resolve()
    out_zip = out_zip.expanduser().resolve()
    if out_dir.exists() or out_zip.exists():
        raise GateError("frozen_package_export_refuses_overwrite")
    if out_dir == out_zip or out_dir in out_zip.parents or out_zip in out_dir.parents:
        raise GateError("frozen_package_export_path_invalid")
    out_dir.parent.mkdir(parents=True, exist_ok=True)
    out_zip.parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(
        tempfile.mkdtemp(prefix=".breaking-identity-labels-export-", dir=out_dir.parent)
    )
    staged_dir = stage_root / "package"
    staged_dir.mkdir()
    with tempfile.NamedTemporaryFile(
        prefix=f".{out_zip.name}.", suffix=".tmp", dir=out_zip.parent, delete=False
    ) as handle:
        staged_zip = Path(handle.name)
        handle.write(archive_bytes)
        handle.flush()
        os.fsync(handle.fileno())
    published_dir = False
    try:
        for relative, payload in sorted(payloads.items()):
            target = staged_dir / PurePosixPath(relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(payload)
        staged_dir.replace(out_dir)
        published_dir = True
        staged_zip.replace(out_zip)
    except Exception:
        if published_dir and out_dir.exists() and not out_dir.is_symlink():
            shutil.rmtree(out_dir)
        raise
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
        if staged_zip.exists():
            staged_zip.unlink()
    return {
        "status": "exported_frozen_package",
        "run_id": state["run_id"],
        "candidate_id": state["candidate_id"],
        "package": str(out_dir),
        "archive": str(out_zip),
        "archive_sha256": sha256_bytes(archive_bytes),
        "manifest_sha256": sha256_bytes(payloads["PACKAGE-MANIFEST.json"]),
        "tree_sha256": manifest["tree_sha256"],
    }


def verify_exported_run_package(
    root: Path,
    run_dir: Path,
    out_dir: Path,
    out_zip: Path,
) -> dict:
    """Verify existing exported bytes against the authenticated run archive."""

    payloads, archive_bytes, manifest, state = frozen_package_payloads(root, run_dir)
    out_dir = out_dir.expanduser().resolve()
    out_zip = out_zip.expanduser().resolve()
    if (
        not out_dir.is_dir()
        or out_dir.is_symlink()
        or not out_zip.is_file()
        or out_zip.is_symlink()
        or out_zip.read_bytes() != archive_bytes
    ):
        raise GateError("frozen_package_export_mismatch")
    actual_files = {
        path.relative_to(out_dir).as_posix(): path
        for path in out_dir.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if set(actual_files) != set(payloads):
        raise GateError("frozen_package_export_mismatch")
    if any(actual_files[path].read_bytes() != payload for path, payload in payloads.items()):
        raise GateError("frozen_package_export_mismatch")
    return {
        "status": "verified_frozen_package_export",
        "run_id": state["run_id"],
        "candidate_id": state["candidate_id"],
        "package": str(out_dir),
        "archive": str(out_zip),
        "archive_sha256": sha256_bytes(archive_bytes),
        "manifest_sha256": sha256_bytes(payloads["PACKAGE-MANIFEST.json"]),
        "tree_sha256": manifest["tree_sha256"],
    }


def command_export_package(args: argparse.Namespace) -> int:
    root = args.root.expanduser().resolve()
    state_path = args.state.expanduser().resolve()
    manifest_path = args.test_manifest.expanduser().resolve()
    with release_state_lock(state_path, exclusive=False):
        state = read_json(state_path, "release_state")
        manifest = read_json(manifest_path, "test_manifest")
        gate = evaluate_gate(root, state, manifest, manifest_path)
        if not gate.get("valid"):
            raise GateError(*gate.get("errors", ["release_state_invalid"]))
        if not gate.get("release_eligible"):
            raise GateError("release_state_not_release_eligible")
        binding = state.get("completed_run")
        if not isinstance(binding, dict) or not isinstance(binding.get("run_dir"), str):
            raise GateError("release_completed_run_required")
        run_dir = resolve_within(root, binding["run_dir"], "release_completed_run")
        with evolution_run_lock(run_dir, exclusive=False):
            if args.verify_only:
                result = verify_exported_run_package(
                    root, run_dir, args.out_dir, args.out_archive
                )
            else:
                result = export_completed_run_package(
                    root, run_dir, args.out_dir, args.out_archive
                )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    common.add_argument(
        "--state", type=Path, default=DEFAULT_ROOT / "evals" / "release-gate.json"
    )
    common.add_argument(
        "--test-manifest",
        type=Path,
        default=DEFAULT_ROOT / "evals" / "test-generation-manifest.json",
    )
    top = argparse.ArgumentParser(
        description="Executable evolution loop and local release gate"
    )
    commands = top.add_subparsers(dest="command", required=True)

    check = commands.add_parser("check", parents=[common])
    mode = check.add_mutually_exclusive_group()
    mode.add_argument("--allow-blocked", action="store_true")
    mode.add_argument("--strict-release", action="store_true")
    check.set_defaults(handler=command_check)

    freeze = commands.add_parser("freeze", parents=[common])
    freeze.add_argument("--candidate-id", required=True)
    freeze.add_argument("--workflow", type=Path)
    freeze.add_argument("--completed-run-dir", type=Path)
    freeze.add_argument("--clock", default=utc_now())
    freeze.add_argument("--blocker", action="append", type=parse_blocker)
    freeze.set_defaults(handler=command_freeze)

    audit = commands.add_parser("record-audit", parents=[common])
    audit.add_argument("--receipt", help="relative path to one structured audit receipt")
    audit.add_argument("--audit-id", help=argparse.SUPPRESS)
    audit.add_argument("--status", help=argparse.SUPPRESS)
    audit.add_argument("--blocker-count", help=argparse.SUPPRESS)
    audit.add_argument("--severity", help=argparse.SUPPRESS)
    audit.add_argument("--evidence", action="append", default=[], help=argparse.SUPPRESS)
    audit.set_defaults(handler=command_record_audit)

    sync = commands.add_parser("sync-tests", parents=[common])
    sync.set_defaults(handler=command_sync_tests)

    migrate = commands.add_parser("migrate-test", parents=[common])
    migrate.add_argument("--receipt", required=True, type=Path)
    migrate.add_argument(
        "--permit-pending-receipt",
        action="append",
        type=Path,
        help=argparse.SUPPRESS,
    )
    migrate.set_defaults(handler=command_migrate_test)

    run = commands.add_parser("run", parents=[common])
    run.add_argument("--workflow", required=True, type=Path)
    run.add_argument("--run-dir", required=True, type=Path)
    run.add_argument("--run-id", required=True)
    run.add_argument("--candidate-id", required=True)
    run.set_defaults(handler=command_run)

    resume = commands.add_parser("resume", parents=[common])
    resume.add_argument("--run-dir", required=True, type=Path)
    resume.set_defaults(handler=command_resume)

    status = commands.add_parser("status", parents=[common])
    status.add_argument("--run-dir", required=True, type=Path)
    status.set_defaults(handler=command_loop_status)

    next_iteration = commands.add_parser("next-iteration", parents=[common])
    next_iteration.add_argument("--previous-run-dir", required=True, type=Path)
    next_iteration.add_argument("--workflow", type=Path)
    next_iteration.add_argument("--run-dir", required=True, type=Path)
    next_iteration.add_argument("--run-id", required=True)
    next_iteration.add_argument("--candidate-id", required=True)
    next_iteration.add_argument(
        "--carry-over-blocker",
        action="append",
        type=parse_blocker,
    )
    next_iteration.add_argument(
        "--resolve-blocker",
        action="append",
        type=Path,
    )
    next_iteration.set_defaults(handler=command_next_iteration)

    external = commands.add_parser("complete-external", parents=[common])
    external.add_argument("--run-dir", required=True, type=Path)
    external.add_argument("--step-id", required=True)
    external.add_argument("--receipt", required=True, type=Path)
    external.set_defaults(handler=command_complete_external)

    export = commands.add_parser("export-package", parents=[common])
    export.add_argument("--out-dir", required=True, type=Path)
    export.add_argument("--out-archive", required=True, type=Path)
    export.add_argument("--verify-only", action="store_true")
    export.set_defaults(handler=command_export_package)
    return top


def main() -> int:
    args = parser().parse_args()
    try:
        return args.handler(args)
    except GateError as error:
        print(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "valid": False,
                    "effective_decision": "invalid_run",
                    "release_eligible": False,
                    "errors": sorted(set(error.codes)),
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
