# Physical fulfillment planning boundary

This slice creates durable shipment planning records only after a commerce order is already `paid`. It does not call CDEK, calculate delivery prices, create a waybill, contact a seller, or expose a buyer-facing checkout route.

## Invariants

- One paid multi-seller order creates at most one shipment plan per seller account.
- Each shipment stores an immutable copy of the order lines for that seller, the seller identifiers, an explicit delivery mode (`cdek` or `seller`), and a deterministic provider-safe client reference of at most 30 characters.
- The requested delivery-mode map must cover exactly the sellers in the paid order; no default delivery method is invented.
- Repeating the same plan request returns the same records without duplicate shipments or events. A changed mode or line snapshot is rejected.
- Awaiting-payment, cancelled, missing, or foreign orders are not exposed through this internal boundary.
- Shipment state starts at `pending`; no pending state means that a parcel exists or that delivery has begun.

## Acceptance

1. A paid multi-seller order produces one immutable shipment plan per seller with the requested mode.
2. Missing, extra, or unsupported delivery modes are rejected before writes.
3. Repeated identical planning is idempotent; conflicting replay is rejected.
4. An unpaid order cannot create a shipment plan.
5. The plan records no address, fee, waybill, delivery confirmation, or provider response.
6. Focused tests, migration drift, import contracts, full suite, and restore proof pass.

## Deferred

CDEK requests and verified provider lifecycle events, packaging/address collection, courier pickup/refusal/returns, delivery fees, and digital asset/entitlement delivery remain separate slices. The local seller-arranged state workflow and buyer receipt confirmation are implemented separately in the fulfillment lifecycle boundary.
