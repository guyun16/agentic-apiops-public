package com.apiops.auth.repository;

import com.apiops.auth.security.ApiOpsPrincipal;
import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;
import org.springframework.security.authentication.ProviderManager;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.authentication.dao.DaoAuthenticationProvider;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

import javax.sql.DataSource;
import java.io.IOException;
import java.io.InputStream;
import java.io.UncheckedIOException;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;
import java.sql.Statement;
import java.io.PrintWriter;
import java.util.Optional;
import java.util.logging.Logger;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertInstanceOf;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class AuthUserMySqlIntegrationTest {

    private static final String DEMO_PASSWORD = demoPasswordFromProof();

    @Test
    void shouldAuthenticateProvisionedSeedUserThroughMySqlAndPasswordEncoder() throws Exception {
        String url = System.getenv("APIOPS_AUTH_DB_URL");
        Assumptions.assumeTrue(url != null,
                "Set APIOPS_AUTH_DB_URL to run MySQL integration");
        Class.forName("com.mysql.cj.jdbc.Driver");

        String username = System.getenv("APIOPS_AUTH_DB_USERNAME");
        String password = System.getenv("APIOPS_AUTH_DB_PASSWORD");
        assertNotNull(username, "Set APIOPS_AUTH_DB_USERNAME");
        assertNotNull(password, "Set APIOPS_AUTH_DB_PASSWORD");

        DataSource dataSource = new DriverManagerDataSource(url, username, password);
        boolean tableExists;
        try (Connection connection = dataSource.getConnection();
             Statement statement = connection.createStatement();
             var tables = statement.executeQuery("SHOW TABLES LIKE 'auth_user'")) {
            assertEquals("apiops_auth", connection.getCatalog());
            tableExists = tables.next();
        }
        assertTrue(tableExists,
                "auth_user table is missing; execute auth-schema.sql and auth-seed.sql before running this test");

        AuthUserRepository repository = new JdbcAuthUserRepository(dataSource);
        Optional<ApiOpsPrincipal> loaded = repository.findByUsername("demo-user");
        assertNotNull(loaded.orElse(null));

        PasswordEncoder passwordEncoder = new BCryptPasswordEncoder();
        DaoAuthenticationProvider provider = new DaoAuthenticationProvider(
                new com.apiops.auth.security.ApiOpsUserDetailsService(repository)
        );
        provider.setPasswordEncoder(passwordEncoder);

        ApiOpsPrincipal authenticated = assertInstanceOf(
                ApiOpsPrincipal.class,
                new ProviderManager(provider).authenticate(
                        UsernamePasswordAuthenticationToken.unauthenticated(
                                "demo-user", DEMO_PASSWORD
                        )
                ).getPrincipal()
        );
        assertEquals(loaded.get().getUserId(), authenticated.getUserId());
        assertEquals("demo-user", authenticated.getUsername());
    }

    private static String resource(String name) {
        try (InputStream input = AuthUserMySqlIntegrationTest.class
                .getClassLoader().getResourceAsStream(name)) {
            if (input == null) {
                throw new IllegalStateException("Missing test resource: " + name);
            }
            return new String(input.readAllBytes(), StandardCharsets.UTF_8);
        } catch (IOException exception) {
            throw new UncheckedIOException(exception);
        }
    }

    private static String demoPasswordFromProof() {
        String marker = "<!-- demo-password: ";
        return resource("auth-demo-password-proof.md").lines()
                .filter(line -> line.startsWith(marker))
                .map(line -> line.substring(marker.length(), line.length() - " -->".length()))
                .findFirst()
                .orElseThrow(() -> new IllegalStateException("Missing demonstration password proof"));
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
        public <T> T unwrap(Class<T> iface) throws SQLException {
            throw new SQLException("Not a wrapper");
        }

        @Override
        public boolean isWrapperFor(Class<?> iface) {
            return false;
        }

        @Override
        public PrintWriter getLogWriter() {
            return null;
        }

        @Override
        public void setLogWriter(PrintWriter out) {
        }

        @Override
        public void setLoginTimeout(int seconds) {
        }

        @Override
        public int getLoginTimeout() {
            return 0;
        }

        @Override
        public Logger getParentLogger() {
            return Logger.getLogger(Logger.GLOBAL_LOGGER_NAME);
        }
    }
}
