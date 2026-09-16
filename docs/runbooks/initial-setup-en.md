# Initial installation

This runbook applies to a new local Open Marketplace copy. It does not connect to someone else's installation, change the current demonstration, or replace settings for an existing database.

After startup, open the [built-in read-only guide](http://127.0.0.1:8000/setup/) in your browser. It presents the same secure order and explains the boundaries of public browsing and private data.

## 1. Get the source

Download the current branch as a ZIP or clone the repository. Change to the directory containing `compose.yaml`; run all commands below there. Public source download does not grant access to someone else's accounts, data, or server.

## 2. Create settings once

Use the Python generator in the [README settings section](../../README.en.md#3-create-settings-first-run-only). It creates a new `.env`, prints no secrets, and refuses to overwrite an existing file. Do not delete `.env` for an existing database, and never send its contents to chat or logs.

## 3. Start the application

```bash
docker compose run --rm --build web python manage.py migrate --noinput
```

```bash
docker compose run --rm web python manage.py prepare_catalog_search
```

```bash
docker compose up --build -d
```

Open the site at <http://127.0.0.1:8000/> and local email at [Mailpit](http://127.0.0.1:8025/). `localhost` and `127.0.0.1` mean only the computer running Docker; this does not publish the site on the internet.

## 4. Complete the protected setup

After migrations, run the existing one-time command:

```bash
docker compose run --rm web python manage.py bootstrap_security_admin --email admin@example.test
```

Open the invitation in Mailpit, set a password, configure an authenticator app, and save recovery codes outside the repository. Do not bypass the invitation, two-factor protection, or reauthentication. Use separate personal and staff accounts for the remaining steps.

## 5. Demonstration boundaries

Guests see only explicitly public published products. Saved items and demo orders for public products require an active personal account with verified email; private products additionally require admission. Selling and catalog management are not granted by registration: the administrator admits sellers separately. An [optional synthetic storefront](storefront-demo-en.md) is available.

This version has no real orders, payments, reservations, delivery, or digital-file delivery. An optional [demo order journey](demo-orders-en.md) exercises simulated payment, hand-over and cancellation without real money. Local running is a demonstration on your computer, not a ready public service.
