package com.apiops.auth.repository;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;
import org.springframework.security.access.AccessDeniedException;

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

class ProjectSpaceMySqlIntegrationTest {

    @Test
    void shouldPersistAndAuthorizeProjectMembershipsThroughMySql() throws Exception {
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
        String ownerUsername = "project-owner-" + suffix;
        String editorUsername = "project-editor-" + suffix;
        String viewerUsername = "project-viewer-" + suffix;
        String projectOneKey = "project-one-" + suffix;
        String projectTwoKey = "project-two-" + suffix;

        try (Connection connection = dataSource.getConnection()) {
            assertEquals("apiops_auth", connection.getCatalog());
            executeSchemaScriptTwice(connection);
            assertRequiredTable(connection, "apiops_project");
            assertRequiredTable(connection, "apiops_project_member");

            long ownerId = insertUser(connection, ownerUsername);
            long editorId = insertUser(connection, editorUsername);
            long viewerId = insertUser(connection, viewerUsername);
            long projectOneId = insertProject(connection, projectOneKey, ownerId);
            long projectTwoId = insertProject(connection, projectTwoKey, ownerId);

            insertMembership(connection, projectOneId, ownerId, ProjectRole.OWNER);
            insertMembership(connection, projectOneId, editorId, ProjectRole.EDITOR);
            insertMembership(connection, projectOneId, viewerId, ProjectRole.VIEWER);
            insertMembership(connection, projectTwoId, ownerId, ProjectRole.VIEWER);

            ProjectMembershipRepository repository =
                    new JdbcProjectMembershipRepository(dataSource);
            ProjectAuthorizationService authorizationService =
                    new ProjectAuthorizationService(repository);

            assertEquals(ProjectRole.OWNER,
                    repository.findProjectRole(ownerId, projectOneId).orElseThrow());
            assertEquals(ProjectRole.VIEWER,
                    repository.findProjectRole(ownerId, projectTwoId).orElseThrow());
            assertEquals(ProjectRole.EDITOR,
                    repository.findProjectRole(editorId, projectOneId).orElseThrow());

            assertThrows(SQLException.class,
                    () -> insertMembership(connection, projectOneId, editorId, ProjectRole.EDITOR));

            deleteMembership(connection, projectOneId, viewerId);
            assertTrue(repository.findProjectRole(viewerId, projectOneId).isEmpty());
            assertThrows(AccessDeniedException.class,
                    () -> authorizationService.requireProjectReadable(viewerId, projectOneId));
        } finally {
            try (Connection cleanupConnection = dataSource.getConnection()) {
                deleteProject(cleanupConnection, projectOneKey);
                deleteProject(cleanupConnection, projectTwoKey);
                deleteUser(cleanupConnection, ownerUsername);
                deleteUser(cleanupConnection, editorUsername);
                deleteUser(cleanupConnection, viewerUsername);
            }
        }
    }

    private static void executeSchemaScriptTwice(Connection connection) throws Exception {
        String script;
        try (InputStream inputStream = Objects.requireNonNull(
                ProjectSpaceMySqlIntegrationTest.class.getResourceAsStream("/db/auth-schema.sql"))) {
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

    private static void assertRequiredTable(Connection connection, String tableName)
            throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement("SHOW TABLES LIKE ?")) {
            statement.setString(1, tableName);
            try (ResultSet resultSet = statement.executeQuery()) {
                assertTrue(resultSet.next(),
                        tableName + " table is missing; execute auth-schema.sql first");
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
        return findId(connection, "auth_user", "username", username);
    }

    private static long insertProject(Connection connection, String projectKey, long ownerId)
            throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                """
                INSERT INTO apiops_project
                    (project_key, project_name, owner_user_id, status, created_at, updated_at)
                VALUES (?, ?, ?, 'ACTIVE', CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))
                """)) {
            statement.setString(1, projectKey);
            statement.setString(2, "Integration project " + projectKey);
            statement.setLong(3, ownerId);
            statement.executeUpdate();
        }
        return findId(connection, "apiops_project", "project_key", projectKey);
    }

    private static void insertMembership(
            Connection connection,
            long projectId,
            long userId,
            ProjectRole projectRole
    ) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                """
                INSERT INTO apiops_project_member
                    (project_id, user_id, project_role, joined_at, updated_at)
                VALUES (?, ?, ?, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))
                """)) {
            statement.setLong(1, projectId);
            statement.setLong(2, userId);
            statement.setString(3, projectRole.name());
            statement.executeUpdate();
        }
    }

    private static void deleteMembership(Connection connection, long projectId, long userId)
            throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "DELETE FROM apiops_project_member WHERE project_id = ? AND user_id = ?")) {
            statement.setLong(1, projectId);
            statement.setLong(2, userId);
            statement.executeUpdate();
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

    private static long findId(
            Connection connection,
            String tableName,
            String columnName,
            String value
    ) throws SQLException {
        String sql = "SELECT id FROM " + tableName + " WHERE " + columnName + " = ?";
        try (PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setString(1, value);
            try (ResultSet resultSet = statement.executeQuery()) {
                assertTrue(resultSet.next(), "Missing " + tableName + " row for " + value);
                return resultSet.getLong(1);
            }
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
