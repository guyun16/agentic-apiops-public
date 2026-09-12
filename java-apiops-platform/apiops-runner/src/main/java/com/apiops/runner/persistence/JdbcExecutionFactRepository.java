package com.apiops.runner.persistence;

import com.apiops.common.enums.FailureType;
import com.apiops.runner.assertion.AssertionResult;
import com.apiops.runner.dsl.AssertionType;
import com.apiops.runner.execution.StepResult;
import com.apiops.runner.http.HttpResponseSnapshot;
import com.apiops.runner.state.RunStatus;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.sql.Timestamp;
import java.sql.Types;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Optional;
import java.util.UUID;

/** Plain JDBC adapter for the runner execution fact tables. */
public final class JdbcExecutionFactRepository implements ExecutionFactRepository {

    @Override
    public Optional<UUID> findBatchIdForRun(long projectId, long runId) {
        requirePositive(projectId, "projectId");
        requirePositive(runId, "runId");
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     "SELECT batch_id FROM test_batch_run WHERE project_id = ? AND run_id = ?")) {
            statement.setLong(1, projectId);
            statement.setLong(2, runId);
            try (ResultSet result = statement.executeQuery()) {
                return result.next() ? Optional.of(UUID.fromString(result.getString(1))) : Optional.empty();
            }
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to find execution batch", exception);
        }
    }

    private static final String INSERT_BATCH = """
            INSERT INTO test_batch (id, project_id, requested_by, status)
            VALUES (?, ?, ?, 'PENDING')
            """;
    private static final String INSERT_BATCH_RUN = """
            INSERT INTO test_batch_run (batch_id, project_id, run_id, member_order)
            VALUES (?, ?, ?, ?)
            """;
    private static final String FIND_BATCH = """
            SELECT project_id, requested_by, status, cancel_requested,
                   started_at, finished_at
            FROM test_batch
            WHERE project_id = ? AND id = ?
            """;
    private static final String FIND_BATCH_MEMBERS = """
            SELECT r.task_id, br.run_id
            FROM test_batch_run br
            JOIN test_run r ON r.project_id = br.project_id AND r.id = br.run_id
            WHERE br.project_id = ? AND br.batch_id = ?
            ORDER BY br.member_order
            """;
    private static final String CLAIM_BATCH = """
            UPDATE test_batch
            SET status = 'RUNNING', started_at = ?
            WHERE project_id = ? AND id = ? AND status = 'PENDING'
            """;
    private static final String REQUEST_BATCH_CANCEL = """
            UPDATE test_batch
            SET cancel_requested = 1
            WHERE project_id = ? AND id = ?
              AND status IN ('PENDING', 'RUNNING') AND cancel_requested = 0
            """;
    private static final String COMPLETE_BATCH = """
            UPDATE test_batch
            SET status = CASE WHEN cancel_requested = 1 THEN 'CANCELLED' ELSE ? END,
                finished_at = ?
            WHERE project_id = ? AND id = ? AND status IN ('PENDING', 'RUNNING')
            """;

    private static final String INSERT_TASK = """
            INSERT INTO test_task
                (project_id, case_id, api_id, task_name, testcase_dsl_json)
            VALUES (?, ?, ?, ?, ?)
            """;

    private static final String CLOSE_UNSTARTED_BATCH_MEMBERS = """
            UPDATE test_run r
            JOIN test_batch_run br ON br.project_id = r.project_id AND br.run_id = r.id
            JOIN test_batch b ON b.project_id = br.project_id AND b.id = br.batch_id
            SET r.status = b.status,
                r.failure_type = CASE WHEN b.status = 'CANCELLED' THEN 'NONE' ELSE 'SYSTEM_ERROR' END,
                r.finished_at = b.finished_at
            WHERE b.project_id = ? AND b.id = ?
              AND b.status IN ('EXECUTION_FAILED', 'CANCELLED') AND r.status = 'PENDING'
            """;

    private static final String INSERT_RUN = """
            INSERT INTO test_run
                (project_id, task_id, status, failure_type, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """;

    private static final String INSERT_CASE_RESULT = """
            INSERT INTO case_result
                (project_id, run_id, case_id, status, failure_type, started_at, finished_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """;

    private static final String INSERT_STEP_RESULT = """
            INSERT INTO step_result
                (project_id, run_id, case_result_id, step_id, status, failure_type,
                 assertion_results_json, response_status_code, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """;

    private static final String TASK_EXISTS =
            "SELECT 1 FROM test_task WHERE project_id = ? AND id = ?";
    private static final String RUN_EXISTS =
            "SELECT 1 FROM test_run WHERE project_id = ? AND id = ?";
    private static final String CASE_RESULT_EXISTS = """
            SELECT 1 FROM case_result
            WHERE project_id = ? AND run_id = ? AND id = ?
            """;

    private static final String FIND_EXECUTION_INPUT = """
            SELECT r.project_id, r.task_id, r.id AS run_id,
                   t.case_id, t.api_id, t.testcase_dsl_json
            FROM test_run r
            JOIN test_task t
              ON t.project_id = r.project_id AND t.id = r.task_id
            WHERE r.id = ?
            """;

    private static final String CLAIM_RUN = """
            UPDATE test_run
            SET status = 'RUNNING', started_at = ?
            WHERE project_id = ? AND id = ? AND status = 'PENDING'
            """;

    private static final String COMPLETE_RUN = """
            UPDATE test_run
            SET status = ?, failure_type = ?, finished_at = ?
            WHERE id = ? AND status = 'RUNNING'
            """;

    private static final String CANCEL_PENDING_RUN = """
            UPDATE test_run
            SET status = 'CANCELLED', failure_type = 'NONE', finished_at = ?
            WHERE project_id = ? AND id = ? AND status = 'PENDING'
            """;

    private static final String FIND_RUN = """
            SELECT r.project_id, r.task_id, r.id AS run_id,
                   t.case_id, t.api_id, t.task_name,
                   r.status, r.failure_type, r.started_at, r.finished_at
            FROM test_run r
            JOIN test_task t
              ON t.project_id = r.project_id AND t.id = r.task_id
            WHERE r.project_id = ? AND r.id = ?
            """;

    private static final String FIND_RECENT_RUN_SUMMARIES = """
            SELECT r.id AS run_id, t.case_id, t.api_id, t.task_name,
                   r.status, r.failure_type, r.created_at, r.started_at, r.finished_at
            FROM test_run r
            JOIN test_task t
              ON t.project_id = r.project_id AND t.id = r.task_id
            WHERE r.project_id = ?
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT 100
            """;

    private static final String FIND_LATEST_RUN_SUMMARY_BY_CASE = """
            SELECT r.id AS run_id, t.case_id, t.api_id, t.task_name,
                   r.status, r.failure_type, r.created_at, r.started_at, r.finished_at
            FROM test_run r
            JOIN test_task t
              ON t.project_id = r.project_id AND t.id = r.task_id
            WHERE r.project_id = ? AND t.case_id = ?
            ORDER BY r.created_at DESC, r.id DESC
            LIMIT 1
            """;

    private static final String FIND_RUN_SUMMARY_PAGE = """
            SELECT r.id AS run_id, t.case_id, t.api_id, t.task_name,
                   r.status, r.failure_type, r.created_at, r.started_at, r.finished_at
            FROM test_run r
            JOIN test_task t
              ON t.project_id = r.project_id AND t.id = r.task_id
            WHERE r.project_id = ? AND (? IS NULL OR r.id < ?)
            ORDER BY r.id DESC
            LIMIT ?
            """;

    private static final String FIND_CASE_RESULTS = """
            SELECT project_id, run_id, id AS case_result_id, case_id,
                   status, failure_type, started_at, finished_at
            FROM case_result
            WHERE project_id = ? AND run_id = ?
            ORDER BY id
            """;

    private static final String FIND_STEP_RESULTS = """
            SELECT s.project_id, s.run_id, s.case_result_id, s.id AS step_result_id,
                   s.step_id, s.status, s.failure_type, s.assertion_results_json,
                   s.response_status_code, s.duration_ms, s.created_at, x.snapshot_json
            FROM step_result s
            LEFT JOIN step_exchange_snapshot x ON x.step_result_id = s.id
            WHERE s.project_id = ? AND s.run_id = ? AND s.case_result_id = ?
            ORDER BY s.id
            """;

    private final DataSource dataSource;
    private final ObjectMapper objectMapper;

    public JdbcExecutionFactRepository(DataSource dataSource) {
        this(dataSource, new ObjectMapper());
    }

    public JdbcExecutionFactRepository(DataSource dataSource, ObjectMapper objectMapper) {
        this.dataSource = Objects.requireNonNull(dataSource, "dataSource must not be null");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
    }

    @Override
    public PreparedBatch prepareBatch(
            UUID batchId, long projectId, long requestedBy, List<PreparedRun> runs) {
        Objects.requireNonNull(batchId, "batchId must not be null");
        requirePositive(projectId, "projectId");
        requirePositive(requestedBy, "requestedBy");
        List<PreparedRun> cases = List.copyOf(
                Objects.requireNonNull(runs, "runs must not be null"));
        if (cases.isEmpty()) throw new IllegalArgumentException("runs must not be empty");
        try (Connection connection = dataSource.getConnection()) {
            boolean originalAutoCommit = connection.getAutoCommit();
            connection.setAutoCommit(false);
            try {
                try (PreparedStatement statement = connection.prepareStatement(INSERT_BATCH)) {
                    statement.setString(1, batchId.toString());
                    statement.setLong(2, projectId);
                    statement.setLong(3, requestedBy);
                    statement.executeUpdate();
                }
                List<BatchMember> members = new ArrayList<>(cases.size());
                for (int index = 0; index < cases.size(); index++) {
                    PreparedRun prepared = cases.get(index);
                    validateTask(projectId, prepared.caseId(), prepared.apiId(),
                            prepared.name(), prepared.testCaseDslJson());
                    long taskId = insertTask(connection, projectId, prepared.caseId(),
                            prepared.apiId(), prepared.name(), prepared.testCaseDslJson());
                    long runId = insertRun(connection, projectId, taskId, RunStatus.PENDING,
                            FailureType.NONE, null, null);
                    try (PreparedStatement statement = connection.prepareStatement(
                            INSERT_BATCH_RUN)) {
                        statement.setString(1, batchId.toString());
                        statement.setLong(2, projectId);
                        statement.setLong(3, runId);
                        statement.setInt(4, index);
                        statement.executeUpdate();
                    }
                    members.add(new BatchMember(taskId, runId));
                }
                connection.commit();
                return new PreparedBatch(batchId, projectId, members);
            } catch (SQLException | RuntimeException exception) {
                rollback(connection, exception);
                throw exception;
            } finally {
                connection.setAutoCommit(originalAutoCommit);
            }
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to prepare execution batch", exception);
        }
    }

    @Override
    public Optional<BatchExecutionFacts> findBatch(long projectId, UUID batchId) {
        requirePositive(projectId, "projectId");
        Objects.requireNonNull(batchId, "batchId must not be null");
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(FIND_BATCH)) {
            statement.setLong(1, projectId);
            statement.setString(2, batchId.toString());
            try (ResultSet rows = statement.executeQuery()) {
                if (!rows.next()) return Optional.empty();
                return Optional.of(new BatchExecutionFacts(
                        batchId,
                        rows.getLong("project_id"),
                        rows.getLong("requested_by"),
                        runStatus(rows.getString("status")),
                        rows.getBoolean("cancel_requested"),
                        timestamp(rows, "started_at"),
                        timestamp(rows, "finished_at"),
                        findBatchMembers(connection, projectId, batchId)));
            }
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to load execution batch", exception);
        }
    }

    @Override
    public boolean tryClaimBatch(long projectId, UUID batchId, Instant startedAt) {
        requirePositive(projectId, "projectId");
        Objects.requireNonNull(batchId, "batchId must not be null");
        Objects.requireNonNull(startedAt, "startedAt must not be null");
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(CLAIM_BATCH)) {
            setTimestamp(statement, 1, startedAt);
            statement.setLong(2, projectId);
            statement.setString(3, batchId.toString());
            return statement.executeUpdate() == 1;
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to claim execution batch", exception);
        }
    }

    @Override
    public boolean requestBatchCancel(long projectId, UUID batchId) {
        return updateBatchIdentity(REQUEST_BATCH_CANCEL, projectId, batchId) == 1;
    }

    @Override
    public boolean completeBatch(
            long projectId, UUID batchId, RunStatus terminalStatus, Instant finishedAt) {
        requireTerminal(terminalStatus);
        Objects.requireNonNull(finishedAt, "finishedAt must not be null");
        requirePositive(projectId, "projectId");
        Objects.requireNonNull(batchId, "batchId must not be null");
        try (Connection connection = dataSource.getConnection()) {
            boolean originalAutoCommit = connection.getAutoCommit();
            connection.setAutoCommit(false);
            try {
                int updated;
                try (PreparedStatement statement = connection.prepareStatement(COMPLETE_BATCH)) {
                    statement.setString(1, terminalStatus.name());
                    setTimestamp(statement, 2, finishedAt);
                    statement.setLong(3, projectId);
                    statement.setString(4, batchId.toString());
                    updated = statement.executeUpdate();
                }
                // Started runs retain their owner and outcome; retries cannot rewrite history.
                if (updated == 1) {
                    try (PreparedStatement statement = connection.prepareStatement(CLOSE_UNSTARTED_BATCH_MEMBERS)) {
                        statement.setLong(1, projectId);
                        statement.setString(2, batchId.toString());
                        statement.executeUpdate();
                    }
                }
                connection.commit();
                return updated == 1;
            } catch (SQLException | RuntimeException exception) {
                rollback(connection, exception);
                throw exception;
            } finally {
                connection.setAutoCommit(originalAutoCommit);
            }
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to complete execution batch", exception);
        }
    }

    @Override
    public long prepareRun(
            long projectId,
            String caseId,
            String apiId,
            String name,
            String testCaseDslJson) {
        validateTask(projectId, caseId, apiId, name, testCaseDslJson);
        try (Connection connection = dataSource.getConnection()) {
            boolean originalAutoCommit = connection.getAutoCommit();
            connection.setAutoCommit(false);
            try {
                long taskId = insertTask(
                        connection, projectId, caseId, apiId, name, testCaseDslJson);
                long runId = insertRun(
                        connection,
                        projectId,
                        taskId,
                        RunStatus.PENDING,
                        FailureType.NONE,
                        null,
                        null);
                connection.commit();
                return runId;
            } catch (SQLException | RuntimeException exception) {
                rollback(connection, exception);
                throw exception;
            } finally {
                connection.setAutoCommit(originalAutoCommit);
            }
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to prepare test run", exception);
        }
    }

    @Override
    public long saveTask(
            long projectId,
            String caseId,
            String apiId,
            String name,
            String testCaseDslJson) {
        validateTask(projectId, caseId, apiId, name, testCaseDslJson);
        try (Connection connection = dataSource.getConnection()) {
            return insertTask(connection, projectId, caseId, apiId, name, testCaseDslJson);
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to save test task", exception);
        }
    }

    @Override
    public long saveRun(
            long projectId,
            long taskId,
            RunStatus status,
            FailureType failureType,
            Instant startedAt,
            Instant finishedAt) {
        requirePositive(projectId, "projectId");
        requirePositive(taskId, "taskId");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(failureType, "failureType must not be null");
        if (status == RunStatus.PENDING && (startedAt != null || finishedAt != null)) {
            throw new IllegalArgumentException("PENDING run timestamps must be null");
        }
        if (status != RunStatus.PENDING && startedAt == null) {
            throw new IllegalArgumentException("startedAt must not be null after PENDING");
        }
        try (Connection connection = dataSource.getConnection()) {
            requireParent(connection, TASK_EXISTS, projectId, taskId, "test task");
            return insertRun(
                    connection, projectId, taskId, status, failureType, startedAt, finishedAt);
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to save test run", exception);
        }
    }

    @Override
    public Optional<RunExecutionInput> findExecutionInput(long runId) {
        requirePositive(runId, "runId");
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(FIND_EXECUTION_INPUT)) {
            statement.setLong(1, runId);
            try (ResultSet rows = statement.executeQuery()) {
                if (!rows.next()) {
                    return Optional.empty();
                }
                return Optional.of(new RunExecutionInput(
                        rows.getLong("project_id"),
                        rows.getLong("task_id"),
                        rows.getLong("run_id"),
                        rows.getString("case_id"),
                        rows.getString("api_id"),
                        rows.getString("testcase_dsl_json")));
            }
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to load run execution input", exception);
        }
    }

    @Override
    public boolean tryClaim(long projectId, long runId, Instant startedAt) {
        requirePositive(projectId, "projectId");
        requirePositive(runId, "runId");
        Objects.requireNonNull(startedAt, "startedAt must not be null");
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(CLAIM_RUN)) {
            setTimestamp(statement, 1, startedAt);
            statement.setLong(2, projectId);
            statement.setLong(3, runId);
            return statement.executeUpdate() == 1;
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to claim test run", exception);
        }
    }

    @Override
    public boolean cancelPendingRun(long projectId, long runId, Instant finishedAt) {
        requirePositive(projectId, "projectId");
        requirePositive(runId, "runId");
        Objects.requireNonNull(finishedAt, "finishedAt must not be null");
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(CANCEL_PENDING_RUN)) {
            setTimestamp(statement, 1, finishedAt);
            statement.setLong(2, projectId);
            statement.setLong(3, runId);
            return statement.executeUpdate() == 1;
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to cancel pending test run", exception);
        }
    }

    @Override
    public boolean completeRun(
            long runId,
            RunStatus terminalStatus,
            FailureType failureType,
            Instant finishedAt) {
        requirePositive(runId, "runId");
        requireTerminal(terminalStatus);
        Objects.requireNonNull(failureType, "failureType must not be null");
        Objects.requireNonNull(finishedAt, "finishedAt must not be null");
        try (Connection connection = dataSource.getConnection()) {
            return completeRun(connection, runId, terminalStatus, failureType, finishedAt) == 1;
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to complete test run", exception);
        }
    }

    @Override
    public long saveCaseResult(
            long projectId,
            long runId,
            String caseId,
            RunStatus status,
            FailureType failureType,
            Instant startedAt,
            Instant finishedAt) {
        requirePositive(projectId, "projectId");
        requirePositive(runId, "runId");
        requireText(caseId, "caseId");
        Objects.requireNonNull(status, "status must not be null");
        Objects.requireNonNull(failureType, "failureType must not be null");
        Objects.requireNonNull(startedAt, "startedAt must not be null");
        try (Connection connection = dataSource.getConnection()) {
            requireParent(connection, RUN_EXISTS, projectId, runId, "test run");
            return insertCaseResult(connection, projectId, runId, caseId,
                    status, failureType, startedAt, finishedAt);
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to save case result", exception);
        }
    }

    @Override
    public long saveStepResult(
            long projectId,
            long runId,
            long caseResultId,
            String stepId,
            StepResult result) {
        requirePositive(projectId, "projectId");
        requirePositive(runId, "runId");
        requirePositive(caseResultId, "caseResultId");
        requireText(stepId, "stepId");
        Objects.requireNonNull(result, "result must not be null");
        try (Connection connection = dataSource.getConnection()) {
            requireParent(connection, CASE_RESULT_EXISTS,
                    projectId, runId, caseResultId, "case result");
            return insertStepResult(connection, projectId, runId,
                    caseResultId, stepId, result);
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to save step result", exception);
        }
    }

    @Override
    public void saveExecutionOutcome(RunExecutionOutcome outcome) {
        Objects.requireNonNull(outcome, "outcome must not be null");
        requirePositive(outcome.projectId(), "projectId");
        requirePositive(outcome.runId(), "runId");
        requireText(outcome.caseId(), "caseId");
        requireTerminal(outcome.status());

        try (Connection connection = dataSource.getConnection()) {
            boolean originalAutoCommit = connection.getAutoCommit();
            connection.setAutoCommit(false);
            try {
                requireParent(connection, RUN_EXISTS,
                        outcome.projectId(), outcome.runId(), "test run");
                long caseResultId = insertCaseResult(
                        connection,
                        outcome.projectId(),
                        outcome.runId(),
                        outcome.caseId(),
                        outcome.status(),
                        outcome.failureType(),
                        outcome.startedAt(),
                        outcome.finishedAt());
                for (StepExecutionOutcome step : outcome.stepResults()) {
                    insertStepResult(
                            connection,
                            outcome.projectId(),
                            outcome.runId(),
                            caseResultId,
                            step.stepId(),
                            step.result());
                }
                int affectedRows = completeRun(
                        connection,
                        outcome.runId(),
                        outcome.status(),
                        outcome.failureType(),
                        outcome.finishedAt());
                if (affectedRows != 1) {
                    throw new SQLException("RUNNING test run could not be completed");
                }
                connection.commit();
            } catch (SQLException | RuntimeException exception) {
                rollback(connection, exception);
                throw exception;
            } finally {
                connection.setAutoCommit(originalAutoCommit);
            }
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to save execution outcome", exception);
        }
    }

    @Override
    public List<RunSummary> findRecentRunSummaries(long projectId) {
        requirePositive(projectId, "projectId");
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(FIND_RECENT_RUN_SUMMARIES)) {
            statement.setLong(1, projectId);
            try (ResultSet rows = statement.executeQuery()) {
                List<RunSummary> summaries = new ArrayList<>();
                while (rows.next()) {
                    summaries.add(new RunSummary(
                            rows.getLong("run_id"),
                            rows.getString("case_id"),
                            rows.getString("api_id"),
                            rows.getString("task_name"),
                            runStatus(rows.getString("status")),
                            failureType(rows.getString("failure_type")),
                            timestamp(rows, "created_at"),
                            timestamp(rows, "started_at"),
                            timestamp(rows, "finished_at")));
                }
                return summaries;
            }
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to list test run summaries", exception);
        }
    }

    @Override
    public Optional<RunSummary> findLatestRunSummary(long projectId, String caseId) {
        requirePositive(projectId, "projectId");
        if (caseId == null || caseId.isBlank()) {
            throw new IllegalArgumentException("caseId must not be blank");
        }
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     FIND_LATEST_RUN_SUMMARY_BY_CASE)) {
            statement.setLong(1, projectId);
            statement.setString(2, caseId);
            try (ResultSet rows = statement.executeQuery()) {
                if (!rows.next()) {
                    return Optional.empty();
                }
                return Optional.of(runSummary(rows));
            }
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to resolve test run summary by case", exception);
        }
    }

    @Override
    public List<RunSummary> findRunSummariesPage(
            long projectId,
            Long beforeRunId,
            int limit
    ) {
        requirePositive(projectId, "projectId");
        if (beforeRunId != null) {
            requirePositive(beforeRunId, "beforeRunId");
        }
        if (limit < 1 || limit > 100) {
            throw new IllegalArgumentException("limit must be between 1 and 100");
        }
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(FIND_RUN_SUMMARY_PAGE)) {
            statement.setLong(1, projectId);
            if (beforeRunId == null) {
                statement.setNull(2, Types.BIGINT);
                statement.setNull(3, Types.BIGINT);
            } else {
                statement.setLong(2, beforeRunId);
                statement.setLong(3, beforeRunId);
            }
            statement.setInt(4, limit);
            try (ResultSet rows = statement.executeQuery()) {
                List<RunSummary> summaries = new ArrayList<>();
                while (rows.next()) {
                    summaries.add(runSummary(rows));
                }
                return summaries;
            }
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to page test run summaries", exception);
        }
    }

    @Override
    public Optional<RunExecutionFacts> findRun(long projectId, long runId) {
        requirePositive(projectId, "projectId");
        requirePositive(runId, "runId");
        try (Connection connection = dataSource.getConnection()) {
            RunRow run;
            try (PreparedStatement statement = connection.prepareStatement(FIND_RUN)) {
                statement.setLong(1, projectId);
                statement.setLong(2, runId);
                try (ResultSet rows = statement.executeQuery()) {
                    if (!rows.next()) {
                        return Optional.empty();
                    }
                    run = new RunRow(
                            rows.getLong("project_id"),
                            rows.getLong("task_id"),
                            rows.getLong("run_id"),
                            rows.getString("case_id"),
                            rows.getString("api_id"),
                            rows.getString("task_name"),
                            runStatus(rows.getString("status")),
                            failureType(rows.getString("failure_type")),
                            timestamp(rows, "started_at"),
                            timestamp(rows, "finished_at"));
                }
            }
            return Optional.of(new RunExecutionFacts(
                    run.projectId(),
                    run.taskId(),
                    run.runId(),
                    run.caseId(),
                    run.apiId(),
                    run.taskName(),
                    run.status(),
                    run.failureType(),
                    run.startedAt(),
                    run.finishedAt(),
                    findCaseResults(connection, projectId, runId)));
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to load test run", exception);
        }
    }

    private RunSummary runSummary(ResultSet rows) throws SQLException {
        return new RunSummary(
                rows.getLong("run_id"),
                rows.getString("case_id"),
                rows.getString("api_id"),
                rows.getString("task_name"),
                runStatus(rows.getString("status")),
                failureType(rows.getString("failure_type")),
                timestamp(rows, "created_at"),
                timestamp(rows, "started_at"),
                timestamp(rows, "finished_at"));
    }

    private List<CaseExecutionFacts> findCaseResults(
            Connection connection, long projectId, long runId) throws SQLException {
        List<CaseRow> rows = new ArrayList<>();
        try (PreparedStatement statement = connection.prepareStatement(FIND_CASE_RESULTS)) {
            statement.setLong(1, projectId);
            statement.setLong(2, runId);
            try (ResultSet resultSet = statement.executeQuery()) {
                while (resultSet.next()) {
                    rows.add(new CaseRow(
                            resultSet.getLong("project_id"),
                            resultSet.getLong("run_id"),
                            resultSet.getLong("case_result_id"),
                            resultSet.getString("case_id"),
                            runStatus(resultSet.getString("status")),
                            failureType(resultSet.getString("failure_type")),
                            timestamp(resultSet, "started_at"),
                            timestamp(resultSet, "finished_at")));
                }
            }
        }
        return rows.stream()
                .map(row -> new CaseExecutionFacts(
                        row.projectId(),
                        row.runId(),
                        row.caseResultId(),
                        row.caseId(),
                        row.status(),
                        row.failureType(),
                        row.startedAt(),
                        row.finishedAt(),
                        findStepResultsUnchecked(connection, projectId, runId, row.caseResultId())))
                .toList();
    }

    private List<BatchMember> findBatchMembers(
            Connection connection, long projectId, UUID batchId) throws SQLException {
        List<BatchMember> members = new ArrayList<>();
        try (PreparedStatement statement = connection.prepareStatement(FIND_BATCH_MEMBERS)) {
            statement.setLong(1, projectId);
            statement.setString(2, batchId.toString());
            try (ResultSet rows = statement.executeQuery()) {
                while (rows.next()) {
                    members.add(new BatchMember(rows.getLong("task_id"), rows.getLong("run_id")));
                }
            }
        }
        return List.copyOf(members);
    }

    private int updateBatchIdentity(String sql, long projectId, UUID batchId) {
        requirePositive(projectId, "projectId");
        Objects.requireNonNull(batchId, "batchId must not be null");
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setLong(1, projectId);
            statement.setString(2, batchId.toString());
            return statement.executeUpdate();
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to update execution batch", exception);
        }
    }

    private List<StepExecutionFacts> findStepResultsUnchecked(
            Connection connection,
            long projectId,
            long runId,
            long caseResultId) {
        try {
            return findStepResults(connection, projectId, runId, caseResultId);
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to load step results", exception);
        }
    }

    private List<StepExecutionFacts> findStepResults(
            Connection connection,
            long projectId,
            long runId,
            long caseResultId) throws SQLException {
        List<StepExecutionFacts> values = new ArrayList<>();
        try (PreparedStatement statement = connection.prepareStatement(FIND_STEP_RESULTS)) {
            statement.setLong(1, projectId);
            statement.setLong(2, runId);
            statement.setLong(3, caseResultId);
            try (ResultSet rows = statement.executeQuery()) {
                while (rows.next()) {
                    values.add(new StepExecutionFacts(
                            rows.getLong("project_id"),
                            rows.getLong("run_id"),
                            rows.getLong("case_result_id"),
                            rows.getLong("step_result_id"),
                            rows.getString("step_id"),
                            runStatus(rows.getString("status")),
                            failureType(rows.getString("failure_type")),
                            rows.getString("assertion_results_json"),
                            nullableInteger(rows, "response_status_code"),
                            nullableLong(rows, "duration_ms"),
                            timestamp(rows, "created_at"), rows.getString("snapshot_json")));
                }
            }
        }
        return List.copyOf(values);
    }

    private long insertTask(
            Connection connection,
            long projectId,
            String caseId,
            String apiId,
            String name,
            String testCaseDslJson) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                INSERT_TASK, Statement.RETURN_GENERATED_KEYS)) {
            statement.setLong(1, projectId);
            statement.setString(2, caseId);
            statement.setString(3, apiId);
            statement.setString(4, name);
            statement.setString(5, testCaseDslJson);
            statement.executeUpdate();
            return generatedId(statement);
        }
    }

    private long insertRun(
            Connection connection,
            long projectId,
            long taskId,
            RunStatus status,
            FailureType failureType,
            Instant startedAt,
            Instant finishedAt) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                INSERT_RUN, Statement.RETURN_GENERATED_KEYS)) {
            statement.setLong(1, projectId);
            statement.setLong(2, taskId);
            statement.setString(3, status.name());
            statement.setString(4, failureType.name());
            setTimestamp(statement, 5, startedAt);
            setTimestamp(statement, 6, finishedAt);
            statement.executeUpdate();
            return generatedId(statement);
        }
    }

    private long insertCaseResult(
            Connection connection,
            long projectId,
            long runId,
            String caseId,
            RunStatus status,
            FailureType failureType,
            Instant startedAt,
            Instant finishedAt) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                INSERT_CASE_RESULT, Statement.RETURN_GENERATED_KEYS)) {
            statement.setLong(1, projectId);
            statement.setLong(2, runId);
            statement.setString(3, caseId);
            statement.setString(4, status.name());
            statement.setString(5, failureType.name());
            setTimestamp(statement, 6, startedAt);
            setTimestamp(statement, 7, finishedAt);
            statement.executeUpdate();
            return generatedId(statement);
        }
    }

    private long insertStepResult(
            Connection connection,
            long projectId,
            long runId,
            long caseResultId,
            String stepId,
            StepResult result) throws SQLException {
        String assertionResultsJson = assertionResultsJson(result);
        HttpResponseSnapshot response = result.responseSnapshot();
        try (PreparedStatement statement = connection.prepareStatement(
                INSERT_STEP_RESULT, Statement.RETURN_GENERATED_KEYS)) {
            statement.setLong(1, projectId);
            statement.setLong(2, runId);
            statement.setLong(3, caseResultId);
            statement.setString(4, stepId);
            statement.setString(5, result.status().name());
            statement.setString(6, result.failureType().name());
            statement.setString(7, assertionResultsJson);
            if (response == null) {
                statement.setNull(8, Types.INTEGER);
                statement.setNull(9, Types.BIGINT);
            } else {
                statement.setInt(8, response.statusCode());
                statement.setLong(9, response.durationMs());
            }
            statement.executeUpdate();
            long stepResultId = generatedId(statement);
            if (result.httpExchange() != null) {
                try (PreparedStatement exchange = connection.prepareStatement(
                        "INSERT INTO step_exchange_snapshot (step_result_id, snapshot_json) VALUES (?, ?)")) {
                    exchange.setLong(1, stepResultId);
                    exchange.setString(2, exchangeJson(result));
                    exchange.executeUpdate();
                }
            }
            return stepResultId;
        }
    }

    private String exchangeJson(StepResult result) {
        try {
            return objectMapper.writeValueAsString(result.httpExchange());
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Unable to serialize redacted HTTP exchange", exception);
        }
    }

    private static int completeRun(
            Connection connection,
            long runId,
            RunStatus terminalStatus,
            FailureType failureType,
            Instant finishedAt) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(COMPLETE_RUN)) {
            statement.setString(1, terminalStatus.name());
            statement.setString(2, failureType.name());
            setTimestamp(statement, 3, finishedAt);
            statement.setLong(4, runId);
            return statement.executeUpdate();
        }
    }

    private static void rollback(Connection connection, Exception original) {
        try {
            connection.rollback();
        } catch (SQLException rollbackFailure) {
            original.addSuppressed(rollbackFailure);
        }
    }

    private String assertionResultsJson(StepResult result) {
        try {
            ArrayNode values = objectMapper.createArrayNode();
            for (AssertionResult assertion : result.assertionResults()) {
                ObjectNode value = objectMapper.valueToTree(assertion);
                if (assertion.type() == AssertionType.HEADER) {
                    // Header assertion values may contain Authorization/Cookie/API key material.
                    value.put("expected", "[REDACTED]");
                    value.put("actual", "[REDACTED]");
                }
                values.add(value);
            }
            return objectMapper.writeValueAsString(values);
        } catch (JsonProcessingException | IllegalArgumentException exception) {
            throw new IllegalStateException("Unable to serialize assertion results", exception);
        }
    }

    private static long generatedId(PreparedStatement statement) throws SQLException {
        try (ResultSet keys = statement.getGeneratedKeys()) {
            if (!keys.next()) {
                throw new SQLException("Insert did not return a generated id");
            }
            return keys.getLong(1);
        }
    }

    private static void requireParent(
            Connection connection,
            String sql,
            long projectId,
            long parentId,
            String parentName) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setLong(1, projectId);
            statement.setLong(2, parentId);
            try (ResultSet rows = statement.executeQuery()) {
                if (!rows.next()) {
                    throw new SQLException(parentName + " does not belong to project");
                }
            }
        }
    }

    private static void requireParent(
            Connection connection,
            String sql,
            long projectId,
            long runId,
            long caseResultId,
            String parentName) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setLong(1, projectId);
            statement.setLong(2, runId);
            statement.setLong(3, caseResultId);
            try (ResultSet rows = statement.executeQuery()) {
                if (!rows.next()) {
                    throw new SQLException(parentName + " does not belong to project and run");
                }
            }
        }
    }

    private static void setTimestamp(
            PreparedStatement statement, int index, Instant value) throws SQLException {
        if (value == null) {
            statement.setNull(index, Types.TIMESTAMP);
        } else {
            statement.setTimestamp(index, Timestamp.from(value));
        }
    }

    private static Instant timestamp(ResultSet rows, String column) throws SQLException {
        Timestamp value = rows.getTimestamp(column);
        return value == null ? null : value.toInstant();
    }

    private static Integer nullableInteger(ResultSet rows, String column) throws SQLException {
        int value = rows.getInt(column);
        return rows.wasNull() ? null : value;
    }

    private static Long nullableLong(ResultSet rows, String column) throws SQLException {
        long value = rows.getLong(column);
        return rows.wasNull() ? null : value;
    }

    private static RunStatus runStatus(String value) throws SQLException {
        try {
            return RunStatus.valueOf(value);
        } catch (RuntimeException exception) {
            throw new SQLException("Unknown run status: " + value, exception);
        }
    }

    private static FailureType failureType(String value) throws SQLException {
        try {
            return FailureType.valueOf(value);
        } catch (RuntimeException exception) {
            throw new SQLException("Unknown failure type: " + value, exception);
        }
    }

    private static void requirePositive(long value, String field) {
        if (value <= 0) {
            throw new IllegalArgumentException(field + " must be positive");
        }
    }

    private static void requireText(String value, String field) {
        if (value == null || value.isBlank()) {
            throw new IllegalArgumentException(field + " must not be blank");
        }
    }

    private static void validateTask(
            long projectId,
            String caseId,
            String apiId,
            String name,
            String testCaseDslJson) {
        requirePositive(projectId, "projectId");
        requireText(caseId, "caseId");
        requireText(apiId, "apiId");
        requireText(name, "name");
        requireText(testCaseDslJson, "testCaseDslJson");
    }

    private static void requireTerminal(RunStatus status) {
        Objects.requireNonNull(status, "status must not be null");
        if (!status.isTerminal()) {
            throw new IllegalArgumentException("status must be terminal");
        }
    }

    private static IllegalStateException persistenceFailure(String message, SQLException cause) {
        return new IllegalStateException(message, cause);
    }

    private record RunRow(
            long projectId,
            long taskId,
            long runId,
            String caseId,
            String apiId,
            String taskName,
            RunStatus status,
            FailureType failureType,
            Instant startedAt,
            Instant finishedAt
    ) {
    }

    private record CaseRow(
            long projectId,
            long runId,
            long caseResultId,
            String caseId,
            RunStatus status,
            FailureType failureType,
            Instant startedAt,
            Instant finishedAt
    ) {
    }
}
