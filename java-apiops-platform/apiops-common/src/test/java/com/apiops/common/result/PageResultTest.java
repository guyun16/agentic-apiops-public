package com.apiops.common.result;

import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

public class PageResultTest {

    @Test
    void testOfShouldKeepPageFields() {
        PageResult<String> page = PageResult.of(
                2,
                1,
                10,
                List.of("api_001", "api_002")
        );

        assertEquals(2L, page.getTotal(), "total should be 2");
        assertEquals(1L, page.getPageNo(), "pageNo should be 1");
        assertEquals(10L, page.getPageSize(), "pageSize should be 10");
        assertEquals(2, page.getRecords().size(), "records size should be 2");
        assertEquals("api_001", page.getRecords().get(0), "first record should be api_001");
    }

    @Test
    void testEmptyShouldReturnEmptyRecords() {
        PageResult<String> page = PageResult.empty(1, 10);

        assertEquals(0L, page.getTotal(), "empty total should be 0");
        assertEquals(1L, page.getPageNo(), "empty pageNo should be 1");
        assertEquals(10L, page.getPageSize(), "empty pageSize should be 10");
        assertTrue(page.getRecords().isEmpty(), "empty records should be empty list");
    }

    @Test
    void testNullRecordsShouldBecomeEmptyList() {
        PageResult<String> page = PageResult.of(0, 1, 10, null);

        assertNotNull(page.getRecords(), "records should not be null");
        assertTrue(page.getRecords().isEmpty(), "null records should become empty list");
    }

    @Test
    void testGenericRecordsShouldNotNeedCast() {
        PageResult<Long> page = PageResult.of(
                2,
                1,
                10,
                List.of(100L, 200L)
        );

        Long first = page.getRecords().get(0);

        assertEquals(100L, first, "first long record should be 100");
    }

}
