package com.apiops.common.demo;

public class ArrayAndPassDemo {
    public static void changeNumber(int value){
        value = 100;
    }
    public static void changeArrayFirstElment(String[] values){
        values[0] = "changed";
    }
    public static void replaceArrayFirst(String[] values){
        values = new String[]{"new_array_value"};
    }

    public static void main(String[] args) {
        int num = 10;
        changeNumber(num);
        System.out.println("num = " + num);

        String[] traceIds = {"trace_001","trace_002"};

        changeArrayFirstElment(traceIds);
        System.out.println("traceIds[0] = " + traceIds[0]);

        replaceArrayFirst(traceIds);
        System.out.println("traceIds[0] = " + traceIds[0]);

    }


}
