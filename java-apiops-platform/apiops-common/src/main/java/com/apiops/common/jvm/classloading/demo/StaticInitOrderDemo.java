package com.apiops.common.jvm.classloading.demo;

public class StaticInitOrderDemo {

    public static void main(String[] args) {
        System.out.println("main started");
        System.out.println("Child value = " + Child.value);
        System.out.println("Child value again = " + Child.value);
    }

    static class Parent {
        static int parentValue = initParentValue();

        static {
            System.out.println("Parent static block");
        }

        private static int initParentValue() {
            System.out.println("Parent static field");
            return 1;
        }
    }

    static class Child extends Parent {
        static int value = initChildValue();

        static {
            System.out.println("Child static block");
        }

        private static int initChildValue() {
            System.out.println("Child static field");
            return 2;
        }
    }
}