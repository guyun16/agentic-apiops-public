# Public documentation / 公开文档

This repository contains the reviewed public application, ordinary tests, synthetic
fixtures and the published APIOps Bench result bundles. Start with the
[project overview](../README.md) or [中文说明](../zh/README.md).

- [Development environment](README-dev-env.md): dependencies, configuration and manual startup.
- [Windows launcher](local-start.md): prerequisites for the prepared local showcase.
- [HR demo](hr-demo.md): dedicated accounts, an isolated project and real example runs.
- [Console workflows](console-workflows.md): generation, execution, diagnosis and recovery.
- [HTTP snapshots](http-exchange-snapshots.md): request/response evidence and redaction.
- [Benchmark design and interpretation](benchmark-design.md): dataset, results and limitations.
- [Benchmark publication](benchmark-publication.md): immutable bundles and public source verification.

Historical result references retain their original run IDs and source-relative
paths. Selected regression inputs normalize machine-local prefixes and disclose the
changes in the evidence inventory. Unrelated raw experiments and service logs are
outside this public distribution; published result files are available under
[artifacts/benchmark](../artifacts/benchmark/).
