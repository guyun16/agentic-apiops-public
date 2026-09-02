package com.apiops.web.project;

import com.apiops.auth.jwt.JwtTokenService;
import com.apiops.auth.repository.AuthUserRepository;
import com.apiops.auth.repository.GlobalRbacRepository;
import com.apiops.auth.repository.ProjectMembershipRepository;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.web.project.domain.AccessibleProject;
import com.apiops.web.project.domain.Project;
import com.apiops.web.project.domain.ProjectMember;
import com.apiops.web.project.repository.ProjectRepository;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.context.annotation.Primary;
import org.springframework.test.context.ActiveProfiles;
import org.springframework.test.web.servlet.MockMvc;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.Set;
import java.util.concurrent.atomic.AtomicLong;

import static org.hamcrest.Matchers.containsString;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.springframework.http.MediaType.APPLICATION_JSON;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.put;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@SpringBootTest
@AutoConfigureMockMvc
@ActiveProfiles("test")
@Import(ProjectApiIntegrationTest.ProjectApiTestConfiguration.class)
class ProjectApiIntegrationTest {

    private static final String OWNER = "project-owner";
    private static final String EDITOR = "project-editor";
    private static final String VIEWER = "project-viewer";
    private static final String OUTSIDER = "project-outsider";
    private static final String PLATFORM_USER = "project-platform-user";
    private static final long OWNER_ID = 101L;
    private static final long EDITOR_ID = 102L;
    private static final long VIEWER_ID = 103L;
    private static final long OUTSIDER_ID = 104L;
    private static final long PLATFORM_USER_ID = 105L;

    @Autowired
    private MockMvc mockMvc;

    @Autowired
    private JwtTokenService jwtTokenService;

    @Autowired
    private ObjectMapper objectMapper;

    @Autowired
    private TestProjectStore projectStore;

    @BeforeEach
    void clearStore() {
        projectStore.clear();
    }

    @AfterEach
    void clearSecurityContext() {
        org.springframework.security.core.context.SecurityContextHolder.clearContext();
    }

