package com.apiops.demo.order.user.vo;

import io.swagger.v3.oas.annotations.media.Schema;

import java.time.LocalDateTime;

@Schema(description = "User view. Authentication credentials and persistence-only fields are not exposed.")
public class UserVO {

    @Schema(description = "User primary key.", example = "1", format = "int64",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private Long id;
    @Schema(description = "Stable user business number.", example = "usr_001",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private String userNo;
    @Schema(description = "User display name.", example = "Demo User 001",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private String userName;
    @Schema(description = "User lifecycle status.", allowableValues = {"ENABLED", "DISABLED"},
            example = "ENABLED", requiredMode = Schema.RequiredMode.REQUIRED)
    private String status;
    @Schema(description = "Creation time in ISO-8601 date-time format.",
            example = "2025-01-01T00:00:00", format = "date-time",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private LocalDateTime createdAt;
    @Schema(description = "Last update time in ISO-8601 date-time format.",
            example = "2025-01-01T00:00:00", format = "date-time",
            requiredMode = Schema.RequiredMode.REQUIRED)
    private LocalDateTime updatedAt;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public String getUserNo() { return userNo; }
    public void setUserNo(String userNo) { this.userNo = userNo; }
    public String getUserName() { return userName; }
    public void setUserName(String userName) { this.userName = userName; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public LocalDateTime getCreatedAt() { return createdAt; }
    public void setCreatedAt(LocalDateTime createdAt) { this.createdAt = createdAt; }
    public LocalDateTime getUpdatedAt() { return updatedAt; }
    public void setUpdatedAt(LocalDateTime updatedAt) { this.updatedAt = updatedAt; }
}
