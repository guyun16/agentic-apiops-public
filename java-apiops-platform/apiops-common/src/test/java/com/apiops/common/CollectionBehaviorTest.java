package com.apiops.common;

import com.apiops.common.demo.TaskIdentity;
import org.junit.jupiter.api.Test;

import java.util.HashMap;
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class CollectionBehaviorTest {

    @Test
    void shouldTreatSameProjectAndTaskAsSameIdentity() {
        TaskIdentity task1 = new TaskIdentity("proj_001", "task_001");
        TaskIdentity task2 = new TaskIdentity("proj_001", "task_001");
        TaskIdentity task3 = new TaskIdentity("proj_001", "task_002");

        assertTrue(task1.equals(task2), "same projectId and taskId should be equal");
        assertFalse(task1.equals(task3), "different taskId should not be equal");
    }

    @Test
    void shouldDeduplicateSameTaskIdentityInHashSet() {
        TaskIdentity task1 = new TaskIdentity("proj_001", "task_001");
        TaskIdentity task2 = new TaskIdentity("proj_001", "task_001");
        TaskIdentity task3 = new TaskIdentity("proj_001", "task_002");

        Set<TaskIdentity> set = new HashSet<>();
        set.add(task1);
        set.add(task2);
        set.add(task3);

        assertEquals(2, set.size(), "HashSet should deduplicate same task identity");
    }

    @Test
    void shouldFindValueByEquivalentHashMapKey() {
        TaskIdentity task1 = new TaskIdentity("proj_001", "task_001");
        TaskIdentity task2 = new TaskIdentity("proj_001", "task_001");
        TaskIdentity task3 = new TaskIdentity("proj_001", "task_002");

        Map<TaskIdentity, String> map = new HashMap<>();
        map.put(task1, "RUNNING");

        assertEquals("RUNNING", map.get(task2), "HashMap should find value by equivalent key");
        assertNull(map.get(task3), "HashMap should not find value for different key");
    }
}
