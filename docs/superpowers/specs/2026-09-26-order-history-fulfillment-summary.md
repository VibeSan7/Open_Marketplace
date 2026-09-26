# Order history fulfillment summary

Show the buyer's authorized local fulfillment status and shipment links in the existing order-history page. This is a read-only presentation layer over the existing commerce boundaries.

## Scope

- Load buyer-authorized orders and fulfillment shipments through `commerce.public`.
- Group shipments by immutable `order_id`.
- Add state/mode labels and authorized shipment-detail URLs to each order-history row.
- Show a neutral not-planned message when an order has no fulfillment shipment.
- Keep buyer package manifests redacted and do not change order or shipment state.

## Invariants

- Web code imports no protected commerce models.
- Existing order and shipment authorization remains authoritative.
- No migration, provider request, payment, quote, waybill, carrier evidence, or write operation is introduced.
- The order-detail summary remains unchanged and uses the same presentation shape.

## Acceptance

1. An order-history row with a local shipment shows its state and links to the authorized shipment detail.
2. An order-history row without a shipment shows the neutral not-planned message.
3. Existing order-history, order-detail, fulfillment, import-boundary, migration, and full tests remain green.
