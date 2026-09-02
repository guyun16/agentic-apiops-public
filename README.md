# Agentic APIOps Portfolio

Agentic APIOps Portfolio is a dual-project portfolio for API testing, test execution, failure diagnosis, controlled tool use, and Agent evaluation.

The project is built around one business domain:

```text
APIOps: API testing, execution, diagnosis, evidence collection, and evaluation.
```

It is not a Postman clone and not a simple LLM wrapper. The goal is to show how a production-style Java platform and an experimental Python Agent lab can work together through stable contracts, shared schemas, security boundaries, and measurable evaluation.

## Public release scope

This repository is a code-only public snapshot of the Agentic APIOps portfolio. Documentation directories and Benchmark materials are intentionally not included in this release. The public snapshot keeps the executable source, shared contracts, ordinary tests, and public-safe configuration needed to inspect and verify the platform.

## 1. Project Overview

The portfolio contains two independent but connected projects:

```text
Java Agentic APIOps Platform
Python APIOps-AgentLab
```

Their responsibilities are intentionally different:

| Project | Position | Main Responsibility |
|---|---|---|
| Java Agentic APIOps Platform | Production-oriented backend platform | Formal execution, validation, report authority, Tool Gateway, audit, security boundary |
| Python APIOps-AgentLab | Agent workflow and evaluation lab | TestCase generation, failure diagnosis, tool-use planning, tracing, runtime evaluation |

The key design principle is:

```text
Java closes the formal business loop.
Python explores, optimizes, and evaluates Agent workflows.
```

## 2. Why This Project

Traditional API testing platforms mainly focus on:

```text
sending requests
checking assertions
generating reports
```

This project extends that workflow with Agentic capabilities:

```text
OpenAPI-based TestCase DSL generation
controlled tool-use diagnosis
traceable evidence collection
structured diagnosis reports
runtime Agent evaluation
safety and audit constraints
```

The portfolio is designed to demonstrate four engineering capabilities:

- Java backend platform engineering
- API testing platform design
- Python Agent workflow engineering
- Agent evaluation and safety measurement

## 3. Core Business Flow

The main APIOps flow is:

```text
OpenAPI Document
→ API Metadata
→ TestCase DSL
→ Java Runner
→ TestReport
→ Diagnosis
→ Evidence / Tool
→ DiagnosisReport
→ Trace / Evaluation
```

Meaning of each step:

| Step | Meaning |
|---|---|
| OpenAPI Document | Source API facts |
| API Metadata | Normalized API structure |
| TestCase DSL | Executable test case contract |
| Java DSL Validation | Schema and rule validation before execution |
| Java Runner | Formal API test execution |
| Assertion Result | Status, header, body, JSONPath, and latency assertion outcomes |
| Test Report | Authoritative execution result |
| Context Pack / Tool Evidence | Controlled evidence for diagnosis |
| Diagnosis Report | Structured, evidence-based failure explanation |
| Evaluation Result | Agent behavior and output quality metrics |

Agent output must not remain free-form natural language. It must be converted into schema-validated artifacts such as:

```text
TestCase DSL
ToolCall
ToolResult
DiagnosisReport
Runtime Evaluation facts
```

## 4. Java Platform Responsibility

Java Agentic APIOps Platform is the trusted platform boundary.

It owns:

- OpenAPI metadata management
- TestCase DSL validation
- HTTP Runner
- Assertion Engine
- Test Report
- Tool Gateway
- Security Guard
- Audit Log
- RAG / Context Pack integration position
- production-oriented Java AI capabilities

Java is authoritative for:

```text
formal execution
security boundary
audit logging
report generation
permission control
tool access governance
platform-level reliability
```

Future Java modules include:

```text
apiops-common
apiops-auth
apiops-web
apiops-openapi
apiops-runner
apiops-report
apiops-agent
apiops-rag
apiops-tool-gateway
apiops-demo-order-service
apiops-eval
```

