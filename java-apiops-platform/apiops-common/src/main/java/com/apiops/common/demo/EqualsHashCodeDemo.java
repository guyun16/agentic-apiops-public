package com.apiops.common.demo;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

public class EqualsHashCodeDemo {

    public static void main(String[] args) {
        TaskIdentity task1 = new TaskIdentity("proj_001", "task_001");
        TaskIdentity task2 = new TaskIdentity("proj_001", "task_001");
        TaskIdentity task3 = new TaskIdentity("proj_001", "task_002");

        System.out.println("task1 = " + task1);
        System.out.println("task2 = " + task2);
        System.out.println("task3 = " + task3);

        System.out.println("task1 == task2: " + (task1 == task2));
        System.out.println("task1.equals(task2): " + task1.equals(task2));
        System.out.println("task1.equals(task3): " + task1.equals(task3));

        System.out.println("task1.hashCode(): " + task1.hashCode());
        System.out.println("task2.hashCode(): " + task2.hashCode());
        System.out.println("task3.hashCode(): " + task3.hashCode());

        Set<TaskIdentity> set = new HashSet<>();
        set.add(task1);
        set.add(task2);
        set.add(task3);

        System.out.println("HashSet size: " + set.size());

        Map<TaskIdentity, String> map = new HashMap<>();
        map.put(task1, "RUNNING");

        System.out.println("map.get(task2): " + map.get(task2));
        System.out.println("map.get(task3): " + map.get(task3));
    }
}