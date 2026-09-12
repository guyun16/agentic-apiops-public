"""Minimal outbound client for the Java API Ops metadata read boundary."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Generic, TypeVar
from urllib.parse import quote
from uuid import uuid4

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
)

from app.rag.errors import (
    EvidenceAuthorizationError,
    EvidenceRequestContractError,
    EvidenceResponseContractError,
    EvidenceSystemError,
)
from app.rag.models import EvidenceRetrieval
from app.schemas.openapi_metadata import OpenApiMetadataDetail
from app.schemas.runner import RunnerProgress, RunnerSubmission, TestReport
from app.schemas.testcase_dsl import TestCaseDSL
from app.schemas.tool_call import ToolCall
from app.schemas.tool_result import ToolResult
from app.tools import (
    InvalidGatewayResultError,
    ToolCatalog,
    ToolGatewayAuthenticationError,
    ToolGatewayAuthorizationError,
    ToolGatewayNotFoundError,
    ToolGatewayTimeoutError,
    ToolGatewayTransportError,
    ToolIntent,
    map_tool_intent,
)


class JavaApiOpsError(RuntimeError):
    """Base class for stable Java API Ops client failures."""


class JavaApiOpsHttpError(JavaApiOpsError):
    """An unexpected non-2xx HTTP response from Java API Ops."""

    def __init__(self, status_code: int) -> None:
        self.status_code = status_code
        super().__init__(f"Java API Ops request returned HTTP {status_code}")


class JavaApiOpsClientError(JavaApiOpsHttpError):
    """A 4xx response from Java API Ops."""


class JavaApiOpsServerError(JavaApiOpsHttpError):
    """A 5xx response from Java API Ops."""


class JavaApiOpsTimeoutError(JavaApiOpsError):
    """The Java API Ops request exceeded its configured timeout."""


class JavaApiOpsTransportError(JavaApiOpsError):
    """The Java API Ops request failed before receiving an HTTP response."""


class JavaApiOpsMalformedResponseError(JavaApiOpsError):
    """A 2xx response did not contain valid JSON."""


class JavaApiOpsResponseValidationError(JavaApiOpsError):
    """A 2xx JSON response did not match the Java response contract."""


class JavaApiOpsAuthenticationError(JavaApiOpsClientError):
    """Java rejected the supplied credential (HTTP 401)."""


class JavaApiOpsAuthorizationError(JavaApiOpsClientError):
    """Java denied access to the project-scoped resource (HTTP 403)."""


class JavaApiOpsNotFoundError(JavaApiOpsClientError):
    """The Java-owned resource was not found (HTTP 404)."""


class JavaApiOpsConflictError(JavaApiOpsClientError):
    """Java rejected the operation because of a resource conflict (HTTP 409)."""


class JavaRunnerSubmitUncertainError(JavaApiOpsTimeoutError):
    """Submit timed out after dispatch; Java may or may not have accepted it."""


class JavaRunnerStatusQueryTimeoutError(JavaApiOpsTimeoutError):
    """Status observation timed out; this is not Java Runner status TIMEOUT."""


_EnvelopeData = TypeVar("_EnvelopeData")


class _JavaResultEnvelope(BaseModel, Generic[_EnvelopeData]):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
    )

    success: StrictBool
    code: StrictStr
    message: StrictStr
    data: _EnvelopeData


class _JavaLoginPayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
    )

    user_id: int = Field(alias="userId")
    username: StrictStr
    token_type: StrictStr = Field(alias="tokenType")
    access_token: StrictStr = Field(alias="accessToken")
    expires_at: StrictStr = Field(alias="expiresAt")


class _JavaProjectPayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
    )

    id: StrictInt = Field(ge=1)
    project_key: StrictStr = Field(alias="projectKey", min_length=1)
    project_name: StrictStr = Field(alias="projectName", min_length=1)
    owner_user_id: StrictInt = Field(alias="ownerUserId", ge=1)
    status: StrictStr = Field(min_length=1)
    created_at: StrictStr = Field(alias="createdAt", min_length=1)
    updated_at: StrictStr = Field(alias="updatedAt", min_length=1)


class _JavaRunSummaryPayload(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
    )

    run_id: StrictInt = Field(alias="runId", ge=1)
    case_id: StrictStr = Field(alias="caseId", min_length=1)
    api_id: StrictStr = Field(alias="apiId", min_length=1)
    test_case_name: StrictStr = Field(alias="testCaseName", min_length=1)
    status: StrictStr = Field(min_length=1)
    failure_type: StrictStr = Field(alias="failureType", min_length=1)
    created_at: StrictStr = Field(alias="createdAt", min_length=1)
    started_at: StrictStr | None = Field(alias="startedAt")
    finished_at: StrictStr | None = Field(alias="finishedAt")
    duration_ms: StrictInt | None = Field(alias="durationMs", ge=0)


@dataclass(frozen=True, slots=True)
class JavaAuthenticatedSession:
    """Authenticated Java session; the token is intentionally non-represented."""

    user_id: int
    username: str
    token_type: str
    token: str = field(repr=False)
    expires_at: datetime

    def __post_init__(self) -> None:
        if isinstance(self.user_id, bool) or not isinstance(self.user_id, int):
            raise ValueError("user_id must be an integer")
        if self.user_id < 1:
            raise ValueError("user_id must be positive")
        if not isinstance(self.username, str) or not self.username.strip():
            raise ValueError("username must be non-empty")
        if not isinstance(self.token_type, str) or not self.token_type.strip():
            raise ValueError("token_type must be non-empty")
        if not isinstance(self.token, str) or not self.token.strip():
            raise ValueError("token must be non-empty")
        if not isinstance(self.expires_at, datetime) or self.expires_at.utcoffset() is None:
            raise ValueError("expires_at must be a timezone-aware datetime")


@dataclass(frozen=True, slots=True)
class JavaRunSummary:
    """Project-scoped Java Run summary used to resolve a symbolic input slot."""

    run_id: int
    case_id: str
    api_id: str

    def __post_init__(self) -> None:
        if isinstance(self.run_id, bool) or not isinstance(self.run_id, int) or self.run_id < 1:
            raise ValueError("run_id must be a positive integer")
        if not isinstance(self.case_id, str) or not self.case_id.strip():
            raise ValueError("case_id must be non-empty")
        if not isinstance(self.api_id, str) or not self.api_id.strip():
            raise ValueError("api_id must be non-empty")


_RAG_TOOL_NAME = "rag.search"
_RAG_PATH_TEMPLATE = "/api/v1/projects/{project_id}/tool-calls"
_RAG_MAX_QUERY_LENGTH = 4_096
_RAG_MAX_TOP_K = 20


class JavaApiOpsClient:
    """Shared Java public-boundary client with an injected AsyncClient lifecycle."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        base_url: str,
        timeout_seconds: float,
    ) -> None:
        if not isinstance(base_url, str) or not base_url.strip():
            raise ValueError("base_url must be a non-empty string")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be greater than zero")

        self._http_client = http_client
        self._base_url = base_url.rstrip("/")
        self._timeout_seconds = float(timeout_seconds)

    async def login(self, *, username: str, password: str) -> JavaAuthenticatedSession:
        """Exchange one profile credential for a Java-issued JWT."""

        if not isinstance(username, str) or not username.strip():
            raise ValueError("username must be a non-empty string")
        if not isinstance(password, str) or not password.strip():
            raise ValueError("password must be a non-empty string")

        response = await self._request(
            "POST",
            "/api/v1/auth/login",
            token=None,
            trace_id=None,
            operation="login",
            json_body={"username": username, "password": password},
        )
        payload = self._parse_json(response, operation="login")
        try:
            envelope = _JavaResultEnvelope[object].model_validate(payload)
        except ValidationError as exc:
            raise JavaApiOpsResponseValidationError(
                "Java API Ops login response did not match the response envelope"
            ) from exc
        if not envelope.success:
            raise JavaApiOpsAuthenticationError(401)
        try:
            login = _JavaLoginPayload.model_validate(envelope.data)
        except ValidationError as exc:
            raise JavaApiOpsResponseValidationError(
                "Java API Ops login response did not match the login contract"
            ) from exc
        if login.token_type.lower() != "bearer":
            raise JavaApiOpsResponseValidationError(
                "Java API Ops login returned an unsupported token type"
            )
        try:
            expires_at = datetime.fromisoformat(login.expires_at)
            if expires_at.utcoffset() is None:
                raise ValueError("timezone required")
        except ValueError as exc:
            raise JavaApiOpsResponseValidationError(
                "Java API Ops login returned an invalid session expiry"
            ) from exc
        return JavaAuthenticatedSession(
            user_id=login.user_id,
            username=login.username,
            token_type=login.token_type,
            token=login.access_token,
            expires_at=expires_at,
        )

    async def get_api_metadata(
        self,
        *,
        project_id: int,
        api_id: str,
        token: str,
        trace_id: str | None = None,
    ) -> OpenApiMetadataDetail:
        """Read one project-scoped API metadata detail from Java API Ops."""

        self._validate_call_context(project_id, api_id, token, trace_id)
        path = f"/api/v1/projects/{project_id}/openapi/apis/{quote(api_id, safe='')}"
        response = await self._request(
            "GET",
            path,
            token=token,
            trace_id=trace_id,
            operation="metadata",
        )
        return self._parse_envelope(response, OpenApiMetadataDetail, operation="metadata")

    async def assert_project_readable(
        self,
        *,
        project_id: int,
        token: str,
        trace_id: str,
    ) -> None:
        """Authorize a project read through Java's public project boundary."""

        self._validate_project_auth_trace(project_id, token, trace_id)
        path = f"/api/v1/projects/{project_id}"
        response = await self._request(
            "GET",
            path,
            token=token,
            trace_id=trace_id,
            operation="project authorization",
        )
        project = self._parse_envelope(
            response,
            _JavaProjectPayload,
            operation="project authorization",
        )
        if project.id != project_id:
            raise JavaApiOpsResponseValidationError(
                "Java project response id did not match the requested project"
            )

    async def list_test_runs(
        self,
        *,
        project_id: int,
        token: str,
        trace_id: str,
    ) -> tuple[JavaRunSummary, ...]:
        """Read Java-owned project run summaries for symbolic input resolution."""

        self._validate_project_auth_trace(project_id, token, trace_id)
        path = f"/api/v1/projects/{project_id}/test-runs"
        response = await self._request(
            "GET",
            path,
            token=token,
            trace_id=trace_id,
            operation="Runner summaries",
        )
        summaries = self._parse_envelope(
            response,
            list[_JavaRunSummaryPayload],
            operation="Runner summaries",
        )
        return tuple(
            JavaRunSummary(run_id=item.run_id, case_id=item.case_id, api_id=item.api_id)
            for item in summaries
        )

    async def find_latest_test_run(
        self,
        *,
        project_id: int,
        case_id: str,
        token: str,
        trace_id: str,
    ) -> JavaRunSummary | None:
        """Resolve one exact case without depending on the bounded Runs explorer window."""

        self._validate_project_auth_trace(project_id, token, trace_id)
        if not isinstance(case_id, str) or not case_id.strip():
            raise ValueError("case_id must be non-empty")
        path = (
            f"/api/v1/projects/{project_id}/test-runs/latest-by-case"
            f"?caseId={quote(case_id, safe='')}"
        )
        try:
            response = await self._request(
                "GET",
                path,
                token=token,
                trace_id=trace_id,
                operation="Runner summary by case",
            )
        except JavaApiOpsClientError as exc:
            if exc.status_code != 404:
                raise
            return await self._find_test_run_by_case_paginated(
                project_id=project_id,
                case_id=case_id,
                token=token,
                trace_id=trace_id,
            )
        payload = self._parse_json(response, operation="Runner summary by case")
        try:
            envelope = _JavaResultEnvelope[object].model_validate(payload)
        except ValidationError as exc:
            raise JavaApiOpsResponseValidationError(
                "Java API Ops case Run response did not match the response envelope"
            ) from exc
        if not envelope.success:
            raise JavaApiOpsResponseValidationError(
                "Java API Ops case Run response reported an unsuccessful envelope"
            )
        if envelope.data is None:
            return None
        try:
            item = _JavaRunSummaryPayload.model_validate(envelope.data)
        except ValidationError as exc:
            raise JavaApiOpsResponseValidationError(
                "Java API Ops case Run response did not match the Run summary contract"
            ) from exc
        if item.case_id != case_id:
            raise JavaApiOpsResponseValidationError(
                "Java case Run identity did not match the request"
            )
        return JavaRunSummary(run_id=item.run_id, case_id=item.case_id, api_id=item.api_id)

    async def _find_test_run_by_case_paginated(
        self,
        *,
        project_id: int,
        case_id: str,
        token: str,
        trace_id: str,
    ) -> JavaRunSummary | None:
        """Compatibility path for servers exposing paging but not exact-case lookup."""

        before_run_id: int | None = None
        previous_floor: int | None = None
        while True:
            query = "limit=100"
            if before_run_id is not None:
                query += f"&beforeRunId={before_run_id}"
            response = await self._request(
                "GET",
                f"/api/v1/projects/{project_id}/test-runs?{query}",
                token=token,
                trace_id=trace_id,
                operation="Runner summaries page",
            )
            page = self._parse_envelope(
                response,
                list[_JavaRunSummaryPayload],
                operation="Runner summaries page",
            )
            for item in page:
                if item.case_id == case_id:
                    return JavaRunSummary(
                        run_id=item.run_id,
                        case_id=item.case_id,
                        api_id=item.api_id,
                    )
            if len(page) < 100:
                return None
            floor = min(item.run_id for item in page)
            if previous_floor is not None and floor >= previous_floor:
                raise JavaApiOpsResponseValidationError(
                    "Java Run summary pagination did not advance"
                )
            previous_floor = floor
            before_run_id = floor

    async def execute_tool_call(
        self,
        *,
        project_id: int,
        tool_call: ToolCall,
        token: str,
    ) -> ToolResult:
        """Execute one canonical shared ToolCall through the Java public boundary."""

        if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id < 1:
            raise ValueError("project_id must be a positive integer")
        if not isinstance(tool_call, ToolCall):
            raise TypeError("tool_call must be a ToolCall")
        if tool_call.project_id != str(project_id):
            raise ValueError("tool_call projectId must match trusted project_id")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token must be a non-empty string")

        path = _RAG_PATH_TEMPLATE.format(project_id=project_id)
        response = await self._request(
            "POST",
            path,
            token=token,
            trace_id=tool_call.trace_id,
            operation="Tool Gateway",
            json_body=tool_call.model_dump(mode="json"),
        )
        payload = self._parse_json(response, operation="Tool Gateway")
        try:
            result = ToolResult.model_validate(payload)
        except ValidationError as exc:
            raise JavaApiOpsResponseValidationError(
                "Java Tool Gateway response did not match shared ToolResult"
            ) from exc
        if result.trace_id != tool_call.trace_id:
            raise JavaApiOpsResponseValidationError(
                "Java Tool Gateway response traceId did not match ToolCall"
            )
        return result

    async def submit_testcase(
        self,
        *,
        project_id: int,
        testcase: TestCaseDSL,
        token: str,
        trace_id: str,
    ) -> RunnerSubmission:
        """Submit one validated DSL and preserve Java-owned execution identities.

        This method deliberately performs exactly one POST. A client timeout is
        reported as uncertain because Java may have accepted the submission.
        """

        self._validate_project_auth_trace(project_id, token, trace_id)
        if not isinstance(testcase, TestCaseDSL):
            raise TypeError("testcase must be a validated TestCaseDSL")
        if testcase.project_id != project_id:
            raise ValueError("testcase projectId must match trusted project_id")
        path = f"/api/v1/projects/{project_id}/test-batches"
        try:
            response = await self._request(
                "POST",
                path,
                token=token,
                trace_id=trace_id,
                operation="Runner submit",
                json_body={"testCases": [testcase.model_dump(mode="json")]},
            )
        except JavaApiOpsTimeoutError as exc:
            raise JavaRunnerSubmitUncertainError(
                "Java Runner submit timed out; acceptance state is uncertain"
            ) from exc
        return self._parse_envelope(response, RunnerSubmission, operation="Runner submit")

    async def wait_for_run_terminal(
        self,
        *,
        project_id: int,
        run_id: int,
        token: str,
        trace_id: str,
        overall_deadline_seconds: float,
    ) -> RunnerProgress:
        """Observe Java's existing progress SSE until its contract reports terminal."""

        self._validate_project_auth_trace(project_id, token, trace_id)
        self._validate_positive_int(run_id, "run_id")
        if (
            isinstance(overall_deadline_seconds, bool)
            or not isinstance(overall_deadline_seconds, (int, float))
            or overall_deadline_seconds <= 0
        ):
            raise ValueError("overall_deadline_seconds must be greater than zero")
        path = f"/api/v1/projects/{project_id}/test-runs/{run_id}/progress/events"
        headers = self._headers(token=token, trace_id=trace_id, accept="text/event-stream")
        try:
            async with asyncio.timeout(float(overall_deadline_seconds)):
                async with self._http_client.stream(
                    "GET",
                    f"{self._base_url}{path}",
                    headers=headers,
                    timeout=httpx.Timeout(
                        self._timeout_seconds,
                        read=float(overall_deadline_seconds),
                    ),
                ) as response:
                    self._raise_for_status(response)
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        raw = line.removeprefix("data:").strip()
                        if not raw:
                            continue
                        progress = self._parse_sse_progress(raw)
                        if progress.project_id != project_id or progress.run_id != run_id:
                            raise JavaApiOpsResponseValidationError(
                                "Java Runner progress identity did not match the request"
                            )
                        if progress.terminal:
                            return progress
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise JavaRunnerStatusQueryTimeoutError(
                "Java Runner status observation timed out"
            ) from exc
        except httpx.TransportError as exc:
            raise JavaApiOpsTransportError(
                "Java Runner status request failed during transport"
            ) from exc
        raise JavaApiOpsResponseValidationError(
            "Java Runner progress stream ended before a terminal state"
        )

    async def get_test_report(
        self,
        *,
        project_id: int,
        run_id: int,
        token: str,
        trace_id: str,
    ) -> TestReport:
        """Read the Java-owned TestReport through its public project boundary."""

        self._validate_project_auth_trace(project_id, token, trace_id)
        self._validate_positive_int(run_id, "run_id")
        path = f"/api/v1/projects/{project_id}/test-runs/{run_id}/report"
        response = await self._request(
            "GET",
            path,
            token=token,
            trace_id=trace_id,
            operation="TestReport",
        )
        report = self._parse_envelope(response, TestReport, operation="TestReport")
        if report.project_id != project_id or report.run_id != run_id:
            raise JavaApiOpsResponseValidationError(
                "Java TestReport identity did not match the request"
            )
        return report

    async def retrieve_evidence(
        self,
        *,
        project_id: int,
        query: str,
        top_k: int,
        token: str,
        trace_id: str | None = None,
        target_project_id: int | None = None,
    ) -> EvidenceRetrieval:
        """Read evidence through Java, optionally requesting another project scope."""

        self._validate_rag_call_context(
            project_id, query, top_k, token, trace_id, target_project_id
        )
        effective_trace_id = trace_id.strip() if trace_id and trace_id.strip() else str(uuid4())
        arguments: dict[str, object] = {"query": query, "topK": top_k}
        if target_project_id is not None:
            arguments["targetProjectId"] = target_project_id
        tool_call = map_tool_intent(
            ToolIntent(
                tool_name=_RAG_TOOL_NAME,
                arguments=arguments,
            ),
            catalog=ToolCatalog(),
            agent_run_id=f"evidence:{uuid4()}",
            project_id=str(project_id),
            trace_id=effective_trace_id,
        )
        try:
            result = await self.execute_tool_call(
                project_id=project_id,
                tool_call=tool_call,
                token=token,
            )
        except JavaApiOpsTimeoutError as exc:
            raise EvidenceSystemError("Java RAG request timed out") from exc
        except JavaApiOpsTransportError as exc:
            raise EvidenceSystemError("Java RAG request failed during transport") from exc
        except JavaApiOpsClientError as exc:
            if exc.status_code in (401, 403):
                raise EvidenceAuthorizationError(status_code=exc.status_code) from exc
            if exc.status_code == 400:
                raise EvidenceRequestContractError(status_code=exc.status_code) from exc
            raise EvidenceSystemError(
                f"Java RAG request returned HTTP {exc.status_code}",
                status_code=exc.status_code,
            ) from exc
        except (JavaApiOpsServerError, JavaApiOpsHttpError) as exc:
            raise EvidenceSystemError(
                f"Java RAG request returned HTTP {exc.status_code}",
                status_code=exc.status_code,
            ) from exc
        except (JavaApiOpsMalformedResponseError, JavaApiOpsResponseValidationError) as exc:
            raise EvidenceResponseContractError(
                "Java RAG ToolResult response did not match the shared contract"
            ) from exc

        if result.status == "FORBIDDEN":
            raise EvidenceAuthorizationError(tool_status=result.status)
        if result.status == "PARAM_INVALID":
            raise EvidenceRequestContractError(tool_status=result.status)
        if result.status == "RESULT_INVALID":
            raise EvidenceResponseContractError("Java RAG ToolResult reported invalid result")
        if result.status != "SUCCESS":
            raise EvidenceSystemError(
                f"Java RAG tool returned {result.status}",
                tool_status=result.status,
            )

        try:
            return EvidenceRetrieval.model_validate(result.data)
        except ValidationError as exc:
            raise EvidenceResponseContractError(
                "Java RAG evidence response did not match the expected contract"
            ) from exc

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None,
        trace_id: str | None,
        operation: str,
        json_body: object | None = None,
    ) -> httpx.Response:
        request_options: dict[str, object] = {}
        if json_body is not None:
            request_options["json"] = json_body
        try:
            response = await self._http_client.request(
                method,
                f"{self._base_url}{path}",
                headers=self._headers(token=token, trace_id=trace_id),
                timeout=self._timeout_seconds,
                **request_options,
            )
        except httpx.TimeoutException as exc:
            raise JavaApiOpsTimeoutError(f"Java API Ops {operation} request timed out") from exc
        except httpx.TransportError as exc:
            raise JavaApiOpsTransportError(
                f"Java API Ops {operation} request failed during transport"
            ) from exc
        self._raise_for_status(response)
        return response

    @staticmethod
    def _headers(
        *,
        token: str | None,
        trace_id: str | None,
        accept: str = "application/json",
    ) -> dict[str, str]:
        headers = {"Accept": accept}
        if token is not None:
            if not isinstance(token, str) or not token.strip():
                raise ValueError("token must be a non-empty string")
            headers["Authorization"] = f"Bearer {token.strip()}"
        if trace_id is not None and trace_id.strip():
            headers["X-Trace-Id"] = trace_id.strip()
        return headers

    @staticmethod
    def _raise_for_status(response: httpx.Response) -> None:
        status = response.status_code
        error_types: dict[int, type[JavaApiOpsClientError]] = {
            401: JavaApiOpsAuthenticationError,
            403: JavaApiOpsAuthorizationError,
            404: JavaApiOpsNotFoundError,
            409: JavaApiOpsConflictError,
        }
        if status in error_types:
            raise error_types[status](status)
        if 400 <= status < 500:
            raise JavaApiOpsClientError(status)
        if 500 <= status < 600:
            raise JavaApiOpsServerError(status)
        if not 200 <= status < 300:
            raise JavaApiOpsHttpError(status)

    @staticmethod
    def _parse_json(response: httpx.Response, *, operation: str) -> object:
        try:
            return response.json()
        except ValueError as exc:
            raise JavaApiOpsMalformedResponseError(
                f"Java API Ops {operation} response was not valid JSON"
            ) from exc

    @classmethod
    def _parse_envelope(
        cls,
        response: httpx.Response,
        data_type: type[_EnvelopeData],
        *,
        operation: str,
    ) -> _EnvelopeData:
        payload = cls._parse_json(response, operation=operation)
        try:
            envelope = _JavaResultEnvelope[data_type].model_validate(payload)
        except ValidationError as exc:
            raise JavaApiOpsResponseValidationError(
                f"Java API Ops {operation} response did not match the expected contract"
            ) from exc
        if not envelope.success:
            raise JavaApiOpsResponseValidationError(
                f"Java API Ops {operation} response reported an unsuccessful result"
            )
        return envelope.data

    @staticmethod
    def _parse_sse_progress(raw: str) -> RunnerProgress:
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise JavaApiOpsMalformedResponseError(
                "Java Runner progress event was not valid JSON"
            ) from exc
        try:
            return RunnerProgress.model_validate(payload)
        except ValidationError as exc:
            raise JavaApiOpsResponseValidationError(
                "Java Runner progress event did not match TaskProgressSnapshot"
            ) from exc

    @classmethod
    def _validate_project_auth_trace(cls, project_id: int, token: str, trace_id: str) -> None:
        cls._validate_positive_int(project_id, "project_id")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token must be a non-empty string")
        if not isinstance(trace_id, str) or not trace_id.strip():
            raise ValueError("trace_id must be a non-empty string")

    @staticmethod
    def _validate_positive_int(value: int, name: str) -> None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")

    @staticmethod
    def _validate_call_context(
        project_id: int,
        api_id: str,
        token: str,
        trace_id: str | None,
    ) -> None:
        if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id < 1:
            raise ValueError("project_id must be a positive integer")
        if not isinstance(api_id, str) or not api_id.strip():
            raise ValueError("api_id must be a non-empty string")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token must be a non-empty string")
        if trace_id is not None and not isinstance(trace_id, str):
            raise ValueError("trace_id must be a string or None")

    @staticmethod
    def _validate_rag_call_context(
        project_id: int,
        query: str,
        top_k: int,
        token: str,
        trace_id: str | None,
        target_project_id: int | None,
    ) -> None:
        if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id < 1:
            raise ValueError("project_id must be a positive integer")
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")
        if len(query) > _RAG_MAX_QUERY_LENGTH:
            raise ValueError("query must not exceed 4096 characters")
        if isinstance(top_k, bool) or not isinstance(top_k, int):
            raise ValueError("top_k must be an integer")
        if not 1 <= top_k <= _RAG_MAX_TOP_K:
            raise ValueError("top_k must be between 1 and 20")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("token must be a non-empty string")
        if trace_id is not None and not isinstance(trace_id, str):
            raise ValueError("trace_id must be a string or None")
        if target_project_id is not None:
            JavaApiOpsClient._validate_positive_int(target_project_id, "target_project_id")


