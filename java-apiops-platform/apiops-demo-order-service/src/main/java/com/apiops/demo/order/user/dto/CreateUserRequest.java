package com.apiops.demo.order.user.dto;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;

@Schema(description = "Request to create a demo user.")
public class CreateUserRequest {

    @NotBlank
    @Size(max = 64)
    @Schema(description = "Stable user business number.", example = "usr_demo_001", maxLength = 64,
            requiredMode = Schema.RequiredMode.REQUIRED)
    private String userNo;

    @NotBlank
    @Size(max = 128)
    @Schema(description = "User display name.", example = "Demo User 001", maxLength = 128,
            requiredMode = Schema.RequiredMode.REQUIRED)
    private String userName;

    public String getUserNo() {
        return userNo;
    }

    public void setUserNo(String userNo) {
        this.userNo = userNo;
    }

    public String getUserName() {
        return userName;
    }

    public void setUserName(String userName) {
        this.userName = userName;
    }
}
