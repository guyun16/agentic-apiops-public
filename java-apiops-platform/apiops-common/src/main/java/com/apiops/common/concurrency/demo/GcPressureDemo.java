package com.apiops.common.concurrency.demo;

import java.util.ArrayList;
import java.util.List;

public class GcPressureDemo {

    private static final int ROUND_COUNT = 10;
    private static final int OBJECTS_PER_ROUND = 5_000;

    private static final List<MockCaseResult> RETAINED_RESULTS = new ArrayList<>();

    public static void main(String[] args) throws InterruptedException {
        printMemory("start");

        runShortLivedMode();
        printMemory("after short-lived mode");

        runLongLivedMode();
        printMemory("after long-lived mode");

        System.out.println("retained result count = " + RETAINED_RESULTS.size());
        System.out.println("GcPressureDemo finished.");
    }

    private static void runShortLivedMode() throws InterruptedException {
        System.out.println("=== short-lived mode ===");

        for (int round = 1; round <= ROUND_COUNT; round++) {
            for (int i = 0; i < OBJECTS_PER_ROUND; i++) {
                byte[] responseBody = new byte[1024];
                MockResponseSnapshot snapshot = new MockResponseSnapshot(
                        "trace_short_" + round + "_" + i,
                        responseBody
                );

                if (snapshot.responseBody().length == 0) {
                    throw new IllegalStateException("empty response");
                }
            }

            printMemory("short-lived round " + round);
            Thread.sleep(100);
        }
    }

    private static void runLongLivedMode() throws InterruptedException {
        System.out.println("=== long-lived mode ===");

        for (int round = 1; round <= ROUND_COUNT; round++) {
            for (int i = 0; i < OBJECTS_PER_ROUND; i++) {
                byte[] fullResponseBody = new byte[1024];
                MockCaseResult result = new MockCaseResult(
                        "case_long_" + round + "_" + i,
                        "FAILED",
                        fullResponseBody
                );

                RETAINED_RESULTS.add(result);
            }

            printMemory("long-lived round " + round);
            Thread.sleep(100);
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

    private record MockResponseSnapshot(
            String traceId,
            byte[] responseBody
    ) {
    }

    private record MockCaseResult(
            String caseId,
            String status,
            byte[] fullResponseBody
    ) {
    }
}