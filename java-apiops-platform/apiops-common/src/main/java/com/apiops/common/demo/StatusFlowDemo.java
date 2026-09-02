package com.apiops.common.demo;

public class StatusFlowDemo {

    public static void main(String[] args) {
        printTransit("PENDING", "RUNNING");
        printTransit("RUNNING", "SUCCESS");
        printTransit("RUNNING", "FAILED");
        printTransit("PENDING", "SUCCESS");
        printTransit("SUCCESS", "RUNNING");
        printTransit("FAILED", "RUNNING");
        printTransit(null, "RUNNING");
        printTransit("RUNNING", null);

        System.out.println("PENDING terminal: " + isTerminalStatus("PENDING"));
        System.out.println("RUNNING terminal: " + isTerminalStatus("RUNNING"));
        System.out.println("SUCCESS terminal: " + isTerminalStatus("SUCCESS"));
        System.out.println("FAILED terminal: " + isTerminalStatus("FAILED"));

        System.out.println("SUCCESS description: " + describeStatus("SUCCESS"));
        System.out.println("UNKNOWN description: " + describeStatus("UNKNOWN"));
    }

    public static boolean canTransit(String fromStatus, String toStatus) {
        if (fromStatus == null || toStatus == null) {
            return false;
        }

        switch (fromStatus) {
            case "PENDING":
                return "RUNNING".equals(toStatus);
            case "RUNNING":
                return "SUCCESS".equals(toStatus) || "FAILED".equals(toStatus);
            default:
                return false;
        }
    }

    public static boolean isTerminalStatus(String status) {
        return "SUCCESS".equals(status) || "FAILED".equals(status);
    }

    public static String describeStatus(String status) {
        if (status == null) {
            return "unknown status";
        }

        switch (status) {
            case "PENDING":
                return "task is waiting to run";
            case "RUNNING":
                return "task is running";
            case "SUCCESS":
                return "task finished successfully";
            case "FAILED":
                return "task failed";
            default:
                return "unknown status";
        }
    }

    private static void printTransit(String fromStatus, String toStatus) {
        System.out.println(
                fromStatus + " -> " + toStatus
                        + ", allowed=" + canTransit(fromStatus, toStatus)
        );
    }
}