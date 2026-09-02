package com.apiops.openapi.repository;

import com.apiops.openapi.domain.ApiDocument;
import com.apiops.openapi.domain.ApiEndpoint;
import com.apiops.openapi.domain.ApiExample;
import com.apiops.openapi.domain.ApiParameter;
import com.apiops.openapi.domain.ApiRequestSchema;
import com.apiops.openapi.domain.ApiResponseSchema;
import org.springframework.jdbc.datasource.TransactionAwareDataSourceProxy;

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

/** Plain JDBC adapter matching the platform's existing persistence style. */
public final class JdbcOpenApiMetadataRepository implements OpenApiMetadataRepository {

    private final DataSource dataSource;

    public JdbcOpenApiMetadataRepository(DataSource dataSource) {
        this.dataSource = new TransactionAwareDataSourceProxy(
                Objects.requireNonNull(dataSource, "dataSource must not be null"));
    }

    @Override
    public ApiDocument save(ApiDocument value) {
        long id = insert("""
                INSERT INTO api_document
                    (api_doc_id, project_id, source_key, document_name, openapi_version,
                     title, api_version, document_format, content_hash, raw_content,
                     version_no, status, created_by, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP(3),
                        CURRENT_TIMESTAMP(3))
                """, statement -> {
            statement.setString(1, value.apiDocId());
            statement.setLong(2, value.projectId());
            statement.setString(3, value.sourceKey());
            statement.setString(4, value.documentName());
            statement.setString(5, value.openapiVersion());
            statement.setString(6, value.title());
            statement.setString(7, value.apiVersion());
            statement.setString(8, value.documentFormat());
            statement.setString(9, value.contentHash());
            statement.setString(10, value.rawContent());
            statement.setInt(11, value.versionNo());
            statement.setString(12, value.status());
            statement.setLong(13, value.createdBy());
        });
        return findOne("SELECT * FROM api_document WHERE id = ?", id, this::document)
                .orElseThrow();
    }

    @Override
    public Optional<ApiDocument> findDocument(long projectId, String apiDocId) {
        return findOne("""
                SELECT * FROM api_document
                WHERE project_id = ? AND api_doc_id = ?
                ORDER BY id DESC LIMIT 1
                """, statement -> {
            statement.setLong(1, projectId);
            statement.setString(2, apiDocId);
        }, this::document);
    }

    @Override
    public Optional<ApiDocument> findDocument(
            long projectId, String sourceKey, String contentHash) {
        return findOne("""
                SELECT * FROM api_document
                WHERE project_id = ? AND source_key = ? AND content_hash = ?
                ORDER BY version_no DESC LIMIT 1
                """, statement -> {
            statement.setLong(1, projectId);
            statement.setString(2, sourceKey);
            statement.setString(3, contentHash);
        }, this::document);
    }

    @Override
    public Optional<ApiDocument> findLatestDocument(long projectId, String sourceKey) {
        return findOne("""
                SELECT * FROM api_document
                WHERE project_id = ? AND source_key = ?
                ORDER BY version_no DESC LIMIT 1
                """, statement -> {
            statement.setLong(1, projectId);
            statement.setString(2, sourceKey);
        }, this::document);
    }

    @Override
    public List<ApiDocument> findDocuments(long projectId) {
        return findMany("""
                SELECT * FROM api_document
                WHERE project_id = ?
                ORDER BY source_key ASC, version_no DESC, api_doc_id ASC
                """, statement -> statement.setLong(1, projectId), this::document);
    }

    @Override
    public ApiEndpoint save(ApiEndpoint value) {
        long id = insert("""
                INSERT INTO api_endpoint
                    (api_id, api_doc_id, project_id, operation_id, http_method, path,
                     summary, description, tags_json, servers_json, security_json,
                     deprecated, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP(3),
                        CURRENT_TIMESTAMP(3))
                """, statement -> {
            statement.setString(1, value.apiId());
            statement.setString(2, value.apiDocId());
            statement.setLong(3, value.projectId());
            statement.setString(4, value.operationId());
            statement.setString(5, value.httpMethod());
            statement.setString(6, value.path());
            statement.setString(7, value.summary());
            statement.setString(8, value.description());
            statement.setString(9, value.tagsJson());
            statement.setString(10, value.serversJson());
            statement.setString(11, value.securityJson());
            statement.setBoolean(12, value.deprecated());
        });
        return findOne("SELECT * FROM api_endpoint WHERE id = ?", id, this::endpoint)
                .orElseThrow();
    }

