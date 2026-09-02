package com.apiops.common.concurrency.demo;

import java.util.ArrayList;
import java.util.List;

public class ControlledHeapOomDemo {

    public static void main(String[] args) {
        int maxChunks = 200;
        int chunkSizeMb = 1;

        List<byte[]> retainedPayloads = new ArrayList<>();

        Runtime runtime = Runtime.getRuntime();

        try {
            for (int i = 1; i <= maxChunks; i++) {
                retainedPayloads.add(new byte[chunkSizeMb * 1024 * 1024]);

                long usedMemory = runtime.totalMemory() - runtime.freeMemory();

                System.out.println(
                        "created chunks = " + i
                                + ", approx used memory MB = " + usedMemory / 1024 / 1024
                );
            }

            System.out.println("Finished without OOM. retained chunks = " + retainedPayloads.size());
        } catch (OutOfMemoryError error) {
            System.out.println("OutOfMemoryError occurred.");
            System.out.println("retained chunks before OOM = " + retainedPayloads.size());
            System.out.println("message = " + error.getMessage());
        }
    }
}
