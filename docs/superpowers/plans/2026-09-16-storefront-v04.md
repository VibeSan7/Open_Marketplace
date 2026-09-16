# Marketplace v0.4 Implementation Plan

> **For agentic workers:** Use executing-plans, bounded coder invocations and lead integration. Follow the companion specification and file ownership; do not commit or publish independently.

**Goal:** Deliver an original, populated, public-browsing marketplace with an authenticated cart and connected simulated-order journey.

**Architecture:** Preserve Django templates and catalog.public boundaries. Add explicit public-listing opt-in and reuse demo_orders for cart checkout. Keep identity and seller authorization unchanged except for verified ordinary buyer access to explicitly public products.

**Tech Stack:** Python 3.13.15, Django 5.2.17, PostgreSQL 17, plain HTML/CSS/JavaScript, Playwright, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-16-storefront-v04-design.md`

## Global Constraints

- No real payments, shipping integration, outside deployment, real credentials, licence grant or copied reference-site assets.
- Product.public_listing defaults False; no migration opens old records. Anonymous result composition excludes private products and linked private offers before totals/filtering.
- Existing import boundaries, secure responses, live-session checks, CSRF and owner authorization stay active.
- Public opt-in applies only to eligible published content. Personal actions require an active verified ordinary account. Existing participant admission remains the private-catalog/seller boundary.
- DEMO_ORDERS_ENABLED explicitly controls simulated writes; no stock mutation in real catalog by checkout.
- One explicit coder-luna invocation per bounded work package; no hidden retry or reviewing model.
- Lead alone edits shared routes, settings, web/catalog_views.py, release docs and runtime.

## 1. Public listing and buyer access

**Files:** catalog/models.py, migrations/0004_public_listing.py (use actual next migration), policy.py, queries.py, search.py, common_cards.py, application.py, buyer.py, demo.py, public.py; catalog/tests/test_public_listing.py. Do not edit cart tests or templates.

**Interfaces:** set_public_listing(product_id, enabled, context); own-product DTO.public_listing; existing search/get_product/get_photo/get_seller_store signatures remain stable. get_demo_participant validates active verified ordinary buyer and serializes lock=True without granting Participant.allowed.

- [ ] Add regression using CatalogTestCase: create a published private product; anonymous search omits it; anonymous detail/photo fail; explicit owner opt-in exposes only the published photo and content.
- [ ] Add tests for owner mismatch, blocked/suspended/withdrawn data, private linked offers, category/suggestion totals, photo drafts, opt-out, non-admitted verified buyer and revoked sessions.
- [ ] Run `python manage.py test open_marketplace.catalog.tests.test_public_listing --noinput`; record expected RED.
- [ ] Implement the field, migration, visibility composition and opt-in function. Preserve private admitted behavior and protected owner preview.
- [ ] Run the focused tests, catalog regression and lint-imports; hand off exact changed paths and logs.

Representative test:
```python
product_id, variant_id, photo_id = self.product()
self.catalog.set_public_listing(product_id=product_id, enabled=True, context=self.seller_context)
result = self.catalog.get_product(product_id=product_id, context=anonymous_context)
self.assertEqual(result["id"], str(product_id))
```
The anonymous_context is an OperationContext with actor_account_id=None and session_id=None; all other fields follow existing fixtures.

## 2. Cart and coherent checkout

**Files:** demo_orders/cart.py, cart_views.py, cart_forms.py, cart_urls.py, models.py, migrations; templates/cart/; demo_orders/static/demo_orders/cart.css; catalog/tests/test_cart.py; web/tests/test_cart_journey.py.

**Interfaces:** get_cart/add_cart_item/update_cart_item/remove_cart_item/checkout_cart exactly as in the spec. URL names cart/cart-add/cart-update/cart-checkout, served by cart_urls.py without app namespace. Lead includes at root in config/urls.py. Existing demo-order APIs and routes remain valid.

- [ ] Test two-item account-owned cart; add/update/remove, whole and fractional units, free price, no self-purchase, no foreign ownership/price input, disabled mode and CSRF.
- [ ] Test stale prices/cart revision and one atomic multi-item checkout; repeat stable intent returns the same orders; one unavailable row rolls back all reservations.
- [ ] Use a per-buyer unique Cart with revision, line snapshots and confirmed unit prices; derive a stable checkout intent from cart/revision. Store successful checkout receipt/order IDs to recognize repeats after cart clearing. Price changes require explicit quantity/price confirmation, not an automatic refresh-and-purchase.
- [ ] Implement through catalog.public and demo_orders.public only; lock cart then process variant IDs in sorted order. Use Decimal localcontext adequate for existing max_digits.
- [ ] Provide secure GET/POST views, Russian field/errors, seller grouping, totals, remove/update buttons and honest simulation/disabled states.
- [ ] Run focused tests and preserve legacy single-offer order flows.

Core acceptance sequence:
```python
add_cart_item(variant_id=first, quantity="1", context=buyer)
add_cart_item(variant_id=second, quantity="2", context=buyer)
cart = get_cart(context=buyer)
orders = checkout_cart(intent_id=cart["intent_id"], context=buyer)
replayed = checkout_cart(intent_id=cart["intent_id"], context=buyer)
assert orders == replayed
```

## 3. Storefront presentation

**Files:** templates/base.html, home.html, catalog/search.html, _results.html, product.html, saved.html, seller.html; templates/demo_orders/; catalog/static/catalog/site.css, catalog.css and buyer interaction JS if needed; web/home_views.py; web/tests/test_storefront_presentation.py.

**Interfaces:** keep existing search/product DTO and URLs, data-results/data-items/data-item-id/cursor/fragment hooks. Home receives storefront.categories/items/total via anonymous catalog.public access. Cart links use specified route names; POST add contains quantity=1 and csrf_token. No cart-model or protected-module imports.

- [ ] Add template/view regressions for global search, cart navigation, nonempty anonymous homepage from public data, empty installation, semantic headings, hidden private records and valid category links.
- [ ] Build Explore-first responsive header, category shortcuts, product grid and compact editorial category features. Keep original restrained teal brand, clear numeric prices and neutral product surfaces. No copied images, ratings, discounts or filler metrics.
- [ ] Rework detail into gallery + selection + purchase area; selected variant and seller offers remain visible and accurate. Gallery buttons must select the real image; no dead controls.
- [ ] Style saved, seller and demo order/list/detail views coherently with mobile targets >=44px and one visible page h1.
- [ ] Run focused Django tests. Lead performs full desktop/mobile browser runs after integration.

## 4. Lead integration and reproducible content

**Files:** web/catalog_views.py, web/urls.py, config/urls.py, templates/catalog/editor.html, verification/demo_storefront.py, verification/management/commands/seed_demo_storefront.py, verification demo image assets + provenance, tests, README and release/runbooks.

- [ ] Remove login-only wrappers solely from eligible browse GET routes; add owner-protected POST public opt-in toggle with strict boolean form. Preserve owner, staff and saved authentication.
- [ ] Include cart URLs. Wire home/category links and public editor state without crossing module boundaries.
- [ ] Test the explicit demo-content command before implementing: refuses non-demo collisions, is idempotent, creates no usable/fixed passwords, never opens existing private products, runs only under explicit demo confirmation and writes images safely.
- [ ] Create a curated manifest with stable namespaced UUIDs, synthetic category/offer content and bundled licensed product photographs. Normal startup remains empty. Existing real/legacy content is untouched.
- [ ] Seed a disposable installation, prepare search and verify every generated category/product/photo count programmatically against the manifest.

## 5. Acceptance and delivery

- [ ] Run check, makemigrations --check --dry-run, lint-imports and the complete open_marketplace tests in an isolated database.
- [ ] Run real Playwright desktop/mobile public browse, saved/cart/checkout/cancellation and seller opt-in/out tests. Capture screenshots and inspect them; verify images, no horizontal overflow, keyboard access, no console/page errors and no dead primary links.
- [ ] Exercise documented clean Docker installation and seed command, plus database/photo restore.
- [ ] Update version and Russian/English docs with exact access migration, demo nature, seed, startup and rollback instructions. Audit source/history/archive for secrets/private runtime files.
- [ ] Commit, open PR in the existing repository, wait for exact-head CI, merge, wait for main CI, publish verified ZIP/checksum and download without auth.
- [ ] Back up the authorized local demo database/media/config/image metadata; update only that stack and verify public storefront plus preserved private legacy data. Do not remove volumes. Record and exercise the reversible image/config/database rollback procedure in a disposable restore environment.
- [ ] Report the actual local address, release/download links, completed verification and limits (simulation, not real trade).
