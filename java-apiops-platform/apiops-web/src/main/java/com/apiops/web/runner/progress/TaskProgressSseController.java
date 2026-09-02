package com.apiops.web.runner.progress;

import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import java.util.Objects;

@RestController
@ConditionalOnBean(TaskProgressSseApplicationService.class)
@RequestMapping("/api/v1/projects/{projectId}/test-runs")
public final class TaskProgressSseController {
    private final TaskProgressSseApplicationService service;
    public TaskProgressSseController(TaskProgressSseApplicationService service){this.service=Objects.requireNonNull(service);}
    @GetMapping(value="/{runId}/progress/events",produces=MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter events(@PathVariable long projectId,@PathVariable long runId){return service.connect(projectId,runId);}
}
