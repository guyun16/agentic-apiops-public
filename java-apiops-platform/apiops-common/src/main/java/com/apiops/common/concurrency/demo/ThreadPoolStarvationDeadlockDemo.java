package com.apiops.common.concurrency.demo;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

public class ThreadPoolStarvationDeadlockDemo {

    public static void main(String[] args) throws Exception {
        ExecutorService executor = Executors.newFixedThreadPool(1, runnable -> {
            Thread thread = new Thread(runnable);
            thread.setName("apiops-runner-worker-1");
            return thread;
        });

        Future<String> parentFuture = executor.submit(() -> {
            System.out.println(Thread.currentThread().getName() + " parent task started");

            Future<String> childFuture = executor.submit(() -> {
                System.out.println(Thread.currentThread().getName() + " child task started");
                return "child result";
            });

            System.out.println(Thread.currentThread().getName() + " waiting child result");
            return childFuture.get();
        });

        try {
            System.out.println(parentFuture.get(2, TimeUnit.SECONDS));
        } catch (TimeoutException e) {
            System.out.println("parent task timeout: possible thread pool starvation deadlock");
        } finally {
            executor.shutdownNow();
        }
    }
}