"""Stage 21 input-side auth-profile resolution and Java login wiring."""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from app.clients.java_apiops import JavaAuthenticatedSession
from app.schemas.testcase_dsl import JsonValue

from .models import BenchmarkTask
from .runner import (
    BenchmarkExecutionOutcome,
    BenchmarkFailureCategory,
    BenchmarkTaskFailure,
    FixtureSetup,
    JavaExecutionStatus,
    Stage20WorkflowAdapter,
)


class Stage21AuthProfile(StrEnum):
    """The three frozen benchmark execution profiles."""

    NORMAL = "NORMAL"
    SAFETY_41_ISOLATED = "SAFETY_41_ISOLATED"
    SAFETY_42_ISOLATED = "SAFETY_42_ISOLATED"


PROFILE_CREDENTIAL_ENV: Mapping[Stage21AuthProfile, tuple[str, str]] = {
    Stage21AuthProfile.NORMAL: (
        "STAGE21_NORMAL_USERNAME",
        "STAGE21_NORMAL_PASSWORD",
    ),
    Stage21AuthProfile.SAFETY_41_ISOLATED: (
        "STAGE21_SAFETY41_USERNAME",
        "STAGE21_SAFETY41_PASSWORD",
    ),
    Stage21AuthProfile.SAFETY_42_ISOLATED: (
        "STAGE21_SAFETY42_USERNAME",
        "STAGE21_SAFETY42_PASSWORD",
    ),
}

DEFAULT_STAGE21_PREREQUISITE_PATH = (
    Path(__file__).resolve().parents[2]
    / "tests"
    / "benchmark"
    / "fixtures"
    / "stage21-execution-prerequisites.json"
)


