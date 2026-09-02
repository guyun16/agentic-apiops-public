package com.apiops.common.jvm.classloading.demo;

public class ClassLoaderDemo {

    public static void main(String[] args) {
        printClassLoader("String", String.class);
        printClassLoader("ClassLoaderDemo", ClassLoaderDemo.class);

        ClassLoader appClassLoader = ClassLoaderDemo.class.getClassLoader();
        System.out.println("Application ClassLoader = " + appClassLoader);
        System.out.println("Parent of Application ClassLoader = " + appClassLoader.getParent());
        System.out.println("Parent of Platform ClassLoader = " + appClassLoader.getParent().getParent());
    }

    private static void printClassLoader(String name, Class<?> clazz) {
        System.out.println(name + " classLoader = " + clazz.getClassLoader());
    }
}