package com.apiops.common.concurrency.demo;

public class VolatileStopFlagDemo {

    private volatile boolean cancelled = false;

    public void cancel() {
        this.cancelled = true;
    }

    public void runTask() {
        int step = 0;

        while (!cancelled) {
            step++;

            if (step % 1_000_000 == 0) {
                System.out.println("worker running, step = " + step);
            }
        }

        System.out.println("worker stopped, cancelled = " + cancelled + ", step = " + step);
    }

    public static void main(String[] args) throws InterruptedException {
        VolatileStopFlagDemo demo = new VolatileStopFlagDemo();

        Thread worker = new Thread(demo::runTask);
        worker.setName("apiops-runner-cancellable-worker");
        worker.start();

        Thread.sleep(1000);

        System.out.println("main thread requests cancel");
        demo.cancel();

        worker.join();
        System.out.println("main finished");
    }
}