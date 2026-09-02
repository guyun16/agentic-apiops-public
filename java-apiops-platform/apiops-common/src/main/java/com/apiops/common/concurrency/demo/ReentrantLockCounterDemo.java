package com.apiops.common.concurrency.demo;

import java.util.concurrent.locks.ReentrantLock;

public class ReentrantLockCounterDemo {

    private static final int THREAD_COUNT = 10;
    private static final int INCREMENT_PER_THREAD = 10_000;

    private static int counter = 0;
    private static final ReentrantLock lock = new ReentrantLock();

    public static void main(String[] args) throws InterruptedException {
        Thread[] workers = new Thread[THREAD_COUNT];

        for (int i = 0; i < THREAD_COUNT; i++) {
            workers[i] = new Thread(() -> {
                for (int j = 0; j < INCREMENT_PER_THREAD; j++) {
                    lock.lock();
                    try {
                        counter++;
                    } finally {
                        lock.unlock();
                    }
                }
            });
            workers[i].setName("apiops-lock-worker-" + i);
            workers[i].start();
        }

        for (Thread worker : workers) {
            worker.join();
        }

        int expected = THREAD_COUNT * INCREMENT_PER_THREAD;
        int actual = counter;

        System.out.println("expected = " + expected);
        System.out.println("actual = " + actual);
    }
}