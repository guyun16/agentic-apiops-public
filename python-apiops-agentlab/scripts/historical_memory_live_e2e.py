"""Cross-process Historical Memory acceptance probes."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from uuid import uuid4

import httpx

from app.clients.java_apiops import JavaApiOpsClient, JavaApiOpsError
from app.memory.fingerprint import build_failure_fingerprint, normalize_identity
from app.schemas.runner import TestReport
from app.workflows.diagnosis_memory_query import build_memory_symptoms

PROJECT_ID = 42
RUN_ID = 701
EXPECTED_API_ID = "orders-api"
EXPECTED_REPORT_ID = "report:701"
EXPECTED_ROOT_CAUSE = "The endpoint returned an unexpected server response."
EXPECTED_CHECK = "Inspect the upstream service health."
MODEL = "controlled-memory-e2e"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _prompt_value(prompt: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}=([^\s,\r\n]+)", prompt)
    if match is None:
        raise ValueError(f"controlled provider could not read {name} from the prompt")
    return match.group(1).rstrip(".,")


class _ControlledProvider:
    """A local HTTP provider that records counters, never complete prompts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.calls = 0
        self.initial_calls = 0
        self.refinement_calls = 0

    def completion(self, prompt: str) -> dict[str, object]:
        project_id = int(_prompt_value(prompt, "projectId"))
        run_id = int(_prompt_value(prompt, "runId"))
        report_id = _prompt_value(prompt, "reportId")
        agent_run_id = _prompt_value(prompt, "agentRunId")
        trace_id = _prompt_value(prompt, "traceId")
        refinement = "bounded final diagnosis refinement" in prompt.lower()
        memory_id = None
        if refinement:
            memory_ids = re.findall(r"\bmemory_[0-9a-f]{64}\b", prompt)
            if len(memory_ids) != 1:
                raise ValueError("controlled refinement prompt must contain one memory id")
            memory_id = memory_ids[0]

        with self._lock:
            self.calls += 1
            if refinement:
                self.refinement_calls += 1
            else:
                self.initial_calls += 1

        report = {
            "schemaVersion": "0.1.0",
            "reportId": report_id,
            "agentRunId": agent_run_id,
            "projectId": project_id,
            "runId": run_id,
            "failureType": "ASSERTION_MISMATCH",
            "summary": "The status assertion observed HTTP 500 instead of HTTP 200.",
            "rootCauseHypotheses": [
                {
                    "statement": EXPECTED_ROOT_CAUSE,
                    "confidence": "MEDIUM",
                    "evidenceRefs": [{"itemId": memory_id or report_id}],
                }
            ],
            "sufficientEvidence": True,
            "limitations": [],
            "recommendedChecks": [EXPECTED_CHECK],
            "traceId": trace_id,
        }
        return {
            "id": "controlled-memory-e2e",
            "model": MODEL,
            "choices": [
                {
                    "message": {
                        "content": json.dumps(report, ensure_ascii=False, separators=(",", ":"))
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 1,
                "completion_tokens": 1,
                "total_tokens": 2,
            },
        }


class _ProviderHandler(BaseHTTPRequestHandler):
    provider: _ControlledProvider

    def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
        if self.path != "/chat/completions":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            prompt = payload["messages"][0]["content"]
            response = self.provider.completion(prompt)
            body = json.dumps(response, ensure_ascii=False, separators=(",", ":")).encode()
            self.send_response(200)
        except Exception:  # noqa: BLE001 - provider failure must reach the real client
            body = b'{"error":{"message":"controlled provider rejected the request"}}'
            self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        del format, args


class _ControlledProviderServer:
    def __init__(self, provider: _ControlledProvider) -> None:
        handler = type("ControlledProviderHandler", (_ProviderHandler,), {"provider": provider})
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self._server.server_port}"

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)


def _launch_python(
    *,
    project: Path,
    port: int,
    env: dict[str, str],
    log_dir: Path,
    label: str,
) -> subprocess.Popen[bytes]:
    stdout_path = log_dir / f"{label}.stdout.log"
    stderr_path = log_dir / f"{label}.stderr.log"
    stdout = stdout_path.open("wb")
    stderr = stderr_path.open("wb")
    try:
        return subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(port),
            ],
            cwd=project,
            env=env,
            stdout=stdout,
            stderr=stderr,
        )
    finally:
        stdout.close()
        stderr.close()


