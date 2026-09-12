# Orders duplicate-key incident report

Report 701 records a duplicate-key failure while creating an order. Its
primary evidence identity is `report-701`; the Orders API returned HTTP 409
after a database constraint violation. The failed request reused an existing
customer reference, and the constraint was
`orders_unique_customer_reference`.

## Formal report citation identity

The formal report citation identity is this report.

For a formal report citation, preserve `report-701`, HTTP 409, and the
`duplicate-key` section. A diagnosis sentence alone is not a citation. This
incident report is relevant evidence; the companion evidence is the unique-
index reference in the Orders constraint index.
