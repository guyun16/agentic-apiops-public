"""Prove DiagnosisRun and Durable HITL recovery across real Python processes."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread

INITIAL_MARKER = "INITIAL: return either a final DiagnosisReport or one ToolIntent."
CONTINUATION_MARKER = (
    "CONTINUATION: the tool budget is exhausted; return only a final DiagnosisReport."
)
RAG_QUERY = "diagnosis HITL restart acceptance evidence"
RAG_TOP_K = 11
MODEL_NAME = "deepseek-hitl-acceptance"
FAKE_API_KEY = "acceptance-local-fake-key"
FAILED_RUN_STATUSES = {"ASSERTION_FAILED", "EXECUTION_FAILED", "TIMEOUT"}


class HttpTransportError(RuntimeError):
    """The HTTP request did not receive a response."""


class AcceptanceFailure(RuntimeError):
    """A named acceptance gate failed without retaining sensitive payloads."""

    def __init__(
        self,
        step: str,
        code: str,
        message: str,
        *,
        facts: dict[str, object] | None = None,
        http_status: int | None = None,
    ) -> None:
        super().__init__(message)
        self.step = step
        self.code = code
        self.message = message
        self.facts = facts if facts is not None else {}
        self.http_status = http_status
        self.log_tail_a = ""
        self.log_tail_b = ""


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    data: object | None


@dataclass(slots=True)
class FakeProviderState:
    lock: Lock
    request_modes: list[str]
    request_hashes: list[str]
    expected_final: dict[str, object] | None

    def bind_final_identity(
        self,
        *,
        project_id: int,
        run_id: int,
        report_id: str,
        agent_run_id: str,
        trace_id: str,
        failure_type: str,
    ) -> None:
        values: dict[str, object] = {
            "projectId": project_id,
            "runId": run_id,
            "reportId": report_id,
            "agentRunId": agent_run_id,
            "traceId": trace_id,
            "failureType": failure_type,
        }
        if (
            isinstance(project_id, bool)
            or not isinstance(project_id, int)
            or project_id < 1
            or isinstance(run_id, bool)
            or not isinstance(run_id, int)
            or run_id < 1
            or any(
                not isinstance(values[key], str) or not values[key]
                for key in values
                if key not in {"projectId", "runId"}
            )
        ):
            raise ValueError("fake final identity must contain non-empty controlled values")
        with self.lock:
            if self.expected_final is not None:
                raise ValueError("fake final identity is already bound")
            self.expected_final = values

    def snapshot(self) -> tuple[list[str], list[str]]:
        with self.lock:
            return list(self.request_modes), list(self.request_hashes)


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _fake_initial_envelope() -> dict[str, object]:
    content = {
        "tool_name": "rag.search",
        "arguments": {"query": RAG_QUERY, "topK": RAG_TOP_K},
    }
    return {
        "id": "fake-hitl-initial-1",
        "model": MODEL_NAME,
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        content,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _fake_continuation_envelope(state: FakeProviderState) -> dict[str, object]:
    expected = state.expected_final
    if expected is None:
        raise RuntimeError("fake final identity is not bound")
    report = {
        "schemaVersion": "0.1.0",
        "reportId": expected["reportId"],
        "agentRunId": expected["agentRunId"],
        "projectId": expected["projectId"],
        "runId": expected["runId"],
        "failureType": expected["failureType"],
        "summary": (
            "The deterministic acceptance provider completed the resumed diagnosis "
            "after the approved tool step."
        ),
        "rootCauseHypotheses": [],
        "sufficientEvidence": False,
        "limitations": [
            "This deterministic provider is used only to verify HITL restart and "
            "checkpoint recovery."
        ],
        "recommendedChecks": [
            "Review the Java-owned tool evidence and the original failed TestReport."
        ],
        "traceId": expected["traceId"],
    }
    return {
        "id": "fake-hitl-continuation-2",
        "model": MODEL_NAME,
        "choices": [
            {
                "message": {
                    "content": json.dumps(
                        report,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _write_http_response(handler: BaseHTTPRequestHandler, status: int, body: object) -> None:
    encoded = _json_bytes(body)
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(encoded)))
    handler.end_headers()
    handler.wfile.write(encoded)


def _make_fake_handler(state: FakeProviderState) -> type[BaseHTTPRequestHandler]:
    class FakeDeepSeekHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            _write_http_response(self, 404, {"error": "not found"})

        def do_POST(self) -> None:
            if self.path != "/chat/completions":
                _write_http_response(self, 404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 2_000_000:
                    raise ValueError("invalid request length")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                messages = payload.get("messages") if isinstance(payload, dict) else None
                prompt = (
                    messages[0].get("content") if isinstance(messages, list) and messages else None
                )
                if not isinstance(prompt, str) or not prompt.strip():
                    raise ValueError("prompt is missing")
            except (
                UnicodeDecodeError,
                ValueError,
                json.JSONDecodeError,
                AttributeError,
                IndexError,
                TypeError,
            ):
                _write_http_response(self, 500, {"error": "invalid fake provider request"})
                return

            prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
            with state.lock:
                if not state.request_modes:
                    if INITIAL_MARKER not in prompt:
                        state.request_modes.append("UNEXPECTED")
                        state.request_hashes.append(prompt_hash)
                        _write_http_response(self, 500, {"error": "expected INITIAL model call"})
                        return
                    state.request_modes.append("INITIAL")
                    state.request_hashes.append(prompt_hash)
                    response = _fake_initial_envelope()
                elif state.request_modes == ["INITIAL"]:
                    expected = state.expected_final
                    identity_present = expected is not None and all(
                        str(value) in prompt for value in expected.values()
                    )
                    if CONTINUATION_MARKER not in prompt or not identity_present:
                        state.request_modes.append("UNEXPECTED")
                        state.request_hashes.append(prompt_hash)
                        _write_http_response(
                            self,
                            500,
                            {"error": "expected bound CONTINUATION model call"},
                        )
                        return
                    state.request_modes.append("CONTINUATION")
                    state.request_hashes.append(prompt_hash)
                    response = _fake_continuation_envelope(state)
                else:
                    _write_http_response(
                        self,
                        500,
                        {"error": "unexpected model call after continuation"},
                    )
                    return
            _write_http_response(self, 200, response)

        def log_message(self, format: str, *args: object) -> None:
            del format, args

    return FakeDeepSeekHandler


def _start_fake_server(state: FakeProviderState) -> tuple[ThreadingHTTPServer, Thread]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _make_fake_handler(state))
    thread = Thread(target=server.serve_forever, name="fake-deepseek", daemon=True)
    thread.start()
    return server, thread


def _request_json(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: object | None = None,
    timeout: float,
) -> HttpResponse:
    data = None if body is None else _json_bytes(body)
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    if body is not None:
        request_headers.setdefault("Content-Type", "application/json")
    request = urllib.request.Request(
        url,
        data=data,
        headers=request_headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            return HttpResponse(response.status, _decode_json(raw))
    except urllib.error.HTTPError as error:
        try:
            raw = error.read()
        finally:
            error.close()
        return HttpResponse(error.code, _decode_json(raw))
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        raise HttpTransportError from error


def _decode_json(raw: bytes) -> object | None:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def _required_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be a non-empty string")
    return value


def _java_preflight(
    args: argparse.Namespace, token: str, facts: dict[str, object]
) -> dict[str, object]:
    base_url = args.java_base_url.rstrip("/")
    try:
        health = _request_json(
            "GET",
            f"{base_url}/actuator/health",
            timeout=args.request_timeout,
        )
    except HttpTransportError as error:
        raise AcceptanceFailure(
            "java health",
            "JAVA_UNAVAILABLE",
            "Java health endpoint did not respond",
            facts=facts,
        ) from error
    facts["last_http_status"] = health.status
    if health.status != 200:
        code = "JAVA_AUTH_FAILED" if health.status in {401, 403} else "JAVA_UNAVAILABLE"
        raise AcceptanceFailure(
            "java health",
            code,
            "Java health endpoint did not return HTTP 200",
            facts=facts,
            http_status=health.status,
        )

    preflight_trace = f"acceptance-preflight-{os.urandom(16).hex()}"
    try:
        report_response = _request_json(
            "GET",
            f"{base_url}/api/v1/projects/{args.project_id}/test-runs/{args.run_id}/report",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Trace-Id": preflight_trace,
            },
            timeout=args.request_timeout,
        )
    except HttpTransportError as error:
        raise AcceptanceFailure(
            "java TestReport preflight",
            "JAVA_UNAVAILABLE",
            "Java TestReport endpoint did not respond",
            facts=facts,
        ) from error
    facts["last_http_status"] = report_response.status
    if report_response.status in {401, 403}:
        raise AcceptanceFailure(
            "java TestReport preflight",
            "JAVA_AUTH_FAILED",
            "Java rejected the supplied credential",
            facts=facts,
            http_status=report_response.status,
        )
    if report_response.status != 200:
        code = "JAVA_UNAVAILABLE" if report_response.status >= 500 else "FAILED_RUN_NOT_AVAILABLE"
        raise AcceptanceFailure(
            "java TestReport preflight",
            code,
            "The required Java TestReport was not readable",
            facts=facts,
            http_status=report_response.status,
        )
    try:
        envelope = report_response.data
        report = envelope["data"] if isinstance(envelope, dict) else None
        summary = report["summary"] if isinstance(report, dict) else None
        report_id = _required_string(report["reportId"], "reportId")
        status = _required_string(report["status"], "status")
        failure_type = _required_string(summary["failureType"], "failureType")
        if status not in FAILED_RUN_STATUSES:
            raise ValueError("run status is not an accepted failed status")
        if report["projectId"] != args.project_id or report["runId"] != args.run_id:
            raise ValueError("TestReport identity does not match the requested run")
    except (KeyError, TypeError, ValueError) as error:
        raise AcceptanceFailure(
            "java TestReport preflight",
            "FAILED_RUN_NOT_AVAILABLE",
            "Java TestReport did not match the required failed-run contract",
            facts=facts,
            http_status=report_response.status,
        ) from error
    return {
        "health": 200,
        "projectId": args.project_id,
        "runId": args.run_id,
        "reportId": report_id,
        "status": status,
        "failureType": failure_type,
    }


def _find_free_port(host: str) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _child_environment(
    *,
    java_base_url: str,
    fake_base_url: str,
    runtime_db: Path,
    memory_db: Path,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.pop("JAVA_APIOPS_TOKEN", None)
    environment.update(
        {
            "JAVA_APIOPS_BASE_URL": java_base_url,
            "DEEPSEEK_BASE_URL": fake_base_url,
            "DEEPSEEK_API_KEY": FAKE_API_KEY,
            "DEEPSEEK_MODEL": MODEL_NAME,
            "DEEPSEEK_TIMEOUT_SECONDS": "10",
            "RUNTIME_DB_PATH": str(runtime_db),
            "MEMORY_DB_PATH": str(memory_db),
            "LOG_LEVEL": "WARNING",
            "ENVIRONMENT": "acceptance",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return environment


def _start_python_process(
    *,
    host: str,
    port: int,
    project_dir: Path,
    environment: dict[str, str],
    log_path: Path,
) -> subprocess.Popen[bytes]:
    log_file = log_path.open("w", encoding="utf-8")
    try:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                host,
                "--port",
                str(port),
                "--log-level",
                "warning",
            ],
            cwd=project_dir,
            env=environment,
            stdout=log_file,
            stderr=subprocess.STDOUT,
        )
    finally:
        log_file.close()


def _wait_for_health(
    base_url: str,
    timeout: float,
    *,
    process: subprocess.Popen[bytes] | None = None,
) -> HttpResponse:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise AcceptanceFailure(
                "python process health",
                "FAKE_PROVIDER_NOT_CALLED",
                "Python child process exited before health became ready",
            )
        try:
            response = _request_json(
                "GET",
                f"{base_url.rstrip('/')}/health",
                timeout=min(5.0, timeout),
            )
            if (
                response.status == 200
                and isinstance(response.data, dict)
                and response.data.get("status") == "ok"
            ):
                return response
        except HttpTransportError:
            pass
        time.sleep(0.2)
    raise AcceptanceFailure(
        "python process health",
        "FAKE_PROVIDER_NOT_CALLED",
        "Python child process did not become healthy before the startup timeout",
    )


def _stop_process(process: subprocess.Popen[bytes] | None) -> bool:
    if process is None:
        return True
    if process.poll() is None:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            return False
    return process.poll() is not None


def _assert_old_health_unavailable(base_url: str, timeout: float, facts: dict[str, object]) -> None:
    deadline = time.monotonic() + min(5.0, timeout)
    while time.monotonic() < deadline:
        try:
            response = _request_json("GET", f"{base_url.rstrip('/')}/health", timeout=1.0)
        except HttpTransportError:
            return
        facts["last_http_status"] = response.status
        raise AcceptanceFailure(
            "old Python process stop",
            "RESUME_FAILED",
            "The old Python process still answered the health endpoint",
            facts=facts,
            http_status=response.status,
        )
    raise AcceptanceFailure(
        "old Python process stop",
        "RESUME_FAILED",
        "The old Python health endpoint did not become unavailable",
        facts=facts,
    )


def _persistence_failure(
    field: str,
    expected: object,
    observed: object,
    message: str,
    *,
    step: str = "SQLite DiagnosisRun evidence",
    code: str = "APPROVAL_PAYLOAD_CHANGED",
) -> AcceptanceFailure:
    return AcceptanceFailure(
        step,
        code,
        message,
        facts={
            "persistence_blocker": True,
            "persistence_field": field,
            "persistence_expected": expected,
            "persistence_observed": observed,
        },
    )


def _read_runtime_evidence(
    runtime_db: Path,
    *,
    agent_run_id: str,
    workflow_id: str,
    expected_status: str,
    expected_approval: dict[str, object] | None,
    facts: dict[str, object] | None = None,
) -> tuple[bool, int, dict[str, object]]:
    try:
        database_uri = f"{runtime_db.as_uri()}?mode=ro"
        connection = sqlite3.connect(database_uri, uri=True)
    except (OSError, sqlite3.Error) as error:
        raise AcceptanceFailure(
            "SQLite evidence",
            "DIAGNOSIS_ROW_MISSING",
            "Runtime SQLite could not be opened read-only",
        ) from error
    try:
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }
        if not {"diagnosis_run", "checkpoints", "writes"}.issubset(tables):
            raise _persistence_failure(
                "sqlite.tables",
                ["diagnosis_run", "checkpoints", "writes"],
                sorted(tables),
                "Runtime SQLite is missing a required persistence table",
                step="SQLite evidence",
                code="CHECKPOINT_ROW_MISSING",
            )
        rows = connection.execute(
            "SELECT workflow_id, payload_json FROM diagnosis_run WHERE agent_run_id = ?",
            (agent_run_id,),
        ).fetchall()
        if len(rows) != 1:
            raise _persistence_failure(
                "diagnosis_run.row",
                "exactly one row",
                len(rows),
                "Runtime SQLite did not contain exactly one matching DiagnosisRun",
                step="SQLite DiagnosisRun evidence",
                code="DIAGNOSIS_ROW_MISSING",
            )
        if facts is not None:
            facts["diagnosis_row_exists"] = True
        persisted_workflow_id = rows[0][0]
        if persisted_workflow_id != workflow_id:
            raise _persistence_failure(
                "diagnosis_run.workflow_id",
                workflow_id,
                persisted_workflow_id,
                "DiagnosisRun workflow_id did not match the Start workflowId",
            )
        try:
            payload = json.loads(rows[0][1])
        except (TypeError, json.JSONDecodeError) as error:
            raise _persistence_failure(
                "diagnosis_run.payload_json",
                "valid JSON object",
                "invalid JSON",
                "DiagnosisRun payload was not valid JSON",
                code="DIAGNOSIS_ROW_MISSING",
            ) from error
        if not isinstance(payload, dict):
            raise _persistence_failure(
                "diagnosis_run.payload_json",
                "object",
                type(payload).__name__,
                "DiagnosisRun payload was not a JSON object",
                code="DIAGNOSIS_ROW_MISSING",
            )
        persisted_risk = payload.get("approval_risk")
        if facts is not None:
            facts["persisted_approval_risk"] = persisted_risk
        if payload.get("agent_run_id") != agent_run_id:
            raise _persistence_failure(
                "diagnosis_run.payload.agent_run_id",
                agent_run_id,
                payload.get("agent_run_id"),
                "Persisted agentRunId did not match the Start agentRunId",
            )
        if payload.get("status") != expected_status:
            raise _persistence_failure(
                "diagnosis_run.payload.status",
                expected_status,
                payload.get("status"),
                "Persisted DiagnosisRun status did not match the pending status",
            )
        persisted_request = payload.get("approval_request")
        if not isinstance(persisted_request, dict):
            raise _persistence_failure(
                "diagnosis_run.payload.approval_request",
                "object",
                None if persisted_request is None else type(persisted_request).__name__,
                "Persisted ApprovalRequest was missing or not an object",
                step="SQLite approval_request evidence",
            )
        if expected_approval is not None:
            scope = expected_approval["scope"]
            expected_request = {
                "workflow_id": scope["workflowId"],
                "project_id": scope["projectId"],
                "intent_id": scope["toolIntentId"],
                "tool_name": expected_approval["toolName"],
                "arguments_fingerprint": scope["argumentsFingerprint"],
            }
            for field, expected in expected_request.items():
                observed = persisted_request.get(field)
                if observed != expected:
                    raise _persistence_failure(
                        f"diagnosis_run.payload.approval_request.{field}",
                        expected,
                        observed,
                        (
                            f"Persisted ApprovalRequest {field} did not match the Start "
                            "approval request"
                        ),
                        step="SQLite approval_request evidence",
                    )
            persisted_arguments = payload.get("approval_arguments")
            if not isinstance(persisted_arguments, dict):
                raise _persistence_failure(
                    "diagnosis_run.payload.approval_arguments",
                    "object",
                    None if persisted_arguments is None else type(persisted_arguments).__name__,
                    "Persisted approval_arguments was missing or not an object",
                    step="SQLite approval_arguments evidence",
                )
            expected_arguments = expected_approval["arguments"]
            for field in ("query", "topK"):
                expected = expected_arguments[field]
                observed = persisted_arguments.get(field)
                if observed != expected:
                    raise _persistence_failure(
                        f"diagnosis_run.payload.approval_arguments.{field}",
                        expected,
                        observed,
                        f"Persisted approval_arguments.{field} did not match the Start arguments",
                        step="SQLite approval_arguments evidence",
                    )
        checkpoint_count = connection.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?",
            (workflow_id,),
        ).fetchone()[0]
        if facts is not None:
            facts["checkpoint_count"] = checkpoint_count
        if not isinstance(checkpoint_count, int) or checkpoint_count <= 0:
            raise _persistence_failure(
                "checkpoints.thread_id",
                f"count > 0 for {workflow_id}",
                checkpoint_count,
                "Runtime SQLite did not contain a checkpoint for workflow_id",
                step="SQLite checkpoint evidence",
                code="CHECKPOINT_ROW_MISSING",
            )
        return True, checkpoint_count, {"approval_risk": persisted_risk}
    finally:
        connection.close()


def _read_final_runtime_status(
    runtime_db: Path,
    *,
    agent_run_id: str,
    workflow_id: str,
    minimum_checkpoint_count: int,
) -> tuple[str, int]:
    try:
        database_uri = f"{runtime_db.as_uri()}?mode=ro"
        connection = sqlite3.connect(database_uri, uri=True)
    except (OSError, sqlite3.Error) as error:
        raise AcceptanceFailure(
            "final SQLite evidence",
            "DIAGNOSIS_ROW_MISSING",
            "Runtime SQLite could not be reopened read-only",
        ) from error
    try:
        row = connection.execute(
            "SELECT workflow_id, payload_json FROM diagnosis_run WHERE agent_run_id = ?",
            (agent_run_id,),
        ).fetchone()
        if row is None or row[0] != workflow_id:
            raise AcceptanceFailure(
                "final SQLite evidence",
                "DIAGNOSIS_ROW_MISSING",
                "Final DiagnosisRun row was missing or changed workflow identity",
            )
        payload = json.loads(row[1])
        status = payload.get("status") if isinstance(payload, dict) else None
        checkpoint_count = connection.execute(
            "SELECT COUNT(*) FROM checkpoints WHERE thread_id = ?",
            (workflow_id,),
        ).fetchone()[0]
        if status != "COMPLETED":
            raise AcceptanceFailure(
                "final SQLite evidence",
                "FINAL_STATUS_NOT_COMPLETED",
                "Final DiagnosisRun row was not COMPLETED",
            )
        if not isinstance(checkpoint_count, int) or checkpoint_count < minimum_checkpoint_count:
            raise AcceptanceFailure(
                "final SQLite evidence",
                "CHECKPOINT_ROW_MISSING",
                "Final checkpoint count decreased unexpectedly",
            )
        return status, checkpoint_count
    except json.JSONDecodeError as error:
        raise AcceptanceFailure(
            "final SQLite evidence",
            "DIAGNOSIS_ROW_MISSING",
            "Final DiagnosisRun payload was not valid JSON",
        ) from error
    finally:
        connection.close()


def _scan_java_token(paths: tuple[Path, ...], token: str) -> bool:
    marker = token.encode("utf-8")
    for path in paths:
        for candidate in (path, Path(f"{path}-wal"), Path(f"{path}-shm")):
            if candidate.exists() and marker in candidate.read_bytes():
                return True
    return False


def _approval_snapshot(response: dict[str, object]) -> dict[str, object]:
    approval = response.get("approvalRequest")
    if not isinstance(approval, dict):
        raise ValueError("approvalRequest is missing")
    scope = approval.get("scope")
    arguments = approval.get("arguments")
    if not isinstance(scope, dict) or not isinstance(arguments, dict):
        raise ValueError("approvalRequest scope or arguments is missing")
    fingerprint = scope.get("argumentsFingerprint")
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise ValueError("approval fingerprint is invalid")
    if (
        approval.get("toolName") != "rag.search"
        or approval.get("risk") != "REQUIRE_APPROVAL"
        or arguments.get("query") != RAG_QUERY
        or arguments.get("topK") != RAG_TOP_K
        or not scope.get("workflowId")
        or not scope.get("projectId")
        or not scope.get("toolIntentId")
    ):
        raise ValueError("approval request does not match the frozen rag.search intent")
    return {
        "toolName": approval["toolName"],
        "risk": approval["risk"],
        "arguments": {"query": arguments["query"], "topK": arguments["topK"]},
        "scope": {
            "workflowId": scope["workflowId"],
            "projectId": scope["projectId"],
            "toolIntentId": scope["toolIntentId"],
            "argumentsFingerprint": fingerprint,
        },
    }


def _assert_pending_response(
    response: object,
    *,
    expected: dict[str, object],
    expected_approval: dict[str, object],
) -> None:
    if not isinstance(response, dict):
        raise ValueError("Diagnosis response is not an object")
    for key in ("agentRunId", "workflowId", "traceId", "projectId", "runId", "reportId", "model"):
        if response.get(key) != expected[key]:
            raise ValueError(f"Diagnosis identity changed: {key}")
    if response.get("status") != "APPROVAL_REQUIRED":
        raise ValueError("Diagnosis response is not APPROVAL_REQUIRED")
    if _approval_snapshot(response) != expected_approval:
        raise ValueError("approval payload changed")


def _assert_identity_unchanged(response: object, expected: dict[str, object]) -> None:
    if not isinstance(response, dict):
        raise ValueError("Diagnosis response is not an object")
    for key in ("agentRunId", "workflowId", "traceId", "projectId", "runId", "reportId"):
        if response.get(key) != expected[key]:
            raise ValueError(f"Diagnosis identity changed: {key}")


def _real_acceptance(args: argparse.Namespace, token: str) -> dict[str, object]:
    facts: dict[str, object] = {
        "pid_a": None,
        "pid_b": None,
        "first_stopped": False,
        "second_started": False,
        "provider_modes": [],
        "diagnosis_row_exists": None,
        "checkpoint_count": None,
        "recovery_get_status": None,
        "resume_status": None,
        "tool_call_id_present": False,
        "last_http_status": None,
    }
    process_a: subprocess.Popen[bytes] | None = None
    process_b: subprocess.Popen[bytes] | None = None
    fake_server: ThreadingHTTPServer | None = None
    fake_thread: Thread | None = None
    temporary_directory: tempfile.TemporaryDirectory[str] | None = None
    failure: AcceptanceFailure | None = None
    try:
        java = _java_preflight(args, token, facts)
        temporary_directory = tempfile.TemporaryDirectory()
        temporary_root = Path(temporary_directory.name)
        runtime_db = temporary_root / "agentlab-runtime.sqlite3"
        memory_db = temporary_root / "historical-memory.sqlite3"
        log_a = temporary_root / "python-a.log"
        log_b = temporary_root / "python-b.log"
        state = FakeProviderState(Lock(), [], [], None)
        fake_server, fake_thread = _start_fake_server(state)
        fake_base_url = f"http://127.0.0.1:{fake_server.server_address[1]}"
        python_port = _find_free_port(args.python_host)
        python_base_url = f"http://{args.python_host}:{python_port}"
        child_env = _child_environment(
            java_base_url=args.java_base_url,
            fake_base_url=fake_base_url,
            runtime_db=runtime_db,
            memory_db=memory_db,
        )
        project_dir = Path(__file__).resolve().parents[1]

        process_a = _start_python_process(
            host=args.python_host,
            port=python_port,
            project_dir=project_dir,
            environment=child_env,
            log_path=log_a,
        )
        facts["pid_a"] = process_a.pid
        _wait_for_health(python_base_url, args.startup_timeout, process=process_a)
        start_trace_id = f"diagnosis-hitl-restart-{os.urandom(16).hex()}"
        try:
            start_response = _request_json(
                "POST",
                f"{python_base_url}/api/v1/diagnosis/runs",
                headers={
                    "Authorization": f"Bearer {token}",
                    "X-Trace-Id": start_trace_id,
                },
                body={"projectId": args.project_id, "runId": args.run_id},
                timeout=args.request_timeout,
            )
        except HttpTransportError as error:
            raise AcceptanceFailure(
                "diagnosis start",
                "APPROVAL_NOT_TRIGGERED",
                "Diagnosis start did not return an HTTP response",
                facts=facts,
            ) from error
        facts["last_http_status"] = start_response.status
        modes, _ = state.snapshot()
        facts["provider_modes"] = modes
        if start_response.status != 200:
            code = "FAKE_PROVIDER_NOT_CALLED" if not modes else "APPROVAL_NOT_TRIGGERED"
            if modes and modes[-1] == "UNEXPECTED":
                code = "UNEXPECTED_MODEL_MODE"
            raise AcceptanceFailure(
                "diagnosis start",
                code,
                "Diagnosis start did not return HTTP 200 with an approval checkpoint",
                facts=facts,
                http_status=start_response.status,
            )
        if not isinstance(start_response.data, dict):
            raise AcceptanceFailure(
                "diagnosis start",
                "APPROVAL_NOT_TRIGGERED",
                "Diagnosis start response was not JSON",
                facts=facts,
                http_status=start_response.status,
            )
        start = start_response.data
        try:
            if (
                start.get("status") != "APPROVAL_REQUIRED"
                or start.get("runtime") != "PYTHON_AGENTLAB"
                or start.get("implementation") != "REAL"
                or start.get("provider") != "DeepSeek"
                or start.get("model") != MODEL_NAME
                or start.get("projectId") != args.project_id
                or start.get("runId") != args.run_id
                or start.get("traceId") != start_trace_id
                or not start.get("agentRunId")
                or not start.get("workflowId")
                or not start.get("reportId")
            ):
                raise ValueError("start identity or status assertion failed")
            test_report = start.get("testReport")
            summary = test_report.get("summary") if isinstance(test_report, dict) else None
            if (
                not isinstance(summary, dict)
                or summary.get("failureType") != java["failureType"]
                or start.get("reportId") != java["reportId"]
            ):
                raise ValueError("start TestReport identity or failureType changed")
            approval = _approval_snapshot(start)
            if start.get("toolCallId") is not None:
                raise ValueError("toolCallId must be null before approval")
        except (KeyError, TypeError, ValueError) as error:
            raise AcceptanceFailure(
                "diagnosis start assertions",
                "APPROVAL_NOT_TRIGGERED",
                "Diagnosis start did not produce the frozen APPROVAL_REQUIRED contract",
                facts=facts,
                http_status=start_response.status,
            ) from error

        final_identity = {
            "project_id": start["projectId"],
            "run_id": start["runId"],
            "report_id": start["reportId"],
            "agent_run_id": start["agentRunId"],
            "trace_id": start["traceId"],
            "failure_type": start["testReport"]["summary"]["failureType"],
        }
        state.bind_final_identity(**final_identity)
        facts["provider_modes"] = state.snapshot()[0]
        diagnosis_found, checkpoint_count, persisted_evidence = _read_runtime_evidence(
            runtime_db,
            agent_run_id=start["agentRunId"],
            workflow_id=start["workflowId"],
            expected_status="APPROVAL_REQUIRED",
            expected_approval=approval,
            facts=facts,
        )
        facts["diagnosis_row_exists"] = diagnosis_found
        facts["checkpoint_count"] = checkpoint_count
        facts["persisted_approval_risk"] = persisted_evidence["approval_risk"]

        facts["first_stopped"] = _stop_process(process_a)
        if not facts["first_stopped"]:
            raise AcceptanceFailure(
                "process A stop",
                "RESUME_FAILED",
                "Python process A did not stop after terminate and kill",
                facts=facts,
            )
        _assert_old_health_unavailable(python_base_url, args.request_timeout, facts)
        process_b = _start_python_process(
            host=args.python_host,
            port=python_port,
            project_dir=project_dir,
            environment=child_env,
            log_path=log_b,
        )
        facts["pid_b"] = process_b.pid
        if facts["pid_b"] == facts["pid_a"]:
            raise AcceptanceFailure(
                "process B identity",
                "RESUME_FAILED",
                "Python process B reused process A identity",
                facts=facts,
            )
        _wait_for_health(python_base_url, args.startup_timeout, process=process_b)
        facts["second_started"] = True
        try:
            recovered_response = _request_json(
                "GET",
                f"{python_base_url}/api/v1/diagnosis/runs/{start['agentRunId']}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=args.request_timeout,
            )
        except HttpTransportError as error:
            raise AcceptanceFailure(
                "restart recovery GET",
                "RECOVERY_GET_404",
                "Recovery GET did not return an HTTP response",
                facts=facts,
            ) from error
        facts["last_http_status"] = recovered_response.status
        facts["recovery_get_status"] = recovered_response.status
        if recovered_response.status != 200:
            raise AcceptanceFailure(
                "restart recovery GET",
                "RECOVERY_GET_404" if recovered_response.status == 404 else "RESUME_FAILED",
                "Recovery GET did not return HTTP 200",
                facts=facts,
                http_status=recovered_response.status,
            )
        try:
            _assert_pending_response(
                recovered_response.data,
                expected=start,
                expected_approval=approval,
            )
        except (KeyError, TypeError, ValueError) as error:
            raise AcceptanceFailure(
                "restart recovery assertions",
                "RECOVERY_IDENTITY_CHANGED"
                if "identity" in str(error)
                else "APPROVAL_PAYLOAD_CHANGED",
                "Recovery GET changed the persisted approval identity or payload",
                facts=facts,
                http_status=recovered_response.status,
            ) from error
        facts["provider_modes"] = state.snapshot()[0]
        if facts["provider_modes"] != ["INITIAL"]:
            raise AcceptanceFailure(
                "restart recovery provider sequence",
                "UNEXPECTED_MODEL_CALL_COUNT",
                "Recovery GET triggered an unexpected model call",
                facts=facts,
            )

        try:
            resume_response = _request_json(
                "POST",
                f"{python_base_url}/api/v1/diagnosis/runs/{start['agentRunId']}/resume",
                headers={"Authorization": f"Bearer {token}"},
                body={"decision": "APPROVE"},
                timeout=args.request_timeout,
            )
        except HttpTransportError as error:
            raise AcceptanceFailure(
                "approval resume",
                "RESUME_FAILED",
                "Approval resume did not return an HTTP response",
                facts=facts,
            ) from error
        facts["last_http_status"] = resume_response.status
        facts["resume_status"] = resume_response.status
        facts["provider_modes"] = state.snapshot()[0]
        if resume_response.status != 200:
            code = (
                "WORKFLOW_RESTARTED_FROM_INITIAL"
                if facts["provider_modes"] == ["INITIAL", "INITIAL"]
                else "RESUME_FAILED"
            )
            if facts["provider_modes"] == ["INITIAL"]:
                code = "JAVA_RAG_RUNTIME_BLOCKED"
            raise AcceptanceFailure(
                "approval resume",
                code,
                "Approval resume did not return HTTP 200",
                facts=facts,
                http_status=resume_response.status,
            )
        if not isinstance(resume_response.data, dict):
            raise AcceptanceFailure(
                "approval resume",
                "RESUME_FAILED",
                "Approval resume response was not JSON",
                facts=facts,
                http_status=resume_response.status,
            )
        final_response = resume_response.data
        try:
            _assert_identity_unchanged(final_response, start)
            if final_response.get("status") != "COMPLETED":
                raise ValueError("final status is not COMPLETED")
            if final_response.get("approvalRequest") is not None:
                raise ValueError("approvalRequest was not cleared")
            if not final_response.get("toolIntentId"):
                raise ValueError("toolIntentId is missing")
            tool_call_id = final_response.get("toolCallId")
            if not isinstance(tool_call_id, str) or not tool_call_id:
                raise ValueError("Java toolCallId is missing")
            report = final_response.get("report")
            if not isinstance(report, dict) or report.get("reportId") != start["reportId"]:
                raise ValueError("final DiagnosisReport is missing or changed identity")
        except (KeyError, TypeError, ValueError) as error:
            facts["tool_call_id_present"] = bool(final_response.get("toolCallId"))
            code = (
                "JAVA_RAG_RUNTIME_BLOCKED"
                if not facts["tool_call_id_present"]
                else "FINAL_STATUS_NOT_COMPLETED"
            )
            raise AcceptanceFailure(
                "resume result assertions",
                code,
                "Approved resume did not produce the required completed Java tool result",
                facts=facts,
                http_status=resume_response.status,
            ) from error
        facts["tool_call_id_present"] = True
        facts["provider_modes"] = state.snapshot()[0]
        if facts["provider_modes"] == ["INITIAL", "INITIAL"]:
            raise AcceptanceFailure(
                "resume provider sequence",
                "WORKFLOW_RESTARTED_FROM_INITIAL",
                "Resume restarted the workflow from INITIAL",
                facts=facts,
            )
        if facts["provider_modes"] != ["INITIAL", "CONTINUATION"]:
            raise AcceptanceFailure(
                "resume provider sequence",
                "UNEXPECTED_MODEL_CALL_COUNT",
                "Provider call sequence was not exactly INITIAL then CONTINUATION",
                facts=facts,
            )
        final_db_status, final_checkpoint_count = _read_final_runtime_status(
            runtime_db,
            agent_run_id=start["agentRunId"],
            workflow_id=start["workflowId"],
            minimum_checkpoint_count=checkpoint_count,
        )
        facts["final_db_status"] = final_db_status
        facts["final_checkpoint_count"] = final_checkpoint_count
        try:
            final_get_response = _request_json(
                "GET",
                f"{python_base_url}/api/v1/diagnosis/runs/{start['agentRunId']}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=args.request_timeout,
            )
        except HttpTransportError as error:
            raise AcceptanceFailure(
                "final diagnosis GET",
                "RESUME_FAILED",
                "Final Diagnosis GET did not return an HTTP response",
                facts=facts,
            ) from error
        facts["last_http_status"] = final_get_response.status
        if final_get_response.status != 200 or not isinstance(final_get_response.data, dict):
            raise AcceptanceFailure(
                "final diagnosis GET",
                "RESUME_FAILED",
                "Final Diagnosis GET did not return HTTP 200 JSON",
                facts=facts,
                http_status=final_get_response.status,
            )
        if (
            final_get_response.data.get("status") != "COMPLETED"
            or final_get_response.data.get("toolCallId") != final_response["toolCallId"]
            or final_get_response.data.get("workflowId") != start["workflowId"]
            or final_get_response.data.get("reportId") != start["reportId"]
        ):
            raise AcceptanceFailure(
                "final diagnosis GET assertions",
                "RESUME_FAILED",
                "Final Diagnosis GET changed completed identity or toolCallId",
                facts=facts,
                http_status=final_get_response.status,
            )
        if not _stop_process(process_b):
            raise AcceptanceFailure(
                "process B stop",
                "RESUME_FAILED",
                "Python process B did not stop after final evidence",
                facts=facts,
            )
        if _scan_java_token((runtime_db, memory_db), token):
            raise AcceptanceFailure(
                "secret scan",
                "APPROVAL_PAYLOAD_CHANGED",
                "Java token was found in a runtime or historical-memory database",
                facts=facts,
            )
        return {
            "status": "PASS",
            "java": java,
            "pythonProcess": {
                "firstPid": facts["pid_a"],
                "secondPid": facts["pid_b"],
                "firstStopped": True,
                "secondStarted": True,
            },
            "pending": {
                "status": "APPROVAL_REQUIRED",
                "agentRunId": start["agentRunId"],
                "workflowId": start["workflowId"],
                "traceId": start["traceId"],
                "toolName": approval["toolName"],
                "risk": approval["risk"],
                "topK": RAG_TOP_K,
                "argumentsFingerprint": approval["scope"]["argumentsFingerprint"],
            },
            "persistence": {
                "diagnosisRunFoundBeforeRestart": True,
                "checkpointCountBeforeRestart": checkpoint_count,
                "recoveredAfterRestart": True,
                "sameAgentRunId": recovered_response.data["agentRunId"] == start["agentRunId"],
                "sameWorkflowId": recovered_response.data["workflowId"] == start["workflowId"],
                "sameApprovalFingerprint": _approval_snapshot(recovered_response.data)["scope"][
                    "argumentsFingerprint"
                ]
                == approval["scope"]["argumentsFingerprint"],
                "persistedApprovalRisk": facts["persisted_approval_risk"],
            },
            "resume": {
                "decision": "APPROVE",
                "status": final_response["status"],
                "toolCallIdPresent": True,
                "toolCallId": final_response["toolCallId"],
                "approvalCleared": final_response["approvalRequest"] is None,
            },
            "provider": {
                "modes": facts["provider_modes"],
                "requestCount": len(facts["provider_modes"]),
            },
            "secrets": {"javaTokenPrinted": False, "javaTokenPersisted": False},
        }
    except AcceptanceFailure as error:
        failure = error
        raise
    except Exception as error:
        failure = AcceptanceFailure(
            "acceptance harness",
            "RESUME_FAILED",
            "Unexpected acceptance harness failure",
            facts=facts,
        )
        raise failure from error
    finally:
        cleanup_a = _stop_process(process_a)
        cleanup_b = _stop_process(process_b)
        if failure is None and (not cleanup_a or not cleanup_b):
            failure = AcceptanceFailure(
                "finally cleanup",
                "RESUME_FAILED",
                "A Python child process remained alive during cleanup",
                facts=facts,
            )
        if fake_server is not None:
            fake_server.shutdown()
            fake_server.server_close()
        if fake_thread is not None:
            fake_thread.join(timeout=10)
        if failure is not None:
            failure.facts.update(facts)
            if temporary_directory is not None:
                failure.log_tail_a = _log_tail(Path(temporary_directory.name) / "python-a.log")
                failure.log_tail_b = _log_tail(Path(temporary_directory.name) / "python-b.log")
        if temporary_directory is not None:
            temporary_directory.cleanup()


def _log_tail(path: Path) -> str:
    if not path.exists():
        return "<log unavailable>"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()[-80:]
    except OSError:
        return "<log unavailable>"
    return "\n".join(lines) if lines else "<log empty>"


def _self_test_request(url: str, prompt: str) -> HttpResponse:
    return _request_json(
        "POST",
        url,
        headers={"Authorization": f"Bearer {FAKE_API_KEY}"},
        body={
            "model": MODEL_NAME,
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"},
        },
        timeout=5.0,
    )


def _self_test() -> None:
    state = FakeProviderState(Lock(), [], [], None)
    server: ThreadingHTTPServer | None = None
    thread: Thread | None = None
    try:
        server, thread = _start_fake_server(state)
        url = f"http://127.0.0.1:{server.server_address[1]}/chat/completions"
        first = _self_test_request(url, INITIAL_MARKER)
        if first.status != 200 or not isinstance(first.data, dict):
            raise ValueError("fake first response was not HTTP 200 JSON")
        content = first.data["choices"][0]["message"]["content"]
        tool_intent = json.loads(content)
        if tool_intent != {
            "tool_name": "rag.search",
            "arguments": {"query": RAG_QUERY, "topK": RAG_TOP_K},
        }:
            raise ValueError("fake first response did not contain rag.search topK=11")
        if state.snapshot()[0] != ["INITIAL"]:
            raise ValueError("fake first mode was not INITIAL")
        state.bind_final_identity(
            project_id=41,
            run_id=4520,
            report_id="report:self-test",
            agent_run_id="agent_run:self-test",
            trace_id="trace:self-test",
            failure_type="ASSERTION_MISMATCH",
        )
        second_prompt = (
            f"{CONTINUATION_MARKER} projectId=41 runId=4520 reportId=report:self-test "
            "agentRunId=agent_run:self-test traceId=trace:self-test "
            "failureType=ASSERTION_MISMATCH"
        )
        second = _self_test_request(url, second_prompt)
        if second.status != 200 or not isinstance(second.data, dict):
            raise ValueError("fake continuation response was not HTTP 200 JSON")
        report = json.loads(second.data["choices"][0]["message"]["content"])
        required = {
            "schemaVersion",
            "reportId",
            "agentRunId",
            "projectId",
            "runId",
            "failureType",
            "summary",
            "rootCauseHypotheses",
            "sufficientEvidence",
            "limitations",
            "recommendedChecks",
            "traceId",
        }
        if (
            set(report) != required
            or report["reportId"] != "report:self-test"
            or report["agentRunId"] != "agent_run:self-test"
            or report["projectId"] != 41
            or report["runId"] != 4520
            or report["traceId"] != "trace:self-test"
            or not isinstance(report["rootCauseHypotheses"], list)
            or not isinstance(report["sufficientEvidence"], bool)
        ):
            raise ValueError("fake continuation response was not a DiagnosisReport shape")
        third = _self_test_request(url, f"{CONTINUATION_MARKER} unexpected third request")
        if third.status != 500:
            raise ValueError("fake third model request was not rejected")
        modes, hashes = state.snapshot()
        if modes != ["INITIAL", "CONTINUATION"] or len(hashes) != 2:
            raise ValueError("fake provider state did not retain the exact two-call sequence")
        field_names = set(FakeProviderState.__dataclass_fields__)
        if field_names != {"lock", "request_modes", "request_hashes", "expected_final"}:
            raise ValueError("fake provider state has an unexpected field")
        if any("prompt" in name.lower() or "token" in name.lower() for name in field_names):
            raise ValueError("fake provider state contains a prohibited secret field")
        if state.expected_final is None or set(state.expected_final) != {
            "projectId",
            "runId",
            "reportId",
            "agentRunId",
            "traceId",
            "failureType",
        }:
            raise ValueError("fake provider retained unexpected final state")
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()
        if thread is not None:
            thread.join(timeout=10)


def _print_failure(error: AcceptanceFailure) -> None:
    facts = error.facts
    print(f"FAILED_STEP: {error.step}", file=sys.stderr)
    print(f"ERROR_CODE: {error.code}", file=sys.stderr)
    print(f"HTTP_STATUS: {error.http_status or facts.get('last_http_status')}", file=sys.stderr)
    print(f"PID A: {facts.get('pid_a')}", file=sys.stderr)
    print(f"PID B: {facts.get('pid_b')}", file=sys.stderr)
    print(
        f"PROVIDER_MODES: {json.dumps(facts.get('provider_modes', []), ensure_ascii=False)}",
        file=sys.stderr,
    )
    print(f"DIAGNOSIS_ROW_EXISTS: {facts.get('diagnosis_row_exists')}", file=sys.stderr)
    print(f"CHECKPOINT_ROW_COUNT: {facts.get('checkpoint_count')}", file=sys.stderr)
    print(f"RECOVERY_GET_STATUS: {facts.get('recovery_get_status')}", file=sys.stderr)
    print(f"RESUME_STATUS: {facts.get('resume_status')}", file=sys.stderr)
    print(f"TOOL_CALL_ID_PRESENT: {facts.get('tool_call_id_present')}", file=sys.stderr)
    print(f"PERSISTENCE_BLOCKER: {facts.get('persistence_blocker')}", file=sys.stderr)
    print(f"PERSISTENCE_FIELD: {facts.get('persistence_field')}", file=sys.stderr)
    print(
        "PERSISTENCE_EXPECTED: "
        + json.dumps(facts.get("persistence_expected"), ensure_ascii=False),
        file=sys.stderr,
    )
    print(
        "PERSISTENCE_OBSERVED: "
        + json.dumps(facts.get("persistence_observed"), ensure_ascii=False),
        file=sys.stderr,
    )
    print(
        "PERSISTED_APPROVAL_RISK: "
        + json.dumps(facts.get("persisted_approval_risk"), ensure_ascii=False),
        file=sys.stderr,
    )
    print("python-a.log tail:", file=sys.stderr)
    print(_redact_log(error.log_tail_a), file=sys.stderr)
    print("python-b.log tail:", file=sys.stderr)
    print(_redact_log(error.log_tail_b), file=sys.stderr)


def _redact_log(value: str) -> str:
    if not value:
        return "<log unavailable>"
    lines: list[str] = []
    for line in value.splitlines():
        lowered = line.lower()
        if any(
            marker in lowered
            for marker in ("prompt", "authorization", "api_key", "apikey", "bearer")
        ):
            lines.append("<redacted log line>")
        else:
            lines.append(line)
    return "\n".join(lines)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", type=int)
    parser.add_argument("--run-id", type=int)
    parser.add_argument(
        "--java-base-url",
        default=os.environ.get("JAVA_APIOPS_BASE_URL", "http://127.0.0.1:8080"),
    )
    parser.add_argument("--python-host", default="127.0.0.1")
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    parser.add_argument("--request-timeout", type=float, default=90.0)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.startup_timeout <= 0 or args.request_timeout <= 0:
        parser.error("timeouts must be greater than zero")
    if not args.self_test and (args.project_id is None or args.run_id is None):
        parser.error("--project-id and --run-id are required unless --self-test is used")
    if not args.self_test and (args.project_id < 1 or args.run_id < 1):
        parser.error("project and run ids must be positive")
    return args


def main() -> int:
    args = _parse_args()
    if args.self_test:
        try:
            _self_test()
        except Exception as error:
            failure = AcceptanceFailure(
                "self-test", "UNEXPECTED_MODEL_MODE", "Fake provider self-test failed"
            )
            failure.log_tail_a = str(error)
            _print_failure(failure)
            return 1
        print(json.dumps({"status": "SELF_TEST_PASS"}, ensure_ascii=False))
        return 0
    token = os.environ.get("JAVA_APIOPS_TOKEN")
    if not token or not token.strip():
        print("JAVA_APIOPS_TOKEN is required", file=sys.stderr)
        return 2
    try:
        evidence = _real_acceptance(args, token)
    except AcceptanceFailure as error:
        _print_failure(error)
        return 1
    print(json.dumps(evidence, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
