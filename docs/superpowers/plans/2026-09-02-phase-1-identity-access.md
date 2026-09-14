# Open Marketplace Phase 1 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Создать локально работающий и проверенный поток `регистрация → подтверждение email → вход и безопасность → заявка продавца → решение сотрудника → допуск и аудит` без каталога, денег, облака и настоящих документов.

**Architecture:** Один Django-проект и одна PostgreSQL-база образуют модульный монолит. Пять предметных модулей (`identity`, `access`, `seller_onboarding`, `audit`, `outbox`) публикуют небольшие интерфейсы через `public.py`; HTML, Django Admin, management-команды и worker вызывают эти интерфейсы и не меняют защищённые модели напрямую.

**Tech Stack:** Python 3.13.15, Django 5.2.17 LTS, PostgreSQL 17.11, psycopg 3.3.5, cryptography 50.0.1, PyOTP 2.10.0, uv 0.12.9, Import Linter 2.14, Mailpit 1.31.0, Docker Compose.

**Spec:** `D:/Open_Marketplace/docs/superpowers/specs/2026-09-02-phase-1-identity-access-design.md`

## Global Constraints

- Корень будущего Git-репозитория: `D:/Open_Marketplace`.
- Git-репозиторий создаётся только в Task 1; до запуска этого плана его нет.
- Пользовательский интерфейс: только server-rendered HTML Django. JSON API и Django REST Framework отсутствуют.
- Служебный интерфейс: только защищённый Django Admin с вызовом прикладных операций.
- PostgreSQL является единственной базой; SQLite запрещён даже в интеграционных тестах.
- Секреты находятся только в `.env`; `.env` обязательно игнорируется Git. В плане и фикстурах открытых секретов нет.
- TOTP-секрет шифруется с проверкой целостности; пароли хеширует Django; recovery codes и одноразовые токены хранятся только как необратимые отпечатки.
- Состояние партии, каталога, денег, заказов и иные будущие общие данные в эту фазу не добавляются.
- Реальные документы, KYC/AML, production email, Redis, Celery, Kafka, Kubernetes и облачное развёртывание отсутствуют.
- Каждая изменяющая операция создаёт допустимый аудит и применимое outbox-сообщение в той же транзакции.
- Django signals не координируют бизнес-переходы.
- Каждая задача с продуктовым кодом содержит явный сфокусированный цикл RED → минимальная реализация → GREEN и заканчивается отдельным коммитом. Task 1 сначала создаёт необходимое окружение, затем проводит первый RED/GREEN; финальные интеграционные задачи не подменяют модульные циклы.
- Все команды выполняются скрыто через внутренние инструменты Hermes из `D:/Open_Marketplace`; внешнее окно терминала не открывается.
- Исходники не подключаются в контейнер через bind-mount. Поэтому каждая команда `docker compose ... run` после изменения кода использует `--build`; запуск старого образа не считается проверкой.

## Fixed Versions and Images

```text
Python:          3.13.15
Django:          5.2.17
psycopg[binary]: 3.3.5
cryptography:    50.0.1
PyOTP:           2.10.0
Import Linter:   2.14
uv:              0.12.9
PostgreSQL:      17.11
Mailpit:         1.31.0
```

```text
python:3.13.15-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e
postgres:17.11-bookworm@sha256:051f7b7b3abdd564d5d1bd1e8c4b9c1b6e77087d1dd22020ede611c096a272e0
axllent/mailpit:v1.31.0@sha256:c96991d9bef73594c246d89ca81411d4e916f03e76a7d2d72fa2ab5dd3c9ce24
ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff
```

## Fixed Security Configuration

The checked-in Django settings expose these exact named phase-1 values; later tasks consume them rather than repeating literals inside business logic:

- `EMAIL_VERIFICATION_TTL = 24 hours`;
- `PASSWORD_RESET_TTL = 30 minutes`;
- `STAFF_INVITATION_TTL = 24 hours`;
- `MANDATORY_TOTP_RECOVERY_TTL = 30 minutes`;
- `SENSITIVE_ACTION_REAUTH_TTL = 15 minutes`;
- `TOTP_SETUP_TTL = 10 minutes`;
- `RECOVERY_CODE_COUNT = 10`;
- `PASSWORD_MIN_LENGTH = 12` and `PASSWORD_MAX_LENGTH = 128`, with Django common-password validation;
- `ORDINARY_SESSION_ABSOLUTE_TTL = 30 days`;
- `SERVICE_SESSION_ABSOLUTE_TTL = 12 hours` and `SERVICE_SESSION_IDLE_TTL = 30 minutes`;
- `LOGIN_THROTTLE_THRESHOLD = 5` with `LOGIN_THROTTLE_WINDOW = 15 minutes`, `LOGIN_THROTTLE_INITIAL_DELAY = 5 seconds` and `LOGIN_THROTTLE_MAX_DELAY = 60 seconds`; the first five failed attempts are recorded without a pre-authentication denial, then the next attempt is delayed for 5 seconds, and every subsequently permitted failed attempt doubles the next delay through 10, 20 and 40 seconds to the 60-second cap;
- `EMAIL_THROTTLE_LIMIT = 3` with `EMAIL_THROTTLE_WINDOW = 1 hour` independently per purpose plus source limit.

Task 1 architecture tests assert these exact settings. The responsible feature task tests the just-before/at/just-after boundary with an injected `Clock`; expiry and reauthentication are invalid when `now >= deadline`.

## Shared Public Contracts

All public view/result objects below are immutable dataclasses; enums use the exact string values shown. Public adapters receive these objects, never ORM models.

```python
AccountKind = Literal["ordinary", "service"]
AccountState = Literal["pending_email_verification", "active", "blocked"]
SessionRevocationReason = Literal[
    "logout", "user_revoked", "other_sessions_revoked", "password_changed",
    "password_reset", "optional_totp_disabled", "mandatory_totp_recovered",
    "account_blocked", "role_changed", "compromised",
]
StaffRole = Literal["seller_reviewer", "security_admin"]
SellerApplicationState = Literal[
    "draft", "submitted", "under_review", "changes_requested",
    "approved", "rejected", "withdrawn",
]
SellerState = Literal["awaiting_owner_totp", "active", "suspended", "revoked"]
OutboxState = Literal["pending", "processing", "retry_wait", "succeeded", "manual_review"]
OutboxMessageType = Literal[
    "identity.email_verification",
    "identity.password_reset",
    "access.staff_invitation",
    "seller_onboarding.application_decision",
    "identity.protected_account_change",
    "seller_onboarding.admission_change",
]
ThrottleScope = Literal["login", "registration_email", "password_reset_email", "staff_invitation_email"]
TotpRequirementSource = Literal["staff_role", "seller_profile"]

PermissionCode = Literal[
    "seller_application.read", "seller_application.review",
    "staff.invite", "staff.invitation_revoke", "staff.role_revoke",
    "account.read", "account.block", "account.unblock", "identity.mandatory_totp_recover",
    "seller.read", "seller.suspend", "seller.restore", "seller.revoke",
    "audit.read", "outbox.manual_retry",
]
```

```python
NeutralAccepted(accepted: Literal[True])
AccountSnapshot(id: UUID, email: str, kind: AccountKind, state: AccountState,
                email_verified_at: datetime | None, totp_enabled: bool)
AccountQuery(kind: AccountKind | None, state: AccountState | None,
             canonical_email: str | None, limit: int, cursor: UUID | None)
AuthenticationResult(account_id: UUID, kind: AccountKind, authenticated_at: datetime,
                     session_id: UUID)
SessionView(id: UUID, created_at: datetime, last_activity_at: datetime,
            absolute_expires_at: datetime, device_label: str,
            is_current: bool, revoked_at: datetime | None)
SessionSecuritySnapshot(id: UUID, account_id: UUID, revoked_at: datetime | None,
                        absolute_expires_at: datetime,
                        reauthenticated_at: datetime | None)
TotpSetupView(setup_id: UUID, manual_secret: str, provisioning_uri: str,
              expires_at: datetime)
ThrottleDecision(allowed: bool, retry_after_seconds: int)
```

```python
AuditQuery(from_at: datetime | None, to_at: datetime | None,
           actor_id: UUID | None, action: str | None,
           object_type: str | None, object_id: str | None,
           result: str | None, limit: int, cursor: UUID | None)
AuditEntryView(id: UUID, occurred_at: datetime, actor_id: UUID | None,
               effective_role: str | None, action: str, object_type: str,
               object_id: str, result: str, reason: str | None,
               request_id: UUID, before: dict[str, object],
               after: dict[str, object], source: str)
ClaimedMessage(id: UUID, message_type: OutboxMessageType, format_version: int,
               payload: dict[str, object], encrypted_delivery: bytes | None,
               idempotency_key: str, attempt_number: int)
OutboxQuery(state: OutboxState, message_type: OutboxMessageType | None,
            limit: int, cursor: UUID | None)
OutboxMessageView(id: UUID, message_type: OutboxMessageType, state: OutboxState,
                  attempts: int, next_attempt_at: datetime | None,
                  last_safe_error: str | None, created_at: datetime)
```

Every supported outbox type has only `format_version = 1` in phase 1 and uses this closed schema:

- `identity.email_verification`: safe payload `{account_id, token_id}`; encrypted delivery `{recipient, absolute_token_url}`; SMTP.
- `identity.password_reset`: safe payload `{account_id, token_id}`; encrypted delivery `{recipient, absolute_token_url}`; SMTP.
- `access.staff_invitation`: safe payload `{invitation_id, role}`; encrypted delivery `{recipient, absolute_token_url}`; SMTP.
- `seller_onboarding.application_decision`: safe payload `{application_id, decision}`; encrypted delivery `{recipient}`; SMTP.
- `identity.protected_account_change`: safe payload `{account_id, change}`; encrypted delivery `{recipient}`; SMTP.
- `seller_onboarding.admission_change`: safe payload `{seller_id, state}`; `encrypted_delivery` is `None`; idempotent local handler.

Identifiers are canonical UUID strings; `role` is a `StaffRole`; `decision` is exactly `request_changes`, `approve` or `reject`; `change` is exactly `password_reset`, `password_changed`, `totp_enabled`, `totp_disabled`, `totp_recovered`, `account_blocked`, `account_unblocked` or `role_changed`; and admission `state` is a `SellerState`. No other payload or delivery key/value is accepted. The encrypted delivery plaintext is itself validated against the exact per-type schema before encryption and again after decryption.

```python
StaffAcceptanceMode = Literal["new_service_account", "existing_service_account"]
StaffAcceptanceSetup(acceptance_id: UUID, account_id: UUID,
                     mode: StaffAcceptanceMode,
                     totp_setup: TotpSetupView | None)
StaffAcceptanceResult(assignment_id: UUID, recovery_codes: tuple[str, ...])
RoleAssignmentView(id: UUID, account_id: UUID, role: StaffRole,
                   active_from: datetime, revoked_at: datetime | None)
StaffInvitationView(id: UUID, email: str, role: StaffRole, state: str,
                    expires_at: datetime, accepted_at: datetime | None)
StaffInvitationQuery(state: str | None, role: StaffRole | None,
                     canonical_email: str | None, limit: int, cursor: UUID | None)
```

```python
SellerDraftData(business_form: Literal["sole_proprietor", "legal_entity", "self_employed"],
                display_name: str, official_name: str,
                registration_identifier: str, contact_email: str,
                test_data_attested: bool)
SellerApplicationView(id: UUID, applicant_id: UUID,
                      state: SellerApplicationState, current_version: int,
                      reviewer_id: UUID | None, decision: str | None,
                      reason: str | None, created_at: datetime,
                      submitted_at: datetime | None)
SellerApplicationVersionView(application_id: UUID, version_number: int,
                             data: SellerDraftData, submitted_at: datetime)
SellerReviewQuery(states: tuple[SellerApplicationState, ...],
                  reviewer_id: UUID | None, limit: int, cursor: UUID | None)
SellerProfileView(id: UUID, owner_id: UUID, application_id: UUID,
                  approved_version: int, state: SellerState,
                  restriction_reason: str | None)
SellerProfileQuery(state: SellerState | None, owner_id: UUID | None,
                   limit: int, cursor: UUID | None)
```

Expected application errors are typed as `InputRejected`, `AuthenticationDenied`, `PermissionDenied`, `InvalidState`, `ConcurrentConflict`, `TokenRejected` and `RateLimited`. Adapters map them to neutral HTML/Admin responses; unexpected exceptions retain only a correlation/request ID outside internal logs.

These shared error types live in `open_marketplace/common/errors.py`. Feature modules reuse them instead of defining incompatible module-local variants.

## Planned File Map

```text
D:/Open_Marketplace/
  .dockerignore
  .env.example
  .gitignore
  .python-version
  Dockerfile
  README.md
  compose.yaml
  compose.test.yaml
  manage.py
  pyproject.toml
  uv.lock
  ops/verify_restore.sh
  docs/security/phase-1-review.md
  docs/runbooks/local-development.md
  docs/runbooks/test-and-restore.md
  open_marketplace/
    __init__.py
    config/{settings.py,urls.py,asgi.py,wsgi.py}
    common/{types.py,errors.py,crypto.py,clock.py}
    identity/{apps.py,domain.py,managers.py,models.py,application.py,public.py,middleware.py,migrations/,tests/}
    access/{apps.py,domain.py,models.py,application.py,public.py,migrations/,management/commands/,tests/}
    seller_onboarding/{apps.py,domain.py,models.py,application.py,public.py,migrations/,tests/}
    audit/{apps.py,models.py,application.py,public.py,migrations/,tests/}
    outbox/{apps.py,models.py,application.py,public.py,migrations/,management/commands/,tests/}
    workflows/totp.py
    web/{forms.py,identity_views.py,staff_views.py,seller_views.py,sensitive_links.py,middleware.py,errors.py,logging.py,urls.py,tests/}
    staff_admin/{site.py,identity_admin.py,access_admin.py,seller_admin.py,audit_admin.py,outbox_admin.py,tests/}
    verification/{apps.py,management/commands/,tests/}
    templates/{base.html,registration/,identity/,staff/,seller/,admin/}
    tests/{test_architecture.py,test_full_flows.py,test_security.py,test_scope_boundaries.py,test_migrations.py}
```

---

### Task 1: Git, locked environment, containers, Django skeleton, module contracts

**Objective:** Получить воспроизводимый пустой Django-проект, который запускается на PostgreSQL и уже запрещает недопустимые импорты.

**Files:**
- Create: `.gitignore`, `.dockerignore`, `.env.example`, `.python-version`
- Create: `pyproject.toml`, `uv.lock`, `Dockerfile`, `compose.yaml`, `compose.test.yaml`
- Create: `manage.py`, `open_marketplace/config/settings.py`, `open_marketplace/config/urls.py`, `open_marketplace/config/asgi.py`, `open_marketplace/config/wsgi.py`
- Create: `open_marketplace/common/types.py`, `open_marketplace/common/clock.py`
- Create empty package files for all five modules, `web`, `staff_admin`, `workflows`, and `open_marketplace/tests/test_architecture.py`

