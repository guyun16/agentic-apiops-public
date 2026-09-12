# Service data-integrity constraints reference

Relational services enforce data integrity at more than one boundary. A
unique constraint prevents two rows from claiming the same key. A foreign-key
constraint requires a referenced parent row and rejects an orphan relation.
Application validation and database enforcement can therefore expose
different failure locations for the same invalid write.

When investigating a rejected write, retain the table or resource scope, the
constraint name when available, and whether the record was committed. A
successful validation response is not evidence that the database accepted the
write. A database constraint error is not evidence of a transport outage.