Current Java implementation work starts from `apiops-common`, because later modules need stable result wrappers, error codes, exceptions, enums, utility rules, and common models.

## 5. Python AgentLab Responsibility

Python APIOps-AgentLab is the Agent workflow laboratory.

It owns:

- Agent Workflow
- TestCase generation
- failure diagnosis
- tool-use planning
- Agent Trace
- Runtime Evaluation
- Ablation Study
- workflow optimization

Python does not replace Java Platform. It calls Java Platform APIs and Java Tool Gateway to complete APIOps workflows.

Future Python modules include:

```text
app/api
app/schemas
app/agents
app/workflows
app/tools
app/rag
app/memory
app/guardrails
app/tracing
app/evaluator
app/reports
```

## 6. Java AI and Python AI Boundary

This project has two AI positions:

```text
Java AI = production-oriented AI inside Java Platform.
Python AI = experiment-oriented Agent workflow capability inside AgentLab.
```

Java AI is used for:

- production-facing intelligent features
- structured output validation
- controlled tool calling
- platform-integrated diagnosis
- auditable model call records
- stable business integration

Python AI is used for:

- Agent workflow experiments
- prompt structure optimization
- tool-use strategy exploration
- RAG strategy experiments
- runtime evaluation
- ablation studies
- trace analysis

When a good strategy is discovered in Python AgentLab, the transferable assets are not the Python code itself. They are:

```text
Prompt structure
Workflow steps
Structured output schema
Tool-use strategy
RAG usage position
Guardrail rules
Evaluation findings
Error repair strategy
```

## 7. Java × Python Integration

The main integration direction is:

```text
Python AgentLab → Java Agentic APIOps Platform
```

Python calls Java because Java is the formal platform provider.

Core integration APIs:

| Scenario | Method | Path | Purpose |
|---|---|---|---|
| Get API metadata | GET | `/api/v1/openapi/apis/{apiId}` | Read normalized API metadata |
| Validate TestCase DSL | POST | `/api/v1/testcases/validate` | Validate Agent-generated DSL |
| Submit test run | POST | `/api/v1/runs` | Submit executable test cases to Java Runner |
| Query report | GET | `/api/v1/reports/{reportId}` | Read Java authoritative test report |
| Call tool | POST | `/api/v1/tools/call` | Access controlled tools through Java Tool Gateway |

Unified response format:

```json
{
  "code": "SUCCESS",
  "message": "ok",
  "data": {},
  "traceId": "trace_001"
}
```

Machine behavior must branch on `code`, not on `message`.

## 8. Shared Schemas

Shared schemas are placed under:

```text
shared-schemas/
```

They define the contract between Java Platform and Python AgentLab.

Current Stage 0 schemas:

```text
testcase-dsl-schema.json
openapi-metadata-schema.json
tool-call-schema.json
tool-result-schema.json
diagnosis-report-schema.json
```

Schema responsibilities:

| Schema | Producer | Consumer |
|---|---|---|
| `testcase-dsl-schema.json` | Python Agent / Java Agent | Java Runner |
| `openapi-metadata-schema.json` | Java Platform | Python AgentLab / Console |
| `tool-call-schema.json` | Python Agent / Java Agent | Java Tool Gateway |
| `tool-result-schema.json` | Java Tool Gateway | Python Agent / Java Agent |
| `diagnosis-report-schema.json` | Diagnosis Agent | Evaluator / Report UI |

Shared schemas make Agent output:

```text
validatable
executable
auditable
versioned
cross-language compatible
```

## 9. Tool Gateway and Security Boundary

Tool Gateway is located in Java Platform. It is the controlled tool-use entry point for Agents.

Python AgentLab must not directly access:

```text
production MySQL
production Redis
internal HTTP services
raw log files
sensitive runtime resources
```

All tool access must follow:

```text
Python AgentLab
→ Java Tool Gateway
→ ToolAuth
→ ParamValidator
→ Guard
→ Executor
→ ResultSanitizer
→ AuditLogger
→ ToolResult
```

