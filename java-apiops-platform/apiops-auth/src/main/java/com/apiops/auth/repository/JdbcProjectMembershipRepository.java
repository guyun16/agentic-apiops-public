package com.apiops.auth.repository;

import com.apiops.auth.enums.ProjectRole;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Objects;
import java.util.Optional;

/** JDBC adapter for one project membership lookup. */
public final class JdbcProjectMembershipRepository implements ProjectMembershipRepository {

    private static final String FIND_PROJECT_ROLE = """
            SELECT project_role
            FROM apiops_project_member
            WHERE project_id = ?
              AND user_id = ?
            """;

    private final DataSource dataSource;

    public JdbcProjectMembershipRepository(DataSource dataSource) {
        this.dataSource = Objects.requireNonNull(dataSource, "dataSource must not be null");
    }

    @Override
    public Optional<ProjectRole> findProjectRole(long userId, long projectId) {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(FIND_PROJECT_ROLE)) {
            statement.setLong(1, projectId);
            statement.setLong(2, userId);
            try (ResultSet resultSet = statement.executeQuery()) {
                if (!resultSet.next()) {
                    return Optional.empty();
                }
                return ProjectRole.fromCode(resultSet.getString("project_role"));
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Unable to load project membership", exception);
        }
    }
}
