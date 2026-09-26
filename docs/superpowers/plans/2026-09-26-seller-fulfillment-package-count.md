# Seller fulfillment package count Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show seller-only package counts in the fulfillment list without exposing package data to buyers.

**Architecture:** The existing fulfillment web presentation checks whether the authorized public snapshot contains the seller-owned `packages` key. It adds a count only when that key is present. The list template renders the count conditionally; the domain boundary and stored manifest remain unchanged.

**Tech Stack:** Django web view/template, existing commerce public fulfillment snapshots, Django Test Client, disposable Docker Compose services.

**Spec:** `docs/superpowers/specs/2026-09-26-seller-fulfillment-package-count.md`

## Global Constraints

- No provider calls, delivery quotes, waybills, payments, refunds, payouts, deployment, or migrations.
- Package count is seller-only; missing `packages` must not become a buyer-visible zero.
- Web code uses the public commerce boundary and does not import protected models.

---

### Task 1: Add failing seller/buyer list assertions

**Files:**
- Modify: `open_marketplace/web/tests/test_commerce_fulfillment_journey.py`

**Interfaces:**
- Consumes: seller/buyer authorized fulfillment clients and existing package journey helpers.
- Produces: regression coverage for zero, updated and redacted package counts.

- [x] Assert seller sees `Упаковок: 0` in the fulfillment list before saving a manifest.
- [x] Assert buyer does not see `Упаковок` in the same list.
- [x] Extend the multiple-package journey to assert seller sees `Упаковок: 2` after saving.
- [x] Run the focused tests before implementation and confirm the new seller count assertion fails.

### Task 2: Add the seller-only presentation field

**Files:**
- Modify: `open_marketplace/web/commerce_fulfillment_views.py`
- Modify: `open_marketplace/templates/commerce_fulfillment/list.html`

**Interfaces:**
- Consumes: authorized shipment snapshots with seller-only `packages`.
- Produces: `package_count`, set to `len(packages)` only when the snapshot contains `packages`, otherwise `None`.

- [x] Add `package_count` in `_present` without changing the public snapshot or authorization.
- [x] Render the count only when it is not `None`.
- [x] Run the focused fulfillment journey and confirm green.

### Task 3: Verify and commit locally

**Files:**
- No additional files.

- [x] Run compileall, JavaScript syntax check, diff check, focused tests, Django checks, migration drift check, import contracts, and the full suite.
- [x] Mark this plan complete.
- [x] Commit locally with `feat: show seller fulfillment package count`.
- [x] Do not push or create a PR.