**Interfaces:**
- Produces: `OperationSource = Literal["html", "admin", "command", "worker"]` and `OperationContext(actor_account_id: UUID | None, session_id: UUID | None, request_id: UUID, source: OperationSource, source_address: str | None, now: datetime)` in `common/types.py`. HTML/Admin contexts carry the server registry session UUID plus the request's server-observed `REMOTE_ADDR`; commands/workers use `None` for address and use `None` for session unless acting through a real registry session.
- Produces: `Clock.now() -> datetime` and injectable `SystemClock`.
- Produces: `AuthorizationDecision(account_id: UUID, permission: str, effective_roles: tuple[str, ...], scopes: tuple[str, ...], reauthenticated_at: datetime | None)` and `Authorize`, a protocol with `__call__(context: OperationContext, permission: str) -> AuthorizationDecision`; protected modules call it internally to check rights, scope and required freshness without importing `access` and creating a cycle.
- Global actor rule: a protected operation obtains the actor only from `context.actor_account_id`. It never accepts a separate `reviewer_id` or `administrator_id`; ordinary own-resource operations either derive the owner from context or compare the target account to context inside the operation.
- Produces: `lint-imports` contracts that allow `seller_onboarding -> identity.public/access.public`, allow all changing modules to use `audit.public/outbox.public`, and forbid reverse/cyclic dependencies.

- [ ] **Step 1: Initialize only the approved repository**

Run:

```bash
cd D:/Open_Marketplace
git init
git branch -M main
```

Expected: repository root is exactly `D:/Open_Marketplace`; существующие Markdown-документы остаются без изменений.

- [ ] **Step 2: Write the environment manifest**

`pyproject.toml` must contain these direct dependencies and no others:

```toml
[project]
name = "open-marketplace"
version = "0.1.0"
requires-python = "==3.13.15"
dependencies = [
  "Django==5.2.17",
  "psycopg[binary]==3.3.5",
  "cryptography==50.0.1",
  "PyOTP==2.10.0",
]

[dependency-groups]
dev = [
  "import-linter==2.14",
]

[tool.uv]
package = false

[tool.importlinter]
root_package = "open_marketplace"
include_external_packages = false

[[tool.importlinter.contracts]]
name = "Common primitives are domain-independent"
type = "forbidden"
source_modules = ["open_marketplace.common"]
forbidden_modules = [
  "open_marketplace.identity",
  "open_marketplace.access",
  "open_marketplace.seller_onboarding",
  "open_marketplace.audit",
  "open_marketplace.outbox",
]

[[tool.importlinter.contracts]]
name = "Identity does not depend on access or seller onboarding"
type = "forbidden"
source_modules = ["open_marketplace.identity"]
forbidden_modules = ["open_marketplace.access", "open_marketplace.seller_onboarding"]

[[tool.importlinter.contracts]]
name = "Access does not depend on seller onboarding"
type = "forbidden"
source_modules = ["open_marketplace.access"]
forbidden_modules = ["open_marketplace.seller_onboarding"]

[[tool.importlinter.contracts]]
name = "Audit and outbox do not call subject modules"
type = "forbidden"
source_modules = ["open_marketplace.audit", "open_marketplace.outbox"]
forbidden_modules = [
  "open_marketplace.identity",
  "open_marketplace.access",
  "open_marketplace.seller_onboarding",
  "open_marketplace.workflows",
  "open_marketplace.web",
  "open_marketplace.staff_admin",
  "open_marketplace.verification",
]

[[tool.importlinter.contracts]]
name = "Audit does not depend on outbox"
type = "forbidden"
source_modules = ["open_marketplace.audit"]
forbidden_modules = ["open_marketplace.outbox"]

[[tool.importlinter.contracts]]
name = "Subject modules do not depend on external coordinators or adapters"
type = "forbidden"
source_modules = [
  "open_marketplace.identity",
  "open_marketplace.access",
  "open_marketplace.seller_onboarding",
]
forbidden_modules = [
  "open_marketplace.workflows",
  "open_marketplace.web",
  "open_marketplace.staff_admin",
  "open_marketplace.verification",
]

[[tool.importlinter.contracts]]
name = "Identity internals are protected"
type = "protected"
protected_modules = [
  "open_marketplace.identity.application",
  "open_marketplace.identity.domain",
  "open_marketplace.identity.managers",
  "open_marketplace.identity.middleware",
  "open_marketplace.identity.models",
]
allowed_importers = ["open_marketplace.identity"]

[[tool.importlinter.contracts]]
name = "Access internals are protected"
type = "protected"
protected_modules = [
  "open_marketplace.access.application",
  "open_marketplace.access.domain",
  "open_marketplace.access.models",
]
allowed_importers = ["open_marketplace.access"]

[[tool.importlinter.contracts]]
name = "Seller onboarding internals are protected"
type = "protected"
protected_modules = [
  "open_marketplace.seller_onboarding.application",
  "open_marketplace.seller_onboarding.domain",
  "open_marketplace.seller_onboarding.models",
]
allowed_importers = ["open_marketplace.seller_onboarding"]

[[tool.importlinter.contracts]]
name = "Audit internals are protected"
type = "protected"
protected_modules = [
  "open_marketplace.audit.application",
  "open_marketplace.audit.models",
]
allowed_importers = ["open_marketplace.audit"]

[[tool.importlinter.contracts]]
name = "Outbox internals are protected"
type = "protected"
protected_modules = [
  "open_marketplace.outbox.application",
  "open_marketplace.outbox.models",
]
allowed_importers = ["open_marketplace.outbox"]
```

Do not add Import Linter ignore rules to make a failing contract pass. Tests outside a protected module create state through public test builders exposed by that module, not by importing its models.

- [ ] **Step 3: Generate `uv.lock` with the approved uv image**

Run:

```bash
docker run --rm -v "D:/Open_Marketplace:/workspace" -w /workspace ghcr.io/astral-sh/uv:0.12.9-python3.13-trixie-slim@sha256:f0a4f125bb15cf64eeee78a687f00bfb3ae4cd8863a3d8bb0b625fdffb4467ae /usr/local/bin/uv lock --python 3.13.15
```

Expected: `uv.lock` exists; `uv lock --check` exits 0 on a second run.

- [ ] **Step 4: Create safe environment templates**

`.env.example` contains this safe template:

```dotenv
DJANGO_SECRET_KEY=
DATABASE_NAME=open_marketplace
DATABASE_USER=open_marketplace
DATABASE_PASSWORD=
DATABASE_HOST=postgres
DATABASE_PORT=5432
TOTP_ENCRYPTION_KEY=
OUTBOX_ENCRYPTION_KEY=
LINK_EXCHANGE_ENCRYPTION_KEY=
THROTTLE_HASH_KEY=
DEBUG=false
DJANGO_SECURE_COOKIES=false
ALLOWED_HOSTS=localhost,127.0.0.1
APP_BASE_URL=http://localhost:8000
EMAIL_HOST=mailpit
EMAIL_PORT=1025
```

`.gitignore` includes `.env`, `.venv/`, `.model-launcher-runtime/`, `__pycache__/`, `.coverage`, `artifacts/` and database dumps. `.dockerignore` independently excludes `.env`, `.git/`, `.venv/`, `.model-launcher-runtime/`, `artifacts/`, dumps, caches and local editor metadata; excluding a file only from Git is not sufficient because `COPY . .` consumes the Docker build context. During execution, create `.env` without printing values, using the pinned Python image rather than the non-canonical host Python:

```bash
docker run --rm -i -v "D:/Open_Marketplace:/workspace" -w /workspace \
  python:3.13.15-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e \
  python - <<'PY'
from base64 import urlsafe_b64encode
from pathlib import Path
from secrets import token_bytes, token_urlsafe

template = Path(".env.example").read_text(encoding="utf-8")
values = {
    "DJANGO_SECRET_KEY": token_urlsafe(64),
    "DATABASE_PASSWORD": token_urlsafe(32),
    "TOTP_ENCRYPTION_KEY": urlsafe_b64encode(token_bytes(32)).decode("ascii"),
    "OUTBOX_ENCRYPTION_KEY": urlsafe_b64encode(token_bytes(32)).decode("ascii"),
    "LINK_EXCHANGE_ENCRYPTION_KEY": urlsafe_b64encode(token_bytes(32)).decode("ascii"),
    "THROTTLE_HASH_KEY": urlsafe_b64encode(token_bytes(32)).decode("ascii"),
}
lines = []
for line in template.splitlines():
    name, separator, current = line.partition("=")
    lines.append(f"{name}={values.get(name, current)}" if separator else line)
Path(".env").write_text("\n".join(lines) + "\n", encoding="utf-8")
PY
git check-ignore .env
```

Expected: `.env` exists, no secret is printed, and `git check-ignore .env` exits 0.

Settings have no development fallback for `DJANGO_SECRET_KEY`, `DATABASE_PASSWORD`, `TOTP_ENCRYPTION_KEY`, `OUTBOX_ENCRYPTION_KEY`, `LINK_EXCHANGE_ENCRYPTION_KEY` or `THROTTLE_HASH_KEY`. They fail at startup on missing/empty/malformed values, naming only the variable and never echoing its value; Fernet-compatible keys decode to exactly 32 bytes and the HMAC key has at least 32 random bytes. Architecture tests exercise each invalid case with sanitized captured output.

- [ ] **Step 5: Create pinned Docker and Compose configuration**

`Dockerfile` has a runtime target without test tools and a test target with the development group:

```dockerfile
FROM ghcr.io/astral-sh/uv:0.12.9@sha256:8b940d3a9d65bed080436972241af2e21c84b5e8c9193f7014ed71479ee795ff AS uv
FROM python:3.13.15-slim-bookworm@sha256:ed86c82274b3c69b52fb5820f358f0bd7df0b603332063cb5c6e32bd220c3e6e AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PATH="/app/.venv/bin:$PATH"
WORKDIR /app
COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project
RUN useradd --create-home --uid 10001 appuser
COPY --chown=appuser:appuser . .
USER appuser
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]

FROM runtime AS test
USER root
RUN uv sync --locked --dev --no-install-project
USER appuser
CMD ["python", "manage.py", "test", "open_marketplace", "-v", "2"]
```

Settings validate `APP_BASE_URL` at startup as an absolute configured `http`/`https` origin with no credentials, query or fragment; local development uses the shown localhost URL. Email-link generation never derives its origin from request `Host` or forwarding headers.

`compose.yaml` defines `postgres`, `mailpit`, `web`, and `worker`. Use the pinned PostgreSQL and Mailpit images, `env_file: .env`, the named volume `postgres_data`, and a `pg_isready` health check. Because the application variables are named `DATABASE_*` while the official image initializes from `POSTGRES_*`, the `postgres` service explicitly maps `POSTGRES_DB: ${DATABASE_NAME:?required}`, `POSTGRES_USER: ${DATABASE_USER:?required}` and `POSTGRES_PASSWORD: ${DATABASE_PASSWORD:?required}`; it does not rely on `env_file` to rename them. The health check uses the configured database and user. `web` and `worker` build target `runtime`; `worker` runs `python manage.py run_outbox_worker`; both depend on healthy PostgreSQL. `web` exposes `8000:8000`; Mailpit exposes `8025:8025` and `1025:1025`. No password literal appears in Compose.

`compose.test.yaml` adds `postgres-test` with the pinned PostgreSQL image, the same explicit `DATABASE_* → POSTGRES_*` initialization mapping and a `tmpfs` data directory, plus a `test` service that builds target `test`, reads `.env`, overrides `DATABASE_HOST=postgres-test`, and depends on the healthy test database. It must not attach `postgres_data`. This separation makes `lint-imports` available in every command that uses the `test` service and prevents tests from touching development data. Architecture smoke verification includes `docker compose ... config` and asserts both rendered database services contain non-empty `POSTGRES_DB`, `POSTGRES_USER` and `POSTGRES_PASSWORD` keys without printing their values.

- [ ] **Step 6: Write the failing architecture smoke test**

```python
from datetime import timedelta

from django.test import SimpleTestCase
from django.conf import settings

class ProjectSmokeTests(SimpleTestCase):
    def test_postgresql_is_the_only_database_engine(self):
        self.assertEqual(settings.DATABASES["default"]["ENGINE"], "django.db.backends.postgresql")

    def test_drf_is_not_installed(self):
        self.assertNotIn("rest_framework", settings.INSTALLED_APPS)

    def test_phase_one_security_values_are_exact(self):
        expected = {
            "EMAIL_VERIFICATION_TTL": timedelta(hours=24),
            "PASSWORD_RESET_TTL": timedelta(minutes=30),
            "STAFF_INVITATION_TTL": timedelta(hours=24),
            "MANDATORY_TOTP_RECOVERY_TTL": timedelta(minutes=30),
            "SENSITIVE_ACTION_REAUTH_TTL": timedelta(minutes=15),
            "RECOVERY_CODE_COUNT": 10,
            "PASSWORD_MIN_LENGTH": 12,
            "PASSWORD_MAX_LENGTH": 128,
            "ORDINARY_SESSION_ABSOLUTE_TTL": timedelta(days=30),
            "SERVICE_SESSION_ABSOLUTE_TTL": timedelta(hours=12),
            "SERVICE_SESSION_IDLE_TTL": timedelta(minutes=30),
            "LOGIN_THROTTLE_THRESHOLD": 5,
            "LOGIN_THROTTLE_WINDOW": timedelta(minutes=15),
            "EMAIL_THROTTLE_LIMIT": 3,
            "EMAIL_THROTTLE_WINDOW": timedelta(hours=1),
        }
        for name, value in expected.items():
            with self.subTest(name=name):
                self.assertEqual(getattr(settings, name), value)

        validators = {
            item["NAME"] for item in settings.AUTH_PASSWORD_VALIDATORS
        }
        self.assertIn(
            "django.contrib.auth.password_validation.CommonPasswordValidator",
            validators,
        )
```

- [ ] **Step 7: Run RED, implement settings, then run GREEN**

Run before settings exist:

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace.tests.test_architecture -v 2
```

Expected RED: settings/package import failure.

After implementation run:

```bash
docker compose config --quiet
docker compose -f compose.yaml -f compose.test.yaml config --quiet
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py check
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test lint-imports --no-cache
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace.tests.test_architecture -v 2
docker compose run --rm --build --no-deps web sh -c 'test ! -e /app/.env && test ! -e /app/.git'
docker compose -f compose.yaml -f compose.test.yaml run --rm --build --no-deps test sh -c 'test ! -e /app/.env && test ! -e /app/.git'
```

Expected GREEN: both Compose configurations interpolate all required database initialization variables without printing them; Django check has no issues; all import contracts are kept; smoke tests pass; and neither image contains `.env` or `.git` from the build context.

- [ ] **Step 8: Commit**

```bash
git add .
git commit -m "build: initialize locked Django environment"
```

---

### Task 2: Custom account before the first migration

**Objective:** Создать канонический email-account и гарантировать, что Django никогда не мигрирует стандартного пользователя.

**Files:**
- Create: `open_marketplace/identity/domain.py`, `managers.py`, `models.py`, `public.py`
- Create: `open_marketplace/identity/tests/test_account_model.py`
- Create: `open_marketplace/identity/migrations/0001_initial.py`
- Modify: `open_marketplace/config/settings.py`

**Interfaces:**
- Produces: `AccountId = UUID`.
- Produces: `canonicalize_email(value: str) -> str`: first `trimmed = value.strip()`, then Django validates `trimmed`, then the function returns `trimmed.casefold()`.
- Produces: `get_account_snapshot(account_id: UUID) -> AccountSnapshot` through `identity.public`.

- [ ] **Step 1: Write failing account tests**

Tests must prove: case-insensitive uniqueness, external whitespace trimming, email confirmation state, immutable `kind`, service accounts are separate, password is hashed, and default superuser creation is rejected.

```python
class AccountModelTests(TestCase):
    def test_email_is_trimmed_and_casefolded(self):
        account = Account.objects.create_user(email="  User@Example.COM ", password="correct horse battery staple")
        self.assertEqual(account.email, "user@example.com")
        self.assertTrue(account.check_password("correct horse battery staple"))
