# Relevant Orders evidence over Catalog distractors

The Orders database uses the exact unique index
`orders_unique_customer_reference` on `(customer_id, customer_reference)`.
It prevents two orders from claiming the same customer reference.

This is the primary Orders schema record for the duplicate-key constraint.
Incident report 701 records the HTTP 409; this index is the schema source.
Quantity minimum is 1, create-order retries retain an idempotency key scoped to
the customer account, and customer reference must be unique. These are
independent Orders constraints.

## Retrieval guidance

For an exact unique-index request, use this Orders record. For relevant
evidence over a Catalog distractor, this unique-index record is the relevant
Orders result. A Payments provider-reference note is a near-match comparison
from another service, not the Orders schema record.
