# Runner reliability and failure taxonomy runbook

Runner states are accepted, queued, running, and terminal. A terminal report
retains run identity, testcase identity, request outcome, and assertion
outcome. A status page without its report is not proof of the business result.

Classify failures at the first reliable boundary: validation, authorization,
transport, timeout, HTTP response, assertion, or persistence. A timeout before
a response is transport, not an HTTP conflict. Retry only an idempotent
operation or one with an explicit idempotency contract; retrying an unknown
mutation can duplicate a side effect.

Correlate the terminal report with its index or summary using stable run and
testcase identity. Do not substitute a nearby, stale, or similarly named run.