```

- [ ] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace.identity.tests.test_account_model -v 2
```

Expected: FAIL because `Account` does not exist.

- [ ] **Step 3: Implement the minimum model**

Use `AbstractBaseUser`; fields are UUID primary key, canonical unique email, `kind`, `state`, `email_verified_at`, timestamps and optimistic `version`. `is_active` derives from `state == active`; `is_staff` derives from service kind plus active state and is not an authorization decision. `create_superuser()` raises an explicit exception directing the operator to `bootstrap_security_admin`.

Set:

```python
AUTH_USER_MODEL = "identity.Account"
```

before any migration command.

- [ ] **Step 4: Create and inspect the first migration**

```bash
docker rm -f open-marketplace-task2-makemigrations 2>/dev/null || true
docker compose -f compose.yaml -f compose.test.yaml run --name open-marketplace-task2-makemigrations --build test python manage.py makemigrations identity
mkdir -p open_marketplace/identity/migrations
docker cp open-marketplace-task2-makemigrations:/app/open_marketplace/identity/migrations/. open_marketplace/identity/migrations/
docker rm open-marketplace-task2-makemigrations
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py migrate --plan
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py migrate --noinput
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py shell -c 'from django.db import connection; tables = set(connection.introspection.table_names()); assert "identity_account" in tables; assert "auth_user" not in tables'
```

Expected: first identity migration creates `identity_account`; `migrate --plan` may still list Django's swappable `auth.0001 Create model User` operation, but live PostgreSQL introspection proves that `auth_user` was not created.

- [ ] **Step 5: Run GREEN and full checks**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace.identity.tests.test_account_model -v 2
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test lint-imports --no-cache
```

- [ ] **Step 6: Commit**

```bash
git add open_marketplace/identity open_marketplace/config/settings.py
git commit -m "feat: add canonical account model"
```

---

### Task 3: Append-only audit module

**Objective:** Создать единственный интерфейс добавления аудита без прикладного изменения или удаления существующих записей.

**Files:**
- Create: `open_marketplace/common/errors.py`
- Create: `open_marketplace/audit/apps.py`, `models.py`, `application.py`, `public.py`
- Create: `open_marketplace/audit/migrations/0001_initial.py`
- Create: `open_marketplace/audit/tests/test_audit.py`
- Modify: `open_marketplace/config/settings.py`

**Interfaces:**

```python
append_audit_entry(
    *, context: OperationContext, action: str, object_type: str,
    object_id: str, result: str, reason: str | None,
    before: dict[str, object], after: dict[str, object],
    effective_role: str | None,
) -> UUID
```

```python
query_audit_entries(
    *, query: AuditQuery, context: OperationContext,
    authorize: Authorize,
) -> tuple[AuditEntryView, ...]
```

The operation calls `decision = authorize(context, "audit.read")` internally, intersects every requested filter with `decision.scopes`, enforces a bounded `limit`, and never accepts raw SQL/filter fragments. This avoids an `audit -> access` import cycle without trusting the HTML/Admin adapter to skip or broaden authorization.

`before` and `after` are flat dictionaries. Their only permitted keys are `kind`, `state`, `email_verified`, `totp_enabled`, `role`, `requirement_source`, `version`, `decision`, `session_count`, `revoked_session_count`, `message_type`, `format_version`, `attempt_number`, `next_attempt_at`, `token_purpose`, `subject_fingerprint`, `source_fingerprint` and `expires_at`. Values are bounded `str`, `int`, `bool` or `None`; datetimes use a UTC ISO-8601 string, and fingerprints are fixed 64-character lowercase hexadecimal HMAC digests. Object/account/application/session identifiers remain in the dedicated actor/object columns and are not duplicated into these dictionaries. Unknown keys, nested containers and non-scalar values are rejected before persistence.

Exact audit bounds are closed phase-1 constants: `action`, `object_type`, `result` and `effective_role` are at most 64 characters; `object_id` is at most 128; `reason` is at most 1024; string values inside `before`/`after` are at most 256; integer values are from `0` through `2**63 - 1`; and query `limit` is from `1` through `100`. Violations raise `InputRejected` rather than truncating or clamping data.

Audit queries order entries newest first by `(occurred_at, id)`. A cursor is the UUID of the final entry returned by the previous page and resumes strictly after that row within the same authorized-and-requested result set; an unknown cursor is rejected. Audit scopes use only `audit:<field>:<value>` where `<field>` is `actor_id`, `action`, `object_type`, `object_id` or `result`. Multiple values for one field are ORed; different fields are ANDed. Requested filters are always ANDed with the resulting authorized predicate. Empty, malformed or unknown audit scopes deny access rather than broadening it.

- [ ] **Step 1: Write RED tests**

Prove append succeeds; existing entries reject repeated instance `save`, `save(update_fields=...)`, `delete`, QuerySet `update`/`delete`/`bulk_update` and manager `update_or_create`; every listed before/after key and scalar type is accepted while an unknown key, nested container, overlong value, out-of-range integer or malformed fingerprint/datetime is rejected; `password`, `token`, `secret`, `totp`, `recovery_code` keys are rejected at any attempted nesting; missing `audit.read` is denied; malformed/empty scopes deny; reviewer/security scopes cannot be widened through query filters; and the exact limit/cursor/order boundaries are enforced.

- [ ] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace.audit.tests -v 2
```

- [ ] **Step 3: Implement append-only model and manager**

Register `AuditConfig` in Django settings before creating the migration. Use UUID actor/object identifiers rather than ForeignKey imports. The model permits only initial insert through the audit append manager; it rejects direct create/bulk-create, every existing-instance save/delete plus QuerySet/manager bulk or update path, and is never registered with model Admin. Keep database migrations/raw operator maintenance outside the application runtime as the only explicit escape path.

- [ ] **Step 4: Run GREEN and migration checks**

```bash
docker rm -f open-marketplace-task3-makemigrations 2>/dev/null || true
docker compose -f compose.yaml -f compose.test.yaml run --name open-marketplace-task3-makemigrations --build test python manage.py makemigrations audit
mkdir -p open_marketplace/audit/migrations
docker cp open-marketplace-task3-makemigrations:/app/open_marketplace/audit/migrations/. open_marketplace/audit/migrations/
docker rm open-marketplace-task3-makemigrations
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py makemigrations --check --dry-run
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py migrate --plan
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace.audit.tests -v 2
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-09-02-phase-1-identity-access.md open_marketplace/common/errors.py open_marketplace/audit open_marketplace/config/settings.py
git commit -m "feat(audit): add append-only audit log"
```

---

### Task 4: Transactional outbox with lease recovery

**Objective:** Надёжно сохранить и повторить email/internal events без длинной транзакции и без повторения предметного действия.

**Files:**
- Create: `open_marketplace/outbox/apps.py`, `models.py`, `application.py`, `public.py`
- Create: `open_marketplace/outbox/migrations/0001_initial.py`
- Create: `open_marketplace/outbox/tests/test_outbox.py`, `test_concurrency.py`
- Modify: `open_marketplace/config/settings.py`

**Interfaces:**

```python
enqueue_outbox_message(*, message_type: OutboxMessageType, format_version: Literal[1],
                       payload: dict[str, object], delivery: dict[str, str] | None,
                       idempotency_key: str) -> UUID
claim_ready_messages(*, worker_id: str, now: datetime, lease_seconds: int, limit: int) -> list[ClaimedMessage]
mark_message_succeeded(*, message_id: UUID, worker_id: str,
                       attempt_number: int, now: datetime) -> None
schedule_message_retry(*, message_id: UUID, worker_id: str,
                       attempt_number: int, now: datetime, safe_error: str) -> None
mark_message_for_manual_review(*, message_id: UUID, worker_id: str,
                               attempt_number: int, now: datetime,
                               safe_error: str, context: OperationContext) -> None
retry_message_from_manual_review(*, message_id: UUID, reason: str, context: OperationContext, authorize: Authorize) -> None
query_manual_review_messages(*, query: OutboxQuery, context: OperationContext, authorize: Authorize) -> tuple[OutboxMessageView, ...]
```

`enqueue_outbox_message` is the only encryption boundary. It validates the exact phase-1 payload and delivery schema for `(message_type, format_version)` and then encrypts the delivery dictionary with `OUTBOX_ENCRYPTION_KEY`; subject modules never construct ciphertext or read the key directly. The persisted safe payload never contains `recipient`, `absolute_token_url` or another delivery field. SMTP delivery requires a valid email recipient of at most 320 characters; token URLs are absolute `http`/`https` URLs of at most 2048 characters with no credentials or fragment. The internal seller-admission event requires `delivery is None`. Encrypted delivery is at most 8192 bytes and is erased only on terminal success. Decryption in the later worker validates the same exact schema again before use.

Outbox identifiers in payload are canonical lowercase UUID strings. `role`, `decision`, `change` and seller `state` use only the closed values in the shared contract; no unknown key, nested value or extra delivery field is accepted. `idempotency_key` and `worker_id` are 1–128 characters from `[A-Za-z0-9._:-]`. Duplicate idempotency keys raise `ConcurrentConflict` without creating a second row. `safe_error` is a non-secret machine code of 1–128 lowercase characters from `[a-z0-9_.-]`, not raw exception text. A manual retry reason is trimmed, non-empty and at most 1024 characters.

Phase-1 retry constants are closed: five automatic delivery attempts; `lease_seconds` from 1 through 300; claim and query `limit` from 1 through 100; and retry delay `min(60 * 2 ** (attempt_number - 1), 3600)` seconds. Attempt numbers are monotonic and never reset, including after manual review. A completion or retry transition succeeds only while state is `processing`, `worker_id` and `attempt_number` match the current claim, and the lease is still active at `now`; stale or expired claims raise `ConcurrentConflict`. At attempt five the worker uses `mark_message_for_manual_review` rather than scheduling another automatic retry. A manual retry keeps the same row and idempotency key, clears lease/error fields, becomes immediately claimable and grants the next monotonic attempt.

`query_manual_review_messages` and `retry_message_from_manual_review` both call `authorize(context, "outbox.manual_retry")` internally and require a matching account/permission decision. Outbox scopes use only `outbox:<field>:<value>` where `<field>` is `state`, `message_type` or `id`; values within one field are ORed and different fields are ANDed. Empty, malformed or unknown scopes deny access. The query accepts only `state="manual_review"`, applies requested `message_type` as an additional narrowing filter, orders newest first by `(created_at, id)`, and uses the final row UUID as a cursor within the same authorized result set. Manual retry selects its target through the same authorized predicate. Both transition into and retry out of `manual_review` append an audit record inside the same database transaction without copying ciphertext or delivery plaintext.

- [ ] **Step 1: Write RED state-machine and concurrency tests**

Cover `pending → processing → succeeded`, `processing → retry_wait`, exact exponential delay, fifth attempt → `manual_review`, expired lease reclamation, stale/expired owner or attempt completion denial after reclaim (including reused worker ID), all six exact message payload/delivery schemas, encryption-at-rest and ciphertext erasure after success, duplicate idempotency key rejection and two workers using `select_for_update(skip_locked=True)`. Also prove every numeric/string boundary, malformed safe-error code, invalid URL/recipient, manual-review query/retry denial without `outbox.manual_retry`, matching decision actor, required reason, closed scope intersection, stable cursor ordering, monotonic manual retry and atomic audit rollback without exposing encrypted delivery.

