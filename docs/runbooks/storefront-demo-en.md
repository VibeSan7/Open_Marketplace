# Storefront demonstration v0.4

Optional synthetic content: 24 illustrated products, 48 variants, 6 categories and 3 fictional stores. Images have individual [credits and licenses](../demo-image-credits.md); names, prices and configurations are educational. There are no fabricated reviews, sales, discounts or ratings, real payments or shipments.

Complete the ordinary [README installation](../../README.md), including migrations and search preparation. Then run:

```bash
docker compose run --rm -e DEMO_CONTENT_ENABLED=true web python manage.py seed_demo_storefront --confirm-demo
```

Open <http://127.0.0.1:8000/> without signing in. Import is deliberately not part of ordinary startup. The flag applies to this command only. The operation creates its own new records, does not open old private listings or replace accounts, and is idempotent. Conflicting identifiers cause a refusal rather than an overwrite. Fictional seller accounts have unusable passwords; they are sample storefronts, not preset logins.

## Cart and simulated orders

Set `DEMO_ORDERS_ENABLED=true` in your existing `.env`, preserving all other keys, then recreate application services:

```bash
docker compose up -d --no-deps --force-recreate web worker
```

Register your own personal account and verify email through local Mailpit at <http://127.0.0.1:8025/>. No private-catalog admission is required for public products. Choose a variant, add it to the cart, adjust quantities, and check out. Changed prices require confirmation by updating the line. The server rechecks eligibility, price and availability; checkout is all-or-nothing and duplicate-safe.

Payment approval/decline and cancellation are simulations. Full seller handover uses your own approved seller accounts, not the fictional stores that have no usable logins. See [demo-order behavior](demo-orders-en.md).

## Upgrade and rollback

Back up `.env`, the database and photo volume using the [backup guide](catalog-quickstart-en.md#backups-and-updates). Apply normal migrations. Existing products remain `public_listing=false`; publication and guest visibility are separate actions.

Rollback requires the previous code/image **and** its matching saved database, photos and original `.env`. Do not improvise reverse migrations or use `docker compose down -v`. Restoring an earlier database loses subsequent activity; save the current state first.

`127.0.0.1` refers to the Docker computer, not a public website or a phone address.
