# Commerce order contract

This slice adds the durable marketplace order boundary on top of the provider-independent catalog reservation. It is local code only: no provider request, seller payout, shipment creation, digital entitlement, deployment, or public checkout route.

## Invariants

- One canonical buyer intent creates at most one `CommerceOrder` and one catalog reservation.
- An order stores an immutable copy of the catalog reservation lines and the calculated RUB total. Later catalog price, publication, or seller-display changes do not rewrite it.
- Creating an order is atomic with reserving every physical line. Any failure leaves no order, reservation, or held stock.
- Only the buyer who owns the reservation can replay the intent. A different intent body or account is rejected without mutation.
- A new order starts `awaiting_payment`; that state is not a payment success and grants no seller payout or file access.
- Cancelling an `awaiting_payment` order releases its reservation exactly once. A paid order cannot be cancelled through this local command because a provider-authoritative refund/reconciliation flow is required.
- Order reads return a copied snapshot and never expose provider secrets or raw callback payloads.
- This service imports catalog through `catalog.public` and remains outside catalog internals.

## Acceptance

1. A mixed-seller physical basket produces one order with all lines, exact decimal total, and one held reservation.
2. Identical retries return the same order and do not change stock or create a second order.
3. Changed intent contents, a different buyer, withdrawn/private offers, stale prices, and insufficient stock fail without partial state.
4. A cancelled awaiting-payment order releases all original allocations once; repeated cancellation is a stable read.
5. Paid/cancelled terminal transitions are guarded and do not invoke a provider or pretend that a payout occurred.
6. Concurrent same-intent calls converge to one order; concurrent different buyers cannot reuse the intent.
7. Django checks, migration drift, import contracts, focused tests, full tests, and restore verification pass.

## Explicitly deferred

- Provider-specific payment intent creation, callback endpoint, reconciliation worker, Safe Deal contract for legal-entity payouts, refunds after fulfillment, shipment persistence, seller-arranged delivery, digital upload/versioning, and protected downloads.
