-- Stage 8 runner execution facts for MySQL 8.x.
-- Raw request headers, response headers, and response bodies are intentionally not stored.
CREATE TABLE IF NOT EXISTS test_task (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    project_id BIGINT UNSIGNED NOT NULL,
    case_id VARCHAR(128) NOT NULL,
    api_id VARCHAR(128) NOT NULL,
    task_name VARCHAR(255) NOT NULL,
    testcase_dsl_json LONGTEXT NOT NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    INDEX idx_test_task_project_created_at (project_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS test_run (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    project_id BIGINT UNSIGNED NOT NULL,
    task_id BIGINT UNSIGNED NOT NULL,
    status VARCHAR(32) NOT NULL,
    failure_type VARCHAR(64) NOT NULL,
    started_at DATETIME(3) NULL,
    finished_at DATETIME(3) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    INDEX idx_test_run_project_task (project_id, task_id, id),
    CONSTRAINT fk_test_run_task
        FOREIGN KEY (task_id) REFERENCES test_task (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS test_batch (
    id CHAR(36) NOT NULL,
    project_id BIGINT UNSIGNED NOT NULL,
    requested_by BIGINT UNSIGNED NOT NULL,
    status VARCHAR(32) NOT NULL,
    cancel_requested TINYINT(1) NOT NULL DEFAULT 0,
    started_at DATETIME(3) NULL,
    finished_at DATETIME(3) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    INDEX idx_test_batch_project_created_at (project_id, created_at),
    CONSTRAINT chk_test_batch_cancel_requested CHECK (cancel_requested IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS test_batch_run (
    batch_id CHAR(36) NOT NULL,
    project_id BIGINT UNSIGNED NOT NULL,
    run_id BIGINT UNSIGNED NOT NULL,
    member_order INT UNSIGNED NOT NULL,
    PRIMARY KEY (batch_id, run_id),
    UNIQUE KEY uk_test_batch_run_order (batch_id, member_order),
    INDEX idx_test_batch_run_project_run (project_id, run_id),
    CONSTRAINT fk_test_batch_run_batch
        FOREIGN KEY (batch_id) REFERENCES test_batch (id),
    CONSTRAINT fk_test_batch_run_run
        FOREIGN KEY (run_id) REFERENCES test_run (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS case_result (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    project_id BIGINT UNSIGNED NOT NULL,
    run_id BIGINT UNSIGNED NOT NULL,
    case_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    failure_type VARCHAR(64) NOT NULL,
    started_at DATETIME(3) NOT NULL,
    finished_at DATETIME(3) NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    INDEX idx_case_result_project_run (project_id, run_id, id),
    CONSTRAINT fk_case_result_run
        FOREIGN KEY (run_id) REFERENCES test_run (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS step_result (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    project_id BIGINT UNSIGNED NOT NULL,
    run_id BIGINT UNSIGNED NOT NULL,
    case_result_id BIGINT UNSIGNED NOT NULL,
    step_id VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    failure_type VARCHAR(64) NOT NULL,
    assertion_results_json JSON NOT NULL,
    response_status_code INT NULL,
    duration_ms BIGINT UNSIGNED NULL,
    created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
    PRIMARY KEY (id),
    INDEX idx_step_result_project_case (project_id, case_result_id, id),
    CONSTRAINT fk_step_result_case
        FOREIGN KEY (case_result_id) REFERENCES case_result (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS step_exchange_snapshot (
    step_result_id BIGINT UNSIGNED NOT NULL,
    snapshot_json JSON NOT NULL,
    PRIMARY KEY (step_result_id),
    CONSTRAINT fk_step_exchange_snapshot_step
        FOREIGN KEY (step_result_id) REFERENCES step_result (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
