# Open Marketplace: product catalog

[Русский](README.md) | English

**Current source:** [download the main branch ZIP](https://github.com/VibeSan7/Open_Marketplace/archive/refs/heads/main.zip) · [Changes in v0.4.0](docs/releases/v0.4.0.en.md)

[Archived release v0.2.0](https://github.com/VibeSan7/Open_Marketplace/releases/tag/v0.2.0) remains unchanged and contains the earlier interface.

Run the project on your computer with Docker and open it in a browser. Sellers manage product listings, photos, variants, prices, and stock. Buyers search the catalog and compare verified offers from sellers.

**An open storefront with an optional, separately enabled cart and order demonstration — no real payments.** Digital products can only be saved as unpublished drafts. Running the project locally does not publish a website on the internet.

Guests can browse explicitly public products, photos, search and seller pages. Existing listings remain private after an upgrade: the owner explicitly enables guest visibility after publication. Saved products and demo orders require an active personal account with verified email; private-catalog admission and seller-management permissions remain separate.

This guide is in English. The documentation update does not translate the application interface; Russian button labels are included below where needed.

![Open Marketplace public product storefront](docs/images/storefront-preview.png)

The preview uses synthetic data. A fresh installation is empty; an [optional command](docs/runbooks/storefront-demo-en.md) adds 24 illustrated products, 48 variants, 6 categories and 3 fictional stores. No preset passwords are distributed. [Image credits and licenses](docs/demo-image-credits.md).

## Features

- Registration, email verification, sign-in, two-factor authentication, session management, and staff roles.
- Public guest browsing, separate private-catalog admission and seller approval.
- Product drafts: content changes become visible only after publication. Prices and stock are saved separately, without overwriting newer changes.
- Product variants, photos, storage locations, units / kilograms / meters, prices in rubles, and free products.
- Shared product listings and comparison of identical offers after staff approval.
- Keyword, typo-tolerant and semantic search, price range and sorting, automatic loading, and links preserving search conditions. Semantic search matches meaning rather than just spelling.
- Personal saved products, seller pages, clear listing status and private publication previews.
- [Optional order demonstration](docs/runbooks/demo-orders-en.md): multi-seller cart, quantities, totals, price reconfirmation, duplicate-safe checkout, simulated payment, handover, receipt and cancellation. Disabled by default; no real money or shipments.
- Photos and the database are stored in separate persistent Docker volumes. Private photos are not served as public files.

## 1. Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) with Linux container support. Start Docker Desktop before running the commands below.
- [Git for Windows](https://git-scm.com/downloads/win): run these commands in **Git Bash**, not PowerShell. On Linux or macOS, use Bash.
- [Python 3](https://www.python.org/downloads/) to create the settings file once. The application, its dependencies, and the tests run inside Docker.

The first run downloads container images and the local search model. You need an internet connection and enough storage for Docker. Later runs reuse the saved data. To run the tests, use Docker Compose with `!reset` support (2.24.4 or later).

## 2. Get the project

Download the [current source ZIP with the refreshed interface](https://github.com/VibeSan7/Open_Marketplace/archive/refs/heads/main.zip) and extract it. Older versions remain available under [Releases](https://github.com/VibeSan7/Open_Marketplace/releases). Alternatively, clone the repository:

```bash
git clone https://github.com/VibeSan7/Open_Marketplace.git
```

```bash
cd Open_Marketplace
```

If you downloaded a ZIP file, open the extracted directory that contains `compose.yaml`. Run all commands from that directory. Access to the source does not grant access to someone else's installation: configure accounts and permissions in your own copy.

The original v0.2.0 archive predates both the English documentation and the refreshed interface. Download or clone the current `main` branch to get the updated interface and both documentation languages.

## 3. Create settings, first run only

For the ordered first run, use the [English installation runbook](docs/runbooks/initial-setup-en.md). It points back to this procedure and does not suggest replacing settings for an existing installation.

This command creates `.env` with new random keys and a database password. It does not print their values. **It will not overwrite an existing `.env`. Do not delete or regenerate that file for an existing database.**

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
```

Git and the Docker image exclude `.env`. Do not send it to a chat, GitHub, or an error log. If you get `FileExistsError`, the file already exists: keep it and continue instead of deleting the keys.

## 4. Start the application

Create or update the database tables:

```bash
docker compose run --rm --build web python manage.py migrate --noinput
```

Download and check the local semantic search model once:

```bash
docker compose run --rm web python manage.py prepare_catalog_search
```

Start the application and the email delivery worker in the background:

```bash
docker compose up --build -d
```

Check their status:

```bash
docker compose ps
```

Open:

- **Website and getting started:** <http://127.0.0.1:8000/>
- **Local email:** <http://127.0.0.1:8025/> for registration and invitation messages. Mailpit is an inbox for the local installation; it does not deliver these messages to an external email account.
- **Staff panel:** <http://127.0.0.1:8000/admin/>

A fresh installation does not create sample products or preset passwords. Use the [optional demo content](docs/runbooks/storefront-demo-en.md) to explore the storefront, or set up an administrator and seller for your own listings.

## 5. Set up the administrator and add a product

[Step-by-step guide for the owner, seller, and buyer](docs/runbooks/catalog-quickstart-en.md).

After startup, open the [built-in read-only guide](http://127.0.0.1:8000/setup/) in your copy. It explains roles, Mailpit, and explicit admission; the page itself creates nothing.

In brief:

1. Create the first administrator with the command below. `admin@example.test` is for local demonstration; its invitation arrives in Mailpit.
2. Open the invitation in Mailpit, set a password, and configure an authenticator app. It generates a one-time code for the second sign-in step. Store recovery codes securely, outside the repository.
3. Invite a staff member with the seller review role. Then register a separate personal seller account: staff accounts are not used for trading.
4. The seller verifies their email, enables two-factor authentication, and submits an application. The reviewer approves it after checking it.
5. The administrator opens `/catalog/manage/`, grants participation by email, and creates a category with attributes.
6. The seller opens "Мои карточки" (My listings), creates a listing, adds variants, real photos, a price and stock, then clicks "Опубликовать" (Publish). They separately choose "Открыть публичный показ" (Enable public visibility) for guest browsing. Disabling it restores private-only visibility.

```bash
docker compose run --rm web python manage.py bootstrap_security_admin --email admin@example.test
```

The first administrator cannot be created again with this command. Do not reset the database just to issue another invitation. If the invitation has expired or its email does not arrive, use the [local troubleshooting guide](docs/runbooks/local-development.md).

## Stop and restart

A normal shutdown **preserves the database, photos, and model**:

```bash
docker compose down
```

Start it again:

```bash
docker compose up -d
```

**Do not add `-v` to the shutdown command:** it removes the persistent volumes and their data. Before updating, back up `.env`, the database, and photos. See [backups and updates](docs/runbooks/catalog-quickstart-en.md#backups-and-updates).

## Automated checks

Tests use a separate temporary database and a separate Docker project. Do not point them at a working installation: email delivery tests clear the test Mailpit inbox.

The test image includes the Chromium browser:

```bash
docker compose -p open-marketplace-tests -f compose.yaml -f compose.test.yaml build test
```

```bash
docker compose -p open-marketplace-tests -f compose.yaml -f compose.test.yaml run --rm test python manage.py prepare_catalog_search
```

```bash
docker compose -p open-marketplace-tests -f compose.yaml -f compose.test.yaml run --rm test python manage.py test open_marketplace --noinput --verbosity 1
```

```bash
docker compose -p open-marketplace-tests -f compose.yaml -f compose.test.yaml run --rm test lint-imports --no-cache
```

```bash
docker compose -p open-marketplace-tests -f compose.yaml -f compose.test.yaml run --rm test python manage.py makemigrations --check --dry-run
```

The restore check uses a separate test database, not your working database:

```bash
COMPOSE_PROJECT_NAME=open-marketplace-tests bash ops/verify_restore.sh
```

The [release validation report (Russian)](docs/security/phase-2-local-validation.md) records the results, evidence, and limitations. Tests do not guarantee that every installation is error-free or replace the setup needed for an internet-facing server.

## Limitations

- By default, the website is only accessible on the computer running it. This release does not provide a public server, domain, HTTPS setup, external email delivery, or production backup operations. Django's local development server is not suitable for a public internet service.
- Guests see only explicitly public listings. Private listings still require admission; seller approval, catalog management and staff permissions are not granted by registration.
- Local HTTP uses non-secure cookies. Settings for secure HTTPS cookies exist, but do not enable them without HTTPS: the browser would be unable to sign in over plain HTTP.
- Approximate search uses a local multilingual model, but relevance can be wrong. It does not merge products automatically or bypass filters, stock checks, or access rules.
- A photo uploader's authenticity declaration is not an automated verification of the photo's origin.
- There is no real purchasing, real inventory reservation, delivery cost calculation, or digital file delivery. Demonstration orders use separate simulated balances; no bank cards or payment providers are connected.

## Documents and modules

- [Agreed catalog rules (Russian)](docs/superpowers/specs/2026-09-14-phase-2-catalog-design.md).
- [Implementation plan (Russian)](docs/superpowers/plans/2026-09-15-phase-2-catalog-implementation.md).
- [Completed first phase: identity and access](docs/security/phase-1-review.md).
- [Code-use and licence status](docs/code-use-status.md).

The domain modules `identity`, `access`, `seller_onboarding`, `catalog`, `audit`, and `outbox` interact through `public.py`. `web` and `staff_admin` provide the pages; `verification` checks test-database restoration and provides the separate synthetic-content import.
