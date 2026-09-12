package com.apiops.tool.gateway;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.common.enums.ToolStatus;
import com.apiops.common.tool.ToolResult;
import com.apiops.tool.gateway.audit.JdbcToolAuditRepository;
import com.mysql.cj.jdbc.MysqlDataSource;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.MySQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

import javax.sql.DataSource;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.sql.Connection;
import java.sql.Statement;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

@Testcontainers(disabledWithoutDocker = true)
class ToolAuditRepositoryMySqlIntegrationTest {

    private static final long PROJECT_ID = 42L;
    private static final long USER_ID = 7L;

    @Container
    private static final MySQLContainer<?> MYSQL = new MySQLContainer<>("mysql:8.4")
            .withDatabaseName("apiops_tool_gateway")
            .withUsername("root")
            .withPassword("audit-test-password");

    @BeforeAll
    static void createSchema() throws Exception {
        try (InputStream input = ToolAuditRepositoryMySqlIntegrationTest.class
                .getResourceAsStream("/db/tool-gateway-schema.sql");
             Connection connection = dataSource().getConnection();
             Statement statement = connection.createStatement()) {
            statement.execute(new String(input.readAllBytes(), StandardCharsets.UTF_8));
        }
    }

    @Test
    void gatewayAuditSurvivesRepositoryReopenAndContainsOnlySanitizedResult() {
        JdbcToolAuditRepository writer = new JdbcToolAuditRepository(dataSource());
        ProjectAuthorizationService authorization = new ProjectAuthorizationService(
                (userId, projectId) -> userId == USER_ID && projectId == PROJECT_ID
                        ? Optional.of(ProjectRole.VIEWER) : Optional.empty());
        ToolRegistry registry = new ToolRegistry(authorization);
        registry.register(new ToolDefinition("safe.read", "safe read", Set.of("TOOL_READ")));

        ToolResult<Object> result;
        try (ToolGateway gateway = new ToolGateway(
                new ToolAuth(registry, authorization),
                ResourceGuard.allowAll(),
                new Audit(writer::save),
                null)) {
            result = gateway.execute(
                    new ToolExecutionContext(
                            USER_ID, PROJECT_ID, Set.of("TOOL_READ"), "caller-id"),
                    new ToolCallIntent("safe.read", Map.of()),
                    (context, intent) -> Map.of(
                            "value", "visible",
                            "password", "raw-password",
                            "Authorization", "Bearer raw-token"));
        }

        assertEquals(ToolStatus.SUCCESS, result.getStatus());
        Audit.AuditEvent reopened = new JdbcToolAuditRepository(dataSource())
                .findByToolCallId(PROJECT_ID, result.getToolCallId())
                .orElseThrow();
        assertEquals(result.getToolCallId(), reopened.toolCallId());
        assertEquals(AuditStatus.SUCCESS, reopened.status());
        assertTrue(reopened.sanitizedSummary().contains("visible"));
        assertFalse(reopened.sanitizedSummary().contains("raw-password"));
        assertFalse(reopened.sanitizedSummary().contains("raw-token"));
        assertTrue(new JdbcToolAuditRepository(dataSource())
                .findByToolCallId(PROJECT_ID + 1, result.getToolCallId()).isEmpty());
    }

    @Test
    void repositoryRoundTripsEveryExistingTerminalAuditStatus() {
        JdbcToolAuditRepository writer = new JdbcToolAuditRepository(dataSource());
        for (AuditStatus status : AuditStatus.values()) {
            Audit.AuditEvent expected = new Audit.AuditEvent(
                    UUID.randomUUID().toString(),
                    PROJECT_ID,
                    "safe.read",
                    status,
                    status == AuditStatus.SUCCESS ? "NONE" : "TEST_" + status.name(),
                    "[REDACTED]",
                    123L,
                    null);
            writer.save(expected);

            assertEquals(expected, new JdbcToolAuditRepository(dataSource())
                    .findByToolCallId(PROJECT_ID, expected.toolCallId())
                    .orElseThrow());
        }
    }

    private static DataSource dataSource() {
        MysqlDataSource dataSource = new MysqlDataSource();
        dataSource.setUrl(MYSQL.getJdbcUrl());
        dataSource.setUser(MYSQL.getUsername());
        dataSource.setPassword(MYSQL.getPassword());
        return dataSource;
    }
}
