package com.apiops.common.concurrency.demo;

import java.util.concurrent.Callable;
import java.util.concurrent.FutureTask;

public class RunnableCallableDemo {

    public static void main(String[] args) throws Exception {
        System.out.println("main thread = " + Thread.currentThread().getName());

        Runnable runnableTask = () -> {
            System.out.println("runnable task thread = " + Thread.currentThread().getName());
            System.out.println("mock runner task executed by Runnable");
        };

        Thread runnableThread = new Thread(runnableTask);
        runnableThread.setName("apiops-runnable-worker-1");
        runnableThread.start();

        Callable<String> callableTask = () -> {
            System.out.println("callable task thread = " + Thread.currentThread().getName());
            System.out.println("mock runner task executed by Callable");
            return "callable-result: mock case execution finished";
        };

        FutureTask<String> futureTask = new FutureTask<>(callableTask);

        Thread callableThread = new Thread(futureTask);
        callableThread.setName("apiops-callable-worker-1");
        callableThread.start();

        String callableResult = futureTask.get();

        runnableThread.join();

        System.out.println("callable result = " + callableResult);
        System.out.println("main thread finished");
    }
}