"""Python-internal context ranking, compression, masking, and assembly.

This module composes typed evidence and historical memory without changing the
Java-owned RAG contract or the Stage 16 workflow state. Budgets are explicit
policy inputs. Character counts are used as a transparent budget unit; they do
not claim to model a provider tokenizer.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
    model_validator,
)

from app.memory.models import HistoricalFailureMemoryEntry

from .models import EvidenceCitation, RetrievedEvidence

NonEmptyString = Annotated[StrictStr, Field(min_length=1)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
PositiveInt = Annotated[StrictInt, Field(ge=1)]


class ContextSource(StrEnum):
    """Closed internal source categories for context items."""

    API_METADATA = "API_METADATA"
    EXECUTION_FACT = "EXECUTION_FACT"
    RAG_EVIDENCE = "RAG_EVIDENCE"
    HISTORICAL_MEMORY = "HISTORICAL_MEMORY"
    SHORT_TERM_CONTEXT = "SHORT_TERM_CONTEXT"
    USER_INTENT = "USER_INTENT"


class _ContextModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=False,
        strict=True,
        frozen=True,
        validate_default=True,
    )


class ContextProvenance(_ContextModel):
    """Stable provenance retained alongside a context item."""

    source_type: NonEmptyString
    source_id: NonEmptyString
    project_id: StrictInt | None = Field(default=None, ge=1)
    run_id: StrictInt | None = Field(default=None, ge=1)
    document_id: NonEmptyString | None = None
    chunk_id: NonEmptyString | None = None
    location: NonEmptyString | None = None


class ContextItem(_ContextModel):
    """One typed, project-scoped piece of context.

    ``source_id`` is stable within ``source_type`` and ``project_scope``.
    Deduplication uses exactly that identity tuple; content similarity is
    intentionally not considered.
    """

    source_type: ContextSource
    source_id: NonEmptyString
    project_scope: StrictInt | None = Field(default=None, ge=1)
    content: NonEmptyString
    priority: StrictInt = 0
    relevance_score: StrictFloat | None = None
    provenance: tuple[ContextProvenance, ...] = ()
    citation: EvidenceCitation | None = None
    truncated: StrictBool = False

    @field_validator("relevance_score")
    @classmethod
    def relevance_score_must_be_finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("relevance_score must be finite")
        return value

    @model_validator(mode="after")
    def provenance_must_stay_in_scope(self) -> ContextItem:
        if self.citation is not None and self.project_scope is not None:
            if self.citation.project_id != self.project_scope:
                raise ValueError("citation project_id must match project_scope")
        if any(
            reference.project_id is not None
            and self.project_scope is not None
            and reference.project_id != self.project_scope
            for reference in self.provenance
        ):
            raise ValueError("context provenance must stay in project_scope")
        return self

    @property
    def stable_identity(self) -> tuple[ContextSource, int | None, str]:
        """Return the explicit identity used by deterministic deduplication."""

        return (self.source_type, self.project_scope, self.source_id)

    @property
    def source_identity(self) -> tuple[ContextSource, int | None, str]:
        """Compatibility-friendly name for ``stable_identity``."""

        return self.stable_identity

    @classmethod
    def from_retrieved_evidence(
        cls,
        evidence: RetrievedEvidence,
        *,
        priority: int = 0,
    ) -> ContextItem:
        """Adapt one Java-ranked result without changing its citation."""

        if not isinstance(evidence, RetrievedEvidence):
            raise TypeError("evidence must be a RetrievedEvidence")
        citation = evidence.citation
        provenance = ContextProvenance(
            source_type=citation.source_type,
            source_id=citation.source_id,
            project_id=citation.project_id,
            document_id=citation.document_id,
            chunk_id=citation.chunk_id,
            location=citation.location,
        )
        return cls(
            source_type=ContextSource.RAG_EVIDENCE,
            source_id=_retrieved_evidence_source_id(evidence),
            project_scope=evidence.project_id,
            content=evidence.content,
            priority=priority,
            relevance_score=evidence.relevance_score,
            provenance=(provenance,),
            citation=citation,
        )

    @classmethod
    def from_historical_memory(
        cls,
        memory: HistoricalFailureMemoryEntry,
        *,
        priority: int = 0,
        relevance_score: float | None = None,
    ) -> ContextItem:
        """Adapt one verified memory entry as historical context."""

        if not isinstance(memory, HistoricalFailureMemoryEntry):
            raise TypeError("memory must be a HistoricalFailureMemoryEntry")
        provenance = [
            ContextProvenance(
                source_type=reference.source_type,
                source_id=reference.source_id,
                project_id=reference.project_id,
                run_id=reference.run_id,
            )
            for reference in memory.evidence_refs
        ]
        if memory.source_run_id is not None:
            provenance.append(
                ContextProvenance(
                    source_type="RUN",
                    source_id=f"run:{memory.source_run_id}",
                    project_id=memory.project_id,
                    run_id=memory.source_run_id,
                )
            )
        provenance.sort(key=_provenance_sort_key)
        return cls(
            source_type=ContextSource.HISTORICAL_MEMORY,
            source_id=memory.memory_id,
            project_scope=memory.project_id,
            content=_historical_memory_content(memory),
            priority=priority,
            relevance_score=relevance_score,
            provenance=tuple(provenance),
        )


class ContextPolicy(_ContextModel):
    """Explicit authority and compression inputs for context assembly.

    ``source_precedence`` is required because business authority belongs to
    the current workflow/application policy, not to this generic model. No
    total or per-item budget is frozen here. ``None`` disables the
    corresponding bound. Source precedence is a discrete ordering and never
    combines source types into a confidence score.
    """

    source_precedence: tuple[ContextSource, ...]
    drop_below_priority: StrictInt | None = None
    per_source_caps: dict[ContextSource, NonNegativeInt] = Field(default_factory=dict)
    per_item_char_budget: PositiveInt | None = None
    total_char_budget: NonNegativeInt | None = None

    @model_validator(mode="after")
    def validate_precedence(self) -> ContextPolicy:
        if len(set(self.source_precedence)) != len(self.source_precedence):
            raise ValueError("source_precedence must not contain duplicates")
        missing = set(ContextSource) - set(self.source_precedence)
        if missing:
            missing_values = ", ".join(sorted(source.value for source in missing))
            raise ValueError(f"source_precedence is missing: {missing_values}")
        return self


@dataclass(frozen=True)
class ContextCompressionResult:
    """Compression output plus deterministic counts used by ``ContextPack``."""

    items: tuple[ContextItem, ...]
    deduplicated_item_count: int
    policy_selected_item_count: int


class ContextPack(_ContextModel):
    """The deterministic output of context assembly.

    Budget accounting is expressed in characters. The counts are facts about
    this pipeline, not estimates of a provider's exact tokenizer usage.
    """

    project_scope: StrictInt | None = Field(default=None, ge=1)
    items: tuple[ContextItem, ...] = ()
    budget_unit: Literal["characters"] = "characters"
    budget_limit: NonNegativeInt | None = None
    budget_used: NonNegativeInt = 0
    input_item_count: NonNegativeInt = 0
    eligible_item_count: NonNegativeInt = 0
    deduplicated_item_count: NonNegativeInt = 0
    policy_selected_item_count: NonNegativeInt = 0
    dropped_item_count: NonNegativeInt = 0
    truncated_item_count: NonNegativeInt = 0

    @model_validator(mode="after")
    def validate_usage_facts(self) -> ContextPack:
        item_count = len(self.items)
        budget_used = sum(len(item.content) for item in self.items)
        truncated_count = sum(item.truncated for item in self.items)

        if self.project_scope is not None and any(
            item.project_scope != self.project_scope for item in self.items
        ):
            raise ValueError("context pack contains an item outside project_scope")
        if self.budget_used != budget_used:
            raise ValueError("budget_used must equal the sum of item content lengths")
        if self.truncated_item_count != truncated_count:
            raise ValueError("truncated_item_count must match the output items")
        if self.budget_limit is not None and self.budget_used > self.budget_limit:
            raise ValueError("budget_used must not exceed budget_limit")
        if self.input_item_count < self.eligible_item_count:
            raise ValueError("input_item_count must cover eligible_item_count")
        if self.eligible_item_count < self.deduplicated_item_count:
            raise ValueError("eligible_item_count must cover deduplicated_item_count")
        if self.deduplicated_item_count < self.policy_selected_item_count:
            raise ValueError("deduplicated_item_count must cover policy_selected_item_count")
        if self.policy_selected_item_count < item_count:
            raise ValueError("policy_selected_item_count must cover output items")
        if self.dropped_item_count != self.input_item_count - item_count:
            raise ValueError("dropped_item_count must equal input minus output item count")
        return self


class ContextRanker:
    """Stable authority-aware ranking only.

    Eligibility, deduplication, compression, masking, and pack construction
    belong to the other context components. The builder calls this ranker only
    after project eligibility has been established.
    """

    def __init__(self, policy: ContextPolicy) -> None:
        if not isinstance(policy, ContextPolicy):
            raise TypeError("policy must be a ContextPolicy")
        self._policy = policy
        self._source_order = {
            source: index for index, source in enumerate(policy.source_precedence)
        }

    @property
    def policy(self) -> ContextPolicy:
        return self._policy

    def rank(self, items: Iterable[ContextItem]) -> tuple[ContextItem, ...]:
        """Rank by source precedence, priority, relevance, then stable data."""

        materialized = _materialize_context_items(items)
        return tuple(sorted(materialized, key=self._rank_key))

    def _rank_key(self, item: ContextItem) -> tuple[object, ...]:
        relevance = item.relevance_score
        relevance_key = -relevance if relevance is not None else math.inf
        return (
            self._source_order[item.source_type],
            -item.priority,
            relevance_key,
            item.source_id,
            _canonical_rank_item(item),
        )


class DeterministicContextCompressor:
    """Perform identity deduplication and explicit budget compression only."""

    def __init__(self, policy: ContextPolicy) -> None:
        if not isinstance(policy, ContextPolicy):
            raise TypeError("policy must be a ContextPolicy")
        self._policy = policy

    @property
    def policy(self) -> ContextPolicy:
        return self._policy

    def deduplicate(self, ranked_items: Iterable[ContextItem]) -> tuple[ContextItem, ...]:
        """Keep the first item for each identity in an already-ranked sequence."""

        seen: set[tuple[ContextSource, int | None, str]] = set()
        deduplicated: list[ContextItem] = []
        for item in _materialize_context_items(ranked_items):
            if item.stable_identity in seen:
                continue
            seen.add(item.stable_identity)
            deduplicated.append(item)
        return tuple(deduplicated)

    def compress(self, ranked_items: Iterable[ContextItem]) -> tuple[ContextItem, ...]:
        """Compress an already-ranked sequence and preserve its order."""

        return self.compress_with_stats(ranked_items).items

    def compress_with_stats(
        self,
        ranked_items: Iterable[ContextItem],
    ) -> ContextCompressionResult:
        """Run dedup, filtering, caps, item truncation, and total trim."""

        deduplicated = self.deduplicate(ranked_items)
        priority_filtered = self._drop_low_priority(deduplicated)
        capped = self._apply_source_caps(priority_filtered)
        item_compressed = tuple(
            self._truncate(item, self._policy.per_item_char_budget) for item in capped
        )
        final_items = self._trim_total(item_compressed)
        return ContextCompressionResult(
            items=final_items,
            deduplicated_item_count=len(deduplicated),
            policy_selected_item_count=len(capped),
        )

    def _drop_low_priority(self, items: Iterable[ContextItem]) -> tuple[ContextItem, ...]:
        threshold = self._policy.drop_below_priority
        if threshold is None:
            return tuple(items)
        return tuple(item for item in items if item.priority >= threshold)

    def _apply_source_caps(self, items: Iterable[ContextItem]) -> tuple[ContextItem, ...]:
        counts: dict[ContextSource, int] = {}
        selected: list[ContextItem] = []
        for item in items:
            cap = self._policy.per_source_caps.get(item.source_type)
            count = counts.get(item.source_type, 0)
            if cap is not None and count >= cap:
                continue
            selected.append(item)
            counts[item.source_type] = count + 1
        return tuple(selected)

    @staticmethod
    def _truncate(item: ContextItem, limit: int | None) -> ContextItem:
        if limit is None or len(item.content) <= limit:
            return item
        return item.model_copy(update={"content": item.content[:limit], "truncated": True})

    def _trim_total(self, items: Iterable[ContextItem]) -> tuple[ContextItem, ...]:
        budget = self._policy.total_char_budget
        if budget is None:
            return tuple(items)

        remaining = budget
        selected: list[ContextItem] = []
        for item in items:
            if remaining <= 0:
                break
            if len(item.content) <= remaining:
                selected.append(item)
                remaining -= len(item.content)
                continue
            selected.append(self._truncate(item, remaining))
            break
        return tuple(selected)


_AUTHORIZATION_RE = re.compile(
    r"(?P<prefix>\bauthorization\b[\"']?\s*[:=]\s*(?P<quote>[\"']?)(?:bearer\s+)?)"
    r"(?P<value>[^\"'\s,;]+)(?P=quote)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(
    r"(?P<prefix>\bbearer\s+(?P<quote>[\"']?))"
    r"(?P<value>[^\"'\s,;]+)(?P=quote)",
    re.IGNORECASE,
)
_CREDENTIAL_FIELD_RE = re.compile(
    r"(?P<prefix>\b(?:password|api[\s_-]?key|secret|access[\s_-]?token|"
    r"refresh[\s_-]?token|client[\s_-]?secret|private[\s_-]?key|token)\b"
    r"[\"']?\s*[:=]\s*(?P<quote>[\"']?))"
    r"(?P<value>[^\"'\s,;]+)(?P=quote)",
    re.IGNORECASE,
)
_COOKIE_HEADER_RE = re.compile(
    r"(?P<prefix>\b(?:cookie|set-cookie)\b[\"']?\s*[:=]\s*)"
    r"(?P<body>[^\r\n]*)",
    re.IGNORECASE,
)
_COOKIE_PAIR_RE = re.compile(r"(?P<name>[^=;,\s]+)(?P<separator>=)(?P<value>[^;,\s\"']+)")


class SensitiveDataMasker:
    """Mask common credential values with deterministic same-length stars."""

    def mask_text(self, value: str) -> str:
        """Mask recognized credential values without changing surrounding labels."""

        masked = _AUTHORIZATION_RE.sub(self._mask_value_match, value)
        masked = _BEARER_RE.sub(self._mask_value_match, masked)
        masked = _CREDENTIAL_FIELD_RE.sub(self._mask_value_match, masked)
        return _COOKIE_HEADER_RE.sub(self._mask_cookie_header, masked)

    def mask(self, item: ContextItem) -> ContextItem:
        """Return an item with sensitive textual values masked."""

        if not isinstance(item, ContextItem):
            raise TypeError("item must be a ContextItem")
        masked_content = self.mask_text(item.content)
        masked_provenance = tuple(self._mask_provenance(reference) for reference in item.provenance)
        masked_citation = self._mask_citation(item.citation)
        return item.model_copy(
            update={
                "content": masked_content,
                "provenance": masked_provenance,
                "citation": masked_citation,
            }
        )

    def mask_items(self, items: Iterable[ContextItem]) -> tuple[ContextItem, ...]:
        """Mask a stable sequence without changing its order."""

        return tuple(self.mask(item) for item in _materialize_context_items(items))

    @staticmethod
    def _mask_value_match(match: re.Match[str]) -> str:
        value = match.group("value")
        return f"{match.group('prefix')}{'*' * len(value)}{match.group('quote')}"

    def _mask_cookie_header(self, match: re.Match[str]) -> str:
        prefix = match.group("prefix")
        body = match.group("body")
        if "=" not in body:
            return prefix + re.sub(r"\S+", lambda value: "*" * len(value.group()), body)
        return prefix + _COOKIE_PAIR_RE.sub(self._mask_cookie_pair, body)

    @staticmethod
    def _mask_cookie_pair(match: re.Match[str]) -> str:
        value = match.group("value")
        return f"{match.group('name')}{match.group('separator')}{'*' * len(value)}"

    def _mask_provenance(self, reference: ContextProvenance) -> ContextProvenance:
        if reference.location is None:
            return reference
        return reference.model_copy(update={"location": self.mask_text(reference.location)})

    def _mask_citation(self, citation: EvidenceCitation | None) -> EvidenceCitation | None:
        if citation is None:
            return None
        updates = {
            field: self.mask_text(getattr(citation, field))
            for field in ("title", "location", "excerpt")
        }
        return citation.model_copy(update=updates)


class ContextPackBuilder:
    """Compose eligibility, ranking, compression, masking, and pack creation."""

    def __init__(
        self,
        policy: ContextPolicy,
        *,
        project_scope: int,
        ranker: ContextRanker | None = None,
        compressor: DeterministicContextCompressor | None = None,
        masker: SensitiveDataMasker | None = None,
    ) -> None:
        if not isinstance(policy, ContextPolicy):
            raise TypeError("policy must be a ContextPolicy")
        if (
            isinstance(project_scope, bool)
            or not isinstance(project_scope, int)
            or project_scope < 1
        ):
            raise ValueError("project_scope must be a positive integer")
        self._policy = policy
        self._project_scope = project_scope
        self._ranker = ranker or ContextRanker(policy)
        self._compressor = compressor or DeterministicContextCompressor(policy)
        self._masker = masker or SensitiveDataMasker()

    @property
    def project_scope(self) -> int:
        return self._project_scope

    def build(self, items: Iterable[ContextItem]) -> ContextPack:
        """Build a project-isolated deterministic pack from typed items."""

        collected = _materialize_context_items(items)
        eligible = tuple(item for item in collected if item.project_scope == self._project_scope)
        ranked = self._ranker.rank(eligible)
        compression = self._compressor.compress_with_stats(ranked)
        masked = self._masker.mask_items(compression.items)
        return ContextPack(
            project_scope=self._project_scope,
            items=masked,
            budget_limit=self._policy.total_char_budget,
            budget_used=sum(len(item.content) for item in masked),
            input_item_count=len(collected),
            eligible_item_count=len(eligible),
            deduplicated_item_count=compression.deduplicated_item_count,
            policy_selected_item_count=compression.policy_selected_item_count,
            dropped_item_count=len(collected) - len(masked),
            truncated_item_count=sum(item.truncated for item in masked),
        )


def _materialize_context_items(items: Iterable[ContextItem]) -> tuple[ContextItem, ...]:
    materialized = tuple(items)
    if any(not isinstance(item, ContextItem) for item in materialized):
        raise TypeError("items must contain only ContextItem values")
    return materialized


def _canonical_rank_item(item: ContextItem) -> str:
    payload = item.model_dump(mode="json")
    payload.pop("project_scope", None)
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _provenance_sort_key(reference: ContextProvenance) -> tuple[object, ...]:
    return (
        reference.source_type,
        reference.source_id,
        reference.project_id or 0,
        reference.run_id or 0,
        reference.document_id or "",
        reference.chunk_id or "",
        reference.location or "",
    )


def _retrieved_evidence_source_id(evidence: RetrievedEvidence) -> str:
    identity = {
        "chunk_id": evidence.chunk_id,
        "document_id": evidence.document_id,
        "project_id": evidence.project_id,
        "source_id": evidence.citation.source_id,
        "source_type": evidence.citation.source_type,
    }
    return "evidence:" + json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _historical_memory_content(memory: HistoricalFailureMemoryEntry) -> str:
    payload = {
        "api_id": memory.api_id,
        "resolution": memory.resolution,
        "root_cause": memory.root_cause,
        "summary": memory.summary,
        "symptoms": list(memory.symptoms),
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


__all__ = [
    "ContextCompressionResult",
    "ContextItem",
    "ContextPack",
    "ContextPackBuilder",
    "ContextPolicy",
    "ContextProvenance",
    "ContextRanker",
    "ContextSource",
    "DeterministicContextCompressor",
    "SensitiveDataMasker",
]
