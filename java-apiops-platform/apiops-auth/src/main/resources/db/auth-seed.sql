-- Local-only demonstration user. The password is stored only as a BCrypt hash.
INSERT INTO auth_user (username, password_hash, status, created_at, updated_at)
VALUES (
    'demo-user',
    '$2a$10$WenTT0lW/ci4aaLqa/z6geN7/oL9nzW0jsie1LdXjDbRFPeAh4hTi',
    'ENABLED',
    '2025-01-01 00:00:00.000',
    '2025-01-01 00:00:00.000'
)
ON DUPLICATE KEY UPDATE
    password_hash = VALUES(password_hash),
    status = VALUES(status),
    updated_at = VALUES(updated_at);

INSERT INTO auth_role (role_code, created_at, updated_at)
VALUES
    ('PLATFORM_ADMIN', '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'),
    ('PLATFORM_USER', '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000')
ON DUPLICATE KEY UPDATE
    updated_at = VALUES(updated_at);

INSERT INTO auth_permission (permission_code, created_at, updated_at)
VALUES
    ('PLATFORM_PROJECT_CREATE', '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'),
    ('PLATFORM_PROJECT_LIST', '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000')
ON DUPLICATE KEY UPDATE
    updated_at = VALUES(updated_at);

INSERT INTO auth_role_permission (role_id, permission_id, created_at, updated_at)
SELECT r.id, p.id, '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'
FROM auth_role r
JOIN auth_permission p
    ON (r.role_code, p.permission_code) IN (
        ('PLATFORM_ADMIN', 'PLATFORM_PROJECT_CREATE'),
        ('PLATFORM_ADMIN', 'PLATFORM_PROJECT_LIST'),
        ('PLATFORM_USER', 'PLATFORM_PROJECT_LIST')
    )
ON DUPLICATE KEY UPDATE
    updated_at = VALUES(updated_at);

INSERT INTO auth_user_role (user_id, role_id, created_at, updated_at)
SELECT u.id, r.id, '2025-01-01 00:00:00.000', '2025-01-01 00:00:00.000'
FROM auth_user u
JOIN auth_role r
    ON u.username = 'demo-user'
   AND r.role_code = 'PLATFORM_USER'
ON DUPLICATE KEY UPDATE
    updated_at = VALUES(updated_at);
