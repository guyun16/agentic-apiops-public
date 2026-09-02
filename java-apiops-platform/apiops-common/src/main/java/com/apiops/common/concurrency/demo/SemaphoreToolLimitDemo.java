package com.apiops.common.concurrency.demo;

import java.util.concurrent.Semaphore;

public class SemaphoreToolLimitDemo {

    public static void main(String[] args) {
        int toolCallCount = 8;
        int maxConcurrentToolCalls = 3;

        Semaphore semaphore = new Semaphore(maxConcurrentToolCalls);

        for (int i = 1; i <= toolCallCount; i++) {
            String toolCallId = "tool_call_" + i;

            Thread worker = new Thread(() -> {
                try {
                    System.out.println(Thread.currentThread().getName()
                            + " waiting permit for " + toolCallId);

                    semaphore.acquire();

                    System.out.println(Thread.currentThread().getName()
                            + " acquired permit, executing " + toolCallId);

                    Thread.sleep(1000);

                    System.out.println(Thread.currentThread().getName()
                            + " finished " + toolCallId);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    System.out.println(Thread.currentThread().getName()
                            + " interrupted " + toolCallId);
                } finally {
                    semaphore.release();
                    System.out.println(Thread.currentThread().getName()
                            + " released permit for " + toolCallId);
                }
            });

            worker.setName("apiops-tool-worker-" + i);
            worker.start();
        }
    }
}