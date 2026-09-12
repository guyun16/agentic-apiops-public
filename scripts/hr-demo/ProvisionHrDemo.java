import java.sql.*;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

/** Local Java-owned bootstrap: dedicated identities and project, no execution facts. */
class ProvisionHrDemo {
    static final BCryptPasswordEncoder ENCODER = new BCryptPasswordEncoder();
    static String env(String key) {
        String value = System.getenv(key);
        if (value == null || value.isBlank()) throw new IllegalArgumentException("Missing " + key);
        return value;
    }
    static void execute(Connection c, String sql, Object... args) throws SQLException {
        try (var s = c.prepareStatement(sql)) {
            for (int i = 0; i < args.length; i++) s.setObject(i + 1, args[i]);
            s.executeUpdate();
        }
    }
    static long user(Connection c, String name, String password) throws SQLException {
        if (password.length() < 16) throw new IllegalArgumentException("Demo password needs 16 characters");
        try (var s = c.prepareStatement("SELECT id,password_hash,status FROM auth_user WHERE username=?")) {
            s.setString(1, name);
            try (var r = s.executeQuery()) {
                if (r.next()) {
                    if (!ENCODER.matches(password, r.getString(2)) || !"ENABLED".equals(r.getString(3)))
                        throw new IllegalStateException("Existing demo identity differs; refusing to overwrite " + name);
                    return r.getLong(1);
                }
            }
        }
        execute(c, "INSERT INTO auth_user(username,password_hash,status,created_at,updated_at) VALUES(?,?,'ENABLED',NOW(3),NOW(3))",
                name, ENCODER.encode(password));
        return user(c, name, password);
    }
    public static void main(String[] args) throws Exception {
        try (var c = DriverManager.getConnection(env("APIOPS_AUTH_DB_URL"), env("APIOPS_AUTH_DB_USERNAME"), env("APIOPS_AUTH_DB_PASSWORD"))) {
            c.setAutoCommit(false);
            try {
                long presenter = user(c, "hr-presenter", env("HR_PRESENTER_PASSWORD"));
                long viewer = user(c, "hr-viewer", env("HR_VIEWER_PASSWORD"));
                execute(c, "INSERT INTO apiops_project(project_key,project_name,owner_user_id,status,created_at,updated_at) VALUES('hr-showcase','HR Demo / APIOps Portfolio',?,'ACTIVE',NOW(3),NOW(3)) ON DUPLICATE KEY UPDATE project_key=project_key", presenter);
                long project;
                try (var s = c.createStatement(); var r = s.executeQuery("SELECT id,owner_user_id FROM apiops_project WHERE project_key='hr-showcase'")) {
                    r.next(); project = r.getLong(1);
                    if (r.getLong(2) != presenter) throw new IllegalStateException("Demo project belongs to another owner");
                }
                for (long id : new long[]{presenter, viewer}) {
                    try (var s = c.prepareStatement("SELECT COUNT(*) FROM apiops_project_member WHERE user_id=? AND project_id<>?")) {
                        s.setLong(1, id); s.setLong(2, project);
                        try (var r = s.executeQuery()) { r.next(); if (r.getLong(1) != 0) throw new IllegalStateException("Demo identity has unrelated memberships"); }
                    }
                    String role = id == presenter ? "OWNER" : "VIEWER";
                    execute(c, "INSERT INTO apiops_project_member(project_id,user_id,project_role,joined_at,updated_at) VALUES(?,?,?,NOW(3),NOW(3)) ON DUPLICATE KEY UPDATE project_role=project_role", project, id, role);
                    try (var s = c.prepareStatement("SELECT project_role FROM apiops_project_member WHERE project_id=? AND user_id=?")) {
                        s.setLong(1, project); s.setLong(2, id);
                        try (var r = s.executeQuery()) { r.next(); if (!role.equals(r.getString(1))) throw new IllegalStateException("Demo role differs"); }
                    }
                    execute(c, "INSERT INTO auth_user_role(user_id,role_id,created_at,updated_at) SELECT ?,id,NOW(3),NOW(3) FROM auth_role WHERE role_code='PLATFORM_USER' ON DUPLICATE KEY UPDATE user_id=user_id", id);
                }
                // The presenter may use existing project-scoped read tools during diagnosis.
                // No write-tool permission or global administrator role is granted.
                execute(c, "INSERT INTO auth_role(role_code,created_at,updated_at) VALUES('TOOL_READER',NOW(3),NOW(3)) ON DUPLICATE KEY UPDATE role_code=role_code");
                execute(c, "INSERT INTO auth_permission(permission_code,created_at,updated_at) VALUES('TOOL_READ',NOW(3),NOW(3)) ON DUPLICATE KEY UPDATE permission_code=permission_code");
                execute(c, "INSERT INTO auth_role_permission(role_id,permission_id,created_at,updated_at) SELECT r.id,p.id,NOW(3),NOW(3) FROM auth_role r JOIN auth_permission p ON p.permission_code='TOOL_READ' WHERE r.role_code='TOOL_READER' ON DUPLICATE KEY UPDATE role_id=role_id");
                execute(c, "INSERT INTO auth_user_role(user_id,role_id,created_at,updated_at) SELECT ?,id,NOW(3),NOW(3) FROM auth_role WHERE role_code='TOOL_READER' ON DUPLICATE KEY UPDATE user_id=user_id", presenter);
                c.commit();
                System.out.println("{\"projectId\":" + project + ",\"presenterId\":" + presenter + ",\"viewerId\":" + viewer + "}");
            } catch (Exception e) { c.rollback(); throw e; }
        }
    }
}
