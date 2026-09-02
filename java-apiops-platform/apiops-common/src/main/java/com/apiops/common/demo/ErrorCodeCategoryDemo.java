package com.apiops.common.demo;

public class ErrorCodeCategoryDemo {

    public static void main(String[] args) {
        printCategory("A0001");
        printCategory("B0001");
        printCategory("C0001");
        printCategory("S0001");
        printCategory("X0001");
        printCategory("");
        printCategory(null);
    }

    public static String classifyErrorCode(String errorCode) {
        if (errorCode == null || errorCode.length() == 0) {
            return "UNKNOWN_ERROR";
        }

        String prefix = errorCode.substring(0, 1);

        switch (prefix) {
            case "A":
                return "CLIENT_ERROR";
            case "B":
                return "BUSINESS_ERROR";
            case "C":
                return "TOOL_ERROR";
            case "S":
                return "SYSTEM_ERROR";
            default:
                return "UNKNOWN_ERROR";
        }
    }

    private static void printCategory(String errorCode) {
        System.out.println(
                "errorCode=" + errorCode
                        + ", category=" + classifyErrorCode(errorCode)
        );
    }
}