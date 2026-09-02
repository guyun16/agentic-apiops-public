# Orders API diagnostic runbook

When an order request fails, first correlate the request trace with the authoritative execution
facts and TestReport. Confirm the API identifier, environment, response status, assertion result,
and recorded timing before consulting external diagnostic knowledge. The runbook provides possible
investigation paths; it never changes what the test execution recorded.

For authorization failures, verify that the caller has a current project membership and that the
credential audience matches the deployed API. Check whether an expired token, incorrect scope, or
gateway policy explains the observed response. Do not copy credentials into tickets or diagnostic
logs. Record only stable evidence locations and sanitized observations.

For server failures, compare the trace identifier with service logs and dependency health. Inspect
timeouts, connection pool saturation, downstream response codes, and recent configuration changes.
Prefer evidence tied to the same project and API contract. A plausible runbook explanation is not
proof until it is consistent with the formal execution facts.

For contract failures, compare the response with OpenAPI metadata. Validate required fields, media
type, schema constraints, and documented error responses. Keep the original report and metadata as
the authority; this text is supplemental diagnostic knowledge that can be re-indexed or deleted.

Escalate only after recording the source document, chunk identity, and the specific location that
supports the next investigation step. This makes every future citation traceable to formal stored
knowledge without duplicating the full document inside the vector index.
