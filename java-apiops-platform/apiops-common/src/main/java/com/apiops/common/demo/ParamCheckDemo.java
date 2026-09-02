package com.apiops.common.demo;

public class ParamCheckDemo {

    private static final long MAX_PAGE_SIZE = 100;

    public static void main(String[] args) {
        printCheck(1, 20);
        printCheck(0, 20);
        printCheck(1, 0);
        printCheck(1, 100);
        printCheck(1, 101);
        printCheck(-1, 20);
    }

    public static boolean isValidPage(long pageNo, long pageSize) {
        if (pageNo <= 0) {
            return false;
        }

        if (pageSize <= 0 || pageSize > MAX_PAGE_SIZE) {
            return false;
        }

        return true;
    }

    public static void printCheck(long pageNo, long pageSize) {
        System.out.println(
                "pageNo=" + pageNo
                        + ", pageSize=" + pageSize
                        + ", valid=" + isValidPage(pageNo, pageSize)
        );
    }
}