# Tool Gateway and retrieval operations runbook

The Tool Gateway is the authorization boundary for tool calls. The caller's
current project, requested target project, tool name, and required authority
must be checked before a handler runs. A request for another project's
content is a forbidden operation; it must not be converted into an ordinary
empty retrieval result and it must not be answered from a local database path.

Retrieval is evidence support, not an answer generator. A successful search
may return no rows when the indexed knowledge does not support the query. An
empty result is a meaningful zero-hit outcome: do not substitute another
project, a similar service, or an unverified model statement.

Evidence returned by the gateway must retain project, document, chunk, and
source identity. A citation is usable only when those identities match the
authorized result. If a report requires evidence, the caller must retain the
retrieval result and its citation rather than claiming authority from the
query text alone.
