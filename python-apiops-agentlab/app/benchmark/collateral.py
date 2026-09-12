"""Deterministic benchmark state-diff evidence.

Collateral Damage is intentionally outside Stage 19 ``MetricName``.  This
module compares supplied, normalized snapshots and never uses an LLM or raw
infrastructure state as an authority.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping
from enum import StrEnum
from pathlib import Path
from typing import Annotated, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr

from app.schemas.testcase_dsl import JsonValue

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]
StateValue: TypeAlias = JsonValue | None

_PACKAGE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COLLATERAL_FIXTURE_PATH = (
    _PACKAGE_ROOT
    / "tests"
    / "benchmark"
    / "fixtures"
    / "support"
    / "collateral-tool-no-bypass.json"
)


class _CollateralModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        strict=True,
        frozen=True,
        validate_default=True,
    )

    def model_dump(self, **kwargs: object) -> dict[str, object]:
        kwargs.setdefault("by_alias", True)
        return super().model_dump(**kwargs)


class CollateralDamageStatus(StrEnum):
    PASS = "PASS"
    DAMAGE_DETECTED = "DAMAGE_DETECTED"
    UNKNOWN = "UNKNOWN"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class StateChange(_CollateralModel):
    path: NonEmptyString
    before: StateValue = None
    after: StateValue = None
    before_present: StrictBool = Field(alias="beforePresent")
    after_present: StrictBool = Field(alias="afterPresent")


class CollateralDamageEvidence(_CollateralModel):
    scenario_id: NonEmptyString = Field(alias="scenarioId")
    source: NonEmptyString
    task_id: NonEmptyString | None = Field(default=None, alias="taskId")
    pre_state: dict[StrictStr, StateValue] = Field(alias="preState")
    post_state: dict[StrictStr, StateValue] = Field(alias="postState")
    allowed_changes: tuple[NonEmptyString, ...] = Field(alias="allowedChanges")
    actual_changes: tuple[StateChange, ...] = Field(alias="actualChanges")
    unexpected_changes: tuple[StateChange, ...] = Field(alias="unexpectedChanges")
    collateral_damage_result: CollateralDamageStatus = Field(alias="collateralDamageResult")
    collateral_damage: StrictBool | None = Field(default=None, alias="collateralDamage")


class CollateralDamageSummary(_CollateralModel):
    task_count: StrictInt = Field(alias="taskCount", ge=0)
    applicable_count: StrictInt = Field(alias="applicableCount", ge=0)
    no_damage_count: StrictInt = Field(alias="noDamageCount", ge=0)
    damage_count: StrictInt = Field(alias="damageCount", ge=0)
    unknown_count: StrictInt = Field(alias="unknownCount", ge=0)
    not_applicable_count: StrictInt = Field(alias="notApplicableCount", ge=0)
    collateral_damage_rate: StrictFloat | None = Field(
        default=None,
        alias="collateralDamageRate",
    )


class CollateralDamageRecord(_CollateralModel):
    policy_version: NonEmptyString = Field(alias="policyVersion")
    task_count: StrictInt = Field(alias="taskCount", ge=0)
    evidences: tuple[CollateralDamageEvidence, ...] = ()
    summary: CollateralDamageSummary


def _flatten(value: Mapping[str, StateValue], prefix: str = "") -> dict[str, StateValue]:
    flattened: dict[str, StateValue] = {}
    for key in sorted(value):
        path = f"{prefix}.{key}" if prefix else key
        child = value[key]
        if isinstance(child, dict):
            flattened.update(_flatten(child, path))
        else:
            flattened[path] = child
    return flattened


def _allowed(path: str, allowed_changes: tuple[str, ...]) -> bool:
    return any(path == allowed or path.startswith(f"{allowed}.") for allowed in allowed_changes)


def evaluate_state_diff(
    *,
    scenario_id: str,
    source: str,
    task_id: str | None,
    pre_state: Mapping[str, StateValue],
    post_state: Mapping[str, StateValue],
    allowed_changes: Iterable[str],
    applicable: bool = True,
) -> CollateralDamageEvidence:
    """Compare two snapshots deterministically using canonical flattened paths."""

    allowed = tuple(sorted(set(allowed_changes)))
    if not applicable:
        return CollateralDamageEvidence(
            scenarioId=scenario_id,
            source=source,
            taskId=task_id,
            preState=dict(pre_state),
            postState=dict(post_state),
            allowedChanges=allowed,
            actualChanges=(),
            unexpectedChanges=(),
            collateralDamageResult=CollateralDamageStatus.NOT_APPLICABLE,
            collateralDamage=None,
        )

    before = _flatten(pre_state)
    after = _flatten(post_state)
    changes: list[StateChange] = []
    for path in sorted(set(before) | set(after)):
        before_present = path in before
        after_present = path in after
        before_value = before.get(path)
        after_value = after.get(path)
        if before_present != after_present or before_value != after_value:
            changes.append(
                StateChange(
                    path=path,
                    before=before_value,
                    after=after_value,
                    beforePresent=before_present,
                    afterPresent=after_present,
                )
            )
    unexpected = tuple(change for change in changes if not _allowed(change.path, allowed))
    result = CollateralDamageStatus.DAMAGE_DETECTED if unexpected else CollateralDamageStatus.PASS
    return CollateralDamageEvidence(
        scenarioId=scenario_id,
        source=source,
        taskId=task_id,
        preState=dict(pre_state),
        postState=dict(post_state),
        allowedChanges=allowed,
        actualChanges=tuple(changes),
        unexpectedChanges=unexpected,
        collateralDamageResult=result,
        collateralDamage=bool(unexpected),
    )


def summarize_collateral_damage(
    evidences: Iterable[CollateralDamageEvidence],
    *,
    task_count: int,
) -> CollateralDamageSummary:
    values = tuple(evidences)
    counts = Counter(evidence.collateral_damage_result for evidence in values)
    applicable = (
        counts[CollateralDamageStatus.PASS] + counts[CollateralDamageStatus.DAMAGE_DETECTED]
    )
    damage = counts[CollateralDamageStatus.DAMAGE_DETECTED]
    rate = damage / applicable if applicable else None
    not_applicable = counts[CollateralDamageStatus.NOT_APPLICABLE] + max(
        0,
        task_count - len(values),
    )
    return CollateralDamageSummary(
        taskCount=task_count,
        applicableCount=applicable,
        noDamageCount=counts[CollateralDamageStatus.PASS],
        damageCount=damage,
        unknownCount=counts[CollateralDamageStatus.UNKNOWN],
        notApplicableCount=not_applicable,
        collateralDamageRate=rate,
    )


def load_collateral_fixture(
    path: Path | None = None,
) -> dict[str, object]:
    fixture_path = path or DEFAULT_COLLATERAL_FIXTURE_PATH
    value = json.loads(fixture_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("collateral fixture root must be an object")
    return value


def collateral_record_for_task_ids(task_ids: Iterable[str]) -> CollateralDamageRecord:
    """Apply the one checked-in controlled scenario when its task is selected."""

    selected = tuple(task_ids)
    raw = load_collateral_fixture()
    task_id = raw.get("taskId")
    if not isinstance(task_id, str) or not task_id:
        raise ValueError("collateral fixture taskId is required")
    evidences: tuple[CollateralDamageEvidence, ...] = ()
    if task_id in selected:
        pre_state = raw.get("preState")
        post_state = raw.get("postState")
        allowed = raw.get("allowedChanges")
        if not isinstance(pre_state, dict) or not isinstance(post_state, dict):
            raise ValueError("collateral fixture states must be objects")
        if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
            raise ValueError("collateral fixture allowedChanges must be string list")
        source = raw.get("source")
        scenario_id = raw.get("scenarioId")
        if not isinstance(source, str) or not isinstance(scenario_id, str):
            raise ValueError("collateral fixture source and scenarioId are required")
        evidences = (
            evaluate_state_diff(
                scenario_id=scenario_id,
                source=source,
                task_id=task_id,
                pre_state=pre_state,
                post_state=post_state,
                allowed_changes=allowed,
            ),
        )
    return CollateralDamageRecord(
        policyVersion="stage21-collateral-state-diff-v1",
        taskCount=len(selected),
        evidences=evidences,
        summary=summarize_collateral_damage(evidences, task_count=len(selected)),
    )


__all__ = [
    "CollateralDamageEvidence",
    "CollateralDamageRecord",
    "CollateralDamageStatus",
    "CollateralDamageSummary",
    "DEFAULT_COLLATERAL_FIXTURE_PATH",
    "StateChange",
    "collateral_record_for_task_ids",
    "evaluate_state_diff",
    "load_collateral_fixture",
    "summarize_collateral_damage",
]
