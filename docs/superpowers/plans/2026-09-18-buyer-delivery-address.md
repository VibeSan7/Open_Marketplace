# Buyer delivery address implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Require a buyer-owned delivery address for local checkout and preserve its immutable snapshot on the order.

**Architecture:** Add an address model and public application operations inside commerce. Checkout resolves the buyer-scoped address before creating the order, stores a copied JSON snapshot on `CommerceOrder`, and records the selected address ID on the cart receipt for replay protection. The web layer uses only commerce public operations and provides a small saved-address form plus checkout selection.

**Tech Stack:** Django 5.2, PostgreSQL, existing Docker test services, Django forms and templates.

**Spec:** `docs/superpowers/specs/2026-09-18-buyer-delivery-address.md`

## Global constraints

- No new dependencies.
- No payment, payout, delivery quote, CDEK request, shipment creation, or deployment.
- Keep demo orders and demo cart untouched.
- Keep buyer ownership checks inside commerce operations.
- Never log address field values.
- Use TDD: every production behavior starts with a failing test.

---

### Task 1: Domain model and public address operations

**Files:**
- Modify: `open_marketplace/commerce/models.py`
- Create: `open_marketplace/commerce/migrations/0007_commercedeliveryaddress_order_address.py`
- Modify: `open_marketplace/commerce/services.py`, `open_marketplace/commerce/public.py`
- Test: `open_marketplace/commerce/tests/test_delivery_address.py`

**Interfaces:**
- `create_delivery_address(*, data, context) -> dict`
- `list_delivery_addresses(*, context) -> tuple[dict, ...]`
- `get_delivery_address(*, address_id, context) -> dict`
- `checkout_commerce_cart(..., delivery_address_id, ...)` preserves an address ID in the replay receipt.
- `CommerceOrder.delivery_address` stores the copied public address snapshot.

- [x] Write tests for own-address creation/listing, foreign neutral rejection, field validation, order snapshot persistence, same-address replay, and different-address replay rejection.
- [x] Run focused tests and confirm RED because the operations/model do not exist.
- [x] Add the address model, order JSON snapshot, receipt address ID, and migration.
- [x] Implement validation and buyer-scoped service operations without importing web modules.
- [x] Update checkout to resolve the address before order creation and reject conflicting replays.
- [x] Run commerce tests, migration drift, and import contracts; confirm GREEN.
- [x] Commit `feat: add buyer delivery address boundary`.

### Task 2: Address and checkout web flow

**Files:**
- Modify: `open_marketplace/web/commerce_cart_forms.py`, `commerce_cart_views.py`, `commerce_cart_urls.py`
- Create: `open_marketplace/web/commerce_address_views.py`, `commerce_address_urls.py`
- Create: `open_marketplace/templates/commerce_addresses/list.html`, `form.html`, `error.html`
- Modify: `open_marketplace/templates/commerce_cart/checkout.html`, `open_marketplace/config/urls.py`, `templates/base.html`
- Test: `open_marketplace/web/tests/test_commerce_cart_journey.py`

**Interfaces:**
- Authenticated ordinary buyers can create/list addresses at `/commerce-addresses/`.
- Checkout GET lists own addresses; checkout POST requires a canonical `delivery_address_id`.
- Unknown/foreign address IDs return the existing neutral commerce error response.

- [x] Write browser/request regressions for address creation, checkout address selection, missing address, and foreign address rejection.
- [x] Run the new web tests and confirm RED.
- [x] Implement minimal forms, CSRF-protected POST, named routes, and checkout selection.
- [x] Display the immutable order address snapshot in order detail.
- [x] Run focused web tests and confirm GREEN.
- [x] Commit `feat: connect delivery address to checkout`.

### Task 3: Full verification and documentation

**Files:**
- Modify: `docs/integrations/commerce-readiness.md`, `README.md`, `README.ru.md`
- Create/update: `artifacts/commerce-planning/commerce-address-full.log`

- [x] Run `prepare_catalog_search`.
- [x] Run Django checks, migration drift, import contracts, focused tests, full suite, and restore proof in disposable Docker services.
- [x] Run `git diff --check` and compile checks.
- [x] Update documentation without claiming live shipping or payments.
- [x] Commit documentation if needed and report exact test results.