def _wait_for_health(process: subprocess.Popen[bytes], base_url: str) -> None:
    deadline = time.monotonic() + 20
    with httpx.Client(base_url=base_url, timeout=1, trust_env=False) as client:
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise RuntimeError("Python Uvicorn process exited before /health became ready")
            try:
                response = client.get("/health")
                if response.status_code == 200 and response.json().get("status") == "ok":
                    return
            except (httpx.HTTPError, ValueError):
                pass
            time.sleep(0.2)
    raise RuntimeError("Python Uvicorn /health did not become ready within 20 seconds")


def _stop_process(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)


def _json_request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    token: str,
    trace_id: str | None = None,
    payload: dict[str, object] | None = None,
) -> object:
    headers = {"Authorization": f"Bearer {token}"}
    if trace_id is not None:
        headers["X-Trace-Id"] = trace_id
    response = client.request(method, path, headers=headers, json=payload)
    if not 200 <= response.status_code < 300:
        raise RuntimeError(f"Python HTTP {method} {path} returned {response.status_code}")
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError(f"Python HTTP {method} {path} returned invalid JSON") from exc


def _request_status(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    token: str,
    payload: dict[str, object] | None = None,
) -> int:
    response = client.request(
        method,
        path,
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
    )
    return response.status_code


def _memory_snapshot(database_path: Path) -> tuple[dict[str, object], ...]:
    query = """
        SELECT memory_id, project_id, api_id, failure_fingerprint,
               verification_status, lifecycle_status, source_run_id, symptoms
        FROM historical_failure_memory
        ORDER BY memory_id
    """
    connection = sqlite3.connect(database_path)
    try:
        with connection:
            return tuple(
                {
                    "memoryId": row[0],
                    "projectId": row[1],
                    "apiId": row[2],
                    "failureFingerprint": row[3],
                    "verificationStatus": row[4],
                    "lifecycleStatus": row[5],
                    "sourceRunId": row[6],
                    "symptoms": json.loads(row[7]),
                }
                for row in connection.execute(query).fetchall()
            )
    finally:
        connection.close()


def _require(condition: object, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def _assert_diagnosis(response: dict[str, object], trace_id: str) -> dict[str, object]:
    _require(response.get("status") == "COMPLETED", "Diagnosis did not complete")
    _require(response.get("projectId") == PROJECT_ID, "Diagnosis projectId changed")
    _require(response.get("runId") == RUN_ID, "Diagnosis runId changed")
    _require(response.get("reportId") == EXPECTED_REPORT_ID, "Diagnosis reportId changed")
    _require(response.get("traceId") == trace_id, "Diagnosis traceId was not preserved")
    report = response.get("report")
    _require(isinstance(report, dict), "Diagnosis report is missing")
    _require(report.get("rootCauseHypotheses"), "Diagnosis rootCauseHypotheses is empty")
    _require(report.get("recommendedChecks"), "Diagnosis recommendedChecks is empty")
    return report


def _controlled_environment(
    *,
    java_base_url: str,
    token: str,
    provider_url: str,
    database_path: Path,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "JAVA_APIOPS_BASE_URL": java_base_url,
            "JAVA_APIOPS_TOKEN": token,
            "DEEPSEEK_BASE_URL": provider_url,
            "DEEPSEEK_API_KEY": "controlled-not-secret",
            "DEEPSEEK_MODEL": MODEL,
            "MEMORY_DB_PATH": str(database_path),
            "PYTHONUTF8": "1",
        }
    )
    return environment


def _validate_fixture_environment() -> None:
    expected = {
        "STAGE_MEMORY_PROJECT_ID": str(PROJECT_ID),
        "STAGE_MEMORY_RUN_ID": str(RUN_ID),
        "STAGE_MEMORY_EXPECTED_API_ID": EXPECTED_API_ID,
    }
    for name, expected_value in expected.items():
        actual_value = os.environ.get(name, "").strip()
        _require(actual_value == expected_value, f"{name} fixture value changed")


