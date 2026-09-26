# Fulfillment list line summary

Show the authorized shipment lines in the local fulfillment list so buyers and assigned sellers can identify each shipment without opening every detail page.

## Scope

- Render each authorized shipment line's title, variant label and quantity in the existing fulfillment list.
- Use the immutable `lines` data already present in the authorized fulfillment snapshot.
- Keep seller package manifests, delivery addresses and provider data unchanged.
- Keep the detail page, lifecycle actions and authorization behavior unchanged.

## Invariants

- The list renders only lines returned by `commerce.public.list_fulfillment_shipments` for the current actor.
- Buyer and seller see only their already-authorized shipment lines.
- No new domain or public API field is introduced.
- User-provided product text remains template-escaped.

## Acceptance

1. Buyer sees the shipment line title, variant label and quantity in the fulfillment list.
2. Assigned seller sees the same authorized line summary.
3. Foreign sellers still cannot access the shipment detail or list data.
4. Existing package redaction, lifecycle, order, import-boundary, migration and full tests remain green.
