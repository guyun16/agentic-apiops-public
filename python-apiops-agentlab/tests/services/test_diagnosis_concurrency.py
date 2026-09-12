"""Cross-connection exclusion and crash recovery without provider calls."""

import asyncio
import multiprocessing

import pytest
from pydantic import SecretStr

from app.core.errors import ApplicationError
from app.core.settings import AppSettings
from app.services.diagnosis import DiagnosisExecutionService
from app.services.diagnosis_repository import SQLiteDiagnosisRunRepository
from tests.services.test_diagnosis_repository import _test_report, stored_run


def _worker(database, ready):
    repository = SQLiteDiagnosisRunRepository(database)
    with repository.execution_lock(41, 701):
        repository.save(stored_run(status="RUNNING"))
        ready.set()
        # Parent terminates this process to simulate a crash while holding the lock.
        import time

        time.sleep(60)


def test_process_crash_releases_lock_and_recovers_only_running(tmp_path):
    path = str(tmp_path / "runtime.sqlite3")
    context = multiprocessing.get_context("spawn")
    ready = context.Event()
    process = context.Process(target=_worker, args=(path, ready))
    process.start()
    try:
        assert ready.wait(20)
        with SQLiteDiagnosisRunRepository(path) as repository:
            repository.recover_interrupted(41)
            assert repository.get("agent_run:1").status == "RUNNING"
            with pytest.raises(ApplicationError, match="already executing"):
                with repository.execution_lock(41, 701):
                    pytest.fail("live worker lock was stolen")
            # A separate project/run remains independent.
            with repository.execution_lock(42, 701):
                pass
        process.terminate()
        process.join(10)
        assert not process.is_alive()
        with SQLiteDiagnosisRunRepository(path) as repository:
            repository.save(stored_run(agent_run_id="pending", workflow_id="pending"))
            repository.recover_interrupted(41)
            recovered = repository.get("agent_run:1")
            assert recovered.status == "FAILED"
            assert recovered.failure.code == "DIAGNOSIS_INTERRUPTED"
            assert repository.get("pending").status == "APPROVAL_REQUIRED"
            with repository.execution_lock(41, 701):
                pass
    finally:
        if process.is_alive():
            process.terminate()
        process.join(10)


@pytest.mark.anyio
async def test_two_services_start_once_and_cancelled_request_becomes_retryable(
    monkeypatch, tmp_path
):
    path = tmp_path / "runtime.sqlite3"
    settings = AppSettings(deepseek_api_key=SecretStr("test-key"))
    repositories = [SQLiteDiagnosisRunRepository(path) for _ in range(2)]
    services = [DiagnosisExecutionService(settings, run_repository=r) for r in repositories]
    entered = asyncio.Event()
    calls = []

    async def fetch(**kwargs):
        return _test_report()

    async def invoke(**kwargs):
        calls.append(kwargs["record"].agent_run_id)
        entered.set()
        await asyncio.Event().wait()

    for service in services:
        monkeypatch.setattr(service, "_fetch_report", fetch)
        monkeypatch.setattr(service, "_invoke", invoke)
    arguments = dict(project_id=41, run_id=701, token="test", trace_id="trace:test")
    task = asyncio.create_task(services[0].start(**arguments))
    try:
        await asyncio.wait_for(entered.wait(), 5)
        with pytest.raises(ApplicationError) as error:
            await services[1].start(**arguments)
        assert error.value.code == "DIAGNOSIS_ALREADY_RUNNING"
        assert len(calls) == 1
        assert services[1].list(project_id=41)[0].status == "RUNNING"
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        history = services[1].list(project_id=41)
        assert history[0].status == "FAILED"
        recovered = await services[1].get(agent_run_id=calls[0], token="test")
        assert recovered.failure.code == "DIAGNOSIS_INTERRUPTED"
        entered.clear()
        task = asyncio.create_task(services[1].start(**arguments))
        await asyncio.wait_for(entered.wait(), 5)
        assert len(calls) == 2
        assert calls[0] != calls[1]
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        for repository in repositories:
            repository.close()


@pytest.mark.anyio
@pytest.mark.parametrize("status", ["APPROVAL_REQUIRED", "COMPLETED"])
async def test_start_returns_existing_result_without_model_call(monkeypatch, tmp_path, status):
    with SQLiteDiagnosisRunRepository(tmp_path / "runtime.sqlite3") as repository:
        repository.save(stored_run(status=status))
        service = DiagnosisExecutionService(AppSettings(), run_repository=repository)

        async def fetch(**kwargs):
            return _test_report()

        monkeypatch.setattr(service, "_fetch_report", fetch)
        result = await service.start(project_id=41, run_id=701, token="test", trace_id="trace:test")
        assert result.agent_run_id == "agent_run:1"
        assert result.status == status
