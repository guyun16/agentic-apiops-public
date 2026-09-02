package com.apiops.demo.order.product.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.Size;
import org.springdoc.core.annotations.ParameterObject;

@Schema(description = "Product catalog page filters.")
@ParameterObject
public class ProductPageQuery {

    @Min(1)
    @Schema(description = "1-based page number.", example = "1", defaultValue = "1", minimum = "1")
    private long pageNo = 1;

    @Min(1)
    @Max(100)
    @Schema(description = "Number of records per page.", example = "20", defaultValue = "20",
            minimum = "1", maximum = "100")
    private long pageSize = 20;

    @Size(max = 64)
    @Schema(description = "Optional exact product business-number filter.", example = "prd_001",
            maxLength = 64, nullable = true)
    private String productNo;

    @Size(max = 128)
    @Schema(description = "Optional product-name contains filter.", example = "Demo Product",
            maxLength = 128, nullable = true)
    private String productName;

    @Size(max = 32)
    @Schema(description = "Optional status filter. The service applies it as an exact persisted-status filter.",
            example = "ON_SALE", maxLength = 32, nullable = true)
    private String status;

    public long getPageNo() { return pageNo; }
    public void setPageNo(long pageNo) { this.pageNo = pageNo; }
    public long getPageSize() { return pageSize; }
    public void setPageSize(long pageSize) { this.pageSize = pageSize; }
    public String getProductNo() { return productNo; }
    public void setProductNo(String productNo) { this.productNo = productNo; }
    public String getProductName() { return productName; }
    public void setProductName(String productName) { this.productName = productName; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
}
