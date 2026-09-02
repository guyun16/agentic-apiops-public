package com.apiops.runner.state;

import java.util.Map;
import java.util.Objects;
import java.util.Set;

public final class RunStateMachine {

    private static final Map<RunStatus, Set<RunStatus>> ALLOWED_TRANSITIONS = Map.of(
            RunStatus.PENDING, Set.of(RunStatus.RUNNING, RunStatus.CANCELLED),
            RunStatus.RUNNING, Set.of(
                    RunStatus.SUCCESS,
                    RunStatus.ASSERTION_FAILED,
                    RunStatus.EXECUTION_FAILED,
                    RunStatus.TIMEOUT,
                    RunStatus.CANCELLED),
            RunStatus.SUCCESS, Set.of(),
            RunStatus.ASSERTION_FAILED, Set.of(),
            RunStatus.EXECUTION_FAILED, Set.of(),
            RunStatus.TIMEOUT, Set.of(),
            RunStatus.CANCELLED, Set.of());

    private RunStatus currentStatus;

    public RunStateMachine() {
        this(RunStatus.PENDING);
    }

    public RunStateMachine(RunStatus initialStatus) {
        this.currentStatus = Objects.requireNonNull(initialStatus, "initialStatus must not be null");
    }

    public RunStatus currentStatus() {
        return currentStatus;
    }

    public boolean canTransitionTo(RunStatus targetStatus) {
        return targetStatus != null
                && ALLOWED_TRANSITIONS.get(currentStatus).contains(targetStatus);
    }

    public RunStatus transitionTo(RunStatus targetStatus) {
        if (!canTransitionTo(targetStatus)) {
            throw new InvalidRunStateTransitionException(currentStatus, targetStatus);
        }
        currentStatus = targetStatus;
        return currentStatus;
    }
}
