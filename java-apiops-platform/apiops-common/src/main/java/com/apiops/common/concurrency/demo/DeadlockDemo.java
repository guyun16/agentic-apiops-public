package com.apiops.common.concurrency.demo;

public class DeadlockDemo {

    private static final Object LOCK_A = new Object();
    private static final Object LOCK_B = new Object();

    public static void main(String[] args) {
        Thread threadA = new Thread(() -> {
            synchronized (LOCK_A) {
                sleep(100);
                System.out.println(Thread.currentThread().getName() + " acquired LOCK_A");

                synchronized (LOCK_B) {
                    System.out.println(Thread.currentThread().getName() + " acquired LOCK_B");
                }
            }
        });

        Thread threadB = new Thread(() -> {
            synchronized (LOCK_B) {
                sleep(100);
                System.out.println(Thread.currentThread().getName() + " acquired LOCK_B");

                synchronized (LOCK_A) {
                    System.out.println(Thread.currentThread().getName() + " acquired LOCK_A");
                }
            }
        });

        threadA.setName("apiops-runner-lock-worker-A");
        threadB.setName("apiops-runner-lock-worker-B");

        threadA.start();
        threadB.start();
    }

    private static void sleep(long millis) {
        try {
            Thread.sleep(millis);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new RuntimeException("interrupted", e);
        }
    }
}