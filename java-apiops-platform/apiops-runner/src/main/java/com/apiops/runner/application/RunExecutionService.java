package com.apiops.runner.application;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.dsl.TestCase;
import com.apiops.runner.dsl.TestStep;
import com.apiops.runner.execution.StepResult;
import com.apiops.runner.execution.TestStepRunner;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.persistence.ExecutionFactRepository.RunExecutionInput;
import com.apiops.runner.persistence.ExecutionFactRepository.RunExecutionOutcome;
import com.apiops.runner.persistence.ExecutionFactRepository.StepExecutionOutcome;
import com.apiops.runner.state.RunStateMachine;
import com.apiops.runner.state.RunStatus;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.micrometer.core.instrument.MeterRegistry;

import java.time.Clock;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Optional;

/** Application boundary for preparing and executing one persisted TestCase run. */
public final class RunExecutionService {

    private final ExecutionFactRepository repository;
    private final TestStepRunner stepRunner;
    private final ObjectMapper objectMapper;
    private final Clock clock;
    private final RunnerMetrics metrics;

    public RunExecutionService(
            ExecutionFactRepository repository,
            TestStepRunner stepRunner,
            ObjectMapper objectMapper) {
        this(repository, stepRunner, objectMapper, Clock.systemUTC(), null);
    }

    public RunExecutionService(
            ExecutionFactRepository repository,
            TestStepRunner stepRunner,
            ObjectMapper objectMapper,
            Clock clock) {
        this(repository, stepRunner, objectMapper, clock, null);
    }

    public RunExecutionService(
            ExecutionFactRepository repository,
            TestStepRunner stepRunner,
            ObjectMapper objectMapper,
            Clock clock,
            MeterRegistry meterRegistry) {
        this.repository = Objects.requireNonNull(repository, "repository must not be null");
        this.stepRunner = Objects.requireNonNull(stepRunner, "stepRunner must not be null");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
        this.clock = Objects.requireNonNull(clock, "clock must not be null");
        this.metrics = new RunnerMetrics(meterRegistry);
    }

    public long prepare(TestCase testCase) {
        Objects.requireNonNull(testCase, "testCase must not be null");
        if (testCase.steps().isEmpty()) {
            throw new IllegalArgumentException("testCase must contain at least one step");
        }
        String snapshot = writeSnapshot(testCase);
        return repository.prepareRun(
                testCase.projectId(),
                testCase.caseId(),
                testCase.apiId(),
                testCase.name(),
                snapshot);
    }

    /**
     * Executes the immutable snapshot for {@code runId}.
     *
     * @return the terminal status, or empty when this caller did not acquire ownership
     */
    public Optional<RunStatus> execute(long runId) {
        RunExecutionInput input = repository.findExecutionInput(runId)
                .orElseThrow(() -> new IllegalArgumentException("Test run not found: " + runId));
        TestCase testCase = readSnapshot(input);
        Instant startedAt = clock.instant();
        if (!repository.tryClaim(input.projectId(), runId, startedAt)) {
            return Optional.empty();
        }
        long metricStartedNanos = System.nanoTime();

        List<StepExecutionOutcome> stepOutcomes = new ArrayList<>(testCase.steps().size());
        final Aggregate aggregate;
        try {
            for (TestStep step : testCase.steps()) {
                StepResult result = stepRunner.run(testCase.environment(), step);
                stepOutcomes.add(new StepExecutionOutcome(step.stepId(), result));
            }
            aggregate = aggregate(stepOutcomes);
        } catch (RuntimeException executionFailure) {
            try {
                return persistOutcome(
                        input,
                        testCase,
                        startedAt,
                        RunStatus.EXECUTION_FAILED,
                        FailureType.SYSTEM_ERROR,
                        stepOutcomes,
                        metricStartedNanos);
            } catch (UnresolvedRunningExecutionException unresolved) {
                unresolved.addSuppressed(executionFailure);
                throw unresolved;
            }
        }
        return persistOutcome(
                input,
                testCase,
                startedAt,
                aggregate.status(),
                aggregate.failureType(),
                stepOutcomes,
                metricStartedNanos);
    }

    /** Returns a stable status for batch orchestration after the normal execution boundary. */
    public RunStatus executeBatchCase(long runId) {
        Optional<RunStatus> executed = execute(runId);
        return executed.orElseGet(() -> currentStatus(runId));
    }

    /** Cooperatively closes a case that has not acquired execution ownership. */
    public RunStatus cancelBeforeStart(long runId) {
        RunExecutionInput input = loadInput(runId);
        if (repository.cancelPendingRun(input.projectId(), runId, clock.instant())) {
            return RunStatus.CANCELLED;
        }
        return currentStatus(input);
    }

    /** Converts an executor rejection or pre-claim failure into a persisted execution failure. */
    public RunStatus failBeforeStart(long runId) {
        RunExecutionInput input = loadInput(runId);
        TestCase testCase = readSnapshot(input);
        Instant startedAt = clock.instant();
        if (!repository.tryClaim(input.projectId(), runId, startedAt)) {
            return currentStatus(input);
        }
        long metricStartedNanos = System.nanoTime();
        return persistOutcome(
                        input,
                        testCase,
                        startedAt,
                        RunStatus.EXECUTION_FAILED,
                        FailureType.SYSTEM_ERROR,
                        List.of(),
                        metricStartedNanos)
                .orElseThrow();
    }

