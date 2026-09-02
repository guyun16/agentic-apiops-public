package com.apiops.demo.order;

import com.apiops.demo.order.fault.FaultProperties;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.boot.context.properties.EnableConfigurationProperties;

@SpringBootApplication
@EnableConfigurationProperties(FaultProperties.class)
public class DemoOrderApplication {

    public static void main(String[] args) {

        SpringApplication.run(DemoOrderApplication.class, args);
    }
}
