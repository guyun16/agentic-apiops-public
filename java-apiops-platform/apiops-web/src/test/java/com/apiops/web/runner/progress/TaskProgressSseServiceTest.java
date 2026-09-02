package com.apiops.web.runner.progress;

import com.apiops.runner.progress.TaskProgressQueryService;
import com.apiops.runner.progress.TaskProgressSnapshot;
import com.apiops.runner.progress.TaskProgressStore;
import com.apiops.runner.persistence.ExecutionFactRepository;
import com.apiops.runner.state.RunStatus;
import org.junit.jupiter.api.Test;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;

class TaskProgressSseServiceTest {
    @Test void connectSendsCurrentProgressTerminalAndReconnectGetsLatest() throws Exception {
        TaskProgressStore store=mock(TaskProgressStore.class);
        ExecutionFactRepository repository=mock(ExecutionFactRepository.class);
        TaskProgressSnapshot running=snapshot(RunStatus.RUNNING,0,1);
        when(store.find(101,301)).thenReturn(Optional.of(running));
        SseEmitterRegistry registry=new SseEmitterRegistry();
        TaskProgressSseService service=new TaskProgressSseService(
                new TaskProgressQueryService(store,repository),registry,60_000);
        SseEmitter first=service.connect(101,301);
        assertEquals(1,registry.size(101,301));
        TaskProgressSnapshot completed=snapshot(RunStatus.SUCCESS,1,0);
        service.progress(completed); service.terminal(completed);
        assertEquals(0,registry.size(101,301));
        when(store.find(101,301)).thenReturn(Optional.of(completed));
        SseEmitter second=service.connect(101,301);
        assertEquals(0,registry.size(101,301));
        registry.remove(101,301,first); registry.remove(101,301,second);
        assertEquals(0,registry.size(101,301));
    }

    @Test void timeoutErrorAndSendFailureCleanRegistry() throws Exception {
        assertLifecycleCallbackCleansRegistry(Lifecycle.COMPLETION);
        assertLifecycleCallbackCleansRegistry(Lifecycle.TIMEOUT);
        assertLifecycleCallbackCleansRegistry(Lifecycle.ERROR);
        SseEmitter broken=mock(SseEmitter.class);
        doThrow(new IllegalStateException("disconnect")).when(broken).send(any(SseEmitter.SseEventBuilder.class));
        RegistryWithEmitter custom=new RegistryWithEmitter(broken);
        TaskProgressStore store=mock(TaskProgressStore.class);
        ExecutionFactRepository repository=mock(ExecutionFactRepository.class);
        when(store.find(101,301)).thenReturn(Optional.of(snapshot(RunStatus.RUNNING,0,1)));
        TaskProgressSseService service=new TaskProgressSseService(new TaskProgressQueryService(store,repository),custom,1000);
        service.connect(101,301);
        verify(broken).completeWithError(any());
    }

    private void assertLifecycleCallbackCleansRegistry(Lifecycle lifecycle) {
        try (var construction=mockConstruction(SseEmitter.class)) {
            SseEmitterRegistry registry=new SseEmitterRegistry();
            registry.register(1,2,1000);
            SseEmitter emitter=construction.constructed().getFirst();
            assertEquals(1,registry.size(1,2));
            switch(lifecycle) {
                case COMPLETION -> {
                    var callback=org.mockito.ArgumentCaptor.forClass(Runnable.class);
                    verify(emitter).onCompletion(callback.capture()); callback.getValue().run();
                }
                case TIMEOUT -> {
                    var callback=org.mockito.ArgumentCaptor.forClass(Runnable.class);
                    verify(emitter).onTimeout(callback.capture()); callback.getValue().run();
                }
                case ERROR -> {
                    @SuppressWarnings("unchecked")
                    var callback=org.mockito.ArgumentCaptor.forClass(java.util.function.Consumer.class);
                    verify(emitter).onError(callback.capture()); callback.getValue().accept(new IOException("disconnect"));
                }
            }
            assertEquals(0,registry.size(1,2));
        }
    }

    @Test void redisFailureFallsBackToAuthoritativeFacts() {
        TaskProgressStore store=mock(TaskProgressStore.class);
        when(store.find(101,301)).thenThrow(new IllegalStateException("redis down"));
        ExecutionFactRepository repository=mock(ExecutionFactRepository.class);
        when(repository.findRun(101,301)).thenReturn(Optional.of(new ExecutionFactRepository.RunExecutionFacts(
                101,201,301,"case","api","task",RunStatus.SUCCESS,
                com.apiops.common.enums.FailureType.NONE,Instant.EPOCH,Instant.EPOCH.plusSeconds(1),List.of())));
        TaskProgressSnapshot fallback=new TaskProgressQueryService(store,repository).find(101,301).orElseThrow();
        assertEquals(RunStatus.SUCCESS,fallback.status()); assertEquals(1,fallback.completed());
    }

    private static TaskProgressSnapshot snapshot(RunStatus status,int completed,int running){return new TaskProgressSnapshot(
            101,201,301,1,completed,running,status==RunStatus.SUCCESS?1:0,0,0,0,0,status,Instant.EPOCH);}

    private enum Lifecycle { COMPLETION, TIMEOUT, ERROR }

    private static final class RegistryWithEmitter extends SseEmitterRegistry {
        private final SseEmitter emitter;
        RegistryWithEmitter(SseEmitter emitter){this.emitter=emitter;}
        @Override public SseEmitter register(long p,long r,long timeout){return emitter;}
        @Override public java.util.Set<SseEmitter> subscribers(long p,long r){return java.util.Set.of(emitter);}
    }
}
