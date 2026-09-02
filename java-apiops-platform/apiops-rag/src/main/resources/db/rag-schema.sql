-- Stage 10 formal diagnostic knowledge persistence baseline for MySQL 8.x.
-- Embeddings and vector index entries are derived data and are intentionally absent.
CREATE TABLE IF NOT EXISTS rag_document (
    document_id VARCHAR(128) NOT NULL,
    project_id BIGINT UNSIGNED NOT NULL,
    source_key VARCHAR(255) NOT NULL,
    source_type VARCHAR(64) NOT NULL,
    title VARCHAR(255) NOT NULL,
    file_name VARCHAR(255) NOT NULL,
    media_type VARCHAR(128) NOT NULL,
    content_hash CHAR(64) NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_by BIGINT UNSIGNED NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (project_id, document_id),
    CONSTRAINT uk_rag_document_project_source UNIQUE (project_id, source_key),
    CONSTRAINT ck_rag_document_status
        CHECK (status IN ('STORED', 'INDEXED', 'INDEX_FAILED', 'DELETED')),
    INDEX idx_rag_document_project_status (project_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS rag_document_chunk (
    chunk_id VARCHAR(128) NOT NULL,
    document_id VARCHAR(128) NOT NULL,
    project_id BIGINT UNSIGNED NOT NULL,
    ordinal INT UNSIGNED NOT NULL,
    content LONGTEXT NOT NULL,
    content_hash CHAR(64) NOT NULL,
    metadata_json JSON NOT NULL,
    PRIMARY KEY (project_id, chunk_id),
    CONSTRAINT uk_rag_chunk_document_ordinal
        UNIQUE (project_id, document_id, ordinal),
    CONSTRAINT fk_rag_chunk_document
        FOREIGN KEY (project_id, document_id)
        REFERENCES rag_document (project_id, document_id) ON DELETE CASCADE,
    INDEX idx_rag_chunk_project_document (project_id, document_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS rag_query_record (
    rag_query_id VARCHAR(128) NOT NULL,
    project_id BIGINT UNSIGNED NOT NULL,
    query_text TEXT NOT NULL,
    top_k INT UNSIGNED NOT NULL,
    retrieved_count INT UNSIGNED NOT NULL,
    result_references_json JSON NOT NULL,
    status VARCHAR(32) NOT NULL,
    started_at DATETIME(3) NOT NULL,
    finished_at DATETIME(3) NOT NULL,
    duration_ms BIGINT UNSIGNED NOT NULL,
    PRIMARY KEY (project_id, rag_query_id),
    CONSTRAINT ck_rag_query_record_status
        CHECK (status IN ('SUCCESS_WITH_RESULTS', 'ZERO_HIT', 'FAILURE')),
    INDEX idx_rag_query_record_project_started (project_id, started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
