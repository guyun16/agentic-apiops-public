from app.tracing import (
    canonical_json_hash,
    digest_payload,
    redact_text,
    redact_value,
    safe_summary,
    tool_arguments_hash,
)


def test_canonical_tool_arguments_hash_ignores_object_key_order() -> None:
    first = {"query": "timeout", "options": {"topK": 3, "mode": "hybrid"}}
    second = {"options": {"mode": "hybrid", "topK": 3}, "query": "timeout"}

    assert tool_arguments_hash(first) == tool_arguments_hash(second)
    assert canonical_json_hash(first) == canonical_json_hash(second)


def test_sensitive_fields_are_redacted_without_real_credentials() -> None:
    masked = redact_value(
        {
            "Authorization": "Bearer test-token-placeholder",
            "Cookie": "session=test-cookie-placeholder",
            "apiKey": "test-api-key-placeholder",
            "password": "test-password-placeholder",
            "access_token": "test-access-placeholder",
            "refreshToken": "test-refresh-placeholder",
            "providerSecret": "test-provider-secret-placeholder",
            "rawLogs": "test-log-placeholder",
            "fullContextPack": {"content": "test-context-placeholder"},
            "fullToolResult": {"data": "test-result-placeholder"},
            "safe": "retained",
        }
    )

    assert isinstance(masked, dict)
    assert masked["Authorization"] == "[REDACTED]"
    assert masked["Cookie"] == "[REDACTED]"
    assert masked["apiKey"] == "[REDACTED]"
    assert masked["password"] == "[REDACTED]"
    assert masked["safe"] == "retained"


def test_sensitive_text_and_summary_are_bounded() -> None:
    text = redact_text(
        "Authorization: Bearer test-token-placeholder; password=test-password-placeholder"
    )
    summary, truncated = safe_summary("x" * 20, max_chars=10)
    digest = digest_payload({"Authorization": "test-token-placeholder"})

    assert "test-token-placeholder" not in text
    assert "test-password-placeholder" not in text
    assert len(summary) <= 10
    assert truncated is True
    assert digest.summary == '{"Authorization":"[REDACTED]"}'
    assert digest.truncated is False
