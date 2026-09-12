# Inventory service runbook

Project 42 Inventory owns reservation availability. If available quantity is
below the request, the service returns HTTP 409 with business error
`INVENTORY_UNAVAILABLE`, not a transport failure.

The protected stock ledger is `inventory_reservation_ledger`; only Inventory
may change reserved quantity. This runbook is private Project 42 knowledge.
For target-project isolation, a caller whose current project is 41 must receive
Java authorization denial rather than an ordinary zero-hit response.
