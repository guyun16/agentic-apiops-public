package com.apiops.auth.application;

import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.repository.ProjectMembershipRepository;
import org.springframework.security.access.AccessDeniedException;

import java.util.Objects;
import java.util.Optional;
import java.util.function.Predicate;

/** Centralizes project membership authorization without global-role bypasses. */
public final class ProjectAuthorizationService {

    private final ProjectMembershipRepository membershipRepository;

    public ProjectAuthorizationService(ProjectMembershipRepository membershipRepository) {
        this.membershipRepository = Objects.requireNonNull(
                membershipRepository,
                "membershipRepository must not be null"
        );
    }

    public Optional<ProjectRole> findProjectRole(long userId, long projectId) {
        return membershipRepository.findProjectRole(userId, projectId);
    }

    public void requireProjectReadable(long userId, long projectId) {
        requireRole(userId, projectId, role -> true);
    }

    public void requireProjectEditable(long userId, long projectId) {
        requireRole(
                userId,
                projectId,
                role -> role == ProjectRole.OWNER || role == ProjectRole.EDITOR
        );
    }

    public void requireProjectOwner(long userId, long projectId) {
        requireRole(userId, projectId, role -> role == ProjectRole.OWNER);
    }

    private void requireRole(
            long userId,
            long projectId,
            Predicate<ProjectRole> predicate
    ) {
        findProjectRole(userId, projectId)
                .filter(predicate)
                .orElseThrow(() -> new AccessDeniedException("Project access denied"));
    }
}
