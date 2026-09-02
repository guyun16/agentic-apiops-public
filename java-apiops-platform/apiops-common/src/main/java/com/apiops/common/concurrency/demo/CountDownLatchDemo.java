package com.apiops.common.concurrency.demo;

import java.util.concurrent.CountDownLatch;

public class CountDownLatchDemo {

    public static void main(String[] args) throws InterruptedException {
        int caseCount = 5;
        CountDownLatch latch = new CountDownLatch(caseCount);

        System.out.println("main thread waiting for mock case results...");

        for (int i = 1; i <= caseCount; i++) {
            String caseId = "case_" + i;

            Thread worker = new Thread(() -> {
                try {
                    System.out.println(Thread.currentThread().getName() + " started " + caseId);

                    Thread.sleep(500);

                    System.out.println(Thread.currentThread().getName() + " finished " + caseId);
                } catch (InterruptedException e) {
                    Thread.currentThread().interrupt();
                    System.out.println(Thread.currentThread().getName() + " interrupted " + caseId);
                } finally {
                    latch.countDown();
                }
            });

            worker.setName("apiops-case-worker-" + i);
            worker.start();
        }

        latch.await();

        System.out.println("all mock cases finished, generate summary report");
    }
}