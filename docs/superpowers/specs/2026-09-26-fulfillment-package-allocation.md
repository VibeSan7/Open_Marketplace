# Fulfillment package-to-line allocation boundary

Extend the seller-owned local package manifest so each package identifies the shipment lines and quantities it contains. This remains local preparation data: it does not calculate delivery, call CDEK, create a waybill, or prove carrier movement.

## Scope

- Each package contains one or more `{line_index, quantity}` allocations.
- `line_index` addresses the immutable zero-based line position inside that seller shipment snapshot.
- A line may be split across packages, but its total allocated quantity must equal the shipment line quantity exactly.
- Every shipment line must be allocated exactly once in total when a non-empty package manifest is saved.
- Empty `packages=[]` remains allowed to clear preparation data.
- Seller can edit dimensions and allocations only while the shipment is `pending`.
- Buyer views remain redacted; provider behavior remains unchanged.

## Invariants

- Unknown package fields, unknown line indexes, duplicate allocations within one package, non-positive quantities, invalid unit precision, and incomplete totals are rejected before writes.
- Allocation quantities use the shipment line's unit precision: whole numbers for `pc`, up to three decimal places for `kg` and `m`.
- Package dimensions remain positive integers in grams and centimetres.
- Allocation validation uses the immutable shipment snapshot, not mutable catalog data.
- Updating package data does not change order lines, shipment state, or fulfillment events.

## Acceptance

1. A seller can save multiple packages with valid line allocations.
2. A line can be split across packages and the exact total is accepted.
3. Missing, excessive, foreign, duplicate, malformed, and over-allocated quantities are rejected without mutation.
4. Empty manifests clear all package preparation data.
5. Seller web forms show only lines in that shipment; buyer and foreign actors cannot update them.
6. Focused tests, import contracts, migration checks, full suite, compileall, and whitespace checks pass.

## Deferred

Delivery quotes, package-to-provider payload mapping, CDEK shipment creation, pickup/refusal/returns, carrier lifecycle events, refunds, disputes, and payouts remain separate slices.
