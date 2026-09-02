package com.apiops.rag.repository;

import com.apiops.rag.domain.Document;
import com.apiops.rag.domain.DocumentChunk;
import com.apiops.rag.domain.DocumentStatus;
import com.apiops.rag.retrieval.RagQueryRecord;
import com.apiops.rag.retrieval.RagQueryStatus;
import com.apiops.rag.retrieval.RagResultReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;

import javax.sql.DataSource;
import java.io.InputStream;
import java.io.PrintWriter;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.SQLException;
import java.sql.SQLFeatureNotSupportedException;
import java.sql.Statement;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.UUID;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.logging.Logger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class JdbcDocumentRepositoryMySqlIntegrationTest {

    private static final List<Long> PROJECTS_TO_CLEAN = new CopyOnWriteArrayList<>();
    private static DataSource dataSource;

    @BeforeAll
    static void initializeSchema() throws Exception {
        String url = System.getenv("APIOPS_RAG_DB_URL");
        Assumptions.assumeTrue(url != null, "Set APIOPS_RAG_DB_URL to run MySQL integration");
        String username = System.getenv("APIOPS_RAG_DB_USERNAME");
        String password = System.getenv("APIOPS_RAG_DB_PASSWORD");
        Assumptions.assumeTrue(username != null && password != null,
                "Set matching MySQL username and password environment variables");
        Class.forName("com.mysql.cj.jdbc.Driver");
        dataSource = new DriverManagerDataSource(url, username, password);
        try (Connection connection = dataSource.getConnection()) {
            assertEquals("apiops_rag", connection.getCatalog());
            executeSchema(connection);
            executeSchema(connection);
        }
    }

    @AfterEach
    void cleanRows() throws SQLException {
        if (dataSource == null) {
            return;
        }
        try (Connection connection = dataSource.getConnection()) {
            for (long projectId : PROJECTS_TO_CLEAN) {
                try (PreparedStatement chunks = connection.prepareStatement(
                        "DELETE FROM rag_document_chunk WHERE project_id = ?");
                     PreparedStatement queries = connection.prepareStatement(
                             "DELETE FROM rag_query_record WHERE project_id = ?");
                     PreparedStatement documents = connection.prepareStatement(
                             "DELETE FROM rag_document WHERE project_id = ?")) {
                    chunks.setLong(1, projectId);
                    chunks.executeUpdate();
                    queries.setLong(1, projectId);
                    queries.executeUpdate();
                    documents.setLong(1, projectId);
                    documents.executeUpdate();
                }
            }
        } finally {
            PROJECTS_TO_CLEAN.clear();
        }
    }

    @Test
    void persistsProjectScopedRagQueryFactWithoutChunkContent() {
        long projectId = 800_000L + Math.abs(UUID.randomUUID().hashCode());
        PROJECTS_TO_CLEAN.add(projectId);
        RagQueryRecordRepository repository = new JdbcRagQueryRecordRepository(
                dataSource, new ObjectMapper());
        RagQueryRecord fact = new RagQueryRecord(
                "ragq-integration", projectId, "Why did order creation fail?", 5, 1,
                List.of(new RagResultReference("doc-orders", "chunk-orders-1")),
                RagQueryStatus.SUCCESS_WITH_RESULTS,
                Instant.parse("2026-08-13T00:00:00Z"),
                Instant.parse("2026-08-13T00:00:00.125Z"), 125L);

        repository.save(fact);

        assertEquals(fact, repository.findById(
                projectId, "ragq-integration").orElseThrow());
        assertTrue(repository.findById(
                projectId + 1, "ragq-integration").isEmpty());
    }

    @Test
    void persistsReplacesAndDeletesProjectScopedFormalKnowledge() {
        long projectId = 800_000L + Math.abs(UUID.randomUUID().hashCode());
        PROJECTS_TO_CLEAN.add(projectId);
        DocumentRepository repository = new JdbcDocumentRepository(
                dataSource, new ObjectMapper());
        Document stored = document(projectId, DocumentStatus.STORED, "a".repeat(64));

        repository.saveKnowledge(stored, List.of(
                chunk(projectId, "chunk-old-0", 0, "first"),
                chunk(projectId, "chunk-old-1", 1, "second")));
        repository.updateStatus(projectId, stored.documentId(), DocumentStatus.INDEXED);

        assertEquals(DocumentStatus.INDEXED,
                repository.findById(projectId, stored.documentId()).orElseThrow().status());
        assertEquals(List.of(0, 1), repository.findChunks(projectId, stored.documentId())
                .stream().map(DocumentChunk::ordinal).toList());

        Document replacement = document(
                projectId, DocumentStatus.STORED, "b".repeat(64));
        repository.saveKnowledge(replacement,
                List.of(chunk(projectId, "chunk-new-0", 0, "replacement")));

        List<DocumentChunk> current = repository.findChunks(projectId, stored.documentId());
        assertEquals(1, current.size());
        assertEquals("chunk-new-0", current.getFirst().chunkId());
        assertEquals(Map.of("section", "runbook"), current.getFirst().metadata());
        assertEquals(replacement.contentHash(),
                repository.findBySourceKey(projectId, "runbook/orders").orElseThrow()
                        .contentHash());

        repository.markDeleted(projectId, stored.documentId());

        assertEquals(DocumentStatus.DELETED,
                repository.findById(projectId, stored.documentId()).orElseThrow().status());
        assertTrue(repository.findChunks(projectId, stored.documentId()).isEmpty());
    }

    private Document document(long projectId, DocumentStatus status, String hash) {
        return new Document(
                "doc-integration", projectId, "runbook/orders", "RUNBOOK",
                "Orders runbook", "orders.md", "text/markdown", hash, status,
                7L, Instant.parse("2026-08-12T12:00:00Z"));
    }

    private DocumentChunk chunk(
            long projectId, String chunkId, int ordinal, String content) {
        return new DocumentChunk(
                chunkId, "doc-integration", projectId, ordinal, content,
                "c".repeat(64),
                Map.of("section", "runbook"));
    }

    private static void executeSchema(Connection connection) throws Exception {
        String script;
        try (InputStream input = Objects.requireNonNull(
                JdbcDocumentRepositoryMySqlIntegrationTest.class.getResourceAsStream(
                        "/db/rag-schema.sql"))) {
            script = new String(input.readAllBytes(), StandardCharsets.UTF_8);
        }
        for (String statementText : script.split(";")) {
            String sql = statementText.trim();
            if (!sql.isEmpty()) {
                try (Statement statement = connection.createStatement()) {
                    statement.execute(sql);
                }
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
        public PrintWriter getLogWriter() throws SQLException {
            return DriverManager.getLogWriter();
        }

        @Override
        public void setLogWriter(PrintWriter out) throws SQLException {
            DriverManager.setLogWriter(out);
        }

        @Override
        public void setLoginTimeout(int seconds) throws SQLException {
            DriverManager.setLoginTimeout(seconds);
        }

        @Override
        public int getLoginTimeout() throws SQLException {
            return DriverManager.getLoginTimeout();
        }

        @Override
        public Logger getParentLogger() throws SQLFeatureNotSupportedException {
            throw new SQLFeatureNotSupportedException();
        }

        @Override
        public <T> T unwrap(Class<T> iface) throws SQLException {
            if (iface.isInstance(this)) {
                return iface.cast(this);
            }
            throw new SQLException("Not a wrapper for " + iface.getName());
        }

        @Override
        public boolean isWrapperFor(Class<?> iface) {
            return iface.isInstance(this);
        }
    }
}
