package com.apiops.common.demo;

public class GenericDemo {

    public static void main(String[] args) {
        Box<String> stringBox = new Box<>("trace_001");
        String traceId = stringBox.getValue();
        System.out.println("traceId=" + traceId);

        Box<Integer> intBox = new Box<>(100);
        Integer count = intBox.getValue();
        System.out.println("count=" + count);

        ObjectBox objectBox = new ObjectBox("run_001");

        // 这行编译能过，但运行会出错：
        // Integer wrongValue = (Integer) objectBox.getValue();

        String runId = (String) objectBox.getValue();
        System.out.println("runId=" + runId);
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

    static class ObjectBox {
        private final Object value;

        ObjectBox(Object value) {
            this.value = value;
        }

        Object getValue() {
            return value;
        }
    }
}