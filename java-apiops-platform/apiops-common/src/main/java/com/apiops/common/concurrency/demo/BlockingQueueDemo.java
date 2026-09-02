package com.apiops.common.concurrency.demo;

import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.BlockingQueue;

public class BlockingQueueDemo {

    private static final String POISON_PILL = "STOP";

    public static void main(String[] args) throws InterruptedException {
        BlockingQueue<String> queue = new ArrayBlockingQueue<>(3);

        int workerCount = 2;
        int caseCount = 8;

        for (int i = 1; i <= workerCount; i++) {
            Thread worker = new Thread(() -> {
                try {
                    while (true) {
                        String caseId = queue.take();

                        if (POISON_PILL.equals(caseId)) {
                            System.out.println(Thread.currentThread().getName() + " received stop signal");
                            break;
                        }

                        System.out.println(Thread.currentThread().getName() + " executing " + caseId);
                        Thread.sleep(1000);
                        System.out.println(Thread.currentThread().getName() + " finished " + caseId);
                    }
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    System.out.println(Thread.currentThread().getName() + " interrupted");
                }
            });

            worker.setName("apiops-runner-worker-" + i);
            worker.start();
        }

        for (int i = 1; i <= caseCount; i++) {
            String caseId = "case_" + i;
            System.out.println("submitter trying to enqueue " + caseId);
            queue.put(caseId);
            System.out.println("submitter enqueued " + caseId + ", queue size = " + queue.size());
        }

        for (int i = 1; i <= workerCount; i++) {
            queue.put(POISON_PILL);
        }

        System.out.println("submitter finished submitting mock cases");
    }
}