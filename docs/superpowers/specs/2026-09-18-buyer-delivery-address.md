# Buyer delivery address boundary

## Goal

Collect one buyer-owned delivery address before local checkout and persist an immutable copy on the durable order. This is a local commerce boundary only: it does not quote delivery, call CDEK, or create a shipment.

## Invariants

- An address belongs to exactly one authenticated ordinary buyer.
- Address reads and checkout selection are buyer-scoped; foreign or unknown IDs are neutral failures.
- Checkout requires an address ID and stores the server-side address snapshot on the order.
- Replaying a cart intent with a different address is rejected; replaying the same intent with the same address returns the same order.
- The order snapshot is not changed if the saved address is later changed or removed. This slice does not expose address mutation/deletion.
- Address fields are validated at the application boundary, and raw address values are not written to logs.
- No delivery quote, package dimensions, waybill, provider request, payment, payout, or shipment state is created.

## Address fields

The first slice supports Russian physical delivery with: optional label, recipient name, phone, postal code, region, city, street, building, optional apartment, and optional delivery comment. Country is stored as `RU` and is not user-selectable in this slice.

## Acceptance

1. A buyer can create and list their own saved addresses.
2. A foreign address cannot be selected or exposed.
3. Checkout without an address is rejected before order creation.
4. Checkout persists an immutable address snapshot and reserves inventory once.
5. Same intent plus same address is idempotent; same intent plus another address is rejected.
6. Order history/detail displays the snapshot, not a live address lookup.
7. Django checks, migration drift, import contracts, focused tests, full suite, and restore proof pass.
