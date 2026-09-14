# Local development and Phase 1 demonstration runbook

This runbook is for the isolated local Docker Compose environment. It does not use cloud resources and does not open an external terminal window. Commands are run from the repository root.

## 1. Prepare `.env` safely

For first-time setup only, generate `.env` and its six secret values locally using the procedure in [README.md](../../README.md). The generator prints no secret and refuses to overwrite an existing `.env`. Keep existing keys when reusing a database; do not copy `.env.example` over them. Confirm only the file's Git state:

```bash
git check-ignore .env
test -z "$(git ls-files -- .env)"
```

Never inspect `.env` with a command whose output is copied into a log. The Docker build context also excludes `.env` and `.git`.

## 2. Start and stop

Use the exact documented start command:

```bash
docker compose run --rm --build web python manage.py migrate --noinput && docker compose up --build
```

Services:

- `postgres` — persistent local Phase 1 database;
- `web` — Django HTML and custom Admin pages on port 8000;
- `worker` — long-running outbox delivery worker;
- `mailpit` — local SMTP on 1025 and UI/API on 8025.

For a hidden/background local run, the equivalent operational command is:

```bash
docker compose up --build -d
```

Check status without printing environment values:

```bash
docker compose ps
```

Normal shutdown keeps the local database:

```bash
docker compose down
```

A clean demo reset deletes only disposable local Compose data:

```bash
docker compose down -v
docker compose run --rm --build web python manage.py migrate --noinput
docker compose up --build
```

Do not use `down -v` when the local database contains data you need.

## 3. Bootstrap the first security administrator

Run after migrations:

```bash
docker compose run --rm web python manage.py bootstrap_security_admin --email admin@example.test
```

Bootstrap is command-only and can create the initial security-admin invitation only once. The command output is limited to an invitation UUID. The recipient opens the link from Mailpit, chooses a password, confirms TOTP and receives recovery codes once. Do not record the password, manual TOTP secret or recovery codes.

Mailpit:

- UI: <http://127.0.0.1:8025/>;
- SMTP is internal to Compose at `mailpit:1025`;
- the worker handles ready outbox messages automatically.

Use a bounded worker pass when diagnosing a local queue:

```bash
docker compose run --rm web python manage.py run_outbox_worker --once
```

A `succeeded` outbox row means the configured handler completed. For SMTP messages, verify receipt in Mailpit as well; do not treat the database state alone as proof of mailbox delivery.

## 4. Demonstration sequence

Use disposable addresses and do not record their credentials.

1. Bootstrap one security-admin invitation.
2. Accept it through the staff HTML flow and confirm TOTP. Recovery codes are displayed once only.
3. From custom Admin, invite a `seller_reviewer`.
4. Accept the reviewer invitation and confirm TOTP.
5. Register an ordinary account through `/register/`, follow its email link in Mailpit, and log in.
6. Open `/sessions/` to verify session management.
7. Create, edit and submit the seller application through the HTML pages.
8. For the active/suspend/restore demonstration, first enable TOTP for the ordinary owner using that owner's separate Authenticator entry. As reviewer, open the custom Admin seller queue, start review and approve the application.
9. As security-admin, open the seller detail and suspend, then restore, admission.
10. As reviewer, open the Admin audit page and verify the application action chain. The security-admin's audit scope covers seller admission and security operations, not seller applications; use that role for admission history. Mailpit must contain the invitation, verification and decision messages.

For sensitive actions, confirm the current account password and second factor through `/security/reauthenticate/` (or complete a fresh login), then perform the action in the same uninterrupted manual sequence. A confirmation checked before a pause in the conversation may expire before the user clicks the action. Do not weaken timeouts or change permissions to complete the demonstration.

The earlier automated Task 20 demonstration used Django's in-process test Client; it remains integration evidence only. The [owner-driven Chrome demonstration completed on 2026-09-13](../security/phase-1-browser-acceptance-2026-09-13.md) passed all ten browser-checklist items with read-only database checks and actual Mailpit receipts. It used a separate `postgres-test` Compose stack. The [ordinary persistent-database start command was subsequently verified](../security/phase-1-ordinary-startup-2026-09-13.md) in an owner-approved isolated source copy using alternate loopback ports to preserve the existing demo. Together these proofs complete Task 20 Step 5. The [fresh local quality gate also passed](../security/phase-1-local-validation-2026-09-13.md); only the verification copy was stopped afterwards. That was the pre-review checkpoint. A later owner-authorized independent static review returned APPROVE with remarks, followed by the separately approved R-01/R-03/R-05 changes. The [earlier 2026-09-14 post-review check](../security/phase-1-local-validation-2026-09-14.md) exposed the first-time README environment-generation failure VAL-001 despite 411 passing application tests. After a separately approved one-line correction, [the fresh local gate completed](../security/phase-1-local-validation-2026-09-14-after-val-001.md): clean environment generation and its overwrite guard, 411 application tests, standalone scope checks and real database restore all passed. Existing working keys must still never be regenerated or overwritten. The owner subsequently accepted Phase 1 and Task 20 and authorized publishing and merging [PR #21](https://github.com/VibeSan7/Open_Marketplace/pull/21) on 2026-09-14. Its GitHub status records integration; this acceptance does not authorize a production deployment, working-data reset or the next phase.

## 5. Failure recovery

If an acceptance run leaves a disposable local demo in an unusable state, stop the stack and recreate only its Compose volume:

```bash
docker compose down
# Use `docker volume ls` only to identify the project-local postgres_data volume.
# Remove that volume only when the database is disposable.
docker compose up --build -d
```

If the test database is left by an interrupted Django test run, do not remove the application database. Restart the disposable `postgres-test` service and rerun the focused test command. The test suite uses PostgreSQL, not SQLite.

If a new service-account invitation's TOTP setup expires before confirmation, reopen the original invitation link and enter the same password again. Only a still-pending invitation can replace the expired setup; an active setup is not rotated on retry, and the old secret cannot be used. Repeated wrong-password attempts use the shared login throttle and return the neutral error page when blocked.

If an outbox message is in retry state, inspect only its safe state/error fields through the Admin outbox page and run the bounded worker command. Never decrypt or print delivery payloads. An expired lease is reclaimed by the worker; the domain operation is protected by its idempotency key.

Run security-throttle cleanup periodically:

```bash
docker compose run --rm web python manage.py purge_security_throttles
```

For backup/restore evidence, use [test-and-restore.md](test-and-restore.md). It uses the disposable `postgres-test` tmpfs database and removes source/target databases and dump files after the proof.
