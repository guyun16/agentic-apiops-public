package com.apiops.tool.gateway;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.common.enums.ToolStatus;
import com.apiops.common.tool.ToolResult;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import javax.sql.DataSource;
import java.io.PrintWriter;
import java.sql.*;
import java.time.Duration;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.logging.Logger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * Opt-in real-JDBC evidence for the demo-order database.
 *
 * <p>The test owns an ephemeral MySQL instance, creates a dedicated SELECT-only
 * account, and injects the container's mapped JDBC endpoint at runtime. It
 * therefore proves both the real MySQL behavior and the gateway's use of a
 * restricted account without relying on a developer's local database.</p>
 */
@Testcontainers(disabledWithoutDocker = true)
class SqlReadMySqlIntegrationTest {

    private static final long USER_ID = 1L;
    private static final long PROJECT_ID = 1L;
    private static final String DATABASE = "apiops_demo_order";
    private static final String ROOT_USERNAME = "root";
    private static final String ROOT_PASSWORD = "root-test-password";
    private static final String READONLY_USERNAME = "apiops_tool_readonly";
    private static final String READONLY_PASSWORD = "readonly-test-password";

    @Container
    private static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4")
            .withDatabaseName(DATABASE)
            .withUsername(ROOT_USERNAME)
            .withPassword(ROOT_PASSWORD);

    @BeforeAll
    static void initializeSchemaAndReadOnlyAccount() throws SQLException {
        try (Connection connection = DriverManager.getConnection(
                MYSQL.getJdbcUrl(), ROOT_USERNAME, ROOT_PASSWORD);
             Statement statement = connection.createStatement()) {
            statement.execute("""
                    CREATE TABLE demo_user (
                        id BIGINT NOT NULL AUTO_INCREMENT,
                        user_no VARCHAR(64) NOT NULL,
                        user_name VARCHAR(128) NOT NULL,
                        password VARCHAR(255) NOT NULL,
                        status VARCHAR(32) NOT NULL,
                        created_at TIMESTAMP(3) NOT NULL,
                        updated_at TIMESTAMP(3) NOT NULL,
                        PRIMARY KEY (id)
                    )
                    """);
            statement.execute("CREATE USER '" + READONLY_USERNAME
                    + "'@'%' IDENTIFIED BY '" + READONLY_PASSWORD + "'");
            statement.execute("GRANT SELECT ON `" + DATABASE + "`.* TO '"
                    + READONLY_USERNAME + "'@'%'");
        }

        try (Connection connection = DriverManager.getConnection(
                MYSQL.getJdbcUrl(), ROOT_USERNAME, ROOT_PASSWORD);
             PreparedStatement statement = connection.prepareStatement("""
                     INSERT INTO demo_user (
                         user_no, user_name, password, status, created_at, updated_at
                     ) VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))
                     """)) {
            for (int index = 1; index <= 120; index++) {
                statement.setString(1, "user-" + index);
                statement.setString(2, "Demo User " + index);
                statement.setString(3, "not-returned-" + index);
                statement.setString(4, "ENABLED");
                statement.addBatch();
            }
            statement.executeBatch();
        }
    }

    @Test
    void configuredAccountCanSelectOnlyFromDemoOrderDatabase() throws SQLException {
        try (Connection connection = configuredDataSource().getConnection()) {
            try (Statement statement = connection.createStatement();
                 ResultSet resultSet = statement.executeQuery(
                         "SELECT DATABASE(), CURRENT_USER()")) {
                assertTrue(resultSet.next());
                assertEquals(DATABASE, resultSet.getString(1));
                assertTrue(resultSet.getString(2).startsWith(configuredUsername() + "@"));
            }

            String grants = readGrants(connection).toUpperCase(Locale.ROOT);
            assertTrue(grants.contains("SELECT"), grants);
            for (String forbiddenPrivilege : List.of(
                    "ALL PRIVILEGES", "INSERT", "UPDATE", "DELETE", "CREATE",
                    "ALTER", "DROP", "TRIGGER", "EVENT", "GRANT OPTION")) {
                assertFalse(grants.contains(forbiddenPrivilege),
                        () -> "read-only account has forbidden privilege: "
                                + forbiddenPrivilege + " in " + grants);
            }
        }
    }

    @Test
    void writeAndDdlStatementsAreRejectedByTheConfiguredAccount() throws SQLException {
        assertStatementDenied("""
                INSERT INTO demo_user (
                    user_no, user_name, status, created_at, updated_at
                )
                SELECT 'tool_gateway_probe_never_inserted', 'probe', 'ENABLED',
                       CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3)
                WHERE 1 = 0
                """);
        assertStatementDenied("UPDATE demo_user SET status = status WHERE id = -1");
        assertStatementDenied("DELETE FROM demo_user WHERE id = -1");
        assertStatementDenied("CREATE TEMPORARY TABLE tool_gateway_privilege_probe (id INT)");
    }

    @Test
    void allowedSqlRunsThroughGatewayAndReturnsRealRows() throws SQLException {
        SqlGuard guard = SqlGuard.demoOrder();
        try (ToolGateway gateway = gateway(guard)) {
            SqlReadExecutor executor = new SqlReadExecutor(
                    configuredDataSource(), guard, Duration.ofSeconds(2));
            ToolResult<Object> result = SqlReadTool.execute(
                    gateway,
                    executor,
                    context("mysql-allowed"),
                    intent("SELECT id, user_no, status FROM demo_user LIMIT 1"));

            List<?> rows = successfulRows(result);
            assertFalse(rows.isEmpty(), "demo-order seed data is required");
            assertTrue(rows.size() <= SqlGuard.MAX_ROWS);
        }
    }

