-- Durable Java Tool Gateway audit facts for MySQL 8.x.
-- Only the Gateway's sanitized summary is stored; raw arguments/results are absent.
CREATE TABLE IF NOT EXISTS tool_audit (
    tool_call_id VARCHAR(128) NOT NULL,
    project_id BIGINT UNSIGNED NOT NULL,
    tool_name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    violation_code VARCHAR(128) NOT NULL,
    sanitized_summary TEXT NOT NULL,
    latency_nanos BIGINT UNSIGNED NOT NULL,
    requested_target_project_id BIGINT UNSIGNED NULL,
    recorded_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (project_id, tool_call_id),
    CONSTRAINT ck_tool_audit_status CHECK (
        status IN ('SUCCESS', 'DENIED', 'INVALID', 'SAFETY_VIOLATION', 'TIMEOUT', 'FAILED')
    ),
    INDEX idx_tool_audit_project_recorded (project_id, recorded_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
