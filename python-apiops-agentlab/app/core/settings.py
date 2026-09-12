"""Environment-backed settings for the Python AgentLab boundary."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    """Validated environment configuration for local and real boundaries."""

    model_config = SettingsConfigDict(
        case_sensitive=False,
        env_prefix="",
        extra="ignore",
    )

    java_apiops_base_url: str = Field(default="http://localhost:8080", min_length=1)
    java_apiops_timeout_seconds: float = Field(default=5.0, gt=0)
    java_apiops_token: SecretStr | None = None
    deepseek_api_key: SecretStr | None = None
    deepseek_base_url: str = Field(default="https://api.deepseek.com", min_length=1)
    deepseek_model: str = Field(default="deepseek-v4-flash", min_length=1)
    deepseek_timeout_seconds: float = Field(default=60.0, gt=0)
    diagnosis_llm_provider: Literal["deepseek", "qwen"] = "deepseek"
    testcase_llm_provider: Literal["deepseek", "qwen"] = "deepseek"
    qwen_api_key: SecretStr | None = None
    qwen_base_url: str = Field(
        default="https://your-provider.example/v1",
        min_length=1,
    )
    qwen_model: str = Field(default="qwen3.8-max", min_length=1)
    qwen_timeout_seconds: float = Field(default=60.0, gt=0)
    memory_db_path: str = Field(default="data/historical-memory.sqlite3", min_length=1)
    runtime_db_path: str = Field(default="data/agentlab-runtime.sqlite3", min_length=1)
    trace_sink: Literal["memory", "jsonl"] = "jsonl"
    trace_jsonl_path: str = Field(
        default="data/traces/agent-traces.jsonl",
        min_length=1,
    )
    trace_max_file_bytes: int = Field(
        default=16 * 1024 * 1024,
        gt=0,
    )
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    environment: str = Field(default="development", min_length=1)


@lru_cache(maxsize=1)
def get_settings() -> AppSettings:
    """Return process settings; tests can clear the cache when changing env vars."""

    return AppSettings()
