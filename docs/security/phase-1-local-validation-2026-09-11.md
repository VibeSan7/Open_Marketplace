# Phase 1 — local validation 2026-09-11

Validation completed on 2026-09-11 at 02:16:27 +03:00. This is local validation of the current fixes, **not an independent assessment and not authorization to merge or for user launch**.

## Scope and initial state

- The owner chose: “For now, perform only local checks yourself.”
- Working directory: `D:/Open_Marketplace/.worktrees/task20-phase1-completion`.
- Branch: `task20-phase1-completion`.
- HEAD: `d2a37bc18f2dcc688ff1afe333294c333a0dc7eb`.
- Existing uncommitted fixes were checked, including TOTP reconfiguration through the employee invitation, attempt limiting, audit logging, and `Referrer-Policy` changes.
- Application code, tests, dependencies, and Compose settings were not changed in this validation. After the commands ran, only the documentation was changed and the results were preserved.
- No other models were run. Commit, push, branch merge, external-resource setup, and deployment were not performed.

## Isolation and data preservation

Separate temporary Compose project `omp-localcheck-20260910t230519z` was used with the existing `compose.yaml` and `compose.test.yaml`.

- Validation used only `postgres-test`; its data was stored in `tmpfs`, that is, the container’s temporary memory.
- The live Docker configuration confirmed `HostConfig.Tmpfs["/var/lib/postgresql/data"]`. This container’s `Mounts` field was empty; by itself, that does not prove the absence of `tmpfs`.
- The application volume `task20-phase1-completion_postgres_data` was not attached to the tests. The existing application database container was not started.
- Mailpit was a separate test instance. This matters because `open_marketplace/outbox/tests/test_mail_delivery.py` clears the mailbox through `DELETE /api/v1/messages`.
- The existing `.env` remained unchanged, Git-ignored, and untracked. Secrets were not printed in reports.
- For the browser-validation attempt, the current runtime image was started with `DATABASE_HOST=postgres-test` and the port bound only to `127.0.0.1:8000`.

## Confirmed results

All commands ran on newly built images of the current working tree, sequentially against the test database.

- Runtime and test image builds: successful.
- `makemigrations --check --dry-run`: `No changes detected`.
- `migrate --noinput`: successful in the isolated test environment.
- `check --deploy`: only the four previously documented warnings for the local HTTP profile: `security.W004`, `security.W008`, `security.W012`, `security.W016`. This is not authorization to use HTTP settings in production.
- `lint-imports --no-cache`: `11 kept, 0 broken`.
- Full test suite: `Ran 407 tests in 175.159s`, `OK`; no tests were skipped.
- All 17 scenarios from `open_marketplace/tests/test_full_flows.py` are present in the successful full run.
- Runtime and test images passed the check for the absence of `/app/.env` and `/app/.git`.
- Checks of tracked files for the specified private-key patterns and non-empty assignments of the six project secrets found no matches. These are limited pattern checks, not a claim that all secrets are absolutely absent.
- `git diff --check` and `bash -n ops/verify_restore.sh`: successful.

## Actual database restoration

The standard command was run with an explicit temporary Compose-project name:

```bash
COMPOSE_PROJECT_NAME=omp-localcheck-20260910t230519z bash ops/verify_restore.sh
```

Result: exit code `0`. Separate temporary source and target databases were created; `pg_dump` and `pg_restore` were run. Checks of the source and restored schemas and their related data graph matched. After completion, the absence of temporary `restore_source_*` / `restore_target_*` databases and temporary dump/partial-report files was separately confirmed.

## Browser acceptance — not completed

An attempt to open `http://127.0.0.1:8000/login/` through `browser_exec` with `local=true` ended with a tool refusal:

```text
Blocked: URL targets a private or internal address
```

The restriction was not bypassed. Passwords, TOTP codes, and other secrets were not entered through the browser. Registration and login in a real browser, administrator-invitation acceptance, reviewer application handling, and the full seller flow are **not confirmed**.

The first separate readiness HTTP request immediately after startup returned `curl` exit `52` (`Empty reply from server`, HTTP code `000`). This was not a successful HTTP check. The container log later confirmed that Django 5.2.17 started without system-check errors, but the fact that the server started does not replace page checks or browser acceptance.

Automated HTML/Admin tests remain automated tests and do not count in place of Task 20 Step 5.

## Observation about local startup

In the existing `compose.yaml`, the web port is specified as `8000:8000`; Docker showed the standard container bound to `0.0.0.0:8000`. This is broader than access from this computer only. This validation used the standard Compose option `run --publish 127.0.0.1:8000:8000`; the original configuration was not fixed.

Before ordinary local startup, the loopback binding should be separately fixed in the local configuration. This is not a reason to expose the service externally or to consider the development server suitable for production.

## Completion and next step

The temporary containers and network created by this validation were stopped and removed; general Docker cleanup and removal of application volumes were not performed. The results were preserved.

- Task 20 Step 3: local automated validation completed.
- Task 20 Step 5: remains incomplete — a real browser pass through `docs/runbooks/local-development.md`, section 4, is required via an approved access method or manually by the owner.
- An independent assessment of the current fixes remains a separate unmet condition. Declining to run a new model now does not remove this condition.
- Task 20 Step 7, merge, and user launch are not approved. After the remaining checks, the evidence must be updated and a final pre-commit check performed.

## Evidence location

Local directory (Git-ignored):

`artifacts/local-validation-20260910T230519Z/`

Main files: `preflight.json`, `source-hashes-before.json`, `database-isolation.json`, `build.log`, `makemigrations.log`, `migrate.log`, `check-deploy.log`, `import-linter.log`, `full-suite.log`, `quality-gate-summary.json`, `test-image-secrecy.log`, `runtime-image-secrecy.log`, `repository-secrecy.json`, `restore.log`, `restore-result.txt`, `restore-summary.json`, `browser-status.json`.

Related documents: [phase 1 plan](../superpowers/plans/2026-09-02-phase-1-identity-access.md), [main report](phase-1-review.md), [local startup](../runbooks/local-development.md), [restoration](../runbooks/test-and-restore.md).
