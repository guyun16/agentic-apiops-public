package com.apiops.demo.order.fault;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("local")
@EnabledIfEnvironmentVariable(named = "APIOPS_ORDER_DB_URL", matches = ".+")
class SlowSqlMySqlTest {

    @Autowired
    private FaultService faultService;

    @Autowired
    private SlowSqlMapper slowSqlMapper;

    @Test
    void executesParameterizedSleepThroughMyBatisJdbcAndMySql() {
        assertThat(slowSqlMapper.executeSleep(0.1)).isZero();

        long elapsedMs = faultService.executeSlowSql(100);

        assertThat(elapsedMs).isGreaterThanOrEqualTo(80L);
    }
}
