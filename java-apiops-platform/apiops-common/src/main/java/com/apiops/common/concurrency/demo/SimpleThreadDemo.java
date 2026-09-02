package com.apiops.common.concurrency.demo;

public class SimpleThreadDemo {
    public static void main(String[] args) {
        System.out.println("main thread = " + Thread.currentThread().getName());

        Thread worker = new Thread(() -> {
            System.out.println("worker thread = " + Thread.currentThread().getName());
            System.out.println("mock runner task is executing");
        });

        worker.setName("apiops-runner-worker-1");
        worker.start();

        System.out.println("main thread continues");
    }
}
