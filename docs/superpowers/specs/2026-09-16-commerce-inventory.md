# Commerce inventory foundation

Status: implementation specification for the provider-independent inventory slice of the owner's approved real-commerce direction. This is not a payment integration, delivery integration, or activation approval.

## Approval and boundaries

The owner confirmed T-Bank Multi-calculation Service, CDEK plus seller-arranged delivery with buyer confirmation, and private checked/versioned digital fulfillment. Contracts, credentials, money movement, real shipments, production migrations, deployment, and publication are not authorized by that confirmation. The existing demonstration remains isolated.

## Inventory contract

- `Stock.quantity` remains the on-hand quantity. Add `reserved_quantity`, initially zero. Available-to-buy quantity is `quantity - reserved_quantity`; an unknown quantity remains unknown.
- Reserve all requested physical seller variants atomically; no partial basket holds. Lock the reservation, products, variants and stocks in a stable order. Never reserve a common aggregate card, a digital draft, the buyer's own product, or an offer not currently visible to that buyer.
- A caller-supplied UUID identifies one checkout intent globally. The authenticated buyer and the complete normalized request bind it permanently. Identical retries return the original snapshot, even after subsequent listing/price changes; different buyer or contents cannot reuse it.
- Each line contains `variant_id`, positive `quantity`, and `expected_unit_price`. The expected price is a stale-check only, never a source of the charged price. Use the catalog's exact decimal validation and physical units. Store an immutable server-side line snapshot containing product/variant/seller identities, published versions, title, label, unit, quantity and price.
- Reserve from the seller's storage locations in UUID order and persist each allocation. Holds increment `reserved_quantity` without decrementing on-hand stock. Stock versions increase so an old seller edit cannot overwrite a hold.
- Internal settlement commands have three states: `held`, `committed`, `released`. Committing a held reservation decrements both on-hand and reserved quantities exactly once. Releasing a held reservation decrements reserved quantity only, exactly once. Committed cannot be released; released cannot be committed. A refund/restock after fulfillment is a different operation, not an inventory-release shortcut.
- These internal commands are not exposed as HTTP endpoints. Only a transactionally coordinated, authenticated commerce service may invoke them after authoritative payment/cancellation reconciliation. A user return URL, simulator button, local clock, network timeout or an unverified provider callback cannot settle inventory.
- No automatic expiry policy is invented in this slice. Holds remain held until the coordinator can prove payment or cancellation. Do not expose real checkout until provider reconciliation, expiry/cancellation, abuse controls and recovery exist.
- Seller stock edits cannot reduce on-hand stock below the reserved quantity. Unknown stock cannot have a nonzero reserve. Database checks enforce these invariants even if application validation is bypassed.
- Buyer availability and demo initial availability exclude real reservations. Demo orders still use their separate `DemoInventory` and cannot commit/release a real reservation.

## Acceptance

1. Reserving physical stock changes real available-to-buy quantity and freezes the authoritative snapshot.
2. Identical retries have one effect; changed contents or identity are rejected without mutations.
3. Mixed sellers/locations reserve atomically, with rollback if any line is invalid or unavailable.
4. Commit/release are idempotent, mutually exclusive, preserve nonnegative available stock and never resurrect fulfilled inventory.
5. Existing catalog privacy, session security, seller approval, fixed unit precision and stale stock-version protection hold.
6. PostgreSQL concurrent requests for the last unit produce one winner; identical intents converge; reversed multi-product requests do not deadlock; commit/release races produce exactly one terminal effect.
7. Full existing project tests, Django checks, migration drift and import-boundary contracts pass. The demonstration runtime and its database remain untouched.

## Evidence sources

- Django 5.2 transactions: https://docs.djangoproject.com/en/5.2/topics/db/transactions/
- Django row locking and concurrency tests: https://docs.djangoproject.com/en/5.2/ref/models/querysets/#select-for-update
- Existing `catalog.models`, `catalog.application.set_offer`, `catalog.policy`, `catalog.queries`, and `demo_orders.public` inspected before design. Cross-module access remains through `catalog.public` only.
