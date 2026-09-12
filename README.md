# Agentic APIOps

Production-style API testing and diagnosis platform with Java execution authority, Python Agent workflows, a guarded Tool Gateway, tracing/evaluation, and a React console.

[中文说明](zh/README.md) · [Documentation](docs/README.md) · [HR demo](docs/hr-demo.md) · [Benchmark results](artifacts/benchmark/portfolio-manifest.json)

[![Java CI](https://github.com/guyun16/agentic-apiops-public/actions/workflows/java-ci.yml/badge.svg)](https://github.com/guyun16/agentic-apiops-public/actions/workflows/java-ci.yml)
![Java 21](https://img.shields.io/badge/Java-21-007396?logo=openjdk&logoColor=white)
![Spring Boot](https://img.shields.io/badge/Spring%20Boot-3.5-6DB33F?logo=springboot&logoColor=white)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white)
![LangGraph](https://img.shields.io/badge/LangGraph-1F2937?logo=langchain&logoColor=white)
![React](https://img.shields.io/badge/React-18-61DAFB?logo=react&logoColor=111827)
![TypeScript](https://img.shields.io/badge/TypeScript-5-3178C6?logo=typescript&logoColor=white)

## Why this project is different

- Java owns deterministic execution, security, and authoritative `TestReport` facts.
- Python AgentLab owns TestCase generation, diagnosis, tool orchestration, tracing, and runtime evaluation.
- Agents cannot bypass Java-owned resources; resource access crosses the guarded Java Tool Gateway.
- The Java ↔ Python boundary is verified with real cross-process E2E tests.
- The public release includes 14 complete APIOps Bench runs, with failures, unknowns and execution modes preserved.

## Architecture

![Agentic APIOps runtime architecture](.github/assets/agentic-apiops-architecture.svg)

Java owns deterministic execution and security boundaries. Python owns Agent orchestration, diagnosis, tracing, and evaluation.

## Core flow

```text
OpenAPI → Metadata → TestCase DSL → Async Runner → Assertion → TestReport
→ Diagnosis → Evidence / Tool → DiagnosisReport → Trace / Evaluation
```

LLM-generated TestCases are candidates. Java validates the DSL, runs the test, and publishes the authoritative `TestReport`; AgentLab consumes that report and controlled evidence to produce diagnosis and evaluation outputs.

## Authority boundary

| Fact / Responsibility | Authority |
| --- | --- |
| OpenAPI metadata | Java Platform |
| DSL validation | Java Platform |
| HTTP execution | Java Runner |
| Assertions | Java Platform |
| TestReport | Java Platform |
| Tool authorization | Java Tool Gateway |
| Agent workflow | Python AgentLab |
| Diagnosis reasoning | Python AgentLab |
| Agent trace | Python AgentLab |
| Runtime evaluation | Python AgentLab |

`LLM output` is a candidate or inference. `Java TestReport` is execution truth. Python `ALLOW` is not Java `ALLOW`, and Human Approval is not Java Authorization.

## Implemented & Verified

### Java Platform

- OpenAPI metadata and project-scoped API access
- TestCase DSL validation
- HTTP Runner and asynchronous batch execution
- Assertion Engine and authoritative TestReport
- JWT/project authorization
- RAG retrieval and Context Pack construction
- Structured Agent generation and diagnosis integration
- Tool Gateway, guards, sanitization, and audit

### Python AgentLab

- TestCase Generation workflow
- Diagnosis workflow with structured outputs
- Context engineering and Java evidence consumption
- Tool planning and guarded tool-use workflow
- HITL approval flow
- Trace recording and redaction
- Runtime evaluator, metrics, judge, and reporting

### Console

- Overview
- API Studio
- Runs
- Diagnosis Studio and Diagnosis execution
- Traces
- Evaluation
- Settings

The Console supports Chinese and English, URL-based navigation, run cancellation
and reruns, redacted HTTP snapshots, report export, persisted diagnosis history and
approval recovery. Automatic diagnosis triggering and browser-based Java diagnosis
are not implemented. Diagnosis locking and recovery target a single-machine SQLite
deployment.

## APIOps Bench

APIOps-Bench 105 is a project-specific evaluation across generation, diagnosis, tool
safety, RAG evidence and end-to-end API operations. The public bundle contains 14
complete runs and 1,470 task results: 12 real-model adapter runs and two mixed fixture
baselines.

| Run | PASS | FAIL | UNKNOWN |
| --- | ---: | ---: | ---: |
| Portfolio v5 | 95 | 9 | 1 |
| Diagnosis Contract v2 | 94 | 8 | 3 |

These runs use different evaluation contracts and must not be combined or treated
as a controlled model comparison. The v5 pass rate is 95/105 (90.48%). Historical
failures and unavailable metrics remain visible. This is not a general model
leaderboard or a production reliability estimate.

The Console reads saved results and starts no evaluations. See
[result interpretation](docs/benchmark-design.md),
[publication policy](docs/benchmark-publication.md) and the
[published bundles](artifacts/benchmark/). This release copies existing evidence;
it does not call models, rerun tasks or change scores.

## Recruiter walkthrough

The [HR demo setup](docs/hr-demo.md) creates a dedicated project, presenter/viewer
accounts with random local passwords, and real HTTP success/failure examples. After
configuring the services, run `scripts/setup-hr-demo.ps1 -SkipStart` on Windows.
The [prepared Windows launcher](docs/local-start.md) is also included.

Walk through API Studio, a successful run, an intentional assertion failure, the
diagnosis entry point and Benchmark history. The [existing examples](examples/)
remain contract fixtures; they are not presented as new runtime evidence.

## Agent Safety Boundary

![Agent Tool Security boundary](.github/assets/agentic-apiops-tool-security.svg)

Python tool selection is orchestration, not authorization. Python Guard is defense-in-depth; HITL is workflow consent, not Java resource authorization. Java Tool Gateway performs final authorization, guarding, execution, sanitization, and audit. Java `DENY` is terminal; Python has no raw-resource fallback.

## Implementation Evidence

| Capability | Implementation | Verification |
| --- | --- | --- |
| OpenAPI metadata | [OpenAPI metadata controller](java-apiops-platform/apiops-openapi/src/main/java/com/apiops/openapi/controller/OpenApiMetadataQueryController.java) | [Controller test](java-apiops-platform/apiops-openapi/src/test/java/com/apiops/openapi/controller/OpenApiMetadataQueryControllerTest.java) |
| TestCase DSL validation | [DSL validator](java-apiops-platform/apiops-runner/src/main/java/com/apiops/runner/validation/TestCaseDslValidator.java) | [Validation tests](java-apiops-platform/apiops-runner/src/test/java/com/apiops/runner/validation/TestCaseDslValidationTest.java) |
| HTTP execution | [Run execution service](java-apiops-platform/apiops-runner/src/main/java/com/apiops/runner/application/RunExecutionService.java) | [Runner service tests](java-apiops-platform/apiops-runner/src/test/java/com/apiops/runner/application/RunExecutionServiceTest.java) |
| Assertions | [Assertion Engine](java-apiops-platform/apiops-runner/src/main/java/com/apiops/runner/assertion/AssertionEngine.java) | [Assertion tests](java-apiops-platform/apiops-runner/src/test/java/com/apiops/runner/assertion/AssertionEngineTest.java) |
| Async test batches | [Batch controller](java-apiops-platform/apiops-web/src/main/java/com/apiops/web/runner/controller/AsyncBatchController.java) | [Batch controller tests](java-apiops-platform/apiops-web/src/test/java/com/apiops/web/runner/controller/AsyncBatchControllerTest.java) |
| TestReport | [Report controller](java-apiops-platform/apiops-report/src/main/java/com/apiops/report/controller/TestReportController.java) | [Report controller tests](java-apiops-platform/apiops-report/src/test/java/com/apiops/report/TestReportControllerTest.java) |
| Tool Gateway | [Tool Gateway](java-apiops-platform/apiops-tool-gateway/src/main/java/com/apiops/tool/gateway/ToolGateway.java) | [Gateway tests](java-apiops-platform/apiops-tool-gateway/src/test/java/com/apiops/tool/gateway/ToolGatewayTest.java) |
| RAG / evidence | [Context Pack builder](java-apiops-platform/apiops-rag/src/main/java/com/apiops/rag/context/ContextPackBuilder.java) | [Context Pack tests](java-apiops-platform/apiops-rag/src/test/java/com/apiops/rag/context/ContextPackBuilderTest.java) |
| Python generation | [Generation workflow](python-apiops-agentlab/app/workflows/testcase_generation_graph.py) | [Generation workflow tests](python-apiops-agentlab/tests/workflows/test_testcase_generation_graph.py) |
| Python diagnosis | [Diagnosis workflow](python-apiops-agentlab/app/workflows/diagnosis_workflow.py) | [Diagnosis workflow tests](python-apiops-agentlab/tests/workflows/test_diagnosis_workflow.py) |
| Tracing | [Trace recorder](python-apiops-agentlab/app/tracing/recorder.py) | [Trace recorder tests](python-apiops-agentlab/tests/tracing/test_recorder.py) |
| Runtime evaluation | [Evaluator](python-apiops-agentlab/app/evaluator/evaluator.py) | [Evaluator tests](python-apiops-agentlab/tests/evaluator/test_evaluator.py) |
| Java ↔ Python integration | [Java API client](python-apiops-agentlab/app/clients/java_apiops.py) | [Cross-process E2E test](java-apiops-platform/apiops-web/src/test/java/com/apiops/web/tool/Stage20FinalAcceptanceCrossProcessE2ETest.java) |
| Console context trail | [Console shell](apiops-console/src/components/layout/AppShell.tsx) | [Context-trail verification](apiops-console/scripts/verify-context-trail.ts) |

## REST integration

The public integration surface is project-scoped:

| Capability | Method | Path |
| --- | --- | --- |
| OpenAPI metadata | `GET` | `/api/v1/projects/{projectId}/openapi/apis/{apiId}` |
| Validate an API's TestCase DSL | `POST` | `/api/v1/projects/{projectId}/openapi/apis/{apiId}/testcases:validate` |
| Submit test batch | `POST` | `/api/v1/projects/{projectId}/test-batches` |
| Read test report | `GET` | `/api/v1/projects/{projectId}/test-runs/{runId}/report` |
| Call a guarded tool | `POST` | `/api/v1/projects/{projectId}/tool-calls` |

Java also validates the DSL at Agent and Runner boundaries. The Python read-only
Benchmark endpoint is `GET /api/v1/benchmark/results`.

## Quick start

Run each verification block from the repository root.

### Verify the repository

```bash
# Java Platform
cd java-apiops-platform
./mvnw clean verify
```

```bash
# Python AgentLab
cd python-apiops-agentlab
uv run ruff check .
uv run pytest
uv run python ../scripts/validate-schemas.py
```

```bash
# React Console
cd apiops-console
npm ci
npm run lint
npm run test:context
npm run verify:benchmark
npm run build
```

On Windows, use `./mvnw.cmd clean verify` for the Java command.

### Local development

```bash
# Python API
cd python-apiops-agentlab
uv run uvicorn app.main:app --reload
```

```bash
# Console
cd apiops-console
npm run dev
```

The Console and AgentLab connect to their configured Java/Python services. `docker-compose.dev.yml` provides local MySQL, Redis, and RabbitMQ infrastructure; it is not a one-command application deployment.

See [development setup](docs/README-dev-env.md) for configuration, proxy ports and
the complete Console verification commands. Real provider credentials and personal
deployment endpoints must be supplied locally.

## Verification

The [public source and evidence workflow](https://github.com/guyun16/agentic-apiops-public/actions/workflows/public-checks.yml)
runs the Python suite, Ruff, shared-schema checks, Console checks and immutable
evidence verification. [Java CI](https://github.com/guyun16/agentic-apiops-public/actions/workflows/java-ci.yml)
runs the default Maven verification with Docker. Use the commands above to reproduce
the checks locally.

Environment-gated live tests may be skipped; skipped checks are not successful live
validation. Historical model-run results are independent of these code checks. The
public source inventory records publication work with no benchmark execution or model calls.

## Repository structure

```text
agentic-apiops-public
├── .github
│   └── assets
├── java-apiops-platform
├── python-apiops-agentlab
├── apiops-console
├── shared-schemas
├── examples
├── artifacts/benchmark
├── docs
├── scripts
└── README.md
```

Java is responsible for execution, security, audit, and report truth. Python is responsible for Agent workflow, tool orchestration, tracing, and runtime evaluation. The projects meet through shared schemas, REST contracts, and the Java Tool Gateway.

## Public scope

This public portfolio includes executable source, ordinary tests, synthetic fixtures,
shared schemas, selected documentation, demo initialization scripts and the reviewed
Benchmark publication and selected regression evidence. Unrelated raw experiments, local databases, service logs,
private development notes and credentials are excluded. Historical provenance paths
remain as source identifiers; available public result files are listed in the manifest.
Machine-local paths in selected regression copies are normalized and recorded in the
evidence inventory; the published run bundles remain byte-identical to their sources.

Configuration templates are provided as `.env.example` files; real credentials are never committed.