    @Override
    public Optional<ApiEndpoint> findEndpoint(long projectId, String apiId) {
        return findOne("""
                SELECT * FROM api_endpoint
                WHERE project_id = ? AND api_id = ?
                ORDER BY id DESC LIMIT 1
                """, statement -> {
            statement.setLong(1, projectId);
            statement.setString(2, apiId);
        }, this::endpoint);
    }

    @Override
    public List<ApiEndpoint> findEndpoints(long projectId) {
        return findMany("""
                SELECT * FROM api_endpoint
                WHERE project_id = ? ORDER BY path, http_method, api_id
                """, statement -> statement.setLong(1, projectId), this::endpoint);
    }

    @Override
    public ApiParameter save(ApiParameter value) {
        long id = insert("""
                INSERT INTO api_parameter
                    (api_id, project_id, name, location, required, description,
                     schema_json, example_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP(3))
                """, statement -> {
            statement.setString(1, value.apiId());
            statement.setLong(2, value.projectId());
            statement.setString(3, value.name());
            statement.setString(4, value.location());
            statement.setBoolean(5, value.required());
            statement.setString(6, value.description());
            statement.setString(7, value.schemaJson());
            statement.setString(8, value.exampleJson());
        });
        return findOne("SELECT * FROM api_parameter WHERE id = ?", id, this::parameter)
                .orElseThrow();
    }

    @Override
    public List<ApiParameter> findParameters(long projectId, String apiId) {
        return findMany("""
                SELECT * FROM api_parameter
                WHERE project_id = ? AND api_id = ? ORDER BY id
                """, projectId, apiId, this::parameter);
    }

    @Override
    public ApiRequestSchema save(ApiRequestSchema value) {
        long id = insert("""
                INSERT INTO api_request_schema
                    (api_id, project_id, required, media_type, schema_json, created_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP(3))
                """, statement -> {
            statement.setString(1, value.apiId());
            statement.setLong(2, value.projectId());
            statement.setBoolean(3, value.required());
            statement.setString(4, value.mediaType());
            statement.setString(5, value.schemaJson());
        });
        return findOne("SELECT * FROM api_request_schema WHERE id = ?", id,
                this::requestSchema).orElseThrow();
    }

    @Override
    public List<ApiRequestSchema> findRequestSchemas(long projectId, String apiId) {
        return findMany("""
                SELECT * FROM api_request_schema
                WHERE project_id = ? AND api_id = ? ORDER BY id
                """, projectId, apiId, this::requestSchema);
    }

    @Override
    public ApiResponseSchema save(ApiResponseSchema value) {
        long id = insert("""
                INSERT INTO api_response_schema
                    (api_id, project_id, status_code, description, media_type,
                     schema_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP(3))
                """, statement -> {
            statement.setString(1, value.apiId());
            statement.setLong(2, value.projectId());
            statement.setString(3, value.statusCode());
            statement.setString(4, value.description());
            statement.setString(5, value.mediaType());
            statement.setString(6, value.schemaJson());
        });
        return findOne("SELECT * FROM api_response_schema WHERE id = ?", id,
                this::responseSchema).orElseThrow();
    }

    @Override
    public List<ApiResponseSchema> findResponseSchemas(long projectId, String apiId) {
        return findMany("""
                SELECT * FROM api_response_schema
                WHERE project_id = ? AND api_id = ? ORDER BY id
                """, projectId, apiId, this::responseSchema);
    }

    @Override
    public ApiExample save(ApiExample value) {
        long id = insert("""
                INSERT INTO api_example
                    (api_id, project_id, owner_type, owner_ref_id, example_name,
                     summary, description, value_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP(3))
                """, statement -> {
            statement.setString(1, value.apiId());
            statement.setLong(2, value.projectId());
            statement.setString(3, value.ownerType());
            statement.setLong(4, value.ownerRefId());
            statement.setString(5, value.exampleName());
            statement.setString(6, value.summary());
            statement.setString(7, value.description());
            statement.setString(8, value.valueJson());
        });
        return findOne("SELECT * FROM api_example WHERE id = ?", id, this::example)
                .orElseThrow();
    }

    @Override
    public List<ApiExample> findExamples(long projectId, String apiId) {
        return findMany("""
                SELECT * FROM api_example
                WHERE project_id = ? AND api_id = ? ORDER BY id
                """, projectId, apiId, this::example);
    }