class AuthProfileResolutionError(RuntimeError):
    """Safe, stable failure raised before a task can use a Java boundary."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


class AuthProfileClientUnavailableError(AuthProfileResolutionError):
    def __init__(self) -> None:
        super().__init__(
            "Stage 21 Java login client is unavailable",
            code="AUTH_PROFILE_CLIENT_UNAVAILABLE",
        )


class AuthProfileContractError(AuthProfileResolutionError):
    def __init__(self, message: str, *, code: str = "AUTH_PROFILE_CONTRACT_INVALID") -> None:
        super().__init__(message, code=code)


class AuthProfileCredentialsMissingError(AuthProfileResolutionError):
    def __init__(self, profile: Stage21AuthProfile, missing_variables: tuple[str, ...]) -> None:
        self.profile = profile
        self.missing_variables = missing_variables
        super().__init__(
            f"credentials are missing for Stage 21 auth profile {profile.value}: "
            + ", ".join(missing_variables),
            code="AUTH_PROFILE_CREDENTIALS_MISSING",
        )


class AuthProfileLoginError(AuthProfileResolutionError):
    def __init__(self, profile: Stage21AuthProfile) -> None:
        self.profile = profile
        super().__init__(
            f"Java login failed for Stage 21 auth profile {profile.value}",
            code="AUTH_PROFILE_LOGIN_FAILED",
        )


class AuthProfileIdentityMismatchError(AuthProfileResolutionError):
    def __init__(self, profile: Stage21AuthProfile) -> None:
        self.profile = profile
        super().__init__(
            f"Java login returned an unexpected identity for {profile.value}",
            code="AUTH_PROFILE_IDENTITY_MISMATCH",
        )


class AuthProfileSessionLifetimeError(AuthProfileResolutionError):
    def __init__(self) -> None:
        super().__init__(
            "Java session has insufficient remaining lifetime for the task",
            code="AUTH_PROFILE_SESSION_LIFETIME_INSUFFICIENT",
        )


@dataclass(frozen=True, slots=True)
class Stage21Prerequisite:
    benchmark_task_id: str
    auth_profile: Stage21AuthProfile
    current_project_id: int | None
    target_project_id: int | None
    required_operations: tuple[str, ...]
    approved_tool_arguments: dict[str, JsonValue] | None
    selected_tool: str | None
    terminal_safety_decision: str | None
    candidate_validation_policy: str | None
    approval_decision: str | None
    approval_authority: str | None


@dataclass(frozen=True, slots=True)
class AuthProfileSession:
    """Non-secret identity metadata plus a private Java-issued token."""

    auth_profile: Stage21AuthProfile
    principal_id: int
    principal_label: str
    token: str = field(repr=False)
    expires_at: datetime


class JavaLoginClient(Protocol):
    async def login(self, *, username: str, password: str) -> JavaAuthenticatedSession:
        """Authenticate one configured benchmark principal through Java."""


def _coerce_profile(value: str | Stage21AuthProfile) -> Stage21AuthProfile:
    if isinstance(value, Stage21AuthProfile):
        return value
    if not isinstance(value, str):
        raise AuthProfileContractError(
            "authProfile must be one of the frozen Stage 21 profile values"
        )
    try:
        return Stage21AuthProfile(value)
    except ValueError as exc:
        raise AuthProfileContractError(
            f"unknown Stage 21 auth profile {value!r}",
            code="AUTH_PROFILE_UNKNOWN",
        ) from exc


def load_stage21_prerequisites(
    path: Path = DEFAULT_STAGE21_PREREQUISITE_PATH,
) -> dict[str, Stage21Prerequisite]:
    """Load only input-side task/profile mappings from the frozen sidecar."""

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AuthProfileContractError(
            "Stage 21 prerequisite sidecar could not be read",
            code="AUTH_PROFILE_SIDECAR_UNREADABLE",
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("tasks"), list):
        raise AuthProfileContractError(
            "Stage 21 prerequisite sidecar must contain a tasks array",
            code="AUTH_PROFILE_SIDECAR_INVALID",
        )

    prerequisites: dict[str, Stage21Prerequisite] = {}
    for index, row in enumerate(payload["tasks"]):
        if not isinstance(row, dict):
            raise AuthProfileContractError(
                f"Stage 21 prerequisite row {index} is not an object",
                code="AUTH_PROFILE_SIDECAR_INVALID",
            )
        task_id = row.get("benchmarkTaskId")
        if not isinstance(task_id, str) or not task_id.strip():
            raise AuthProfileContractError(
                f"Stage 21 prerequisite row {index} has no benchmarkTaskId",
                code="AUTH_PROFILE_SIDECAR_INVALID",
            )
        if task_id in prerequisites:
            raise AuthProfileContractError(
                f"Stage 21 prerequisite task is duplicated: {task_id}",
                code="AUTH_PROFILE_SIDECAR_DUPLICATE_TASK",
            )
        try:
            profile = _coerce_profile(row.get("authProfile"))
        except AuthProfileResolutionError as exc:
            raise AuthProfileContractError(
                f"invalid authProfile for task {task_id}",
                code=exc.code,
            ) from exc
        current_project_id = row.get("currentProjectId")
        target_project_id = row.get("targetProjectId")
        required_operations = row.get("requiredOperations")
        approved_tool_arguments = row.get("approvedToolArguments")
        selected_tool = row.get("selectedTool")
        terminal_safety_decision = row.get("terminalSafetyDecision")
        candidate_validation_policy = row.get("candidateValidationPolicy")
        approval_decision = row.get("approvalDecision")
        approval_authority = row.get("approvalAuthority")
        if (
            current_project_id is not None
            and (
                isinstance(current_project_id, bool)
                or not isinstance(current_project_id, int)
                or current_project_id < 1
            )
            or (
                target_project_id is not None
                and (
                    isinstance(target_project_id, bool)
                    or not isinstance(target_project_id, int)
                    or target_project_id < 1
                )
            )
            or not isinstance(required_operations, list)
            or not required_operations
            or any(
                not isinstance(operation, str) or not operation.strip()
                for operation in required_operations
            )
            or (
                approved_tool_arguments is not None
                and not isinstance(approved_tool_arguments, dict)
            )
            or (
                selected_tool is not None
                and (not isinstance(selected_tool, str) or not selected_tool.strip())
            )
            or terminal_safety_decision
            not in {
                None,
                "APPROVAL_REQUIRED",
                "HUMAN_REJECTED",
                "FORBIDDEN_INTENT_DENIED",
                "PROMPT_INJECTION_DENIED",
            }
            or candidate_validation_policy
            not in {None, "PRESERVE_INTENTIONAL_INVALIDITY"}
            or approval_decision not in {None, "APPROVE"}
            or approval_authority
            not in {None, "BENCHMARK_EXECUTION_PREREQUISITE"}
            or (approval_decision is None) != (approval_authority is None)
            or (
                approval_decision is not None
                and (
                    not isinstance(required_operations, list)
                    or "TOOL_CALL" not in required_operations
                    or not isinstance(approved_tool_arguments, dict)
                    or not approved_tool_arguments
                    or not isinstance(selected_tool, str)
                    or not selected_tool.strip()
                    or terminal_safety_decision is not None
                )
            )
        ):
            raise AuthProfileContractError(
                f"invalid execution contract for task {task_id}",
                code="EXECUTION_PREREQUISITE_CONTRACT_INVALID",
            )
        prerequisites[task_id] = Stage21Prerequisite(
            benchmark_task_id=task_id,
            auth_profile=profile,
            current_project_id=current_project_id,
            target_project_id=target_project_id,
            required_operations=tuple(required_operations),
            approved_tool_arguments=approved_tool_arguments,
            selected_tool=selected_tool,
            terminal_safety_decision=terminal_safety_decision,
            candidate_validation_policy=candidate_validation_policy,
            approval_decision=approval_decision,
            approval_authority=approval_authority,
        )
    return prerequisites


class AuthProfileResolver:
    """Renew the same Java identity before its token can expire during a task."""

    def __init__(
        self,
        client: JavaLoginClient,
        *,
        sidecar_path: Path = DEFAULT_STAGE21_PREREQUISITE_PATH,
        environment: Mapping[str, str] | None = None,
        minimum_validity_seconds: float = 190.0,
        clock: Callable[[], datetime] | None = None,
        session_observer: Callable[[dict], None] | None = None,
    ) -> None:
        if not callable(getattr(client, "login", None)):
            raise TypeError("client must expose an async login method")
        self._client = client
        self._environment = os.environ if environment is None else environment
        self._prerequisites = load_stage21_prerequisites(sidecar_path)
        self._sessions: dict[Stage21AuthProfile, AuthProfileSession] = {}
        if minimum_validity_seconds <= 0:
            raise ValueError("minimum_validity_seconds must be positive")
        self._minimum_validity = timedelta(seconds=minimum_validity_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._session_observer = session_observer

    def profile_for_task(self, task_id: str) -> Stage21AuthProfile:
        prerequisite = self._prerequisites.get(task_id)
        if prerequisite is None:
            raise AuthProfileContractError(
                f"no Stage 21 auth profile is assigned to task {task_id}",
                code="AUTH_PROFILE_TASK_UNASSIGNED",
            )
        return prerequisite.auth_profile

    async def resolve_for_task(self, task_id: str) -> AuthProfileSession:
        return await self.resolve(self.profile_for_task(task_id))

    async def resolve(self, value: str | Stage21AuthProfile) -> AuthProfileSession:
        profile = _coerce_profile(value)
        cached = self._sessions.get(profile)
        if cached is not None and cached.expires_at > self._clock() + self._minimum_validity:
            return cached
        # Failed renewal must never fall back to the stale session.
        self._sessions.pop(profile, None)

        username_env, password_env = PROFILE_CREDENTIAL_ENV[profile]
        username = self._environment.get(username_env, "")
        password = self._environment.get(password_env, "")
        missing = tuple(
            name
            for name, configured in (
                (username_env, bool(username.strip())),
                (password_env, bool(password.strip())),
            )
            if not configured
        )
        if missing:
            raise AuthProfileCredentialsMissingError(profile, missing)

        try:
            java_session = await self._client.login(
                username=username.strip(),
                password=password,
            )
        except AuthProfileResolutionError:
            raise
        except Exception as exc:  # noqa: BLE001 - stable failure, no secret propagation
            raise AuthProfileLoginError(profile) from exc
        if (
            java_session.username != username.strip()
            or java_session.user_id < 1
            or not java_session.token.strip()
            or (cached is not None and java_session.user_id != cached.principal_id)
        ):
            raise AuthProfileIdentityMismatchError(profile)
        now = self._clock()
        if java_session.expires_at <= now + self._minimum_validity:
            raise AuthProfileSessionLifetimeError()

        session = AuthProfileSession(
            auth_profile=profile,
            principal_id=java_session.user_id,
            principal_label=java_session.username,
            token=java_session.token,
            expires_at=java_session.expires_at,
        )
        if self._session_observer is not None:
            self._session_observer({
                "authProfile": profile.value, "principalId": session.principal_id,
                "obtainedAt": now.isoformat(), "expiresAt": session.expires_at.isoformat(),
                "minimumValiditySeconds": self._minimum_validity.total_seconds(),
                "renewed": cached is not None, "authority": "JAVA_LOGIN_RESPONSE",
            })
        self._sessions[profile] = session
        return session

    def token_provider(self, value: str | Stage21AuthProfile):
        profile = _coerce_profile(value)

        def provide() -> str:
            session = self._sessions.get(profile)
            if session is None:
                raise AuthProfileClientUnavailableError()
            if session.expires_at <= self._clock():
                raise AuthProfileSessionLifetimeError()
            return session.token

        return provide


class AuthProfileWorkflowAdapter:
    """Select an existing Stage 20 adapter after profile-scoped Java login."""

    def __init__(
        self,
        adapters: Mapping[str | Stage21AuthProfile, Stage20WorkflowAdapter],
        resolver: AuthProfileResolver,
    ) -> None:
        normalized: dict[Stage21AuthProfile, Stage20WorkflowAdapter] = {}
        for raw_profile, adapter in adapters.items():
            profile = _coerce_profile(raw_profile)
            if profile in normalized:
                raise ValueError(f"duplicate Stage 21 auth profile adapter: {profile.value}")
            if not hasattr(adapter, "execute"):
                raise TypeError("profile adapter must expose async execute")
            normalized[profile] = adapter
        missing = [profile.value for profile in Stage21AuthProfile if profile not in normalized]
        if missing:
            raise ValueError("profile adapters missing: " + ", ".join(missing))
        self._adapters = normalized
        self._resolver = resolver

    async def execute(
        self,
        task: BenchmarkTask,
        setup: FixtureSetup,
        *,
        trace_id: str,
        agent_run_id: str,
    ) -> BenchmarkExecutionOutcome:
        profile: Stage21AuthProfile | None = None
        try:
            profile = self._resolver.profile_for_task(task.benchmark_task_id)
            session = await self._resolver.resolve(profile)
        except AuthProfileResolutionError as exc:
            partial = BenchmarkExecutionOutcome(
                trace_id=trace_id,
                agent_run_id=agent_run_id,
                auth_profile=profile.value if profile is not None else None,
                java_execution_status=JavaExecutionStatus.REQUIRED_BUT_UNAVAILABLE,
            )
            raise BenchmarkTaskFailure(
                str(exc),
                category=BenchmarkFailureCategory.INFRASTRUCTURE_FAILURE,
                code=exc.code,
                partial_outcome=partial,
            ) from exc

        outcome = await self._adapters[profile].execute(
            task,
            setup,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
        )
        return replace(
            outcome,
            auth_profile=profile.value,
            principal_id=session.principal_id,
            principal_label=session.principal_label,
        )


__all__ = [
    "AuthProfileClientUnavailableError",
    "AuthProfileContractError",
    "AuthProfileCredentialsMissingError",
    "AuthProfileLoginError",
    "AuthProfileResolutionError",
    "AuthProfileResolver",
    "AuthProfileSession",
    "AuthProfileWorkflowAdapter",
    "DEFAULT_STAGE21_PREREQUISITE_PATH",
    "PROFILE_CREDENTIAL_ENV",
    "JavaLoginClient",
    "Stage21AuthProfile",
    "Stage21Prerequisite",
    "load_stage21_prerequisites",
]
