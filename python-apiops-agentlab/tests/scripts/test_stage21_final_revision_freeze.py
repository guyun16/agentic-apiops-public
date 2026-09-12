"""Known limitations affect admission only, never outcome or shared security strength."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts"))
import freeze_benchmark_portfolio as portfolio_freeze  # noqa: E402
import stage21_final_revision_freeze as freeze  # noqa: E402
import stage21_final_revision_gate as gate  # noqa: E402
import stage21_final_v2_formal105 as formal  # noqa: E402

from app.core.settings import AppSettings  # noqa: E402


def inputs() -> dict:
    return {
        "runtime": {"status": "PASS", "nonReadyTaskIds": [], "unresolvedJavaResourceCount": 0},
        "provider": {"status": "PASS", "provider": "Qwen", "model": "qwen3.8-max"},
        "path": {"overBudgetCount": 0, "uniqueTaskPaths": 105},
        "integrity": {"status": "PASS"},
        "limitation": gate.known_limitation(),
    }


def test_single_disclosed_gap_allows_admission_without_task_or_outcome_changes() -> None:
    before = inputs()
    saved = copy.deepcopy(before)
    decision = gate.admission_decision(**before)
    assert before == saved
    assert decision["status"] == "ALLOW_WITH_KNOWN_LIMITATION"
    assert decision["taskCount"] == 105
    assert decision["minimumPassCountFor85Percent"] == 90
    assert decision["authorityReadiness"] == "INCOMPLETE_NOT_READY"
    assert decision["prepopulatesOutcomes"] is False
    assert decision["excludedTaskIds"] == []
    assert decision["runtimeSecurityProviderPathPersistenceExemptions"] == []
    assert formal.BENCHMARK_CONTRACT_REVISION == gate.CONFIG["revision"]


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        ("runtime", "status", "FAIL"),
        ("runtime", "nonReadyTaskIds", [gate.KNOWN_TASK]),
        ("runtime", "nonReadyTaskIds", ["another_task"]),
        ("runtime", "unresolvedJavaResourceCount", 1),
        ("runtime", "classificationCounts", {"AUTH_PREREQUISITE_GAP": 1}),
        ("runtime", "classificationCounts", {"REAL_JAVA_BUG": 1}),
        ("provider", "status", "PROVIDER_UNPROVEN"),
        ("provider", "provider", "DeepSeek"),
        ("provider", "model", "qwen3.7-plus-2026-05-26"),
        ("path", "overBudgetCount", 1),
        ("path", "uniqueTaskPaths", 104),
        ("integrity", "status", "FAIL"),
    ],
)
def test_shared_failures_cannot_be_exempted(section: str, key: str, value: object) -> None:
    values = inputs()
    values[section][key] = value
    with pytest.raises(RuntimeError, match="ADMISSION_BLOCKED"):
        gate.admission_decision(**values)


def test_new_blocker_and_widened_limitation_fail_closed() -> None:
    with pytest.raises(RuntimeError, match="ADMISSION_BLOCKED"):
        gate.admission_decision(**inputs(), additional_blockers=("NEW_INFRASTRUCTURE_FAILURE",))
    values = inputs()
    values["limitation"]["limitations"].append(values["limitation"]["limitations"][0].copy())
    with pytest.raises(RuntimeError, match="ADMISSION_BLOCKED"):
        gate.admission_decision(**values)


@pytest.mark.parametrize(
    "field,value",
    [
        ("qwen_model", "wrong-model"),
        ("qwen_base_url", "https://wrong.invalid/v1"),
        ("qwen_timeout_seconds", 600),
    ],
)
def test_provider_configuration_drift(field: str, value: object) -> None:
    with pytest.raises(RuntimeError, match="CONFIGURATION_DRIFT"):
        gate.configuration_check(AppSettings(**{field: value}))


def test_missing_freeze_blocks_before_official_identity_or_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        pytest.fail("must not create an official ID or execute a task")

    monkeypatch.setattr(formal.baseline, "_new_evaluation_run_id", forbidden)
    monkeypatch.setattr(formal, "_execute_baseline_once", forbidden)
    output = tmp_path / "not-created"
    with pytest.raises(RuntimeError, match="revision-freeze"):
        asyncio.run(formal._run_once(AppSettings(), output))
    assert not output.exists()


def test_frozen_source_and_evidence_drift_are_blockers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(gate, "source_inventory", lambda: {"source.py": "current"})
    evidence = tmp_path / "evidence.json"
    evidence.write_text("{}", encoding="utf-8")
    manifest = {
        "finalRevision": gate.FINAL_REVISION,
        "freezeStatus": "FROZEN_WITH_KNOWN_LIMITATION",
        "configuration": gate.CONFIG,
        "knownLimitations": gate.known_limitation(),
        "admission": {"status": "ALLOW_WITH_KNOWN_LIMITATION"},
        "sourceInventory": {"source.py": "current"},
        "evidenceDigests": {str(evidence): gate.digest(evidence)},
    }
    path = tmp_path / "freeze.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    assert gate.verify_frozen_revision(path, AppSettings())["finalRevision"] == gate.FINAL_REVISION
    manifest["freezeStatus"] = "PENDING_VALIDATION"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="FREEZE_OR_SOURCE_DRIFT"):
        gate.verify_frozen_revision(path, AppSettings())
    manifest["freezeStatus"] = "FROZEN_WITH_KNOWN_LIMITATION"
    manifest["sourceInventory"]["source.py"] = "stale"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="SOURCE_DRIFT"):
        gate.verify_frozen_revision(path, AppSettings())
    manifest["sourceInventory"]["source.py"] = "current"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    evidence.write_text("changed", encoding="utf-8")
    with pytest.raises(RuntimeError, match="EVIDENCE_DRIFT"):
        gate.verify_frozen_revision(path, AppSettings())


@pytest.mark.parametrize("failure", [None, "health", "unauth", "login", "allow_cross", "contract"])
def test_live_shared_checks_and_local_scope_are_independent(
    failure: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Http:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            if url.endswith("/api/v1/projects/41"):
                return httpx.Response(200 if failure == "unauth" else 401, json={"code": "A0004"})
            return httpx.Response(503 if failure == "health" else 200)

    class Resolver:
        async def resolve(self, profile):
            if failure == "login":
                raise RuntimeError("SHARED_LOGIN_FAILED")
            return SimpleNamespace(token=profile)

    class Java:
        async def assert_project_readable(self, *, project_id, token, **kwargs):
            if (token, project_id) in {("SAFETY_41_ISOLATED", 42), ("SAFETY_42_ISOLATED", 41)}:
                if failure != "allow_cross":
                    raise gate.JavaApiOpsAuthorizationError("denied")

        async def get_api_metadata(self, **kwargs):
            return SimpleNamespace(
                api_id="stage21-auth-api-key",
                method="POST",
                path="/stage21/auth-check",
                response_schemas=["new-authority"] if failure == "contract" else [],
            )

    monkeypatch.setattr(gate.httpx, "AsyncClient", lambda **kwargs: Http())
    monkeypatch.setattr(gate, "JavaApiOpsClient", lambda *args, **kwargs: Java())
    monkeypatch.setattr(gate, "AuthProfileResolver", lambda *args: Resolver())
    if failure is None:
        result = asyncio.run(gate.shared_live_preflight(AppSettings()))
        assert result["status"] == "PASS"
        assert result["localContract"]["authorityReadiness"] == "INCOMPLETE_NOT_READY"
        assert result["modelCallCount"] == result["runnerSubmitCount"] == 0
        assert len(result["profiles"]) == 3
    else:
        with pytest.raises(RuntimeError):
            asyncio.run(gate.shared_live_preflight(AppSettings()))


def test_persistence_probe_does_not_leave_artifacts(tmp_path: Path) -> None:
    assert gate.persistence_probe(tmp_path)["status"] == "PASS"
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(RuntimeError, match="PARENT_MISSING"):
        gate.persistence_probe(tmp_path / "missing")


def test_parent_acceptance_rejects_new_contract_and_matches_preserved_sources() -> None:
    with pytest.raises(RuntimeError, match="ACCEPTANCE_IMPLEMENTATION_SOURCE_DRIFT"):
        freeze.verify_prior_evidence()
    evidence = portfolio_freeze.verify()
    assert evidence["purpose"] == "PORTFOLIO_PUBLICATION_ACCEPTANCE"
    assert evidence["benchmarkExecuted"] is False
    assert evidence["modelCalled"] is False
    assert evidence["previousFreezeSha256"] == portfolio_freeze.digest(
        portfolio_freeze.PREVIOUS_OUTPUT
    )


def test_publication_freeze_still_rejects_drift_and_overwrite(tmp_path, monkeypatch) -> None:
    source = {"fixture": "original"}
    monkeypatch.setattr(portfolio_freeze, "inventory", lambda: dict(source))
    path = tmp_path / "freeze.json"
    portfolio_freeze.write(path)
    portfolio_freeze.verify(path)
    with pytest.raises(RuntimeError, match="ALREADY_EXISTS"):
        portfolio_freeze.write(path)
    source["fixture"] = "changed"
    with pytest.raises(RuntimeError, match="PORTFOLIO_SOURCE_DRIFT"):
        portfolio_freeze.verify(path)


def test_publication_source_inventory_normalizes_only_checkout_line_endings(tmp_path, monkeypatch):
    monkeypatch.setattr(portfolio_freeze, "ROOT", tmp_path)
    monkeypatch.setattr(portfolio_freeze, "SOURCES", ("source.ts",))
    source = tmp_path / "source.ts"
    source.write_bytes(b"const result = 1\r\n")
    original = portfolio_freeze.inventory()
    source.write_bytes(b"const result = 1\n")
    assert portfolio_freeze.inventory() == original
    source.write_bytes(b"const result = 2\n")
    assert portfolio_freeze.inventory() != original


def test_public_development_default_does_not_hide_confidential_or_changed_values(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(freeze, "ROOT", tmp_path)
    public_value = "public-demo-default"
    monkeypatch.setattr(
        freeze,
        "PUBLIC_LOCAL_BROKER_DEFAULT_SHA256",
        hashlib.sha256(public_value.encode()).hexdigest(),
    )
    script = tmp_path / "scripts/stage21_start_live_services.ps1"
    script.parent.mkdir()
    script.write_text(f"$env:APIOPS_RABBITMQ_PASSWORD = '{public_value}'", encoding="utf-8")
    monkeypatch.setenv("APIOPS_RABBITMQ_PASSWORD", public_value)
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    path = tmp_path / "fixture.txt"
    path.write_text(public_value, encoding="utf-8")
    source = {
        "fixture.txt": gate.digest(path),
        "scripts/stage21_start_live_services.ps1": gate.digest(script),
    }
    scan = freeze.source_credential_findings(source, source, (public_value, "private-test-value"))
    assert scan["confidentialMatchingPaths"] == []
    assert "fixture.txt" in scan["unchangedPublicDevelopmentDefaultPaths"]
    assert scan["artifactScanExemptions"] == scan["runtimeSecurityExemptions"] == []
    assert freeze.source_credential_findings(source, {}, (public_value,))[
        "confidentialMatchingPaths"
    ]
    monkeypatch.setenv("QWEN_API_KEY", public_value)
    assert freeze.source_credential_findings(source, source, (public_value,))[
        "confidentialMatchingPaths"
    ]
    monkeypatch.setenv("QWEN_API_KEY", "private-test-value")
    path.write_text("private-test-value", encoding="utf-8")
    source["fixture.txt"] = gate.digest(path)
    assert freeze.source_credential_findings(source, source, (public_value, "private-test-value"))[
        "confidentialMatchingPaths"
    ]
