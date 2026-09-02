package com.apiops.rag.repository;

import com.apiops.rag.domain.Document;
import com.apiops.rag.domain.DocumentChunk;
import com.apiops.rag.domain.DocumentStatus;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;

/** Plain JDBC adapter matching the platform's module-owned MySQL persistence style. */
public final class JdbcDocumentRepository implements DocumentRepository {

    private static final TypeReference<Map<String, String>> METADATA_TYPE =
            new TypeReference<>() { };

    private final DataSource dataSource;
    private final ObjectMapper objectMapper;

    public JdbcDocumentRepository(DataSource dataSource, ObjectMapper objectMapper) {
        this.dataSource = Objects.requireNonNull(dataSource, "dataSource must not be null");
        this.objectMapper = Objects.requireNonNull(objectMapper, "objectMapper must not be null");
    }

    @Override
    public Optional<Document> findBySourceKey(long projectId, String sourceKey) {
        return findDocument("""
                SELECT * FROM rag_document
                WHERE project_id = ? AND source_key = ?
                """, statement -> {
            statement.setLong(1, projectId);
            statement.setString(2, sourceKey);
        });
    }

    @Override
    public Optional<Document> findById(long projectId, String documentId) {
        return findDocument("""
                SELECT * FROM rag_document
                WHERE project_id = ? AND document_id = ?
                """, statement -> {
            statement.setLong(1, projectId);
            statement.setString(2, documentId);
        });
    }

