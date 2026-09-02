"""Stable failures for the Python Java-backed evidence consumer."""

from __future__ import annotations


class EvidenceRetrievalError(RuntimeError):
    """Base class for failures at the approved evidence read boundary."""


class EvidenceAuthorizationError(EvidenceRetrievalError):
    """Java rejected the authenticated caller or project read."""

    def __init__(
        self,
        message: str = "Java RAG authorization denied",
        *,
        status_code: int | None = None,
        tool_status: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.tool_status = tool_status
        super().__init__(message)


class EvidenceRequestContractError(EvidenceRetrievalError):
    """The submitted request violated the Java RAG tool contract."""

    def __init__(
        self,
        message: str = "Java RAG request contract was rejected",
        *,
        status_code: int | None = None,
        tool_status: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.tool_status = tool_status
        super().__init__(message)


class EvidenceSystemError(EvidenceRetrievalError):
    """The Java/RAG boundary failed before returning usable evidence."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        tool_status: str | None = None,
    ) -> None:
        self.status_code = status_code
        self.tool_status = tool_status
        super().__init__(message)


class EvidenceResponseContractError(EvidenceRetrievalError):
    """Java returned a structurally invalid evidence/result/citation payload."""
