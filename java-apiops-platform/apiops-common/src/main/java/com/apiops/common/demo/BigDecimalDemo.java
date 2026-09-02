package com.apiops.common.demo;

import java.math.BigDecimal;

public class BigDecimalDemo {

    public static void main(String[] args) {
        double doubleResult = 0.1 + 0.2;
        System.out.println("double result = " + doubleResult);

        BigDecimal wrong = new BigDecimal(0.1);
        System.out.println("new BigDecimal(0.1) = " + wrong);

        BigDecimal right = new BigDecimal("0.1").add(new BigDecimal("0.2"));
        System.out.println("BigDecimal string result = " + right);
    }
}