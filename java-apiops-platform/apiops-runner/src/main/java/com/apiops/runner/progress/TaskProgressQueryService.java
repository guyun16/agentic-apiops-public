package com.apiops.runner.progress;

import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.persistence.ExecutionFactRepository.RunExecutionFacts;
import com.apiops.runner.state.RunStatus;

import java.time.Clock;
import java.time.Instant;
import java.util.Objects;
import java.util.Optional;

/** Reads the projection first and reconstructs a minimal current view from authoritative facts. */
public final class TaskProgressQueryService {
    private final TaskProgressStore store;
    private final ExecutionFactRepository repository;
    private final Clock clock;

    public TaskProgressQueryService(TaskProgressStore store, ExecutionFactRepository repository) {
        this(store, repository, Clock.systemUTC());
    }
    TaskProgressQueryService(TaskProgressStore store, ExecutionFactRepository repository, Clock clock) {
        this.store=Objects.requireNonNull(store); this.repository=Objects.requireNonNull(repository);
        this.clock=Objects.requireNonNull(clock);
    }

    public Optional<TaskProgressSnapshot> find(long projectId,long runId) {
        try {
            Optional<TaskProgressSnapshot> projected=store.find(projectId,runId);
            if(projected.isPresent()) return projected;
        } catch(RuntimeException ignored) {
            // Redis is a projection; MySQL facts remain readable.
        }
        return repository.findRun(projectId,runId).map(this::fromFacts);
    }

    private TaskProgressSnapshot fromFacts(RunExecutionFacts facts) {
        RunStatus status=facts.status(); boolean terminal=status.isTerminal();
        Instant updated=facts.finishedAt()!=null?facts.finishedAt():
                facts.startedAt()!=null?facts.startedAt():clock.instant();
        return new TaskProgressSnapshot(facts.projectId(),facts.taskId(),facts.runId(),1,
                terminal?1:0,status==RunStatus.RUNNING?1:0,status==RunStatus.SUCCESS?1:0,
                status==RunStatus.ASSERTION_FAILED?1:0,status==RunStatus.EXECUTION_FAILED?1:0,
                status==RunStatus.TIMEOUT?1:0,status==RunStatus.CANCELLED?1:0,status,updated);
    }
}
