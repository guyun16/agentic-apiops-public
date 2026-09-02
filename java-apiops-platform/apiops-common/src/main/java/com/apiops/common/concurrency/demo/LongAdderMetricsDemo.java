package com.apiops.common.concurrency.demo;

import java.util.concurrent.atomic.LongAdder;

public class LongAdderMetricsDemo {

    private static final int THREAD_COUNT = 10;
    private static final int CALLS_PER_THREAD = 10_000;

    private static final LongAdder sqlReadTotalCount = new LongAdder();
    private static final LongAdder ragSearchTotalCount = new LongAdder();
    private static final LongAdder toolCallFailureCount = new LongAdder();

    public static void main(String[] args) throws InterruptedException {
        Thread[] workers = new Thread[THREAD_COUNT];

        for (int i = 0; i < THREAD_COUNT; i++) {
            workers[i] = new Thread(() -> {
                for (int j = 0; j < CALLS_PER_THREAD; j++) {
                    recordSqlRead();
                    recordRagSearch();

                    if (j % 100 == 0) {
                        recordToolCallFailure();
                    }
                }
            });

            workers[i].setName("apiops-metrics-worker-" + i);
            workers[i].start();
        }

        for (Thread worker : workers) {
            worker.join();
        }

        long expectedSqlRead = THREAD_COUNT * CALLS_PER_THREAD;
        long expectedRagSearch = THREAD_COUNT * CALLS_PER_THREAD;
        long expectedFailure = THREAD_COUNT * (CALLS_PER_THREAD / 100);

        System.out.println("expected sqlReadTotalCount = " + expectedSqlRead);
        System.out.println("actual sqlReadTotalCount = " + sqlReadTotalCount.sum());

        System.out.println("expected ragSearchTotalCount = " + expectedRagSearch);
        System.out.println("actual ragSearchTotalCount = " + ragSearchTotalCount.sum());

        System.out.println("expected toolCallFailureCount = " + expectedFailure);
        System.out.println("actual toolCallFailureCount = " + toolCallFailureCount.sum());
    }

    private static void recordSqlRead() {
        sqlReadTotalCount.increment();
    }

    private static void recordRagSearch() {
        ragSearchTotalCount.increment();
    }

    private static void recordToolCallFailure() {
        toolCallFailureCount.increment();
    }
}