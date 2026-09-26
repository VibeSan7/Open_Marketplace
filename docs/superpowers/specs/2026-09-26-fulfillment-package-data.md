# Fulfillment package data boundary

Add a seller-owned package manifest to each local fulfillment shipment. This is preparation data only: it does not calculate delivery, call CDEK, create a waybill, or prove that a parcel exists.

## Scope

- A shipment stores zero or more package rows in a JSON snapshot.
- Each package row contains positive integer `weight_grams`, `length_cm`, `width_cm`, and `height_cm`.
- Package rows are seller-editable only while the shipment is `pending`.
- The seller may replace the complete manifest atomically; partial row updates are not supported.
- An empty manifest is allowed for seller-arranged local delivery and for existing plans that have not collected package data yet.
- Buyer reads do not expose seller-editable package data through the fulfillment public view.
- Planning remains idempotent: package data does not alter the delivery-mode replay key.
- Package data is not an address, delivery fee, waybill, tracking event, carrier response, or proof of delivery.

## Invariants

- Unknown fields, non-list manifests, empty package rows, booleans, zero, negative, or non-integer values are rejected before writes.
- A foreign seller cannot read or update another seller's package data.
- A shipment that is no longer `pending` cannot be edited.
- Updating package data does not change order lines, buyer address snapshots, shipment state, or fulfillment events.
- The existing provider-disabled behavior remains unchanged.

## Acceptance

1. A new shipment has `packages=[]`.
2. A seller can set a valid complete manifest on their pending shipment and replay the same value safely.
3. Invalid manifests and foreign/state-conflicting updates are rejected without mutation.
4. Seller fulfillment reads include package data; buyer fulfillment reads do not.
5. Migration drift, focused tests, import contracts, full suite, compileall, and whitespace checks pass.

## Deferred

Package-to-line allocation, multi-package browser forms, CDEK payload construction, tariff calculation, shipment creation, pickup/refusal/returns, and verified carrier lifecycle events remain separate slices.