    private Optional<RunStatus> persistOutcome(
            RunExecutionInput input,
            TestCase testCase,
            Instant startedAt,
            RunStatus outcomeStatus,
            FailureType failureType,
            List<StepExecutionOutcome> stepOutcomes,
            long metricStartedNanos) {
        try {
            RunStateMachine stateMachine = new RunStateMachine(RunStatus.RUNNING);
            RunStatus terminalStatus = stateMachine.transitionTo(outcomeStatus);
            Instant finishedAt = clock.instant();
            repository.saveExecutionOutcome(new RunExecutionOutcome(
                    input.projectId(),
                    input.runId(),
                    testCase.caseId(),
                    terminalStatus,
                    failureType,
                    startedAt,
                    finishedAt,
                    stepOutcomes));
            metrics.record(
                    terminalStatus,
                    failureType,
                    Math.max(0, System.nanoTime() - metricStartedNanos));
            return Optional.of(terminalStatus);
        } catch (RuntimeException persistenceFailure) {
            Optional<RunStatus> closed = closeClaimedRunOrThrow(input, persistenceFailure);
            closed.ifPresent(status -> metrics.record(
                    status,
                    FailureType.SYSTEM_ERROR,
                    Math.max(0, System.nanoTime() - metricStartedNanos)));
            return closed;
        }
    }

    private Optional<RunStatus> closeClaimedRunOrThrow(
            RunExecutionInput input, RuntimeException postClaimFailure) {
        RuntimeException completionFailure = null;
        try {
            if (repository.completeRun(
                    input.runId(),
                    RunStatus.EXECUTION_FAILED,
                    FailureType.SYSTEM_ERROR,
                    clock.instant())) {
                return Optional.of(RunStatus.EXECUTION_FAILED);
            }
        } catch (RuntimeException failure) {
            completionFailure = failure;
        }

        RuntimeException inspectionFailure = null;
        try {
            Optional<RunStatus> persistedStatus = repository.findRun(
                            input.projectId(), input.runId())
                    .map(ExecutionFactRepository.RunExecutionFacts::status)
                    .filter(RunStatus::isTerminal);
            if (persistedStatus.isPresent()) {
                return persistedStatus;
            }
        } catch (RuntimeException failure) {
            inspectionFailure = failure;
        }

        UnresolvedRunningExecutionException unresolved =
                new UnresolvedRunningExecutionException(
                        "Claimed test run could not be persisted to a terminal state: "
                                + input.runId(),
                        postClaimFailure);
        if (completionFailure != null) {
            unresolved.addSuppressed(completionFailure);
        }
        if (inspectionFailure != null) {
            unresolved.addSuppressed(inspectionFailure);
        }
        throw unresolved;
    }

    private String writeSnapshot(TestCase testCase) {
        try {
            return objectMapper.writeValueAsString(testCase);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Unable to serialize TestCase snapshot", exception);
        }
    }

    private RunExecutionInput loadInput(long runId) {
        return repository.findExecutionInput(runId)
                .orElseThrow(() -> new IllegalArgumentException("Test run not found: " + runId));
    }

    private RunStatus currentStatus(long runId) {
        return currentStatus(loadInput(runId));
    }

    private RunStatus currentStatus(RunExecutionInput input) {
        RunStatus status = repository.findRun(input.projectId(), input.runId())
                .orElseThrow(() -> new IllegalArgumentException(
                        "Test run not found: " + input.runId()))
                .status();
        if (status == RunStatus.RUNNING) {
            throw new UnresolvedRunningExecutionException(
                    "Test run is RUNNING; the current owner may be active or stale: "
                            + input.runId());
        }
        return status;
    }

    private TestCase readSnapshot(RunExecutionInput input) {
        final TestCase testCase;
        try {
            testCase = objectMapper.readValue(input.testCaseDslJson(), TestCase.class);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Unable to deserialize TestCase snapshot", exception);
        }
        if (testCase.projectId() != input.projectId()
                || !testCase.caseId().equals(input.caseId())
                || !testCase.apiId().equals(input.apiId())) {
            throw new IllegalStateException("TestCase snapshot identity does not match test task");
        }
        if (testCase.steps().isEmpty()) {
            throw new IllegalStateException("Persisted TestCase must contain at least one step");
        }
        return testCase;
    }

    private Aggregate aggregate(List<StepExecutionOutcome> outcomes) {
        StepResult selected = outcomes.getFirst().result();
        int selectedPriority = priority(selected.status());
        for (int index = 1; index < outcomes.size(); index++) {
            StepResult candidate = outcomes.get(index).result();
            int candidatePriority = priority(candidate.status());
            if (candidatePriority > selectedPriority) {
                selected = candidate;
                selectedPriority = candidatePriority;
            }
        }
        return new Aggregate(selected.status(), selected.failureType());
    }

    private int priority(RunStatus status) {
        return switch (status) {
            case SUCCESS -> 0;
            case ASSERTION_FAILED -> 1;
            case EXECUTION_FAILED -> 2;
            case TIMEOUT -> 3;
            case CANCELLED -> 4;
            case PENDING, RUNNING -> throw new IllegalStateException(
                    "Step result must be terminal: " + status);
        };
    }

    private record Aggregate(RunStatus status, FailureType failureType) {
    }
}
