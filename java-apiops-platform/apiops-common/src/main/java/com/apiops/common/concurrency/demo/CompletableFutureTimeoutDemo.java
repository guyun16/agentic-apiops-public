package com.apiops.common.concurrency.demo;

import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

public class CompletableFutureTimeoutDemo {

    public static void main(String[] args) {
        ExecutorService modelExecutor = Executors.newFixedThreadPool(2, runnable -> {
            Thread thread = new Thread(runnable);
            thread.setName("apiops-model-call-worker");
            return thread;
        });

        ExecutorService ragExecutor = Executors.newFixedThreadPool(2, runnable -> {
            Thread thread = new Thread(runnable);
            thread.setName("apiops-rag-query-worker");
            return thread;
        });

        try {
            CompletableFuture<String> ragFuture = CompletableFuture
                    .supplyAsync(() -> mockRagSearch("report_001"), ragExecutor)
                    .completeOnTimeout("NO_RAG_EVIDENCE", 1, TimeUnit.SECONDS);

            CompletableFuture<String> modelFuture = CompletableFuture
                    .supplyAsync(() -> mockModelCall("report_001"), modelExecutor)
                    .orTimeout(2, TimeUnit.SECONDS)
                    .exceptionally(ex -> "AGENT_MODEL_TIMEOUT");

            CompletableFuture<String> diagnosisFuture = ragFuture.thenCombine(
                    modelFuture,
                    (ragEvidence, modelResult) -> "diagnosis: rag=" + ragEvidence + ", model=" + modelResult
            );

            System.out.println(diagnosisFuture.join());
        } finally {
            shutdownExecutor(modelExecutor);
            shutdownExecutor(ragExecutor);
        }
    }

    private static String mockRagSearch(String reportId) {
        sleep(1500);
        System.out.println(Thread.currentThread().getName() + " query rag for " + reportId);
        return "RAG_EVIDENCE";
    }

    private static String mockModelCall(String reportId) {
        sleep(2500);
        System.out.println(Thread.currentThread().getName() + " call model for " + reportId);
        return "MODEL_DIAGNOSIS";
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new RuntimeException("task interrupted", e);
        }
    }

    private static void shutdownExecutor(ExecutorService executor) {
        executor.shutdown();
        try {
            if (!executor.awaitTermination(3, TimeUnit.SECONDS)) {
                executor.shutdownNow();
                if (!executor.awaitTermination(3, TimeUnit.SECONDS)) {
                    System.err.println("executor did not terminate");
                }
            }
        } catch (InterruptedException exception) {
            executor.shutdownNow();
            Thread.currentThread().interrupt();
        }
    }
}
