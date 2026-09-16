# Commerce order implementation plan

> Execute in `feature/commerce-foundation`; keep the v0.4.0 demo runtime untouched.

**Goal:** persist a real marketplace order boundary on top of catalog reservations without making provider or delivery claims.

**Architecture:** `open_marketplace.commerce` owns `CommerceOrder` and `CommerceOrderEvent`; its public service calls `catalog.public.reserve_inventory`, `commit_inventory`, and `release_inventory`. No web route imports commerce internals, and no provider client is called by this slice.

## Steps

- [x] Add `CommerceConfig`, app registration, models, and migration. Use UUID identifiers, canonical buyer intent, immutable JSON line snapshot, Decimal RUB total, explicit state choices, and database uniqueness/check constraints.
- [x] Add red tests for mixed-seller order creation, exact total, retry identity, rollback, buyer isolation, cancellation, terminal state guards, and absence of provider calls.
- [x] Implement `create_order`, `get_order`, and `cancel_order` with one transaction around catalog reservation and order persistence. Lock an existing order before replay; preserve the reservation snapshot.
- [x] Add focused concurrency coverage with PostgreSQL and verify same-intent convergence.
- [x] Add public exports and import-boundary protection without exposing model internals to other domains.
- [x] Run `check`, migration drift, import contracts, focused tests, full project suite, and restore verification. Record actual outputs before reporting.

## Constraints

- No real API calls, credentials, payment charges, payouts, shipments, or deployment in this local phase. Publication may document this explicitly incomplete foundation.
- No simulated payment success. `awaiting_payment` must remain visibly non-paid if a UI is added later.
- No guessed expiry, commission, payout, refund, delivery, or digital-file limits.