- [ ] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace.outbox.tests -v 2
```

- [ ] **Step 3: Implement short transactional claims**

Register `OutboxConfig` in Django settings before generating the migration. The model stores UUID id, type/version, safe JSON payload, encrypted binary delivery, unique idempotency key, created time, monotonic attempts, next-attempt time, claim time, worker id, lease expiry, state, bounded safe-error code and success time. Claim and state update occur inside `transaction.atomic()` with PostgreSQL `select_for_update(skip_locked=True)`. Every completion/retry transition locks the row and checks state, worker, attempt and active lease; stale results cannot close a reclaimed attempt. External delivery is never called by `claim_ready_messages`. Public results are immutable dataclasses and never expose an ORM model.

- [ ] **Step 4: Run GREEN with `TransactionTestCase`**

```bash
docker rm -f open-marketplace-task4-makemigrations 2>/dev/null || true
docker compose -f compose.yaml -f compose.test.yaml run --name open-marketplace-task4-makemigrations --build test python manage.py makemigrations outbox
mkdir -p open_marketplace/outbox/migrations
docker cp open-marketplace-task4-makemigrations:/app/open_marketplace/outbox/migrations/. open_marketplace/outbox/migrations/
docker rm open-marketplace-task4-makemigrations
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py makemigrations --check --dry-run
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py migrate --plan
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace.outbox.tests -v 2
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-09-02-phase-1-identity-access.md open_marketplace/outbox open_marketplace/config/settings.py
git commit -m "feat(outbox): add leased transactional outbox"
```

---

### Task 5: Registration, email verification and one-time token primitive

**Objective:** Реализовать нейтральную регистрацию и подтверждение email на одном безопасном механизме одноразовых токенов.

**Files:**
- Create: `open_marketplace/common/crypto.py`
- Create: `open_marketplace/identity/application.py`
- Create: `open_marketplace/identity/tests/test_registration.py`, `test_tokens.py`, `test_registration_concurrency.py`
- Modify: `open_marketplace/identity/domain.py`, `models.py`, `public.py`
- Create: identity migration for `OneTimeToken`

**Interfaces:**

```python
register_account(*, email: str, password: str, context: OperationContext) -> NeutralAccepted
verify_email(*, raw_token: str, context: OperationContext) -> UUID
```

`NeutralAccepted` is a frozen, slotted identity-domain dataclass whose only field is `accepted: Literal[True]`; every valid registration request returns the same `NeutralAccepted(accepted=True)`. Registration requires an anonymous `OperationContext` and validates/canonicalizes email before database access. The canonical email is at most 254 characters. Password input is a string of 12–128 characters and passes every configured Django validator, including common-password, numeric-password and account/email similarity validation. The password hash is computed before looking up the email on every new, pending, active, blocked and service-account path so the expensive operation does not reveal account existence; only a new ordinary account stores that hash.

For a new email, one outer transaction creates an ordinary `pending_email_verification` Account, token, audit entry and outbox message. For an existing pending ordinary account, the stored password and Account version remain unchanged; the operation revokes the prior active email-verification token and creates a new token, audit and outbox message. Existing active/blocked accounts and every service account return the same neutral result without account/token/audit/outbox mutation. Public registration can therefore never issue a token that activates a staff-invitation account. A missing-row creation race is resolved through the canonical-email uniqueness constraint and a savepoint, after which the winning Account row is locked; simultaneous requests produce one Account and one active verification token, never a duplicate account.

`OneTimeToken` stores UUID id, `PROTECT` Account relation, purpose, unique lowercase SHA-256 digest, explicit created/expiry times, use time, revocation time and bounded revocation reason. Purpose values are exactly `email_verification`, `password_reset` and `mandatory_totp_recovery`. Phase-1 revocation reasons used here are exactly `superseded` and `account_verified`. Database constraints require `expires_at > created_at`, forbid a token from being both used and revoked, and require revocation timestamp/reason to be null or non-null together. An active token is unconsumed, unrevoked and unexpired. New issuance revokes prior active tokens of the same account and purpose as `superseded`.

Raw tokens are generated with `secrets.token_urlsafe(32)`, have exactly 43 URL-safe `[A-Za-z0-9_-]` characters and are stored only as `sha256(raw_token)`; malformed or oversized token input is rejected before hashing. The verification URL is exactly `{APP_BASE_URL}/identity/verify-email/{raw_token}/`. It is built only from validated settings and never from request Host/forwarding headers. Identity passes outbox type `identity.email_verification`, safe payload `{account_id, token_id}`, plaintext delivery `{recipient, absolute_token_url}` and idempotency key `identity.email_verification:{token_id}`; outbox owns encryption.

Registration audit actions are exactly `identity.account_registered` and `identity.email_verification_reissued`; verification uses `identity.email_verified`. Audit contains only allowlisted state/kind/email-verified/token-purpose/expiry metadata and UUID object IDs, never email, password, hash, digest or raw token. Active/blocked/service neutral no-op responses create no audit entry.

`verify_email` uses `context.now` as the sole clock and treats `now >= expires_at` as expired. Unknown, malformed, wrong-purpose, expired, used, revoked, wrong-kind and wrong-state tokens all raise the same generic `InputRejected`. It first resolves only candidate IDs, then locks in the fixed Account → Token order and rechecks every condition. Success changes only a pending ordinary account to active, sets `email_verified_at = context.now`, increments Account version, marks the selected token used, revokes every other unconsumed/unrevoked email-verification token as `account_verified`, appends audit in the same transaction and returns the Account UUID. Concurrent use succeeds once. Do not use Django signals.

- [ ] **Step 1: Write RED registration/token tests**

Cover all new/pending/active/blocked/service branches; immutable neutral result; email/password/type/length/common/numeric/similarity boundaries; unchanged pending password and Account version; 43-character token format and digest-only storage; configured-origin link despite hostile Host/forwarding values; exact outbox payload/delivery/idempotency; audit allowlist; 24-hour just-before/at/after boundary; purpose isolation; unknown/malformed/used/revoked/wrong-state generic rejection; one-time use; prior-token revocation; Account version transition; no clear email/password/token/digest in audit or safe outbox/account/token fields; and transaction rollback on audit/outbox failure.

Use `TransactionTestCase` to prove simultaneous same-email registration creates one Account and one active token, and concurrent verification succeeds only once without deadlock.

- [ ] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.identity.tests.test_registration open_marketplace.identity.tests.test_tokens open_marketplace.identity.tests.test_registration_concurrency -v 2
```

Expected RED: `OneTimeToken`, `NeutralAccepted`, `register_account` and `verify_email` do not exist.

- [ ] **Step 3: Implement minimal token and registration operations**

Keep cryptographic token generation/hash helpers domain-independent in `common.crypto`; orchestration, model access, configured URL construction, audit and outbox calls stay inside identity application code. Use one outer `transaction.atomic()` per domain operation, nested savepoints only for the canonical-email creation race, and the fixed Account → OneTimeToken lock order. Do not add HTTP, email sending, throttle persistence or password-reset behavior in this task.

- [ ] **Step 4: Run GREEN, migration and rollback checks**

Inject audit and outbox failures and prove no account/token state commits partially. Generate the migration in a named container and copy it out because Compose source is image-copied rather than bind-mounted.

```bash
docker rm -f open-marketplace-task5-makemigrations 2>/dev/null || true
docker compose -f compose.yaml -f compose.test.yaml run --name open-marketplace-task5-makemigrations --build test python manage.py makemigrations identity
mkdir -p open_marketplace/identity/migrations
docker cp open-marketplace-task5-makemigrations:/app/open_marketplace/identity/migrations/. open_marketplace/identity/migrations/
docker rm open-marketplace-task5-makemigrations
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py makemigrations --check --dry-run
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py migrate --plan
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.identity.tests.test_registration open_marketplace.identity.tests.test_tokens open_marketplace.identity.tests.test_registration_concurrency -v 2
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/plans/2026-09-02-phase-1-identity-access.md open_marketplace/common/crypto.py open_marketplace/identity
git commit -m "feat(identity): add registration and email verification"
```

---

### Task 6: Primary authentication and revocable sessions

**Objective:** Реализовать нейтральную проверку пароля, атомарную выдачу серверного сеанса после неё, rotation contract и точечный отзыв.

**Files:**
- Modify: `open_marketplace/identity/models.py`, `application.py`, `public.py`
- Create: `open_marketplace/identity/middleware.py`
- Create: identity migration for `AccountSession`
- Create: `open_marketplace/identity/tests/test_authentication.py`, `test_sessions.py`

**Interfaces:**

```python
authenticate_account(*, email: str, password: str, second_factor: str | None,
                     django_session_key: str, device_label: str,
                     context: OperationContext) -> AuthenticationResult
log_out_session(*, context: OperationContext) -> None
list_sessions(*, context: OperationContext) -> tuple[SessionView, ...]
revoke_session(*, session_id: UUID, context: OperationContext) -> None
revoke_other_sessions(*, context: OperationContext) -> int
revoke_sessions_for_security_event(*, account_id: UUID,
                                   reason: SessionRevocationReason,
                                   context: OperationContext) -> int
get_session_security_snapshot(*, session_id: UUID, account_id: UUID) -> SessionSecuritySnapshot
```

`authenticate_account` is the only public login entry. In Task 6 it supports accounts without enabled/mandatory TOTP; Task 8 adds second-factor verification behind the same final signature. It derives the account from verified credentials and creates its registry row itself, so no adapter can pass a different account ID. The adapter rotates/creates the server-side Django session key before the call, passes it once, and writes browser login state only from the successful `AuthenticationResult`.

**Fixed Task 6 contract:**

- `AccountSession` owns a UUID public identifier and an internal unique `django_session_key` with Django's 40-character storage bound. Authentication accepts the key only when the corresponding Django database-session row exists, is not expired at `context.now`, and no registry row has ever claimed the key. The raw key never appears in public values, exceptions, audit payloads or logs.
- `device_label` is plain text: remove Unicode control characters, collapse whitespace, strip, use `Unknown device` when empty, and keep at most 200 Unicode code points. HTML escaping remains the responsibility of the later template adapter.
- Explicit revocation reasons are exactly `SessionRevocationReason`. A revoked row has both `revoked_at` and `revoked_reason`; a live row has neither. Session keys are never reused after revocation.
- `list_sessions` returns only the actor's live, unexpired sessions. Unknown, foreign, revoked or expired `session_id` values are indistinguishable through one `AuthenticationDenied`. `revoke_other_sessions` preserves the valid current session.
- Expiry is invalid when `now >= deadline`. Natural absolute/idle expiry is not rewritten as revocation and does not create revocation audit. Explicit revocation and logout update the registry and append audit in the same transaction.
- Middleware first requires an exact Django-key/account/registry tuple and rejects blocked, revoked, absolute-expired or service-idle-expired state. Only then may it load `request.user`; it updates `last_activity_at` when at least one minute has elapsed, never more often.
- Login throttling counters and delay remain owned by the later security-throttling task. Task 6 only creates HMAC-SHA-256 subject/source fingerprints for allowlisted failed-login audit fields; raw unknown email and source address never enter audit or logs.

- [ ] **Step 1: Write RED authentication/session tests**

Cover unknown/existing email parity, blocked/unverified denial, authenticated account/session binding, rejection without valid credentials, rotated-key contract, raw Django session key never exposed or logged, bounded/plain-text device labels from hostile user-agent input, own-only list/revoke, current-session logout, ordinary 30-day absolute expiry, service 12-hour absolute and 30-minute idle expiry, immediate enforcement of database revocation, and safe audit for successful/failed authentication plus session creation/revocation. Unknown-email and source-address values never enter audit openly or produce a distinguishable external result.

- [ ] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.identity.tests.test_authentication open_marketplace.identity.tests.test_sessions -v 2
```

- [ ] **Step 3: Implement session registry and middleware**

Use Django database sessions. `authenticate_account` verifies credentials and creates `AccountSession` plus success audit in one application transaction; no public post-authentication registration function accepts an account ID. Failed attempts write only allowlisted generic outcome metadata keyed by request ID and, where needed, a `THROTTLE_HASH_KEY` HMAC fingerprint rather than raw unknown email/address. Session logout/revocation writes audit in the same transaction as registry state. `AccountSession` stores the Django server key only as sensitive internal data and exposes its own UUID. After success, web stores only returned `account_id` and registry `session_id` in the server-side Django session. `identity.middleware` is the sole adapter allowed to import the Account model: on every protected request it compares the current Django key/account/registry tuple, loads the current account internally into `request.user`, updates `last_activity_at` at most once per minute, and flushes revoked, expired, blocked or mismatched sessions. Role, seller state and reauthentication are never cached as browser authority; protected operations re-read them server-side.

- [ ] **Step 4: Run GREEN**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.identity.tests.test_authentication open_marketplace.identity.tests.test_sessions -v 2
```

- [ ] **Step 5: Commit**

```bash
git add open_marketplace/identity
git commit -m "feat: add primary authentication and revocable sessions"
```

---

### Task 7: Password reset and authenticated password change

**Objective:** Добавить одноразовый 30-минутный сброс и безопасную смену пароля с отзывом уже существующих сеансов.

**Files:**
- Modify: `open_marketplace/identity/application.py`, `public.py`
- Create: `open_marketplace/identity/tests/test_passwords.py`

**Interfaces:**

```python
request_password_reset(*, email: str, context: OperationContext) -> NeutralAccepted
reset_password(*, raw_token: str, new_password: str, context: OperationContext) -> None
change_password(*, current_password: str, new_password: str, context: OperationContext) -> None
```

**Fixed Task 7 contract:**

- `request_password_reset` validates and canonicalizes a valid email but always returns the same `NeutralAccepted`. It issues a reset only for an email-verified ordinary or service account whose state is `active` or `blocked`; unknown and pending accounts cause no token, audit or outbox mutation. Reset never changes account state or TOTP state, so a blocked account stays blocked.
- A new request revokes every older active password-reset token as `superseded`, creates a 30-minute token and sends exactly `{APP_BASE_URL}/identity/reset-password/{raw_token}/` through `identity.password_reset` with payload `{account_id, token_id}` and encrypted delivery `{recipient, absolute_token_url}`.
- Malformed, unknown, wrong-purpose, expired, used, revoked or newly ineligible reset tokens all raise one generic `InputRejected`. Expiry is invalid at `context.now >= expires_at`. Password validation happens before token consumption; a weak password or one matching the current password is rejected without token/account/session mutation.
- Successful reset and authenticated change increment `Account.version`, revoke every live session including the current session for `change_password`, and revoke every other active password-reset token. Token revocation reasons are exactly `superseded`, `password_reset_completed` and `password_changed`; the selected reset token is marked used, not revoked.
- Anonymous reset calls a private locked session-revocation helper only after the token has proved the target account. The public `revoke_sessions_for_security_event` wrapper remains protected by a valid current session and must not be weakened for reset.
- Reset completion and authenticated change send `identity.protected_account_change` with safe payload `{account_id, change}` where change is respectively `password_reset` or `password_changed`, and encrypted delivery `{recipient}`. Passwords, password hashes and raw/digested tokens never enter audit, outbox safe payloads or logs.
- Account/password/token/session/audit/outbox effects are one outer transaction. Injected audit or outbox failure rolls back password, Account version, token consumption/revocation and session revocation together.

- [ ] **Step 1: Write RED password tests**

Cover known/unknown neutral response, 30-minute expiry, purpose isolation, one-time use, newer-token revocation of older reset tokens, current-password proof, password validators, all-session revocation, notification outbox and audit without clear token/password.

- [ ] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.identity.tests.test_passwords -v 2
```

- [ ] **Step 3: Implement reset/change operations**

Both final operations lock the account and applicable token, hash through Django, call the session-revocation primitive, revoke sibling reset tokens, and write subject/audit/outbox in one outer transaction. Injected audit/outbox failure must roll back password and revocations.

- [ ] **Step 4: Run GREEN and commit**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.identity.tests.test_passwords open_marketplace.identity.tests.test_sessions -v 2
git add open_marketplace/identity
git commit -m "feat: add protected password recovery"
```

---

### Task 8: TOTP setup, authentication and recovery codes

**Objective:** Реализовать добровольный/обязательный TOTP и одноразовые recovery codes без хранения открытого секрета.

**Files:**
- Modify: `open_marketplace/identity/models.py`, `domain.py`, `application.py`, `public.py`
- Modify: `open_marketplace/config/settings.py`, `open_marketplace/tests/test_architecture.py`
- Create: identity migrations for `TotpSetup`, `TotpCredential`, `TotpRequirement`, `RecoveryCode`
- Create: `open_marketplace/identity/tests/test_totp.py`, `test_recovery_codes.py`

**Interfaces:**

```python
begin_totp_setup(*, current_password: str, context: OperationContext) -> TotpSetupView
enable_totp(*, setup_id: UUID, code: str, context: OperationContext) -> tuple[str, ...]
authenticate_account(*, email: str, password: str, second_factor: str | None,
                     django_session_key: str, device_label: str,
                     context: OperationContext) -> AuthenticationResult
reauthenticate_session(*, password: str, second_factor: str | None,
                       context: OperationContext) -> datetime
replace_recovery_codes(*, password: str, second_factor: str, context: OperationContext) -> tuple[str, ...]
disable_optional_totp(*, password: str, second_factor: str, context: OperationContext) -> None
add_totp_requirement(*, account_id: UUID, source_type: TotpRequirementSource,
                     source_id: UUID, context: OperationContext) -> None
remove_totp_requirement(*, account_id: UUID, source_type: TotpRequirementSource,
                        source_id: UUID, context: OperationContext) -> None
```

The requirement operations are cross-module consistency ports, not HTML/Admin routes. Staff-role acceptance/revocation and seller-profile creation/revocation call them inside the same outer transaction as the source transition. A unique `(account_id, source_type, source_id)` row preserves independent requirements; `disable_optional_totp` decides only from these identity-owned rows and therefore does not import `access` or `seller_onboarding`.

