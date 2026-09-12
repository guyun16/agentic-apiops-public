-- Local-only bootstrap for the six logical MySQL schemas used by the Java Platform.
-- The schema files remain owned by their modules; this file only selects the
-- database before sourcing those existing repeatable scripts.

CREATE DATABASE IF NOT EXISTS apiops_auth
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS apiops_openapi
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS apiops_runner
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS apiops_tool_gateway
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS apiops_rag
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
CREATE DATABASE IF NOT EXISTS apiops_demo_order
    CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;

USE apiops_auth;
SOURCE /docker-entrypoint-initdb.d/schema/auth-schema.sql
SOURCE /docker-entrypoint-initdb.d/schema/auth-seed.sql

USE apiops_openapi;
SOURCE /docker-entrypoint-initdb.d/schema/openapi-schema.sql

USE apiops_runner;
SOURCE /docker-entrypoint-initdb.d/schema/runner-schema.sql

USE apiops_tool_gateway;
SOURCE /docker-entrypoint-initdb.d/schema/tool-gateway-schema.sql

USE apiops_rag;
SOURCE /docker-entrypoint-initdb.d/schema/rag-schema.sql

USE apiops_demo_order;
SOURCE /docker-entrypoint-initdb.d/schema/demo-order-schema.sql
SOURCE /docker-entrypoint-initdb.d/schema/demo-order-seed.sql
