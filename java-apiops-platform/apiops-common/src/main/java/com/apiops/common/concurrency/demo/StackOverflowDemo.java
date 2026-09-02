package com.apiops.common.concurrency.demo;

public class StackOverflowDemo {

    private static int depth = 0;

    public static void main(String[] args) {
        try {
            recursiveCall();
        } catch (StackOverflowError error) {
            System.out.println("StackOverflowError occurred.");
            System.out.println("recursive depth = " + depth);
        }
    }

    private static void recursiveCall() {
        depth++;
        recursiveCall();
    }
}