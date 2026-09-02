package com.apiops.demo.order.order.query;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;

public class OrderPageQuery {

    @Min(1)
    private long pageNo = 1;

    @Min(1)
    @Max(100)
    private long pageSize = 20;

    private Long userId;
    private String status;

    public long getPageNo() { return pageNo; }
    public void setPageNo(long pageNo) { this.pageNo = pageNo; }
    public long getPageSize() { return pageSize; }
    public void setPageSize(long pageSize) { this.pageSize = pageSize; }
    public Long getUserId() { return userId; }
    public void setUserId(Long userId) { this.userId = userId; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
}
