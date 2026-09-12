# Payments incident report

Payment incident P-204 concerns a provider timeout followed by a retry. The
payment reference is `pay-204`; no completed capture was recorded before the
retry deadline. The incident belongs to Project 42.

The report distinguishes a provider timeout from an HTTP 409 inventory
conflict. It grants no permission to read the Orders project or modify the
protected stock ledger.
