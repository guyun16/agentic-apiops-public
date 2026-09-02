package com.apiops.web;

import com.apiops.outside.OutsideScanFixture;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.NoSuchBeanDefinitionException;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.ApplicationContext;
import org.springframework.test.context.ActiveProfiles;

import static org.junit.jupiter.api.Assertions.assertThrows;

@SpringBootTest
@ActiveProfiles("test")
class ComponentScanBoundaryTest {

    @Autowired
    private ApplicationContext applicationContext;

    @Test
    void shouldNotScanComponentOutsideWebRootPackage() {
        assertThrows(
                NoSuchBeanDefinitionException.class,
                () -> applicationContext.getBean(
                        OutsideScanFixture.class
                )
        );
    }
}
