package com.apiops.common.basic;
import java.math.BigDecimal;

public class FieldTypeDemo {

    public static void main(String[] args) {
        demoBasicType();
        demoReferenceType();
        demoBoxingAndUnboxing();
        demoNullUnboxingRisk();
        demoStringCompare();
        demoIntLongRange();
        demoPaginationDefaultValue();
        demoDoublePrecision();
        demoBigDecimal();
        demoBigDecimalCompare();
    }

    private static void demoBasicType() {
        int pageSize = 20;
        long total = 10000000000L;
        boolean success = true;

        System.out.println("pageSize = " + pageSize);
        System.out.println("total = " + total);
        System.out.println("success = " + success);
    }

    private static void demoReferenceType() {
        String traceId = "trace_001";

        System.out.println("traceId = " + traceId);
        System.out.println("traceId length = " + traceId.length());
    }

    private static void demoBoxingAndUnboxing() {
        Integer boxedPageSize = 20;     // 自动装箱
        int pageSize = boxedPageSize;   // 自动拆箱

        System.out.println("boxedPageSize = " + boxedPageSize);
        System.out.println("pageSize = " + pageSize);
    }

    private static void demoNullUnboxingRisk() {
        Integer total = null;

        System.out.println("total is null: " + (total == null));

        // 下面这行如果打开，会抛出 NullPointerException
        // int realTotal = total;

        if (total != null && total > 0) {
            System.out.println("has data");
        } else {
            System.out.println("no data or total is null");
        }
    }
    private static void demoStringCompare() {
        String traceIdFromRequest = new String("trace_001");
        String traceIdFromResponse = new String("trace_001");

        System.out.println("== compare result: " + (traceIdFromRequest == traceIdFromResponse));
        System.out.println("equals compare result: " + traceIdFromRequest.equals(traceIdFromResponse));

        String nullableTraceId = null;

        System.out.println("constant equals nullable: " + "trace_001".equals(nullableTraceId));

        String leftTraceId = null;
        String rightTraceId = null;

        System.out.println("Objects.equals result: " + java.util.Objects.equals(leftTraceId, rightTraceId));
    }
    public static void demoIntLongRange() {
        int maxInt = Integer.MAX_VALUE;
        int overflow  = maxInt+1;
        long largeTotal = 10000000000L;

        System.out.println("maxInt = " + maxInt);
        System.out.println("overflow = " + overflow);
        System.out.println("largeTotal = " + largeTotal);
    }
    public static void demoPaginationDefaultValue() {
        Long inputPageNo = null;
        Long inputPageSize = null;

        long pageNo = inputPageNo == null ? 1L :inputPageNo;
        long pageSize = inputPageSize == null ? 20L :inputPageSize;
        long total = 0L;

        System.out.println("pageNo = " + pageNo);
        System.out.println("pageSize = " + pageSize);
        System.out.println("total = " + total);
    }
    private static void demoDoublePrecision() {
        double a = 0.1;
        double b = 0.2;
        double sum = a+b;

        System.out.println("double sum =  " + sum);
    }

    private static void demoBigDecimal() {
        BigDecimal a = new BigDecimal("0.10");
        BigDecimal b = new BigDecimal("0.20");

        BigDecimal sum = a.add(b);
        System.out.println("BigDecimal sum = " + sum);
    }
    private static void demoBigDecimalCompare() {
        BigDecimal a = new BigDecimal("0.10");
        BigDecimal b = new BigDecimal("0.100");

        System.out.println("BigDecimal equals: " + a.equals(b));
        System.out.println("BigDecimal compareTo: " + a.compareTo(b));
    }
}