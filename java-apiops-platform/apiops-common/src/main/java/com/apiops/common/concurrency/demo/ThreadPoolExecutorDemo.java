package com.apiops.common.concurrency.demo;

import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

public class ThreadPoolExecutorDemo {

    public static void main(String[] args) throws InterruptedException {
        ThreadPoolExecutor executor = new ThreadPoolExecutor(
                2,
                4,
                60L,
                TimeUnit.SECONDS,
                new ArrayBlockingQueue<>(2),
                new NamedThreadFactory("apiops-runner-worker"),
                new ThreadPoolExecutor.AbortPolicy()
        );

        for (int i = 1; i <= 7; i++) {
            String taskName = "case_" + i;

            try {
                System.out.println("submit " + taskName
                        + ", poolSize=" + executor.getPoolSize()
                        + ", activeCount=" + executor.getActiveCount()
                        + ", queueSize=" + executor.getQueue().size());

                executor.execute(() -> runCase(taskName));

                System.out.println("accepted " + taskName
                        + ", poolSize=" + executor.getPoolSize()
                        + ", activeCount=" + executor.getActiveCount()
                        + ", queueSize=" + executor.getQueue().size());

            } catch (Exception e) {
                System.out.println("rejected " + taskName + ", reason=" + e.getClass().getSimpleName());
            }
        }

        executor.shutdown();
        executor.awaitTermination(30, TimeUnit.SECONDS);
    }

    private static void runCase(String caseId) {
        System.out.println(Thread.currentThread().getName() + " executing " + caseId);

        try {
            Thread.sleep(3000L);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            System.out.println(Thread.currentThread().getName() + " interrupted " + caseId);
        }

        System.out.println(Thread.currentThread().getName() + " finished " + caseId);
    }

    private static class NamedThreadFactory implements ThreadFactory {

        private final String prefix;
        private final AtomicInteger index = new AtomicInteger(1);

        private NamedThreadFactory(String prefix) {
            this.prefix = prefix;
        }

        @Override
        public Thread newThread(Runnable runnable) {
            Thread thread = new Thread(runnable);
            thread.setName(prefix + "-" + index.getAndIncrement());
            return thread;
        }
    }
}