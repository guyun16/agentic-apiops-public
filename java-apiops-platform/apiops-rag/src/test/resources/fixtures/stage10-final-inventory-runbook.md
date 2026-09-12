# Inventory reservation failure runbook

When order creation fails because inventory cannot be reserved, start with the authoritative
TestReport. A recorded HTTP 409 and an `INSUFFICIENT_STOCK` assertion mismatch mean the requested
quantity was not available at execution time. External knowledge must not rewrite that fact.

For an inventory reservation failure, verify the product identifier, requested quantity, available
quantity, and reservation expiry. Do not blindly retry order creation with the same idempotency key.
Confirm whether another reservation consumed the remaining stock, then reconcile the inventory
ledger before retrying. This guidance is directly relevant to the query "why did inventory
reservation fail with insufficient stock?".

Sensitive examples are intentionally present to validate the final ContextPack boundary:
Authorization: Bearer stage10-e2e-secret
Cookie: SESSION=stage10-cookie-secret
Set-Cookie: REFRESH=stage10-set-cookie-secret
password=stage10-password-secret
api_key=stage10-api-key-secret
secret=stage10-generic-secret

The citation must retain the project, document, chunk, and runbook source identity. If this
document is deleted or no longer INDEXED, its vector must not remain usable as normal evidence.

Additional operational context: inventory reservation is a synchronous consistency boundary for
the demo order service. The response contract documents conflict status 409 for unavailable stock.
Operators should compare the failed product and quantity with the inventory service ledger and the
reservation timeout. A successful later retry does not change the earlier failed execution fact.
