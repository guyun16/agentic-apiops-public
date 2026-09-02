package com.apiops.auth.repository;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.LinkedHashSet;
import java.util.Set;

/** JDBC adapter for global RBAC reads. */
public final class JdbcGlobalRbacRepository implements GlobalRbacRepository {

    private static final String FIND_ROLE_CODES_BY_USER_ID = """
            SELECT DISTINCT r.role_code
            FROM auth_user_role ur
            JOIN auth_role r ON r.id = ur.role_id
            WHERE ur.user_id = ?
            ORDER BY r.role_code
            """;

    private static final String FIND_PERMISSION_CODES_BY_USER_ID = """
            SELECT DISTINCT p.permission_code
            FROM auth_user_role ur
            JOIN auth_role r ON r.id = ur.role_id
            JOIN auth_role_permission rp ON rp.role_id = r.id
            JOIN auth_permission p ON p.id = rp.permission_id
            WHERE ur.user_id = ?
            ORDER BY p.permission_code
            """;

    private final DataSource dataSource;

    public JdbcGlobalRbacRepository(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @Override
    public Set<String> findRoleCodesByUserId(long userId) {
        return queryCodes(FIND_ROLE_CODES_BY_USER_ID, userId, "global roles");
    }

    @Override
    public Set<String> findPermissionCodesByUserId(long userId) {
        return queryCodes(FIND_PERMISSION_CODES_BY_USER_ID, userId, "global permissions");
    }

    private Set<String> queryCodes(String sql, long userId, String resourceName) {
        Set<String> codes = new LinkedHashSet<>();
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            statement.setLong(1, userId);
            try (ResultSet resultSet = statement.executeQuery()) {
                while (resultSet.next()) {
                    codes.add(resultSet.getString(1));
                }
            }
            return Set.copyOf(codes);
        } catch (SQLException exception) {
            throw new IllegalStateException("Unable to load " + resourceName, exception);
        }
    }
}
