package com.apiops.demo.order.persistence.mapper;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Configuration;

@Configuration(proxyBeanMethods = false)
@ConditionalOnProperty(name = "spring.datasource.url")
@MapperScan({
        "com.apiops.demo.order.user.mapper",
        "com.apiops.demo.order.product.mapper",
        "com.apiops.demo.order.inventory.mapper",
        "com.apiops.demo.order.coupon.mapper",
        "com.apiops.demo.order.order.mapper",
        "com.apiops.demo.order.payment.mapper",
        "com.apiops.demo.order.fault"
})
public class MybatisMapperConfiguration {
}
