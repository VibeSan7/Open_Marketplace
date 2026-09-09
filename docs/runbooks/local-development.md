# Local development and Phase 1 demonstration runbook

This runbook is for the isolated local Docker Compose environment. It does not use cloud resources and does not open an external terminal window. Commands are run from the repository root.

## 1. Prepare `.env` safely

Copy `.env.example` and generate the six secret values locally using the procedure in [README.md](../../README.md). The generator writes `.env` but prints no secret. Confirm only its Git state:

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
8. As reviewer, open the custom Admin seller queue, start review and approve the application.
9. As security-admin, open the seller detail and suspend, then restore, admission.
10. Open the Admin audit page and verify the application action chain. Mailpit must contain the invitation, verification and decision messages.

The Task 20 demonstration executed this sequence against the live local Compose PostgreSQL and Mailpit services. It recorded only counts, statuses and UUIDs; recovery-code and token values were not written to the repository or output.

## 5. Failure recovery

If an acceptance run leaves a disposable local demo in an unusable state, stop the stack and recreate only its Compose volume:

```bash
docker compose down
# Use `docker volume ls` only to identify the project-local postgres_data volume.
# Remove that volume only when the database is disposable.
docker compose up --build -d
```

If the test database is left by an interrupted Django test run, do not remove the application database. Restart the disposable `postgres-test` service and rerun the focused test command. The test suite uses PostgreSQL, not SQLite.

If an outbox message is in retry state, inspect only its safe state/error fields through the Admin outbox page and run the bounded worker command. Never decrypt or print delivery payloads. An expired lease is reclaimed by the worker; the domain operation is protected by its idempotency key.

Run security-throttle cleanup periodically:

```bash
docker compose run --rm web python manage.py purge_security_throttles
```

For backup/restore evidence, use [test-and-restore.md](test-and-restore.md). It uses the disposable `postgres-test` tmpfs database and removes source/target databases and dump files after the proof.
