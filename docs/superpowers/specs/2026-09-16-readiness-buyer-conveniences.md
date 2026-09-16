# Buyer conveniences inside the closed test catalogue

These implement the owner's approved product-review improvements, not a change of admission, trading or payment policy. Existing CAT semantics remain the default.

## Saved products

- Add catalogue `SavedProduct(account_id UUID, product FK, created_at)` with a unique account/product constraint. Store no copied titles, seller private details or historic price snapshots.
- Public module operations: `set_saved_product(product_id, saved: bool, context)` and `list_saved_products(context)`. Require current catalogue participation on every call. Adding requires current visibility via the existing catalogue policy. Removing is idempotent and scoped to the current account even if the product is now hidden. Never expose another account's collection.
- Read lists through current authorized public projections; hidden, blocked, withdrawn, non-admitted seller/category content does not leak through bookmarks.
- Web GET `/catalog/saved/` (`catalog-saved`), POST `/catalog/p/<uuid:product_id>/saved/` (`catalog-save-product`). Explicit `save`/`remove`, CSRF, safe hard-coded application redirect (no user-supplied redirect URLs), no GET mutation.
- Product detail gets a local save/remove form; lists get links and owner-scoped removal. No shared-layout mutation forms, preserving neutral responses.

## Seller storefront

- Read-only `/catalog/seller/<uuid:seller_id>/` (`catalog-seller`), service `get_seller_storefront(seller_id, context)`.
- Only currently admitted viewers and sellers with currently visible products. Use existing approved public seller display names and catalogue projections; never copy legal name, registration identifier, contact email, applications or employee fields into a public page.
- Show the seller's currently visible physical cards, current prices and availability, explain that test admission is not a quality guarantee. Do not fabricate delivery, return, rating or verification promises. The existing absence of orders/payment/delivery terms is explicit.
- Public offer projections may include seller-profile IDs to build these links; never expose account IDs or application IDs.

## Budget and order controls

- Query parameters `price_min`, `price_max`, `sort`; sort values `relevance` (default), `price_asc`, `price_desc`. Use the existing exact decimal price validator (including zero and comma input), reject invalid precision, negatives, unsupported sort values and min > max. Do not silently clear invalid conditions.
- Budget applies to available eligible offers, not an unrelated cheapest offer on the same common variant. Filtered cards show prices from the eligible offers. Existing characteristic, availability and common-card aggregation rules remain enforced.
- Sorting operates over the whole matching set before pagination; deterministic ID tie-break, approximate-match flags and spelling suggestions remain correct. Cursor fingerprints bind budget and sort too; price keys are serializable exact minor-unit integers, not floats.
- Preserve conditions through pagination, search suggestions, share/back links and explicit single-condition removal. Initial detail selection must correspond to a matching variant from search; the product page must clearly distinguish preserved search conditions from the full set of that variant's offers. An explicitly selected valid variant is never silently replaced. Inactive/hidden data never enters any result.

## Tests and verification

TDD: ownership, revocation/hidden data, idempotency/CSRF, zero-price boundary, multi-offer budget, sorting/ties/cursor mismatch, facet conditions, malformed/duplicate URL parameters, real browser controls and no-JS submission. Exact-decimal storage/API remains unchanged. Use isolated test DBs and mount `D:/Open_Marketplace/.worktrees/phase2-catalog/model-cache:/app/model-cache` whenever a test searches text. Update migration/restore checks and prove the full suite after integration. No live demo data changes until final verified runtime update.
