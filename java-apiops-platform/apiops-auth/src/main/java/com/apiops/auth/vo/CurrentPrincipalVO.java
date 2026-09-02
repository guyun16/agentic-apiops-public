package com.apiops.auth.vo;

public record CurrentPrincipalVO(
        Long userId,
        String username
) {
}
