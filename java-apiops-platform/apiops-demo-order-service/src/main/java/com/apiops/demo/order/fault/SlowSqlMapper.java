package com.apiops.demo.order.fault;

import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Profile;

/**
 * Dedicated mapper for fault-injection SQL.
 * Uses MySQL {@code SELECT SLEEP(n)} which blocks the connection
 * for approximately {@code n} seconds.
 */
@Profile({"local", "test"})
@ConditionalOnProperty(name = "apiops.fault.enabled", havingValue = "true")
public interface SlowSqlMapper {

    @Select("SELECT SLEEP(#{delaySeconds})")
    Integer executeSleep(@Param("delaySeconds") double delaySeconds);
}
