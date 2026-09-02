package com.apiops.web.runner.progress;

import com.apiops.runner.progress.TaskProgressSnapshot;
import com.apiops.runner.progress.TaskProgressStore;
import com.apiops.runner.state.RunStatus;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.Optional;

public final class RedisTaskProgressStore implements TaskProgressStore {
    private static final DefaultRedisScript<Long> CREATE = new DefaultRedisScript<>("""
            redis.call('HSET', KEYS[1], 'projectId', ARGV[1], 'taskId', ARGV[2],
              'runId', ARGV[3], 'total', ARGV[4], 'completed', 0, 'running', 0,
              'success', 0, 'assertionFailed', 0, 'executionFailed', 0,
              'timeout', 0, 'cancelled', 0, 'status', 'PENDING', 'updatedAt', ARGV[5])
            redis.call('PEXPIRE', KEYS[1], ARGV[6]); return 1
            """, Long.class);
    private static final DefaultRedisScript<Long> START = new DefaultRedisScript<>("""
            if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
            redis.call('HINCRBY', KEYS[1], 'running', 1)
            redis.call('HSET', KEYS[1], 'status', 'RUNNING', 'updatedAt', ARGV[1])
            redis.call('PEXPIRE', KEYS[1], ARGV[2]); return 1
            """, Long.class);
    private static final DefaultRedisScript<Long> COMPLETE = new DefaultRedisScript<>("""
            if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
            redis.call('HINCRBY', KEYS[1], 'completed', 1)
            local running=tonumber(redis.call('HGET', KEYS[1], 'running') or '0')
            if running > 0 then redis.call('HINCRBY', KEYS[1], 'running', -1) end
            redis.call('HINCRBY', KEYS[1], ARGV[1], 1)
            redis.call('HSET', KEYS[1], 'updatedAt', ARGV[2])
            redis.call('PEXPIRE', KEYS[1], ARGV[3]); return 1
            """, Long.class);
    private static final DefaultRedisScript<Long> TERMINAL = new DefaultRedisScript<>("""
            if redis.call('EXISTS', KEYS[1]) == 0 then return 0 end
            redis.call('HSET', KEYS[1], 'status', ARGV[1], 'running', 0, 'updatedAt', ARGV[2])
            redis.call('PEXPIRE', KEYS[1], ARGV[3]); return 1
            """, Long.class);

    private final StringRedisTemplate redis;
    private final Duration ttl;
    private final Clock clock;

    public RedisTaskProgressStore(StringRedisTemplate redis, Duration ttl) {
        this(redis, ttl, Clock.systemUTC());
    }
    RedisTaskProgressStore(StringRedisTemplate redis, Duration ttl, Clock clock) {
        if (ttl == null || ttl.isZero() || ttl.isNegative())
            throw new IllegalArgumentException("progress ttl must be positive");
        this.redis = java.util.Objects.requireNonNull(redis);
        this.ttl = ttl;
        this.clock = java.util.Objects.requireNonNull(clock);
    }

    public TaskProgressSnapshot create(long projectId, long taskId, long runId, int total) {
        String key=key(projectId,runId); Instant now=clock.instant();
        redis.execute(CREATE, List.of(key), Long.toString(projectId), Long.toString(taskId),
                Long.toString(runId), Integer.toString(total), now.toString(),
                Long.toString(ttl.toMillis()));
        return require(key);
    }
    public TaskProgressSnapshot caseStarted(long projectId,long runId) {
        String key=key(projectId,runId); executeRequired(START,key,clock.instant().toString(),
                Long.toString(ttl.toMillis())); return require(key);
    }
    public TaskProgressSnapshot caseCompleted(long projectId,long runId,RunStatus status) {
        String key=key(projectId,runId); executeRequired(COMPLETE,key,counter(status),
                clock.instant().toString(),Long.toString(ttl.toMillis())); return require(key);
    }
    public TaskProgressSnapshot terminal(long projectId,long runId,RunStatus status) {
        if (!status.isTerminal()) throw new IllegalArgumentException("terminal status required");
        String key=key(projectId,runId); executeRequired(TERMINAL,key,status.name(),
                clock.instant().toString(),Long.toString(ttl.toMillis())); return require(key);
    }
    public Optional<TaskProgressSnapshot> find(long projectId,long runId) {
        Map<Object,Object> values=redis.opsForHash().entries(key(projectId,runId));
        return values.isEmpty()?Optional.empty():Optional.of(map(values));
    }
    private void executeRequired(DefaultRedisScript<Long> script,String key,String... args) {
        Long result=redis.execute(script,List.of(key),(Object[])args);
        if (result==null||result==0) throw new IllegalStateException("progress key not found");
    }
    private TaskProgressSnapshot require(String key) {
        Map<Object,Object> values=redis.opsForHash().entries(key);
        if(values.isEmpty()) throw new IllegalStateException("progress key not found");
        return map(values);
    }
    private TaskProgressSnapshot map(Map<Object,Object> v) {
        return new TaskProgressSnapshot(l(v,"projectId"),l(v,"taskId"),l(v,"runId"),
                i(v,"total"),i(v,"completed"),i(v,"running"),i(v,"success"),
                i(v,"assertionFailed"),i(v,"executionFailed"),i(v,"timeout"),
                i(v,"cancelled"),RunStatus.valueOf(s(v,"status")),Instant.parse(s(v,"updatedAt")));
    }
    private static String counter(RunStatus s) { return switch(s) {
        case SUCCESS->"success"; case ASSERTION_FAILED->"assertionFailed";
        case EXECUTION_FAILED->"executionFailed"; case TIMEOUT->"timeout";
        case CANCELLED->"cancelled"; default->throw new IllegalArgumentException("terminal required");};}
    private static String key(long p,long r){return "apiops:runner:progress:"+p+":"+r;}
    private static String s(Map<Object,Object> v,String k){return String.valueOf(v.get(k));}
    private static int i(Map<Object,Object> v,String k){return Integer.parseInt(s(v,k));}
    private static long l(Map<Object,Object> v,String k){return Long.parseLong(s(v,k));}
}
