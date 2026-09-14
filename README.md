# Open Marketplace — Phase 1

Phase 1 covers identity, access, seller onboarding, audit and the outbox worker. This worktree contains the Task 20 acceptance, migration-compatibility, scope and secrecy evidence. The implementation remains deliberately limited to the Phase 1 non-goals listed below.

## Source documents

- [Phase 1 design](docs/superpowers/specs/2026-09-02-phase-1-identity-access-design.md)
- [Phase 1 implementation plan](docs/superpowers/plans/2026-09-02-phase-1-identity-access.md)
- [Phase 1 security review](docs/security/phase-1-review.md)
- [Local development runbook](docs/runbooks/local-development.md)
- [Test and restore runbook](docs/runbooks/test-and-restore.md)

## Prerequisites

- Docker Desktop with Compose and WSL integration enabled;
- Git Bash, WSL or another POSIX-compatible shell for the commands below;
- Python 3 for the one-time, standard-library-only `.env` generator below; the application and canonical tests run in Docker, not host Python.

## Create the local environment file

Secrets belong only in the untracked `.env` file. Do not paste their values into a command, log, issue or pull request. From the repository root, generate a new `.env` from the safe variable-name template without printing values. This is for first-time setup only: an existing `.env` must be kept, not regenerated while its database or encrypted records are in use. Exclusive file creation makes the command fail rather than overwrite existing keys.

```bash
python - <<'PY'
import base64
import os
import secrets
from pathlib import Path

keys = {
    "DJANGO_SECRET_KEY": secrets.token_urlsafe(48),
    "DATABASE_PASSWORD": secrets.token_urlsafe(32),
    "TOTP_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
    "OUTBOX_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
    "LINK_EXCHANGE_ENCRYPTION_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
    "THROTTLE_HASH_KEY": base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii"),
}
source = Path(".env.example").read_text(encoding="utf-8").splitlines()
rendered = []
for line in source:
    name, separator, _ = line.partition("=")
    rendered.append(f"{name}={keys[name]}" if separator and name in keys else line)
descriptor = os.open(".env", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
    output.write("\n".join(rendered) + "\n")
PY

git check-ignore .env
test -z "$(git ls-files -- .env)"
```

The last two commands must succeed. Never use `cat .env` in a log or chat.

## Start the local stack

The documented local-start command is intentionally one command: migrate first, then start the web app, worker, PostgreSQL and Mailpit.

```bash
docker compose run --rm --build web python manage.py migrate --noinput && docker compose up --build
```

Open these local surfaces:

- application: <http://127.0.0.1:8000/login/>;
- Mailpit UI: <http://127.0.0.1:8025/>;
- custom staff Admin: <http://127.0.0.1:8000/admin/>.

The local profile uses HTTP only. Production HTTPS behavior is enabled by setting `DJANGO_SECURE_COOKIES=true`; the security test proves that this turns on secure cookies, redirect and HSTS settings.

## Bootstrap the first administrator

Run this once after migrations:

```bash
docker compose run --rm web python manage.py bootstrap_security_admin --email admin@example.test
```

The command prints only an invitation UUID. The recipient completes the one-time invitation, sets TOTP and receives recovery codes once. Do not copy recovery-code values into notes or logs.

The background `worker` delivers outbox messages to Mailpit. For a bounded local retry/diagnostic pass, use:

```bash
docker compose run --rm web python manage.py run_outbox_worker --once
```

## Verification commands

Focused Phase 1 acceptance and migration suites:

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace.tests.test_full_flows open_marketplace.tests.test_migrations open_marketplace.tests.test_scope_boundaries -v 2
```

Complete quality gate:

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py makemigrations --check --dry-run
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py migrate --noinput
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py check --deploy
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test lint-imports --no-cache
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace -v 2
bash ops/verify_restore.sh
```

`check --deploy` reports four expected warnings in the HTTP-only local profile. Any other warning is a failure until investigated. The restore proof uses the disposable `postgres-test` service and never the application `postgres_data` volume.

## Operations

Expired throttles can be purged in bounded batches:

```bash
docker compose run --rm web python manage.py purge_security_throttles
```

Stop containers while retaining the local PostgreSQL volume:

```bash
docker compose down
```

Remove the local demo database and containers only when the data is disposable and a clean demo is intended:

```bash
docker compose down -v
```

## Module map

- `identity` — accounts, sessions, email verification, password/TOTP/recovery flows;
- `access` — roles, permissions and one-time staff invitations;
- `seller_onboarding` — drafts, versions, review decisions and seller admission;
- `audit` — validated, scoped audit append/query boundary;
- `outbox` — encrypted delivery payloads, retry/lease handling and Mailpit SMTP delivery;
- `web` — ordinary HTML forms and sensitive-link exchange;
- `staff_admin` — custom Django Admin adapters;
- `verification` — disposable PostgreSQL restore-probe commands.

Application code crosses module boundaries through `public.py` contracts. Historical migration models are used only by `test_migrations.py` as required by Django's migration executor.

## Explicit non-goals

Phase 1 does not implement catalog, inventory, orders, payments, KYC/document uploads, cloud resources, a JSON API, DRF, Redis or a production backup-retention policy. The restore script is a local PostgreSQL restoration proof; production RPO/RTO, retention, key custody and off-site storage require a separate design and review.
