# Fulfillment event timeline

Expose a sanitized local state timeline for each authorized fulfillment shipment and render it on the shipment-detail page.

## Scope

- Include ordered fulfillment events in the existing commerce fulfillment snapshot.
- Expose only sequence, state, action, and timestamp; never expose actor identifiers.
- Keep buyer package redaction unchanged.
- Render readable event labels for authorized buyers and sellers.

## Invariants

- Event order is the persisted sequence order.
- The initial `planned` event exists for every created shipment.
- State transitions append one event and never rewrite prior events.
- The timeline is read-only and does not call a provider or create external evidence.
- Web code continues to use the public commerce boundary only.

## Acceptance

1. A new shipment exposes one sanitized `planned` event.
2. A transition appends an event with the new state and action in the correct sequence.
3. Buyer and authorized seller can see the timeline; unauthorized users cannot read the shipment.
4. Actor IDs, package manifests and delivery addresses are absent from event data.
5. Existing focused, full, import-boundary and migration checks remain green.
