package com.apiops.web.runner.progress;

import com.apiops.runner.progress.TaskProgressSnapshot;
import com.apiops.runner.state.RunStatus;
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.GenericContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;

import static org.junit.jupiter.api.Assertions.*;

@Testcontainers(disabledWithoutDocker = true)
class RedisTaskProgressStoreIntegrationTest {
    @Container
    private static final GenericContainer<?> REDIS = new GenericContainer<>("redis:7-alpine")
            .withExposedPorts(6379);

    @Test void realRedisHashLuaConcurrencyTtlAndTerminalSnapshot() throws Exception {
        String host=REDIS.getHost();
        int port=REDIS.getMappedPort(6379);
        LettuceConnectionFactory factory=new LettuceConnectionFactory(
                new RedisStandaloneConfiguration(host,port));
        factory.afterPropertiesSet(); factory.start();
        StringRedisTemplate redis=new StringRedisTemplate(factory); redis.afterPropertiesSet();
        assertEquals("PONG",redis.getConnectionFactory().getConnection().ping());
        long projectId=900_000+Math.abs(UUID.randomUUID().getLeastSignificantBits()%10_000);
        long runId=800_000+Math.abs(UUID.randomUUID().getMostSignificantBits()%10_000);
        String key="apiops:runner:progress:"+projectId+":"+runId;
        RedisTaskProgressStore store=new RedisTaskProgressStore(redis,Duration.ofSeconds(60));
        try {
            TaskProgressSnapshot initial=store.create(projectId,700001,runId,20);
            assertEquals("hash",redis.type(key).code());
            assertEquals(20,initial.total()); assertEquals(0,initial.completed());
            assertEquals(0,initial.running()); assertEquals(RunStatus.PENDING,initial.status());
            assertTrue(redis.opsForHash().entries(key).keySet().containsAll(List.of(
                    "total","completed","running","success","assertionFailed",
                    "executionFailed","timeout","cancelled","status","updatedAt")));
            Long firstTtl=redis.getExpire(key,java.util.concurrent.TimeUnit.MILLISECONDS);
            assertNotNull(firstTtl); assertTrue(firstTtl>0&&firstTtl<=60_000);

            ExecutorService pool=Executors.newFixedThreadPool(8);
            CountDownLatch start=new CountDownLatch(1); List<Future<?>> futures=new ArrayList<>();
            for(int i=0;i<20;i++) { final int index=i; futures.add(pool.submit(()->{
                start.await(); store.caseStarted(projectId,runId);
                RunStatus status=switch(index%5){case 0->RunStatus.SUCCESS;
                    case 1->RunStatus.ASSERTION_FAILED; case 2->RunStatus.EXECUTION_FAILED;
                    case 3->RunStatus.TIMEOUT; default->RunStatus.CANCELLED;};
                store.caseCompleted(projectId,runId,status); return null;})); }
            start.countDown(); for(Future<?> future:futures) future.get();
            pool.shutdown();
            TaskProgressSnapshot concurrent=store.find(projectId,runId).orElseThrow();
            assertEquals(20,concurrent.completed()); assertEquals(0,concurrent.running());
            assertEquals(4,concurrent.success()); assertEquals(4,concurrent.assertionFailed());
            assertEquals(4,concurrent.executionFailed()); assertEquals(4,concurrent.timeout());
            assertEquals(4,concurrent.cancelled());
            Thread.sleep(20); store.terminal(projectId,runId,RunStatus.TIMEOUT);
            Long refreshed=redis.getExpire(key,java.util.concurrent.TimeUnit.MILLISECONDS);
            assertNotNull(refreshed); assertTrue(refreshed>0&&refreshed<=60_000);
            TaskProgressSnapshot terminal=store.find(projectId,runId).orElseThrow();
            assertEquals(terminal.total(),terminal.completed()); assertEquals(0,terminal.running());
            assertEquals(RunStatus.TIMEOUT,terminal.status());
        } finally { redis.delete(key); factory.destroy(); }
    }
}
