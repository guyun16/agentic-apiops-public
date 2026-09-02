-- Repeatable baseline data for local development and tests.
-- Relationships resolve internal IDs from stable business numbers.

INSERT INTO demo_user (user_no, user_name, status, created_at, updated_at)
VALUES
    ('usr_001', 'Demo User 001', 'ENABLED', '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'),
    ('usr_002', 'Demo User 002', 'ENABLED', '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'),
    ('usr_disabled_001', 'Disabled Demo User', 'DISABLED', '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000')
ON DUPLICATE KEY UPDATE
    user_name = VALUES(user_name),
    status = VALUES(status),
    created_at = VALUES(created_at),
    updated_at = VALUES(updated_at);

INSERT INTO demo_product (
    product_no, product_name, sale_price, status, version, deleted, created_at, updated_at
)
VALUES
    ('prd_001', 'Demo Product 001', 100.00, 'ON_SALE', 0, 0, '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'),
    ('prd_002', 'Demo Product 002', 50.00, 'ON_SALE', 0, 0, '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'),
    ('prd_off_sale_001', 'Off-sale Demo Product', 80.00, 'OFF_SALE', 0, 0, '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000')
ON DUPLICATE KEY UPDATE
    product_name = VALUES(product_name),
    sale_price = VALUES(sale_price),
    status = VALUES(status),
    version = VALUES(version),
    deleted = VALUES(deleted),
    created_at = VALUES(created_at),
    updated_at = VALUES(updated_at);

INSERT INTO demo_inventory (product_id, available_stock, created_at, updated_at)
SELECT id, 100, '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'
FROM demo_product WHERE product_no = 'prd_001'
ON DUPLICATE KEY UPDATE
    available_stock = VALUES(available_stock),
    created_at = VALUES(created_at),
    updated_at = VALUES(updated_at);

INSERT INTO demo_inventory (product_id, available_stock, created_at, updated_at)
SELECT id, 2, '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'
FROM demo_product WHERE product_no = 'prd_002'
ON DUPLICATE KEY UPDATE
    available_stock = VALUES(available_stock),
    created_at = VALUES(created_at),
    updated_at = VALUES(updated_at);

INSERT INTO demo_inventory (product_id, available_stock, created_at, updated_at)
SELECT id, 50, '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'
FROM demo_product WHERE product_no = 'prd_off_sale_001'
ON DUPLICATE KEY UPDATE
    available_stock = VALUES(available_stock),
    created_at = VALUES(created_at),
    updated_at = VALUES(updated_at);

INSERT INTO demo_coupon (
    coupon_no, coupon_name, threshold_amount, discount_amount,
    valid_from, valid_until, status, deleted, created_at, updated_at
)
VALUES
    ('cpn_001', '100 minus 20', 100.00, 20.00, '2020-01-01 00:00:00.000', '2099-12-31 23:59:59.999', 'ACTIVE', 0, '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'),
    ('cpn_inactive_001', '50 minus 10 inactive', 50.00, 10.00, '2020-01-01 00:00:00.000', '2099-12-31 23:59:59.999', 'INACTIVE', 0, '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'),
    ('cpn_expired_001', '50 minus 5 expired', 50.00, 5.00, '2020-01-01 00:00:00.000', '2020-12-31 23:59:59.999', 'ACTIVE', 0, '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'),
    ('cpn_used_001', '30 minus 5', 30.00, 5.00, '2020-01-01 00:00:00.000', '2099-12-31 23:59:59.999', 'ACTIVE', 0, '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000')
ON DUPLICATE KEY UPDATE
    coupon_name = VALUES(coupon_name),
    threshold_amount = VALUES(threshold_amount),
    discount_amount = VALUES(discount_amount),
    valid_from = VALUES(valid_from),
    valid_until = VALUES(valid_until),
    status = VALUES(status),
    deleted = VALUES(deleted),
    created_at = VALUES(created_at),
    updated_at = VALUES(updated_at);

INSERT INTO demo_user_coupon (
    user_coupon_no, user_id, coupon_id, status, received_at, used_at, created_at, updated_at
)
SELECT 'ucp_001', u.id, c.id, 'AVAILABLE', '2025-01-01 00:00:00.000', NULL,
       '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'
FROM demo_user u JOIN demo_coupon c ON c.coupon_no = 'cpn_001'
WHERE u.user_no = 'usr_001'
ON DUPLICATE KEY UPDATE
    user_id = VALUES(user_id), coupon_id = VALUES(coupon_id), status = VALUES(status),
    received_at = VALUES(received_at), used_at = VALUES(used_at),
    created_at = VALUES(created_at), updated_at = VALUES(updated_at);

INSERT INTO demo_user_coupon (
    user_coupon_no, user_id, coupon_id, status, received_at, used_at, created_at, updated_at
)
SELECT 'ucp_002', u.id, c.id, 'AVAILABLE', '2025-01-01 00:00:00.000', NULL,
       '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'
FROM demo_user u JOIN demo_coupon c ON c.coupon_no = 'cpn_001'
WHERE u.user_no = 'usr_002'
ON DUPLICATE KEY UPDATE
    user_id = VALUES(user_id), coupon_id = VALUES(coupon_id), status = VALUES(status),
    received_at = VALUES(received_at), used_at = VALUES(used_at),
    created_at = VALUES(created_at), updated_at = VALUES(updated_at);

INSERT INTO demo_user_coupon (
    user_coupon_no, user_id, coupon_id, status, received_at, used_at, created_at, updated_at
)
SELECT 'ucp_used_001', u.id, c.id, 'USED', '2025-01-01 00:00:00.000', '2025-01-02 00:00:00.000',
       '2025-01-01 00:00:00.000', '2025-01-02 00:00:00.000'
FROM demo_user u JOIN demo_coupon c ON c.coupon_no = 'cpn_used_001'
WHERE u.user_no = 'usr_001'
ON DUPLICATE KEY UPDATE
    user_id = VALUES(user_id), coupon_id = VALUES(coupon_id), status = VALUES(status),
    received_at = VALUES(received_at), used_at = VALUES(used_at),
    created_at = VALUES(created_at), updated_at = VALUES(updated_at);

INSERT INTO demo_user_coupon (
    user_coupon_no, user_id, coupon_id, status, received_at, used_at, created_at, updated_at
)
SELECT 'ucp_expired_001', u.id, c.id, 'EXPIRED', '2020-01-01 00:00:00.000', NULL,
       '2020-01-01 00:00:00.000', '2021-01-01 00:00:00.000'
FROM demo_user u JOIN demo_coupon c ON c.coupon_no = 'cpn_expired_001'
WHERE u.user_no = 'usr_001'
ON DUPLICATE KEY UPDATE
    user_id = VALUES(user_id), coupon_id = VALUES(coupon_id), status = VALUES(status),
    received_at = VALUES(received_at), used_at = VALUES(used_at),
    created_at = VALUES(created_at), updated_at = VALUES(updated_at);
