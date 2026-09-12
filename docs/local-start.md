# Prepared Windows showcase

The Windows launcher reuses an already configured development stack. It is not a
fresh-machine installer. For generic installation and manual startup, begin with
[Development environment](README-dev-env.md).

## Prerequisites

- Java 21, Node/npm, Python, Docker Desktop and the MySQL command-line client on PATH.
- Local MySQL with the module schemas initialized and a non-empty local root password.
- A root `.env.local` containing the database password as `APIOPS_STAGE21_DB_PASSWORD`,
  a JWT secret, RAG embedding configuration (`ZHIPU_API_KEY`) and any chosen model settings.
- The launcher's three local validation accounts already provisioned. Their names and
  passwords are supplied through `STAGE21_NORMAL_USERNAME`, `STAGE21_NORMAL_PASSWORD`,
  `STAGE21_SAFETY41_USERNAME`, `STAGE21_SAFETY41_PASSWORD`, `STAGE21_SAFETY42_USERNAME`
  and `STAGE21_SAFETY42_PASSWORD` as required by the validation scripts.

Use the root and Python `.env.example` files to identify configuration fields. Public
templates contain no working personal credentials. New users can start the services
manually and run the HR setup with `-SkipStart` instead of provisioning the launcher's
historical validation accounts.

## Start and stop

Run `start-project.cmd` from the repository root. After `READY`, the Console opens at
`http://127.0.0.1:5173`. The managed stack uses Java on 19090, Python on 18000 and the
demo-order service on 18080. The launcher sets the matching proxy configuration.

Use `start-project.cmd -Restart` after changing code or local configuration. Use
`stop-project.cmd` to stop applications owned by this launcher. Database data is
retained. The launcher records process identities and refuses to stop unrelated
processes. Logs and state are stored in ignored `.local-run/` and the local temporary
runtime directory.

These launchers share fixed ports and a temporary runtime-state location across
checkouts. Run only one checkout's managed stack at a time and stop it using the same
checkout's launcher before changing checkouts.

The startup build uses `-DskipTests package` to prepare applications. Readiness checks
do not replace `clean verify`, pytest or the Console checks. Viewing published
Benchmark results starts no model run; deliberately using generation or diagnosis
may call the configured provider.
