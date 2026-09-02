package com.apiops.common.concurrency.demo;

public class ThreadLifecycleDemo {

    public static void main(String[] args) throws InterruptedException {
        Thread worker = new Thread(() -> {
            System.out.println("worker running, state = " + Thread.currentThread().getState());

            try {
                Thread.sleep(1000);
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                System.out.println("worker interrupted");
            }

            System.out.println("worker finished");
        });

        worker.setName("apiops-runner-worker-demo");

        System.out.println("after new, state = " + worker.getState());

        worker.start();
        System.out.println("after start, state = " + worker.getState());

        Thread.sleep(100);
        System.out.println("while sleeping, state = " + worker.getState());

        worker.join();
        System.out.println("after join, state = " + worker.getState());
    }
}