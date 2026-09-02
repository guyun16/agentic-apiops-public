"""Deterministic, project-scoped Historical Failure Memory retrieval."""

from __future__ import annotations

from collections.abc import Sequence

from .fingerprint import build_failure_fingerprint
from .models import HistoricalFailureMemoryEntry, MemoryLifecycleStatus
from .store import MemoryStore


class MemoryRetriever:
    """Read only ACTIVE memories matching one stable failure identity."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    def retrieve(
        self,
        *,
        project_id: int,
        failure_fingerprint: str | None = None,
        api_id: str | None = None,
        symptoms: Sequence[str] | None = None,
        root_cause: str | None = None,
        top_k: int = 5,
    ) -> list[HistoricalFailureMemoryEntry]:
        """Retrieve ACTIVE matches, always constrained to ``project_id``."""

        self._validate_scope(project_id=project_id, top_k=top_k)
        if failure_fingerprint is None:
            if api_id is None or symptoms is None or root_cause is None:
                raise ValueError(
                    "retrieve requires failure_fingerprint or api_id, symptoms, and root_cause"
                )
            failure_fingerprint = build_failure_fingerprint(
                api_id=api_id,
                symptoms=symptoms,
                root_cause=root_cause,
            )
        elif not isinstance(failure_fingerprint, str) or not failure_fingerprint.strip():
            raise ValueError("failure_fingerprint must be a non-empty string")
        else:
            failure_fingerprint = failure_fingerprint.strip()

        matches = self._store.find_by_failure_fingerprint(
            project_id=project_id,
            failure_fingerprint=failure_fingerprint,
            lifecycle_status=MemoryLifecycleStatus.ACTIVE,
        )
        return matches[:top_k]

    def retrieve_similar(
        self,
        *,
        project_id: int,
        api_id: str,
        symptoms: Sequence[str],
        root_cause: str,
        top_k: int = 5,
    ) -> list[HistoricalFailureMemoryEntry]:
        """Convenience form for deterministic semantic-identity retrieval."""

        return self.retrieve(
            project_id=project_id,
            api_id=api_id,
            symptoms=symptoms,
            root_cause=root_cause,
            top_k=top_k,
        )

    @staticmethod
    def _validate_scope(*, project_id: int, top_k: int) -> None:
        if isinstance(project_id, bool) or not isinstance(project_id, int) or project_id < 1:
            raise ValueError("project_id must be a positive integer")
        if isinstance(top_k, bool) or not isinstance(top_k, int) or top_k < 1:
            raise ValueError("top_k must be a positive integer")


__all__ = ["MemoryRetriever"]
