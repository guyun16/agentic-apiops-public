package com.apiops.rag.repository;

import com.apiops.rag.retrieval.RagQueryRecord;
import com.apiops.rag.retrieval.RagQueryStatus;
import com.apiops.rag.retrieval.RagResultReference;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.util.List;
import java.util.Objects;
import java.util.Optional;

/** Plain JDBC persistence for project-scoped retrieval facts. */
public final class JdbcRagQueryRecordRepository implements RagQueryRecordRepository {

    private static final TypeReference<List<RagResultReference>> REFERENCES_TYPE =
            new TypeReference<>() { };

    private final DataSource dataSource;
    private final ObjectMapper objectMapper;

    public JdbcRagQueryRecordRepository(DataSource dataSource, ObjectMapper objectMapper) {
        this.dataSource = Objects.requireNonNull(dataSource, "dataSource must not be null");
        this.objectMapper = Objects.requireNonNull(
                objectMapper, "objectMapper must not be null");
    }

    @Override
    public void save(RagQueryRecord value) {
        Objects.requireNonNull(value, "record must not be null");
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement("""
                     INSERT INTO rag_query_record
                         (rag_query_id, project_id, query_text, top_k, retrieved_count,
                          result_references_json, status, started_at, finished_at, duration_ms)
                     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                     """)) {
            statement.setString(1, value.ragQueryId());
            statement.setLong(2, value.projectId());
            statement.setString(3, value.queryText());
            statement.setInt(4, value.topK());
            statement.setInt(5, value.retrievedCount());
            statement.setString(6, writeReferences(value.resultReferences()));
            statement.setString(7, value.status().name());
            statement.setTimestamp(8, Timestamp.from(value.startedAt()));
            statement.setTimestamp(9, Timestamp.from(value.finishedAt()));
            statement.setLong(10, value.durationMs());
            statement.executeUpdate();
        } catch (SQLException exception) {
            throw new IllegalStateException("Unable to save RAG query record", exception);
        }
    }

    @Override
    public Optional<RagQueryRecord> findById(long projectId, String ragQueryId) {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement("""
                     SELECT * FROM rag_query_record
                     WHERE project_id = ? AND rag_query_id = ?
                     """)) {
            statement.setLong(1, projectId);
            statement.setString(2, ragQueryId);
            try (ResultSet rows = statement.executeQuery()) {
                return rows.next() ? Optional.of(record(rows)) : Optional.empty();
            }
        } catch (SQLException exception) {
            throw new IllegalStateException("Unable to load RAG query record", exception);
        }
    }

    private RagQueryRecord record(ResultSet row) throws SQLException {
        return new RagQueryRecord(
                row.getString("rag_query_id"), row.getLong("project_id"),
                row.getString("query_text"), row.getInt("top_k"),
                row.getInt("retrieved_count"),
                readReferences(row.getString("result_references_json")),
                RagQueryStatus.valueOf(row.getString("status")),
                row.getTimestamp("started_at").toInstant(),
                row.getTimestamp("finished_at").toInstant(),
                row.getLong("duration_ms"));
    }

    private String writeReferences(List<RagResultReference> references) {
        try {
            return objectMapper.writeValueAsString(references);
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException(
                    "RAG query result references cannot be serialized", exception);
        }
    }

    private List<RagResultReference> readReferences(String references) {
        try {
            return objectMapper.readValue(references, REFERENCES_TYPE);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException(
                    "Stored RAG query result references are invalid", exception);
        }
    }
}