    @Test
    void deniedSqlStopsAtGuardWithoutOpeningRealJdbcConnection() throws SQLException {
        SqlGuard guard = SqlGuard.demoOrder();
        CountingDataSource dataSource = new CountingDataSource(configuredDataSource());
        SqlReadExecutor executor = new SqlReadExecutor(
                dataSource, guard, Duration.ofSeconds(2));

        try (ToolGateway gateway = gateway(guard)) {
            ToolResult<Object> result = SqlReadTool.execute(
                    gateway,
                    executor,
                    context("mysql-denied"),
                    intent("SELECT password FROM demo_user"));

            assertEquals(ToolStatus.FORBIDDEN, result.getStatus());
        }

        assertEquals(0, dataSource.connectionCalls());
    }

    @Test
    void missingAndOversizedLimitReturnAtMostOneHundredRealRows() throws SQLException {
        SqlGuard guard = SqlGuard.demoOrder();
        try (ToolGateway gateway = gateway(guard)) {
            SqlReadExecutor executor = new SqlReadExecutor(
                    configuredDataSource(), guard, Duration.ofSeconds(2));
            for (String sql : List.of(
                    "SELECT id, user_no, status FROM demo_user",
                    "SELECT id, user_no, status FROM demo_user LIMIT 1000000")) {
                List<?> rows = successfulRows(SqlReadTool.execute(
                        gateway, executor, context("mysql-limit"), intent(sql)));
                assertTrue(rows.size() <= SqlGuard.MAX_ROWS, sql);
            }
        }
    }

    private static String readGrants(Connection connection) throws SQLException {
        StringBuilder grants = new StringBuilder();
        try (Statement statement = connection.createStatement();
             ResultSet resultSet = statement.executeQuery("SHOW GRANTS")) {
            while (resultSet.next()) {
                if (grants.length() > 0) {
                    grants.append('\n');
                }
                grants.append(resultSet.getString(1));
            }
        }
        return grants.toString();
    }

    private static void assertStatementDenied(String sql) throws SQLException {
        try (Connection connection = configuredDataSource().getConnection();
             Statement statement = connection.createStatement()) {
            assertThrows(SQLException.class, () -> statement.execute(sql), sql);
        }
    }

    private static List<?> successfulRows(ToolResult<Object> result) {
        assertNotNull(result);
        assertEquals(ToolStatus.SUCCESS, result.getStatus());
        assertTrue(result.getData() instanceof List<?>);
        return (List<?>) result.getData();
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
                new ToolExecutionLimiter(Duration.ofSeconds(5), 10, 1),
                new ResultSanitizer(),
                new ResultLimiter(10_000),
                new Audit(),
                new Metrics()
        );
    }

    private static ToolExecutionContext context(String runId) {
        return new ToolExecutionContext(
                USER_ID,
                PROJECT_ID,
                Set.of("TOOL_READ"),
                "integration-test-call",
                runId
        );
    }

    private static ToolCallIntent intent(String sql) {
        return new ToolCallIntent(SqlGuard.SQL_READ, Map.of(SqlGuard.SQL_ARGUMENT, sql));
    }

    private static DataSource configuredDataSource() {
        return new DriverManagerDataSource(
                MYSQL.getJdbcUrl(), READONLY_USERNAME, READONLY_PASSWORD);
    }

    private static String configuredUsername() {
        return READONLY_USERNAME;
    }

    private static final class CountingDataSource implements DataSource {

        private final DataSource delegate;
        private final AtomicInteger connectionCalls = new AtomicInteger();

        private CountingDataSource(DataSource delegate) {
            this.delegate = delegate;
        }

        private int connectionCalls() {
            return connectionCalls.get();
        }

        @Override
        public Connection getConnection() throws SQLException {
            connectionCalls.incrementAndGet();
            return delegate.getConnection();
        }

        @Override
        public Connection getConnection(String username, String password) throws SQLException {
            connectionCalls.incrementAndGet();
            return delegate.getConnection(username, password);
        }

        @Override
        public PrintWriter getLogWriter() throws SQLException {
            return delegate.getLogWriter();
        }

        @Override
        public void setLogWriter(PrintWriter out) throws SQLException {
            delegate.setLogWriter(out);
        }

        @Override
        public void setLoginTimeout(int seconds) throws SQLException {
            delegate.setLoginTimeout(seconds);
        }

        @Override
        public int getLoginTimeout() throws SQLException {
            return delegate.getLoginTimeout();
        }

        @Override
        public Logger getParentLogger() {
            return Logger.getLogger(Logger.GLOBAL_LOGGER_NAME);
        }

        @Override
        public <T> T unwrap(Class<T> iface) throws SQLException {
            return delegate.unwrap(iface);
        }

        @Override
        public boolean isWrapperFor(Class<?> iface) throws SQLException {
            return delegate.isWrapperFor(iface);
        }
    }

    private static final class DriverManagerDataSource implements DataSource {

        private final String url;
        private final String username;
        private final String password;

        private DriverManagerDataSource(String url, String username, String password) {
            this.url = url;
            this.username = username;
            this.password = password;
        }

        @Override
        public Connection getConnection() throws SQLException {
            return DriverManager.getConnection(url, username, password);
        }

        @Override
        public Connection getConnection(String username, String password) throws SQLException {
            return DriverManager.getConnection(url, username, password);
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
            return Logger.getLogger(Logger.GLOBAL_LOGGER_NAME);
        }

        @Override
        public <T> T unwrap(Class<T> iface) throws SQLException {
            if (iface.isInstance(this)) {
                return iface.cast(this);
            }
            throw new SQLException("not a wrapper for " + iface.getName());
        }

        @Override
        public boolean isWrapperFor(Class<?> iface) {
            return iface.isInstance(this);
        }
    }
}
