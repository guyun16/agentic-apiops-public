package com.apiops.web.system.controller;

import com.apiops.common.result.Result;
import com.apiops.web.system.application.SystemQueryService;
import com.apiops.web.system.converter.SystemInfoConverter;
import com.apiops.web.system.domain.SystemInfo;
import com.apiops.web.system.vo.SystemInfoVO;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/v1/system")
public class SystemController {

    private final SystemQueryService systemQueryService;
    private final SystemInfoConverter systemInfoConverter;

    public SystemController(
            SystemQueryService systemQueryService,
            SystemInfoConverter systemInfoConverter
    ) {
        this.systemQueryService = systemQueryService;
        this.systemInfoConverter = systemInfoConverter;
    }

    @GetMapping("/info")
    public Result<SystemInfoVO> info() {
        SystemInfo systemInfo = systemQueryService.query();
        SystemInfoVO systemInfoVO = systemInfoConverter.toVO(systemInfo);
        return Result.success(systemInfoVO);
    }
}
