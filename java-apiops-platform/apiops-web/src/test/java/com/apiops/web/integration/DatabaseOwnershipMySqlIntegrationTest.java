package com.apiops.web.integration;

import org.junit.jupiter.api.Assumptions;
import org.junit.jupiter.api.Test;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.ResultSet;
import java.sql.Statement;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

import static org.junit.jupiter.api.Assertions.assertEquals;

class DatabaseOwnershipMySqlIntegrationTest {

    @Test
    void shouldKeepEveryLocalDatabaseInsideItsSchemaBoundary() throws Exception {
        List<DatabaseSpec> databases = List.of(
                new DatabaseSpec(
                        "apiops_auth", "APIOPS_AUTH_DB",
                        Set.of(
                                "auth_user", "auth_role", "auth_permission",
                                "auth_user_role", "auth_role_permission",
                                "apiops_project", "apiops_project_member"
                        )),
                new DatabaseSpec(
                        "apiops_openapi", "APIOPS_OPENAPI_DB",
                        Set.of(
                                "api_document", "api_endpoint", "api_parameter",
                                "api_request_schema", "api_response_schema", "api_example"
                        )),
                new DatabaseSpec(
                        "apiops_runner", "APIOPS_RUNNER_DB",
                        Set.of("test_task", "test_run", "test_batch", "test_batch_run",
                                "case_result", "step_result")),
                new DatabaseSpec(
                        "apiops_rag", "APIOPS_RAG_DB",
                        Set.of("rag_document", "rag_document_chunk")),
                new DatabaseSpec(
                        "apiops_demo_order", "APIOPS_ORDER_DB",
                        Set.of(
                                "demo_user", "demo_product", "demo_inventory",
                                "demo_order", "demo_order_item", "demo_payment",
                                "demo_payment_callback", "demo_coupon", "demo_user_coupon"
                        ))
        );

        Assumptions.assumeTrue(
                databases.stream().allMatch(DatabaseSpec::environmentIsComplete),
                "Set each module's URL, username, and password variables"
        );
        Class.forName("com.mysql.cj.jdbc.Driver");

        for (DatabaseSpec database : databases) {
            try (Connection connection = DriverManager.getConnection(
                    database.url(), database.username(), database.password())) {
                assertEquals(database.catalog(), connection.getCatalog());
                assertEquals(database.allowedTables(), tables(connection));
            }
        }
    }

    private static Set<String> tables(Connection connection) throws Exception {
        Set<String> tables = new LinkedHashSet<>();
        try (Statement statement = connection.createStatement();
             ResultSet resultSet = statement.executeQuery("SHOW TABLES")) {
            while (resultSet.next()) {
                tables.add(resultSet.getString(1));
            }
        }
        return Set.copyOf(tables);
    }

    private record DatabaseSpec(
            String catalog,
            String environmentPrefix,
            Set<String> allowedTables
    ) {
        String url() {
            return System.getenv(environmentPrefix + "_URL");
        }

        String username() {
            return System.getenv(environmentPrefix + "_USERNAME");
        }

        String password() {
            return System.getenv(environmentPrefix + "_PASSWORD");
        }

        boolean environmentIsComplete() {
            return url() != null && username() != null && password() != null;
        }
    }
}
