# Fulfillment web operations

## Goal

Expose the existing local fulfillment lifecycle through authenticated browser screens without adding provider calls, package data, carrier evidence, payment, payout, refund, or deployment.

## Invariants

- A buyer sees only shipments belonging to their own orders.
- A seller sees only shipments assigned to their seller account.
- Shipment screens never expose the buyer delivery address to sellers.
- Seller-arranged shipments may be advanced by the assigned seller from `pending` to `ready` and from `ready` to `in_transit`.
- A buyer may confirm receipt only for a seller-arranged shipment in `in_transit`.
- CDEK state changes remain provider-driven and have no browser transition action.
- All mutations are POST-only, CSRF-protected, exact-field validated, and use the existing public commerce boundary.
- Foreign and unknown shipment IDs return the existing neutral unavailable response.

## Routes

- Authenticated GET `/commerce-fulfillment/` lists authorized shipment snapshots.
- Authenticated GET `/commerce-fulfillment/<uuid>/` shows one authorized shipment.
- Authenticated POST `/commerce-fulfillment/<uuid>/transition/` requests one explicit target state.

## Acceptance

1. Buyer and seller scope is enforced in service and web layers.
2. Seller can prepare and dispatch only their seller-arranged shipment.
3. Buyer can confirm receipt only for their seller-arranged shipment.
4. CDEK transitions are rejected without provider evidence.
5. Every accepted transition remains recorded by the existing fulfillment event ledger.
6. Browser journey, import boundaries, migration drift, full suite, and restore proof pass.