def run_controlled() -> dict[str, object]:
    _validate_fixture_environment()
    java_base_url = os.environ.get("JAVA_APIOPS_BASE_URL", "").strip()
    token = os.environ.get("JAVA_APIOPS_TOKEN", "").strip()
    if not java_base_url or not token:
        raise RuntimeError("JAVA_APIOPS_BASE_URL and JAVA_APIOPS_TOKEN are required")
    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(
        prefix="historical-memory-live-e2e-", ignore_cleanup_errors=True
    ) as temp_dir:
        temp_path = Path(temp_dir)
        database_path = temp_path / "historical-memory.sqlite3"
        provider = _ControlledProvider()
        provider_server = _ControlledProviderServer(provider)
        process_one: subprocess.Popen[bytes] | None = None
        process_two: subprocess.Popen[bytes] | None = None
        try:
            provider_server.start()
            environment = _controlled_environment(
                java_base_url=java_base_url,
                token=token,
                provider_url=provider_server.base_url,
                database_path=database_path,
            )
            port_one = _free_port()
            process_one = _launch_python(
                project=project,
                port=port_one,
                env=environment,
                log_dir=temp_path,
                label="python-1",
            )
            _wait_for_health(process_one, f"http://127.0.0.1:{port_one}")

            with httpx.Client(
                base_url=f"http://127.0.0.1:{port_one}",
                timeout=30,
                trust_env=False,
            ) as client_one:
                first_trace_id = f"historical-memory-first-{uuid4().hex}"
                first = _json_request(
                    client_one,
                    "POST",
                    "/api/v1/diagnosis/runs",
                    token=token,
                    trace_id=first_trace_id,
                    payload={"projectId": PROJECT_ID, "runId": RUN_ID},
                )
                _require(isinstance(first, dict), "first Diagnosis response is not an object")
                first_report = _assert_diagnosis(first, first_trace_id)
                _require(provider.calls == 1, "process #1 must make exactly one provider call")
                _require(provider.initial_calls == 1, "process #1 provider call must be initial")
                _require(provider.refinement_calls == 0, "process #1 must not refine before write")

                pre_write_row_count = len(_memory_snapshot(database_path))
                _require(pre_write_row_count == 0, "Memory was written before explicit remember")
                first_agent_run_id = str(first["agentRunId"])
                write = _json_request(
                    client_one,
                    "POST",
                    f"/api/v1/diagnosis/runs/{first_agent_run_id}/memory",
                    token=token,
                    payload={"hypothesisIndex": 0},
                )
                _require(isinstance(write, dict), "write response is not an object")
                _require(write.get("outcome") == "ACCEPT", "explicit remember was not ACCEPT")
                _require(write.get("stored") is True, "accepted memory was not stored")
                memory_id = write.get("memoryId")
                _require(
                    isinstance(memory_id, str) and re.fullmatch(r"memory_[0-9a-f]{64}", memory_id),
                    "write response memoryId is invalid",
                )
                written_rows = _memory_snapshot(database_path)
                _require(len(written_rows) == 1, "explicit remember did not create one SQLite row")
                written_row = written_rows[0]
                _require(
                    written_row["memoryId"] == memory_id,
                    "SQLite memoryId differs from response",
                )
                _require(written_row["projectId"] == PROJECT_ID, "SQLite project scope changed")
                _require(
                    written_row["apiId"] == EXPECTED_API_ID,
                    "SQLite apiId is not Java run-summary apiId",
                )
                _require(written_row["verificationStatus"] == "VERIFIED", "memory is not VERIFIED")
                _require(written_row["lifecycleStatus"] == "ACTIVE", "memory is not ACTIVE")
                _require(written_row["sourceRunId"] == RUN_ID, "memory source run changed")
                _require(bool(written_row["failureFingerprint"]), "memory fingerprint is empty")

                duplicate = _json_request(
                    client_one,
                    "POST",
                    f"/api/v1/diagnosis/runs/{first_agent_run_id}/memory",
                    token=token,
                    payload={"hypothesisIndex": 0},
                )
                _require(isinstance(duplicate, dict), "duplicate response is not an object")
                _require(
                    duplicate.get("outcome") == "IDEMPOTENT",
                    "duplicate remember was not IDEMPOTENT",
                )
                _require(duplicate.get("memoryId") == memory_id, "duplicate memoryId changed")
                _require(len(_memory_snapshot(database_path)) == 1, "duplicate created another row")

                invalid_hypothesis_status = _request_status(
                    client_one,
                    "POST",
                    f"/api/v1/diagnosis/runs/{first_agent_run_id}/memory",
                    token=token,
                    payload={"hypothesisIndex": 999},
                )
                _require(
                    invalid_hypothesis_status >= 400,
                    "invalid hypothesis index was not rejected",
                )
                _require(
                    len(_memory_snapshot(database_path)) == 1,
                    "invalid hypothesis index changed SQLite",
                )
                extra_authority_status = _request_status(
                    client_one,
                    "POST",
                    f"/api/v1/diagnosis/runs/{first_agent_run_id}/memory",
                    token=token,
                    payload={
                        "hypothesisIndex": 0,
                        "verificationStatus": "VERIFIED",
                        "apiId": "attacker-api",
                        "rootCause": "attacker root cause",
                    },
                )
                _require(
                    extra_authority_status >= 400,
                    "extra authority field was not rejected",
                )
                negative_post_row_count = len(_memory_snapshot(database_path))
                _require(
                    negative_post_row_count == 1,
                    "extra authority field changed SQLite",
                )

            first_root_cause = str(first_report["rootCauseHypotheses"][0]["statement"])
            first_test_report = TestReport.model_validate(first["testReport"])
            first_symptoms = list(build_memory_symptoms(first_test_report))
            _require(
                first_symptoms == written_row["symptoms"],
                "SQLite symptoms differ from the Java TestReport-derived symptoms",
            )
            first_fingerprint = str(written_row["failureFingerprint"])
            pid_one = process_one.pid
            _stop_process(process_one)
            _require(process_one.poll() is not None, "Python process #1 did not terminate")
            post_restart_rows = _memory_snapshot(database_path)
            _require(len(post_restart_rows) == 1, "SQLite row disappeared after process #1 stopped")
            _require(
                post_restart_rows[0]["memoryId"] == memory_id,
                "memoryId changed after restart",
            )
            _require(
                post_restart_rows[0]["verificationStatus"] == "VERIFIED"
                and post_restart_rows[0]["lifecycleStatus"] == "ACTIVE",
                "memory status changed after restart",
            )

            port_two = _free_port()
            process_two = _launch_python(
                project=project,
                port=port_two,
                env=environment,
                log_dir=temp_path,
                label="python-2",
            )
            _wait_for_health(process_two, f"http://127.0.0.1:{port_two}")
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port_two}",
                timeout=30,
                trust_env=False,
            ) as client_two:
                second_trace_id = f"historical-memory-second-{uuid4().hex}"
                second = _json_request(
                    client_two,
                    "POST",
                    "/api/v1/diagnosis/runs",
                    token=token,
                    trace_id=second_trace_id,
                    payload={"projectId": PROJECT_ID, "runId": RUN_ID},
                )
                _require(isinstance(second, dict), "second Diagnosis response is not an object")
                second_report = _assert_diagnosis(second, second_trace_id)
                _require(
                    second.get("context", {}).get("modelCalls") == 2,
                    "process #2 model budget changed",
                )
                _require(
                    second.get("context", {}).get("toolCalls") == 0,
                    "process #2 called Tool Gateway",
                )
                second_evidence = second_report["rootCauseHypotheses"][0]["evidenceRefs"]
                _require(
                    second_evidence[0]["itemId"] == memory_id,
                    "refinement did not cite memoryId",
                )
                trace = _json_request(
                    client_two,
                    "GET",
                    f"/api/v1/traces/{second_trace_id}",
                    token=token,
                )
                _require(isinstance(trace, list), "trace response is not an array")

            historical_retrievals = [
                record
                for record in trace
                if record.get("record_type") == "retrieval"
                and record.get("retrieval_kind") == "HISTORICAL_MEMORY"
                and record.get("reference", {}).get("memory_id") == memory_id
                and record.get("result_count", 0) >= 1
            ]
            refinement_calls = [
                record
                for record in trace
                if record.get("record_type") == "model_call"
                and record.get("prompt", {}).get("name") == "diagnosis_memory_refinement"
            ]
            tool_records = [
                record for record in trace if record.get("record_type") == "tool_result"
            ]
            _require(
                len(historical_retrievals) == 1,
                "expected one Historical Memory retrieval fact",
            )
            _require(bool(refinement_calls), "refinement model call trace is missing")
            _require(not tool_records, "process #2 emitted a Tool Gateway result")
            _require(provider.calls == 3, "controlled provider call count is not three")
            _require(
                provider.initial_calls == 2,
                "controlled provider initial call count is not two",
            )
            _require(
                provider.refinement_calls == 1,
                "controlled provider refinement count is not one",
            )

            second_root_cause = str(second_report["rootCauseHypotheses"][0]["statement"])
            second_test_report = TestReport.model_validate(second["testReport"])
            second_symptoms = list(build_memory_symptoms(second_test_report))
            second_api_id = post_restart_rows[0]["apiId"]
            second_fingerprint = build_failure_fingerprint(
                api_id=str(second_api_id),
                symptoms=second_symptoms,
                root_cause=second_root_cause,
            )
            return {
                "status": "PASS",
                "projectId": PROJECT_ID,
                "runId": RUN_ID,
                "apiId": written_row["apiId"],
                "firstAgentRunId": first_agent_run_id,
                "secondAgentRunId": str(second["agentRunId"]),
                "firstTraceId": first_trace_id,
                "secondTraceId": second_trace_id,
                "memoryId": memory_id,
                "preWriteRowCount": pre_write_row_count,
                "writeOutcome": write["outcome"],
                "duplicateOutcome": duplicate["outcome"],
                "invalidHypothesisStatus": invalid_hypothesis_status,
                "extraAuthorityStatus": extra_authority_status,
                "negativePostRowCount": negative_post_row_count,
                "postWriteRowCount": len(written_rows),
                "postRestartRowCount": len(post_restart_rows),
                "pythonRestarted": pid_one != process_two.pid,
                "firstPid": pid_one,
                "secondPid": process_two.pid,
                "historicalMemoryRetrievalCount": len(historical_retrievals),
                "refinementModelCallPresent": bool(refinement_calls),
                "toolCallCountAfterRestart": len(tool_records),
                "providerCallCount": provider.calls,
                "providerInitialCallCount": provider.initial_calls,
                "providerRefinementCallCount": provider.refinement_calls,
                "firstRootCauseRaw": first_root_cause,
                "secondRootCauseRaw": second_root_cause,
                "firstRootCauseNormalized": normalize_identity(first_root_cause),
                "secondRootCauseNormalized": normalize_identity(second_root_cause),
                "firstSymptoms": first_symptoms,
                "secondSymptoms": second_symptoms,
                "apiIdEqual": written_row["apiId"] == second_api_id,
                "symptomsEqual": first_symptoms == second_symptoms,
                "normalizedRootCauseEqual": normalize_identity(first_root_cause)
                == normalize_identity(second_root_cause),
                "writtenFingerprint": first_fingerprint,
                "secondQueryFingerprint": second_fingerprint,
                "fingerprintsEqual": first_fingerprint == second_fingerprint,
            }
        finally:
            _stop_process(process_two)
            _stop_process(process_one)
            provider_server.close()


