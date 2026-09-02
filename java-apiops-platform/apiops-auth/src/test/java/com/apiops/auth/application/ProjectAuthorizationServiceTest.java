package com.apiops.auth.application;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.repository.ProjectMembershipRepository;
import org.junit.jupiter.api.Test;
import org.springframework.security.access.AccessDeniedException;

import java.util.Map;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertDoesNotThrow;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

class ProjectAuthorizationServiceTest {

    private static final long USER_ID = 101L;
    private static final long PROJECT_ONE = 1L;
    private static final long PROJECT_TWO = 2L;

    @Test
    void ownerCanReadEditAndOwnProject() {
        ProjectAuthorizationService service = serviceWith(
                Map.of(key(USER_ID, PROJECT_ONE), ProjectRole.OWNER)
        );

        assertEquals(Optional.of(ProjectRole.OWNER),
                service.findProjectRole(USER_ID, PROJECT_ONE));
        assertDoesNotThrow(() -> service.requireProjectReadable(USER_ID, PROJECT_ONE));
        assertDoesNotThrow(() -> service.requireProjectEditable(USER_ID, PROJECT_ONE));
        assertDoesNotThrow(() -> service.requireProjectOwner(USER_ID, PROJECT_ONE));
    }

    @Test
    void editorCanReadAndEditButCannotOwnProject() {
        ProjectAuthorizationService service = serviceWith(
                Map.of(key(USER_ID, PROJECT_ONE), ProjectRole.EDITOR)
        );

        assertDoesNotThrow(() -> service.requireProjectReadable(USER_ID, PROJECT_ONE));
        assertDoesNotThrow(() -> service.requireProjectEditable(USER_ID, PROJECT_ONE));
        assertThrows(AccessDeniedException.class,
                () -> service.requireProjectOwner(USER_ID, PROJECT_ONE));
    }

    @Test
    void viewerCanReadButCannotEditOrOwnProject() {
        ProjectAuthorizationService service = serviceWith(
                Map.of(key(USER_ID, PROJECT_ONE), ProjectRole.VIEWER)
        );

        assertDoesNotThrow(() -> service.requireProjectReadable(USER_ID, PROJECT_ONE));
        assertThrows(AccessDeniedException.class,
                () -> service.requireProjectEditable(USER_ID, PROJECT_ONE));
        assertThrows(AccessDeniedException.class,
                () -> service.requireProjectOwner(USER_ID, PROJECT_ONE));
    }

    @Test
    void nonMemberIsDeniedWithoutBecomingAnInternalServerError() {
        ProjectAuthorizationService service = serviceWith(Map.of());

        assertEquals(Optional.empty(), service.findProjectRole(USER_ID, PROJECT_ONE));
        assertThrows(AccessDeniedException.class,
                () -> service.requireProjectReadable(USER_ID, PROJECT_ONE));
        assertThrows(AccessDeniedException.class,
                () -> service.requireProjectEditable(USER_ID, PROJECT_ONE));
        assertThrows(AccessDeniedException.class,
                () -> service.requireProjectOwner(USER_ID, PROJECT_ONE));
    }

    @Test
    void membershipRoleIsScopedToProjectId() {
        ProjectAuthorizationService service = serviceWith(
                Map.of(
                        key(USER_ID, PROJECT_ONE), ProjectRole.OWNER,
                        key(USER_ID, PROJECT_TWO), ProjectRole.VIEWER
                )
        );

        assertEquals(Optional.of(ProjectRole.OWNER),
                service.findProjectRole(USER_ID, PROJECT_ONE));
        assertEquals(Optional.of(ProjectRole.VIEWER),
                service.findProjectRole(USER_ID, PROJECT_TWO));
        assertThrows(AccessDeniedException.class,
                () -> service.requireProjectOwner(USER_ID, PROJECT_TWO));
        assertThrows(AccessDeniedException.class,
                () -> service.requireProjectEditable(USER_ID, PROJECT_TWO));
    }

    private static ProjectAuthorizationService serviceWith(Map<String, ProjectRole> memberships) {
        ProjectMembershipRepository repository = (userId, projectId) ->
                Optional.ofNullable(memberships.get(key(userId, projectId)));
        return new ProjectAuthorizationService(repository);
    }

    private static String key(long userId, long projectId) {
        return userId + ":" + projectId;
    }
}