    private ApiDocument document(ResultSet row) throws SQLException {
        return new ApiDocument(row.getLong("id"), row.getString("api_doc_id"),
                row.getLong("project_id"), row.getString("source_key"),
                row.getString("document_name"), row.getString("openapi_version"),
                row.getString("title"), row.getString("api_version"),
                row.getString("document_format"), row.getString("content_hash"),
                row.getString("raw_content"), row.getInt("version_no"),
                row.getString("status"), row.getLong("created_by"),
                instant(row, "created_at"), instant(row, "updated_at"));
    }

    private ApiEndpoint endpoint(ResultSet row) throws SQLException {
        return new ApiEndpoint(row.getLong("id"), row.getString("api_id"),
                row.getString("api_doc_id"), row.getLong("project_id"),
                row.getString("operation_id"), row.getString("http_method"),
                row.getString("path"), row.getString("summary"),
                row.getString("description"), row.getString("tags_json"),
                row.getString("servers_json"), row.getString("security_json"),
                row.getBoolean("deprecated"), instant(row, "created_at"),
                instant(row, "updated_at"));
    }

    private ApiParameter parameter(ResultSet row) throws SQLException {
        return new ApiParameter(row.getLong("id"), row.getString("api_id"),
                row.getLong("project_id"), row.getString("name"),
                row.getString("location"), row.getBoolean("required"),
                row.getString("description"), row.getString("schema_json"),
                row.getString("example_json"), instant(row, "created_at"));
    }

    private ApiRequestSchema requestSchema(ResultSet row) throws SQLException {
        return new ApiRequestSchema(row.getLong("id"), row.getString("api_id"),
                row.getLong("project_id"), row.getBoolean("required"),
                row.getString("media_type"), row.getString("schema_json"),
                instant(row, "created_at"));
    }

    private ApiResponseSchema responseSchema(ResultSet row) throws SQLException {
        return new ApiResponseSchema(row.getLong("id"), row.getString("api_id"),
                row.getLong("project_id"), row.getString("status_code"),
                row.getString("description"), row.getString("media_type"),
                row.getString("schema_json"), instant(row, "created_at"));
    }

    private ApiExample example(ResultSet row) throws SQLException {
        return new ApiExample(row.getLong("id"), row.getString("api_id"),
                row.getLong("project_id"), row.getString("owner_type"),
                row.getLong("owner_ref_id"), row.getString("example_name"),
                row.getString("summary"), row.getString("description"),
                row.getString("value_json"), instant(row, "created_at"));
    }

    private long insert(String sql, Binder binder) {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(
                     sql, Statement.RETURN_GENERATED_KEYS)) {
            binder.bind(statement);
            statement.executeUpdate();
            try (ResultSet keys = statement.getGeneratedKeys()) {
                if (!keys.next()) {
                    throw new SQLException("Metadata insert did not return an id");
                }
                return keys.getLong(1);
            }
        } catch (SQLException exception) {
            throw failure("Unable to save OpenAPI metadata", exception);
        }
    }

    private <T> Optional<T> findOne(String sql, long id, Mapper<T> mapper) {
        return findOne(sql, statement -> statement.setLong(1, id), mapper);
    }

    private <T> Optional<T> findOne(String sql, Binder binder, Mapper<T> mapper) {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            binder.bind(statement);
            try (ResultSet resultSet = statement.executeQuery()) {
                return resultSet.next() ? Optional.of(mapper.map(resultSet)) : Optional.empty();
            }
        } catch (SQLException exception) {
            throw failure("Unable to load OpenAPI metadata", exception);
        }
    }

    private <T> List<T> findMany(
            String sql, long projectId, String apiId, Mapper<T> mapper) {
        return findMany(sql, statement -> {
            statement.setLong(1, projectId);
            statement.setString(2, apiId);
        }, mapper);
    }

    private <T> List<T> findMany(
            String sql, Binder binder, Mapper<T> mapper) {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            binder.bind(statement);
            try (ResultSet resultSet = statement.executeQuery()) {
                List<T> values = new ArrayList<>();
                while (resultSet.next()) {
                    values.add(mapper.map(resultSet));
                }
                return List.copyOf(values);
            }
        } catch (SQLException exception) {
            throw failure("Unable to load OpenAPI metadata", exception);
        }
    }

    private static Instant instant(ResultSet row, String column) throws SQLException {
        Timestamp timestamp = row.getTimestamp(column);
        return timestamp == null ? null : timestamp.toInstant();
    }

    private static IllegalStateException failure(String message, SQLException cause) {
        return new IllegalStateException(message, cause);
    }

    @FunctionalInterface
    private interface Binder {
        void bind(PreparedStatement statement) throws SQLException;
    }

    @FunctionalInterface
    private interface Mapper<T> {
        T map(ResultSet resultSet) throws SQLException;
    }
}
