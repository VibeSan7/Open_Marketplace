# Fulfillment state filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a validated state filter to the authorized fulfillment list.

**Architecture:** Parse one exact optional `state` query parameter in the fulfillment web view, load the actor-authorized shipment snapshots through `commerce.public`, then filter the in-memory presentation rows. The template renders fixed state links and keeps the existing detail and mutation routes unchanged.

**Tech Stack:** Django view/template, existing commerce public boundary, Django Test Client, Docker Compose validation.

**Spec:** `docs/superpowers/specs/2026-09-27-fulfillment-state-filter.md`

## Global Constraints

- No provider calls, delivery quotes, waybills, payments, refunds, payouts, deployment or migrations.
- Filter only authorized public snapshots; never query or expose protected models from web code.
- Accept exactly zero or one `state` value and reject all other query parameters.
- Preserve existing package redaction and fulfillment state transitions.

---

### Task 1: Add failing filter assertions

**Files:**
- Modify: `open_marketplace/web/tests/test_commerce_fulfillment_journey.py`

**Interfaces:**
- Consumes: existing seller fulfillment list client and pending shipment fixture.
- Produces: regression coverage for matching, non-matching and malformed filters.

- [x] Assert `?state=pending` includes the shipment ID.
- [x] Assert `?state=ready` excludes the shipment and renders the empty result.
- [x] Assert duplicate `state`, unsupported state and unknown query keys return 400.
- [x] Run the focused test and confirm the new assertions fail before implementation.

### Task 2: Implement exact state parsing and filtering

**Files:**
- Modify: `open_marketplace/web/commerce_fulfillment_views.py`

**Interfaces:**
- Consumes: `request.GET` and authorized snapshots from `commerce.public.list_fulfillment_shipments`.
- Produces: filtered `shipments`, `active_state`, and fixed `state_filters` template data.

- [x] Add a parser that permits only one optional `state` key and validates it against `_STATE_LABELS`.
- [x] Load authorized shipments first, then filter by the validated state.
- [x] Build fixed links for all state labels plus the unfiltered list without accepting a user-supplied URL.
- [x] Return the existing 400 error for malformed query parameters.
- [x] Run the focused journey tests and confirm they pass.

### Task 3: Render, verify and commit locally

**Files:**
- Modify: `open_marketplace/templates/commerce_fulfillment/list.html`
- Modify: `docs/superpowers/plans/2026-09-27-fulfillment-state-filter.md`

- [x] Render the filter links, active state and filtered empty message.
- [x] Run compileall, JavaScript syntax check, diff check, focused tests, Django checks, migration drift check, import contracts and the full suite.
- [x] Mark this plan complete.
- [x] Commit locally with `feat: add fulfillment state filter`.
- [x] Do not push or create a PR.
