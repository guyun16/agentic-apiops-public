package com.apiops.auth.repository;

import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

import javax.sql.DataSource;
import java.io.PrintWriter;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Set;
import java.util.UUID;
import java.util.logging.Logger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class GlobalRbacMySqlIntegrationTest {

    @Test
    void shouldQuerySeededGlobalRolesAndDistinctPermissionsThroughMySql() throws Exception {
        String url = System.getenv("APIOPS_AUTH_DB_URL");
        Assumptions.assumeTrue(
                url != null,
                "Set APIOPS_AUTH_DB_URL to run MySQL integration"
        );
        Class.forName("com.mysql.cj.jdbc.Driver");

        String username = System.getenv("APIOPS_AUTH_DB_USERNAME");
        String password = System.getenv("APIOPS_AUTH_DB_PASSWORD");
        assertNotNull(username, "Set APIOPS_AUTH_DB_USERNAME");
        assertNotNull(password, "Set APIOPS_AUTH_DB_PASSWORD");

        DataSource dataSource = new DriverManagerDataSource(url, username, password);
        String suffix = UUID.randomUUID().toString().replace("-", "");
        String adminUsername = "rbac-admin-" + suffix;
        String userUsername = "rbac-user-" + suffix;
        String multiRoleUsername = "rbac-multi-" + suffix;
        String noRoleUsername = "rbac-none-" + suffix;

        try (Connection connection = dataSource.getConnection()) {
            assertEquals("apiops_auth", connection.getCatalog());
            assertRequiredTable(connection, "auth_role");
            assertRequiredTable(connection, "auth_permission");
            assertRequiredTable(connection, "auth_user_role");
            assertRequiredTable(connection, "auth_role_permission");

            long adminUserId = insertUser(connection, adminUsername);
            long userId = insertUser(connection, userUsername);
            long multiRoleUserId = insertUser(connection, multiRoleUsername);
            long noRoleUserId = insertUser(connection, noRoleUsername);
            long adminRoleId = findId(connection, "auth_role", "role_code", "PLATFORM_ADMIN");
            long userRoleId = findId(connection, "auth_role", "role_code", "PLATFORM_USER");

            insertUserRole(connection, adminUserId, adminRoleId);
            insertUserRole(connection, userId, userRoleId);
            insertUserRole(connection, multiRoleUserId, adminRoleId);
            insertUserRole(connection, multiRoleUserId, userRoleId);

            GlobalRbacRepository repository = new JdbcGlobalRbacRepository(dataSource);

            assertEquals(Set.of("PLATFORM_ADMIN"),
                    repository.findRoleCodesByUserId(adminUserId));
            assertEquals(Set.of("PLATFORM_USER"),
                    repository.findRoleCodesByUserId(userId));
            assertEquals(Set.of("PLATFORM_ADMIN", "PLATFORM_USER"),
                    repository.findRoleCodesByUserId(multiRoleUserId));
            assertEquals(Set.of(), repository.findRoleCodesByUserId(noRoleUserId));

            assertEquals(Set.of("PLATFORM_PROJECT_CREATE", "PLATFORM_PROJECT_LIST"),
                    repository.findPermissionCodesByUserId(adminUserId));
            assertEquals(Set.of("PLATFORM_PROJECT_LIST"),
                    repository.findPermissionCodesByUserId(userId));
            assertEquals(Set.of("PLATFORM_PROJECT_CREATE", "PLATFORM_PROJECT_LIST"),
                    repository.findPermissionCodesByUserId(multiRoleUserId));
            assertEquals(Set.of(), repository.findPermissionCodesByUserId(noRoleUserId));

            long listPermissionId = findId(
                    connection,
                    "auth_permission",
                    "permission_code",
                    "PLATFORM_PROJECT_LIST"
            );
            assertThrows(SQLException.class,
                    () -> insertUserRole(connection, adminUserId, adminRoleId));
            assertThrows(SQLException.class,
                    () -> insertRolePermission(connection, userRoleId, listPermissionId));
        } finally {
            try (Connection cleanupConnection = dataSource.getConnection();
                 PreparedStatement statement = cleanupConnection.prepareStatement(
                         "DELETE FROM auth_user WHERE username IN (?, ?, ?, ?)")) {
                statement.setString(1, adminUsername);
                statement.setString(2, userUsername);
                statement.setString(3, multiRoleUsername);
                statement.setString(4, noRoleUsername);
                statement.executeUpdate();
            }
        }
    }

    private static void assertRequiredTable(Connection connection, String tableName)
            throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                "SHOW TABLES LIKE ?")) {
            statement.setString(1, tableName);
            try (ResultSet resultSet = statement.executeQuery()) {
                assertTrue(resultSet.next(),
                        "" + tableName + " table is missing; execute auth-schema.sql and auth-seed.sql");
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

    private static void insertUserRole(Connection connection, long userId, long roleId)
            throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                """
                INSERT INTO auth_user_role
                    (user_id, role_id, created_at, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))
                """)) {
            statement.setLong(1, userId);
            statement.setLong(2, roleId);
            statement.executeUpdate();
        }
    }

    private static void insertRolePermission(
            Connection connection,
            long roleId,
            long permissionId
    ) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                """
                INSERT INTO auth_role_permission
                    (role_id, permission_id, created_at, updated_at)
                VALUES (?, ?, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))
                """)) {
            statement.setLong(1, roleId);
            statement.setLong(2, permissionId);
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
