package com.apiops.common.demo;

import java.util.function.Predicate;

public class LambdaDemo {

    public static void main(String[] args) {
        Predicate<String> isSuccess = code -> "SUCCESS".equals(code);

        System.out.println(isSuccess.test("SUCCESS"));
        System.out.println(isSuccess.test("FAILED"));
    }
}