package com.apiops.runner.application;

import com.apiops.runner.state.RunStatus;

import java.util.List;
import java.util.Objects;

/** Deterministic Stage 9 aggregation over existing Stage 8 statuses. */
public final class BatchExecutionAggregator {

    public RunStatus aggregate(boolean cancellationOwned, List<BatchCaseOutcome> outcomes) {
        Objects.requireNonNull(outcomes, "outcomes must not be null");
        if (cancellationOwned) {
            return RunStatus.CANCELLED;
        }
        RunStatus selected = RunStatus.SUCCESS;
        int selectedPriority = priority(selected);
        for (BatchCaseOutcome outcome : outcomes) {
            RunStatus candidate = Objects.requireNonNull(outcome, "outcome must not be null")
                    .status();
            int candidatePriority = priority(candidate);
            if (candidatePriority > selectedPriority) {
                selected = candidate;
                selectedPriority = candidatePriority;
            }
        }
        return selected;
    }

    private int priority(RunStatus status) {
        return switch (status) {
            case SUCCESS -> 0;
            case ASSERTION_FAILED -> 1;
            case EXECUTION_FAILED -> 2;
            case TIMEOUT -> 3;
            case CANCELLED -> 4;
            case PENDING, RUNNING -> throw new IllegalArgumentException(
                    "Batch case status must be terminal: " + status);
        };
    }
}
