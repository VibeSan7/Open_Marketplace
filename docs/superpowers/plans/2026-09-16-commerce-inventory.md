# Commerce Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and exercise the real inventory prerequisite for the approved commerce integration without exposing real checkout or mutating the running demo.

**Architecture:** Catalog owns physical stock, persisted reservation snapshots and storage allocations. A unique reservation UUID serializes repeated requests; ordered PostgreSQL row locks protect products and stock. The later commerce coordinator consumes only catalog public functions; the inventory slice neither calls providers nor decides financial outcomes.

**Tech Stack:** Python 3.13.15, Django 5.2.17, PostgreSQL, existing Docker test image.

**Spec:** `docs/superpowers/specs/2026-09-16-commerce-inventory.md`

## Global Constraints

- No real payments, shipments, credentials, production migrations, deployments or publication.
- No new dependencies or tools. English source documentation, Russian UI/errors.
- Existing demo models and flags remain separate; no simulated evidence of provider integration.
- Test first, run real PostgreSQL concurrency tests, then full workspace verification.

## Task 1: Transactional inventory reservation

**Files:**
- Create: `open_marketplace/catalog/tests/test_reservations.py`
- Create: `open_marketplace/catalog/reservations.py`
- Modify: `open_marketplace/catalog/models.py`, `public.py`, `application.py`, `queries.py`, `demo.py`
- Generate: `open_marketplace/catalog/migrations/0005_stock_reservations.py`
- Modify: `pyproject.toml` catalog protected-module list only.

**Interfaces:**
- `reserve_inventory(*, intent_id, lines, context)` returns `{id, buyer_id, state, lines}`. Each input line has exactly `variant_id`, `quantity`, `expected_unit_price`. UUIDs are canonical; prices/quantities use catalog decimal validation. Snapshot numeric values are decimal strings, never floats.
- `commit_inventory(*, reservation_id)` and `release_inventory(*, reservation_id)` are internal settlement entry points and return the same snapshot shape. They do not authenticate HTTP requests or assert a payment happened; they are not wired to any route.
- `Stock.available_quantity` is a nullable Decimal derived from on-hand less reserved stock.

- [ ] Write real behavior tests. Core assertion:

```python
held = self.catalog.reserve_inventory(
    intent_id=uuid4(),
    lines=[{"variant_id": str(variant_id), "quantity": "1", "expected_unit_price": "120"}],
    context=self.buyer_context,
)
stock.refresh_from_db()
self.assertEqual(stock.quantity, Decimal("2"))
self.assertEqual(stock.reserved_quantity, Decimal("1"))
self.assertEqual(stock.available_quantity, Decimal("1"))
self.assertEqual(held["lines"][0]["unit_price"], "120.00")
```

Also assert rejection of invalid units/amounts, invalid/duplicate IDs, self/private/withdrawn purchases, insufficient stock, changed retry contents, below-reserve seller edits, and opposite terminal transitions. Assert whole-transaction rollback and original-location restoration of availability.

- [ ] Run the test module in the existing isolated test network with a unique test DB name. Expect a deliberate `assertTrue(callable(...))` failure because the public operation is absent, not import/setup failure.
- [ ] Add `reserved_quantity` and database constraints; add reservation (UUID PK, buyer ID, normalized request, immutable snapshot, constrained state, creation time) and allocation (reservation/stock, positive quantity, unique pair) models. Implement atomic get-or-create, request identity comparison, ordered product/stock locking and updates. Reuse catalog authorization and visibility checks; check prices under the product lock. Return copied snapshots.

```python
with transaction.atomic():
    reservation, created = InventoryReservation.objects.get_or_create(
        id=intent_id,
        defaults={"buyer_id": account.id, "request": request, "created_at": context.now},
    )
    reservation = InventoryReservation.objects.select_for_update().get(pk=reservation.id)
```

On an existing ID, compare buyer and complete normalized request before returning its stored snapshot. For a new ID, any invalid line raises and rolls back both the new row and all preceding allocations. For settlement, lock the reservation, its product rows and stock rows before changing balances and the terminal state in the same transaction.

- [ ] Use `available_quantity` for availability and quantity aggregation; reject stock edits below the held quantity. Generate migration with Django and inspect it; run focused tests until green.

## Task 2: Concurrency and regression evidence

**Files:**
- Create: `open_marketplace/catalog/tests/test_reservation_concurrency.py`
- Create: `artifacts/commerce-planning/inventory-verification.md` (local evidence, not release claims)

- [ ] Use `TransactionTestCase`, per-thread Django connections and a start barrier. Run two authenticated buyers requesting the final unit and assert exactly one success, one domain rejection, one reservation, on-hand one, held one. Run identical UUID requests and assert one reservation/allocation. Run commit against release and assert one terminal result with balances matching that result. Reverse two-line baskets and assert no deadlock/oversell.
- [ ] Execute focused concurrency tests against PostgreSQL; each worker closes its own connection in a `finally` block. Unexpected database/deadlock errors fail tests, never count as acceptable stock rejection.
- [ ] Execute full project validation with a unique disposable test DB:

```sh
python manage.py check
python manage.py makemigrations --check --dry-run
lint-imports --no-cache
python manage.py test open_marketplace --noinput --verbosity 1
```

- [ ] Record actual command exits and test totals from saved logs. Review `git diff --check` and full changed files. Keep the implementation local until the full commerce feature is ready; report this inventory slice as a prerequisite, not completed payment/delivery/file fulfillment.
