package com.apiops.common.concurrency;

import org.junit.jupiter.api.Test;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.junit.jupiter.api.Assertions.fail;

public class CompletableFutureTimeoutTest {

    @Test
    void timeoutResultsMustUseFallbacksWhileUnderlyingTasksFinish() throws Exception {
        ExecutorService ragExecutor = Executors.newSingleThreadExecutor(runnable -> new Thread(runnable, "apiops-test-rag"));
        ExecutorService modelExecutor = Executors.newSingleThreadExecutor(runnable -> new Thread(runnable, "apiops-test-model"));
        AtomicBoolean ragFinished = new AtomicBoolean();
        AtomicBoolean modelFinished = new AtomicBoolean();
        AtomicBoolean modelTimedOut = new AtomicBoolean();
        CountDownLatch underlyingFinished = new CountDownLatch(2);
        AtomicReference<Throwable> workerFailure = new AtomicReference<>();

        try {
            CompletableFuture<String> ragFuture = CompletableFuture
                    .supplyAsync(() -> completeAfterDelay(ragFinished, underlyingFinished, workerFailure), ragExecutor)
                    .completeOnTimeout("NO_RAG_EVIDENCE", 150, TimeUnit.MILLISECONDS);

            CompletableFuture<String> timedModelFuture = CompletableFuture
                    .supplyAsync(() -> completeAfterDelay(modelFinished, underlyingFinished, workerFailure), modelExecutor)
                    .orTimeout(150, TimeUnit.MILLISECONDS);
            CompletableFuture<String> modelFuture = timedModelFuture.exceptionally(exception -> {
                modelTimedOut.set(true);
                return "AGENT_MODEL_TIMEOUT";
            });

            CompletableFuture<String> combined = ragFuture.thenCombine(
                    modelFuture,
                    (rag, model) -> "rag=" + rag + ", model=" + model
            );
            String result = combined.get(2, TimeUnit.SECONDS);

            assertEquals("rag=NO_RAG_EVIDENCE, model=AGENT_MODEL_TIMEOUT", result,
                    "timeout results must be converted to the expected fallback values");
            assertTrue(modelTimedOut.get(), "orTimeout must complete exceptionally before fallback conversion");
            assertTrue(!ragFinished.get() || !modelFinished.get(),
                    "future timeout must occur before at least one underlying task naturally finishes");

            // CompletableFuture timeout changes the completion result.
            // It does not automatically interrupt or cancel the underlying task.
            assertTrue(underlyingFinished.await(3, TimeUnit.SECONDS),
                    "underlying tasks must still be allowed to finish naturally");
            assertNull(workerFailure.get(), "underlying timeout task must not fail");
            assertTrue(ragFinished.get(), "RAG task must eventually finish after its future timed out");
            assertTrue(modelFinished.get(), "model task must eventually finish after its future timed out");
        } finally {
            try {
                shutdownExecutor(ragExecutor);
            } finally {
                shutdownExecutor(modelExecutor);
            }
        }
    }

    private static String completeAfterDelay(
            AtomicBoolean finished,
            CountDownLatch underlyingFinished,
            AtomicReference<Throwable> workerFailure
    ) {
        try {
            Thread.sleep(700);
            return "UNDERLYING_RESULT";
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            RuntimeException failure = new RuntimeException(exception);
            workerFailure.compareAndSet(null, failure);
            throw failure;
        } catch (RuntimeException | Error failure) {
            workerFailure.compareAndSet(null, failure);
            throw failure;
        } finally {
            finished.set(true);
            underlyingFinished.countDown();
        }
    }

    private static void shutdownExecutor(ExecutorService executor) {
        executor.shutdown();
        try {
            if (!executor.awaitTermination(3, TimeUnit.SECONDS)) {
                executor.shutdownNow();
                assertTrue(executor.awaitTermination(3, TimeUnit.SECONDS), "executor must terminate after shutdownNow");
            }
        } catch (InterruptedException exception) {
            executor.shutdownNow();
            Thread.currentThread().interrupt();
            fail("interrupted while shutting down executor", exception);
        }
    }
}
