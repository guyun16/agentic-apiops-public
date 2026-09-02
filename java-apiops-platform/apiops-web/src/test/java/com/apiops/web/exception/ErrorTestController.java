package com.apiops.web.exception;

import com.apiops.common.enums.ErrorCode;
import com.apiops.common.exception.BusinessException;
import com.apiops.common.result.Result;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/test/errors")
class ErrorTestController {

    @GetMapping("/business")
    Result<Void> businessError() {
        throw new BusinessException(ErrorCode.TASK_STATUS_INVALID, "task status conflict");
    }

    @GetMapping("/unknown")
    Result<Void> unknownError() {
        throw new IllegalStateException("sensitive internal detail");
    }
}
