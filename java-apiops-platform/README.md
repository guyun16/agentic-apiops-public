# Java APIOps Platform

Java 21 / Spring Boot platform for OpenAPI metadata, TestCase DSL validation,
asynchronous execution, assertions, reports, authentication, project isolation,
RAG and the guarded Tool Gateway. Java owns authoritative execution facts; Python
consumes the project-scoped APIs.

Run `./mvnw clean verify` here, or `.\mvnw.cmd clean verify` on Windows. Docker is
required for the default Testcontainers tests. External-service and real-model
checks have separate gates; skipped tests are not successful live validation.

See [development setup](../docs/README-dev-env.md), [the project overview](../README.md)
and [HTTP snapshot semantics](../docs/http-exchange-snapshots.md). Database schemas
remain owned by their modules and configuration secrets belong in local environment
variables, never committed defaults.