    @Override
    public List<DocumentChunk> findChunks(long projectId, String documentId) {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement("""
                     SELECT * FROM rag_document_chunk
                     WHERE project_id = ? AND document_id = ?
                     ORDER BY ordinal
                     """)) {
            statement.setLong(1, projectId);
            statement.setString(2, documentId);
            try (ResultSet rows = statement.executeQuery()) {
                List<DocumentChunk> values = new ArrayList<>();
                while (rows.next()) {
                    values.add(chunk(rows));
                }
                return List.copyOf(values);
            }
        } catch (SQLException exception) {
            throw failure("Unable to load document chunks", exception);
        }
    }

    @Override
    public void saveKnowledge(Document document, List<DocumentChunk> chunks) {
        Objects.requireNonNull(document, "document must not be null");
        List<DocumentChunk> values = List.copyOf(
                Objects.requireNonNull(chunks, "chunks must not be null"));
        for (DocumentChunk chunk : values) {
            if (chunk.projectId() != document.projectId()
                    || !chunk.documentId().equals(document.documentId())) {
                throw new IllegalArgumentException(
                        "Chunk does not belong to the project document");
            }
        }

        inTransaction(connection -> {
            upsertDocument(connection, document);
            deleteChunks(connection, document.projectId(), document.documentId());
            for (DocumentChunk chunk : values) {
                insertChunk(connection, chunk);
            }
        }, "Unable to save document knowledge");
    }

    @Override
    public void updateStatus(long projectId, String documentId, DocumentStatus status) {
        Objects.requireNonNull(status, "status must not be null");
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement("""
                     UPDATE rag_document SET status = ?
                     WHERE project_id = ? AND document_id = ?
                     """)) {
            statement.setString(1, status.name());
            statement.setLong(2, projectId);
            statement.setString(3, documentId);
            requireOne(statement.executeUpdate(), "Document does not exist");
        } catch (SQLException exception) {
            throw failure("Unable to update document status", exception);
        }
    }

    @Override
    public void markDeleted(long projectId, String documentId) {
        inTransaction(connection -> {
            deleteChunks(connection, projectId, documentId);
            try (PreparedStatement statement = connection.prepareStatement("""
                    UPDATE rag_document SET status = 'DELETED'
                    WHERE project_id = ? AND document_id = ?
                    """)) {
                statement.setLong(1, projectId);
                statement.setString(2, documentId);
                requireOne(statement.executeUpdate(), "Document does not exist");
            }
        }, "Unable to delete document knowledge");
    }

    private void upsertDocument(Connection connection, Document value) throws SQLException {
        try (PreparedStatement update = connection.prepareStatement("""
                UPDATE rag_document
                SET source_key = ?, source_type = ?, title = ?, file_name = ?,
                    media_type = ?, content_hash = ?, status = ?
                WHERE project_id = ? AND document_id = ?
                """)) {
            update.setString(1, value.sourceKey());
            update.setString(2, value.sourceType());
            update.setString(3, value.title());
            update.setString(4, value.fileName());
            update.setString(5, value.mediaType());
            update.setString(6, value.contentHash());
            update.setString(7, value.status().name());
            update.setLong(8, value.projectId());
            update.setString(9, value.documentId());
            if (update.executeUpdate() == 1) {
                return;
            }
        }
        try (PreparedStatement insert = connection.prepareStatement("""
                INSERT INTO rag_document
                    (document_id, project_id, source_key, source_type, title, file_name,
                     media_type, content_hash, status, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """)) {
            insert.setString(1, value.documentId());
            insert.setLong(2, value.projectId());
            insert.setString(3, value.sourceKey());
            insert.setString(4, value.sourceType());
            insert.setString(5, value.title());
            insert.setString(6, value.fileName());
            insert.setString(7, value.mediaType());
            insert.setString(8, value.contentHash());
            insert.setString(9, value.status().name());
            insert.setLong(10, value.createdBy());
            insert.setTimestamp(11, Timestamp.from(value.createdAt()));
            insert.executeUpdate();
        }
    }

    private void insertChunk(Connection connection, DocumentChunk value) throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement("""
                INSERT INTO rag_document_chunk
                    (chunk_id, document_id, project_id, ordinal, content,
                     content_hash, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """)) {
            statement.setString(1, value.chunkId());
            statement.setString(2, value.documentId());
            statement.setLong(3, value.projectId());
            statement.setInt(4, value.ordinal());
            statement.setString(5, value.content());
            statement.setString(6, value.contentHash());
            statement.setString(7, writeMetadata(value.metadata()));
            statement.executeUpdate();
        }
    }

    private void deleteChunks(Connection connection, long projectId, String documentId)
            throws SQLException {
        try (PreparedStatement statement = connection.prepareStatement("""
                DELETE FROM rag_document_chunk
                WHERE project_id = ? AND document_id = ?
                """)) {
            statement.setLong(1, projectId);
            statement.setString(2, documentId);
            statement.executeUpdate();
        }
    }

    private Optional<Document> findDocument(String sql, Binder binder) {
        try (Connection connection = dataSource.getConnection();
             PreparedStatement statement = connection.prepareStatement(sql)) {
            binder.bind(statement);
            try (ResultSet rows = statement.executeQuery()) {
                return rows.next() ? Optional.of(document(rows)) : Optional.empty();
            }
        } catch (SQLException exception) {
            throw failure("Unable to load document", exception);
        }
    }

    private Document document(ResultSet row) throws SQLException {
        return new Document(
                row.getString("document_id"), row.getLong("project_id"),
                row.getString("source_key"), row.getString("source_type"),
                row.getString("title"), row.getString("file_name"),
                row.getString("media_type"), row.getString("content_hash"),
                DocumentStatus.valueOf(row.getString("status")), row.getLong("created_by"),
                row.getTimestamp("created_at").toInstant());
    }

    private DocumentChunk chunk(ResultSet row) throws SQLException {
        return new DocumentChunk(
                row.getString("chunk_id"), row.getString("document_id"),
                row.getLong("project_id"), row.getInt("ordinal"),
                row.getString("content"), row.getString("content_hash"),
                readMetadata(row.getString("metadata_json")));
    }

    private String writeMetadata(Map<String, String> metadata) {
        try {
            return objectMapper.writeValueAsString(metadata);
        } catch (JsonProcessingException exception) {
            throw new IllegalArgumentException("Chunk metadata cannot be serialized", exception);
        }
    }

    private Map<String, String> readMetadata(String metadata) {
        try {
            return objectMapper.readValue(metadata, METADATA_TYPE);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Stored chunk metadata is invalid", exception);
        }
    }

    private void inTransaction(SqlWork work, String message) {
        try (Connection connection = dataSource.getConnection()) {
            boolean autoCommit = connection.getAutoCommit();
            connection.setAutoCommit(false);
            try {
                work.execute(connection);
                connection.commit();
            } catch (RuntimeException | SQLException failure) {
                try {
                    connection.rollback();
                } catch (SQLException rollbackFailure) {
                    failure.addSuppressed(rollbackFailure);
                }
                throw failure;
            } finally {
                connection.setAutoCommit(autoCommit);
            }
        } catch (SQLException exception) {
            throw failure(message, exception);
        }
    }

    private static void requireOne(int affected, String message) {
        if (affected != 1) {
            throw new IllegalStateException(message);
        }
    }

    private static IllegalStateException failure(String message, SQLException cause) {
        return new IllegalStateException(message, cause);
    }

    @FunctionalInterface
    private interface Binder {
        void bind(PreparedStatement statement) throws SQLException;
    }

    @FunctionalInterface
    private interface SqlWork {
        void execute(Connection connection) throws SQLException;
    }
}
