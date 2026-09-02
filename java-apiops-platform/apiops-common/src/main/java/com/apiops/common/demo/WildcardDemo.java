package com.apiops.common.demo;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;

public class WildcardDemo {

    public static void main(String[] args) {
        List<Integer> integers = Arrays.asList(1, 2, 3);
        List<Double> doubles = Arrays.asList(1.1, 2.2, 3.3);

        printNumbers(integers);
        printNumbers(doubles);

        List<Number> numberList = new ArrayList<>();
        addIntegers(numberList);
        System.out.println(numberList);

        List<Object> objectList = new ArrayList<>();
        addIntegers(objectList);
        System.out.println(objectList);

        printUnknown(Arrays.asList("trace_001", "trace_002"));
        printUnknown(Arrays.asList(100, 200));
    }

    private static void printNumbers(List<? extends Number> numbers) {
        for (Number number : numbers) {
            System.out.println("number=" + number);
        }

        // 不允许：
        // numbers.add(1);
    }

    private static void addIntegers(List<? super Integer> list) {
        list.add(1);
        list.add(2);

        Object value = list.get(0);
        System.out.println("first value as Object=" + value);

        // 不允许：
        // Integer integer = list.get(0);
    }

    private static void printUnknown(List<?> list) {
        for (Object item : list) {
            System.out.println("item=" + item);
        }

        // 不允许：
        // list.add("abc");
    }
}