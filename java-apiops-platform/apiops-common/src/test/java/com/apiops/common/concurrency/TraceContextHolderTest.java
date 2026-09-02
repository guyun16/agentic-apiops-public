package com.apiops.common.concurrency;

import com.apiops.common.concurrency.design.ContextAwareExecutor;
import com.apiops.common.concurrency.design.TraceContextHolder;
import com.apiops.common.concurrency.design.TraceContextSnapshot;
import org.junit.jupiter.api.Test;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class TraceContextHolderTest {

    @Test
    void verifyOldContextIsRestored() throws Exception {
        ExecutorService rawExecutor = Executors.newSingleThreadExecutor(runnable -> new Thread(runnable, "apiops-test-trace-old"));
        try {
            Future<?> initialized = rawExecutor.submit(() -> TraceContextHolder.set(snapshot("old_worker_trace")));
            initialized.get(2, TimeUnit.SECONDS);

            TraceContextHolder.set(snapshot("captured_main_trace"));
            try {
                ContextAwareExecutor executor = new ContextAwareExecutor(rawExecutor);
                AtomicReference<TraceContextSnapshot> observed = new AtomicReference<>();
                AtomicReference<Throwable> workerFailure = new AtomicReference<>();
                CountDownLatch completed = new CountDownLatch(1);
                executor.execute(() -> {
                    try {
                        observed.set(TraceContextHolder.get());
                    } catch (RuntimeException | Error failure) {
                        workerFailure.compareAndSet(null, failure);
                    } finally {
                        completed.countDown();
                    }
                });
                assertTrue(completed.await(2, TimeUnit.SECONDS), "captured-context task must complete");
                assertNull(workerFailure.get(), "captured-context worker must not fail");
                assertEquals("captured_main_trace", observed.get().traceId(), "worker must observe captured context");
            } finally {
                TraceContextHolder.clear();
            }

            TraceContextSnapshot restored = rawExecutor.submit(TraceContextHolder::get).get(2, TimeUnit.SECONDS);
            assertEquals("old_worker_trace", restored.traceId(), "worker old context must be restored after command completion");
        } finally {
            TraceContextHolder.clear();
            clearWorkerContextAndShutdown(rawExecutor);
        }
    }

    @Test
    void verifyNoOldContextIsClearedAndTracesDoNotLeak() throws Exception {
        ExecutorService rawExecutor = Executors.newSingleThreadExecutor(runnable -> new Thread(runnable, "apiops-test-trace-empty"));
        try {
            rawExecutor.submit(TraceContextHolder::clear).get(2, TimeUnit.SECONDS);
            ContextAwareExecutor executor = new ContextAwareExecutor(rawExecutor);

            assertObservedTrace(executor, "trace_without_old");
            assertNull(rawExecutor.submit(TraceContextHolder::get).get(2, TimeUnit.SECONDS),
                    "worker must be clear when no old context existed");

            assertObservedTrace(executor, "trace_A");
            assertObservedTrace(executor, "trace_B");
            assertNull(rawExecutor.submit(TraceContextHolder::get).get(2, TimeUnit.SECONDS),
                    "worker must not retain trace_A or trace_B after wrapped tasks");
        } finally {
            TraceContextHolder.clear();
            clearWorkerContextAndShutdown(rawExecutor);
        }
    }

    private static void assertObservedTrace(ContextAwareExecutor executor, String traceId) throws InterruptedException {
        TraceContextHolder.set(snapshot(traceId));
        try {
            AtomicReference<TraceContextSnapshot> observed = new AtomicReference<>();
            AtomicReference<Throwable> workerFailure = new AtomicReference<>();
            CountDownLatch completed = new CountDownLatch(1);
            executor.execute(() -> {
                try {
                    observed.set(TraceContextHolder.get());
                } catch (RuntimeException | Error failure) {
                    workerFailure.compareAndSet(null, failure);
                } finally {
                    completed.countDown();
                }
            });
            assertTrue(completed.await(2, TimeUnit.SECONDS), "context-aware task must complete");
            assertNull(workerFailure.get(), "context-aware worker must not fail");
            assertEquals(traceId, observed.get().traceId(), "worker must observe the captured trace");
        } finally {
            TraceContextHolder.clear();
        }
    }

    private static TraceContextSnapshot snapshot(String traceId) {
        return new TraceContextSnapshot(traceId, "request", "task", "case", null);
    }

    private static void clearWorkerContextAndShutdown(ExecutorService executor) throws Exception {
        try {
            executor.submit(TraceContextHolder::clear).get(2, TimeUnit.SECONDS);
        } finally {
            shutdownExecutor(executor);
        }
    }

    private static void shutdownExecutor(ExecutorService executor) throws InterruptedException {
        executor.shutdown();
        try {
            if (!executor.awaitTermination(3, TimeUnit.SECONDS)) {
                executor.shutdownNow();
                assertTrue(executor.awaitTermination(3, TimeUnit.SECONDS), "executor must terminate after shutdownNow");
            }
        } catch (InterruptedException exception) {
            executor.shutdownNow();
            throw exception;
        }
    }
}
