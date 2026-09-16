# Plan: physical fulfillment planning

- [x] Define a provider-independent boundary for paid physical orders.
- [x] Add one immutable pending shipment snapshot per seller.
- [x] Persist an append-only planning event for each shipment.
- [x] Generate a deterministic reference no longer than CDEK's conservative 30-character limit.
- [x] Enforce explicit delivery mode for every seller and buyer ownership checks.
- [x] Make replay idempotent and reject conflicting input.
- [x] Add PostgreSQL-focused tests, migration drift checks, import boundaries, and documentation updates.

## Intentionally deferred

This slice does not calculate delivery prices, persist addresses, call CDEK, create a waybill, contact a seller, transition courier states, confirm receipt, execute returns, or expose a browser checkout route. Those actions require separate provider credentials, operational policy, and user-facing boundary design.