**Fixed Task 8 contract:**

- `TOTP_SETUP_TTL` is a checked-in 10-minute security setting. A normal setup is bound to the current Account and `AccountSession`, invalidates the prior unconsumed setup, and is rejected when an active credential already exists. `TotpSetupView` alone returns a 32-character/160-bit Base32 secret and an `otpauth://` URI labelled with the canonical email and issuer `Open Marketplace`; neither value is logged or stored in plaintext.
- `TotpSetup` stores only Fernet ciphertext plus explicit created/expiry/consumed/invalidated times. Success is invalid at `now >= expires_at`, requires the same live account/session, and atomically consumes the setup, creates one active credential and one recovery-code set. A failed/replayed/wrong-account/wrong-session setup confirmation has one generic denial and leaves the setup usable when the code itself was merely wrong.
- TOTP is exactly six digits with a 30-second interval and `valid_window=1`. The matching counter must be strictly greater than `TotpCredential.last_accepted_counter`; enabling stores its first accepted counter so the same code cannot immediately authenticate. Credential secrets remain Fernet-encrypted and only verification code may decrypt them.
- Login with an active credential requires one valid TOTP or recovery code and keeps the same neutral authentication failure as wrong primary credentials. A requirement without an active credential permits a password-only setup-limited session to avoid lockout, but every requirement-protected permission remains denied server-side until TOTP is enabled. Enabling from that session updates `reauthenticated_at` after the first valid code.
- Recovery codes use `secrets.token_urlsafe(16)` (128 random bits, exactly 22 URL-safe characters). Exactly `RECOVERY_CODE_COUNT = 10` are returned once; `RecoveryCode` stores only a unique SHA-256 digest, UUID set identifier, issue/use/revocation times and Account. Any accepted recovery code is marked used in the same transaction as login/reauthentication or the protected operation, and each use receives a secret-free audit entry.
- `reauthenticate_session` accepts `second_factor=None` only when no active credential exists. Password plus required factor are bound to the actor and current live session; success sets `reauthenticated_at=context.now`. Freshness is valid only while `context.now < reauthenticated_at + SENSITIVE_ACTION_REAUTH_TTL`.
- `replace_recovery_codes` verifies password plus current factor, consumes a recovery factor when supplied, revokes the complete prior active set, returns one new 10-code set once and audits replacement without an email notification.
- `disable_optional_totp` verifies password plus current factor and fails while any active requirement exists. Success disables the credential, revokes all unused recovery codes, preserves the current session, revokes every other live session with reason `optional_totp_disabled`, updates current-session reauthentication, and atomically writes audit plus `identity.protected_account_change(change=totp_disabled)`.
- `enable_totp` writes secret-free enable/recovery-set audit and `identity.protected_account_change(change=totp_enabled)`. `AccountSnapshot.totp_enabled` is derived from an active credential. Routine TOTP success is not audited; enable/disable/reauthentication/recovery-set replacement and every recovery-code use are.
- `TotpRequirement` is a unique tombstone row `(account, source_type, source_id)` with `created_at` and nullable `removed_at`. Add-existing and remove-missing/removed are idempotent; a removed row is never resurrected by a delayed repeated add. A genuinely new source has a new UUID. These trusted consistency ports are not exposed as HTML/Admin routes and perform no cross-module import.
- Account/session/setup/credential/recovery/requirement rows use `PROTECT` ownership and database constraints for valid time/state pairs and active uniqueness. Operations lock in the fixed Account → AccountSession → Setup/Credential → RecoveryCode/Requirement order. Any audit/outbox failure rolls back all state and one-time consumption.

- [ ] **Step 1: Write RED TOTP/recovery tests**

Cover encrypted secret, expiring unconfirmed setup, PyOTP six-digit/30-second verification, `valid_window=1`, replay rejection through `last_accepted_counter`, 10 codes shown once, at least 128 random bits per code, SHA-256 storage, one-time recovery use, whole-set revocation/replacement, password+second-factor reauthentication bound to the actor and current non-revoked `context.session_id`, 15-minute freshness boundary, idempotent requirement add/remove, two independent requirement sources, and mandatory-role/seller disable denial until the final requirement is removed.

- [ ] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.identity.tests.test_totp open_marketplace.identity.tests.test_recovery_codes -v 2
```

- [ ] **Step 3: Implement TOTP and second-factor authentication**

Encrypt credentials with Fernet and `TOTP_ENCRYPTION_KEY`. `TotpSetupView` is the only response containing the manual secret/`otpauth://` URI; no QR dependency is added. `enable_totp` consumes a setup only after valid code and returns the newly generated recovery codes once. `authenticate_account` composes primary and second-factor checks and session creation without revealing which factor failed. Own-account operations derive the account and current session only from `OperationContext`.

- [ ] **Step 4: Run GREEN and commit**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.identity.tests.test_authentication open_marketplace.identity.tests.test_totp open_marketplace.identity.tests.test_recovery_codes -v 2
git add open_marketplace/identity
git commit -m "feat: add TOTP and recovery codes"
```

---

### Task 9: Service-role assignments and exact permissions

**Objective:** Создать независимо отзываемые `seller_reviewer`/`security_admin` assignments and the single permission-checking implementation.

**Files:**
- Create: `open_marketplace/access/apps.py`, `domain.py`, `models.py`, `application.py`, `public.py`
- Create: `open_marketplace/access/migrations/0001_initial.py`
- Create: `open_marketplace/access/tests/test_roles.py`, `test_permissions.py`
- Modify: `open_marketplace/config/settings.py`
- Modify: `open_marketplace/identity/application.py`, `public.py`, `tests/test_sessions.py`

**Interfaces:**

```python
check_permission(*, permission: PermissionCode, context: OperationContext) -> AuthorizationDecision
authorize(*, context: OperationContext, permission: PermissionCode) -> AuthorizationDecision
list_active_roles(*, account_id: UUID, context: OperationContext) -> tuple[RoleAssignmentView, ...]
revoke_staff_role(*, assignment_id: UUID, reason: str, context: OperationContext) -> None

# narrow identity.public liveness port; the existing snapshot API remains unchanged
require_live_session_security_snapshot(*, session_id: UUID, account_id: UUID,
                                       now: datetime) -> SessionSecuritySnapshot
```

Exact role matrix:

- `seller_reviewer`: `seller_application.read`, `seller_application.review`, and `audit.read` scoped to seller-application decisions visible to that reviewer.
- `security_admin`: staff invitation/revocation/role-revocation; account read/block/unblock; mandatory-TOTP recovery; seller read/suspend/restore/revoke; `outbox.manual_retry`; and `audit.read` scoped to those security objects.
- A dual-role account gets the union of two independently active assignments. No other mapping, wildcard permission or Django model permission grants domain access.

Exact scope contract:

- `list_active_roles` always authorizes `account.read`; only an active `security_admin` may list roles, including its own, and the target `account_id` never grants self-service access.
- `seller_reviewer` receives these `audit.read` scopes: `audit:object_type:seller_application`, `audit:object_type:seller_application_version`, and `audit:object_type:seller_review_decision`.
- `security_admin` receives these `audit.read` scopes: `audit:object_type:account`, `audit:object_type:session`, `audit:object_type:staff_invitation`, `audit:object_type:role_assignment`, `audit:object_type:seller_profile`, and `audit:object_type:outbox_message`.
- A dual-role account receives the stable de-duplicated union of both audit scope sets.
- `outbox.manual_retry` receives only `outbox:state:manual_review`. Every other phase-1 permission receives an empty scope tuple; no implicit or wildcard scope exists.

- [ ] **Step 1: Write RED role/permission tests**

Cover the exact `PermissionCode` matrix, independent dual roles, no privilege from account `is_staff`, denial for inactive/blocked service accounts, safe audit of denied staff operations, scoped audit decisions, mandatory reason on revoke, no duplicate active assignment, matching TOTP-requirement removal only for the revoked assignment, and session revocation on role change. No generic external `grant_role` operation may exist.

- [ ] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.access.tests.test_roles open_marketplace.access.tests.test_permissions -v 2
```

- [ ] **Step 3: Implement role assignments and authorization**

`authorize`/`check_permission` derive the account only from `context.actor_account_id`; they lock/read current assignments and account snapshot, then call `identity.public.require_live_session_security_snapshot` for every role-backed permission. The identity-owned liveness port validates the UUID inputs and UTC `now`, returns the existing immutable snapshot only when the registry row belongs to the account, is not revoked, is before absolute expiry, is within the service idle TTL and still has a live backing Django database session; otherwise it raises the existing neutral authentication denial. The older `get_session_security_snapshot` remains unchanged for non-authorizing inspection. Authorization returns only exact granting roles/scopes/freshness and raises `PermissionDenied` otherwise. Permissions for review decisions, invitations/role changes, block/unblock, mandatory TOTP recovery, seller admission changes and outbox manual retry require `reauthenticated_at > context.now - settings.SENSITIVE_ACTION_REAUTH_TTL`; equality is expired, and a future timestamp is denied. Role revocation removes its matching identity TOTP requirement and revokes affected sessions in the same outer transaction. Module-local tests may create assignments through an access-local builder; production `public.py` exposes no direct role grant.

- [ ] **Step 4: Run GREEN and contracts**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.access.tests.test_roles open_marketplace.access.tests.test_permissions -v 2
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test lint-imports --no-cache
```

- [ ] **Step 5: Commit**

```bash
git add open_marketplace/access
git commit -m "feat: add exact staff permissions"
```

---

### Task 10: Account block/unblock and mandatory TOTP recovery

**Objective:** Реализовать security-admin операции блокировки, разблокировки и восстановления обязательного TOTP внутри identity с внутренней авторизацией, обязательной причиной и полным отзывом затронутых сеансов.

**Files:**
- Modify: `open_marketplace/identity/domain.py`, `models.py`, `application.py`, `public.py`
- Create: `open_marketplace/identity/migrations/0005_account_administration_and_totp_recovery.py`
- Create: `open_marketplace/identity/tests/test_account_administration.py`, `test_totp_recovery.py`
- Modify: `open_marketplace/outbox/application.py`, `tests/test_outbox.py`
- Modify: существующие test fixtures, создающие `state="blocked"`

**Interfaces:**

```python
block_account(*, account_id: UUID, reason: str, context: OperationContext, authorize: Authorize) -> None
unblock_account(*, account_id: UUID, reason: str, context: OperationContext, authorize: Authorize) -> None
recover_mandatory_totp(*, account_id: UUID, reason: str, context: OperationContext, authorize: Authorize) -> None
begin_mandatory_totp_recovery(*, raw_token: str, current_password: str,
                              context: OperationContext) -> TotpSetupView
complete_mandatory_totp_recovery(*, raw_token: str, setup_id: UUID, code: str, context: OperationContext) -> tuple[str, ...]
query_accounts(*, query: AccountQuery, context: OperationContext, authorize: Authorize) -> tuple[AccountSnapshot, ...]
```

- [ ] **Step 1: Write RED administration/recovery tests**

Cover missing/wrong permission, spoofed actor mismatch, mandatory non-empty reason, exact account state transitions, self-block and self-recovery denial, block metadata integrity, all-session revocation on block/recovery, immediate old credential/code revocation, fail-closed password login when mandatory TOTP has no active credential, denial of ordinary TOTP setup/enable during mandatory recovery, neutral secret-free audit of failed recovery proofs, 30-minute one-time recovery token, current-password proof before a replacement setup, setup/token/account binding, email-only bypass denial, successful replacement code, no automatic login, scoped/bounded account query, exact `identity.mandatory_totp_recovery` outbox schema, and rollback of all effects after injected audit/outbox failure.

- [ ] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.identity.tests.test_account_administration \
  open_marketplace.identity.tests.test_totp_recovery \
  open_marketplace.outbox.tests.test_outbox -v 2
```

- [ ] **Step 3: Implement protected operations**

Each privileged entry calls `authorize(context=context, permission=exact_permission)` inside the outer transaction before mutation, derives the administrator only from the returned decision, locks target state, and writes state/audit/outbox/session changes atomically. Blocking permits only `active -> blocked`, rejects self-blocking, records reason/actor/time/audit linkage, and revokes all live target sessions; unblocking permits only `blocked -> active` and clears current block metadata while immutable audit retains history. Recovery rejects self-recovery, accepts only an active email-verified account with an active mandatory TOTP requirement and either an active credential or a proven unfinished prior recovery, immediately disables the old credential and revokes codes and sessions, then sends a 30-minute link through `identity.mandatory_totp_recovery`. An open administrator-initiated recovery — active mandatory requirement, no active credential, and an unused unrevoked recovery token — fails closed at normal login and rejects ordinary `begin_totp_setup`/`enable_totp`, so only the token-bound recovery path can replace the factor; initial mandatory enrollment without such a token keeps its existing limited setup flow. `begin_mandatory_totp_recovery` validates that emailed token without consuming it, verifies the current password, and creates an encrypted setup bound to that token and account. Completion consumes only that token and its confirmed fresh setup, creates a new credential and recovery-code set, preserves the mandatory requirement, and creates no session. Failed password/TOTP proofs append only neutral HMAC subject/source fingerprints; persistent throttling remains Task 17.

- [ ] **Step 4: Run GREEN and commit**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.identity.tests.test_account_administration \
  open_marketplace.identity.tests.test_totp_recovery \
  open_marketplace.outbox.tests.test_outbox -v 2
git add docs/superpowers open_marketplace/access/tests open_marketplace/identity open_marketplace/outbox
git commit -m "feat: add protected account recovery operations"
```

---

### Task 11: Staff invitations and bootstrap

**Objective:** Создать service accounts only through one-time invitations and activate one exact role only after password/email/TOTP proof.

**Files:**
- Modify: `open_marketplace/access/models.py`, `application.py`, `public.py`
- Create: `open_marketplace/access/migrations/0002_staff_invitations.py`
- Modify: `open_marketplace/identity/application.py`, `public.py`
- Create: `open_marketplace/access/management/commands/bootstrap_security_admin.py`
- Create: `open_marketplace/access/tests/test_invitations.py`, `test_bootstrap.py`

**Interfaces:**

```python
list_staff_invitations(*, query: StaffInvitationQuery, context: OperationContext) -> tuple[StaffInvitationView, ...]
invite_staff_member(*, email: str, role: StaffRole, context: OperationContext) -> UUID
begin_staff_invitation_acceptance(*, raw_token: str, password: str, context: OperationContext) -> StaffAcceptanceSetup
accept_staff_invitation(*, acceptance_id: UUID, raw_token: str,
                        totp_code: str, context: OperationContext) -> StaffAcceptanceResult
revoke_staff_invitation(*, invitation_id: UUID, reason: str, context: OperationContext) -> None
bootstrap_security_admin(*, email: str, context: OperationContext) -> UUID

# narrow identity.public consistency ports; no HTML/Admin route exposes them
provision_service_account_for_invitation(*, email: str, password: str,
    invitation_id: UUID, context: OperationContext) -> tuple[UUID, TotpSetupView]
enable_invited_service_totp(*, account_id: UUID, setup_id: UUID, code: str,
    invitation_id: UUID, context: OperationContext) -> tuple[str, ...]
