package com.apiops.web.runner.progress;

import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

public class SseEmitterRegistry {
    private final ConcurrentHashMap<String, Set<SseEmitter>> emitters=new ConcurrentHashMap<>();

    public SseEmitter register(long projectId,long runId,long timeout) {
        SseEmitter emitter=new SseEmitter(timeout); String key=key(projectId,runId);
        emitters.computeIfAbsent(key,ignored->ConcurrentHashMap.newKeySet()).add(emitter);
        Runnable cleanup=()->remove(key,emitter);
        emitter.onCompletion(cleanup); emitter.onTimeout(cleanup); emitter.onError(error->cleanup.run());
        return emitter;
    }
    public Set<SseEmitter> subscribers(long projectId,long runId) {
        return Set.copyOf(emitters.getOrDefault(key(projectId,runId),Set.of()));
    }
    public void remove(long projectId,long runId,SseEmitter emitter){remove(key(projectId,runId),emitter);}
    public int size(long projectId,long runId){return subscribers(projectId,runId).size();}
    private void remove(String key,SseEmitter emitter){emitters.computeIfPresent(key,(k,set)->{set.remove(emitter);return set.isEmpty()?null:set;});}
    private static String key(long p,long r){return p+":"+r;}
}
