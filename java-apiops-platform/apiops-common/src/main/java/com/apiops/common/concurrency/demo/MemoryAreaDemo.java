package com.apiops.common.concurrency.demo;

public class MemoryAreaDemo {

    public static void main(String[] args) {
        Runtime runtime = Runtime.getRuntime();

        long maxMemory = runtime.maxMemory();
        long totalMemory = runtime.totalMemory();
        long freeMemory = runtime.freeMemory();
        long usedMemory = totalMemory - freeMemory;

        System.out.println("maxMemory bytes = " + maxMemory);
        System.out.println("totalMemory bytes = " + totalMemory);
        System.out.println("freeMemory bytes = " + freeMemory);
        System.out.println("usedMemory bytes = " + usedMemory);

        System.out.println("main thread = " + Thread.currentThread().getName());
    }
}