```

Invitation creation generates a 256-bit token, stores only its SHA-256 hash in `StaffInvitation`, and places the recipient/link only in outbox `encrypted_delivery`; terminal delivery erases that ciphertext. `begin_staff_invitation_acceptance` locks and validates the invitation before calling the narrow identity-public provisioning port. For a new email it creates only an email-verified `kind="service"` account, stores a Django password hash, creates a TOTP setup bound to that account/invitation and returns no role. The pending acceptance is bound to invitation-token hash, account and setup. An existing service account must be the authenticated context actor, have the same canonical email and verify password; its setup is `None`. `accept_staff_invitation` calls the invitation-bound TOTP port for a new account or verifies existing TOTP, adds the role's matching identity TOTP requirement, activates only the invited role, revokes affected sessions and writes credential/recovery/requirement/assignment/audit/outbox atomically. It returns new recovery codes once only for the new-account path; an existing account gets an empty tuple.

- [ ] **Step 1: Write RED invitation/bootstrap tests**

Cover unused email → unprivileged service account → invitation-bound TOTP → role → one-time recovery-code display; ordinary-account rejection; second role for an authenticated existing service account without regenerating recovery codes; one-time/expired/revoked invitation; token hash-only storage plus encrypted delivery and no raw token in audit/logs; no role or TOTP requirement before completion; cross-token/account/setup denial; idempotent pending setup; exact role plus one matching requirement only; permission/scoped filters/bounded cursor on invitation listing; one live bootstrap invitation; and no bootstrap with an active security admin.

- [ ] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.access.tests.test_invitations open_marketplace.access.tests.test_bootstrap -v 2
```

- [ ] **Step 3: Implement invitation workflow and bootstrap command**

The command accepts `--email`, never accepts/prints a password, creates only an auditable invitation and returns the existing live bootstrap result on safe retry. It allows a new invitation only after expiry/revocation and only while no active security admin exists.

- [ ] **Step 4: Verify CLI, GREEN and contracts**

```bash
docker compose run --rm --build web python manage.py bootstrap_security_admin --help
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.access.tests -v 2
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test lint-imports --no-cache
```

Expected: help contains `--email` and no `--password`; all invitation/access tests pass.

- [ ] **Step 5: Commit**

```bash
git add open_marketplace/access open_marketplace/identity/application.py open_marketplace/identity/public.py
git commit -m "feat: add invited staff accounts"
```

---

### Task 12: Seller application drafts, immutable versions and own queries

**Objective:** Реализовать ordinary-account draft/submit/withdraw history with one unfinished application and immutable submitted versions.

**Files:**
- Create: `open_marketplace/seller_onboarding/__init__.py`, `apps.py`, `migrations/__init__.py`, `tests/__init__.py`
- Create: `open_marketplace/seller_onboarding/domain.py`, `models.py`, `application.py`, `public.py`
- Create: `open_marketplace/seller_onboarding/migrations/0001_initial.py`
- Create: `open_marketplace/seller_onboarding/tests/test_applications.py`, `test_versions.py`, `test_concurrency.py`
- Modify: `open_marketplace/config/settings.py`
- Modify: `open_marketplace/outbox/application.py`, `tests/test_outbox.py`

**Interfaces:**

```python
create_seller_application(*, context: OperationContext) -> UUID
update_seller_application_draft(*, application_id: UUID, data: SellerDraftData, context: OperationContext) -> None
submit_seller_application(*, application_id: UUID, context: OperationContext) -> UUID
withdraw_seller_application(*, application_id: UUID, context: OperationContext) -> None
list_own_seller_applications(*, context: OperationContext) -> tuple[SellerApplicationView, ...]
get_own_seller_application(*, application_id: UUID, context: OperationContext) -> tuple[SellerApplicationView, tuple[SellerApplicationVersionView, ...]]
```

- [ ] **Step 1: Write RED draft/version tests**

Cover exact test-only fields, active/verified ordinary owner, own-only access, one unfinished application, allowed draft/submit/withdraw transitions, immutable submitted version, monotonically increasing `(application, version_number)`, separate new history after terminal withdraw, and atomically linked audit plus `seller_onboarding.application_submitted` outbox event.

- [ ] **Step 2: Write RED concurrency tests and run RED**

Use `TransactionTestCase` for simultaneous create, update and submit.

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.seller_onboarding.tests.test_applications open_marketplace.seller_onboarding.tests.test_versions open_marketplace.seller_onboarding.tests.test_concurrency -v 2
```

- [ ] **Step 3: Implement models/constraints/own operations**

Register `SellerOnboardingConfig` in `INSTALLED_APPS`. Add the strict internal outbox type `seller_onboarding.application_submitted` version 1 with payload `{application_id, version_id}` and no delivery data. Use a conditional `UniqueConstraint` for unfinished states and unique `(application, version_number)`. Updates lock the application, compare actor from context, and never update a submitted version. Submission creates/freezes a version and writes audit/outbox in one transaction; withdrawal never deletes history.

- [ ] **Step 4: Run GREEN and commit**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py makemigrations seller_onboarding
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.seller_onboarding.tests.test_applications open_marketplace.seller_onboarding.tests.test_versions open_marketplace.seller_onboarding.tests.test_concurrency -v 2
git add open_marketplace/seller_onboarding open_marketplace/config/settings.py \
  open_marketplace/outbox/application.py open_marketplace/outbox/tests/test_outbox.py
git commit -m "feat: add versioned seller applications"
```

---

### Task 13: Seller review, profile, admission and TOTP activation workflow

**Objective:** Добавить reviewer decisions, one owner/profile, admission transitions and atomic activation after owner TOTP.

**Files:**
- Modify: `open_marketplace/seller_onboarding/models.py`, `application.py`, `public.py`
- Create: `open_marketplace/seller_onboarding/migrations/0002_reviews_and_profiles.py`
- Create: `open_marketplace/workflows/totp.py`
- Create: `open_marketplace/seller_onboarding/tests/test_decisions.py`, `test_admission.py`, `test_review_concurrency.py`

**Interfaces:**

```python
start_seller_application_review(*, application_id: UUID, context: OperationContext) -> None
request_seller_application_changes(*, application_id: UUID, reason: str, context: OperationContext) -> None
approve_seller_application(*, application_id: UUID, reason: str, context: OperationContext) -> UUID
reject_seller_application(*, application_id: UUID, reason: str, context: OperationContext) -> None
list_seller_review_queue(*, query: SellerReviewQuery, context: OperationContext) -> tuple[SellerApplicationView, ...]
get_seller_application_for_review(*, application_id: UUID, context: OperationContext) -> tuple[SellerApplicationView, tuple[SellerApplicationVersionView, ...]]
get_seller_profile_for_owner(*, context: OperationContext) -> SellerProfileView | None
query_seller_profiles(*, query: SellerProfileQuery, context: OperationContext) -> tuple[SellerProfileView, ...]
activate_seller_after_totp(*, seller_id: UUID, context: OperationContext) -> None
suspend_seller(*, seller_id: UUID, reason: str, context: OperationContext) -> None
restore_seller(*, seller_id: UUID, reason: str, context: OperationContext) -> None
revoke_seller(*, seller_id: UUID, reason: str, context: OperationContext) -> None

# open_marketplace.workflows.totp
enable_totp_and_activate_waiting_seller(*, setup_id: UUID, code: str, context: OperationContext) -> tuple[str, ...]
```

- [x] **Step 1: Write RED decision/admission tests**

Cover every review/profile transition, exact reviewer/security permission, mandatory reason, staff non-editability, bounded/scoped review and seller-profile queries, changes-requested → new immutable version → submit, reject/reapply, approved reapplication denial, one owner/profile, owner TOTP deciding `active` vs `awaiting_owner_totp`, independent ordinary account, requirement persistence during suspend/restore, and terminal `revoked` removing only that profile's TOTP requirement.

- [x] **Step 2: Write RED concurrency/idempotency tests**

Use `TransactionTestCase` for simultaneous review claim and approval. `context.request_id` is the sole operation/idempotency identifier: retrying it returns the existing profile and creates no duplicate decision/profile/audit/outbox; a different request against an already decided version fails by state.

- [x] **Step 3: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.seller_onboarding.tests.test_decisions open_marketplace.seller_onboarding.tests.test_admission open_marketplace.seller_onboarding.tests.test_review_concurrency -v 2
```

- [x] **Step 4: Implement review/profile/admission operations**

Use row locks, unique owner/application constraints and one outer transaction for decision/profile/owner/TOTP-requirement/audit/outbox. Profile creation adds an identity `seller_profile` TOTP requirement whether the profile starts active or awaiting TOTP; only terminal seller revocation removes it, in the same transaction. Privileged operations derive actor from context and call `access.public.authorize` internally. `enable_totp_and_activate_waiting_seller` opens one outer transaction, calls `identity.public.enable_totp`, queries the owner's profile, activates only `awaiting_owner_totp`, and rolls credential/recovery/profile/audit/outbox back together on any failure.

Independent review remediation (after commit `425a11d`): decision replay now compares the recorded decision with the retried one; UUID cursor filters match `id` ordering in both review-queue and profile queries; profile admission audits record the real prior state and the mandatory reason; `activate_seller_after_totp` requires an active, email-verified ordinary account with a live session; admission operations return `None` per the approved interfaces; the profile-creation fallback only replays a profile of the same version. Follow-up review found and fixed repeat admission-cycle outbox collisions and stale `restriction_reason` after restore. Final full suite 230/230.

- [x] **Step 5: Run GREEN and contracts**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py makemigrations seller_onboarding
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace.seller_onboarding.tests -v 2
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test lint-imports --no-cache
```

- [x] **Step 6: Commit**

```bash
git add open_marketplace/seller_onboarding open_marketplace/workflows/totp.py
git commit -m "feat: add seller review and admission"
```

---

### Task 14: Identity, sensitive-link and staff-invitation HTML flow

**Objective:** Сделать реальный browser flow for registration, verification, login, password, sessions, TOTP and staff-invitation acceptance without JSON and without leaving raw one-time tokens in rendered pages, redirects, logs or clean-form URLs.

**Files:**
- Create: `open_marketplace/web/forms.py`, `identity_views.py`, `staff_views.py`, `sensitive_links.py`, `middleware.py`, `errors.py`, `logging.py`, `urls.py`
- Create templates under `templates/registration/`, `templates/identity/` and `templates/staff/`
- Create: `open_marketplace/web/tests/test_identity_pages.py`, `test_session_pages.py`, `test_totp_pages.py`, `test_staff_invitation_pages.py`, `test_sensitive_links.py`
- Modify: `open_marketplace/config/urls.py`, `settings.py`

**Interfaces:**
- Identity views consume only `identity.public`; staff invitation pages consume only `access.public`. Seller-owner TOTP activation consumes the `workflows.totp` coordinator.
- Produces named token-free form routes: `register`, `verify-email-complete`, `login`, `logout`, `password-reset-request`, `password-reset-confirm`, `password-change`, `security`, `reauthenticate`, `totp-setup`, `totp-disable`, `recovery-codes-replace`, `mandatory-totp-recovery`, `sessions`, `session-revoke`, `sessions-revoke-others`, and `staff-invitation-accept`. Separate sensitive-link entry routes exist for email verification, password reset, mandatory-TOTP recovery and staff invitation; their token-bearing paths only perform the clean-URL exchange described below.
- A sensitive-link GET accepts the raw email token exactly once at a dedicated route, encrypts it with `LINK_EXCHANGE_ENCRYPTION_KEY` into a purpose-bound envelope stored in the server-side Django session for 10 minutes, and immediately returns `303 See Other` to a token-free URL. It performs no domain mutation. A single-step clean POST consumes and deletes its envelope before calling the public operation. For staff acceptance and mandatory-TOTP recovery, the first POST consumes the initial envelope and, only after successful `begin_*`, replaces it with a 5-minute encrypted continuation envelope containing the same token plus the returned setup/acceptance identifier; the final POST consumes and deletes that continuation before completion. Expired, missing, replayed, cross-session or wrong-purpose envelopes fail neutrally.
- Sensitive-link responses and clean forms send `Cache-Control: no-store` and `Referrer-Policy: no-referrer`; forms never copy a token into HTML, query strings or hidden fields. A logging filter is attached to every configured Django/application handler and redacts sensitive route segments before records are formatted.
- Request middleware generates a new UUID request ID server-side and ignores client attempts to choose it; the same ID enters `OperationContext`, internal logs and an allowed response header. With safe-default `DEBUG=false`, custom `handler500` renders only a neutral page plus that ID. It never renders a traceback, exception text, request body or sensitive path.
- GET is otherwise read-only; logout, email verification completion, password change/reset confirmation, TOTP confirmation/recovery, staff invitation acceptance and session revocation are CSRF-protected POST.
- Login rotates/creates the Django server-side session key before calling `authenticate_account`; the operation binds that key to the credentials-derived account and returns the registry `session_id`. The view writes account/session UUIDs only after success and never calls a separate account-selected session-registration operation. A failed attempt flushes that anonymous key. On following requests, `identity.middleware` reconstructs `request.user` only after registry validation; web and Admin never import the Account model. HTML/Admin context construction takes `source_address` only from `request.META["REMOTE_ADDR"]`; it ignores client-supplied forwarding headers until a future trusted-proxy design explicitly replaces this local rule.
- New staff acceptance is a clean-URL two-step flow: the first POST calls `begin_staff_invitation_acceptance` with password and the initial-envelope token; the second uses the continuation envelope to call `accept_staff_invitation`. The pending account receives no role before completion, and the resulting recovery codes are rendered once under `no-store`. Existing service accounts authenticate normally and then complete TOTP before acceptance without receiving a replacement recovery set. Mandatory-TOTP recovery follows the same continuation pattern with `begin_mandatory_totp_recovery` and `complete_mandatory_totp_recovery`.

- [x] **Step 1: Write RED client and token-hygiene tests**

Use Django `Client(enforce_csrf_checks=True)`. Cover all routes, neutral messages, safe `next` handling, credentials-to-registry-session binding, session rotation, registration/verification/reset/TOTP/session flows, mandatory-TOTP recovery and both new/existing-account staff invitations. With sentinel tokens, captured Django/application logs and rendered bodies, prove every state-changing route rejects missing CSRF; the initial sensitive GET is mutation-free; redirect targets are token-free; initial and continuation envelopes are encrypted, session/purpose-bound, expiring and single-use; and no raw session ID, token or secret is redisplayed or logged. Inject an unexpected operation exception and prove rollback, a neutral response containing only its request/correlation ID, no traceback to the browser, and redacted internal logs. Recovery codes appear once. Settings tests prove `HttpOnly`/`SameSite` defaults and that `DJANGO_SECURE_COOKIES=true` enables secure session/CSRF cookies plus HTTPS redirect/security flags.

- [x] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.web.tests.test_identity_pages open_marketplace.web.tests.test_session_pages open_marketplace.web.tests.test_totp_pages open_marketplace.web.tests.test_staff_invitation_pages open_marketplace.web.tests.test_sensitive_links -v 2
```

- [x] **Step 3: Implement thin forms/views/templates and logging redaction**

Views translate form input into an `OperationContext`, invoke public operations, and map typed expected errors to neutral messages. No view imports another module’s models. Exchange sensitive links before rendering and register the redacting filter on Django request/server loggers. The domain token is never persisted a second time: the short-lived encrypted session envelope is only transport state.

- [x] **Step 4: Run GREEN**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace.web.tests -v 2
```

