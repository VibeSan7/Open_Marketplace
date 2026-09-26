# Fulfillment list line summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a concise authorized shipment-line summary in the fulfillment list.

**Architecture:** Reuse the existing `lines` array in each authorized fulfillment snapshot. The web presenter adds a display-safe `lines_with_labels` projection, and the existing list template renders it. No domain model, public boundary, authorization rule or provider integration changes.

**Tech Stack:** Django view/template, existing `commerce.public` fulfillment snapshots, Django Test Client, Docker Compose validation.

**Spec:** `docs/superpowers/specs/2026-09-27-fulfillment-line-summary.md`

## Global Constraints

- No provider calls, delivery quotes, waybills, payments, refunds, payouts, deployment or migrations.
- Use only authorized snapshots returned through `commerce.public`.
- Do not expose package manifests or delivery addresses in the list.
- Keep web code independent from protected `commerce.models`.

---

### Task 1: Add regression assertions

**Files:**
- Modify: `open_marketplace/web/tests/test_commerce_fulfillment_journey.py`

**Interfaces:**
- Consumes: existing buyer and seller fulfillment list clients.
- Produces: coverage proving both authorized actors see the line summary.

- [x] Add assertions for the product title, variant label and quantity to the buyer list response.
- [x] Add the same assertions to the assigned seller list response.
- [x] Run the focused journey test and confirm it fails because the list does not render shipment lines.

### Task 2: Add the presentation projection and template output

**Files:**
- Modify: `open_marketplace/web/commerce_fulfillment_views.py`
- Modify: `open_marketplace/templates/commerce_fulfillment/list.html`

**Interfaces:**
- Consumes: `shipment["lines"]` from authorized public snapshots.
- Produces: `lines_with_labels`, preserving title, variant label and quantity for template rendering.

- [x] Build `lines_with_labels` from the existing line snapshot without changing the snapshot itself.
- [x] Render one escaped list item per shipment line below the shipment metadata.
- [x] Keep package count conditional so buyers still do not receive a seller-only zero value.
- [x] Run the focused journey test and confirm it passes.

### Task 3: Verify and commit locally

**Files:**
- No additional files.

- [x] Run compileall, JavaScript syntax check, diff check, focused tests, Django checks, migration drift check, import contracts and the full suite.
- [x] Mark this plan complete.
- [x] Commit locally with `feat: show fulfillment line summary`.
- [x] Do not push or create a PR.
