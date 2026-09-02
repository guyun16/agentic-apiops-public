package com.apiops.common.concurrency.demo;

public class SynchronizedTaskStateDemo {

    public static void main(String[] args) throws InterruptedException {
        RunnerTaskState state = new RunnerTaskState();

        Thread t1 = new Thread(state::markRunning, "runner-worker-1");
        Thread t2 = new Thread(state::markSuccess, "runner-worker-2");

        t1.start();
        t1.join();

        t2.start();
        t2.join();

        System.out.println("final status = " + state.getStatus());
    }

    static final class RunnerTaskState {
        private String status = "PENDING";

        public synchronized void markRunning() {
            if ("PENDING".equals(status)) {
                status = "RUNNING";
            }
        }

        public synchronized void markSuccess() {
            if ("RUNNING".equals(status)) {
                status = "SUCCESS";
            }
        }

        public synchronized String getStatus() {
            return status;
        }
    }
}