# Fulfillment state summary

Show authorized shipment counts by lifecycle state above the fulfillment list.

## Scope

- Count the full authorized shipment snapshot before applying the optional state filter.
- Render total count and one count for each existing fulfillment state.
- Keep the current state filter, shipment lines, seller package count and detail links unchanged.
- Use the existing public fulfillment list; do not add provider or persistence behavior.

## Invariants

- Counts include only shipments already authorized for the current buyer or seller.
- Counts are independent of the active list filter.
- State labels use the existing presentation mapping.
- No package manifest, delivery address, actor identifier or provider evidence is introduced.

## Acceptance

1. An authorized actor sees the total and pending count for the current scope.
2. The counts remain the same when a state filter is active.
3. A buyer cannot see shipments or counts outside their own orders.
4. Existing filtering, package redaction, lifecycle, import-boundary, migration and full tests remain green.
