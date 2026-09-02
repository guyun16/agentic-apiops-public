# Stage 5 Day 3 authentication seed proof

The local-only `demo-user` test credential is `stage5-demo-password`.
<!-- demo-password: stage5-demo-password -->
The integration test verifies that this demonstration password matches the
BCrypt hash in `src/main/resources/db/auth-seed.sql`; it is not a real
credential and must not be reused outside local tests.
