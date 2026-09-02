package com.apiops.common.concurrency.demo;

public class HappensBeforeJoinDemo {
    private int result = 0;

    public void calculate(){
        result = 42;
    }
    public int getResult(){
        return result;
    }

    public static void main(String[] args) throws InterruptedException {
        HappensBeforeJoinDemo demo = new HappensBeforeJoinDemo();
        Thread worker = new Thread(demo::calculate);
        worker.setName("apiops-happens-before-worker");
        worker.start();
        worker.join();
        System.out.println("Result: " + demo.getResult());

    }
}