_REAL_FAILURE_STATUSES = frozenset({"ASSERTION_FAILED", "EXECUTION_FAILED", "TIMEOUT"})


def _safe_error(exception: BaseException) -> str:
    message = str(exception)
    for name in ("JAVA_APIOPS_TOKEN", "DEEPSEEK_API_KEY"):
        secret = os.environ.get(name, "")
        if secret:
            message = message.replace(secret, "<redacted>")
    return re.sub(r"sk-[A-Za-z0-9]+", "<redacted>", message)[:1_000]


def _real_configuration() -> dict[str, object]:
    missing: list[str] = []
    java_base_url = os.environ.get("JAVA_APIOPS_BASE_URL", "").strip()
    token = os.environ.get("JAVA_APIOPS_TOKEN", "").strip()
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    project_text = os.environ.get("REAL_MODEL_PROJECT_ID", "").strip()
    run_text = os.environ.get("REAL_MODEL_RUN_ID", "").strip()
    if not java_base_url:
        missing.append("JAVA_APIOPS_BASE_URL")
    if not token:
        missing.append("JAVA_APIOPS_TOKEN")
    if not api_key:
        missing.append("DEEPSEEK_API_KEY")
    try:
        project_id = int(project_text)
        if project_id < 1:
            raise ValueError
    except ValueError:
        missing.append("REAL_MODEL_PROJECT_ID (positive integer)")
        project_id = 0
    try:
        run_id = int(run_text)
        if run_id < 1:
            raise ValueError
    except ValueError:
        missing.append("REAL_MODEL_RUN_ID (positive integer)")
        run_id = 0
    if missing:
        return {"status": "NOT_RUN", "missingPrerequisites": missing}
    return {
        "status": "READY",
        "javaBaseUrl": java_base_url,
        "token": token,
        "apiKey": api_key,
        "projectId": project_id,
        "runId": run_id,
        "deepseekBaseUrl": os.environ.get(
            "DEEPSEEK_BASE_URL", "https://api.deepseek.com"
        ).strip(),
        "deepseekModel": os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash").strip(),
    }


