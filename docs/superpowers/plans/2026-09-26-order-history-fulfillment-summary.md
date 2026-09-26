# Order history fulfillment summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show authorized local shipment status and links in the buyer's order-history rows.

**Architecture:** The order-list view reads orders and the buyer-authorized fulfillment list through `commerce.public`. It groups shipment rows by `order_id`, applies the existing web presentation labels and detail URLs, and passes the grouped summaries to the existing history template. No domain or persistence behavior changes.

**Tech Stack:** Django views/templates, existing commerce public boundary, Django Test Client, disposable Docker Compose test services.

**Spec:** `docs/superpowers/specs/2026-09-26-order-history-fulfillment-summary.md`

## Global Constraints

- No provider calls, delivery quotes, waybills, payments, refunds, payouts, deployment, or migrations.
- Web code uses `open_marketplace.commerce.public` and does not import protected commerce models.
- No new write operation; shipment state remains controlled by existing fulfillment operations.
- Buyer package manifests remain absent from buyer fulfillment snapshots.

---

### Task 1: Add failing order-history assertions

**Files:**
- Modify: `open_marketplace/web/tests/test_commerce_cart_journey.py`

**Interfaces:**
- Consumes: existing order-history journey setup and `commerce_public.create_fulfillment_plan`.
- Produces: regression coverage for planned and unplanned history rows.

- [x] Add an assertion that the unpaid order-history row shows the neutral not-planned message.
- [x] Extend the paid-order journey to open `/commerce-orders/` and expect the shipment state and authorized detail URL.
- [x] Run the focused journey test before implementation and confirm the planned history assertion fails because the list view/template does not expose fulfillment data.

### Task 2: Implement grouped read-only history summaries

**Files:**
- Modify: `open_marketplace/web/commerce_order_views.py`
- Modify: `open_marketplace/templates/commerce_orders/list.html`

**Interfaces:**
- Consumes: buyer-authorized `commerce_public.list_orders(context=...)` and `commerce_public.list_fulfillment_shipments(context=...)` rows.
- Produces: each order row gains `fulfillment_summaries`, using the same `id`, `state_label`, `delivery_mode_label`, and `detail_url` shape as order details.

- [x] Extract the existing single-shipment presentation mapping so order detail and order list use the same labels and URL construction.
- [x] Group authorized shipment summaries by `order_id` in one read and merge them into order rows.
- [x] Render each shipment link/state in the history row and the neutral message when the group is empty.
- [x] Preserve existing error handling and buyer authorization boundaries.
- [x] Run the focused cart and fulfillment journey tests and confirm green.

### Task 3: Verify and commit locally

**Files:**
- No additional files.

- [x] Run compileall, JavaScript syntax check, diff check, focused tests, Django checks, migration drift check, import contracts, and the full suite.
- [x] Mark this plan complete.
- [x] Commit locally with `feat: show fulfillment status in order history`.
- [x] Do not push or create a PR.
