# APIOps Bench

APIOps Bench is the project's own API-operations benchmark. APIOps-Bench 105 contains
105 tasks across TestCase Generation, Failure Diagnosis, Tool Safety, RAG Evidence
and End-to-End APIOps. It is a project-specific evaluation, not an external model
leaderboard or a production reliability estimate.

The [dataset fixtures](../python-apiops-agentlab/tests/benchmark/fixtures/),
[task models](../python-apiops-agentlab/app/benchmark/models.py),
[runner](../python-apiops-agentlab/app/benchmark/runner.py) and
[outcome evaluator](../python-apiops-agentlab/app/benchmark/outcome_v2.py) are public.
Fixtures are synthetic contract and test inputs; historical model runs are explicitly
distinguished from fixture executions.

## Published results

The [publication manifest](../artifacts/benchmark/portfolio-manifest.json) contains
14 complete runs and 1,470 task results: 12 real-model adapter runs and two mixed
fixture baselines. The [history metadata](stage21-benchmark-authority.json) preserves
execution modes, contract versions and incomplete or unavailable metrics.

| Run | PASS | FAIL | UNKNOWN | Interpretation |
| --- | ---: | ---: | ---: | --- |
| Portfolio v5 | 95 | 9 | 1 | Current portfolio result; V2 outcome contract |
| Diagnosis Contract v2 | 94 | 8 | 3 | Independent diagnosis contract validation |

These runs use different contracts and must not be combined or treated as a
controlled model comparison. The v5 pass rate is 95/105 (90.48%); UNKNOWN tasks stay
in its denominator. Historical failures and unknowns remain visible. Some older
runs lack comparable task-success or token metrics; absence is not zero.

## Evidence and authority

Java owns HTTP execution and the authoritative TestReport. Python consumes Java
APIs and controlled tools, records Agent traces and evaluates outcomes. A successful
model response is not itself a successful API task. Tool approval does not replace
Java authorization or project isolation.

The Console reads saved result summaries and task records through the
[Benchmark API](../python-apiops-agentlab/app/services/benchmark_results.py). It does
not run or rescore tasks. Invalid, partial, unpublished or mismatched bundles are
not exposed. API failures are shown as unavailable data.

The public bundle preserves the existing result JSON bytes and original identifiers.
Original source paths in provenance records identify historical experiments; they
are not promises that every raw trace or local log is distributed here. The checked-in
dataset and ordinary tests support inspection of the evaluation contract. Repeating
real-model experiments requires separately provisioned services, credentials,
runtime evidence and an intentional new run configuration.

## Scope and limitations

- Results describe this dataset, runtime and contract revision, not general Agent capability.
- The current result retains nine failures and one unknown; known limitations remain part of the evidence.
- Diagnosis Contract v2 uses a separate reviewed diagnosis contract and cannot replace the v5 score.
- Publishing this snapshot performs no model calls, benchmark executions or score changes.
- Full local service traces and historical intermediate experiments are not included.

See [publication policy](benchmark-publication.md) for the distribution and verification rules.
