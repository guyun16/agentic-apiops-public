# Inventory security and evidence runbook

Protected inventory records are governed by project membership and an
approval gate. Read access does not imply mutation authority, and a mutation
without an approval record must be denied before persistence. Foreign-key and
reservation constraints remain in force after authorization succeeds.

For a diagnosis that combines an incident report with an index or runbook,
each claim must be tied to the relevant evidence identity. Prefer multiple
independent sources when the conclusion depends on both an observed event and
a stored constraint. A source from a similar service is a near match, not
supporting evidence for the protected inventory conclusion.
