"""Reuse verified TLS configuration without sharing credentials or responses."""

import ssl
from functools import lru_cache

import certifi


@lru_cache(maxsize=1)
def client_tls_context() -> ssl.SSLContext:
    # Match httpx's trust_env=False CA bundle. Loading it for every request can
    # block the event loop, particularly on Windows. Treat this context as read-only.
    return ssl.create_default_context(cafile=certifi.where())
