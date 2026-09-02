package com.apiops.web.system.converter;

import com.apiops.web.system.domain.SystemInfo;
import com.apiops.web.system.vo.SystemInfoVO;
import org.springframework.stereotype.Component;

@Component
public class SystemInfoConverter {

    public SystemInfoVO toVO(SystemInfo source) {
        return new SystemInfoVO(
                source.serviceName(),
                source.version(),
                source.status(),
                source.generatedAt()
        );
    }
}
