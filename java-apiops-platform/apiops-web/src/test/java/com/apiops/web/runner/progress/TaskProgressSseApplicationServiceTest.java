package com.apiops.web.runner.progress;

import com.apiops.auth.application.ProjectAuthorizationService;
import com.apiops.auth.enums.ProjectRole;
import com.apiops.auth.security.ApiOpsPrincipal;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class TaskProgressSseApplicationServiceTest {
    @AfterEach void clear(){SecurityContextHolder.clearContext();}
    @Test void memberCanConnectButOtherProjectIsDenied(){
        ProjectAuthorizationService auth=new ProjectAuthorizationService((user,project)->
                project==101?Optional.of(ProjectRole.VIEWER):Optional.empty());
        TaskProgressSseService sse=mock(TaskProgressSseService.class);
        when(sse.connect(101,301)).thenReturn(new SseEmitter());
        TaskProgressSseApplicationService service=new TaskProgressSseApplicationService(auth,sse);
        ApiOpsPrincipal principal=new ApiOpsPrincipal(7L,"user","hash",true,List.of());
        SecurityContextHolder.getContext().setAuthentication(
                UsernamePasswordAuthenticationToken.authenticated(principal,null,List.of()));
        assertNotNull(service.connect(101,301));
        assertThrows(AccessDeniedException.class,()->service.connect(202,301));
        verify(sse,never()).connect(202,301);
    }
}
