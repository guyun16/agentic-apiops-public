package com.apiops.common.concurrency.demo;

import java.util.concurrent.atomic.AtomicReference;

public class AtomicTaskStateDemo {

    enum TaskStatus {
        PENDING,
        RUNNING,
        SUCCESS,
        FAILED,
        CANCELLED
    }

    static class RunnerTaskState {
        private final AtomicReference<TaskStatus> status =
                new AtomicReference<>(TaskStatus.PENDING);

        public boolean markRunning() {
            return status.compareAndSet(TaskStatus.PENDING, TaskStatus.RUNNING);
        }

        public boolean markSuccess() {
            return status.compareAndSet(TaskStatus.RUNNING, TaskStatus.SUCCESS);
        }

        public boolean markFailed() {
            return status.compareAndSet(TaskStatus.RUNNING, TaskStatus.FAILED);
        }

        public boolean cancelFromPending() {
            return status.compareAndSet(TaskStatus.PENDING, TaskStatus.CANCELLED);
        }

        public TaskStatus getStatus() {
            return status.get();
        }
    }

    public static void main(String[] args) throws InterruptedException {
        RunnerTaskState taskState = new RunnerTaskState();

        Thread worker = new Thread(() -> {
            boolean running = taskState.markRunning();
            System.out.println(Thread.currentThread().getName()
                    + " markRunning = " + running
                    + ", status = " + taskState.getStatus());

            boolean success = taskState.markSuccess();
            System.out.println(Thread.currentThread().getName()
                    + " markSuccess = " + success
                    + ", status = " + taskState.getStatus());
        });

        Thread cancelWorker = new Thread(() -> {
            boolean cancelled = taskState.cancelFromPending();
            System.out.println(Thread.currentThread().getName()
                    + " cancelFromPending = " + cancelled
                    + ", status = " + taskState.getStatus());
        });

        worker.setName("apiops-runner-worker");
        cancelWorker.setName("apiops-cancel-worker");

        worker.start();
        cancelWorker.start();

        worker.join();
        cancelWorker.join();

        System.out.println("final status = " + taskState.getStatus());
    }
}