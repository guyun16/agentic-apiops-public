package com.apiops.common.basic;

import java.math.BigDecimal;

public class BigDecimalPitfallDemo {

    public static void main(String[] args) {
        demoDoublePrecisionProblem();
        demoWrongBigDecimalConstructor();
        demoCorrectBigDecimalConstructor();
        demoEqualsAndCompareTo();
        demoApiOpsCostCalculation();
    }

    private static void demoDoublePrecisionProblem() {
        double a = 0.1;
        double b = 0.2;
        double sum = a + b;

        System.out.println("double 0.1 + 0.2 = " + sum);
    }

    private static void demoWrongBigDecimalConstructor() {
        BigDecimal value = new BigDecimal(0.1);

        System.out.println("new BigDecimal(0.1) = " + value);
    }

    private static void demoCorrectBigDecimalConstructor() {
        BigDecimal a = new BigDecimal("0.10");
        BigDecimal b = new BigDecimal("0.20");
        BigDecimal sum = a.add(b);

        System.out.println("new BigDecimal(\"0.10\") + new BigDecimal(\"0.20\") = " + sum);
    }

    private static void demoEqualsAndCompareTo() {
        BigDecimal a = new BigDecimal("0.10");
        BigDecimal b = new BigDecimal("0.100");

        System.out.println("BigDecimal equals result = " + a.equals(b));
        System.out.println("BigDecimal compareTo result = " + a.compareTo(b));
    }

    private static void demoApiOpsCostCalculation() {
        BigDecimal modelCost = new BigDecimal("0.015");
        BigDecimal toolCallCost = new BigDecimal("0.003");
        BigDecimal evaluationCost = new BigDecimal("0.002");

        BigDecimal totalCost = modelCost.add(toolCallCost).add(evaluationCost);

        System.out.println("APIOps task total cost = " + totalCost);
    }
}