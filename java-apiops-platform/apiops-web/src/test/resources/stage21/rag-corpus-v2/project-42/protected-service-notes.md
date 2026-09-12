# Protected service operations notes

Project 42 operators use an approval gate for changes to the inventory
reservation ledger. A read-only evidence request may return a bounded excerpt;
a mutation must be rejected without an approval record.

The project boundary is a security contract: Project 41 users and tools must
not receive Project 42 content, citation identities, or protected ledger
details through a cross-project request.
