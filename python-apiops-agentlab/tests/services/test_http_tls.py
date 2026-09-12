"""TLS reuse must retain certificate and hostname verification."""

import ssl

from app.core.http_tls import client_tls_context


def test_reused_context_keeps_trusted_roots_and_verification():
    context = client_tls_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert context.cert_store_stats()["x509_ca"] > 0
    assert client_tls_context() is context
