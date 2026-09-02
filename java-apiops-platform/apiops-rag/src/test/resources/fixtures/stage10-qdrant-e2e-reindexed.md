# Orders API diagnostic runbook — revised

Start from the authoritative TestReport and execution facts. Use the trace identifier to verify the
same project, API, environment, response status, assertion result, and timing. External knowledge
can suggest an investigation but cannot rewrite the recorded outcome.

For authorization responses, verify project membership, token expiry, audience, and scope without
logging credentials. For service errors, inspect dependency health, connection pressure, timeout
budgets, and recent configuration changes. For contract failures, compare the response media type,
required fields, and schema constraints with current OpenAPI metadata.

The revised procedure requires every finding to retain its document and chunk identities. Delete
obsolete index entries before publishing replacement chunks so stale evidence cannot be retrieved.
