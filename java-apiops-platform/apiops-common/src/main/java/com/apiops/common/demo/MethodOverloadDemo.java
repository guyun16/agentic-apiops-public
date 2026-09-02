package com.apiops.common.demo;

public class MethodOverloadDemo {
    public static void printValue(String value){
        System.out.println("String value = " + value);
    }
    public static void printValue(long value){
        System.out.println("long value = " + value);
    }
    public static void printValue(boolean value){
        System.out.println("boolean value = "+ value);
    }

    public static void main(String[] args) {
        printValue("trace_001");
        printValue(100L);
        printValue(true);
    }
}
