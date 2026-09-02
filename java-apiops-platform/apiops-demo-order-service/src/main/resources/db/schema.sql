-- Stage 4 Day 3 order-domain baseline schema for MySQL 8.x.
-- This repeatable bootstrap script is not a formal database migration tool.
-- It only creates missing tables; evolve an existing database with reviewed migrations.

CREATE TABLE IF NOT EXISTS demo_user (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_no VARCHAR(64) NOT NULL,
    user_name VARCHAR(128) NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_demo_user_user_no UNIQUE (user_no)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS demo_product (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    product_no VARCHAR(64) NOT NULL,
    product_name VARCHAR(128) NOT NULL,
    sale_price DECIMAL(18,2) NOT NULL,
    status VARCHAR(32) NOT NULL,
    version BIGINT UNSIGNED NOT NULL DEFAULT 0,
    deleted TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_demo_product_product_no UNIQUE (product_no),
    KEY idx_demo_product_status_created_id (status, created_at, id),
    CONSTRAINT chk_demo_product_sale_price CHECK (sale_price >= 0.00),
    CONSTRAINT chk_demo_product_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS demo_inventory (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    product_id BIGINT UNSIGNED NOT NULL,
    available_stock BIGINT UNSIGNED NOT NULL,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_demo_inventory_product_id UNIQUE (product_id),
    CONSTRAINT fk_demo_inventory_product FOREIGN KEY (product_id)
        REFERENCES demo_product (id) ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS demo_coupon (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    coupon_no VARCHAR(64) NOT NULL,
    coupon_name VARCHAR(128) NOT NULL,
    threshold_amount DECIMAL(18,2) NOT NULL,
    discount_amount DECIMAL(18,2) NOT NULL,
    valid_from DATETIME(3) NOT NULL,
    valid_until DATETIME(3) NOT NULL,
    status VARCHAR(32) NOT NULL,
    deleted TINYINT(1) NOT NULL DEFAULT 0,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_demo_coupon_coupon_no UNIQUE (coupon_no),
    CONSTRAINT chk_demo_coupon_threshold CHECK (threshold_amount >= 0.00),
    CONSTRAINT chk_demo_coupon_discount CHECK (discount_amount > 0.00),
    CONSTRAINT chk_demo_coupon_validity CHECK (valid_until > valid_from),
    CONSTRAINT chk_demo_coupon_deleted CHECK (deleted IN (0, 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS demo_user_coupon (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_coupon_no VARCHAR(64) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    coupon_id BIGINT UNSIGNED NOT NULL,
    status VARCHAR(32) NOT NULL,
    received_at DATETIME(3) NOT NULL,
    used_at DATETIME(3) NULL,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_demo_user_coupon_no UNIQUE (user_coupon_no),
    CONSTRAINT uk_demo_user_coupon_user_coupon UNIQUE (user_id, coupon_id),
    KEY idx_demo_user_coupon_user_status_created_id (user_id, status, created_at, id),
    KEY idx_demo_user_coupon_coupon_id (coupon_id),
    CONSTRAINT fk_demo_user_coupon_user FOREIGN KEY (user_id)
        REFERENCES demo_user (id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_demo_user_coupon_coupon FOREIGN KEY (coupon_id)
        REFERENCES demo_coupon (id) ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS demo_order (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    order_no VARCHAR(64) NOT NULL,
    user_id BIGINT UNSIGNED NOT NULL,
    user_coupon_id BIGINT UNSIGNED NULL,
    original_amount DECIMAL(18,2) NOT NULL,
    discount_amount DECIMAL(18,2) NOT NULL,
    payable_amount DECIMAL(18,2) NOT NULL,
    status VARCHAR(32) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_demo_order_order_no UNIQUE (order_no),
    KEY idx_demo_order_user_created_id (user_id, created_at, id),
    KEY idx_demo_order_user_status_created_id (user_id, status, created_at, id),
    KEY idx_demo_order_user_coupon_id (user_coupon_id),
    CONSTRAINT chk_demo_order_original_amount CHECK (original_amount >= 0.00),
    CONSTRAINT chk_demo_order_discount_amount CHECK (discount_amount >= 0.00),
    CONSTRAINT chk_demo_order_payable_amount CHECK (payable_amount >= 0.00),
    CONSTRAINT chk_demo_order_amounts CHECK (
        discount_amount <= original_amount
        AND payable_amount = original_amount - discount_amount
    ),
    CONSTRAINT fk_demo_order_user FOREIGN KEY (user_id)
        REFERENCES demo_user (id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_demo_order_user_coupon FOREIGN KEY (user_coupon_id)
        REFERENCES demo_user_coupon (id) ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS demo_order_item (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    order_id BIGINT UNSIGNED NOT NULL,
    product_id BIGINT UNSIGNED NOT NULL,
    product_no_snapshot VARCHAR(64) NOT NULL,
    product_name_snapshot VARCHAR(128) NOT NULL,
    unit_price DECIMAL(18,2) NOT NULL,
    quantity INT UNSIGNED NOT NULL,
    line_amount DECIMAL(18,2) NOT NULL,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_demo_order_item_order_product UNIQUE (order_id, product_id),
    KEY idx_demo_order_item_product_id (product_id),
    CONSTRAINT chk_demo_order_item_unit_price CHECK (unit_price >= 0.00),
    CONSTRAINT chk_demo_order_item_quantity CHECK (quantity > 0),
    CONSTRAINT chk_demo_order_item_line_amount CHECK (
        line_amount = unit_price * quantity
    ),
    CONSTRAINT fk_demo_order_item_order FOREIGN KEY (order_id)
        REFERENCES demo_order (id) ON UPDATE RESTRICT ON DELETE RESTRICT,
    CONSTRAINT fk_demo_order_item_product FOREIGN KEY (product_id)
        REFERENCES demo_product (id) ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS demo_payment (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    payment_no VARCHAR(64) NOT NULL,
    order_id BIGINT UNSIGNED NOT NULL,
    payment_amount DECIMAL(18,2) NOT NULL,
    status VARCHAR(32) NOT NULL,
    paid_at DATETIME(3) NULL,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_demo_payment_payment_no UNIQUE (payment_no),
    CONSTRAINT uk_demo_payment_order_id UNIQUE (order_id),
    CONSTRAINT chk_demo_payment_amount CHECK (payment_amount >= 0.00),
    CONSTRAINT fk_demo_payment_order FOREIGN KEY (order_id)
        REFERENCES demo_order (id) ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;

CREATE TABLE IF NOT EXISTS demo_payment_callback (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    callback_no VARCHAR(64) NOT NULL,
    payment_id BIGINT UNSIGNED NOT NULL,
    callback_amount DECIMAL(18,2) NOT NULL,
    request_fingerprint VARCHAR(128) NOT NULL,
    process_status VARCHAR(32) NOT NULL,
    result_code VARCHAR(64) NULL,
    result_message VARCHAR(512) NULL,
    received_at DATETIME(3) NOT NULL,
    processed_at DATETIME(3) NULL,
    created_at DATETIME(3) NOT NULL,
    updated_at DATETIME(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uk_demo_payment_callback_no UNIQUE (callback_no),
    KEY idx_demo_payment_callback_payment_received_id (payment_id, received_at, id),
    CONSTRAINT chk_demo_payment_callback_amount CHECK (callback_amount >= 0.00),
    CONSTRAINT fk_demo_payment_callback_payment FOREIGN KEY (payment_id)
        REFERENCES demo_payment (id) ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci;