async def _select_real_failure(
    *,
    java_base_url: str,
    project_id: int,
    run_id: int,
    token: str,
) -> dict[str, object]:
    async with httpx.AsyncClient(trust_env=False) as http_client:
        client = JavaApiOpsClient(
            http_client,
            base_url=java_base_url,
            timeout_seconds=10,
        )
        trace_id = f"historical-memory-real-selection-{uuid4().hex}"
        summaries = await client.list_test_runs(
            project_id=project_id,
            token=token,
            trace_id=trace_id,
        )
        matches = [summary for summary in summaries if summary.run_id == run_id]
        if len(matches) != 1:
            raise RuntimeError(
                f"Java run-summary selection expected one runId={run_id}, found {len(matches)}"
            )
        report = await client.get_test_report(
            project_id=project_id,
            run_id=run_id,
            token=token,
            trace_id=trace_id,
        )
        if report.status not in _REAL_FAILURE_STATUSES:
            raise RuntimeError(
                f"selected Java runId={run_id} is not a terminal failure: {report.status}"
            )
        return {
            "projectId": project_id,
            "runId": run_id,
            "apiId": matches[0].api_id,
            "caseId": matches[0].case_id,
            "status": report.status,
            "failureType": str(report.summary.failure_type),
            "reportId": report.report_id,
        }


