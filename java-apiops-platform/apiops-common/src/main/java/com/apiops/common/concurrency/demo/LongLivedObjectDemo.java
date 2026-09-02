package com.apiops.common.concurrency.demo;

import java.util.ArrayList;
import java.util.List;

public class LongLivedObjectDemo {

    private static final int BATCH_COUNT = 20;
    private static final int RESULTS_PER_BATCH = 2_000;

    private static final List<MockCaseResult> REPORT_RESULTS = new ArrayList<>();

    public static void main(String[] args) throws InterruptedException {
        printMemory("start");

        for (int batch = 1; batch <= BATCH_COUNT; batch++) {
            holdLongLivedResults(batch);
            printMemory("after batch " + batch);

            Thread.sleep(200);
        }

        System.out.println("LongLivedObjectDemo finished.");
        System.out.println("retained result count = " + REPORT_RESULTS.size());
    }

    private static void holdLongLivedResults(int batch) {
        for (int i = 0; i < RESULTS_PER_BATCH; i++) {
            byte[] fullResponseBody = new byte[1024];

            MockCaseResult result = new MockCaseResult(
                    "case_" + batch + "_" + i,
                    "ASSERTION_FAILED",
                    fullResponseBody
            );

            REPORT_RESULTS.add(result);
        }
    }

    private static void printMemory(String stage) {
        Runtime runtime = Runtime.getRuntime();

        long used = runtime.totalMemory() - runtime.freeMemory();

        System.out.println(stage
                + " | usedMemoryMB=" + used / 1024 / 1024
                + " | totalMemoryMB=" + runtime.totalMemory() / 1024 / 1024
                + " | maxMemoryMB=" + runtime.maxMemory() / 1024 / 1024);
    }

    private record MockCaseResult(
            String caseId,
            String status,
            byte[] fullResponseBody
    ) {
    }
}