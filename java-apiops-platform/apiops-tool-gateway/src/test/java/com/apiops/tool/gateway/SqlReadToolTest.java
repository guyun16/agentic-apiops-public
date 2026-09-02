package com.apiops.tool.gateway;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.common.enums.ToolStatus;
import com.apiops.common.tool.ToolResult;
import org.junit.jupiter.api.Test;

import javax.sql.DataSource;
import java.io.PrintWriter;
import java.lang.reflect.InvocationHandler;
import java.lang.reflect.Method;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.logging.Logger;
import java.util.stream.Stream;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class SqlReadToolTest {

    private static final long USER_ID = 7L;
    private static final long PROJECT_ID = 42L;

    @Test
    void normalSelectUsesGatewayAndBoundedReadOnlyJdbc() {
        RecordingDataSource dataSource = new RecordingDataSource();
        SqlGuard guard = SqlGuard.demoOrder();
        SqlReadExecutor executor = new SqlReadExecutor(
                dataSource, guard, Duration.ofMillis(1_500));

        try (ToolGateway gateway = gateway(guard)) {
            ToolResult<Object> result = SqlReadTool.execute(
                    gateway,
                    executor,
                    context("normal-select"),
                    intent("SELECT id, status FROM demo_order WHERE status = 'PAID'"));

            assertEquals(ToolStatus.SUCCESS, result.getStatus());
        }

        assertEquals(1, dataSource.connectionCalls);
        assertTrue(dataSource.readOnly);
        assertTrue(dataSource.sql.contains("LIMIT 100"));
        assertEquals(100, dataSource.maxRows);
        assertEquals(2, dataSource.queryTimeoutSeconds);
    }

    @Test
    void missingAndOversizedLimitAreBoundBeforeJdbcExecution() {
        RecordingDataSource dataSource = new RecordingDataSource();
        SqlGuard guard = SqlGuard.demoOrder();
        SqlReadExecutor executor = new SqlReadExecutor(
                dataSource, guard, Duration.ofSeconds(1));

        try (ToolGateway gateway = gateway(guard)) {
            ToolResult<Object> missingLimit = SqlReadTool.execute(
                    gateway,
                    executor,
                    context("missing-limit"),
                    intent("SELECT id FROM demo_order"));
            ToolResult<Object> oversizedLimit = SqlReadTool.execute(
                    gateway,
                    executor,
                    context("oversized-limit"),
                    intent("SELECT id FROM demo_order LIMIT 1000000"));

            assertEquals(ToolStatus.SUCCESS, missingLimit.getStatus());
            assertEquals(ToolStatus.SUCCESS, oversizedLimit.getStatus());
        }

        assertTrue(dataSource.sql.contains("LIMIT 100"));
        assertFalse(dataSource.sql.contains("1000000"));
        assertEquals(100, dataSource.maxRows);
    }

    @Test
    void deniedSqlDoesNotOpenJdbcConnection() {
        RecordingDataSource dataSource = new RecordingDataSource();
        SqlGuard guard = SqlGuard.demoOrder();
        SqlReadExecutor executor = new SqlReadExecutor(
                dataSource, guard, Duration.ofSeconds(1));

        try (ToolGateway gateway = gateway(guard)) {
            ToolResult<Object> result = SqlReadTool.execute(
                    gateway,
                    executor,
                    context("denied-star"),
                    intent("SELECT * FROM demo_order"));

            assertEquals(ToolStatus.FORBIDDEN, result.getStatus());
        }

        assertEquals(0, dataSource.connectionCalls);
    }

    @Test
    void guardRejectsAllNonV1SqlShapes() {
        SqlGuard guard = SqlGuard.demoOrder();

        sqlCases().forEach(sql -> assertFalse(
                guard.validateSql(sql).allowed(),
                () -> "expected denied SQL: " + sql));
    }

    private static Stream<String> sqlCases() {
        return Stream.of(
                "SELECT * FROM demo_order",
                "SELECT demo_order.* FROM demo_order",
                "SELECT password FROM demo_user",
                "SELECT id FROM auth_user",
                "INSERT INTO demo_order (order_no) VALUES ('o1')",
                "UPDATE demo_order SET status = 'PAID'",
                "DELETE FROM demo_order",
                "CREATE TABLE injected (id INT)",
                "SELECT id FROM demo_order; SELECT id FROM demo_user",
                "SELECT o.id FROM demo_order o JOIN demo_user u ON u.id = o.user_id",
                "SELECT id FROM demo_order WHERE user_id IN "
                        + "(SELECT id FROM demo_user)",
                "WITH selected AS (SELECT id FROM demo_order) "
                        + "SELECT id FROM selected"
        );
    }

    private static ToolGateway gateway(SqlGuard guard) {
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, projectId) -> userId == USER_ID && projectId == PROJECT_ID
                        ? Optional.of(ProjectRole.VIEWER)
                        : Optional.empty());
        ToolRegistry registry = new ToolRegistry(authorization);
        SqlReadTool.register(registry);
        return new ToolGateway(
                new ToolAuth(registry, authorization),
                new ParamValidator(),
                guard,
                new ToolExecutionLimiter(Duration.ofSeconds(2), 10, 1),
                new ResultSanitizer(),
                new ResultLimiter(10_000),
                new Audit(),
                new Metrics()
        );
    }

    private static ToolCallIntent intent(String sql) {
        return new ToolCallIntent(SqlGuard.SQL_READ, Map.of(SqlGuard.SQL_ARGUMENT, sql));
    }

    private static ToolExecutionContext context(String runId) {
        return new ToolExecutionContext(
                USER_ID,
                PROJECT_ID,
                Set.of("TOOL_READ"),
                "test-call",
                runId
        );
    }

    private static final class RecordingDataSource implements DataSource {

        private final Connection connection;
        private int connectionCalls;
        private String sql;
        private int queryTimeoutSeconds;
        private int maxRows;
        private boolean readOnly;

        private RecordingDataSource() {
            connection = proxy(Connection.class, this::connectionCall);
        }

        @Override
        public Connection getConnection() {
            connectionCalls++;
            return connection;
        }

        @Override
        public Connection getConnection(String username, String password) {
            return getConnection();
        }

        @Override
        public PrintWriter getLogWriter() {
            return null;
        }

        @Override
        public void setLogWriter(PrintWriter out) {
        }

        @Override
        public void setLoginTimeout(int seconds) {
        }

        @Override
        public int getLoginTimeout() {
            return 0;
        }

        @Override
        public Logger getParentLogger() {
            return Logger.getGlobal();
        }

        @Override
        public <T> T unwrap(Class<T> iface) throws SQLException {
            throw new SQLException("not a wrapper");
        }

        @Override
        public boolean isWrapperFor(Class<?> iface) {
            return false;
        }

        private Object connectionCall(Object proxy, Method method, Object[] args) {
            return switch (method.getName()) {
                case "setReadOnly" -> {
                    readOnly = (boolean) args[0];
                    yield null;
                }
                case "prepareStatement" -> {
                    sql = (String) args[0];
                    yield proxy(PreparedStatement.class, this::statementCall);
                }
                case "close" -> null;
                case "isClosed" -> false;
                default -> defaultValue(method.getReturnType());
            };
        }

        private Object statementCall(Object proxy, Method method, Object[] args) {
            return switch (method.getName()) {
                case "setQueryTimeout" -> {
                    queryTimeoutSeconds = (int) args[0];
                    yield null;
                }
                case "setMaxRows" -> {
                    maxRows = (int) args[0];
                    yield null;
                }
                case "executeQuery" -> proxy(ResultSet.class, this::resultSetCall);
                case "close" -> null;
                case "isClosed" -> false;
                default -> defaultValue(method.getReturnType());
            };
        }

        private Object resultSetCall(Object proxy, Method method, Object[] args) {
            return switch (method.getName()) {
                case "next" -> Boolean.FALSE;
                case "getMetaData" -> proxy(ResultSetMetaData.class, this::metadataCall);
                case "close" -> null;
                case "isClosed" -> false;
                default -> defaultValue(method.getReturnType());
            };
        }

        private Object metadataCall(Object proxy, Method method, Object[] args) {
            return switch (method.getName()) {
                case "getColumnCount" -> 2;
                case "getColumnLabel", "getColumnName" -> (int) args[0] == 1 ? "id" : "status";
                default -> defaultValue(method.getReturnType());
            };
        }
    }

    @SuppressWarnings("unchecked")
    private static <T> T proxy(Class<T> type, InvocationHandler handler) {
        return (T) Proxy.newProxyInstance(
                type.getClassLoader(),
                new Class<?>[]{type},
                handler
        );
    }

    private static Object defaultValue(Class<?> type) {
        if (!type.isPrimitive()) {
            return null;
        }
        if (type == boolean.class) {
            return false;
        }
        if (type == char.class) {
            return '\0';
        }
        if (type == byte.class) {
            return (byte) 0;
        }
        if (type == short.class) {
            return (short) 0;
        }
        if (type == int.class) {
            return 0;
        }
        if (type == long.class) {
            return 0L;
        }
        if (type == float.class) {
            return 0F;
        }
        return 0D;
    }
}
