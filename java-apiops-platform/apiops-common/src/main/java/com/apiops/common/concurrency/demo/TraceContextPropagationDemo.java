package com.apiops.common.concurrency.demo;

import com.apiops.common.concurrency.design.ContextAwareExecutor;
import com.apiops.common.concurrency.design.TraceContextHolder;
import com.apiops.common.concurrency.design.TraceContextSnapshot;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;

public class TraceContextPropagationDemo {

    public static void main(String[] args) {
        ExecutorService rawExecutor = Executors.newFixedThreadPool(1, runnable -> {
            Thread thread = new Thread(runnable);
            thread.setName("apiops-runner-worker-1");
            return thread;
        });

        try {
            ContextAwareExecutor contextAwareExecutor = new ContextAwareExecutor(rawExecutor);

            TraceContextHolder.set(new TraceContextSnapshot(
                    "trace_001",
                    "request_001",
                    "task_001",
                    "case_001",
                    null
            ));

            System.out.println(Thread.currentThread().getName()
                    + " trace = " + TraceContextHolder.get());

            contextAwareExecutor.execute(() -> {
                System.out.println(Thread.currentThread().getName()
                        + " trace = " + TraceContextHolder.get());
            });
        } finally {
            TraceContextHolder.clear();
            shutdownExecutor(rawExecutor);
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
