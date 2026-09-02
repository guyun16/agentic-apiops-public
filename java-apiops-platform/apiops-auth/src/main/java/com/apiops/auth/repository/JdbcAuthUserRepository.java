package com.apiops.auth.repository;

import com.apiops.auth.security.ApiOpsPrincipal;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Optional;

/**
 * Minimal JDBC adapter for the auth_user table. It only loads the principal;
 * password comparison is performed by DaoAuthenticationProvider.
 */
public final class JdbcAuthUserRepository implements AuthUserRepository {

    private static final String FIND_BY_USERNAME = """
            SELECT id, username, password_hash, status
            FROM auth_user
            WHERE username = ?
            """;

    private final DataSource dataSource;

    public JdbcAuthUserRepository(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    @Override
    public Optional<ApiOpsPrincipal> findByUsername(String username) {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(FIND_BY_USERNAME)) {
            statement.setString(1, username);
            try (ResultSet resultSet = statement.executeQuery()) {
                if (!resultSet.next()) {
                    return Optional.empty();
                }
                return Optional.of(new ApiOpsPrincipal(
                        resultSet.getLong("id"),
                        resultSet.getString("username"),
                        resultSet.getString("password_hash"),
                        "ENABLED".equals(resultSet.getString("status")),
                        null
                ));
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Unable to load authentication user", exception);
        }
    }
}
