package com.apiops.common.demo;

public class ExceptionHierarchyDemo {

    public static void main(String[] args) {
        try {
            checkPageNo(0);
            System.out.println("This line will not execute.");
        } catch (IllegalArgumentException e) {
            System.out.println("Caught exception: " + e.getMessage());
        }

        System.out.println("Program continues after catch.");
    }

    private static void checkPageNo(long pageNo) {
        if (pageNo <= 0) {
            throw new IllegalArgumentException("pageNo must be greater than 0");
        }
    }
}