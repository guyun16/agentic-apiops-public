package com.apiops.common.demo;

public class UncheckedExceptionDemo {

    public static void main(String[] args) {
        checkPageNo(0);
        System.out.println("This line will not execute.");
    }

    private static void checkPageNo(long pageNo) {
        if (pageNo <= 0) {
            throw new IllegalArgumentException("pageNo must be greater than 0");
        }
    }
}