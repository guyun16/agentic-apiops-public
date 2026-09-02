package com.apiops.common.result;

import java.util.Collections;
import java.util.List;

/**
 * Unified pagination result wrapper for list-style platform responses.
 */
public class PageResult<T> {

    private final long total;
    private final long pageNo;
    private final long pageSize;
    private final List<T> records;

    private PageResult(long total, long pageNo, long pageSize, List<T> records) {
        this.total = total;
        this.pageNo = pageNo;
        this.pageSize = pageSize;
        this.records = records == null ? Collections.emptyList() : records;
    }

    public static <T> PageResult<T> of(long total, long pageNo, long pageSize, List<T> records) {
        return new PageResult<>(total, pageNo, pageSize, records);
    }

    public static <T> PageResult<T> empty(long pageNo, long pageSize) {
        return new PageResult<>(0, pageNo, pageSize, Collections.emptyList());
    }

    public long getTotal() {
        return total;
    }

    public long getPageNo() {
        return pageNo;
    }

    public long getPageSize() {
        return pageSize;
    }

    public List<T> getRecords() {
        return records;
    }
}
