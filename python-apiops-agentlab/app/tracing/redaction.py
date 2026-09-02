"""Deterministic hashing and redaction helpers for internal trace facts."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence

from .models import MAX_SAFE_SUMMARY_CHARS, PayloadDigest

_SENSITIVE_KEY_NAMES = {
    "authorization",
    "cookie",
    "setcookie",
    "apikey",
    "password",
    "accesstoken",
    "refreshtoken",
    "apitoken",
    "providertoken",
    "providerauth",
    "providersecret",
    "clientsecret",
    "privatekey",
    "secret",
    "rawlog",
    "rawlogs",
    "contextpack",
    "fullcontextpack",
    "toolresult",
    "fulltoolresult",
}

_ASSIGNMENT_RE = re.compile(
    r"(?P<label>\b(?:authorization|cookie|set-cookie|api[\s_-]*key|password|"
    r"access[\s_-]*token|refresh[\s_-]*token|provider[\s_-]*secret|"
    r"client[\s_-]*secret|private[\s_-]*key|secret|token)\b"
    r"\s*[=:]\s*)(?P<quote>[\"']?)(?P<value>[^\"'\s,;]+)(?P=quote)",
    re.IGNORECASE,
)
_BEARER_RE = re.compile(
    r"(?P<label>\bbearer\s+)(?P<value>[^\s,;]+)",
    re.IGNORECASE,
)
_COOKIE_HEADER_RE = re.compile(
    r"(?P<label>\b(?:cookie|set-cookie)\b\s*[:=]\s*)(?P<value>[^\r\n]+)",
    re.IGNORECASE,
)


def _normalized_key(key: object) -> str:
    return re.sub(r"[^a-z0-9]", "", str(key).lower())


def is_sensitive_key(key: object) -> bool:
    """Return whether a JSON field name must not retain its value."""

    normalized = _normalized_key(key)
    return normalized in _SENSITIVE_KEY_NAMES or normalized.endswith("secret")


def _mask_match(match: re.Match[str]) -> str:
    return f"{match.group('label')}[REDACTED]"


def _mask_cookie_header(match: re.Match[str]) -> str:
    return f"{match.group('label')}[REDACTED]"


def redact_text(value: str) -> str:
    """Mask common credentials in text while retaining safe labels."""

    # Mask the scheme/value pair first so an Authorization header cannot leave
    # the bearer token behind when the assignment pattern sees ``Bearer``.
    masked = _BEARER_RE.sub(_mask_match, value)
    masked = _COOKIE_HEADER_RE.sub(_mask_cookie_header, masked)
    return _ASSIGNMENT_RE.sub(_mask_match, masked)


def redact_value(value: object, *, max_summary_chars: int = MAX_SAFE_SUMMARY_CHARS) -> object:
    """Recursively redact JSON-like data before a sink sees it.

    This function is for the serialization boundary.  The typed trace models
    already exclude raw prompt/context/tool-result fields; this second pass
    protects summaries and future sink payloads from credential-shaped text.
    """

    if isinstance(value, Mapping):
        redacted: dict[object, object] = {}
        summary_truncated = False
        for key, item in value.items():
            if is_sensitive_key(key):
                redacted[key] = "[REDACTED]"
                continue
            if _normalized_key(key) in {"summary", "message", "resultsummary"} and isinstance(
                item, str
            ):
                safe = redact_text(item)
                clipped, was_truncated = _truncate(safe, max_summary_chars)
                redacted[key] = clipped
                summary_truncated = summary_truncated or was_truncated
                continue
            redacted[key] = redact_value(item, max_summary_chars=max_summary_chars)
        if summary_truncated and "truncated" in redacted:
            redacted["truncated"] = True
        return redacted
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray, str)):
        return [redact_value(item, max_summary_chars=max_summary_chars) for item in value]
    return value


def canonical_json(value: object) -> str:
    """Serialize JSON-compatible input with deterministic object key ordering."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def canonical_json_hash(value: object) -> str:
    """Return SHA-256 of the canonical JSON representation."""

    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def tool_arguments_hash(arguments: Mapping[str, object]) -> str:
    """Hash tool arguments without retaining the arguments themselves."""

    return canonical_json_hash(arguments)


def _truncate(value: str, max_chars: int) -> tuple[str, bool]:
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if len(value) <= max_chars:
        return value, False
    if max_chars == 1:
        return "…", True
    return f"{value[: max_chars - 1]}…", True


def safe_summary(value: object, *, max_chars: int = MAX_SAFE_SUMMARY_CHARS) -> tuple[str, bool]:
    """Return a redacted, bounded summary and whether it was truncated."""

    redacted = redact_value(value, max_summary_chars=max_chars)
    text = redacted if isinstance(redacted, str) else canonical_json(redacted)
    return _truncate(text, max_chars)


def digest_payload(value: object, *, max_chars: int = MAX_SAFE_SUMMARY_CHARS) -> PayloadDigest:
    """Create a summary/hash pair; raw input is not present in the result."""

    summary, truncated = safe_summary(value, max_chars=max_chars)
    return PayloadDigest(
        sha256=canonical_json_hash(value),
        summary=summary,
        truncated=truncated,
    )


__all__ = [
    "canonical_json",
    "canonical_json_hash",
    "digest_payload",
    "is_sensitive_key",
    "redact_text",
    "redact_value",
    "safe_summary",
    "tool_arguments_hash",
]
