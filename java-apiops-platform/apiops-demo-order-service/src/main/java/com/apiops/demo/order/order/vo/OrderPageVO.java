package com.apiops.demo.order.order.vo;

import io.swagger.v3.oas.annotations.media.ArraySchema;
import io.swagger.v3.oas.annotations.media.Schema;

import java.util.List;

@Schema(description = "Page response for order queries. No HTTP endpoint currently exposes this type; it remains documented for the order query model.")
public class OrderPageVO {

    @Schema(description = "Total number of matching orders.", example = "1",
            format = "int64", requiredMode = Schema.RequiredMode.REQUIRED)
    private long total;
    @Schema(description = "1-based page number returned by the service.", example = "1",
            format = "int64", requiredMode = Schema.RequiredMode.REQUIRED)
    private long pageNo;
    @Schema(description = "Page size returned by the service.", example = "20",
            format = "int64", requiredMode = Schema.RequiredMode.REQUIRED)
    private long pageSize;
    @ArraySchema(schema = @Schema(implementation = OrderSummaryVO.class),
            arraySchema = @Schema(description = "Matching orders."))
    private List<OrderSummaryVO> records;

    public long getTotal() { return total; }
    public void setTotal(long total) { this.total = total; }
    public long getPageNo() { return pageNo; }
    public void setPageNo(long pageNo) { this.pageNo = pageNo; }
    public long getPageSize() { return pageSize; }
    public void setPageSize(long pageSize) { this.pageSize = pageSize; }
    public List<OrderSummaryVO> getRecords() { return records; }
    public void setRecords(List<OrderSummaryVO> records) { this.records = records; }
}
