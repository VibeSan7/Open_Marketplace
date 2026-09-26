# Order fulfillment summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the buyer's authorized local shipment summaries on the order-detail page without changing commerce state.

**Architecture:** The order view reads the existing order through `commerce.public.get_order` and reads authorized shipments through `commerce.public.list_fulfillment_shipments`, filtering by the order id. The web layer adds presentation labels and links; existing fulfillment snapshots and buyer redaction remain authoritative.

**Tech Stack:** Django views/templates, existing commerce public boundary, Django Test Client, disposable Docker Compose test services.

**Spec:** `docs/superpowers/specs/2026-09-26-order-fulfillment-summary.md`

## Global Constraints

- No provider calls, delivery quotes, waybills, payments, refunds, payouts, deployment, or migrations.
- Web code uses `open_marketplace.commerce.public` and does not import protected commerce models.
- No new write operation; shipment state remains controlled by existing fulfillment operations.
- Buyer package manifests remain absent from buyer fulfillment snapshots.

---

### Task 1: Add the failing order-detail journey tests

**Files:**
- Modify: `open_marketplace/web/tests/test_commerce_cart_journey.py`

**Interfaces:**
- Consumes: `commerce_public.checkout_commerce_cart`, `commerce_public.create_fulfillment_plan`, and the existing buyer web client.
- Produces: regression coverage for planned and unplanned order-detail summaries.

- [x] Add a test that creates a paid local order, plans seller-arranged fulfillment, opens `/commerce-orders/<id>/`, and expects the shipment id, local state, and detail URL.
- [x] Extend the existing unpaid order-detail journey to expect the neutral not-planned message.
- [x] Run the focused order journey tests and confirm the new planned-summary assertion fails because the view/template does not expose it yet.

### Task 2: Implement the read-only order summary

**Files:**
- Modify: `open_marketplace/web/commerce_order_views.py`
- Modify: `open_marketplace/templates/commerce_orders/detail.html`

**Interfaces:**
- Consumes: buyer-authorized `commerce_public.list_fulfillment_shipments(context=...)` rows.
- Produces: template context `fulfillment_shipments`, each with `state_label`, `delivery_mode_label`, `id`, `order_id`, and an authorized detail URL.

- [x] Add local state/mode labels in the web view and filter the public shipment list by `order_id`.
- [x] Catch the same read errors already handled by the order detail view.
- [x] Render a shipment section with links when rows exist and a neutral message when it is empty.
- [x] Keep the existing notice that the commerce flow is local and provider-disabled.
- [x] Run the focused order and fulfillment journey tests and confirm green.

### Task 3: Verify and commit locally

**Files:**
- No additional files.

- [x] Run compileall, JavaScript syntax check, diff check, Django checks, migration drift check, import contracts, focused tests, and the full suite.
- [x] Mark this plan complete.
- [x] Commit locally with `feat: show fulfillment summary on order details`.
- [x] Do not push or create a PR.
