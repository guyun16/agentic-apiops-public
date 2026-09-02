package com.apiops.web.project.repository;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.web.project.domain.AccessibleProject;
import com.apiops.web.project.domain.Project;
import com.apiops.web.project.domain.ProjectMember;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Optional;

/** JDBC persistence adapter for the Day 8 project API. */
public final class JdbcProjectRepository implements ProjectRepository {

    private static final String INSERT_PROJECT = """
            INSERT INTO apiops_project
                (project_key, project_name, owner_user_id, status, created_at, updated_at)
            VALUES (?, ?, ?, 'ACTIVE', CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))
            """;

    private static final String INSERT_MEMBER = """
            INSERT INTO apiops_project_member
                (project_id, user_id, project_role, joined_at, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))
            """;

    private static final String FIND_PROJECT = """
            SELECT id, project_key, project_name, owner_user_id, status, created_at, updated_at
            FROM apiops_project
            WHERE id = ?
            """;

    private static final String FIND_ACCESSIBLE_PROJECTS = """
            SELECT p.id, p.project_name, m.project_role
            FROM apiops_project p
            INNER JOIN apiops_project_member m ON m.project_id = p.id
            WHERE m.user_id = ?
            ORDER BY p.id
            """;

    private static final String UPDATE_PROJECT_NAME = """
            UPDATE apiops_project
            SET project_name = ?, updated_at = CURRENT_TIMESTAMP(3)
            WHERE id = ?
            """;

    private static final String INSERT_MEMBER_RETURNING = """
            INSERT INTO apiops_project_member
                (project_id, user_id, project_role, joined_at, updated_at)
            VALUES (?, ?, ?, CURRENT_TIMESTAMP(3), CURRENT_TIMESTAMP(3))
            """;

    private static final String FIND_MEMBER = """
            SELECT project_id, user_id, project_role, joined_at
            FROM apiops_project_member
            WHERE project_id = ?
              AND user_id = ?
            """;

    private final DataSource dataSource;

    public JdbcProjectRepository(DataSource dataSource) {
        this.dataSource = Objects.requireNonNull(dataSource, "dataSource must not be null");
    }

    @Override
    public Project createProjectWithOwner(
            String projectKey,
            String projectName,
            long ownerUserId
    ) {
        try (Connection connection = dataSource.getConnection()) {
            boolean originalAutoCommit = connection.getAutoCommit();
            connection.setAutoCommit(false);
            try {
                long projectId = insertProject(connection, projectKey, projectName, ownerUserId);
                insertMember(connection, projectId, ownerUserId, ProjectRole.OWNER);
                Project project = findById(connection, projectId)
                        .orElseThrow(() -> new SQLException("Created project could not be reloaded"));
                connection.commit();
                return project;
            } catch (SQLException exception) {
                rollback(connection, exception);
                throw persistenceFailure("Unable to create project", exception);
            } finally {
                restoreAutoCommit(connection, originalAutoCommit);
            }
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to create project", exception);
        }
    }

    @Override
    public Optional<Project> findById(long projectId) {
        try (Connection connection = dataSource.getConnection()) {
            return findById(connection, projectId);
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to load project", exception);
        }
    }

    @Override
    public List<AccessibleProject> findAccessibleProjectsByUserId(long userId) {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(FIND_ACCESSIBLE_PROJECTS)) {
            statement.setLong(1, userId);
            try (ResultSet resultSet = statement.executeQuery()) {
                List<AccessibleProject> projects = new ArrayList<>();
                while (resultSet.next()) {
                    projects.add(new AccessibleProject(
                            resultSet.getLong("id"),
                            resultSet.getString("project_name"),
                            ProjectRole.valueOf(resultSet.getString("project_role"))
                    ));
                }
                return projects;
            }
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to list accessible projects", exception);
        }
    }

    @Override
    public Optional<Project> updateProjectName(long projectId, String projectName) {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(UPDATE_PROJECT_NAME)) {
            statement.setString(1, projectName);
            statement.setLong(2, projectId);
            if (statement.executeUpdate() == 0) {
                return Optional.empty();
            }
            return findById(connection, projectId);
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to update project", exception);
        }
    }

    @Override
    public ProjectMember addMember(
            long projectId,
            long userId,
            ProjectRole projectRole
    ) {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(INSERT_MEMBER_RETURNING)) {
            statement.setLong(1, projectId);
            statement.setLong(2, userId);
            statement.setString(3, projectRole.name());
            statement.executeUpdate();
            return findMember(connection, projectId, userId)
                    .orElseThrow(() -> new SQLException("Created membership could not be reloaded"));
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to add project member", exception);
        }
    }

    private long insertProject(
            Connection connection,
            String projectKey,
            String projectName,
            long ownerUserId
    ) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(
                INSERT_PROJECT,
                Statement.RETURN_GENERATED_KEYS
        )) {
            statement.setString(1, projectKey);
            statement.setString(2, projectName);
            statement.setLong(3, ownerUserId);
            statement.executeUpdate();
            try (ResultSet keys = statement.getGeneratedKeys()) {
                if (!keys.next()) {
                    throw new SQLException("Project insert did not return an id");
                }
                return keys.getLong(1);
            }
        }
    }

    private void insertMember(
            Connection connection,
            long projectId,
            long userId,
            ProjectRole projectRole
    ) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(INSERT_MEMBER)) {
            statement.setLong(1, projectId);
            statement.setLong(2, userId);
            statement.setString(3, projectRole.name());
            statement.executeUpdate();
        }
    }

    private Optional<Project> findById(Connection connection, long projectId) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(FIND_PROJECT)) {
            statement.setLong(1, projectId);
            try (ResultSet resultSet = statement.executeQuery()) {
                if (!resultSet.next()) {
                    return Optional.empty();
                }
                return Optional.of(toProject(resultSet));
            }
        }
    }

    private Optional<ProjectMember> findMember(
            Connection connection,
            long projectId,
            long userId
    ) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement(FIND_MEMBER)) {
            statement.setLong(1, projectId);
            statement.setLong(2, userId);
            try (ResultSet resultSet = statement.executeQuery()) {
                if (!resultSet.next()) {
                    return Optional.empty();
                }
                return Optional.of(new ProjectMember(
                        resultSet.getLong("project_id"),
                        resultSet.getLong("user_id"),
                        ProjectRole.valueOf(resultSet.getString("project_role")),
                        toInstant(resultSet.getTimestamp("joined_at"))
                ));
            }
        }
    }

    private static Project toProject(ResultSet resultSet) throws SQLException {
        return new Project(
                resultSet.getLong("id"),
                resultSet.getString("project_key"),
                resultSet.getString("project_name"),
                resultSet.getLong("owner_user_id"),
                resultSet.getString("status"),
                toInstant(resultSet.getTimestamp("created_at")),
                toInstant(resultSet.getTimestamp("updated_at"))
        );
    }

    private static Instant toInstant(Timestamp timestamp) {
        return timestamp == null ? null : timestamp.toInstant();
    }

    private static void rollback(Connection connection, SQLException original) {
        try {
            connection.rollback();
        } catch (SQLException rollbackException) {
            original.addSuppressed(rollbackException);
        }
    }

    private static void restoreAutoCommit(Connection connection, boolean originalAutoCommit) {
        try {
            connection.setAutoCommit(originalAutoCommit);
        } catch (SQLException exception) {
            throw persistenceFailure("Unable to restore project transaction state", exception);
        }
    }

    private static IllegalStateException persistenceFailure(String message, SQLException cause) {
        return new IllegalStateException(message, cause);
    }
}
