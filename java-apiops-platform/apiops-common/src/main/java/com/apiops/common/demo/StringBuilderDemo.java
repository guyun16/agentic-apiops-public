package com.apiops.common.demo;

public class StringBuilderDemo {

    public static void main(String[] args) {
        StringBuilder builder = new StringBuilder();

        builder.append("traceId=").append("trace_001")
                .append(", runId=").append("run_001")
                .append(", status=").append("ASSERTION_FAILED");

        String message = builder.toString();

        System.out.println(message);
    }
}