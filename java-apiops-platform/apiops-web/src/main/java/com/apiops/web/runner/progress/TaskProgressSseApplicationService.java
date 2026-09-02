package com.apiops.web.runner.progress;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.security.ApiOpsPrincipal;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.access.prepost.PreAuthorize;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import java.util.Objects;

public class TaskProgressSseApplicationService {
    private final ProjectAuthorizationService authorization;
    private final TaskProgressSseService sse;
    public TaskProgressSseApplicationService(ProjectAuthorizationService authorization,TaskProgressSseService sse){
        this.authorization=Objects.requireNonNull(authorization);this.sse=Objects.requireNonNull(sse);}
    @PreAuthorize("isAuthenticated()")
    public SseEmitter connect(long projectId,long runId){
        Object principal=SecurityContextHolder.getContext().getAuthentication().getPrincipal();
        if(!(principal instanceof ApiOpsPrincipal user)) throw new AccessDeniedException("Authenticated ApiOpsPrincipal required");
        authorization.requireProjectReadable(user.getUserId(),projectId);
        return sse.connect(projectId,runId);
    }
}
