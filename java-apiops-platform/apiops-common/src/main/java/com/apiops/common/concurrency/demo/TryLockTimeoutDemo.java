package com.apiops.common.concurrency.demo;

import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.ReentrantLock;

public class TryLockTimeoutDemo {

    private static final ReentrantLock lock = new ReentrantLock();

    public static void main(String[] args) throws InterruptedException {
        Thread slowWorker = new Thread(() -> {
            lock.lock();
            try {
                System.out.println(Thread.currentThread().getName() + " acquired lock");
                sleep(1000);
                System.out.println(Thread.currentThread().getName() + " finished slow work");
            } finally {
                lock.unlock();
            }
        });

        Thread fastWorker = new Thread(() -> {
            try {
                boolean acquired = lock.tryLock(200, TimeUnit.MILLISECONDS);
                if (!acquired) {
                    System.out.println(Thread.currentThread().getName()
                            + " failed to acquire lock, fallback: resource busy");
                    return;
                }

                try {
                    System.out.println(Thread.currentThread().getName() + " acquired lock");
                } finally {
                    lock.unlock();
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                System.out.println(Thread.currentThread().getName() + " interrupted while waiting lock");
            }
        });

        slowWorker.setName("apiops-slow-worker");
        fastWorker.setName("apiops-fast-worker");

        slowWorker.start();
        Thread.sleep(50);
        fastWorker.start();

        slowWorker.join();
        fastWorker.join();
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}