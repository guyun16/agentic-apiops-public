package com.apiops.common.demo;

public class ControlFlowOverview {

    public static void main(String[] args) {
        System.out.println("Page valid: " + isValidPage(1, 20));
        System.out.println("Error category: " + classifyErrorCode("A0001"));
        System.out.println("Status transition: " + canTransit("PENDING", "RUNNING"));
    }

    public static boolean isValidPage(long pageNo, long pageSize) {
        if (pageNo <= 0) {
            return false;
        }

        if (pageSize <= 0 || pageSize > 100) {
            return false;
        }

        return true;
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

    public static boolean canTransit(String fromStatus, String toStatus) {
        if (fromStatus == null || toStatus == null) {
            return false;
        }

        if ("PENDING".equals(fromStatus) && "RUNNING".equals(toStatus)) {
            return true;
        }

        if ("RUNNING".equals(fromStatus)
                && ("SUCCESS".equals(toStatus) || "FAILED".equals(toStatus))) {
            return true;
        }

        return false;
    }
}