- [x] **Step 5: Commit**

```bash
git add open_marketplace/web open_marketplace/templates open_marketplace/config
git commit -m "feat: add identity and invitation HTML flows"
```

---

### Task 15: Seller application HTML flow

**Objective:** Дать ordinary account страницы draft/submit/withdraw/status/history/reapplication.

**Files:**
- Modify: `open_marketplace/seller_onboarding/application.py`, `public.py`
- Modify: `open_marketplace/seller_onboarding/tests/test_applications.py`
- Create: `open_marketplace/seller_onboarding/tests/web_fixtures.py`
- Modify: `open_marketplace/web/forms.py`, `urls.py`
- Create: `open_marketplace/web/seller_views.py`
- Create: templates under `templates/seller/`
- Create: `open_marketplace/web/tests/test_seller_pages.py`

**Interfaces:**
- Consumes only `seller_onboarding.public` and `identity.public`.
- Adds `get_own_seller_application_draft(*, application_id, context) -> SellerDraftData | None`; it enforces ownership and editable state inside `seller_onboarding`, returns `None` for a new empty draft, and never exposes draft data through shared list or review views.
- Produces named routes: `seller-application-create`, `seller-application-edit`, `seller-application-submit`, `seller-application-withdraw`, `seller-applications`, `seller-application-detail`, `seller-status`.

- [x] **Step 1: Write RED tests**

Prove the own-only editable-draft query and HTML access, test fields only, immutable submitted version, visible decision reason, new version after changes, separate reapplication after reject/withdraw, one unfinished application and no catalog links/actions.

- [x] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace.seller_onboarding.tests.test_applications open_marketplace.web.tests.test_seller_pages -v 2
```

- [x] **Step 3: Implement minimal pages**

Keep display/edit forms separate. Never render real-document upload fields, payment fields, KYC text or placeholders implying production approval.

- [x] **Step 4: Run GREEN and commit**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace.seller_onboarding.tests.test_applications open_marketplace.web.tests.test_seller_pages -v 2
git add open_marketplace/seller_onboarding/application.py open_marketplace/seller_onboarding/public.py open_marketplace/seller_onboarding/tests/test_applications.py open_marketplace/seller_onboarding/tests/web_fixtures.py open_marketplace/web open_marketplace/templates/seller docs/superpowers/plans/2026-09-02-phase-1-identity-access.md
git commit -m "feat: add seller application HTML flow"
```

---

### Task 16: Protected Django Admin adapters

**Objective:** Реализовать service UI as custom `AdminSite` pages backed only by public query/operation contracts, with no protected model registration, import or save path and with exact role separation.

**Files:**
- Create: `open_marketplace/staff_admin/site.py`
- Create: `identity_admin.py`, `access_admin.py`, `seller_admin.py`, `audit_admin.py`, `outbox_admin.py`
- Create: templates under `open_marketplace/templates/admin/`
- Create: `open_marketplace/staff_admin/tests/test_admin_permissions.py`, `test_admin_operations.py`, `test_admin_boundaries.py`
- Modify: `open_marketplace/config/urls.py`

**Interfaces:**
- Custom `AdminSite.has_permission()` requires an active service account, completed TOTP authentication and at least one active service role. Every list, detail and action view then calls the public query/operation that authorizes its exact `PermissionCode`; possession of any role does not grant another role's reads or actions.
- Custom `AdminSite.login`, `logout`, `password_change` and `password_change_done` do not use Django Admin's default authentication/mutation forms. They redirect with a validated local `next` target to the Task 14 login/logout/password-change routes, which alone create/revoke registry sessions and change credentials. No standard Django authentication backend or Admin form can establish an unregistered service session or write the Account model directly.
- No protected ORM model is registered with Django Admin. `staff_admin` imports only each module's `public.py` contracts and renders custom index/list/detail/form pages from immutable view objects. It does not import protected `models.py`, call managers/querysets, or save/delete domain rows directly.
- Explicit POST views call public operations for decisions, invitations, role revocation, account block/unblock, mandatory TOTP recovery, seller admission and outbox retry. Every operation receives the server-derived `OperationContext`, including the current registry `session_id`; domain authorization independently enforces required permissions and fresh 15-minute reauthentication.

- [ ] **Step 1: Write RED matrix and boundary tests**

Test reviewer-only, security-admin-only, both roles, no role, revoked role, missing TOTP, blocked account, stale reauthentication and fresh reauthentication. Prove security admin cannot review without reviewer role; reviewer cannot invite, recover or change admission; unauthorized list/detail reads fail; default Admin login/logout/password-change paths cannot bypass shared HTML operations or create an unregistered session; and the installed Admin site has no protected model registration. Import-boundary tests reject protected-model imports from `staff_admin`.

- [ ] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace.staff_admin.tests -v 2
```

- [ ] **Step 3: Implement custom public-contract pages and explicit action forms**

Each action form requires a reason where specified and a fresh server-recorded 15-minute reauthentication where required. There is no direct ORM fallback or bulk action path.

- [ ] **Step 4: Run GREEN and architecture checks**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace.staff_admin.tests -v 2
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test lint-imports --no-cache
```

- [ ] **Step 5: Commit**

```bash
git add open_marketplace/staff_admin open_marketplace/templates/admin open_marketplace/config/urls.py
git commit -m "feat: add role-separated staff admin"
```

---

### Task 17: PostgreSQL security throttling

**Objective:** Добавить нейтральные ограничения входа и email-запросов без Redis и без хранения открытых email/IP в счётчиках.

**Files:**
- Modify: `open_marketplace/config/settings.py`
- Modify: `open_marketplace/identity/models.py`, `domain.py`, `application.py`, `public.py`
- Modify: `open_marketplace/access/application.py`
- Create: identity migration for `SecurityThrottle`
- Create: `open_marketplace/identity/management/commands/purge_security_throttles.py`
- Create: `open_marketplace/tests/test_security.py`

**Interfaces:**

```python
check_throttle(*, scope: ThrottleScope, account_key_hash: str,
               source_key_hash: str, now: datetime) -> ThrottleDecision
check_email_throttle(*, scope: Literal["registration_email", "password_reset_email", "staff_invitation_email"],
                     email: str, source_address: str, now: datetime) -> ThrottleDecision
```

- [x] **Step 1: Write RED boundary/concurrency tests**

Cover five failed logins in a fixed 15-minute window anchored at the first recorded failure; the first five failures are permitted and recorded, the next attempt is denied for 5 seconds, and every subsequently permitted failure sets the next delay to 10, 20, 40 and then at most 60 seconds. Cover success not erasing attack evidence, successful login after a bounded delay, independent account and source counters, no permanent account lock from a foreign source, three email requests in a fixed one-hour window per purpose and independently per account/source, equal external messages/timing class for known and unknown email, `REMOTE_ADDR` use with spoofed forwarding headers ignored, no raw address in counters/audit/logs, reset exactly at the fixed-window boundary, fail-closed public throttle inputs, bounded retention cleanup and simultaneous counter updates under `TransactionTestCase`. A throttled staff invitation raises one bounded generic application error and creates neither an invitation nor an outbox message; registration and password reset retain their existing neutral response.

- [x] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.tests.test_security -v 2
```

- [x] **Step 3: Implement PostgreSQL counters**

Use the Task 1 `THROTTLE_HASH_KEY` inside the identity application layer to derive keys. The exact UTF-8 HMAC-SHA-256 inputs are `{scope}\0account\0{canonical_email}` and `{scope}\0source\0{context.source_address}`. Adapters never precompute or persist them; `check_email_throttle` is the narrow public port that lets `access.application` reuse this identity-owned boundary for staff invitations. `SecurityThrottle` stores one row per independent `(scope, key_kind, key_hash)`, where `key_kind` is exactly `account` or `source`, `key_hash` is 64-character lowercase hexadecimal, and a unique constraint protects that tuple. Each row stores only its fixed-window start, allowed-attempt count and optional block-until time; no raw email or address is stored.

`check_throttle` atomically consumes one attempt only when both independent rows currently allow it; exceeding either counter denies the attempt without consuming either row. It creates missing rows with a conflict-safe PostgreSQL upsert, locks account then source rows in deterministic order, resets a row when `now >= window_started_at + configured_window`, and returns only `allowed` plus the maximum bounded seconds until both rows can proceed. For login, `authenticate_account` performs a non-consuming check before password work and calls the consuming counter only after failed authentication; a successful login therefore neither consumes nor erases failure evidence. For email operations, the consuming check occurs before registration/reset/Admin staff-invitation mutation. A throttled registration or password-reset request returns the existing `NeutralAccepted`; a throttled staff invitation raises one bounded generic `RateLimited` error. HTML/Admin operations reject a missing or empty server-observed address. The local `bootstrap_security_admin` command is the sole explicit exemption: it has no network source and is already bounded by the no-active-admin and one-live-bootstrap-invitation invariants; worker paths do not originate these requests. `purge_security_throttles` removes expired rows in bounded lock-skipping batches, never deletes a row whose `blocked_until` is still in the future, and uses an index on `(scope, window_started_at)`; production deployment must schedule this command before exposing the application to untrusted traffic.

- [x] **Step 4: Run GREEN and commit**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.tests.test_security open_marketplace.identity.tests.test_registration open_marketplace.identity.tests.test_passwords open_marketplace.identity.tests.test_authentication -v 2
git add open_marketplace/config/settings.py open_marketplace/identity open_marketplace/access/application.py open_marketplace/tests/test_security.py
git commit -m "feat: add PostgreSQL security throttling"
```

---

### Task 18: Outbox worker and Mailpit delivery

**Objective:** Реализовать реальную фоновую SMTP-доставку с короткими lease transactions, bounded retry and safe failure evidence.

**Files:**
- Create: `open_marketplace/outbox/mail_delivery.py`
- Create: `open_marketplace/outbox/management/commands/run_outbox_worker.py`
- Create: `open_marketplace/outbox/tests/test_worker.py`, `test_mail_delivery.py`
- Modify: `open_marketplace/outbox/application.py`, `open_marketplace/config/settings.py`, `open_marketplace/tests/test_architecture.py`, `compose.yaml`, `compose.test.yaml`

**Interfaces:**
- `run_outbox_worker --once` claims one bounded batch and exits; default mode polls with bounded sleep and handles SIGTERM between deliveries.
- The adapter decrypts only `encrypted_delivery`, sends through Django SMTP, never logs recipient token/content, and erases delivery ciphertext only after terminal success.
- A closed handler registry maps the exact `(message_type, format_version)` pairs: confirmation, password reset, staff invitation, seller decision and protected-account-change notifications use SMTP; the seller-created/admission-changed internal event uses an idempotent local handler that validates the safe payload and completes no domain transition. Unknown type/version is never guessed and moves to `manual_review` with a bounded safe error.

- [x] **Step 1: Write RED worker tests**

Cover every registered type/version, successful SMTP delivery, local internal-event completion without a subject-module call, unknown-version → `manual_review`, `--once`, process crash after send/before success, expired lease reclaim, retry without a second domain token, exponential bounded delay, bounded/redacted safe error, maximum attempts → `manual_review`, and authorized retry resuming the same outbox message/idempotency key.

- [x] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml up -d postgres-test mailpit
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.outbox.tests.test_worker open_marketplace.outbox.tests.test_mail_delivery -v 2
```

- [x] **Step 3: Implement worker/SMTP adapter**

Each claim and final state update uses its own short transaction; SMTP runs outside them. A send with unknown outcome may be delivered again, as required by at-least-once semantics, but it never creates a second account/domain token. The Mailpit test uses a unique non-secret recipient and its HTTP API to verify received subject/type without recording tokenized links.

- [x] **Step 4: Run GREEN, inspect logs and commit**

```bash
docker compose -f compose.yaml -f compose.test.yaml up -d postgres-test mailpit
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.outbox.tests -v 2
mkdir -p artifacts
docker compose -f compose.yaml -f compose.test.yaml logs --no-color mailpit > artifacts/mailpit.log
```

Expected: tests pass. `test_mail_delivery.py` uses sentinel secret values plus captured worker logs to prove no token, password, TOTP secret, `OUTBOX_ENCRYPTION_KEY`, `LINK_EXCHANGE_ENCRYPTION_KEY` or raw delivery ciphertext was logged; the Mailpit service log contains no message body.

```bash
git add compose.yaml compose.test.yaml docs/superpowers/plans/2026-09-02-phase-1-identity-access.md open_marketplace/config/settings.py open_marketplace/outbox open_marketplace/tests/test_architecture.py
git commit -m "feat: add background email delivery"
```

---

### Task 19: Database restore proof

**Objective:** Доказать реальное восстановление из `pg_dump` в отдельную изолированную PostgreSQL-базу без запуска Django test runner против восстановленной базы и без обещаний production RPO/RTO.

**Files:**
- Create: `ops/verify_restore.sh`
- Create: `open_marketplace/verification/apps.py`
- Create: `open_marketplace/verification/_probe.py`
- Create: `open_marketplace/verification/management/commands/seed_restore_probe.py`
- Create: `open_marketplace/verification/management/commands/verify_restore_probe.py`
- Create: `open_marketplace/verification/tests/test_restore_commands.py`
- Create: `docs/runbooks/test-and-restore.md`
- Modify: `open_marketplace/config/settings.py`, `open_marketplace/access/application.py`, `open_marketplace/access/public.py`, `open_marketplace/outbox/application.py`, `open_marketplace/outbox/public.py`, `open_marketplace/seller_onboarding/application.py`, `open_marketplace/seller_onboarding/domain.py`, `open_marketplace/seller_onboarding/public.py`
- Verify existing isolation/ignore settings: `.gitignore`, `compose.test.yaml`

**Interfaces:**
- `seed_restore_probe --marker RESTORE_MARKER` creates deterministic linked rows through public application interfaces for account, role, seller application/version/decision/profile, audit and outbox.
- `seed_restore_probe` refuses to run before its first write unless the active host is exactly `postgres-test` and the database name starts with `test_` or `restore_source_`.
- `verify_restore_probe --marker RESTORE_MARKER` is read-only, consumes public query/snapshot interfaces, fails non-zero when a row, relationship, terminal state or migration is absent, and prints only row kinds, safe identifiers and migration leaf names.
- Restore verification uses the same authorization policy without writing a permission-denial audit entry, including when restored roles or sessions are missing.
- `ops/verify_restore.sh` uses only `postgres-test` with its `tmpfs`; it creates unique source and target databases, restores the source custom dump into the target, runs `migrate --check` and `verify_restore_probe` against the target, drops both databases, deletes the dump and preserves only `artifacts/restore-result.txt`.

- [x] **Step 1: Write RED restore probe**

Write command tests proving: an empty database fails verification; a complete seeded graph passes; deleting each required relationship or row causes a bounded `CommandError`; output contains no email, token, password, TOTP secret, encryption key or database password.

- [x] **Step 2: Run RED**

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.verification.tests.test_restore_commands -v 2
```

