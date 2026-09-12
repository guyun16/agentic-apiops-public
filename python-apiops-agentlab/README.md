# Python APIOps AgentLab

FastAPI and LangGraph workflows for TestCase generation, failure diagnosis,
controlled tool use, human approval, traces and evaluation. Java owns formal
execution, report facts, authentication and project authorization.

From this directory, use Python 3.11+ and uv:

```bash
uv sync --frozen
uv run pytest
uv run ruff check .
uv run python ../scripts/validate-schemas.py
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The ordinary test suite uses deterministic fixtures. Standalone Benchmark reads
require only the published files; generation, diagnosis and controlled tools require
the configured Java services. Runtime state, checkpoints and traces are stored in
ignored local data files. Diagnosis concurrency protection targets a single-machine
SQLite deployment.

The public distribution includes the Benchmark runner, dataset fixtures, evaluator,
publication API and existing result bundles. Historical real-model scripts require
separately provisioned services, local credentials and the corresponding experiment
configuration. They are not part of the default test invocation. Public templates
replace personal provider deployment URLs with placeholders.

See [project documentation](../docs/README.md),
[Console workflows](../docs/console-workflows.md),
[Benchmark interpretation](../docs/benchmark-design.md) and
[publication verification](../docs/benchmark-publication.md).
