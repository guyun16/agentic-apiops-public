package com.apiops.common.concurrency.demo;

public class SynchronizedCounterDemo {

    private int unsafeCount = 0;
    private int safeCount = 0;

    private final Object lock = new Object();

    public void unsafeIncrement() {
        unsafeCount++;
    }

    public void safeIncrement() {
        synchronized (lock) {
            safeCount++;
        }
    }

    public int getUnsafeCount() {
        return unsafeCount;
    }

    public int getSafeCount() {
        synchronized (lock) {
            return safeCount;
        }
    }

    public static void main(String[] args) throws InterruptedException {
        SynchronizedCounterDemo demo = new SynchronizedCounterDemo();

        int threadCount = 10;
        int loopCount = 10000;

        Thread[] threads = new Thread[threadCount];

        for (int i = 0; i < threadCount; i++) {
            threads[i] = new Thread(() -> {
                for (int j = 0; j < loopCount; j++) {
                    demo.unsafeIncrement();
                    demo.safeIncrement();
                }
            });

            threads[i].setName("apiops-counter-worker-" + i);
            threads[i].start();
        }

        for (Thread thread : threads) {
            thread.join();
        }

        int expected = threadCount * loopCount;

        System.out.println("expected = " + expected);
        System.out.println("unsafeCount = " + demo.getUnsafeCount());
        System.out.println("safeCount = " + demo.getSafeCount());
    }
}