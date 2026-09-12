# API contract and testcase design runbook

OpenAPI is the endpoint authority for an executable API check. Preserve the
HTTP method, path, operation identifier, required parameters, request body
schema, and permitted response status and body schema. A request that violates
these contract fields is not a successful check.

A TestCase DSL describes an executable request and its assertions. Its schema
version, service identifier, project scope, request, and assertion blocks are
contract fields. Valid JSON proves only parseability; it does not prove that
the request or assertions express the intended behavior.

Keep assertion discrepancy separate from HTTP status discrepancy. An expected
body field with the wrong value is an assertion defect even when the status is
correct. A response with the wrong status is a protocol or endpoint defect
even when a body fragment looks plausible. Record both observations so a
diagnosis does not replace the contract semantics.
