package com.apiops.demo.order.fault;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Profile;
import org.springframework.stereotype.Service;

import java.util.Optional;

@Service
@Profile({"local", "test"})
@ConditionalOnProperty(name = "apiops.fault.enabled", havingValue = "true")
public class FaultService {

    private final Optional<SlowSqlMapper> slowSqlMapper;

    public FaultService(Optional<SlowSqlMapper> slowSqlMapper) {
        this.slowSqlMapper = slowSqlMapper;
    }

    /**
     * Executes {@code SELECT SLEEP(…)} through MyBatis/JDBC/MySQL.
     *
     * @param delayMs requested delay in milliseconds
     * @return the elapsed wall-clock time measured via {@link System#nanoTime()}
     */
    public long executeSlowSql(int delayMs) {
        double seconds = delayMs / 1000.0;
        long start = System.nanoTime();
        slowSqlMapper.orElseThrow(() -> new IllegalStateException(
                "Slow SQL fault requires a configured MySQL datasource"))
                .executeSleep(seconds);
        long end = System.nanoTime();
        return (end - start) / 1_000_000;
    }
}
