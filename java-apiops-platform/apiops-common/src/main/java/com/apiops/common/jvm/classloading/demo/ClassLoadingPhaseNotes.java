package com.apiops.common.jvm.classloading.demo;

public class ClassLoadingPhaseNotes {
    private static int count = 10;
    static {
        System.out.println("static block executed = " + count);
    }

    public static void main(String[] args) {
        System.out.println("main started");
        System.out.println("count = " + count);
    }
}
