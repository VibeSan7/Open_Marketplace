# Payment ledger and reconciliation boundary

This slice stores a provider payment intent and applies only an already verified, normalized T-Bank Safe Deal notification. It is not a live checkout integration: it makes no network request, does not create a hosted payment URL, and does not perform payouts or refunds.

## Invariants

- A commerce order has at most one local T-Bank payment intent with a stable provider order number and exact kopeck amount derived from the immutable order total.
- Preparing an intent is buyer-scoped, idempotent, and unavailable for cancelled/paid orders. Credentials and provider responses are not stored.
- Only the T-Bank adapter's normalized notification shape is accepted by the ledger. Raw callback verification remains in `payments.tbank`; the ledger never trusts a browser redirect or a caller-provided success flag.
- Payment events are deduplicated by a deterministic digest of normalized identity/status/amount fields. Repeated callbacks have no second inventory effect.
- `AUTHORIZED` keeps the catalog reservation held. A valid `CONFIRMED` notification commits inventory once and moves the order to `paid`. A valid rejected/reversed notification while awaiting payment releases inventory once and cancels the order.
- A stale notification cannot downgrade a newer state. A refund after commitment is recorded as a provider state but does not release or resurrect inventory; a separate refund/restock workflow remains required.
- No seller payout, deal closure, fiscal receipt, shipment, or digital entitlement is implied by `paid`.

## Acceptance

1. Preparing a payment intent persists exact RUB kopecks and retries return the same reference without provider calls.
2. Identity, amount, state, and buyer mismatches are rejected without mutations.
3. Verified authorized/confirmed/reversed/rejected notifications are applied monotonically and idempotently.
4. Confirmed payment commits reserved stock once; rejected/reversed pre-payment releases it once.
5. Duplicate and stale notifications cannot create duplicate events or reverse inventory.
6. Focused tests, migration drift, import contracts, full suite, and restore verification pass.

## Deferred

The provider-specific legal-entity/sole-trader payout contract, live terminal activation, callback HTTP route, reconciliation scheduler, refund/restock after fulfillment, and seller payout ledger remain deferred until the applicable T-Bank contract is obtained.
