package com.apiops.common.concurrency.demo;

public class ShortLivedObjectDemo {

    private static final int BATCH_COUNT = 20;
    private static final int OBJECTS_PER_BATCH = 10_000;

    public static void main(String[] args) throws InterruptedException {
        printMemory("start");

        for (int batch = 1; batch <= BATCH_COUNT; batch++) {
            createShortLivedObjects();
            printMemory("after batch " + batch);

            Thread.sleep(200);
        }

        System.out.println("ShortLivedObjectDemo finished.");
    }

    private static void createShortLivedObjects() {
        for (int i = 0; i < OBJECTS_PER_BATCH; i++) {
            byte[] responseBody = new byte[1024];

            MockResponseSnapshot snapshot = new MockResponseSnapshot(
                    "trace_" + i,
                    200,
                    responseBody
            );

            if (snapshot.statusCode() != 200) {
                throw new IllegalStateException("unexpected status");
            }
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
            int statusCode,
            byte[] responseBody
    ) {
    }
}