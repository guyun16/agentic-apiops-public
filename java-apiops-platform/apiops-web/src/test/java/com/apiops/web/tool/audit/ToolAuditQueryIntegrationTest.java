package com.apiops.web.tool.audit;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.auth.repository.AuthUserRepository;
import com.apiops.auth.repository.GlobalRbacRepository;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.auth.security.ApiOpsUserDetailsService;
import com.apiops.tool.gateway.Audit;
import com.apiops.tool.gateway.AuditStatus;
import com.apiops.tool.gateway.audit.ToolAuditRepository;
import com.apiops.web.ApiOpsWebApplication;
import org.junit.jupiter.api.Test;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.security.core.authority.SimpleGrantedAuthority;
import org.springframework.security.core.userdetails.UserDetailsService;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import java.util.List;
import java.util.Optional;
import java.util.Set;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest(
        classes = ApiOpsWebApplication.class,
        properties = {
                "apiops.datasource.tool-gateway.url=jdbc:mysql://127.0.0.1:1/not-used",
                "apiops.datasource.tool-gateway.username=root"
        })
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Import(ToolAuditQueryIntegrationTest.FixtureConfiguration.class)
class ToolAuditQueryIntegrationTest {

    private static final long USER_ID = 7L;
    private static final long PROJECT_ID = 42L;
    private static final String USERNAME = "audit-reader";
    private static final String TOOL_CALL_ID = "java-tool-call-1";

    @org.springframework.beans.factory.annotation.Autowired
    private MockMvc mockMvc;

    @org.springframework.beans.factory.annotation.Autowired
    private JwtTokenService jwtTokenService;

    @Test
    void exactReadRequiresJwtAndReturnsProjectScopedAudit() throws Exception {
        String path = "/api/v1/projects/{projectId}/tool-calls/{toolCallId}/audit";

        mockMvc.perform(get(path, PROJECT_ID, TOOL_CALL_ID))
                .andExpect(status().isUnauthorized());

        mockMvc.perform(get(path, PROJECT_ID, TOOL_CALL_ID)
                        .header("Authorization", bearerToken()))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.toolCallId").value(TOOL_CALL_ID))
                .andExpect(jsonPath("$.projectId").value(PROJECT_ID))
                .andExpect(jsonPath("$.toolName").value("rag.search"))
                .andExpect(jsonPath("$.status").value("SAFETY_VIOLATION"))
                .andExpect(jsonPath("$.violationCode").value("RESOURCE_GUARD_REJECTED"))
                .andExpect(jsonPath("$.sanitizedSummary").value("[REDACTED]"));
    }

    @Test
    void authenticatedUserCannotQueryAnotherProject() throws Exception {
        mockMvc.perform(get(
                        "/api/v1/projects/{projectId}/tool-calls/{toolCallId}/audit",
                        PROJECT_ID + 1,
                        TOOL_CALL_ID)
                        .header("Authorization", bearerToken()))
                .andExpect(status().isForbidden());
    }

    private String bearerToken() {
        return "Bearer " + jwtTokenService.generateAccessToken(new ApiOpsPrincipal(
                USER_ID,
                USERNAME,
                "test-password-hash",
                true,
                List.of(new SimpleGrantedAuthority("TOOL_READ"))));
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class FixtureConfiguration {

        @Bean
        @Primary
        ToolAuditRepository toolAuditFixture() {
            Audit.AuditEvent event = new Audit.AuditEvent(
                    TOOL_CALL_ID,
                    PROJECT_ID,
                    "rag.search",
                    AuditStatus.SAFETY_VIOLATION,
                    "RESOURCE_GUARD_REJECTED",
                    "[REDACTED]",
                    123L,
                    null);
            return new ToolAuditRepository() {
                @Override
                public void save(Audit.AuditEvent ignored) {
                }

                @Override
                public Optional<Audit.AuditEvent> findByToolCallId(
                        long projectId,
                        String toolCallId
                ) {
                    return projectId == PROJECT_ID && TOOL_CALL_ID.equals(toolCallId)
                            ? Optional.of(event) : Optional.empty();
                }
            };
        }

        @Bean
        @Primary
        AuthUserRepository auditAuthUserRepository() {
            ApiOpsPrincipal principal = new ApiOpsPrincipal(
                    USER_ID, USERNAME, "test-password-hash", true, List.of());
            return username -> USERNAME.equals(username)
                    ? Optional.of(principal) : Optional.empty();
        }

        @Bean
        @Primary
        UserDetailsService auditUserDetailsService(AuthUserRepository repository) {
            return new ApiOpsUserDetailsService(repository);
        }

        @Bean
        @Primary
        GlobalRbacRepository auditGlobalRbacRepository() {
            return new GlobalRbacRepository() {
                @Override
                public Set<String> findRoleCodesByUserId(long userId) {
                    return Set.of();
                }

                @Override
                public Set<String> findPermissionCodesByUserId(long userId) {
                    return Set.of("TOOL_READ");
                }
            };
        }

        @Bean
        @Primary
        ProjectMembershipRepository auditProjectMembershipRepository() {
            return (userId, projectId) -> userId == USER_ID && projectId == PROJECT_ID
                    ? Optional.of(ProjectRole.VIEWER) : Optional.empty();
        }
    }
}
