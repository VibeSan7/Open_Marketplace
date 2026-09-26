# Fulfillment state summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Display authorized fulfillment counts by state without changing the existing list filter.

**Architecture:** Keep the authorized snapshot tuple as the source of truth, derive a small fixed summary before filtering, then pass the summary to the existing list template. The public commerce boundary, authorization, storage and lifecycle remain unchanged.

**Tech Stack:** Django view/template, existing `commerce.public` fulfillment snapshots, Django Test Client, Docker Compose validation.

**Spec:** `docs/superpowers/specs/2026-09-27-fulfillment-state-summary.md`

## Global Constraints

- No provider calls, delivery quotes, waybills, payments, refunds, payouts, deployment or migrations.
- Derive counts only from authorized snapshots returned by `commerce.public.list_fulfillment_shipments`.
- Counts must be computed before applying `state` filtering.
- Keep package manifests and delivery addresses hidden according to the existing actor boundary.

---

### Task 1: Add failing summary assertions

**Files:**
- Modify: `open_marketplace/web/tests/test_commerce_fulfillment_journey.py`

**Interfaces:**
- Consumes: existing seller list fixture and state-filter request.
- Produces: coverage for total/pending counts and filter-independent summary.

- [x] Assert the unfiltered seller list shows `Всего: 1` and `Ожидает планирования: 1`.
- [x] Assert the `?state=ready` seller list still shows the same counts while showing no matching shipment.
- [x] Run the focused test and confirm the new assertions fail before implementation.

### Task 2: Derive the authorized state summary

**Files:**
- Modify: `open_marketplace/web/commerce_fulfillment_views.py`

**Interfaces:**
- Consumes: the full authorized shipment tuple before state filtering.
- Produces: `state_summary` with total and fixed state counts for the template.

- [x] Derive total and one count per `_STATE_FILTERS` entry before filtering.
- [x] Preserve the existing `shipments`, `active_state_label` and `state_filters` context values.
- [x] Run the focused journey tests and confirm the summary assertions pass.

### Task 3: Render, verify and commit locally

**Files:**
- Modify: `open_marketplace/templates/commerce_fulfillment/list.html`
- Modify: `docs/superpowers/plans/2026-09-27-fulfillment-state-summary.md`

- [x] Render total and state counts without exposing unfiltered shipment details.
- [x] Run compileall, JavaScript syntax check, diff check, focused tests, Django checks, migration drift check, import contracts and the full suite.
- [x] Mark this plan complete.
- [x] Commit locally with `feat: show fulfillment state summary`.
- [x] Do not push or create a PR.
