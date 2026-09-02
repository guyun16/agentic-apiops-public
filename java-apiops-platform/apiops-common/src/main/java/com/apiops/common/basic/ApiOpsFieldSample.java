package com.apiops.common.basic;

import java.math.BigDecimal;
import java.time.LocalDateTime;

public class ApiOpsFieldSample {

    private String projectId;
    private String apiId;
    private String caseId;
    private String traceId;
    private String requestId;
    private String toolCallId;

    private boolean success;
    private String code;
    private String message;

    private long total;
    private long pageNo;
    private long pageSize;

    private BigDecimal cost;
    private LocalDateTime createdAt;

    public ApiOpsFieldSample(
            String projectId,
            String apiId,
            String caseId,
            String traceId,
            String requestId,
            String toolCallId,
            boolean success,
            String code,
            String message,
            long total,
            long pageNo,
            long pageSize,
            BigDecimal cost,
            LocalDateTime createdAt
    ) {
        this.projectId = projectId;
        this.apiId = apiId;
        this.caseId = caseId;
        this.traceId = traceId;
        this.requestId = requestId;
        this.toolCallId = toolCallId;
        this.success = success;
        this.code = code;
        this.message = message;
        this.total = total;
        this.pageNo = pageNo;
        this.pageSize = pageSize;
        this.cost = cost;
        this.createdAt = createdAt;
    }

    public void printSummary() {
        System.out.println("projectId = " + projectId);
        System.out.println("apiId = " + apiId);
        System.out.println("caseId = " + caseId);
        System.out.println("traceId = " + traceId);
        System.out.println("toolCallId = " + toolCallId);
        System.out.println("success = " + success);
        System.out.println("code = " + code);
        System.out.println("message = " + message);
        System.out.println("total = " + total);
        System.out.println("cost = " + cost);
        System.out.println("createdAt = " + createdAt);
    }

    public static void main(String[] args) {
        ApiOpsFieldSample sample = new ApiOpsFieldSample(
                "proj_001",
                "api_create_order",
                "case_missing_token",
                "trace_001",
                "req_001",
                "tool_call_001",
                true,
                "SUCCESS",
                "ok",
                10000000000L,
                1L,
                20L,
                new BigDecimal("0.10"),
                LocalDateTime.now()
        );

        sample.printSummary();
    }
}