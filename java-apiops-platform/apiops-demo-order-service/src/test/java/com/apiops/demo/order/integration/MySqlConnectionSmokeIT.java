package com.apiops.demo.order.integration;

import com.zaxxer.hikari.HikariDataSource;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.ActiveProfiles;

import javax.sql.DataSource;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.NONE)
@ActiveProfiles("local")
class MySqlConnectionSmokeIT {

    private static final String CONNECTION_IDENTITY_QUERY = """
            SELECT DATABASE() AS current_database,
                   CURRENT_USER() AS authenticated_account
            """;

    @Autowired
    private DataSource dataSource;

    @Test
    void connectsToExpectedDatabaseWithExpectedAccount() throws SQLException {
        assertThat(dataSource).isInstanceOf(HikariDataSource.class);
        String expectedUsername = System.getenv().getOrDefault(
                "APIOPS_ORDER_DB_USERNAME", "root");

        try (Connection connection = dataSource.getConnection()) {
            assertThat(connection.isValid(2)).isTrue();

            try (PreparedStatement statement = connection.prepareStatement(CONNECTION_IDENTITY_QUERY);
                 ResultSet resultSet = statement.executeQuery()) {
                assertThat(resultSet.next()).isTrue();
                assertThat(resultSet.getString("current_database")).isEqualTo("apiops_demo_order");
                assertThat(resultSet.getString("authenticated_account"))
                        .startsWith(expectedUsername + "@");
                assertThat(resultSet.next()).isFalse();
            }
        }
    }
}
