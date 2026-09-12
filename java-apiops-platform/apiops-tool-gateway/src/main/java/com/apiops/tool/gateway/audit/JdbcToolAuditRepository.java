package com.apiops.tool.gateway.audit;

import com.apiops.tool.gateway.Audit;
import com.apiops.tool.gateway.AuditStatus;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Types;
import java.util.Objects;
import java.util.Optional;

/** Plain JDBC adapter for the existing Tool Gateway audit event. */
public final class JdbcToolAuditRepository implements ToolAuditRepository {

    private static final String INSERT = """
            INSERT INTO tool_audit
                (tool_call_id, project_id, tool_name, status, violation_code,
                 sanitized_summary, latency_nanos, requested_target_project_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """;

    private static final String FIND = """
            SELECT tool_call_id, project_id, tool_name, status, violation_code,
                   sanitized_summary, latency_nanos, requested_target_project_id
            FROM tool_audit
            WHERE project_id = ? AND tool_call_id = ?
            """;

    private final DataSource dataSource;

    public JdbcToolAuditRepository(DataSource dataSource) {
        this.dataSource = Objects.requireNonNull(dataSource, "dataSource must not be null");
    }

    @Override
    public void save(Audit.AuditEvent event) {
        Objects.requireNonNull(event, "event must not be null");
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(INSERT)) {
            statement.setString(1, event.toolCallId());
            statement.setLong(2, event.projectId());
            statement.setString(3, event.toolName());
            statement.setString(4, event.status().name());
            statement.setString(5, event.violationCode());
            statement.setString(6, event.sanitizedSummary());
            statement.setLong(7, event.latencyNanos());
            if (event.requestedTargetProjectId() == null) {
                statement.setNull(8, Types.BIGINT);
            } else {
                statement.setLong(8, event.requestedTargetProjectId());
            }
            statement.executeUpdate();
        } catch (SQLException exception) {
            throw new IllegalStateException("Unable to persist Tool audit", exception);
        }
    }

    @Override
    public Optional<Audit.AuditEvent> findByToolCallId(long projectId, String toolCallId) {
        if (projectId <= 0) {
            throw new IllegalArgumentException("projectId must be positive");
        }
        requireText(toolCallId, "toolCallId");
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(FIND)) {
            statement.setLong(1, projectId);
            statement.setString(2, toolCallId);
            try (ResultSet resultSet = statement.executeQuery()) {
                if (!resultSet.next()) {
                    return Optional.empty();
                }
                long requestedTargetProjectId = resultSet.getLong(
                        "requested_target_project_id");
                Long requestedTarget = resultSet.wasNull() ? null : requestedTargetProjectId;
                return Optional.of(new Audit.AuditEvent(
                        resultSet.getString("tool_call_id"),
                        resultSet.getLong("project_id"),
                        resultSet.getString("tool_name"),
                        AuditStatus.valueOf(resultSet.getString("status")),
                        resultSet.getString("violation_code"),
                        resultSet.getString("sanitized_summary"),
                        resultSet.getLong("latency_nanos"),
                        requestedTarget));
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Unable to load Tool audit", exception);
        }
    }

    private static void requireText(String value, String name) {
        Objects.requireNonNull(value, name + " must not be null");
        if (value.isBlank()) {
            throw new IllegalArgumentException(name + " must not be blank");
        }
    }
}
