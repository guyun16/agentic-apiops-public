package com.apiops.web.runner.progress;

import com.apiops.runner.progress.TaskProgressListener;
import com.apiops.runner.progress.TaskProgressQueryService;
import com.apiops.runner.progress.TaskProgressSnapshot;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import java.io.IOException;
import java.util.Objects;

public final class TaskProgressSseService implements TaskProgressListener {
    private final TaskProgressQueryService query;
    private final SseEmitterRegistry registry;
    private final long timeout;
    public TaskProgressSseService(TaskProgressQueryService query,SseEmitterRegistry registry,long timeout){
        this.query=Objects.requireNonNull(query);this.registry=Objects.requireNonNull(registry);this.timeout=timeout;
    }
    public SseEmitter connect(long projectId,long runId){
        TaskProgressSnapshot snapshot=query.find(projectId,runId)
                .orElseThrow(()->new IllegalArgumentException("Test run not found: "+runId));
        SseEmitter emitter=registry.register(projectId,runId,timeout);
        if(!send(emitter,"current",snapshot)) return emitter;
        if(snapshot.status().isTerminal()) completeAfterTerminal(projectId,runId,emitter,snapshot);
        return emitter;
    }
    public void progress(TaskProgressSnapshot snapshot){broadcast("progress",snapshot);}
    public void terminal(TaskProgressSnapshot snapshot){
        for(SseEmitter emitter:registry.subscribers(snapshot.projectId(),snapshot.runId()))
            completeAfterTerminal(snapshot.projectId(),snapshot.runId(),emitter,snapshot);
    }
    private void broadcast(String name,TaskProgressSnapshot snapshot){
        for(SseEmitter emitter:registry.subscribers(snapshot.projectId(),snapshot.runId()))
            if(!send(emitter,name,snapshot)) registry.remove(snapshot.projectId(),snapshot.runId(),emitter);
    }
    private boolean send(SseEmitter emitter,String name,TaskProgressSnapshot snapshot){
        try{emitter.send(SseEmitter.event().name(name).data(snapshot));return true;}
        catch(IOException|RuntimeException failure){emitter.completeWithError(failure);return false;}
    }
    private void completeAfterTerminal(long projectId,long runId,SseEmitter emitter,
            TaskProgressSnapshot snapshot){
        if(send(emitter,"terminal",snapshot)) emitter.complete();
        registry.remove(projectId,runId,emitter);
    }
}