Expected RED: the `seed_restore_probe` and `verify_restore_probe` commands do not exist.

- [x] **Step 3: Implement commands and run GREEN**

Register `open_marketplace.verification` as an adapter app. It may import only module `public.py` interfaces; it must not import protected models. Then run:

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.verification.tests.test_restore_commands -v 2
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test lint-imports --no-cache
```

Expected GREEN: command tests pass and module contracts remain intact.

- [x] **Step 4: Implement the exact isolated shell workflow**

`ops/verify_restore.sh` contains this complete workflow:

```bash
#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."
test -f .env
set -a
# shellcheck disable=SC1091
. ./.env
set +a
: "${DATABASE_USER:?required}"

mkdir -p artifacts
compose=(docker compose -f compose.yaml -f compose.test.yaml)
run_id="$(date -u +%Y%m%d%H%M%S)_$$"
source_db="restore_source_${run_id}"
target_db="restore_target_${run_id}"
dump_path="artifacts/phase1_${run_id}.dump"
result_tmp="artifacts/restore-result_${run_id}.txt"
result_path="artifacts/restore-result.txt"
rm -f -- "$result_path"

cleanup() {
  status=$?
  trap - EXIT
  set +e
  cleanup_failed=0
  "${compose[@]}" exec -T postgres-test dropdb --if-exists --maintenance-db=postgres --username "$DATABASE_USER" "$target_db" >/dev/null 2>&1 || cleanup_failed=1
  "${compose[@]}" exec -T postgres-test dropdb --if-exists --maintenance-db=postgres --username "$DATABASE_USER" "$source_db" >/dev/null 2>&1 || cleanup_failed=1
  rm -f -- "$dump_path" || cleanup_failed=1
  if [[ -n "$result_tmp" ]]; then
    rm -f -- "$result_tmp" || cleanup_failed=1
  fi
  if [[ "$cleanup_failed" -ne 0 ]]; then
    rm -f -- "$result_path"
    status=1
  fi
  exit "$status"
}

"${compose[@]}" up -d postgres-test
trap cleanup EXIT
"${compose[@]}" build test
"${compose[@]}" exec -T postgres-test createdb --maintenance-db=postgres --username "$DATABASE_USER" "$source_db"
"${compose[@]}" run --rm -e DATABASE_NAME="$source_db" test python manage.py migrate --noinput
"${compose[@]}" run --rm -e DATABASE_NAME="$source_db" test python manage.py seed_restore_probe --marker "$run_id"
{
  printf 'database=source\n'
  "${compose[@]}" run --rm -e DATABASE_NAME="$source_db" -e PGOPTIONS="-c default_transaction_read_only=on" test python manage.py verify_restore_probe --marker "$run_id"
} > "$result_tmp"
"${compose[@]}" exec -T postgres-test pg_dump --username "$DATABASE_USER" --format=custom --dbname "$source_db" > "$dump_path"
"${compose[@]}" exec -T postgres-test createdb --maintenance-db=postgres --username "$DATABASE_USER" "$target_db"
"${compose[@]}" exec -T postgres-test pg_restore --username "$DATABASE_USER" --exit-on-error --no-owner --dbname "$target_db" < "$dump_path"
{
  printf 'database=target\n'
  "${compose[@]}" run --rm -e DATABASE_NAME="$target_db" test python manage.py migrate --check
  "${compose[@]}" run --rm -e DATABASE_NAME="$target_db" -e PGOPTIONS="-c default_transaction_read_only=on" test python manage.py verify_restore_probe --marker "$run_id"
} >> "$result_tmp"
mv -- "$result_tmp" "$result_path"
result_tmp=""
```

The verification command itself emits only allowlisted row kinds, safe identifiers, invariant results and migration leaves. Therefore the published file contains no Compose environment dump or credentials. The workflow never attaches `postgres_data`, never invokes `manage.py test` against the restored database and leaves the `postgres-test` service available for later test commands while deleting both temporary databases.

- [x] **Step 5: Execute the real restore**

```bash
bash -n ops/verify_restore.sh
bash ops/verify_restore.sh
```

Expected: shell syntax exits 0; restore exits 0; no `artifacts/phase1_*.dump` or result temp remains afterward; the atomically published redacted summary reports source/target migration leaves and every probe invariant as passed; both temporary databases are absent.

- [x] **Step 6: Commit**

```bash
git add docs/superpowers/plans/2026-09-02-phase-1-identity-access.md \
  docs/runbooks/test-and-restore.md ops/verify_restore.sh \
  open_marketplace/config/settings.py open_marketplace/verification \
  open_marketplace/access/application.py open_marketplace/access/public.py \
  open_marketplace/outbox/application.py open_marketplace/outbox/public.py \
  open_marketplace/seller_onboarding/application.py \
  open_marketplace/seller_onboarding/domain.py \
  open_marketplace/seller_onboarding/public.py
git commit -m "test: verify PostgreSQL backup restoration"
```

---

### Task 20: Full flows, documentation, security gate and completion evidence

**Objective:** Доказать все acceptance criteria свежими командами and produce repeatable local runbooks.

**Files:**
- Create: `open_marketplace/tests/test_full_flows.py`, `open_marketplace/tests/test_scope_boundaries.py`, `open_marketplace/tests/test_migrations.py`
- Create: `README.md`, `docs/runbooks/local-development.md`, `docs/security/phase-1-review.md`
- Modify only if a failing acceptance test proves a spec defect in existing implementation files.

**Interfaces:**
- Full-flow tests use only public HTML/Admin/command surfaces and never create protected ORM rows directly. `test_migrations.py` is the sole exception: Django `MigrationExecutor` deliberately uses historical app models to seed the immediate predecessor schema, then verifies current results through public snapshots.
- Security review records severity, evidence, owner and state for every finding; critical/high must have zero unresolved entries.
- If an acceptance/security/migration test reveals an implementation defect, stop the gate, add the minimal regression test to the responsible module, make the surgical fix, rerun that focused suite plus affected contracts, and commit the fix separately before restarting the complete gate. The final documentation commit never hides product-code fixes.

- [x] **Step 1: Write RED tests for all 17 spec-level end-to-end scenarios**

Implement exactly this acceptance matrix:

1. Registration → email → confirmation → login.
2. Expired and reused links are rejected.
3. Password reset revokes previous sessions.
4. TOTP and recovery code work; recovery-code replay fails.
5. Email access alone cannot disable mandatory TOTP.
6. Initial security admin can be bootstrapped only once.
7. A one-time staff invitation grants only its named role.
8. Draft → submit → changes requested → new version → approve.
9. Repeated approve does not create a second seller.
10. Reject leaves the ordinary account active.
11. After reject or withdraw, a new application has separate history and only one unfinished application can exist.
12. Security admin suspends/restores the seller without blocking its owner's ordinary account.
13. A forbidden staff operation is denied and audited.
14. Outbox retry and expired-lease reclaim do not repeat the domain change.
15. Audit reconstructs the action chain and contains no secret.
16. Account block revokes sessions.
17. The test database is really restored into a separate database.

- [x] **Step 2: Write migration compatibility tests**

Use Django `MigrationExecutor` on PostgreSQL. For every non-initial project migration, migrate its app to the immediate predecessor, create the smallest valid predecessor-state rows, migrate to that app's current leaf, and verify preserved identifiers, relationships, defaults and constraints through current public snapshots. Test a clean migration graph separately. The test restores the leaf schema in teardown even after failure and never uses SQLite.

- [x] **Step 3: Run the complete GREEN quality gate**

Local-only checkpoint 2026-09-11: rebuilt images, 407 passing tests (including all 17 acceptance scenarios), migrations, 11 import contracts, expected local-HTTP warnings only, image/repository secrecy checks and real isolated restore passed. See `docs/security/phase-1-local-validation-2026-09-11.md`. This does not complete browser acceptance or independent approval.

Fresh local checkpoint 2026-09-13: after the ordinary-startup documentation updates, the isolated copy passed 407 tests with all 17 scenarios, 11 import contracts, migrations, expected local-HTTP warnings only, secrecy checks and real restore. The separate scope run passed 5/5. See `docs/security/phase-1-local-validation-2026-09-13.md`. Only final evidence documents were updated afterwards; application code remained unchanged. The original demo was preserved and only the copy was stopped. Independent approval is still outstanding.

Post-review checkpoint 2026-09-14: after separately approved R-01/R-03/R-05, the full application suite passed 411/411, including all 17 scenarios, 8 migration checks and 5 scope checks. A later authorized independent static review had returned APPROVE with remarks before those fixes. The current close-out gate is nevertheless incomplete: the unchanged README first-time environment generator failed with `THROTTLE_HASH_KEY is invalid` (VAL-001); the real restore and extra standalone scope run were not executed after that failure. See `docs/security/phase-1-local-validation-2026-09-14.md` and the current summary in `docs/security/phase-1-review.md`. Earlier completed checkboxes and pending-review statements describe their dated historical checkpoints; they do not close the new failure. Step 7 remains open; no README/product fix or Git action is authorized by this result.

Subsequent authorized VAL-001 checkpoint 2026-09-14: one README generator line was corrected without changing application validation or existing keys. The complete corrected generator ran in an empty directory, the actual rebuilt runtime accepted its output, and an existing generated .env was protected from overwrite. With that same fresh environment, the full suite passed 411/411 (17 scenarios, 8 migration checks, 5 scope checks), the standalone scope run passed 5/5, 11 import contracts were kept, and the real pg_dump/pg_restore passed with source/target parity and independently verified cleanup before stopping PostgreSQL. The agreed local gate is complete; see `docs/security/phase-1-local-validation-2026-09-14-after-val-001.md`. The preceding failure checkpoint is historical, not the current status. Final owner acceptance and Git actions remain unapproved; Step 7 stays open.

```bash
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py makemigrations --check --dry-run
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py migrate --noinput
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py check --deploy
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test lint-imports --no-cache
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test python manage.py test open_marketplace -v 2
bash ops/verify_restore.sh
```

Expected: no pending migration, Import Linter contracts kept, zero failed tests, restore exit 0. `check --deploy` warnings caused only by local HTTP settings must be documented and production settings tests must prove secure cookie/HTTPS flags switch on; other warnings are failures.

- [x] **Step 4: Verify repository/image secrecy and scope**

Run:

```bash
if git grep -n -I -E "BEGIN (RSA|OPENSSH|PRIVATE) KEY" -- .; then
  echo "tracked private key material found" >&2
  exit 1
fi
for name in DJANGO_SECRET_KEY DATABASE_PASSWORD TOTP_ENCRYPTION_KEY OUTBOX_ENCRYPTION_KEY LINK_EXCHANGE_ENCRYPTION_KEY THROTTLE_HASH_KEY; do
  if git grep -n -I -E "${name}=[[:space:]]*[^[:space:]]" -- . ':!*.example'; then
    echo "tracked non-empty secret assignment found: ${name}" >&2
    exit 1
  fi
done
git check-ignore .env
test -z "$(git ls-files -- .env)"
docker compose run --rm --build --no-deps web sh -c 'test ! -e /app/.env && test ! -e /app/.git'
docker compose -f compose.yaml -f compose.test.yaml run --rm --build --no-deps test sh -c 'test ! -e /app/.env && test ! -e /app/.git'
docker compose -f compose.yaml -f compose.test.yaml run --rm --build test \
  python manage.py test open_marketplace.tests.test_scope_boundaries -v 2
```

`test_scope_boundaries.py` parses `pyproject.toml` with `tomllib` and enforces the exact approved direct-dependency allowlist after normalizing package names; verifies forbidden apps are absent from `INSTALLED_APPS`; rejects a project `/api` namespace and inspects project-owned URL callbacks (excluding Django's own Admin internals) for JSON/DRF handlers; inspects registered project-model metadata to reject catalog, inventory, order, payment, KYC models and every `FileField`/document-upload field; and scans any tracked fixture files structurally to reject password/token/TOTP/recovery/encryption-key values. Expected: secret scan has no hit, `.env` is ignored and untracked, runtime/test images lack build-context secrets, and the scope test passes. The structured test is authoritative; searching production source for words such as `redis` is not used because security/scope tests must legitimately contain the forbidden names they assert against.

- [x] **Step 5: Perform manual working-result demonstration**

Status: the owner-driven real Chrome flow passed all ten browser-checklist items on 2026-09-13, including the scoped application Audit page and matched Mailpit receipts; see `docs/security/phase-1-browser-acceptance-2026-09-13.md`. The remaining ordinary migrate-then-up command was subsequently verified in an owner-approved isolated copy with the ordinary persistent `postgres` service and alternate loopback ports; see `docs/security/phase-1-ordinary-startup-2026-09-13.md`. These are separate browser and startup proofs; the earlier Django test Client result remains integration evidence only. Step 5 and the fresh local quality gate are complete; valid independent approval and final commit are still outstanding.

After `.env` generation, use the one documented local-start command:

```bash
docker compose run --rm --build web python manage.py migrate --noinput && docker compose up --build
```

Then demonstrate in a local browser and documented CLI: bootstrap creates one security-admin invitation; the new service account accepts it, confirms TOTP and receives recovery codes once without recording them; that admin invites a reviewer; the reviewer accepts and decides a seller application through custom Django Admin pages; the security admin changes seller admission; an ordinary account registers, verifies email, logs in, manages a session and submits the seller application through HTML; Mailpit receives every expected email; audit reconstructs the chain. Use no external terminal window or cloud resource.

Record only non-secret screenshots/command summaries in `docs/security/phase-1-review.md`.

- [x] **Step 6: Write completion documentation**

`README.md` links the approved spec, repeats the exact migrate-then-up command above plus test/restore commands, module map and explicit non-goals. Runbooks explain `.env` generation without exposing values, initial bootstrap, Mailpit, failure recovery and clean shutdown.

- [ ] **Step 7: Final review and commit**

Run the full quality gate again after documentation changes. Then:

```bash
git add README.md docs open_marketplace/tests
git commit -m "docs: complete phase one verification"
git status --short
```

Expected: clean working tree and documented evidence for every criterion in spec section 18.

---

## Plan Self-Review Checklist

- [x] Every requirement in spec sections 1–18 maps to at least one task and test.
- [x] No JSON route, DRF dependency, catalog, inventory, order, payment, cloud or real-document work appears.
- [x] Account is custom before the first migration.
- [x] `SellerProfile.owner` is the sole seller-ownership source; no `seller_owner` role exists.
- [x] One-time secrets are hashed at rest; delivery copies are encrypted; audit/logs exclude them.
- [x] Cross-module transactions write subject change, audit and outbox atomically.
- [x] Concurrency tests use PostgreSQL and `TransactionTestCase`.
- [x] Import Linter verifies all allowed and forbidden module directions.
- [x] Every task has RED, GREEN, focused verification and an atomic commit.
- [x] Repository creation, package installation and product code occur only when this plan is explicitly executed.

## Execution Gate

This plan does not itself create the repository, install packages, write product code or start containers. Execution starts only after Владислав selects an execution mode and explicitly authorizes starting Task 1.
