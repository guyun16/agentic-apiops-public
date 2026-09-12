"""Six-task scope, historical baseline, and fail-closed replay configuration."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
import stage21_final_six_closure as six  # noqa: E402


def test_exact_declared_six_match_all_remaining_historical_nonpass() -> None:
    assert len(six.TARGETS) == len(set(six.TARGETS)) == 6
    assert not set(six.TARGETS) & set(six.CONTROLS)
    assert len(six.CONTROLS) == 4
    assert set(six.RAG_CONFIRMATION_TASKS) == {six.TARGETS[0], six.CONTROLS[0]}
    six.validate_baseline()


@pytest.mark.parametrize("task_ids", [(), ("a", "a"), tuple(map(str, range(105)))])
def test_invalid_explicit_scope_fails_before_creating_artifacts(tmp_path, task_ids) -> None:
    output = tmp_path / "not-created"
    with pytest.raises(six.closure.ClosureFailure, match="EXPLICIT_TARGETED_SCOPE_INVALID"):
        asyncio.run(six.closure._run(
            output, tmp_path, replay_task_ids=task_ids, candidate_revision=six.REVISION,
        ))
    assert not output.exists()


def test_explicit_scope_cannot_mix_confirmation_mode_or_omit_revision(tmp_path) -> None:
    for options in ({}, {"candidate_revision": six.REVISION,
                         "zero_hit_confirmation_root": tmp_path}):
        with pytest.raises(six.closure.ClosureFailure, match="EXPLICIT_TARGETED_SCOPE_INVALID"):
            asyncio.run(six.closure._run(
                tmp_path / "not-created", tmp_path, replay_task_ids=six.TARGETS, **options,
            ))
