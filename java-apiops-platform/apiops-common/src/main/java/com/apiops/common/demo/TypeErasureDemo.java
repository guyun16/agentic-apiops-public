package com.apiops.common.demo;

import java.util.ArrayList;
import java.util.List;

public class TypeErasureDemo {

    public static void main(String[] args) {
        List<String> stringList = new ArrayList<>();
        List<Integer> integerList = new ArrayList<>();

        System.out.println("stringList class = " + stringList.getClass());
        System.out.println("integerList class = " + integerList.getClass());
        System.out.println("same class = " + (stringList.getClass() == integerList.getClass()));

        Box<String> stringBox = new Box<>("trace_001");
        Box<Integer> integerBox = new Box<>(100);

        System.out.println("stringBox value = " + stringBox.getValue());
        System.out.println("integerBox value = " + integerBox.getValue());


        // 下面这种判断不允许：
        // if (stringList instanceof List<String>) {
        //     System.out.println("List<String>");
        // }

        // 只能判断原始类型：
        if (stringList instanceof List) {
            System.out.println("stringList is a List");
        }
    }

    static class Box<T> {
        private final T value;

        Box(T value) {
            this.value = value;
        }

        T getValue() {
            return value;
        }
    }
}