def _real_diagnosis(
    client: httpx.Client,
    *,
    project_id: int,
    run_id: int,
    token: str,
    trace_id: str,
) -> tuple[dict[str, object], dict[str, object]]:
    response = _json_request(
        client,
        "POST",
        "/api/v1/diagnosis/runs",
        token=token,
        trace_id=trace_id,
        payload={"projectId": project_id, "runId": run_id},
    )
    _require(isinstance(response, dict), "real Diagnosis response is not an object")
    if response.get("status") == "APPROVAL_REQUIRED":
        agent_run_id = response.get("agentRunId")
        _require(isinstance(agent_run_id, str) and agent_run_id, "approval lacks agentRunId")
        response = _json_request(
            client,
            "POST",
            f"/api/v1/diagnosis/runs/{agent_run_id}/resume",
            token=token,
            trace_id=f"{trace_id}-resume",
            payload={"decision": "APPROVE", "editedArguments": None},
        )
        _require(isinstance(response, dict), "real resume response is not an object")
    _require(response.get("status") == "COMPLETED", "real Diagnosis did not complete")
    report = response.get("report")
    _require(isinstance(report, dict), "real Diagnosis report is missing")
    hypotheses = report.get("rootCauseHypotheses")
    _require(isinstance(hypotheses, list) and hypotheses, "real root cause hypothesis is missing")
    _require(report.get("recommendedChecks"), "real recommended checks are missing")
    return response, report


def _real_environment(
    *,
    configuration: dict[str, object],
    memory_db_path: Path,
    runtime_db_path: Path,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "JAVA_APIOPS_BASE_URL": str(configuration["javaBaseUrl"]),
            "JAVA_APIOPS_TOKEN": str(configuration["token"]),
            "DEEPSEEK_BASE_URL": str(configuration["deepseekBaseUrl"]),
            "DEEPSEEK_API_KEY": str(configuration["apiKey"]),
            "DEEPSEEK_MODEL": str(configuration["deepseekModel"]),
            "MEMORY_DB_PATH": str(memory_db_path),
            "RUNTIME_DB_PATH": str(runtime_db_path),
            "PYTHONUTF8": "1",
        }
    )
    return environment


