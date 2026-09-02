package com.apiops.web.project.application;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.common.enums.ErrorCode;
import com.apiops.common.exception.BusinessException;
import com.apiops.web.project.domain.AccessibleProject;
import com.apiops.web.project.domain.Project;
import com.apiops.web.project.domain.ProjectMember;
import com.apiops.web.project.dto.AddProjectMemberRequest;
import com.apiops.web.project.dto.CreateProjectRequest;
import com.apiops.web.project.dto.UpdateProjectRequest;
import com.apiops.web.project.exception.ProjectNotFoundException;
import com.apiops.web.project.repository.ProjectRepository;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.Authentication;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.stereotype.Service;

import java.util.List;

/** Application boundary for project operations and project-scoped authorization. */
@Service
public class ProjectApplicationService {

    private final ProjectRepository projectRepository;
    private final ProjectAuthorizationService projectAuthorizationService;

    public ProjectApplicationService(
            ProjectRepository projectRepository,
            ProjectAuthorizationService projectAuthorizationService
    ) {
        this.projectRepository = projectRepository;
        this.projectAuthorizationService = projectAuthorizationService;
    }

    @PreAuthorize("hasAuthority('PLATFORM_PROJECT_CREATE')")
    public Project createProject(CreateProjectRequest request) {
        requireText(request.projectKey(), "projectKey");
        requireText(request.projectName(), "projectName");
        ApiOpsPrincipal principal = currentPrincipal();
        return projectRepository.createProjectWithOwner(
                request.projectKey().trim(),
                request.projectName().trim(),
                principal.getUserId()
        );
    }

    @PreAuthorize("isAuthenticated()")
    public Project getProject(long projectId) {
        long userId = currentPrincipal().getUserId();
        projectAuthorizationService.requireProjectReadable(userId, projectId);
        return projectRepository.findById(projectId)
                .orElseThrow(() -> new ProjectNotFoundException(projectId));
    }

    @PreAuthorize("isAuthenticated()")
    public List<AccessibleProject> listAccessibleProjects() {
        return projectRepository.findAccessibleProjectsByUserId(currentPrincipal().getUserId());
    }

    @PreAuthorize("isAuthenticated()")
    public Project updateProject(long projectId, UpdateProjectRequest request) {
        requireText(request.projectName(), "projectName");
        long userId = currentPrincipal().getUserId();
        projectAuthorizationService.requireProjectEditable(userId, projectId);
        return projectRepository.updateProjectName(projectId, request.projectName().trim())
                .orElseThrow(() -> new ProjectNotFoundException(projectId));
    }

    @PreAuthorize("isAuthenticated()")
    public ProjectMember addMember(long projectId, AddProjectMemberRequest request) {
        if (request.userId() <= 0 || request.projectRole() == null) {
            throw new BusinessException(ErrorCode.PARAM_INVALID, "member request invalid");
        }
        long userId = currentPrincipal().getUserId();
        projectAuthorizationService.requireProjectOwner(userId, projectId);
        return projectRepository.addMember(
                projectId,
                request.userId(),
                request.projectRole()
        );
    }

    private ApiOpsPrincipal currentPrincipal() {
        Authentication authentication = SecurityContextHolder.getContext().getAuthentication();
        if (authentication == null
                || !authentication.isAuthenticated()
                || !(authentication.getPrincipal() instanceof ApiOpsPrincipal principal)) {
            throw new AccessDeniedException("Authenticated ApiOpsPrincipal required");
        }
        return principal;
    }

    private void requireText(String value, String fieldName) {
        if (value == null || value.isBlank()) {
            throw new BusinessException(ErrorCode.PARAM_INVALID, fieldName + " must not be blank");
        }
    }
}
