package com.apiops.web.project.repository;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.web.project.domain.Project;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

import javax.sql.DataSource;
import java.io.InputStream;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.Objects;
import java.util.UUID;
import java.util.logging.Logger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class ProjectRepositoryMySqlIntegrationTest {

    @Test
    void shouldCommitOwnerMembershipAndRollbackProjectWhenMembershipInsertFails()
            throws Exception {
        String url = System.getenv("APIOPS_AUTH_DB_URL");
        Assumptions.assumeTrue(
                url != null,
                "Set APIOPS_AUTH_DB_URL to run MySQL integration"
        );
        Class.forName("com.mysql.cj.jdbc.Driver");

        String username = System.getenv("APIOPS_AUTH_DB_USERNAME");
        String password = System.getenv("APIOPS_AUTH_DB_PASSWORD");
        Assumptions.assumeTrue(username != null && password != null,
                "Set matching MySQL username and password environment variables");

        DataSource dataSource = new DriverManagerDataSource(url, username, password);
        String suffix = UUID.randomUUID().toString().replace("-", "");
        String usernameValue = "project-api-owner-" + suffix;
        String successKey = "project-api-success-" + suffix;
        String rollbackKey = "project-api-rollback-" + suffix;
        String triggerName = "apiops_project_member_fail_" + suffix;

        try (Connection connection = dataSource.getConnection()) {
            assertEquals("apiops_auth", connection.getCatalog());
            executeSchemaScriptTwice(connection);
            long ownerId = insertUser(connection, usernameValue);
            JdbcProjectRepository repository = new JdbcProjectRepository(dataSource);

            Project created = repository.createProjectWithOwner(
                    successKey,
                    "Project API success",
                    ownerId
            );
            assertEquals(ProjectRole.OWNER,
                    findRole(connection, created.id(), ownerId));

            createMembershipFailureTrigger(connection, triggerName);
            assertThrows(IllegalStateException.class,
                    () -> repository.createProjectWithOwner(
                            rollbackKey,
                            "Project API rollback",
                            ownerId
                    ));
            assertEquals(0, countProjects(connection, rollbackKey));
        } finally {
            try (Connection cleanupConnection = dataSource.getConnection()) {
                dropTrigger(cleanupConnection, triggerName);
                deleteProject(cleanupConnection, successKey);
                deleteProject(cleanupConnection, rollbackKey);
                deleteUser(cleanupConnection, usernameValue);
            }
        }
    }

    private static void executeSchemaScriptTwice(Connection connection) throws Exception {
        String script;
        try (InputStream inputStream = Objects.requireNonNull(
                ProjectRepositoryMySqlIntegrationTest.class.getResourceAsStream(
                        "/db/auth-schema.sql"))) {
            script = new String(inputStream.readAllBytes(), StandardCharsets.UTF_8);
        }
        for (int pass = 0; pass < 2; pass++) {
            for (String statementText : script.split(";")) {
                String sql = statementText.trim();
                if (!sql.isEmpty()) {
                    try (Statement statement = connection.createStatement()) {
                        statement.execute(sql);
                    }
                }
            }
        }
    }

    private static long insertUser(Connection connection, String username) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                """
                INSERT INTO auth_user
                    (username, password_hash, status, created_at, updated_at)
                VALUES (?, 'integration-only', 'ENABLED', CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))
                """)) {
            statement.setString(1, username);
            statement.executeUpdate();
        }
        try (PreparedStatement statement = connection.prepareStatement(
                "SELECT id FROM auth_user WHERE username = ?")) {
            statement.setString(1, username);
            try (ResultSet resultSet = statement.executeQuery()) {
                assertTrue(resultSet.next());
                return resultSet.getLong(1);
            }
        }
    }

    private static ProjectRole findRole(Connection connection, long projectId, long userId)
            throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                """
                SELECT project_role
                FROM apiops_project_member
                WHERE project_id = ? AND user_id = ?
                """)) {
            statement.setLong(1, projectId);
            statement.setLong(2, userId);
            try (ResultSet resultSet = statement.executeQuery()) {
                assertTrue(resultSet.next());
                return ProjectRole.valueOf(resultSet.getString(1));
            }
        }
    }

    private static int countProjects(Connection connection, String projectKey)
            throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "SELECT COUNT(*) FROM apiops_project WHERE project_key = ?")) {
            statement.setString(1, projectKey);
            try (ResultSet resultSet = statement.executeQuery()) {
                assertTrue(resultSet.next());
                return resultSet.getInt(1);
            }
        }
    }

    private static void createMembershipFailureTrigger(
            Connection connection,
            String triggerName
    ) throws SQLException {
        String sql = """
                CREATE TRIGGER `%s`
                BEFORE INSERT ON apiops_project_member
                FOR EACH ROW
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'forced membership failure'
                """.formatted(triggerName);
        try (Statement statement = connection.createStatement()) {
            statement.execute(sql);
        }
    }

    private static void dropTrigger(Connection connection, String triggerName) throws SQLException {
        try (Statement statement = connection.createStatement()) {
            statement.execute("DROP TRIGGER IF EXISTS `" + triggerName + "`");
        }
    }

    private static void deleteProject(Connection connection, String projectKey)
            throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "DELETE FROM apiops_project WHERE project_key = ?")) {
            statement.setString(1, projectKey);
            statement.executeUpdate();
        }
    }

    private static void deleteUser(Connection connection, String username) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "DELETE FROM auth_user WHERE username = ?")) {
            statement.setString(1, username);
            statement.executeUpdate();
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
        public <T> T unwrap(Class<T> iface) throws SQLException {
            throw new SQLException("Not a wrapper");
        }

        @Override
        public boolean isWrapperFor(Class<?> iface) {
            return false;
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
    }
}
