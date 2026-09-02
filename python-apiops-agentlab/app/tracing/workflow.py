"""Small containment and boundary helpers for workflow instrumentation.

The helpers in this module deliberately sit at existing workflow/model
boundaries.  They observe facts and never return a route decision to the
business workflow.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter_ns
from uuid import uuid4

from app.agents.testcase_generator import TestCaseGenerator

from .models import (
    FailureDetail,
    IdentityAuthority,
    Latency,
    ModelCall,
    ModelIdentity,
    ParentIdentity,
    PromptIdentity,
    ProviderUsageMetadata,
    TokenUsage,
    TraceEvent,
    TraceRecord,
    TraceStatus,
)
from .recorder import TraceRecorder
from .redaction import digest_payload, safe_summary


def observe(
    recorder: TraceRecorder | None,
    fact: Callable[[], TraceRecord],
) -> None:
    """Build and record one fact without exposing any business decision signal."""

    if recorder is None:
        return
    try:
        recorder.record(fact())
    except Exception:  # noqa: BLE001 - instrumentation construction is best-effort too
        return


def new_identity(prefix: str) -> str:
    """Create a Python-owned identity at the tracing boundary."""

    if not isinstance(prefix, str) or not prefix.strip():
        raise ValueError("identity prefix must be non-empty")
    return f"{prefix}:{uuid4().hex}"


def trace_parent(kind: str, identity: str, authority: IdentityAuthority) -> ParentIdentity:
    """Build one typed parent/ownership reference."""

    return ParentIdentity(authority=authority, kind=kind, identity=identity)


def failure_detail(
    category: str,
    message: object,
    *,
    code: str | None = None,
    error_type: str | None = None,
) -> FailureDetail:
    """Build a bounded, redaction-safe failure fact."""

    summary, _ = safe_summary(message if isinstance(message, str) else str(message))
    return FailureDetail(
        failure_category=category,
        failure_code=code,
        message=summary,
        error_type=error_type,
    )


@dataclass(frozen=True, slots=True)
class TraceStepContext:
    """Context visible to an instrumented model call."""

    recorder: TraceRecorder
    trace_id: str
    agent_run_id: str
    agent_step_id: str
    prompt: PromptIdentity


_ACTIVE_TRACE_STEP: ContextVar[TraceStepContext | None] = ContextVar(
    "active_trace_step",
    default=None,
)


@contextmanager
def trace_step_scope(
    recorder: TraceRecorder | None,
    *,
    trace_id: str,
    agent_run_id: str,
    agent_step_id: str,
    prompt: PromptIdentity,
) -> Iterator[None]:
    """Expose one semantic workflow step to the existing LLM boundary."""

    if recorder is None:
        yield
        return
    token = _ACTIVE_TRACE_STEP.set(
        TraceStepContext(
            recorder=recorder,
            trace_id=trace_id,
            agent_run_id=agent_run_id,
            agent_step_id=agent_step_id,
            prompt=prompt,
        )
    )
    try:
        yield
    finally:
        _ACTIVE_TRACE_STEP.reset(token)


class InstrumentedLLM:
    """Observe one existing provider-neutral LLM call without changing it."""

    def __init__(self, llm: object) -> None:
        self._llm = llm

    @property
    def model(self) -> str:
        value = getattr(self._llm, "model", None)
        return value if isinstance(value, str) and value.strip() else type(self._llm).__name__

    @property
    def provider(self) -> str:
        value = getattr(self._llm, "provider", None)
        return value if isinstance(value, str) and value.strip() else type(self._llm).__name__

    def _completion_usage(self) -> TokenUsage | None:
        metadata = getattr(self._llm, "last_completion_metadata", None)
        if metadata is None:
            return None
        usage = TokenUsage(
            prompt_tokens=getattr(metadata, "prompt_tokens", None),
            completion_tokens=getattr(metadata, "completion_tokens", None),
            total_tokens=getattr(metadata, "total_tokens", None),
            provider_metadata=ProviderUsageMetadata(
                provider_request_id=getattr(metadata, "provider_request_id", None),
                finish_reason=getattr(metadata, "finish_reason", None),
            ),
        )
        if usage.provider_metadata is not None and not any(
            value is not None
            for value in (
                usage.prompt_tokens,
                usage.completion_tokens,
                usage.total_tokens,
                usage.provider_metadata.provider_request_id,
                usage.provider_metadata.finish_reason,
            )
        ):
            return None
        return usage

    async def complete(self, prompt: str) -> str:
        context = _ACTIVE_TRACE_STEP.get()
        if context is None:
            return await self._llm.complete(prompt)  # type: ignore[attr-defined]

        model_call_id = new_identity("model_call")
        started_at = datetime.now(UTC)
        started_clock = perf_counter_ns()
        parent = trace_parent(
            "agent_step",
            context.agent_step_id,
            IdentityAuthority.PYTHON,
        )
        observe(
            context.recorder,
            lambda: ModelCall(
                trace_id=context.trace_id,
                agent_run_id=context.agent_run_id,
                agent_step_id=context.agent_step_id,
                parent_identity=parent,
                event=TraceEvent.START,
                status=TraceStatus.RUNNING,
                model_call_id=model_call_id,
                model_identity=ModelIdentity(
                    provider=self.provider,
                    model=self.model,
                ),
                prompt=context.prompt,
                model_input=digest_payload(prompt),
            ),
        )
        try:
            output = await self._llm.complete(prompt)  # type: ignore[attr-defined]
        except Exception as exc:
            exc_type = type(exc).__name__
            exc_message = str(exc)
            finished_at = datetime.now(UTC)
            duration_ms = max((perf_counter_ns() - started_clock) / 1_000_000, 0.0)
            observe(
                context.recorder,
                lambda: ModelCall(
                    trace_id=context.trace_id,
                    agent_run_id=context.agent_run_id,
                    agent_step_id=context.agent_step_id,
                    parent_identity=parent,
                    event=TraceEvent.TERMINAL,
                    status=TraceStatus.FAILED,
                    failure=failure_detail(
                        "MODEL_CALL_FAILURE",
                        exc_message,
                        code=exc_type,
                        error_type=exc_type,
                    ),
                    model_call_id=model_call_id,
                    model_identity=ModelIdentity(
                        provider=self.provider,
                        model=self.model,
                    ),
                    prompt=context.prompt,
                    model_input=digest_payload(prompt),
                    token_usage=self._completion_usage(),
                    latency=Latency(
                        started_at=started_at,
                        finished_at=finished_at,
                        duration_ms=duration_ms,
                    ),
                ),
            )
            raise

        finished_at = datetime.now(UTC)
        duration_ms = max((perf_counter_ns() - started_clock) / 1_000_000, 0.0)
        observe(
            context.recorder,
            lambda: ModelCall(
                trace_id=context.trace_id,
                agent_run_id=context.agent_run_id,
                agent_step_id=context.agent_step_id,
                parent_identity=parent,
                event=TraceEvent.TERMINAL,
                status=TraceStatus.SUCCESS,
                model_call_id=model_call_id,
                model_identity=ModelIdentity(
                    provider=self.provider,
                    model=self.model,
                ),
                prompt=context.prompt,
                model_input=digest_payload(prompt),
                model_output=digest_payload(output),
                token_usage=self._completion_usage(),
                latency=Latency(
                    started_at=started_at,
                    finished_at=finished_at,
                    duration_ms=duration_ms,
                ),
            ),
        )
        return output


def instrument_generator(
    generator: TestCaseGenerator,
    recorder: TraceRecorder | None,
) -> TestCaseGenerator:
    """Return a shallow boundary wrapper for the existing generator.

    Unsupported/custom generators are intentionally left untouched; their
    semantic workflow steps are still recorded by the graph itself.
    """

    if recorder is None or not isinstance(generator, TestCaseGenerator):
        return generator
    return TestCaseGenerator(InstrumentedLLM(generator._llm))


__all__ = [
    "InstrumentedLLM",
    "TraceStepContext",
    "failure_detail",
    "instrument_generator",
    "new_identity",
    "observe",
    "trace_parent",
    "trace_step_scope",
]
