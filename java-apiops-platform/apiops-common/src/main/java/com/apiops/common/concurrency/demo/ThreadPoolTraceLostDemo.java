package com.apiops.common.concurrency.demo;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

public class ThreadPoolTraceLostDemo {

    private static final ThreadLocal<String> TRACE_ID = new ThreadLocal<>();

    public static void main(String[] args) {
        ExecutorService executor = Executors.newFixedThreadPool(1, runnable -> {
            Thread thread = new Thread(runnable);
            thread.setName("apiops-runner-worker-1");
            return thread;
        });

        try {
            TRACE_ID.set("trace_main_001");

            System.out.println(Thread.currentThread().getName()
                    + " traceId = " + TRACE_ID.get());

            executor.submit(() -> {
                System.out.println(Thread.currentThread().getName()
                        + " traceId = " + TRACE_ID.get());
            });
        } finally {
            TRACE_ID.remove();
            shutdownExecutor(executor);
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
