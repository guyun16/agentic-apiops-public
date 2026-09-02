package com.apiops.common.concurrency;

import org.junit.jupiter.api.Test;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class AtomicCounterTest {

    @Test
    void atomicCounterMustRetainEveryIncrement() throws InterruptedException {
        int threadCount = 8;
        int incrementsPerThread = 10_000;
        AtomicInteger counter = new AtomicInteger();
        CountDownLatch completed = new CountDownLatch(threadCount);
        AtomicReference<Throwable> workerFailure = new AtomicReference<>();

        for (int i = 0; i < threadCount; i++) {
            Thread worker = new Thread(() -> {
                try {
                    for (int j = 0; j < incrementsPerThread; j++) {
                        counter.incrementAndGet();
                    }
                } catch (RuntimeException | Error failure) {
                    workerFailure.compareAndSet(null, failure);
                    throw failure;
                } finally {
                    completed.countDown();
                }
            }, "apiops-atomic-test-worker-" + i);
            worker.start();
        }

        assertTrue(completed.await(5, TimeUnit.SECONDS), "all atomic counter workers must complete");
        assertNull(workerFailure.get(), "atomic counter worker must not fail");
        assertEquals(threadCount * incrementsPerThread, counter.get(), "atomic counter must retain every increment");
    }
}
