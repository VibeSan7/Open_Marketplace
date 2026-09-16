# Plan: fulfillment lifecycle

- [x] Define allowed local transitions for a planned physical shipment.
- [x] Authorize seller preparation and seller-arranged dispatch by seller account.
- [x] Authorize delivery receipt only for the buyer.
- [x] Keep CDEK `in_transit` and `delivered` provider-driven.
- [x] Make repeated current-state requests idempotent.
- [x] Persist a monotonic per-shipment event sequence and backfill existing events safely.
- [x] Verify focused PostgreSQL tests, migration drift, import boundaries, and the full GitHub suite.

## Intentionally deferred

This service boundary has no address form, delivery quote, package dimensions, CDEK request, waybill, courier proof, browser route, payout, refund, or digital-file delivery. The local `delivered` state for seller-arranged delivery is an application receipt confirmation, not carrier evidence.
