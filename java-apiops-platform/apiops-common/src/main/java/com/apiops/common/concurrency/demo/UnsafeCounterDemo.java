package com.apiops.common.concurrency.demo;

public class UnsafeCounterDemo {

    private int count = 0;

    public void increment() {
        count++;
    }

    public int getCount() {
        return count;
    }

    public static void main(String[] args) throws InterruptedException {
        UnsafeCounterDemo demo = new UnsafeCounterDemo();

        int threadCount = 10;
        int loopCount = 10000;
        Thread[] threads = new Thread[threadCount];

        for (int i = 0; i < threadCount; i++) {
            threads[i] = new Thread(() -> {
                for (int j = 0; j < loopCount; j++) {
                    demo.increment();
                }
            });

            threads[i].setName("apiops-unsafe-counter-worker-" + i);
            threads[i].start();
        }

        for (Thread thread : threads) {
            thread.join();
        }

        int expected = threadCount * loopCount;

        System.out.println("expected = " + expected);
        System.out.println("actual = " + demo.getCount());
    }
}