package com.apiops.common.concurrency.demo;

import java.util.concurrent.atomic.AtomicInteger;

public class AtomicCounterDemo {

    private static final int THREAD_COUNT = 10;
    private static final int INCREMENT_PER_THREAD = 10_000;

    private static final AtomicInteger counter = new AtomicInteger(0);

    public static void main(String[] args) throws InterruptedException {
        Thread[] workers = new Thread[THREAD_COUNT];

        for (int i = 0; i < THREAD_COUNT; i++) {
            workers[i] = new Thread(() -> {
                for (int j = 0; j < INCREMENT_PER_THREAD; j++) {
                    counter.incrementAndGet();
                }
            });
            workers[i].setName("apiops-atomic-worker-" + i);
            workers[i].start();
        }

        for (Thread worker : workers) {
            worker.join();
        }

        int expected = THREAD_COUNT * INCREMENT_PER_THREAD;
        int actual = counter.get();

        System.out.println("expected = " + expected);
        System.out.println("actual = " + actual);
    }
}