def run_real() -> dict[str, object]:
    configuration = _real_configuration()
    if configuration["status"] != "READY":
        return configuration

    project_id = int(configuration["projectId"])
    run_id = int(configuration["runId"])
    try:
        selection = asyncio.run(
            _select_real_failure(
                java_base_url=str(configuration["javaBaseUrl"]),
                project_id=project_id,
                run_id=run_id,
                token=str(configuration["token"]),
            )
        )
    except (JavaApiOpsError, httpx.HTTPError, RuntimeError) as exception:
        return {
            "status": "NOT_RUN",
            "projectId": project_id,
            "runId": run_id,
            "classification": "REAL_JAVA_PREREQUISITE_BLOCKER",
            "error": _safe_error(exception),
        }

    project = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory(
        prefix="historical-memory-real-smoke-", ignore_cleanup_errors=True
    ) as temp_dir:
        temp_path = Path(temp_dir)
        memory_db_path = temp_path / "historical-memory.sqlite3"
        runtime_db_path = temp_path / "runtime.sqlite3"
        environment = _real_environment(
            configuration=configuration,
            memory_db_path=memory_db_path,
            runtime_db_path=runtime_db_path,
        )
        process_one: subprocess.Popen[bytes] | None = None
        process_two: subprocess.Popen[bytes] | None = None
        first: dict[str, object] | None = None
        second: dict[str, object] | None = None
        try:
            port_one = _free_port()
            process_one = _launch_python(
                project=project,
                port=port_one,
                env=environment,
                log_dir=temp_path,
                label="real-python-1",
            )
            _wait_for_health(process_one, f"http://127.0.0.1:{port_one}")

            with httpx.Client(
                base_url=f"http://127.0.0.1:{port_one}",
                timeout=120,
                trust_env=False,
            ) as client_one:
                first_request_trace_id = f"historical-memory-real-first-{uuid4().hex}"
                first, first_report = _real_diagnosis(
                    client_one,
                    project_id=project_id,
                    run_id=run_id,
                    token=str(configuration["token"]),
                    trace_id=first_request_trace_id,
                )
                first_agent_run_id = str(first["agentRunId"])
                pre_write_row_count = len(_memory_snapshot(memory_db_path))
                _require(pre_write_row_count == 0, "real Memory was written before remember")
                write = _json_request(
                    client_one,
                    "POST",
                    f"/api/v1/diagnosis/runs/{first_agent_run_id}/memory",
                    token=str(configuration["token"]),
                    payload={"hypothesisIndex": 0},
                )
                _require(isinstance(write, dict), "real memory write response is not an object")
                _require(write.get("outcome") == "ACCEPT", "real memory write was not ACCEPT")
                _require(write.get("stored") is True, "real accepted memory was not stored")
                memory_id = write.get("memoryId")
                _require(
                    isinstance(memory_id, str)
                    and re.fullmatch(r"memory_[0-9a-f]{64}", memory_id),
                    "real memoryId is invalid",
                )
                written_rows = _memory_snapshot(memory_db_path)
                _require(len(written_rows) == 1, "real memory write did not create one row")
                written_row = written_rows[0]
                _require(written_row["memoryId"] == memory_id, "real memoryId changed in SQLite")
                _require(written_row["projectId"] == project_id, "real project scope changed")
                _require(written_row["apiId"] == selection["apiId"], "real apiId changed")
                _require(
                    written_row["verificationStatus"] == "VERIFIED"
                    and written_row["lifecycleStatus"] == "ACTIVE",
                    "real stored memory is not VERIFIED and ACTIVE",
                )

            first_root_cause = str(first_report["rootCauseHypotheses"][0]["statement"])
            first_test_report = TestReport.model_validate(first["testReport"])
            first_symptoms = list(build_memory_symptoms(first_test_report))
            _require(
                first_symptoms == written_row["symptoms"],
                "real SQLite symptoms differ from the Java TestReport",
            )
            written_fingerprint = str(written_row["failureFingerprint"])
            pid_one = process_one.pid
            _stop_process(process_one)
            _require(process_one.poll() is not None, "real Python process #1 did not terminate")
            post_restart_rows = _memory_snapshot(memory_db_path)
            _require(len(post_restart_rows) == 1, "real SQLite row disappeared after restart")
            _require(
                post_restart_rows[0]["memoryId"] == memory_id,
                "real memoryId changed after restart",
            )

            port_two = _free_port()
            process_two = _launch_python(
                project=project,
                port=port_two,
                env=environment,
                log_dir=temp_path,
                label="real-python-2",
            )
            _wait_for_health(process_two, f"http://127.0.0.1:{port_two}")
            with httpx.Client(
                base_url=f"http://127.0.0.1:{port_two}",
                timeout=120,
                trust_env=False,
            ) as client_two:
                second_request_trace_id = f"historical-memory-real-second-{uuid4().hex}"
                second, second_report = _real_diagnosis(
                    client_two,
                    project_id=project_id,
                    run_id=run_id,
                    token=str(configuration["token"]),
                    trace_id=second_request_trace_id,
                )
                second_trace_id = str(second["traceId"])
                trace = _json_request(
                    client_two,
                    "GET",
                    f"/api/v1/traces/{second_trace_id}",
                    token=str(configuration["token"]),
                )
                _require(isinstance(trace, list), "real trace response is not an array")

            historical_retrievals = [
                record
                for record in trace
                if isinstance(record, dict)
                and record.get("record_type") == "retrieval"
                and record.get("retrieval_kind") == "HISTORICAL_MEMORY"
            ]
            matching_retrievals = [
                record
                for record in historical_retrievals
                if isinstance(record.get("reference"), dict)
                and record["reference"].get("memory_id") == memory_id
                and record.get("result_count", 0) >= 1
            ]
            refinement_calls = [
                record
                for record in trace
                if isinstance(record, dict)
                and record.get("record_type") == "model_call"
                and isinstance(record.get("prompt"), dict)
                and record["prompt"].get("name") == "diagnosis_memory_refinement"
            ]
            tool_records = [
                record
                for record in trace
                if isinstance(record, dict) and record.get("record_type") == "tool_result"
            ]
            second_root_cause = str(second_report["rootCauseHypotheses"][0]["statement"])
            second_test_report = TestReport.model_validate(second["testReport"])
            second_symptoms = list(build_memory_symptoms(second_test_report))
            second_fingerprint = build_failure_fingerprint(
                api_id=str(selection["apiId"]),
                symptoms=second_symptoms,
                root_cause=second_root_cause,
            )
            identity = {
                "apiIdEqual": selection["apiId"] == written_row["apiId"],
                "symptomsEqual": first_symptoms == second_symptoms,
                "normalizedRootCauseEqual": normalize_identity(first_root_cause)
                == normalize_identity(second_root_cause),
                "fingerprintsEqual": written_fingerprint == second_fingerprint,
            }
            memory_hit = bool(matching_retrievals and refinement_calls)
            if memory_hit:
                classification = "REAL_MODEL_MEMORY_RECALL=PASS"
            elif not identity["normalizedRootCauseEqual"]:
                classification = "ROOT_CAUSE_IDENTITY_STABILITY_BLOCKER"
            else:
                classification = "REAL_RECALL_IMPLEMENTATION_BLOCKER"
            first_context = first.get("context", {})
            second_context = second.get("context", {})
            return {
                "status": "PASS" if memory_hit else "FAIL",
                **selection,
                "firstAgentRunId": first_agent_run_id,
                "secondAgentRunId": str(second["agentRunId"]),
                "firstTraceId": str(first["traceId"]),
                "secondTraceId": second_trace_id,
                "memoryId": memory_id,
                "preWriteRowCount": pre_write_row_count,
                "writeOutcome": write["outcome"],
                "postWriteRowCount": len(written_rows),
                "postRestartRowCount": len(post_restart_rows),
                "pythonRestarted": pid_one != process_two.pid,
                "firstPid": pid_one,
                "secondPid": process_two.pid,
                "historicalMemoryRetrievalCount": len(historical_retrievals),
                "memoryHit": bool(matching_retrievals),
                "refinementObserved": bool(refinement_calls),
                "refinementModelCallCount": len(refinement_calls),
                "toolCallCountAfterRestart": len(tool_records),
                "firstModelCallCount": first_context.get("modelCalls")
                if isinstance(first_context, dict)
                else None,
                "secondModelCallCount": second_context.get("modelCalls")
                if isinstance(second_context, dict)
                else None,
                "firstToolCallCount": first_context.get("toolCalls")
                if isinstance(first_context, dict)
                else None,
                "secondToolCallCount": second_context.get("toolCalls")
                if isinstance(second_context, dict)
                else None,
                "firstRootCauseRaw": first_root_cause,
                "secondRootCauseRaw": second_root_cause,
                "firstRootCauseNormalized": normalize_identity(first_root_cause),
                "secondRootCauseNormalized": normalize_identity(second_root_cause),
                "firstSymptoms": first_symptoms,
                "secondSymptoms": second_symptoms,
                "writtenFingerprint": written_fingerprint,
                "secondQueryFingerprint": second_fingerprint,
                **identity,
                "classification": classification,
            }
        except Exception as exception:  # noqa: BLE001 - smoke reports its evidence outcome
            result: dict[str, object] = {
                "status": "FAIL",
                **selection,
                "classification": "REAL_MODEL_SMOKE_BLOCKER",
                "error": _safe_error(exception),
            }
            if first is not None:
                result["firstAgentRunId"] = first.get("agentRunId")
                result["firstTraceId"] = first.get("traceId")
            if second is not None:
                result["secondAgentRunId"] = second.get("agentRunId")
                result["secondTraceId"] = second.get("traceId")
            return result
        finally:
            _stop_process(process_two)
            _stop_process(process_one)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("controlled", "real"))
    args = parser.parse_args()
    result = run_controlled() if args.mode == "controlled" else run_real()
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":"), sort_keys=True))


if __name__ == "__main__":
    main()
