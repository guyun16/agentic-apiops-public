package com.apiops.common.concurrency.demo;

public class ThreadLocalTraceDemo {

    private static final ThreadLocal<String> TRACE_ID = new ThreadLocal<>();

    public static void main(String[] args) throws InterruptedException {
        Thread threadA = new Thread(() -> {
            TRACE_ID.set("trace_A");
            try {
                System.out.println(Thread.currentThread().getName()
                        + " traceId = " + TRACE_ID.get());
            } finally {
                TRACE_ID.remove();
            }
        });

        Thread threadB = new Thread(() -> {
            TRACE_ID.set("trace_B");
            try {
                System.out.println(Thread.currentThread().getName()
                        + " traceId = " + TRACE_ID.get());
            } finally {
                TRACE_ID.remove();
            }
        });

        threadA.setName("apiops-worker-A");
        threadB.setName("apiops-worker-B");

        threadA.start();
        threadB.start();

        threadA.join();
        threadB.join();
    }
}