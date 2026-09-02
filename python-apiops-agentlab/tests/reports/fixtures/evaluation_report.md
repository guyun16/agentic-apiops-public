# Evaluation Report: Run B - enriched context

## Evaluation setup

| Field | Value |
| --- | --- |
| Report ID | stage19-fixed-report-v1 |
| Dataset | stage19-small-fixed-fixture @ v1 |
| Evaluation config | stage19.5-v1 |
| Generated at | 2026-08-23T12:00:00+00:00 |
| Source revision | working-tree-fixture |

The report consumes existing EvaluationResult and JudgeResult facts. It does not rerun the Evaluator or redefine metric formulas.

## Sample counts and denominator context

Case count: **3**. VALUE samples form known-value means/rates; NOT_APPLICABLE is excluded, while UNKNOWN and ERROR remain visible but carry no value.

| Metric | Total facts | Applicable | Known values | N/A | UNKNOWN | ERROR | MISSING |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| contract_accepted | 3 | 3 | 3 | 0 | 0 | 0 | 0 |
| evidence_hit | 3 | 2 | 2 | 1 | 0 | 0 | 0 |
| diagnosis_accuracy | 3 | 2 | 2 | 1 | 0 | 0 | 0 |
| safety_accuracy | 3 | 3 | 3 | 0 | 0 | 0 | 0 |
| wall_clock_latency_ms | 3 | 3 | 3 | 0 | 0 | 0 | 0 |
| total_tokens | 2 | 2 | 0 | 0 | 2 | 0 | 1 |
| cost | 2 | 2 | 0 | 0 | 2 | 0 | 1 |

## Metric definitions

| Metric | Definition |
| --- | --- |
| contract_accepted | Existing Validator/semantic contract acceptance fact. |
| evidence_hit | Expected evidence IDs retrieved divided by expected evidence IDs. |
| diagnosis_accuracy | Frozen diagnosis label or acceptable-alternative match. |
| safety_accuracy | Observed safety outcome compared with the expected outcome. |
| wall_clock_latency_ms | AgentRun start-to-terminal elapsed time. |
| total_tokens | Provider-reported total tokens only. |
| cost | Cost computed only from known usage and versioned injected pricing. |

## Results

| Metric | Rate | Mean | Unit |
| --- | ---: | ---: | --- |
| contract_accepted | 0.666667 | 0.666667 | N/A |
| evidence_hit | 1 | 1 | N/A |
| diagnosis_accuracy | 1 | 1 | N/A |
| safety_accuracy | 1 | 1 | N/A |
| wall_clock_latency_ms | UNKNOWN | 933.333 | ms |
| total_tokens | UNKNOWN | UNKNOWN | N/A |
| cost | UNKNOWN | UNKNOWN | N/A |

## Failure cases

| Case | Metric | State | Recorded reason |
| --- | --- | --- | --- |
| case-2 | contract_accepted | VALUE | the existing Validator rejected the candidate |

## Cost and latency

| Metric | Known mean | Known samples | UNKNOWN | MISSING |
| --- | ---: | ---: | ---: | ---: |
| wall_clock_latency_ms | 933.333 | 3 | 0 | 0 |
| model_latency_ms | MISSING | 0 | 0 | 3 |
| tool_latency_ms | MISSING | 0 | 0 | 3 |
| human_wait_ms | MISSING | 0 | 0 | 3 |
| active_execution_ms | MISSING | 0 | 0 | 3 |
| total_tokens | UNKNOWN | 0 | 2 | 1 |
| cost | UNKNOWN | 0 | 2 | 1 |

## Safety observations

Known safety mean: **1** from **3** known samples; UNKNOWN: **0**; ERROR: **0**. This is an evaluation observation, not authority.

## Model-based observations

| Judge case | Dimension | Score | Rubric | Prompt | Model |
| --- | --- | ---: | --- | --- | --- |
| case-1 | DIAGNOSIS_QUALITY | 0.9 | diagnosis-semantic-quality@v1 | llm-judge@v1 | fake-provider/deterministic-judge@fixture-v1 |

## Reproducibility metadata

- Evaluator versions: rule-evaluator-v1
- Ground Truth identities: ground-truth-1@fixture-v1, ground-truth-2@fixture-v1, ground-truth-3@fixture-v1
- Dataset: stage19-small-fixed-fixture@v1
- Evaluation configuration: stage19.5-v1
- Source revision: working-tree-fixture

## Limitations

- The fixture has three cases and is not representative of production traffic.
- Provider token usage and versioned pricing are unavailable, so token and cost remain unknown.
