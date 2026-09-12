# Development environment

Use Java 21, Python 3.11+, uv, Node 22/npm and Docker with Compose v2. The Maven
Wrapper is included. Docker is required by the default Java Testcontainers tests.
The Python and Console default checks use deterministic inputs and do not require
paid model access.

## Verify a checkout

Run each block in its indicated directory:

```bash
cd java-apiops-platform
./mvnw clean verify
```

On Windows, use `.\mvnw.cmd clean verify`.

```bash
cd python-apiops-agentlab
uv sync --frozen
uv run pytest
uv run ruff check .
uv run python ../scripts/validate-schemas.py
```

```bash
cd apiops-console
npm ci
npm run build
npm run test:context
npm run test:console-execution
npm run test:diagnosis
npm run test:evaluation
npm run test:routes
npm run test:editor
npm run test:i18n
npm run test:reports
npm run verify:benchmark
```

Environment-gated live tests are reported as skipped unless their prerequisites are
provided. A skip is not a successful live check. Read a live script's inputs before
opting into real services or model calls.

## Infrastructure and configuration

From the repository root, copy `.env.example` to an ignored `.env`. Replace the JWT
secret with a locally generated value. Add your own credentials only to ignored local
configuration. Provider URLs in public templates use placeholders where a deployment
must be supplied; copying a template does not provision a model endpoint.

```bash
docker compose -f docker-compose.dev.yml up -d
docker compose -f docker-compose.dev.yml ps
```

The development Compose project binds services to loopback and creates MySQL, Redis
and RabbitMQ. A new MySQL volume initializes six module-owned schemas using
[dev-init.sql](../java-apiops-platform/ops/mysql/dev-init.sql). The default local
Compose database uses an empty root password and RabbitMQ uses its local development
account; configure credentials before any shared or non-local deployment. Existing
volumes do not rerun initialization scripts. Apply module schema changes to an
existing database without resetting its volume.

Docker Compose reads `.env`; Java does not automatically read it. Export the relevant
variables into the process or use your IDE run configuration. The source templates
list database, JWT, Redis, RabbitMQ, Tool Gateway, RAG and optional model settings.

After building, a manually configured Java platform can be started with:

```bash
java -jar java-apiops-platform/apiops-web/target/apiops-web-0.1.0-SNAPSHOT.jar --spring.profiles.active=local --server.port=19090
```

Run the demo-order service on port 18080 when using the demo scripts. Supply the
database settings for each Java application. RAG, model generation and diagnosis
need their respective optional service configuration.

## Python API and Console

```bash
cd python-apiops-agentlab
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Copy `apiops-console/.env.example` to its ignored `.env.local` and set the Java and
Python proxy targets to the ports actually running. Then:

```bash
cd apiops-console
npm run dev
```

The Console requires Java authentication and project membership for business pages.
Its Benchmark view reads saved public results. The Python result API can also be
inspected independently at `http://127.0.0.1:8000/api/v1/benchmark/results` without
starting a benchmark or calling a model.

For the prepared Windows stack, see [the launcher prerequisites](local-start.md).
For isolated presenter/viewer accounts and real example runs, see [HR demo](hr-demo.md).
