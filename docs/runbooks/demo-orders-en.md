# Demo orders

Demo orders are simulated only: no real money is charged. The flow is for demonstrating selection of a published physical offer, simulated payment, hand-over, and completion.

## Enable

The feature is disabled by default. In your local Docker installation’s `.env`, change `DEMO_ORDERS_ENABLED=false` to `DEMO_ORDERS_ENABLED=true`. Recreate only the web service; do not remove data volumes:

```sh
docker compose build web
```

```sh
docker compose run --rm --no-deps web python manage.py migrate --noinput
```

```sh
docker compose up -d --no-deps web
```

Any other value, including an unset variable, makes the HTTP routes return 404. The flow has no payment API, SMTP, delivery address, or real dispatch.

## Flow

1. Sign in with an ordinary, verified, admitted account.
2. Open /demo-orders/ or the new-order link from the catalogue.
3. Enter a quantity and submit the form. The server uses the client UUID intent_id, calculates the RUB total, and reserves a separate simulated inventory balance.
4. Choose simulated payment success or decline. Decline keeps the order pending and allows a later success.
5. The active owner of the offer can simulate hand-over; the buyer can complete. The buyer or active owner can cancel before hand-over.

The order stores immutable title, variant, seller, unit, price, quantity, and total snapshots. Simulated inventory is initialized once from known positive catalogue stock; later catalogue edits do not replenish it. This is not real reservation or oversell protection for commerce.

## Verification

Integration tests are in `open_marketplace.catalog.tests.test_demo_orders`, `test_demo_order_concurrency`, and `open_marketplace.web.tests.test_demo_journey`; the full browser journey is in `catalog.tests.test_browser`. Run them against an isolated test database. PostgreSQL is required for concurrency checks; TestCase does not prove real locks, so concurrency tests use TransactionTestCase and separate connections.
