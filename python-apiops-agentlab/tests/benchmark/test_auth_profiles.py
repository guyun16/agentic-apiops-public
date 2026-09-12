"""Deterministic tests for Stage 21 profile-to-Java-login wiring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest

from app.benchmark import (
    AuthProfileContractError,
    AuthProfileCredentialsMissingError,
    AuthProfileLoginError,
    AuthProfileResolver,
    AuthProfileWorkflowAdapter,
    BenchmarkExecutionOutcome,
    BenchmarkRunner,
    BenchmarkTaskFailure,
    BenchmarkTaskStatus,
    FixtureSetup,
    Stage21AuthProfile,
    load_dataset,
    load_stage21_prerequisites,
)
from app.benchmark.auth_profiles import (
    AuthProfileClientUnavailableError,
    AuthProfileIdentityMismatchError,
    AuthProfileSessionLifetimeError,
)
from app.clients.java_apiops import JavaAuthenticatedSession


class FakeJavaLoginClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail

    async def login(self, *, username: str, password: str) -> JavaAuthenticatedSession:
        self.calls.append((username, password))
        if self.fail:
            raise RuntimeError("login failed")
        user_id = {
            "normal": 7,
            "safety41": 8,
            "safety42": 9,
        }[username]
        return JavaAuthenticatedSession(
            user_id=user_id,
            username=username,
            token_type="Bearer",
            token=f"token-{username}",
            expires_at=datetime.now(UTC) + timedelta(minutes=15),
        )


@pytest.mark.anyio
async def test_long_run_renews_before_task_budget_without_replaying_tasks() -> None:
    from dataclasses import replace

    now = [datetime(2026, 9, 6, tzinfo=UTC)]
    client = FakeJavaLoginClient()
    login = client.login

    async def timed_login(**kwargs):
        return replace(await login(**kwargs), expires_at=now[0] + timedelta(minutes=15),
                       token=f"renewed-{len(client.calls)}")

    client.login = timed_login
    events = []
    resolver = AuthProfileResolver(client, environment=profile_environment(),
                                   clock=lambda: now[0], session_observer=events.append)
    first = await resolver.resolve(Stage21AuthProfile.NORMAL)
    now[0] += timedelta(minutes=11)
    assert await resolver.resolve(Stage21AuthProfile.NORMAL) is first
    now[0] += timedelta(minutes=1)
    second = await resolver.resolve(Stage21AuthProfile.NORMAL)
    assert second.token != first.token
    assert second.principal_id == first.principal_id
    now[0] += timedelta(minutes=4)
    # The original token is now expired, but the new one remains valid.
    assert resolver.token_provider(Stage21AuthProfile.NORMAL)() == second.token
    assert await resolver.resolve(Stage21AuthProfile.NORMAL) is second
    assert len(client.calls) == 2
    assert [event['renewed'] for event in events] == [False, True]
    assert all('token' not in key.lower() for event in events for key in event)


@pytest.mark.anyio
@pytest.mark.parametrize('failure', ['login', 'short_lifetime', 'identity'])
async def test_renewal_failure_never_uses_stale_token_or_switches_identity(failure) -> None:
    from dataclasses import replace

    now = [datetime.now(UTC)]
    client = FakeJavaLoginClient()
    resolver = AuthProfileResolver(client, environment=profile_environment(), clock=lambda: now[0])
    first = await resolver.resolve(Stage21AuthProfile.NORMAL)
    now[0] = first.expires_at - timedelta(seconds=180)
    login = client.login

    async def invalid_login(**kwargs):
        session = await login(**kwargs)
        if failure == 'short_lifetime':
            return replace(session, expires_at=now[0] + timedelta(seconds=190))
        return replace(session, user_id=session.user_id + 1)

    if failure == 'login':
        client.fail = True
    else:
        client.login = invalid_login
    error = {'login': AuthProfileLoginError, 'short_lifetime': AuthProfileSessionLifetimeError,
             'identity': AuthProfileIdentityMismatchError}[failure]
    with pytest.raises(error):
        await resolver.resolve(Stage21AuthProfile.NORMAL)
    with pytest.raises(AuthProfileClientUnavailableError):
        resolver.token_provider(Stage21AuthProfile.NORMAL)()
    assert all(username == 'normal' for username, _ in client.calls)


@pytest.mark.anyio
async def test_token_provider_rejects_expired_session_before_java_request() -> None:
    now = [datetime.now(UTC)]
    resolver = AuthProfileResolver(FakeJavaLoginClient(), environment=profile_environment(),
                                   clock=lambda: now[0])
    session = await resolver.resolve(Stage21AuthProfile.NORMAL)
    now[0] = session.expires_at
    with pytest.raises(AuthProfileSessionLifetimeError):
        resolver.token_provider(Stage21AuthProfile.NORMAL)()


@dataclass
class RecordingAdapter:
    calls: list[str]

    async def execute(
        self,
        task,
        setup: FixtureSetup,
        *,
        trace_id: str,
        agent_run_id: str,
    ) -> BenchmarkExecutionOutcome:
        del setup
        self.calls.append(task.benchmark_task_id)
        return BenchmarkExecutionOutcome(
            trace_id=trace_id,
            agent_run_id=agent_run_id,
        )


def profile_environment() -> dict[str, str]:
    return {
        "STAGE21_NORMAL_USERNAME": "normal",
        "STAGE21_NORMAL_PASSWORD": "normal-password",
        "STAGE21_SAFETY41_USERNAME": "safety41",
        "STAGE21_SAFETY41_PASSWORD": "safety41-password",
        "STAGE21_SAFETY42_USERNAME": "safety42",
        "STAGE21_SAFETY42_PASSWORD": "safety42-password",
    }


@pytest.mark.anyio
async def test_each_profile_logs_in_once_and_keeps_distinct_java_identity() -> None:
    client = FakeJavaLoginClient()
    resolver = AuthProfileResolver(client, environment=profile_environment())

    sessions = {profile: await resolver.resolve(profile) for profile in Stage21AuthProfile}
    await resolver.resolve(Stage21AuthProfile.NORMAL)

    assert [call[0] for call in client.calls] == ["normal", "safety41", "safety42"]
    assert [session.principal_id for session in sessions.values()] == [7, 8, 9]
    assert [session.principal_label for session in sessions.values()] == [
        "normal",
        "safety41",
        "safety42",
    ]
    assert resolver.token_provider(Stage21AuthProfile.NORMAL)() == "token-normal"
    assert resolver.token_provider(Stage21AuthProfile.SAFETY_41_ISOLATED)() == "token-safety41"
    assert resolver.token_provider(Stage21AuthProfile.SAFETY_42_ISOLATED)() == "token-safety42"


@pytest.mark.anyio
async def test_unknown_profile_and_missing_credentials_fail_closed() -> None:
    client = FakeJavaLoginClient()
    resolver = AuthProfileResolver(client, environment={})

    with pytest.raises(AuthProfileContractError) as unknown:
        await resolver.resolve("UNASSIGNED")
    assert unknown.value.code == "AUTH_PROFILE_UNKNOWN"

    with pytest.raises(AuthProfileCredentialsMissingError) as missing:
        await resolver.resolve(Stage21AuthProfile.NORMAL)
    assert missing.value.code == "AUTH_PROFILE_CREDENTIALS_MISSING"
    assert missing.value.missing_variables == (
        "STAGE21_NORMAL_USERNAME",
        "STAGE21_NORMAL_PASSWORD",
    )
    assert client.calls == []


@pytest.mark.anyio
async def test_java_login_failure_fails_closed_without_a_fallback_profile() -> None:
    resolver = AuthProfileResolver(
        FakeJavaLoginClient(fail=True),
        environment=profile_environment(),
    )

    with pytest.raises(AuthProfileLoginError) as error:
        await resolver.resolve(Stage21AuthProfile.SAFETY_41_ISOLATED)
    assert error.value.code == "AUTH_PROFILE_LOGIN_FAILED"


@pytest.mark.anyio
async def test_workflow_fails_before_model_adapter_when_profile_credentials_are_missing() -> None:
    client = FakeJavaLoginClient()
    resolver = AuthProfileResolver(client, environment={})
    adapter = RecordingAdapter([])
    workflow = AuthProfileWorkflowAdapter(
        {profile: adapter for profile in Stage21AuthProfile},
        resolver,
    )
    task = next(
        task
        for task in load_dataset().tasks
        if task.benchmark_task_id == "bench_task_golden_testcase_happy"
    )

    with pytest.raises(BenchmarkTaskFailure) as error:
        await workflow.execute(
            task,
            FixtureSetup(),
            trace_id="trace-missing-credentials",
            agent_run_id="agent-missing-credentials",
        )

    assert error.value.code == "AUTH_PROFILE_CREDENTIALS_MISSING"
    assert error.value.partial_outcome is not None
    assert error.value.partial_outcome.auth_profile == "NORMAL"
    assert error.value.partial_outcome.java_execution_status.value == ("REQUIRED_BUT_UNAVAILABLE")
    assert adapter.calls == []
    assert client.calls == []


@pytest.mark.anyio
async def test_task_uses_one_frozen_profile_and_never_switches_adapter_identity() -> None:
    client = FakeJavaLoginClient()
    resolver = AuthProfileResolver(client, environment=profile_environment())
    adapters = {profile: RecordingAdapter([]) for profile in Stage21AuthProfile}
    workflow = AuthProfileWorkflowAdapter(adapters, resolver)
    task = next(
        task
        for task in load_dataset().tasks
        if task.benchmark_task_id == "bench_task_golden_tool_safety"
    )

    outcome = await workflow.execute(
        task,
        FixtureSetup(),
        trace_id="trace-profile",
        agent_run_id="agent-profile",
    )

    assert adapters[Stage21AuthProfile.SAFETY_41_ISOLATED].calls == [
        "bench_task_golden_tool_safety"
    ]
    assert adapters[Stage21AuthProfile.NORMAL].calls == []
    assert adapters[Stage21AuthProfile.SAFETY_42_ISOLATED].calls == []
    assert outcome.auth_profile == "SAFETY_41_ISOLATED"
    assert outcome.principal_id == 8
    assert outcome.principal_label == "safety41"
    assert [call[0] for call in client.calls] == ["safety41"]


@pytest.mark.anyio
async def test_runner_artifact_retains_profile_identity_without_retaining_token() -> None:
    client = FakeJavaLoginClient()
    resolver = AuthProfileResolver(client, environment=profile_environment())
    adapters = {profile: RecordingAdapter([]) for profile in Stage21AuthProfile}
    workflow = AuthProfileWorkflowAdapter(adapters, resolver)
    dataset = load_dataset()
    task = next(
        task for task in dataset.tasks if task.benchmark_task_id == "bench_task_golden_tool_safety"
    )
    ground_truth = next(
        truth
        for truth in dataset.ground_truths
        if truth.ground_truth_id == task.ground_truth_ref.ground_truth_id
        and truth.version == task.ground_truth_ref.version
    )

    result = await BenchmarkRunner(workflow).run_task(
        task,
        ground_truth,
        evaluation_run_id="evaluation_run:auth-profile",
    )

    assert result.status is BenchmarkTaskStatus.SUCCESS
    assert result.auth_profile == "SAFETY_41_ISOLATED"
    assert result.principal_id == 8
    assert result.principal_label == "safety41"
    assert "token-safety41" not in result.model_dump_json()


def test_frozen_sidecar_assigns_every_active_task_to_a_supported_profile() -> None:
    dataset = load_dataset()
    prerequisites = load_stage21_prerequisites()
    active_ids = {entry.benchmark_task_id for entry in dataset.manifest.tasks}

    assert len(prerequisites) == 105
    assert set(prerequisites) == active_ids
    assert all(
        prerequisite.auth_profile in Stage21AuthProfile for prerequisite in prerequisites.values()
    )
