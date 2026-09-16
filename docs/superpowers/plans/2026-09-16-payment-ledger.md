# Payment ledger implementation plan

> Execute in `feature/commerce-foundation`; keep the v0.4.0 demo runtime untouched.

**Goal:** persist a provider payment boundary without pretending that the public T-Bank documents complete mixed-recipient marketplace payouts.

## Steps

- [x] Add provider-independent `PaymentIntent` and append-only normalized `PaymentEvent` records with exact RUB kopecks and database uniqueness/check constraints.
- [x] Add buyer-scoped, idempotent payment preparation and one-time binding of T-Bank payment/deal identifiers without network calls.
- [x] Apply only the low-level adapter's normalized notification shape; deduplicate by digest and reject identity/amount/status mismatches.
- [x] Commit reserved inventory on verified `CONFIRMED`; release it once on pre-payment rejection/reversal; keep stale notifications from downgrading state.
- [x] Keep full and partial refunds visible as provider states without inventing restock, seller payouts, fiscalization, or deal closure.
- [x] Run migration drift, import contracts, focused PostgreSQL tests, full project tests, and restore verification after the final code change.

## Constraints

No provider request, credential, hosted checkout URL, callback HTTP route, real payment, payout, refund, shipment, or deployment belongs to this local slice. Publication must preserve these limits; the next integration phase must obtain the exact T-Bank contract and implement reconciliation before enabling any external side effect.
