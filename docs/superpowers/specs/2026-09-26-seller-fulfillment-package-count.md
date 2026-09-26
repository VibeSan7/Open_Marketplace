# Seller fulfillment package count

Show a seller-only package count in the authorized fulfillment list. This is a read-only presentation hint; it does not expose package contents or change fulfillment state.

## Scope

- Seller shipment-list rows show the number of saved package records.
- Buyer shipment-list rows do not show package count because buyer snapshots omit `packages`.
- The existing detail page remains the source for package contents and allocation.
- No domain, migration, provider, or write behavior changes.

## Invariants

- The count is derived only from the authorized snapshot's `packages` key.
- Missing `packages` means the caller is not allowed to see seller-owned package data; it must not be rendered as zero.
- Seller and buyer shipment authorization remains unchanged.

## Acceptance

1. Seller sees `Упаковок: 0` for a pending shipment with no saved manifest.
2. Seller sees the updated count after saving multiple packages.
3. Buyer does not see the package count or package contents.
4. Existing fulfillment, order, import-boundary, migration, and full tests remain green.
