# Order fulfillment summary boundary

Expose authorized local fulfillment summaries on the buyer's order-detail screen. This is a presentation-only slice over the existing public commerce boundaries: it does not change order or shipment state, call a provider, calculate delivery, or expose seller package manifests.

## Scope

- The order-detail view loads authorized fulfillment shipments through `commerce.public.list_fulfillment_shipments`.
- It keeps only shipments belonging to the displayed order.
- The buyer sees shipment id, delivery mode, local state, and a link to the authorized shipment detail page.
- Unpaid orders with no fulfillment plan show a neutral local message.
- Shipment detail continues to hide seller package data from buyers.
- Seller and provider behavior remain unchanged.

## Invariants

- Web code imports only `commerce.public`, never protected commerce models.
- Order ownership and shipment authorization remain enforced by the existing commerce boundary.
- No new write operation, migration, provider call, payment, delivery quote, waybill, or carrier evidence is introduced.
- A failed or unauthorized read returns the existing neutral order error response.

## Acceptance

1. A buyer viewing an order with a local shipment sees its state and a link to the shipment detail.
2. A buyer viewing an order without a fulfillment plan sees the neutral not-planned message.
3. The linked buyer shipment detail remains package-redacted.
4. Existing order, fulfillment, import-boundary, migration, focused, and full tests remain green.
