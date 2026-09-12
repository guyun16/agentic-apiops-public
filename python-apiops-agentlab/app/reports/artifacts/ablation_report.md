# Minimal Run A / Run B Comparison

This report describes observed differences on the same fixed cases. It does not claim that a configuration difference caused a metric change.

## Evaluation setup

- Matched case count: 3
- Run A: Run A - baseline context
- Run B: Run B - enriched context

## Configuration difference

| Run | Configuration |
| --- | --- |
| A | context_strategy=baseline; judge=fixture-v1 |
| B | context_strategy=enriched; judge=fixture-v1 |

## Selected metric observations

| Metric | Run A | Run B | Delta (B - A) | A known | B known |
| --- | ---: | ---: | ---: | ---: | ---: |
| diagnosis_accuracy | 0.5 | 1 | 0.5 | 2 | 2 |
| evidence_hit | 0.75 | 1 | 0.25 | 2 | 2 |
| safety_accuracy | 0.666667 | 1 | 0.333333 | 3 | 3 |
| wall_clock_latency_ms | 1100 | 933.333 | -166.667 | 3 | 3 |
| total_tokens | UNKNOWN | UNKNOWN | UNKNOWN | 0 | 0 |
| cost | UNKNOWN | UNKNOWN | UNKNOWN | 0 | 0 |

## Limitations

- Observed deltas are descriptive and are not evidence of causal improvement.
- This is a small matched-case comparison, not a randomized or formal multi-group ablation.
- A missing or unknown aggregate remains UNKNOWN; it is never replaced with zero.
- The fixture has three cases and is not representative of production traffic.
- Provider token usage and versioned pricing are unavailable, so token and cost remain unknown.