class JavaApiOpsToolGatewayAdapter:
    """Bind trusted project/auth context to the existing Java API Ops client."""

    def __init__(
        self,
        client: JavaApiOpsClient,
        *,
        project_id: int,
        token_provider: Callable[[], str],
    ) -> None:
        if not isinstance(client, JavaApiOpsClient):
            raise TypeError("client must be a JavaApiOpsClient")
        if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id < 1:
            raise ValueError("project_id must be a positive integer")
        if not callable(token_provider):
            raise TypeError("token_provider must be callable")
        self._client = client
        self._project_id = project_id
        self._token_provider = token_provider

    async def execute(self, tool_call: ToolCall) -> ToolResult:
        try:
            return await self._client.execute_tool_call(
                project_id=self._project_id,
                tool_call=tool_call,
                token=self._token_provider(),
            )
        except JavaApiOpsAuthenticationError as exc:
            raise ToolGatewayAuthenticationError(
                "Java Tool Gateway rejected the credential"
            ) from exc
        except JavaApiOpsAuthorizationError as exc:
            raise ToolGatewayAuthorizationError(
                "Java Tool Gateway denied project authorization"
            ) from exc
        except JavaApiOpsNotFoundError as exc:
            raise ToolGatewayNotFoundError("Java Tool Gateway resource was not found") from exc
        except JavaApiOpsTimeoutError as exc:
            raise ToolGatewayTimeoutError("Java Tool Gateway timed out") from exc
        except JavaApiOpsTransportError as exc:
            raise ToolGatewayTransportError("Java Tool Gateway unavailable") from exc
        except (JavaApiOpsMalformedResponseError, JavaApiOpsResponseValidationError) as exc:
            raise InvalidGatewayResultError("Java Tool Gateway returned invalid result") from exc
        except JavaApiOpsError as exc:
            raise ToolGatewayTransportError("Java Tool Gateway request failed") from exc
