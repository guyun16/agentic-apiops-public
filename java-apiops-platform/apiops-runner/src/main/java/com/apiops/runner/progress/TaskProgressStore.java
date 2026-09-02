package com.apiops.runner.progress;

import com.apiops.runner.state.RunStatus;

import java.util.Optional;

public interface TaskProgressStore {
    TaskProgressSnapshot create(long projectId, long taskId, long runId, int total);
    TaskProgressSnapshot caseStarted(long projectId, long runId);
    TaskProgressSnapshot caseCompleted(long projectId, long runId, RunStatus status);
    TaskProgressSnapshot terminal(long projectId, long runId, RunStatus status);
    Optional<TaskProgressSnapshot> find(long projectId, long runId);
}
