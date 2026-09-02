package com.apiops.common.concurrency;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class ThreadPoolExecutorBehaviorTest {

    @Test
    void boundedPoolMustExpandRejectAndTerminate() throws Exception {
        CountDownLatch firstStartedLatch = new CountDownLatch(1);
        CountDownLatch startedLatch = new CountDownLatch(2);
        CountDownLatch releaseLatch = new CountDownLatch(1);
        List<String> workerNames = Collections.synchronizedList(new ArrayList<>());
        AtomicReference<Throwable> workerFailure = new AtomicReference<>();
        ThreadPoolExecutor executor = new ThreadPoolExecutor(
                1, 2, 1, TimeUnit.SECONDS, new ArrayBlockingQueue<>(1),
                runnable -> new Thread(runnable, "apiops-test-pool-worker"),
                new ThreadPoolExecutor.AbortPolicy()
        );

        try {
            Runnable blockingTask = () -> {
                workerNames.add(Thread.currentThread().getName());
                firstStartedLatch.countDown();
                startedLatch.countDown();
                try {
                    releaseLatch.await();
                } catch (InterruptedException exception) {
                    Thread.currentThread().interrupt();
                    RuntimeException failure = new RuntimeException(exception);
                    workerFailure.compareAndSet(null, failure);
                    throw failure;
                } catch (RuntimeException | Error failure) {
                    workerFailure.compareAndSet(null, failure);
                    throw failure;
                }
            };

            executor.execute(blockingTask);
            assertTrue(firstStartedLatch.await(2, TimeUnit.SECONDS), "first worker must start");
            executor.execute(() -> { });
            assertEquals(1, executor.getQueue().size(), "second task must enter the bounded queue");
            executor.execute(blockingTask);
            assertTrue(startedLatch.await(2, TimeUnit.SECONDS), "third task must expand the pool");
            assertEquals(2, executor.getLargestPoolSize(), "pool must expand to maximum size");

            assertThrows(
                    RejectedExecutionException.class,
                    () -> executor.execute(() -> { }),
                    "fourth task must be rejected when pool and queue are full"
            );
            assertTrue(workerNames.stream().allMatch(name -> name.startsWith("apiops-test-pool-worker")),
                    "worker names must use the configured prefix");
        } finally {
            releaseLatch.countDown();
            shutdownExecutor(executor);
        }

        assertTrue(executor.isTerminated(), "executor must terminate after shutdown");
        assertNull(workerFailure.get(), "pool worker must not fail");
        assertThrows(
                RejectedExecutionException.class,
                () -> executor.execute(() -> { }),
                "submission after shutdown must be rejected"
        );
    }

    private static void shutdownExecutor(ThreadPoolExecutor executor) throws InterruptedException {
        executor.shutdown();
        if (!executor.awaitTermination(3, TimeUnit.SECONDS)) {
            executor.shutdownNow();
            assertTrue(executor.awaitTermination(3, TimeUnit.SECONDS), "executor did not terminate");
        }
    }
}
