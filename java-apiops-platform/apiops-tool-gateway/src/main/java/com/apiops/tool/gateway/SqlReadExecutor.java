package com.apiops.tool.gateway;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/** JDBC read handler; callers invoke it through the existing ToolGateway. */
public final class SqlReadExecutor {

    private final DataSource dataSource;
    private final SqlGuard guard;
    private final int queryTimeoutSeconds;

    public SqlReadExecutor(
            DataSource dataSource,
            SqlGuard guard,
            Duration queryTimeout
    ) {
        this.dataSource = Objects.requireNonNull(dataSource, "dataSource must not be null");
        this.guard = Objects.requireNonNull(guard, "guard must not be null");
        if (queryTimeout == null || queryTimeout.isZero() || queryTimeout.isNegative()) {
            throw new IllegalArgumentException("queryTimeout must be positive");
        }
        long milliseconds = queryTimeout.toMillis();
        this.queryTimeoutSeconds = (int) Math.max(1, Math.min(
                Integer.MAX_VALUE, (milliseconds + 999) / 1_000));
    }

    public Object execute(
            ToolExecutionContext context,
            ToolCallIntent intent
    ) throws SQLException {
        SqlGuard.Validation validation = guard.validate(intent);
        if (!validation.allowed()) {
            throw new SQLException("SQL denied: " + validation.reason());
        }

        try (Connection connection = dataSource.getConnection()) {
            connection.setReadOnly(true);
            try (PreparedStatement statement = connection.prepareStatement(validation.boundedSql())) {
                statement.setQueryTimeout(queryTimeoutSeconds);
                statement.setMaxRows(SqlGuard.MAX_ROWS);
                try (ResultSet resultSet = statement.executeQuery()) {
                    return readRows(resultSet);
                }
            }
        }
    }

    public int queryTimeoutSeconds() {
        return queryTimeoutSeconds;
    }

    private static List<Map<String, Object>> readRows(ResultSet resultSet) throws SQLException {
        ResultSetMetaData metadata = resultSet.getMetaData();
        int columnCount = metadata.getColumnCount();
        List<Map<String, Object>> rows = new ArrayList<>();
        while (rows.size() < SqlGuard.MAX_ROWS && resultSet.next()) {
            Map<String, Object> row = new LinkedHashMap<>();
            for (int column = 1; column <= columnCount; column++) {
                row.put(metadata.getColumnLabel(column), resultSet.getObject(column));
            }
            rows.add(Collections.unmodifiableMap(row));
        }
        return List.copyOf(rows);
    }
}
