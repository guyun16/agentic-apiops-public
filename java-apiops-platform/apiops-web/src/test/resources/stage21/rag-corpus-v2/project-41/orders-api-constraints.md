# Orders API constraints runbook

The Orders API accepts one order item. `quantity` is an integer with a minimum
of 1; quantity 0 is rejected before the order is written. `Idempotency-Key` is
required for a create-order retry and is scoped to the customer account.
`orderId` identifies the order, `customerId` identifies its owner, and a
successful create returns HTTP 201.

For HTTP 409, check the duplicate-key report and the unique-index reference.
A connection failure before an HTTP response is a separate transport failure.

## Exact evidence

This runbook is the exact Orders evidence for the single quantity constraint
and the independent order constraints. For an exact comparison with a
near-match reference, preserve Orders service identity: the Payments provider
reference belongs to another service.