    @Test
    void ownerCanReadEditAndManageMembers() throws Exception {
        long projectId = createProjectAsOwner();

        mockMvc.perform(get("/api/v1/projects/{projectId}", projectId)
                        .header("Authorization", bearerToken(OWNER)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.ownerUserId").value(OWNER_ID));

        mockMvc.perform(put("/api/v1/projects/{projectId}", projectId)
                        .header("Authorization", bearerToken(OWNER))
                        .contentType(APPLICATION_JSON)
                        .content("{\"projectName\":\"renamed\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.projectName").value("renamed"));

        mockMvc.perform(post("/api/v1/projects/{projectId}/members", projectId)
                        .header("Authorization", bearerToken(OWNER))
                        .contentType(APPLICATION_JSON)
                        .content("{\"userId\":102,\"projectRole\":\"EDITOR\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.projectRole").value("EDITOR"));

        assertEquals(Optional.of(ProjectRole.EDITOR),
                projectStore.findProjectRole(EDITOR_ID, projectId));
    }

    @Test
    void editorCanEditButCannotManageMembers() throws Exception {
        long projectId = createProjectWithEditorAndViewer();

        mockMvc.perform(put("/api/v1/projects/{projectId}", projectId)
                        .header("Authorization", bearerToken(EDITOR))
                        .contentType(APPLICATION_JSON)
                        .content("{\"projectName\":\"editor-update\"}"))
                .andExpect(status().isOk());

        mockMvc.perform(post("/api/v1/projects/{projectId}/members", projectId)
                        .header("Authorization", bearerToken(EDITOR))
                        .contentType(APPLICATION_JSON)
                        .content("{\"userId\":104,\"projectRole\":\"VIEWER\"}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value("A0005"));
    }

    @Test
    void viewerCanReadButCannotEdit() throws Exception {
        long projectId = createProjectWithEditorAndViewer();

        mockMvc.perform(get("/api/v1/projects/{projectId}", projectId)
                        .header("Authorization", bearerToken(VIEWER)))
                .andExpect(status().isOk());

        mockMvc.perform(put("/api/v1/projects/{projectId}", projectId)
                        .header("Authorization", bearerToken(VIEWER))
                        .contentType(APPLICATION_JSON)
                        .content("{\"projectName\":\"viewer-update\"}"))
                .andExpect(status().isForbidden())
                .andExpect(jsonPath("$.code").value("A0005"));
    }

    @Test
    void nonMemberCannotReadAnotherProject() throws Exception {
        long projectId = createProjectAsOwner();

        mockMvc.perform(get("/api/v1/projects/{projectId}", projectId)
                        .header("Authorization", bearerToken(OUTSIDER)))
                .andExpect(status().isForbidden())
                .andExpect(content().contentTypeCompatibleWith(APPLICATION_JSON))
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("A0005"))
                .andExpect(jsonPath("$.data").value((Object) null));
    }

    @Test
    void missingTokenReturns401ForProjectApi() throws Exception {
        mockMvc.perform(get("/api/v1/projects/{projectId}", 999L))
                .andExpect(status().isUnauthorized())
                .andExpect(content().contentTypeCompatibleWith(APPLICATION_JSON))
                .andExpect(jsonPath("$.code").value("A0004"));
    }

    @Test
    void currentPrincipalReturnsAuthenticatedIdentityOnly() throws Exception {
        mockMvc.perform(get("/api/v1/auth/me")
                        .header("Authorization", bearerToken(OWNER)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.userId").value(OWNER_ID))
                .andExpect(jsonPath("$.data.username").value(OWNER))
                .andExpect(jsonPath("$.data.accessToken").doesNotExist())
                .andExpect(jsonPath("$.data.projectRole").doesNotExist());
    }

    @Test
    void accessibleProjectsReturnMembershipRolesAndEmptyForNonMember() throws Exception {
        long firstProjectId = createProjectAsOwner();
        long secondProjectId = createProjectAsOwner();
        addMember(firstProjectId, EDITOR_ID, ProjectRole.EDITOR);
        addMember(secondProjectId, EDITOR_ID, ProjectRole.VIEWER);

        mockMvc.perform(get("/api/v1/projects")
                        .header("Authorization", bearerToken(EDITOR)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.length()").value(2))
                .andExpect(jsonPath("$.data[0].projectId").value((int) firstProjectId))
                .andExpect(jsonPath("$.data[0].projectRole").value("EDITOR"))
                .andExpect(jsonPath("$.data[1].projectId").value((int) secondProjectId))
                .andExpect(jsonPath("$.data[1].projectRole").value("VIEWER"));

        mockMvc.perform(get("/api/v1/projects")
                        .header("Authorization", bearerToken(OUTSIDER)))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data").isEmpty());
    }

    @Test
    void projectCreationCreatesOwnerMembershipFromAuthenticatedPrincipal() throws Exception {
        long projectId = createProjectAsOwner();

        assertEquals(Optional.of(ProjectRole.OWNER),
                projectStore.findProjectRole(OWNER_ID, projectId));
        assertEquals(1, projectStore.projectCount());
    }

    @Test
    void platformUserPermissionCanCreateProjectWithoutRequestUserId() throws Exception {
        String response = mockMvc.perform(post("/api/v1/projects")
                        .header("Authorization", bearerToken(PLATFORM_USER))
                        .contentType(APPLICATION_JSON)
                        .content("{\"projectKey\":\"platform-user-key\",\"projectName\":\"Platform User Project\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.ownerUserId").value(PLATFORM_USER_ID))
                .andReturn()
                .getResponse()
                .getContentAsString();

        long projectId = objectMapper.readTree(response).path("data").path("id").asLong();
        assertEquals(Optional.of(ProjectRole.OWNER),
                projectStore.findProjectRole(PLATFORM_USER_ID, projectId));
    }

    @Test
    void ownerMembershipFailureDoesNotLeaveProjectBehind() throws Exception {
        projectStore.failOwnerMembershipInsertion(true);

        mockMvc.perform(post("/api/v1/projects")
                        .header("Authorization", bearerToken(OWNER))
                        .contentType(APPLICATION_JSON)
                        .content("{\"projectKey\":\"rollback-key\",\"projectName\":\"rollback\"}"))
                .andExpect(status().isInternalServerError())
                .andExpect(jsonPath("$.code").value("S0001"))
                .andExpect(content().string(containsString("system error")));

        assertEquals(0, projectStore.projectCount());
    }

    private long createProjectAsOwner() throws Exception {
        String response = mockMvc.perform(post("/api/v1/projects")
                        .header("Authorization", bearerToken(OWNER))
                        .contentType(APPLICATION_JSON)
                        .content("{\"projectKey\":\"project-key\",\"projectName\":\"Project One\"}"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.data.ownerUserId").value(OWNER_ID))
                .andReturn()
                .getResponse()
                .getContentAsString();
        JsonNode root = objectMapper.readTree(response);
        assertTrue(root.path("success").asBoolean());
        return root.path("data").path("id").asLong();
    }

    private long createProjectWithEditorAndViewer() throws Exception {
        long projectId = createProjectAsOwner();
        addMember(projectId, EDITOR_ID, ProjectRole.EDITOR);
        addMember(projectId, VIEWER_ID, ProjectRole.VIEWER);
        return projectId;
    }

    private void addMember(long projectId, long userId, ProjectRole role) throws Exception {
        mockMvc.perform(post("/api/v1/projects/{projectId}/members", projectId)
                        .header("Authorization", bearerToken(OWNER))
                        .contentType(APPLICATION_JSON)
                        .content("{\"userId\":" + userId
                                + ",\"projectRole\":\"" + role.name() + "\"}"))
                .andExpect(status().isOk());
    }

    private String bearerToken(String username) {
        return "Bearer " + jwtTokenService.generateAccessToken(principal(username));
    }

    private ApiOpsPrincipal principal(String username) {
        long userId = switch (username) {
            case OWNER -> OWNER_ID;
            case EDITOR -> EDITOR_ID;
            case VIEWER -> VIEWER_ID;
            case OUTSIDER -> OUTSIDER_ID;
            case PLATFORM_USER -> PLATFORM_USER_ID;
            default -> throw new IllegalArgumentException("Unknown test user");
        };
        return new ApiOpsPrincipal(userId, username, "test-password-hash", true, List.of());
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class ProjectApiTestConfiguration {

        @Bean
        TestProjectStore testProjectStore() {
            return new TestProjectStore();
        }

        @Bean
        @Primary
        ProjectRepository testProjectRepository(TestProjectStore store) {
            return new ProjectRepository() {
                @Override
                public Project createProjectWithOwner(
                        String projectKey,
                        String projectName,
                        long ownerUserId
                ) {
                    return store.createProjectWithOwner(projectKey, projectName, ownerUserId);
                }

                @Override
                public Optional<Project> findById(long projectId) {
                    return store.findById(projectId);
                }

                @Override
                public List<AccessibleProject> findAccessibleProjectsByUserId(long userId) {
                    return store.findAccessibleProjectsByUserId(userId);
                }

                @Override
                public Optional<Project> updateProjectName(long projectId, String projectName) {
                    return store.updateProjectName(projectId, projectName);
                }

                @Override
                public ProjectMember addMember(
                        long projectId,
                        long userId,
                        ProjectRole projectRole
                ) {
                    return store.addMember(projectId, userId, projectRole);
                }
            };
        }

        @Bean
        @Primary
        ProjectMembershipRepository testProjectMembershipRepository(TestProjectStore store) {
            return store::findProjectRole;
        }

        @Bean
        @Primary
        AuthUserRepository testAuthUserRepository() {
            Map<String, ApiOpsPrincipal> principals = new LinkedHashMap<>();
            principals.put(OWNER, new ApiOpsPrincipal(
                    OWNER_ID, OWNER, "test-password-hash", true, List.of()));
            principals.put(EDITOR, new ApiOpsPrincipal(
                    EDITOR_ID, EDITOR, "test-password-hash", true, List.of()));
            principals.put(VIEWER, new ApiOpsPrincipal(
                    VIEWER_ID, VIEWER, "test-password-hash", true, List.of()));
            principals.put(OUTSIDER, new ApiOpsPrincipal(
                    OUTSIDER_ID, OUTSIDER, "test-password-hash", true, List.of()));
            principals.put(PLATFORM_USER, new ApiOpsPrincipal(
                    PLATFORM_USER_ID, PLATFORM_USER, "test-password-hash", true, List.of()));
            return username -> Optional.ofNullable(principals.get(username));
        }

        @Bean
        @Primary
        GlobalRbacRepository testGlobalRbacRepository() {
            return new GlobalRbacRepository() {
                @Override
                public Set<String> findRoleCodesByUserId(long userId) {
                    if (userId == OWNER_ID) {
                        return Set.of("PLATFORM_ADMIN");
                    }
                    if (userId == PLATFORM_USER_ID) {
                        return Set.of("PLATFORM_USER");
                    }
                    return Set.of();
                }

                @Override
                public Set<String> findPermissionCodesByUserId(long userId) {
                    return userId == OWNER_ID || userId == PLATFORM_USER_ID
                            ? Set.of("PLATFORM_PROJECT_CREATE", "PLATFORM_PROJECT_LIST")
                            : Set.of("PLATFORM_PROJECT_LIST");
                }
            };
        }
    }

    static final class TestProjectStore {

        private final AtomicLong ids = new AtomicLong(1000L);
        private final Map<Long, Project> projects = new LinkedHashMap<>();
        private final Map<String, ProjectMember> memberships = new LinkedHashMap<>();
        private boolean failOwnerMembershipInsertion;

        public synchronized Project createProjectWithOwner(
                String projectKey,
                String projectName,
                long ownerUserId
        ) {
            long projectId = ids.incrementAndGet();
            Instant now = Instant.parse("2026-08-07T00:00:00Z");
            Project project = new Project(
                    projectId,
                    projectKey,
                    projectName,
                    ownerUserId,
                    "ACTIVE",
                    now,
                    now
            );
            ProjectMember ownerMembership = new ProjectMember(
                    projectId,
                    ownerUserId,
                    ProjectRole.OWNER,
                    now
            );
            if (failOwnerMembershipInsertion) {
                throw new IllegalStateException("owner membership insert failed");
            }
            projects.put(projectId, project);
            memberships.put(key(projectId, ownerUserId), ownerMembership);
            return project;
        }

        public synchronized Optional<Project> findById(long projectId) {
            return Optional.ofNullable(projects.get(projectId));
        }

        public synchronized List<AccessibleProject> findAccessibleProjectsByUserId(long userId) {
            return memberships.values().stream()
                    .filter(member -> member.userId() == userId)
                    .map(member -> new AccessibleProject(
                            member.projectId(),
                            projects.get(member.projectId()).projectName(),
                            member.projectRole()))
                    .toList();
        }

        public synchronized Optional<Project> updateProjectName(
                long projectId,
                String projectName
        ) {
            Project current = projects.get(projectId);
            if (current == null) {
                return Optional.empty();
            }
            Project updated = new Project(
                    current.id(),
                    current.projectKey(),
                    projectName,
                    current.ownerUserId(),
                    current.status(),
                    current.createdAt(),
                    current.updatedAt()
            );
            projects.put(projectId, updated);
            return Optional.of(updated);
        }

        public synchronized ProjectMember addMember(
                long projectId,
                long userId,
                ProjectRole projectRole
        ) {
            if (!projects.containsKey(projectId)) {
                throw new IllegalStateException("project does not exist");
            }
            String key = key(projectId, userId);
            if (memberships.containsKey(key)) {
                throw new IllegalStateException("membership already exists");
            }
            ProjectMember member = new ProjectMember(
                    projectId,
                    userId,
                    projectRole,
                    Instant.parse("2026-08-07T00:00:00Z")
            );
            memberships.put(key, member);
            return member;
        }

        public synchronized Optional<ProjectRole> findProjectRole(long userId, long projectId) {
            return Optional.ofNullable(memberships.get(key(projectId, userId)))
                    .map(ProjectMember::projectRole);
        }

        synchronized void clear() {
            projects.clear();
            memberships.clear();
            ids.set(1000L);
            failOwnerMembershipInsertion = false;
        }

        synchronized int projectCount() {
            return projects.size();
        }

        synchronized void failOwnerMembershipInsertion(boolean fail) {
            failOwnerMembershipInsertion = fail;
        }

        private static String key(long projectId, long userId) {
            return projectId + ":" + userId;
        }
    }
}
