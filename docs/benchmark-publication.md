# APIOps Bench publication

The [manifest](../artifacts/benchmark/portfolio-manifest.json) is the authority for
the 14 published runs. Each admitted run has 105 unique selected task IDs, 105 unique
persisted results covering exactly those IDs, matching evaluationRunId values and a
completed, non-aborted run envelope. Failures and UNKNOWN scores do not exclude a run.
Completion is distinct from model quality.

## Public distribution

This public release includes the publication manifest, selection ledger, run
envelopes, task result files and associated summary/reproducibility records from the
existing [publication directory](../artifacts/benchmark/). Historical JSON bytes are
copied unchanged. Original run IDs, scores, execution modes and provenance hashes
remain intact. Raw experiment roots, local runtime databases, private credentials,
service logs and unrelated intermediate acceptance captures are excluded. A small
set of historical inputs required by regression tests is also included; these are
not additional Full105 publications.

Only those regression inputs may have machine-local repository paths converted to
repository-relative paths in their public copies. The evidence inventory identifies
each such copy, its original source SHA-256, its public SHA-256 and the transformed
JSON locations. Scores, task content, evaluation facts and hash values are unchanged.
The 14 published run bundles themselves have no such normalization.

The selection ledger and history metadata retain original source-relative paths.
Those paths describe provenance in the development repository. The public API reads
the copied paths in the publication manifest and does not require the omitted raw
experiment directories. The source-freeze v1–v5 records are retained as historical
records, not as proof that this public checkout is byte-identical to an older source
tree.

## Verify the public source snapshot

From `python-apiops-agentlab`:

```bash
uv run python scripts/freeze_benchmark_portfolio.py
uv run pytest tests/api/test_benchmark_results.py tests/scripts/test_benchmark_portfolio_freeze.py
```

The current public source inventory is
`artifacts/benchmark/portfolio-source-freeze-public-v1.json`; it links to the unchanged
v5 source inventory by SHA-256. It covers the public viewer, API, manifest and related
documentation. Source text is normalized to UTF-8 LF for hashing; immutable result
files retain their original bytes. This is publication verification, not a new model run.

The separate `public-evidence-sha256.json` inventory records the SHA-256 of each
distributed publication file and selected regression input. Verify it from the repository root:

```bash
python scripts/verify-public-evidence.py
```

The API independently rejects missing, corrupt, outside-root, duplicate and incomplete
publications. Tests retain these rejection cases. Do not weaken the validator, alter
task truth, rescore results or remove failed tasks to make publication checks pass.

## Future updates

Review the source and selected files for credentials and private deployment details
before publishing. Preserve historical bundles. After an intentional source change,
validate affected tests and the full published history, then write a new versioned
source inventory. Existing inventories cannot be overwritten. Keep historical run
configurations distinct from current public setup and use new run identities for new
experiments. Real-model execution requires separate explicit configuration.
