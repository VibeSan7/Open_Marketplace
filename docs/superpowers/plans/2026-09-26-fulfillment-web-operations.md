# Fulfillment web operations implementation plan

**Goal:** Add buyer/seller browser screens over the existing local fulfillment service boundary.

**Constraints:** No provider calls, package data, waybills, live delivery, payment, payout, refund, or deployment. Keep web imports on `commerce.public`. Use TDD and disposable Docker services.

## Task 1: Public shipment queries

- [x] Add failing tests for buyer/seller shipment visibility and foreign/unknown rejection.
- [x] Add `list_fulfillment_shipments` and `get_fulfillment_shipment` to the commerce public boundary.
- [x] Preserve shipment snapshots without address or provider claims.

## Task 2: Browser routes and transitions

- [x] Add failing request tests for list/detail, CSRF, exact POST fields, seller transitions, buyer receipt, and CDEK rejection.
- [x] Add authenticated list/detail/transition routes and templates.
- [x] Add shipment links and a limited navigation link without exposing seller-private buyer data.

## Task 3: Verification

- [x] Run focused RED/GREEN cycles.
- [x] Run Django checks, migration drift, import contracts, compile and whitespace checks.
- [x] Run the full Docker suite and restore proof.
- [x] Review diff and commit locally. Do not push or deploy without explicit approval.
