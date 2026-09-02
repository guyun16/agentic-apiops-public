package com.apiops.common.demo;

public class LogicalOperatorDemo {

    public static void main(String[] args) {
        System.out.println("safe null check A0001: " + isClientErrorSafe("A0001"));
        System.out.println("safe null check null: " + isClientErrorSafe(null));

        System.out.println("blank check null: " + isBlank(null));
        System.out.println("blank check empty: " + isBlank(""));
        System.out.println("blank check text: " + isBlank("A0001"));

        System.out.println("status transition: " + canTransit("RUNNING", "SUCCESS"));
        System.out.println("status transition null: " + canTransit(null, "SUCCESS"));

        // 不要直接放开这行。放开后会触发 NullPointerException。
        // System.out.println("unsafe null check: " + isClientErrorUnsafe(null));
    }

    public static boolean isClientErrorSafe(String errorCode) {
        return errorCode != null && errorCode.startsWith("A");
    }

    public static boolean isClientErrorUnsafe(String errorCode) {
        return errorCode != null & errorCode.startsWith("A");
    }

    public static boolean isBlank(String value) {
        return value == null || value.length() == 0;
    }

    public static boolean canTransit(String fromStatus, String toStatus) {
        return "RUNNING".equals(fromStatus)
                && ("SUCCESS".equals(toStatus) || "FAILED".equals(toStatus));
    }
}