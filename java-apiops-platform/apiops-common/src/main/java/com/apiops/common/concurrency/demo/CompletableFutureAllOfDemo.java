package com.apiops.common.concurrency.demo;

import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.stream.Collectors;

public class CompletableFutureAllOfDemo {

    public static void main(String[] args) {
        ExecutorService toolExecutor = Executors.newFixedThreadPool(4, runnable -> {
            Thread thread = new Thread(runnable);
            thread.setName("apiops-tool-call-worker");
            return thread;
        });

        try {
            CompletableFuture<String> reportFuture = callToolAsync("REPORT_READ", false, toolExecutor);
            CompletableFuture<String> ragFuture = callToolAsync("RAG_SEARCH", false, toolExecutor);
            CompletableFuture<String> logFuture = callToolAsync("LOG_SEARCH", true, toolExecutor);
            CompletableFuture<String> sqlFuture = callToolAsync("SQL_READ", false, toolExecutor);

            List<CompletableFuture<String>> futures = List.of(
                    reportFuture,
                    ragFuture,
                    logFuture,
                    sqlFuture
            );

            CompletableFuture<Void> allDone = CompletableFuture.allOf(
                    futures.toArray(new CompletableFuture[0])
            );

            allDone.join();

            List<String> results = futures.stream()
                    .map(CompletableFuture::join)
                    .collect(Collectors.toList());

            System.out.println("evidence results:");
            for (String result : results) {
                System.out.println(result);
            }
        } finally {
            shutdownExecutor(toolExecutor);
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

    private static CompletableFuture<String> callToolAsync(
            String toolName,
            boolean shouldFail,
            ExecutorService executor
    ) {
        return CompletableFuture.supplyAsync(() -> {
            System.out.println(Thread.currentThread().getName() + " executing " + toolName);

            if (shouldFail) {
                throw new RuntimeException(toolName + " failed");
            }

            return toolName + "_SUCCESS";
        }, executor).exceptionally(ex -> toolName + "_FAILED: " + ex.getMessage());
    }
}
