# Fulfillment state filter

Add a validated read-only state filter to the authenticated fulfillment list.

## Scope

- Accept one optional `state` query parameter on `GET /commerce-fulfillment/`.
- Support the existing shipment states: `pending`, `ready`, `in_transit`, `delivered`, and `cancelled`.
- Filter only the already-authorized snapshots returned by `commerce.public.list_fulfillment_shipments`.
- Render links for all states and a link back to the unfiltered list.
- Keep shipment detail, lifecycle mutations, package redaction and provider boundaries unchanged.

## Invariants

- Missing, duplicate, unknown or unsupported query parameters are rejected with the existing neutral 400 error.
- Filtering never broadens the authorized result set.
- State labels come from the existing web presentation mapping.
- No database query, migration, provider call or new public commerce API is introduced.

## Acceptance

1. An authorized seller sees a pending shipment with `?state=pending`.
2. The same seller does not see it with `?state=ready`.
3. The active state and a link to all shipments are rendered.
4. Invalid, duplicate and unknown query parameters are rejected.
5. Existing buyer/seller authorization, package redaction, lifecycle, import-boundary, migration and full tests remain green.