Planned tool categories include:

```text
SQL_READ
REDIS_READ
HTTP_CALL
LOG_SEARCH
RAG_SEARCH
REPORT_READ
RUNNER_SUBMIT
OPENAPI_METADATA_READ
```

This design ensures that Agent tool-use is controlled, traceable, auditable, and measurable.

## 10. Runtime Evaluation

The public Console and AgentLab expose runtime evaluation facts for observed Agent executions. These facts cover validation, tool activity, safety outcomes, latency, token usage, and cost while keeping Java Platform as the authority for execution, reports, and access control.

Benchmark materials are not included in this public release.

## 11. Repository Structure

Current repository structure:

```text
agentic-apiops-public
├── README.md
├── shared-schemas
├── examples
├── scripts
├── java-apiops-platform
│   └── apiops-common
└── python-apiops-agentlab
    └── app
```

## 12. Current Stage

Current stage:

```text
Stage 0: Business Domain, Architecture, Contract, and Roadmap Finalization
Stage 1: Java apiops-common foundation is being prepared
Stage 2: JVM and concurrency learning notes are being organized
```

Stage 4 order-service work is present in the current workspace. The service has real user, product, coupon, inventory, order, payment-callback, and fault-injection code plus automated tests. The public snapshot does not include historical acceptance documents or runtime evidence artifacts.

Stage 0 defines architecture, protocols, schemas, examples, and validation boundaries.

Stage 0 does not implement:

```text
real Java Runner
real AssertionEngine
real Tool Gateway executor
real SQL Guard
real Redis Guard
real RAG pipeline
real LangGraph workflow
real Spring AI Agent
real model API integration
real database schema
real Redis / MQ / SSE integration
```

## 13. Roadmap

Planned roadmap:

```text
Stage 1: Java common module, Result<T>, ErrorCode, BusinessException, enums
Stage 2: JVM, concurrency, thread pool design
Stage 3: Maven, Git, Spring Boot engineering foundation
Stage 4: Spring MVC, MySQL, MyBatis, demo order service
Stage 5: Security, JWT, RBAC, OpenAPI documentation generation
Stage 6: OpenAPI parsing and API metadata modeling
Stage 7: TestCase DSL and AssertionEngine
Stage 8: HTTP Runner, state machine, and test report
Stage 9: Redis, RabbitMQ, SSE, and async batch execution
Stage 10: Java RAG and Context Pack
Stage 11: Java Spring AI Agent and structured output
Stage 12: MCP-style Tool Gateway and security guard
Stage 13: Java testing, observability, and performance engineering
Stage 14: Python foundation, Pydantic, FastAPI, and engineering setup
Stage 15: LangChain, LangGraph, and Agent ecosystem
Stage 16: Python TestCase Generator Agent Workflow
Stage 17: Python RAG, Memory, and Context Engineering
Stage 18: Python Tool-use, Guardrails, and Human-in-the-loop
Stage 19: Python Agent Tracing, Evaluator, and experiment reports
Stage 20: Java × Python integration
Stage 22: Ablation study and optimization
```

## 14. Final Positioning

```text
Java is responsible for platformization, execution, security, audit, and formal business closure.
Python is responsible for Agent workflow, tool orchestration, tracing, and runtime evaluation.
The two projects are connected through shared schemas, REST contracts, and Tool Gateway.
Benchmark materials are not included in this public release.
```

## Public verification commands

Run commands from the corresponding project directory:

```bash
# Java Platform
cd java-apiops-platform
./mvnw clean verify

# Python AgentLab
cd python-apiops-agentlab
uv run ruff check .
uv run pytest

# Console
cd apiops-console
npm ci
npm run lint
npm run test:context
npm run build
```

For local development, start the Python API with `uv run uvicorn app.main:app --reload` and the Console with `npm run dev`. Configure credentials through the public-safe `.env.example` templates; real credentials are never committed.
