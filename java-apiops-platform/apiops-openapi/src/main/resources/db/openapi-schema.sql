-- Stage 6 Day 4 OpenAPI Metadata persistence baseline for MySQL 8.x.
CREATE TABLE IF NOT EXISTS api_document (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    api_doc_id VARCHAR(128) NOT NULL,
    project_id BIGINT UNSIGNED NOT NULL,
    source_key VARCHAR(255) NOT NULL,
    document_name VARCHAR(255) NOT NULL,
    openapi_version VARCHAR(32) NOT NULL,
    title VARCHAR(255) NOT NULL,
    api_version VARCHAR(128) NOT NULL,
    document_format VARCHAR(16) NOT NULL,
    content_hash CHAR(64) NOT NULL,
    raw_content LONGTEXT NOT NULL,
    version_no INT UNSIGNED NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_by BIGINT UNSIGNED NOT NULL,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_api_document_api_doc_id UNIQUE (api_doc_id),
    CONSTRAINT uk_api_document_project_source_version
        UNIQUE (project_id, source_key, version_no),
    INDEX idx_api_document_project_content_hash (project_id, content_hash),
    INDEX idx_api_document_project_created_at (project_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS api_endpoint (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    api_id VARCHAR(128) NOT NULL,
    api_doc_id VARCHAR(128) NOT NULL,
    project_id BIGINT UNSIGNED NOT NULL,
    operation_id VARCHAR(255) NULL,
    http_method VARCHAR(16) NOT NULL,
    path VARCHAR(512) NOT NULL,
    summary VARCHAR(1024) NULL,
    description TEXT NULL,
    tags_json JSON NULL,
    servers_json JSON NULL,
    security_json JSON NULL,
    deprecated BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_api_endpoint_api_id UNIQUE (api_id),
    CONSTRAINT uk_api_endpoint_document_method_path
        UNIQUE (api_doc_id, http_method, path)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS api_parameter (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    api_id VARCHAR(128) NOT NULL,
    project_id BIGINT UNSIGNED NOT NULL,
    name VARCHAR(255) NOT NULL,
    location VARCHAR(32) NOT NULL,
    required BOOLEAN NOT NULL,
    description TEXT NULL,
    schema_json JSON NOT NULL,
    example_json JSON NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS api_request_schema (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    api_id VARCHAR(128) NOT NULL,
    project_id BIGINT UNSIGNED NOT NULL,
    required BOOLEAN NOT NULL,
    media_type VARCHAR(255) NOT NULL,
    schema_json JSON NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS api_response_schema (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    api_id VARCHAR(128) NOT NULL,
    project_id BIGINT UNSIGNED NOT NULL,
    status_code VARCHAR(32) NOT NULL,
    description TEXT NULL,
    media_type VARCHAR(255) NOT NULL,
    schema_json JSON NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS api_example (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    api_id VARCHAR(128) NOT NULL,
    project_id BIGINT UNSIGNED NOT NULL,
    owner_type VARCHAR(32) NOT NULL,
    owner_ref_id BIGINT UNSIGNED NOT NULL,
    example_name VARCHAR(255) NOT NULL,
    summary VARCHAR(1024) NULL,
    description TEXT NULL,
    value_json JSON NOT NULL,
    created_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
