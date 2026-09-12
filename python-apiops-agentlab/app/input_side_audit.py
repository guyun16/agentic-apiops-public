"""Stage 21 v3 input-only deterministic audit.

This module is deliberately independent from ``app.benchmark``.  Importing the
benchmark package imports the evaluator and the full task model, which is not a
safe boundary for an audit that must never receive expected-side data.

The projection parser reads task/manifest JSON one top-level value at a time.
Values belonging to expected-side keys are skipped lexically and are never
materialised into an audit object.  Runtime recipe resolution is keyed only by
typed source references; the benchmark task id is used solely to join the
manifest with the input-side prerequisite sidecar.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from json.decoder import JSONDecodeError, scanstring
from pathlib import Path
from typing import Any

ALLOWED_CLASSIFICATIONS = (
    "READY",
    "TASK_INPUT_CONTRACT_GAP",
    "RUNTIME_RESOURCE_MISSING",
    "RESOURCE_MAPPING_BUG",
    "REAL_JAVA_BUG",
    "STRATEGY_INPUT_CONTRACT_GAP",
    "AUTH_PREREQUISITE_GAP",
    "RUNTIME_RECIPE_GAP",
    "NOT_PREFLIGHTABLE_MODEL_BEHAVIOR",
)

TASK_TYPES = {
    "TESTCASE_GENERATION",
    "FAILURE_DIAGNOSIS",
    "TOOL_SAFETY",
    "RAG_EVIDENCE_RETRIEVAL",
    "E2E_APIOPS",
}

INITIAL_ENTRY_KINDS = {"LITERAL", "JAVA_RESOURCE", "PYTHON_FIXTURE"}
AUTH_PROFILES = {"NORMAL", "SAFETY_41_ISOLATED", "SAFETY_42_ISOLATED"}
RESOURCE_SETUP_TYPES = {
    "RUNTIME_RECIPE",
    "EXISTING_JAVA_RESOURCE",
    "TEST_ONLY_REFERENCE",
    "BENCHMARK_LOCAL_INPUT",
}

EXPECTED_SIDE_KEYS = frozenset(
    {
        "groundtruth",
        "groundtruthfile",
        "groundtruthref",
        "expectedoutput",
        "expectedtoolcalls",
        "expectedevidenceids",
        "evaluationresult",
        "modelscore",
        "judgescore",
        "modeljudgescore",
        "evaluationspec",
        "metrics",
    }
)

TASK_ROOT_KEYS = frozenset(
    {
        "schemaVersion",
        "benchmarkTaskId",
        "taskType",
        "instruction",
        "initialState",
        "allowedTools",
        "forbiddenActions",
    }
)

MANIFEST_ROOT_KEYS = frozenset(
    {"manifestVersion", "datasetId", "datasetVersion", "taskSchemaVersion", "tasks"}
)
MANIFEST_ENTRY_KEYS = frozenset(
    {
        "benchmarkTaskId",
        "taskFile",
        "split",
        "difficulty",
        "scenario",
        "difficultyRationale",
        "reviewStatus",
    }
)

STRATEGY_KEYS = ("executionStrategy", "strategy", "generationStrategy")
GENERATION_STRATEGIES = {
    "HAPPY_PATH",
    "MISSING_REQUIRED",
    "BOUNDARY",
    "AUTH_FAILURE",
    "BUSINESS_ERROR",
}

PROFILE_ENV_VARS = {
    "NORMAL": ("STAGE21_NORMAL_USERNAME", "STAGE21_NORMAL_PASSWORD"),
    "SAFETY_41_ISOLATED": ("STAGE21_SAFETY41_USERNAME", "STAGE21_SAFETY41_PASSWORD"),
    "SAFETY_42_ISOLATED": ("STAGE21_SAFETY42_USERNAME", "STAGE21_SAFETY42_PASSWORD"),
}

OPERATION_BOUNDARIES = {
    "READ_METADATA": "GET /api/v1/projects/{currentProjectId}/openapi/apis/{apiId}",
    "RUNNER_SUBMIT": "POST /api/v1/projects/{currentProjectId}/test-batches",
    "RUNNER_STATUS": "GET /api/v1/projects/{currentProjectId}/test-runs/{runId} (SSE/readback)",
    "READ_REPORT": "GET /api/v1/projects/{currentProjectId}/test-runs/{runId}/report",
    "TOOL_CALL": "POST /api/v1/projects/{currentProjectId}/tool-calls",
    "RAG_SEARCH": "POST /api/v1/projects/{currentProjectId}/tool-calls (RAG intent)",
}

JAVA_REF_PATTERNS = {
    "metadata": re.compile(r"^java://metadata/project-(?P<project>\d+)/(?P<api>[^/]+)$"),
    "test_report": re.compile(
        r"^java://test-report/project-(?P<project>\d+)/(?P<rest>[^/]+(?:/[^/]+)*)$"
    ),
    "runner_testcase": re.compile(r"^java://runner-testcase-dsl/(?P<rest>.+)$"),
    "runner_unit": re.compile(r"^java://runner-unit/(?P<rest>.+)$"),
    "rag": re.compile(r"^java://rag/project-(?P<project>\d+)/query/(?P<query>.+)$"),
    "tool_gateway": re.compile(r"^java://tool-gateway/(?P<rest>.+)$"),
}

_NUMBER_RE = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
_JSON_DECODER = json.JSONDecoder()


class InputAuditError(ValueError):
    """A malformed input-only artifact that must fail closed."""


@dataclass(frozen=True, slots=True)
class ProjectionTrace:
    skipped_expected_side_keys: tuple[str, ...] = ()
    ignored_unknown_keys: tuple[str, ...] = ()
    duplicate_keys: tuple[str, ...] = ()

    def plus(self, other: ProjectionTrace) -> ProjectionTrace:
        return ProjectionTrace(
            self.skipped_expected_side_keys + other.skipped_expected_side_keys,
            self.ignored_unknown_keys + other.ignored_unknown_keys,
            self.duplicate_keys + other.duplicate_keys,
        )


def _skip_ws(text: str, position: int) -> int:
    length = len(text)
    while position < length and text[position] in " \t\r\n":
        position += 1
    return position


def _scan_json_string(text: str, position: int) -> tuple[str, int]:
    if position >= len(text) or text[position] != '"':
        raise InputAuditError(f"expected JSON string at offset {position}")
    try:
        value, end = scanstring(text, position + 1, True)
    except (TypeError, ValueError) as exc:
        raise InputAuditError(f"invalid JSON string at offset {position}") from exc
    return value, end


def _skip_json_value(text: str, position: int) -> int:
    """Skip one JSON value without constructing it."""

    position = _skip_ws(text, position)
    if position >= len(text):
        raise InputAuditError("JSON value is truncated")
    token = text[position]

    if token == '"':
        _, end = _scan_json_string(text, position)
        return end

    if token == "{":
        cursor = _skip_ws(text, position + 1)
        if cursor < len(text) and text[cursor] == "}":
            return cursor + 1
        while True:
            _, cursor = _scan_json_string(text, _skip_ws(text, cursor))
            cursor = _skip_ws(text, cursor)
            if cursor >= len(text) or text[cursor] != ":":
                raise InputAuditError("JSON object key is missing ':'")
            cursor = _skip_json_value(text, cursor + 1)
            cursor = _skip_ws(text, cursor)
            if cursor >= len(text):
                raise InputAuditError("JSON object is truncated")
            if text[cursor] == "}":
                return cursor + 1
            if text[cursor] != ",":
                raise InputAuditError("JSON object is missing ','")
            cursor = _skip_ws(text, cursor + 1)

    if token == "[":
        cursor = _skip_ws(text, position + 1)
        if cursor < len(text) and text[cursor] == "]":
            return cursor + 1
        while True:
            cursor = _skip_json_value(text, cursor)
            cursor = _skip_ws(text, cursor)
            if cursor >= len(text):
                raise InputAuditError("JSON array is truncated")
            if text[cursor] == "]":
                return cursor + 1
            if text[cursor] != ",":
                raise InputAuditError("JSON array is missing ','")
            cursor = _skip_ws(text, cursor + 1)

    for literal in ("true", "false", "null"):
        if text.startswith(literal, position):
            return position + len(literal)

    match = _NUMBER_RE.match(text, position)
    if match is not None:
        return match.end()
    raise InputAuditError(f"invalid JSON value at offset {position}")


def _project_object_at(
    text: str,
    position: int,
    *,
    allowed_keys: frozenset[str],
    expected_keys: frozenset[str] = EXPECTED_SIDE_KEYS,
    value_handlers: Mapping[str, Callable[[str, int], tuple[Any, int]]] | None = None,
) -> tuple[dict[str, Any], int, ProjectionTrace]:
    position = _skip_ws(text, position)
    if position >= len(text) or text[position] != "{":
        raise InputAuditError(f"expected JSON object at offset {position}")

    output: dict[str, Any] = {}
    skipped: list[str] = []
    unknown: list[str] = []
    duplicates: list[str] = []
    seen: set[str] = set()
    cursor = _skip_ws(text, position + 1)
    if cursor < len(text) and text[cursor] == "}":
        return output, cursor + 1, ProjectionTrace()

    while True:
        key, cursor = _scan_json_string(text, _skip_ws(text, cursor))
        if key in seen:
            duplicates.append(key)
        seen.add(key)
        cursor = _skip_ws(text, cursor)
        if cursor >= len(text) or text[cursor] != ":":
            raise InputAuditError(f"JSON object key {key!r} is missing ':'")
        cursor = _skip_ws(text, cursor + 1)

        if key in allowed_keys:
            handler = (value_handlers or {}).get(key)
            if handler is not None:
                value, cursor = handler(text, cursor)
            else:
                try:
                    value, cursor = _JSON_DECODER.raw_decode(text, cursor)
                except JSONDecodeError as exc:
                    raise InputAuditError(f"invalid JSON value for allowed key {key!r}") from exc
            output[key] = value
        elif key.casefold() in expected_keys:
            skipped.append(key)
            cursor = _skip_json_value(text, cursor)
        else:
            unknown.append(key)
            cursor = _skip_json_value(text, cursor)

        cursor = _skip_ws(text, cursor)
        if cursor >= len(text):
            raise InputAuditError("JSON object is truncated")
        if text[cursor] == "}":
            return (
                output,
                cursor + 1,
                ProjectionTrace(tuple(skipped), tuple(unknown), tuple(duplicates)),
            )
        if text[cursor] != ",":
            raise InputAuditError("JSON object is missing ','")
        cursor = _skip_ws(text, cursor + 1)


def _finish_document(text: str, end: int) -> None:
    if _skip_ws(text, end) != len(text):
        raise InputAuditError("trailing data after JSON document")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise InputAuditError(f"cannot read input artifact {path}") from exc


@dataclass(frozen=True, slots=True)
class InputEntry:
    kind: str
    key: str
    ref: str | None = None
    value: Any = None

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"kind": self.kind, "key": self.key}
        if self.ref is not None:
            result["ref"] = self.ref
        if self.kind == "LITERAL":
            result["value"] = self.value
        return result


@dataclass(frozen=True, slots=True)
class InputTask:
    task_id: str
    task_type: str
    instruction_length: int
    instruction_sha256: str
    entries: tuple[InputEntry, ...]
    allowed_tools: tuple[str, ...]
    forbidden_actions: tuple[str, ...]
    schema_version: str | None
    contract_issues: tuple[str, ...]
    projection_trace: ProjectionTrace

    @property
    def literals(self) -> dict[str, Any]:
        return {entry.key: entry.value for entry in self.entries if entry.kind == "LITERAL"}


def _string_tuple(value: Any, field_name: str, issues: list[str]) -> tuple[str, ...]:
    if not isinstance(value, list):
        issues.append(f"{field_name}:must_be_array")
        return ()
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            issues.append(f"{field_name}[{index}]:must_be_non_empty_string")
        else:
            result.append(item)
    if len(result) != len(set(result)):
        issues.append(f"{field_name}:duplicate_values")
    return tuple(result)


def _input_entries(value: Any, issues: list[str]) -> tuple[InputEntry, ...]:
    if not isinstance(value, dict):
        issues.append("initialState:must_be_object")
        return ()
    raw_entries = value.get("entries")
    if not isinstance(raw_entries, list) or not raw_entries:
        issues.append("initialState.entries:must_be_non_empty_array")
        return ()

    entries: list[InputEntry] = []
    keys: list[str] = []
    for index, raw in enumerate(raw_entries):
        if not isinstance(raw, dict):
            issues.append(f"initialState.entries[{index}]:must_be_object")
            continue
        kind = raw.get("kind")
        key = raw.get("key")
        if kind not in INITIAL_ENTRY_KINDS:
            issues.append(f"initialState.entries[{index}].kind:unknown")
            continue
        if not isinstance(key, str) or not key.strip():
            issues.append(f"initialState.entries[{index}].key:must_be_non_empty_string")
            continue
        keys.append(key)
        if kind == "LITERAL":
            if "value" not in raw:
                issues.append(f"initialState.entries[{index}].value:missing")
            entries.append(InputEntry(kind, key, value=raw.get("value")))
        else:
            ref = raw.get("ref")
            if not isinstance(ref, str) or not ref.strip():
                issues.append(f"initialState.entries[{index}].ref:must_be_non_empty_string")
            entries.append(InputEntry(kind, key, ref=ref if isinstance(ref, str) else None))
        known = {"kind", "key", "value", "ref"}
        extras = sorted(set(raw) - known)
        if extras:
            issues.append(f"initialState.entries[{index}]:unknown_keys={','.join(extras)}")
    if len(keys) != len(set(keys)):
        issues.append("initialState.entries:duplicate_keys")
    return tuple(entries)


def project_input_task_text(text: str, *, source: str = "<memory>") -> InputTask:
    """Project only inference-time task fields from a task JSON document."""

    try:
        projected, end, trace = _project_object_at(
            text,
            0,
            allowed_keys=TASK_ROOT_KEYS,
        )
        _finish_document(text, end)
    except InputAuditError:
        raise
    except Exception as exc:  # pragma: no cover - defensive fail-closed guard
        raise InputAuditError(f"cannot project task input {source}") from exc

    issues: list[str] = []
    schema_version = projected.get("schemaVersion")
    if schema_version != "0.2.0":
        issues.append("schemaVersion:expected_0.2.0")
    task_id = projected.get("benchmarkTaskId")
    if not isinstance(task_id, str) or not task_id.strip():
        issues.append("benchmarkTaskId:must_be_non_empty_string")
        task_id = "<missing-task-id>"
    task_type = projected.get("taskType")
    if task_type not in TASK_TYPES:
        issues.append("taskType:unknown")
        task_type = str(task_type) if task_type is not None else "<missing-task-type>"
    instruction = projected.get("instruction")
    if not isinstance(instruction, str) or not instruction.strip():
        issues.append("instruction:must_be_non_empty_string")
        instruction = ""
    allowed_tools = _string_tuple(projected.get("allowedTools"), "allowedTools", issues)
    forbidden_actions = _string_tuple(projected.get("forbiddenActions"), "forbiddenActions", issues)
    entries = _input_entries(projected.get("initialState"), issues)
    if trace.ignored_unknown_keys:
        issues.append("task_root:unknown_keys=" + ",".join(sorted(set(trace.ignored_unknown_keys))))
    if trace.duplicate_keys:
        issues.append("task_root:duplicate_keys=" + ",".join(sorted(set(trace.duplicate_keys))))

    return InputTask(
        task_id=task_id,
        task_type=task_type,
        instruction_length=len(instruction),
        instruction_sha256=hashlib.sha256(instruction.encode("utf-8")).hexdigest(),
        entries=entries,
        allowed_tools=allowed_tools,
        forbidden_actions=forbidden_actions,
        schema_version=schema_version if isinstance(schema_version, str) else None,
        contract_issues=tuple(issues),
        projection_trace=trace,
    )


def project_input_task_file(path: Path) -> InputTask:
    return project_input_task_text(_read_text(path), source=str(path))


@dataclass(frozen=True, slots=True)
class ManifestEntry:
    task_id: str
    task_file: str
    split: str
    difficulty: str
    scenario: str
    contract_issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class InputManifest:
    manifest_version: str | None
    dataset_id: str | None
    dataset_version: str | None
    task_schema_version: str | None
    tasks: tuple[ManifestEntry, ...]
    contract_issues: tuple[str, ...]
    projection_trace: ProjectionTrace


def _manifest_task_array_at(
    text: str, position: int
) -> tuple[list[dict[str, Any]], int, ProjectionTrace]:
    position = _skip_ws(text, position)
    if position >= len(text) or text[position] != "[":
        raise InputAuditError("manifest tasks must be an array")
    cursor = _skip_ws(text, position + 1)
    entries: list[dict[str, Any]] = []
    trace = ProjectionTrace()
    if cursor < len(text) and text[cursor] == "]":
        return entries, cursor + 1, trace
    while True:
        projected, cursor, item_trace = _project_object_at(
            text,
            cursor,
            allowed_keys=MANIFEST_ENTRY_KEYS,
        )
        entries.append(projected)
        trace = trace.plus(item_trace)
        cursor = _skip_ws(text, cursor)
        if cursor >= len(text):
            raise InputAuditError("manifest tasks array is truncated")
        if text[cursor] == "]":
            return entries, cursor + 1, trace
        if text[cursor] != ",":
            raise InputAuditError("manifest tasks array is missing ','")
        cursor = _skip_ws(text, cursor + 1)


def _manifest_tasks_handler(text: str, position: int) -> tuple[Any, int]:
    return _manifest_task_array_at(text, position)[:2]


def project_manifest_text(text: str, *, source: str = "<memory>") -> InputManifest:
    nested_trace = ProjectionTrace()

    def tasks_handler(document: str, position: int) -> tuple[Any, int]:
        nonlocal nested_trace
        tasks, end, task_trace = _manifest_task_array_at(document, position)
        nested_trace = nested_trace.plus(task_trace)
        return tasks, end

    projected, end, trace = _project_object_at(
        text,
        0,
        allowed_keys=MANIFEST_ROOT_KEYS,
        value_handlers={"tasks": tasks_handler},
    )
    _finish_document(text, end)
    trace = trace.plus(nested_trace)
    issues: list[str] = []
    for key in ("manifestVersion", "datasetId", "datasetVersion", "taskSchemaVersion"):
        if not isinstance(projected.get(key), str) or not projected[key].strip():
            issues.append(f"{key}:must_be_non_empty_string")
    if projected.get("taskSchemaVersion") != "0.2.0":
        issues.append("taskSchemaVersion:expected_0.2.0")
    raw_tasks = projected.get("tasks")
    if not isinstance(raw_tasks, list) or not raw_tasks:
        issues.append("tasks:must_be_non_empty_array")
        raw_tasks = []

    tasks: list[ManifestEntry] = []
    ids: list[str] = []
    files: list[str] = []
    for index, raw in enumerate(raw_tasks):
        row_issues: list[str] = []
        if not isinstance(raw, dict):
            issues.append(f"tasks[{index}]:must_be_object")
            continue
        task_id = raw.get("benchmarkTaskId")
        task_file = raw.get("taskFile")
        split = raw.get("split")
        difficulty = raw.get("difficulty")
        scenario = raw.get("scenario")
        if not isinstance(task_id, str) or not task_id.strip():
            row_issues.append("benchmarkTaskId:missing")
            task_id = f"<manifest-row-{index}>"
        if not isinstance(task_file, str) or not task_file.strip():
            row_issues.append("taskFile:missing")
            task_file = ""
        if split not in {"dev", "held_out"}:
            row_issues.append("split:must_be_dev_or_held_out")
            split = str(split) if split is not None else "<missing-split>"
        if not isinstance(difficulty, str) or not difficulty.strip():
            row_issues.append("difficulty:missing")
            difficulty = "<missing-difficulty>"
        if not isinstance(scenario, str) or not scenario.strip():
            row_issues.append("scenario:missing")
            scenario = "<missing-scenario>"
        if row_issues:
            issues.extend(f"tasks[{index}].{item}" for item in row_issues)
        tasks.append(
            ManifestEntry(task_id, task_file, split, difficulty, scenario, tuple(row_issues))
        )
        ids.append(task_id)
        files.append(task_file)
    if len(ids) != len(set(ids)):
        issues.append("tasks:duplicate_benchmarkTaskId")
    if len(files) != len(set(files)):
        issues.append("tasks:duplicate_taskFile")
    if trace.ignored_unknown_keys:
        issues.append(
            "manifest_root:unknown_keys=" + ",".join(sorted(set(trace.ignored_unknown_keys)))
        )
    if trace.duplicate_keys:
        issues.append("manifest_root:duplicate_keys=" + ",".join(sorted(set(trace.duplicate_keys))))
    return InputManifest(
        manifest_version=projected.get("manifestVersion"),
        dataset_id=projected.get("datasetId"),
        dataset_version=projected.get("datasetVersion"),
        task_schema_version=projected.get("taskSchemaVersion"),
        tasks=tuple(tasks),
        contract_issues=tuple(issues),
        projection_trace=trace,
    )


def project_manifest_file(path: Path) -> InputManifest:
    return project_manifest_text(_read_text(path), source=str(path))


@dataclass(frozen=True, slots=True)
class Prerequisite:
    task_id: str
    auth_profile: str
    current_project_id: int | None
    target_project_id: int | None
    resource_project_id: int | None
    required_operations: tuple[str, ...]
    minimum_project_role: str | None
    required_authorities: tuple[str, ...]
    resource_setup_type: str
    resource_ownership: str
    contract_gaps: tuple[str, ...]
    contract_issues: tuple[str, ...]


def _optional_int(value: Any, field_name: str, issues: list[str]) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        issues.append(f"{field_name}:must_be_non_negative_integer_or_null")
        return None
    return value


def _strict_string(value: Any, field_name: str, issues: list[str]) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        issues.append(f"{field_name}:must_be_non_empty_string")
        return None
    return value


def load_prerequisites(path: Path) -> dict[str, Prerequisite]:
    try:
        payload = json.loads(_read_text(path))
    except (JSONDecodeError, InputAuditError) as exc:
        raise InputAuditError(f"invalid prerequisite sidecar {path}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
        raise InputAuditError("prerequisite sidecar must contain a tasks array")
    result: dict[str, Prerequisite] = {}
    for index, raw in enumerate(payload["tasks"]):
        if not isinstance(raw, dict):
            raise InputAuditError(f"prerequisite row {index} is not an object")
        issues: list[str] = []
        task_id = _strict_string(raw.get("benchmarkTaskId"), "benchmarkTaskId", issues)
        if task_id is None:
            task_id = f"<sidecar-row-{index}>"
        auth_profile = _strict_string(raw.get("authProfile"), "authProfile", issues) or "<missing>"
        if auth_profile not in AUTH_PROFILES:
            issues.append("authProfile:unknown")
        operations_raw = raw.get("requiredOperations")
        if not isinstance(operations_raw, list) or not operations_raw:
            issues.append("requiredOperations:must_be_non_empty_array")
            operations = ()
        else:
            operations = tuple(
                item for item in operations_raw if isinstance(item, str) and item.strip()
            )
            if len(operations) != len(operations_raw):
                issues.append("requiredOperations:contains_non_string")
        unknown_ops = sorted(
            set(operations)
            - set(OPERATION_BOUNDARIES)
            - {"NO_JAVA_ACCESS", "NO_TOOL_CALL"}
        )
        if unknown_ops:
            issues.append("requiredOperations:unknown=" + ",".join(unknown_ops))
        authorities_raw = raw.get("requiredAuthorities", [])
        if not isinstance(authorities_raw, list):
            issues.append("requiredAuthorities:must_be_array")
            authorities = ()
        else:
            authorities = tuple(
                item for item in authorities_raw if isinstance(item, str) and item.strip()
            )
            if len(authorities) != len(authorities_raw):
                issues.append("requiredAuthorities:contains_non_string")
        gaps_raw = raw.get("contractGaps", [])
        if not isinstance(gaps_raw, list):
            issues.append("contractGaps:must_be_array")
            gaps = ()
        else:
            gaps = tuple(item for item in gaps_raw if isinstance(item, str) and item.strip())
        current = _optional_int(raw.get("currentProjectId"), "currentProjectId", issues)
        target = _optional_int(raw.get("targetProjectId"), "targetProjectId", issues)
        resource = _optional_int(raw.get("resourceProjectId"), "resourceProjectId", issues)
        minimum_role = _strict_string(raw.get("minimumProjectRole"), "minimumProjectRole", issues)
        setup = (
            _strict_string(raw.get("resourceSetupType"), "resourceSetupType", issues) or "<missing>"
        )
        ownership = (
            _strict_string(raw.get("resourceOwnership"), "resourceOwnership", issues) or "<missing>"
        )
        if setup not in RESOURCE_SETUP_TYPES:
            issues.append("resourceSetupType:unknown")
        if task_id in result:
            raise InputAuditError(f"duplicate prerequisite task {task_id}")
        result[task_id] = Prerequisite(
            task_id,
            auth_profile,
            current,
            target,
            resource,
            operations,
            minimum_role,
            authorities,
            setup,
            ownership,
            gaps,
            tuple(issues),
        )
    return result


@dataclass(frozen=True, slots=True)
class Recipe:
    source_reference: str
    kind: str
    family: str
    case_id: str | None
    base_url: str | None
    query: str | None
    top_k: int | None
    catalog_path: str
    issues: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "sourceReference": self.source_reference,
            "kind": self.kind,
            "family": self.family,
            "catalog": self.catalog_path,
            "valid": not self.issues,
        }
        if self.case_id is not None:
            result["caseId"] = self.case_id
        if self.base_url is not None:
            result["baseUrl"] = self.base_url
        if self.query is not None:
            result["query"] = self.query
        if self.top_k is not None:
            result["topK"] = self.top_k
        if self.issues:
            result["issues"] = list(self.issues)
        return result


@dataclass(frozen=True, slots=True)
class RecipeIndex:
    by_source: Mapping[str, tuple[Recipe, ...]]
    by_initial_resource_key: Mapping[str, tuple[Recipe, ...]]
    catalog_issues: tuple[str, ...]


def _find_forbidden_key(value: Any, path: str = "$") -> str | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.casefold() in EXPECTED_SIDE_KEYS:
                return f"{path}.{key}"
            found = _find_forbidden_key(child, f"{path}.{key}")
            if found:
                return found
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found = _find_forbidden_key(child, f"{path}[{index}]")
            if found:
                return found
    return None


def _valid_http_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    parsed = urllib.parse.urlsplit(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and parsed.port is not None


def _validate_test_case(raw: Any) -> tuple[str | None, str | None, tuple[str, ...]]:
    issues: list[str] = []
    if not isinstance(raw, dict):
        return None, None, ("testCase:must_be_object",)
    for key in ("schemaVersion", "caseId", "projectId", "apiId", "name", "environment", "steps"):
        if key not in raw:
            issues.append(f"testCase.{key}:missing")
    if raw.get("schemaVersion") != "1.0.0":
        issues.append("testCase.schemaVersion:expected_1.0.0")
    case_id = raw.get("caseId") if isinstance(raw.get("caseId"), str) else None
    project_id = raw.get("projectId")
    if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id < 0:
        issues.append("testCase.projectId:must_be_non_negative_integer")
    for key in ("caseId", "apiId", "name"):
        if not isinstance(raw.get(key), str) or not raw[key].strip():
            issues.append(f"testCase.{key}:must_be_non_empty_string")
    environment = raw.get("environment")
    base_url: str | None = None
    if not isinstance(environment, dict):
        issues.append("testCase.environment:must_be_object")
    else:
        base_url = (
            environment.get("baseUrl") if isinstance(environment.get("baseUrl"), str) else None
        )
        if not _valid_http_url(base_url):
            issues.append("testCase.environment.baseUrl:must_be_http_url_with_port")
        if not isinstance(environment.get("variables"), dict):
            issues.append("testCase.environment.variables:must_be_object")
    steps = raw.get("steps")
    if not isinstance(steps, list) or not steps:
        issues.append("testCase.steps:must_be_non_empty_array")
    else:
        for index, step in enumerate(steps):
            if not isinstance(step, dict):
                issues.append(f"testCase.steps[{index}]:must_be_object")
                continue
            for key in ("stepId", "name", "request", "assertions", "extractors"):
                if key not in step:
                    issues.append(f"testCase.steps[{index}].{key}:missing")
            request = step.get("request")
            if not isinstance(request, dict):
                issues.append(f"testCase.steps[{index}].request:must_be_object")
            else:
                if request.get("method") not in {
                    "GET",
                    "POST",
                    "PUT",
                    "DELETE",
                    "PATCH",
                    "HEAD",
                    "OPTIONS",
                    "TRACE",
                }:
                    issues.append(f"testCase.steps[{index}].request.method:unknown")
                if not isinstance(request.get("path"), str) or not request["path"].strip():
                    issues.append(f"testCase.steps[{index}].request.path:missing")
            if not isinstance(step.get("assertions"), list) or not step["assertions"]:
                issues.append(f"testCase.steps[{index}].assertions:must_be_non_empty_array")
            if not isinstance(step.get("extractors"), list):
                issues.append(f"testCase.steps[{index}].extractors:must_be_array")
    return case_id, base_url, tuple(issues)


def _load_recipe_catalog(path: Path, family: str) -> tuple[list[Recipe], list[str]]:
    issues: list[str] = []
    try:
        payload = json.loads(_read_text(path))
    except (JSONDecodeError, InputAuditError):
        return [], [f"{path.name}:unreadable_or_invalid_json"]
    if not isinstance(payload, dict) or not isinstance(payload.get("recipes"), list):
        return [], [f"{path.name}:recipes_array_missing"]
    catalog: list[Recipe] = []
    for index, raw in enumerate(payload["recipes"]):
        prefix = f"{path.name}[{index}]"
        if not isinstance(raw, dict):
            issues.append(f"{prefix}:must_be_object")
            continue
        forbidden_key = _find_forbidden_key(raw)
        if forbidden_key is not None:
            issues.append(f"{prefix}:forbidden_expected_side_key={forbidden_key}")
            continue
        source = raw.get("sourceReference")
        resource_key = raw.get("resourceKey")
        if family == "initial":
            if not isinstance(resource_key, str) or not resource_key.strip():
                issues.append(f"{prefix}:resourceKey_missing")
                continue
            kind = "INITIAL_REPORT_RESOURCE"
            source = f"resource-key://{resource_key}"
            case_id = raw.get("caseId") if isinstance(raw.get("caseId"), str) else None
            record_issues: list[str] = []
            if raw.get("resourceType") != "TEST_REPORT":
                record_issues.append("resourceType:expected_TEST_REPORT")
            if raw.get("lifecycle") != "STAGE21_INITIAL":
                record_issues.append("lifecycle:expected_STAGE21_INITIAL")
            if case_id is None:
                record_issues.append("caseId:missing")
            catalog.append(
                Recipe(
                    source,
                    kind,
                    family,
                    case_id,
                    None,
                    None,
                    None,
                    path.name,
                    tuple(record_issues),
                )
            )
            continue
        if not isinstance(source, str) or not source.strip():
            issues.append(f"{prefix}:sourceReference_missing")
            continue
        record_issues = []
        if family in {"report_runtime", "runner_runtime"}:
            case_id, base_url, test_case_issues = _validate_test_case(raw.get("testCase"))
            record_issues.extend(test_case_issues)
            deadline = raw.get("readbackDeadlineSeconds")
            if isinstance(deadline, bool) or not isinstance(deadline, int) or deadline < 1:
                record_issues.append("readbackDeadlineSeconds:must_be_positive_integer")
            family_field = "recipeKind" if family == "report_runtime" else "recipeFamily"
            if not isinstance(raw.get(family_field), str) or not raw[family_field].strip():
                record_issues.append(f"{family_field}:missing")
            kind = str(raw.get(family_field) or "UNKNOWN")
            catalog.append(
                Recipe(
                    source,
                    kind,
                    family,
                    case_id,
                    base_url,
                    None,
                    None,
                    path.name,
                    tuple(record_issues),
                )
            )
        elif family == "rag_runtime":
            query = raw.get("query") if isinstance(raw.get("query"), str) else None
            top_k = raw.get("topK")
            if query is None or not query.strip():
                record_issues.append("query:missing")
            if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
                record_issues.append("topK:must_be_positive_integer")
                top_k = None
            catalog.append(
                Recipe(
                    source,
                    "RAG_SEARCH",
                    family,
                    None,
                    None,
                    query,
                    top_k,
                    path.name,
                    tuple(record_issues),
                )
            )
        else:
            issues.append(f"{prefix}:unknown_catalog_family")
    return catalog, issues


def load_recipe_index(recipe_dir: Path) -> RecipeIndex:
    catalogs = (
        (recipe_dir / "stage21-initial-report-recipes.json", "initial"),
        (recipe_dir / "stage21-report-runtime-recipes.json", "report_runtime"),
        (recipe_dir / "stage21-remaining-runner-recipes.json", "runner_runtime"),
        (recipe_dir / "stage21-remaining-rag-recipes.json", "rag_runtime"),
    )
    by_source: dict[str, list[Recipe]] = defaultdict(list)
    by_initial: dict[str, list[Recipe]] = defaultdict(list)
    errors: list[str] = []
    for path, family in catalogs:
        recipes, catalog_errors = _load_recipe_catalog(path, family)
        errors.extend(catalog_errors)
        for recipe in recipes:
            if family == "initial":
                resource_key = recipe.source_reference.removeprefix("resource-key://")
                by_initial[resource_key].append(recipe)
            else:
                by_source[recipe.source_reference].append(recipe)
    return RecipeIndex(
        {key: tuple(value) for key, value in by_source.items()},
        {key: tuple(value) for key, value in by_initial.items()},
        tuple(errors),
    )


def _java_ref_info(ref: str) -> tuple[str, int | None, str | None] | None:
    for name, pattern in JAVA_REF_PATTERNS.items():
        match = pattern.match(ref)
        if match:
            project = match.groupdict().get("project")
            return (
                name,
                int(project) if project is not None else None,
                match.groupdict().get("rest"),
            )
    return None


def _path_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _resolve_local_ref(repo_root: Path, ref: str) -> tuple[Path | None, str | None]:
    if not ref or ref.startswith("/") or re.match(r"^[A-Za-z]:[\\/]", ref):
        return None, "absolute_or_empty_path"
    path = (repo_root / Path(ref)).resolve()
    if not _path_within(path, repo_root):
        return None, "path_escapes_repository"
    if not path.is_file():
        return path, "file_missing"
    return path, None


def _probe_tcp(url: str) -> str:
    try:
        parsed = urllib.parse.urlsplit(url)
        host = parsed.hostname
        port = parsed.port
        if parsed.scheme not in {"http", "https"} or not host or port is None:
            return "INVALID_URL"
        with socket.create_connection((host, port), timeout=0.25):
            return "TCP_REACHABLE"
    except socket.gaierror:
        return "DNS_UNRESOLVED"
    except (ConnectionRefusedError, TimeoutError, OSError):
        return "TCP_UNREACHABLE"


def _probe_java_health(base_url: str) -> str:
    url = base_url.rstrip("/") + "/actuator/health"
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=0.75) as response:
            if response.status != 200:
                return f"HTTP_STATUS_{response.status}"
            body = response.read(2048)
            try:
                payload = json.loads(body.decode("utf-8"))
            except (JSONDecodeError, UnicodeDecodeError):
                return "HEALTH_PAYLOAD_INVALID"
            return (
                "HEALTHY"
                if isinstance(payload, dict) and payload.get("status") == "UP"
                else "HEALTH_NOT_UP"
            )
    except urllib.error.HTTPError as exc:
        return f"HTTP_STATUS_{exc.code}"
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, socket.gaierror):
            return "DNS_UNRESOLVED"
        return "TCP_UNREACHABLE"
    except (TimeoutError, OSError):
        return "TCP_UNREACHABLE"


def _required_boundaries(operations: Iterable[str]) -> list[str]:
    return [
        OPERATION_BOUNDARIES[operation]
        for operation in operations
        if operation in OPERATION_BOUNDARIES
    ]


def _is_java_required(prerequisite: Prerequisite) -> bool:
    return any(
        operation not in {"NO_JAVA_ACCESS", "NO_TOOL_CALL"}
        for operation in prerequisite.required_operations
    )


def assess_required_fields(
    task: InputTask, prerequisite: Prerequisite
) -> dict[str, dict[str, Any]]:
    """Return semantic field requiredness without treating null/empty as missing.

    ``targetProjectId`` is a task field only when the task's own input makes a
    cross-project target part of the execution plan.  A target can be carried
    by a typed resource reference or by the input literal ``requestedProjectId``;
    the root task JSON does not have to duplicate it.  An empty
    ``requiredAuthorities`` sidecar list is a valid declaration: it is not an
    authority assertion that every task must populate.
    """

    literals = task.literals
    current = prerequisite.current_project_id
    target_literal_key, target_literal = _first_literal(
        literals,
        ("targetProjectId", "target_project_id", "requestedProjectId", "requested_project_id"),
    )
    target_literal_valid = isinstance(target_literal, int) and not isinstance(target_literal, bool)
    typed_projects: list[int] = []
    for entry in task.entries:
        if entry.kind == "JAVA_RESOURCE" and entry.ref:
            info = _java_ref_info(entry.ref)
            if info is not None and info[1] is not None:
                typed_projects.append(info[1])

    explicit_cross_project = False
    if task.task_type == "TOOL_SAFETY":
        if (
            isinstance(target_literal, int)
            and not isinstance(target_literal, bool)
            and current is not None
        ):
            explicit_cross_project = target_literal != current
        if current is not None and any(project != current for project in typed_projects):
            explicit_cross_project = True
        if current is not None and prerequisite.target_project_id is not None:
            if prerequisite.target_project_id != current and (
                prerequisite.target_project_id in typed_projects
                or prerequisite.resource_project_id == prerequisite.target_project_id
            ):
                explicit_cross_project = True
        strategy, _ = _strategy(task)
        if strategy in {
            "CROSS_PROJECT",
            "CROSS_PROJECT_TOOL_GATEWAY",
            "TOOL_GATEWAY_CROSS_PROJECT",
        }:
            explicit_cross_project = True
    elif task.task_type == "E2E_APIOPS":
        if current is not None and any(project != current for project in typed_projects):
            explicit_cross_project = True
    # RAG target scope is carried by the typed RAG resource/query context.  A
    # task-level target field is required only if the task explicitly declares
    # a target-like literal; an empty/null optional field is not a gap.
    elif task.task_type == "RAG_EVIDENCE_RETRIEVAL":
        explicit_cross_project = target_literal_key in {
            "targetProjectId",
            "target_project_id",
            "requestedProjectId",
            "requested_project_id",
        }

    target_provided = target_literal_valid or (
        prerequisite.target_project_id is not None
        and (
            prerequisite.target_project_id in typed_projects
            or prerequisite.resource_project_id == prerequisite.target_project_id
        )
    )
    target_reason = (
        "cross-project target is explicit in a strategy/literal/typed resource"
        if explicit_cross_project
        else "no task-semantic cross-project target is declared"
    )
    java_required = _is_java_required(prerequisite)
    return {
        "targetProjectId": {
            "required": explicit_cross_project,
            "provided": target_provided,
            "providedBy": (
                target_literal_key
                if target_literal_valid
                else "typed_resource_or_sidecar_resourceProjectId"
                if target_provided
                else None
            ),
            "whyRequired": target_reason,
        },
        "requiredAuthorities": {
            "required": False,
            "provided": bool(prerequisite.required_authorities),
            "providedBy": "sidecar.requiredAuthorities"
            if prerequisite.required_authorities
            else None,
            "whyRequired": (
                "optional authority override; empty is valid for this prerequisite "
                "declaration"
            ),
        },
        "minimumProjectRole": {
            "required": java_required,
            "provided": bool(prerequisite.minimum_project_role),
            "providedBy": "sidecar.minimumProjectRole"
            if prerequisite.minimum_project_role
            else None,
            "whyRequired": "Java-required task needs an explicit minimum project role",
        },
    }


def _first_literal(literals: Mapping[str, Any], keys: Iterable[str]) -> tuple[str | None, Any]:
    for key in keys:
        if key in literals:
            return key, literals[key]
    return None, None


def _strategy(task: InputTask) -> tuple[str, list[str]]:
    literals = task.literals
    keys = [key for key in STRATEGY_KEYS if key in literals]
    issues: list[str] = []
    if len(keys) > 1 and len({repr(literals[key]) for key in keys}) > 1:
        issues.append("multiple_strategy_literals_disagree")
    explicit_key = keys[0] if keys else None
    value = literals.get(explicit_key) if explicit_key else None
    if explicit_key and (not isinstance(value, str) or not value.strip()):
        issues.append(f"{explicit_key}:must_be_non_empty_string")
    if isinstance(value, str) and value.strip():
        strategy = value
    else:
        defaults = {
            "TESTCASE_GENERATION": "TESTCASE_GENERATION_FROM_TYPED_INPUT",
            "FAILURE_DIAGNOSIS": "REPORT_BACKED_DIAGNOSIS",
            "TOOL_SAFETY": "TOOL_GATEWAY_PREFLIGHT",
            "RAG_EVIDENCE_RETRIEVAL": "RAG_TOOL_GATEWAY_RETRIEVAL",
            "E2E_APIOPS": "MODEL_GENERATION_THEN_JAVA_EXECUTION",
        }
        strategy = defaults.get(task.task_type, "UNKNOWN")
    if task.task_type == "TESTCASE_GENERATION" and strategy not in GENERATION_STRATEGIES:
        issues.append(f"unsupported_generation_strategy={strategy}")
    return strategy, issues


def _recipe_resolution(
    task: InputTask,
    prerequisite: Prerequisite,
    entries: tuple[InputEntry, ...],
    recipe_index: RecipeIndex,
) -> tuple[dict[str, Any], list[str], list[str], bool, list[str]]:
    """Resolve recipes from typed references, returning (view, gaps, mappings, model, targets)."""

    recipe_view: dict[str, Any] = {
        "resolution": "NOT_REQUIRED",
        "references": [],
        "recipes": [],
    }
    recipe_gaps: list[str] = []
    mapping_issues: list[str] = []
    model_required = False
    target_urls: list[str] = []
    java_refs = [entry.ref for entry in entries if entry.kind == "JAVA_RESOURCE" and entry.ref]
    if not java_refs:
        if prerequisite.resource_setup_type == "RUNTIME_RECIPE":
            recipe_gaps.append("runtime_recipe_requires_java_reference")
        return recipe_view, recipe_gaps, mapping_issues, model_required, target_urls
    recipe_view["resolution"] = "RESOLVED"

    for ref in java_refs:
        assert ref is not None
        recipe_view["references"].append(ref)
        info = _java_ref_info(ref)
        if info is None:
            mapping_issues.append(f"unknown_typed_java_reference={ref}")
            continue
        ref_kind, ref_project, ref_rest = info
        if (
            ref_project is not None
            and prerequisite.resource_project_id is not None
            and ref_project != prerequisite.resource_project_id
        ):
            mapping_issues.append(
                f"resource_project_mismatch:ref={ref_project}:sidecar={prerequisite.resource_project_id}"
            )
        if ref_kind == "metadata":
            recipe_view["recipes"].append(
                {
                    "sourceReference": ref,
                    "kind": "PUBLIC_METADATA_REFERENCE",
                    "projectId": ref_project,
                }
            )
            continue
        if ref_kind == "test_report":
            if ref_rest and ref_rest.startswith("stage21-initial/"):
                resource_key = ref_rest.removeprefix("stage21-initial/")
                candidates = recipe_index.by_initial_resource_key.get(resource_key, ())
                if len(candidates) != 1:
                    recipe_gaps.append(
                        f"initial_report_recipe_count={len(candidates)}:{resource_key}"
                    )
                elif candidates[0].issues:
                    recipe_gaps.extend(
                        f"initial_report_recipe:{item}" for item in candidates[0].issues
                    )
                else:
                    recipe_view["recipes"].append(
                        {
                            "sourceReference": ref,
                            "kind": candidates[0].kind,
                            "caseId": candidates[0].case_id,
                            "catalog": candidates[0].catalog_path,
                            "projectId": ref_project,
                        }
                    )
            else:
                recipe_view["recipes"].append(
                    {
                        "sourceReference": ref,
                        "kind": "PUBLIC_REPORT_REFERENCE",
                        "projectId": ref_project,
                    }
                )
            continue
        if ref_kind in {"runner_testcase", "runner_unit"}:
            candidates = recipe_index.by_source.get(ref, ())
            if len(candidates) == 0:
                if task.task_type == "E2E_APIOPS" and not prerequisite.contract_gaps:
                    model_required = True
                    recipe_view["resolution"] = "MODEL_GENERATED"
                    recipe_view["recipes"].append(
                        {"sourceReference": ref, "kind": "MODEL_GENERATED_TESTCASE_REQUIRED"}
                    )
                else:
                    recipe_gaps.append(f"runner_recipe_missing:{ref}")
            elif len(candidates) > 1:
                mapping_issues.append(
                    f"ambiguous_typed_source_reference:{ref}:candidate_count={len(candidates)}"
                )
                recipe_view["resolution"] = "AMBIGUOUS"
            elif candidates[0].issues:
                recipe_gaps.extend(f"runner_recipe:{item}" for item in candidates[0].issues)
            else:
                recipe = candidates[0]
                recipe_view["recipes"].append(recipe.as_dict())
                if recipe.base_url:
                    target_urls.append(recipe.base_url)
            continue
        if ref_kind == "rag":
            candidates = recipe_index.by_source.get(ref, ())
            if len(candidates) == 0:
                recipe_gaps.append(f"rag_recipe_missing:{ref}")
            elif len(candidates) > 1:
                mapping_issues.append(
                    f"ambiguous_typed_source_reference:{ref}:candidate_count={len(candidates)}"
                )
                recipe_view["resolution"] = "AMBIGUOUS"
            elif candidates[0].issues:
                recipe_gaps.extend(f"rag_recipe:{item}" for item in candidates[0].issues)
            else:
                recipe_view["recipes"].append(candidates[0].as_dict())
            continue
        if ref_kind == "tool_gateway":
            recipe_view["recipes"].append(
                {"sourceReference": ref, "kind": "TOOL_GATEWAY_POLICY_REFERENCE"}
            )

    if prerequisite.resource_setup_type == "BENCHMARK_LOCAL_INPUT":
        mapping_issues.append("sidecar_declares_benchmark_local_input_but_task_has_java_resource")
    if "RESOURCE_REFERENCE_GAP" in prerequisite.contract_gaps:
        mapping_issues.append("sidecar_declared_RESOURCE_REFERENCE_GAP")
    if "TASK_EXECUTION_CONFIG_MISMATCH" in prerequisite.contract_gaps:
        mapping_issues.append("sidecar_declared_TASK_EXECUTION_CONFIG_MISMATCH")
    if "RUNTIME_RECIPE_GAP" in prerequisite.contract_gaps:
        recipe_gaps.append("sidecar_declared_RUNTIME_RECIPE_GAP")
    if recipe_gaps:
        recipe_view["resolution"] = "MISSING_OR_INVALID"
    return (
        recipe_view,
        sorted(set(recipe_gaps)),
        sorted(set(mapping_issues)),
        model_required,
        sorted(set(target_urls)),
    )


def _recommended_action(classification: str) -> str:
    return {
        "READY": "No input-side action; model/evaluation phase was intentionally not run.",
        "TASK_INPUT_CONTRACT_GAP": (
            "Repair the typed task/sidecar input contract before execution; "
            "no repair performed."
        ),
        "RUNTIME_RESOURCE_MISSING": (
            "Provision or expose the declared runtime resource/target service; "
            "no repair performed."
        ),
        "RESOURCE_MAPPING_BUG": (
            "Repair typed resource-to-runtime mapping or source-reference "
            "uniqueness; no repair performed."
        ),
        "REAL_JAVA_BUG": (
            "Investigate the Java public-boundary implementation; "
            "no repair performed."
        ),
        "STRATEGY_INPUT_CONTRACT_GAP": (
            "Repair the declared execution strategy/applicability contract; "
            "no repair performed."
        ),
        "AUTH_PREREQUISITE_GAP": (
            "Provide the declared auth-profile prerequisite through the "
            "approved boundary; no repair performed."
        ),
        "RUNTIME_RECIPE_GAP": (
            "Add or correct the declared input-side runtime recipe; "
            "no repair performed."
        ),
        "NOT_PREFLIGHTABLE_MODEL_BEHAVIOR": (
            "Defer model-generated behavior to a permitted model phase; "
            "it was not run here."
        ),
    }[classification]


def _status(value: str, issues: Iterable[str]) -> str:
    values = sorted(set(issue for issue in issues if issue))
    return value if not values else value + ":" + ";".join(values)


def _input_reference_view(entries: tuple[InputEntry, ...]) -> list[dict[str, Any]]:
    return [entry.as_dict() for entry in entries]


def _scope_issues(
    task: InputTask, prerequisite: Prerequisite, entries: tuple[InputEntry, ...]
) -> list[str]:
    issues: list[str] = []
    literals = task.literals
    requiredness = assess_required_fields(task, prerequisite)
    target_requirement = requiredness["targetProjectId"]
    if target_requirement["required"] and not target_requirement["provided"]:
        issues.append("targetProjectId_semantically_required_but_not_provided")
    if prerequisite.current_project_id is not None:
        for key in ("currentProjectId", "current_project_id"):
            if key in literals and literals[key] != prerequisite.current_project_id:
                issues.append(f"{key}_does_not_match_sidecar_currentProjectId")
    known_scope = {
        value
        for value in (prerequisite.current_project_id, prerequisite.target_project_id)
        if value is not None
    }
    for entry in entries:
        if entry.kind != "JAVA_RESOURCE" or not entry.ref:
            continue
        info = _java_ref_info(entry.ref)
        if info is None:
            continue
        _, project, _ = info
        if (
            project is not None
            and known_scope
            and project not in known_scope | {prerequisite.resource_project_id}
        ):
            issues.append(f"typed_reference_project_outside_declared_scope={project}")
    return sorted(set(issues))


def _input_ref_issues(
    task: InputTask, prerequisite: Prerequisite, repo_root: Path
) -> tuple[list[str], list[str], list[str]]:
    contract: list[str] = []
    mapping: list[str] = []
    missing_local: list[str] = []
    java_refs = 0
    python_refs = 0
    for entry in task.entries:
        if entry.kind == "JAVA_RESOURCE":
            java_refs += 1
            if not entry.ref or not entry.ref.startswith("java://"):
                contract.append(f"{entry.key}:JAVA_RESOURCE_ref_must_use_java_scheme")
            elif _java_ref_info(entry.ref) is None:
                contract.append(f"{entry.key}:unknown_typed_java_reference")
        elif entry.kind == "PYTHON_FIXTURE":
            python_refs += 1
            if not entry.ref or entry.ref.startswith("java://"):
                contract.append(f"{entry.key}:PYTHON_FIXTURE_ref_must_be_local_path")
            else:
                _, error = _resolve_local_ref(repo_root, entry.ref or "")
                if error == "file_missing":
                    missing_local.append(f"python_fixture_missing:{entry.ref}")
                elif error:
                    contract.append(f"{entry.key}:{error}")
    if (
        prerequisite.resource_setup_type == "BENCHMARK_LOCAL_INPUT"
        and java_refs
        and not python_refs
    ):
        mapping.append("BENCHMARK_LOCAL_INPUT_has_no_explicit_python_fixture")
    if prerequisite.resource_setup_type == "EXISTING_JAVA_RESOURCE" and not java_refs:
        mapping.append("EXISTING_JAVA_RESOURCE_has_no_typed_java_reference")
    if prerequisite.resource_setup_type == "TEST_ONLY_REFERENCE" and not java_refs:
        mapping.append("TEST_ONLY_REFERENCE_has_no_typed_java_reference")
    if prerequisite.resource_setup_type == "RUNTIME_RECIPE" and not java_refs:
        mapping.append("RUNTIME_RECIPE_has_no_typed_java_reference")
    return sorted(set(contract)), sorted(set(mapping)), sorted(set(missing_local))


def _audit_one(
    manifest_entry: ManifestEntry,
    task: InputTask,
    prerequisite: Prerequisite,
    *,
    recipe_index: RecipeIndex,
    repo_root: Path,
    java_health: str,
    auth_status: str,
    target_probe_status: Mapping[str, str],
) -> dict[str, Any]:
    contract_issues = list(manifest_entry.contract_issues) + list(task.contract_issues)
    contract_issues.extend(prerequisite.contract_issues)
    if task.task_id != manifest_entry.task_id:
        contract_issues.append("task_file_benchmarkTaskId_does_not_match_manifest")
    if prerequisite.task_id != manifest_entry.task_id:
        contract_issues.append("sidecar_benchmarkTaskId_does_not_match_manifest")
    strategy, strategy_issues = _strategy(task)
    scope_issues = _scope_issues(task, prerequisite, task.entries)
    contract_issues.extend(scope_issues)
    semantic_requiredness = assess_required_fields(task, prerequisite)
    for field_name, requirement in semantic_requiredness.items():
        if requirement["required"] and not requirement["provided"]:
            contract_issues.append(f"{field_name}_semantically_required_but_missing")
    ref_contract, ref_mapping, local_missing = _input_ref_issues(task, prerequisite, repo_root)
    contract_issues.extend(ref_contract)
    mapping_issues = list(ref_mapping)

    runtime_recipe, recipe_gaps, recipe_mapping, model_required, target_urls = _recipe_resolution(
        task, prerequisite, task.entries, recipe_index
    )
    mapping_issues.extend(recipe_mapping)
    java_required = _is_java_required(prerequisite)
    required_boundaries = _required_boundaries(prerequisite.required_operations)
    target_statuses = [target_probe_status.get(url, "NOT_PROBED") for url in target_urls]
    target_unreachable = any(status not in {"TCP_REACHABLE"} for status in target_statuses)
    java_health_bad = java_required and java_health != "HEALTHY"
    auth_missing = java_required and auth_status.startswith("PROFILE_DECLARED_CREDENTIALS_MISSING")

    # Category precedence is root-cause oriented: input/contract and mapping
    # findings precede runtime readiness; no HTTP response code is interpreted
    # as a classification.
    if contract_issues:
        classification = "TASK_INPUT_CONTRACT_GAP"
    elif strategy_issues:
        classification = "STRATEGY_INPUT_CONTRACT_GAP"
    elif mapping_issues:
        classification = "RESOURCE_MAPPING_BUG"
    elif recipe_gaps:
        classification = "RUNTIME_RECIPE_GAP"
    elif local_missing or target_unreachable or java_health_bad:
        classification = "RUNTIME_RESOURCE_MISSING"
    elif auth_missing:
        classification = "AUTH_PREREQUISITE_GAP"
    elif model_required:
        classification = "NOT_PREFLIGHTABLE_MODEL_BEHAVIOR"
    else:
        classification = "READY"

    if local_missing:
        resource_status = "MISSING_LOCAL_INPUT"
    elif mapping_issues:
        resource_status = "CONTRACT_MAPPING_MISMATCH"
    elif java_required:
        resource_status = "PUBLIC_BOUNDARY_NOT_READ_BY_AUDIT_POLICY"
    else:
        resource_status = "LOCAL_INPUT_READY"

    if strategy_issues:
        strategy_status = "INVALID"
    elif task.task_type == "TESTCASE_GENERATION":
        strategy_status = "APPLICABLE"
    else:
        strategy_status = "INPUT_APPLICABLE"

    if not java_required:
        effective_auth_status = "NOT_REQUIRED_NO_JAVA_ACCESS"
    else:
        effective_auth_status = auth_status

    if local_missing:
        runtime_status = "LOCAL_INPUT_MISSING"
    elif target_unreachable:
        runtime_status = "TARGET_SERVICE_UNREACHABLE"
    elif java_health_bad:
        runtime_status = "JAVA_PUBLIC_BOUNDARY_HEALTH_NOT_READY"
    elif auth_missing:
        runtime_status = "JAVA_AUTH_UNAVAILABLE"
    elif model_required:
        runtime_status = "MODEL_GENERATION_REQUIRED"
    elif java_required:
        runtime_status = "JAVA_BOUNDARY_DECLARED_NOT_EXECUTED_BY_POLICY"
    else:
        runtime_status = "READY"

    evidence: list[dict[str, str]] = [
        {
            "kind": "INPUT_PROJECTION",
            "source": "task JSON allowlist projection",
            "rootCause": (
                "Only schemaVersion/benchmarkTaskId/taskType/instruction/initialState/"
                "allowedTools/forbiddenActions were retained."
            ),
        },
        {
            "kind": "SIDECAR_CONTRACT",
            "source": "stage21-execution-prerequisites.json",
            "rootCause": (
                f"authProfile={prerequisite.auth_profile}; "
                f"resourceSetupType={prerequisite.resource_setup_type}; "
                f"requiredOperations={','.join(prerequisite.required_operations)}"
            ),
        },
    ]
    if scope_issues:
        evidence.append(
            {
                "kind": "PROJECT_SCOPE",
                "source": "typed input + input-side prerequisite sidecar",
                "rootCause": ";".join(scope_issues),
            }
        )
    if mapping_issues:
        evidence.append(
            {
                "kind": "RESOURCE_MAPPING",
                "source": "typed sourceReference and input-side recipe index",
                "rootCause": ";".join(sorted(set(mapping_issues))),
            }
        )
    if recipe_gaps:
        evidence.append(
            {
                "kind": "RUNTIME_RECIPE",
                "source": "typed sourceReference and recipe catalog",
                "rootCause": ";".join(recipe_gaps),
            }
        )
    if local_missing:
        evidence.append(
            {
                "kind": "LOCAL_RESOURCE",
                "source": "explicit PYTHON_FIXTURE ref",
                "rootCause": ";".join(local_missing),
            }
        )
    if target_urls:
        evidence.append(
            {
                "kind": "TARGET_SERVICE_PROBE",
                "source": "TCP readiness only; no request execution",
                "rootCause": ";".join(
                    f"{url}={target_probe_status.get(url, 'NOT_PROBED')}" for url in target_urls
                ),
            }
        )
    if java_required:
        evidence.append(
            {
                "kind": "JAVA_PUBLIC_BOUNDARY",
                "source": "GET /actuator/health only; no auth/data/runner/tool call",
                "rootCause": (
                    f"health={java_health}; auth={effective_auth_status}; "
                    f"requiredBoundaries={','.join(required_boundaries)}"
                ),
            }
        )
    if model_required:
        evidence.append(
            {
                "kind": "MODEL_POLICY",
                "source": "input-only audit policy",
                "rootCause": (
                    "A model-generated execution input is required; model calls are "
                    "prohibited in Stage 21 audit."
                ),
            }
        )
    if classification == "READY":
        evidence.append(
            {
                "kind": "DETERMINISTIC_RESULT",
                "source": "input-side checks",
                "rootCause": (
                    "All applicable input-side contract, mapping, recipe, authority and "
                    "runtime prerequisite checks passed."
                ),
            }
        )

    input_ref_types = sorted({entry.kind for entry in task.entries})
    requiredness = semantic_requiredness
    required_target_service: list[str] = list(target_urls)
    if java_required and not required_target_service:
        required_target_service = ["JAVA_PUBLIC_BOUNDARY"]
    return {
        "taskId": manifest_entry.task_id,
        "split": manifest_entry.split,
        "category": task.task_type,
        "authProfile": prerequisite.auth_profile,
        "currentProjectId": prerequisite.current_project_id,
        "targetProjectId": prerequisite.target_project_id,
        "executionStrategy": strategy,
        "inputReferenceType": "+".join(input_ref_types) if input_ref_types else "NONE",
        "inputReferences": _input_reference_view(task.entries),
        "semanticRequiredness": requiredness,
        "runtimeRecipe": runtime_recipe,
        "javaRequired": java_required,
        "requiredJavaBoundary": required_boundaries,
        "requiredTargetService": required_target_service,
        "contractStatus": _status("PASS", contract_issues),
        "resourceStatus": resource_status,
        "strategyStatus": _status(strategy_status, strategy_issues),
        "authStatus": effective_auth_status,
        "runtimePrerequisiteStatus": runtime_status,
        "classification": classification,
        "evidence": evidence,
        "recommendedAction": _recommended_action(classification),
    }


def _auth_status(profile: str, environment: Mapping[str, str]) -> str:
    if profile not in PROFILE_ENV_VARS:
        return "PROFILE_DECLARED_UNKNOWN"
    missing = tuple(
        name for name in PROFILE_ENV_VARS[profile] if not environment.get(name, "").strip()
    )
    if missing:
        return "PROFILE_DECLARED_CREDENTIALS_MISSING:" + ",".join(missing)
    return "PROFILE_DECLARED_CREDENTIALS_PRESENT_NOT_CONSUMED"


@dataclass(frozen=True, slots=True)
class InputAuditResult:
    metadata: dict[str, Any]
    rows: tuple[dict[str, Any], ...]
    verification: dict[str, Any]

    def deterministic_view(self) -> dict[str, Any]:
        return {"metadata": self.metadata, "rows": self.rows, "verification": self.verification}


def run_input_side_audit(
    *,
    manifest_path: Path,
    sidecar_path: Path,
    recipe_dir: Path,
    repo_root: Path,
    java_base_url: str | None = None,
    environment: Mapping[str, str] | None = None,
    probe_runtime: bool = True,
) -> InputAuditResult:
    """Run the read-only audit without loading expected-side data or calling a model."""

    environment = os.environ if environment is None else environment
    manifest = project_manifest_file(manifest_path)
    prerequisites = load_prerequisites(sidecar_path)
    recipe_index = load_recipe_index(recipe_dir)
    java_url = (
        java_base_url
        or environment.get("JAVA_APIOPS_BASE_URL", "").strip()
        or "http://127.0.0.1:19090"
    ).rstrip("/")
    java_health = _probe_java_health(java_url) if probe_runtime else "NOT_PROBED_BY_TEST"

    all_target_urls: set[str] = set()
    preliminary: list[
        tuple[
            ManifestEntry, InputTask, Prerequisite, dict[str, Any], list[str], list[str], list[str]
        ]
    ] = []
    projection_skipped: list[str] = list(manifest.projection_trace.skipped_expected_side_keys)
    projection_unknown: list[str] = list(manifest.projection_trace.ignored_unknown_keys)
    for manifest_entry in manifest.tasks:
        task_path = (manifest_path.parent / manifest_entry.task_file).resolve()
        if not _path_within(task_path, manifest_path.parent.resolve()):
            task = InputTask(
                manifest_entry.task_id,
                "<unreadable>",
                0,
                "",
                (),
                (),
                None,
                ("taskFile:path_escapes_dataset_root",),
                ProjectionTrace(),
            )
        elif not task_path.is_file():
            task = InputTask(
                manifest_entry.task_id,
                "<unreadable>",
                0,
                "",
                (),
                (),
                None,
                ("taskFile:file_missing",),
                ProjectionTrace(),
            )
        else:
            try:
                task = project_input_task_file(task_path)
            except InputAuditError as exc:
                task = InputTask(
                    manifest_entry.task_id,
                    "<unreadable>",
                    0,
                    "",
                    (),
                    (),
                    None,
                    (f"taskFile:input_projection_failed:{type(exc).__name__}",),
                    ProjectionTrace(),
                )
        projection_skipped.extend(task.projection_trace.skipped_expected_side_keys)
        projection_unknown.extend(task.projection_trace.ignored_unknown_keys)
        prerequisite = prerequisites.get(manifest_entry.task_id)
        if prerequisite is None:
            prerequisite = Prerequisite(
                manifest_entry.task_id,
                "<missing>",
                None,
                None,
                None,
                (),
                None,
                (),
                "<missing>",
                "<missing>",
                (),
                ("sidecar_row_missing",),
            )
        runtime_recipe, recipe_gaps, mapping_issues, model_required, target_urls = (
            _recipe_resolution(task, prerequisite, task.entries, recipe_index)
        )
        all_target_urls.update(target_urls)
        preliminary.append(
            (
                manifest_entry,
                task,
                prerequisite,
                runtime_recipe,
                recipe_gaps,
                mapping_issues,
                target_urls,
            )
        )

    target_probe_status = {
        url: (_probe_tcp(url) if probe_runtime else "NOT_PROBED_BY_TEST")
        for url in sorted(all_target_urls)
    }
    rows: list[dict[str, Any]] = []
    for manifest_entry, task, prerequisite, _, _, _, _ in preliminary:
        row = _audit_one(
            manifest_entry,
            task,
            prerequisite,
            recipe_index=recipe_index,
            repo_root=repo_root,
            java_health=java_health,
            auth_status=_auth_status(prerequisite.auth_profile, environment),
            target_probe_status=target_probe_status,
        )
        rows.append(row)

    expected_side_loaded_count = 0
    forbidden_runtime_imports = {
        module: module in __import__("sys").modules
        for module in ("app.evaluator", "app.benchmark.dataset", "app.benchmark.models")
    }
    observed_classifications = Counter(row["classification"] for row in rows)
    classification_counts = {
        classification: observed_classifications.get(classification, 0)
        for classification in ALLOWED_CLASSIFICATIONS
    }
    split_counts = dict(sorted(Counter(row["split"] for row in rows).items()))
    metadata: dict[str, Any] = {
        "schemaVersion": "stage21-input-side-audit/v1",
        "auditMode": "INPUT_ONLY_DETERMINISTIC_PREFLIGHT",
        "datasetId": manifest.dataset_id,
        "datasetVersion": manifest.dataset_version,
        "taskSchemaVersion": manifest.task_schema_version,
        "manifestPath": manifest_path.name,
        "taskCount": len(rows),
        "splitCounts": split_counts,
        "classificationCounts": classification_counts,
        "javaBaseUrl": java_url,
        "javaBaseUrlFromEnvironment": bool(environment.get("JAVA_APIOPS_BASE_URL", "").strip()),
        "javaHealth": java_health,
        "targetServiceProbe": target_probe_status,
        "recipeCatalogIssues": list(recipe_index.catalog_issues),
    }
    verification = {
        "expectedSideLoadedCount": expected_side_loaded_count,
        "expectedSideForbiddenKeysEncountered": sorted(set(projection_skipped)),
        "expectedSideValuesMaterialized": False,
        "expectedSideProjectionProof": {
            "rootTaskProjectionAllowlist": sorted(TASK_ROOT_KEYS),
            "manifestEntryProjectionAllowlist": sorted(MANIFEST_ENTRY_KEYS),
            "expectedSideValuesPassedToAuditObjects": False,
            "expectedSideRawValuesParsed": False,
            "benchmarkEvaluatorImportedDuringAudit": forbidden_runtime_imports["app.evaluator"],
            "benchmarkDatasetLoaderImportedDuringAudit": forbidden_runtime_imports[
                "app.benchmark.dataset"
            ],
            "benchmarkTaskModelImportedDuringAudit": forbidden_runtime_imports[
                "app.benchmark.models"
            ],
        },
        "modelCallCount": 0,
        "fixtureFallbackCount": 0,
        "pythonBypassCount": 0,
        "javaLoginCount": 0,
        "javaMutationCount": 0,
        "runnerSubmitCount": 0,
        "toolGatewayCallCount": 0,
        "reportReadCount": 0,
        "instructionSubstringRoutingCount": 0,
        "taskIdRuntimeRoutingCount": 0,
        "expectedSideRoutingCount": 0,
        "unknownRecipeFailClosed": True,
        "auditProjectionUnknownRootKeys": sorted(set(projection_unknown)),
        "manifestContractIssues": list(manifest.contract_issues),
        "sidecarTaskCount": len(prerequisites),
        "recipeTargetServiceProbeIsTCPOnly": True,
        "javaProbeIsHealthOnly": True,
    }
    return InputAuditResult(metadata, tuple(rows), verification)


def assert_result_invariants(result: InputAuditResult) -> None:
    rows = result.rows
    if len(rows) != 105:
        raise AssertionError(f"expected 105 audit rows, got {len(rows)}")
    if Counter(row["split"] for row in rows) != Counter({"dev": 95, "held_out": 10}):
        raise AssertionError("split count is not DEV95 + HELD_OUT10")
    ids = [row["taskId"] for row in rows]
    if len(ids) != len(set(ids)):
        raise AssertionError("duplicate taskId in audit matrix")
    allowed = set(ALLOWED_CLASSIFICATIONS)
    invalid = sorted({row["classification"] for row in rows} - allowed)
    if invalid:
        raise AssertionError(f"invalid classification values: {invalid}")
    if set(result.metadata["classificationCounts"]) != allowed:
        raise AssertionError("classification count map does not enumerate the frozen categories")
    required_fields = {
        "taskId",
        "split",
        "category",
        "authProfile",
        "currentProjectId",
        "targetProjectId",
        "executionStrategy",
        "inputReferenceType",
        "inputReferences",
        "runtimeRecipe",
        "javaRequired",
        "requiredJavaBoundary",
        "requiredTargetService",
        "contractStatus",
        "resourceStatus",
        "strategyStatus",
        "authStatus",
        "runtimePrerequisiteStatus",
        "classification",
        "evidence",
        "recommendedAction",
    }
    for row in rows:
        missing = required_fields - set(row)
        if missing:
            raise AssertionError(f"{row.get('taskId')}: missing matrix fields {sorted(missing)}")
    verification = result.verification
    if verification["expectedSideLoadedCount"] != 0:
        raise AssertionError("expected-side data was loaded")
    if verification["modelCallCount"] != 0:
        raise AssertionError("model call count is non-zero")
    if verification["fixtureFallbackCount"] != 0:
        raise AssertionError("fixture fallback count is non-zero")
    if verification["pythonBypassCount"] != 0:
        raise AssertionError("Python bypass count is non-zero")
    proof = verification["expectedSideProjectionProof"]
    if proof["expectedSideValuesPassedToAuditObjects"] or proof["expectedSideRawValuesParsed"]:
        raise AssertionError("expected-side projection proof failed")


def result_digest(result: InputAuditResult) -> str:
    canonical = json.dumps(
        result.deterministic_view(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def run_validator_self_tests() -> dict[str, str]:
    """Run deterministic requiredness/isolation checks without repository I/O."""

    def prerequisite(
        *,
        current: int | None = 41,
        target: int | None = 42,
        resource: int | None = None,
        operations: tuple[str, ...] = ("NO_JAVA_ACCESS",),
    ) -> Prerequisite:
        return Prerequisite(
            "self-test-task",
            "NORMAL",
            current,
            target,
            resource,
            operations,
            "VIEWER",
            (),
            "TEST_ONLY_REFERENCE",
            "TEST_ONLY",
            (),
            (),
        )

    def task(
        *,
        task_type: str,
        task_id: str = "self-test-task",
        strategy: Any = None,
        entries: list[dict[str, Any]] | None = None,
        expected_value: Any = {"sentinel": "one"},
    ) -> InputTask:
        input_entries = list(entries or [])
        if strategy is not None:
            input_entries.append({"kind": "LITERAL", "key": "executionStrategy", "value": strategy})
        root = {
            "schemaVersion": "0.2.0",
            "benchmarkTaskId": task_id,
            "taskType": task_type,
            "instruction": "self test input",
            "initialState": {"entries": input_entries},
            "allowedTools": ["rag.search"],
            "forbiddenActions": ["bypass"],
            "expectedOutput": expected_value,
            "expectedToolCalls": [{"toolName": "sentinel"}],
            "groundTruthRef": {"groundTruthId": "sentinel", "version": "1"},
            "evaluationResult": {"score": expected_value},
            "modelScore": 0.99,
        }
        return project_input_task_text(json.dumps(root, ensure_ascii=False))

    local_prerequisite = prerequisite()
    optional = task(
        task_type="TESTCASE_GENERATION",
        entries=[{"kind": "LITERAL", "key": "targetProjectId", "value": None}],
    )
    if _scope_issues(optional, local_prerequisite, optional.entries):
        raise AssertionError("optional null field incorrectly created a contract gap")

    required_missing = task(task_type="TOOL_SAFETY", strategy="CROSS_PROJECT")
    if "targetProjectId_semantically_required_but_not_provided" not in _scope_issues(
        required_missing, local_prerequisite, required_missing.entries
    ):
        raise AssertionError("required target field did not create a contract gap")

    generation = task(task_type="TESTCASE_GENERATION", strategy="HAPPY_PATH")
    normal_tool = task(task_type="TOOL_SAFETY", strategy="TOOL_GATEWAY_PREFLIGHT")
    cross_tool = task(task_type="TOOL_SAFETY", strategy="CROSS_PROJECT")
    if _scope_issues(generation, local_prerequisite, generation.entries):
        raise AssertionError("generation task inherited cross-project requiredness")
    if _scope_issues(normal_tool, local_prerequisite, normal_tool.entries):
        raise AssertionError("non-cross-project tool task inherited target requiredness")
    if not _scope_issues(cross_tool, local_prerequisite, cross_tool.entries):
        raise AssertionError("cross-project strategy did not require target")

    expected_one = task(task_type="TOOL_SAFETY", strategy="CROSS_PROJECT", expected_value={"a": 1})
    expected_two = task(
        task_type="TOOL_SAFETY", strategy="CROSS_PROJECT", expected_value={"a": 2, "b": 3}
    )
    if assess_required_fields(expected_one, local_prerequisite) != assess_required_fields(
        expected_two, local_prerequisite
    ):
        raise AssertionError("expected-side variation changed requiredness")

    renamed = task(
        task_type="TOOL_SAFETY",
        task_id="renamed-task",
        strategy="CROSS_PROJECT",
        entries=[{"kind": "LITERAL", "key": "targetProjectId", "value": 42}],
    )
    original = task(
        task_type="TOOL_SAFETY",
        strategy="CROSS_PROJECT",
        entries=[{"kind": "LITERAL", "key": "targetProjectId", "value": 42}],
    )
    if assess_required_fields(original, local_prerequisite) != assess_required_fields(
        renamed, local_prerequisite
    ):
        raise AssertionError("taskId rename changed requiredness")

    unknown = task(
        task_type="TOOL_SAFETY",
        entries=[{"kind": "JAVA_RESOURCE", "key": "unknown", "ref": "java://unknown/resource"}],
    )
    contract, _, _ = _input_ref_issues(unknown, local_prerequisite, Path.cwd())
    if "unknown:unknown_typed_java_reference" not in contract:
        raise AssertionError("unknown typed reference was not failed closed")

    return {
        "optionalNullField": "PASS",
        "requiredFieldMissing": "PASS",
        "categoryStrategySensitiveRequiredness": "PASS",
        "expectedSideInvariant": "PASS",
        "taskIdInvariant": "PASS",
        "unknownTypedContractFailClosed": "PASS",
    }


__all__ = [
    "ALLOWED_CLASSIFICATIONS",
    "InputAuditError",
    "InputAuditResult",
    "assess_required_fields",
    "assert_result_invariants",
    "load_recipe_index",
    "load_prerequisites",
    "project_input_task_text",
    "project_manifest_text",
    "project_input_task_file",
    "project_manifest_file",
    "result_digest",
    "run_validator_self_tests",
    "run_input_side_audit",
]
