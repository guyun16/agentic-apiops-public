package com.apiops.auth.controller;

import com.apiops.auth.application.AuthenticationService;
import com.apiops.auth.dto.LoginRequest;
import com.apiops.auth.security.ApiOpsPrincipal;
import com.apiops.auth.vo.CurrentPrincipalVO;
import com.apiops.auth.vo.LoginVO;
import com.apiops.common.enums.ErrorCode;
import com.apiops.common.exception.BusinessException;
import com.apiops.common.result.Result;
import org.springframework.security.access.AccessDeniedException;
import org.springframework.security.core.Authentication;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/auth")
public final class AuthController {

    private final AuthenticationService authenticationService;

    public AuthController(AuthenticationService authenticationService) {
        this.authenticationService = authenticationService;
    }

    @PostMapping("/login")
    public Result<LoginVO> login(@RequestBody(required = false) LoginRequest request) {
        validate(request);
        return Result.success(authenticationService.login(request));
    }

    @GetMapping("/me")
    public Result<CurrentPrincipalVO> currentPrincipal(Authentication authentication) {
        if (!(authentication.getPrincipal() instanceof ApiOpsPrincipal principal)) {
            throw new AccessDeniedException("Authenticated ApiOpsPrincipal required");
        }
        return Result.success(new CurrentPrincipalVO(principal.getUserId(), principal.getUsername()));
    }

    private void validate(LoginRequest request) {
        if (request == null
                || request.getUsername() == null
                || request.getUsername().isBlank()
                || request.getPassword() == null
                || request.getPassword().isBlank()) {
            throw new BusinessException(ErrorCode.PARAM_INVALID);
        }
    }
}
