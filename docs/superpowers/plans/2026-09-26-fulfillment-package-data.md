# Fulfillment package data implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Store and expose seller-owned package dimensions for pending local fulfillment shipments without connecting a carrier.

**Architecture:** Add a JSON package manifest to `FulfillmentShipment`. Validate and replace the complete manifest inside the commerce service under a row lock. Keep package data in seller-facing fulfillment snapshots only; buyer snapshots remain unchanged.

**Tech Stack:** Django models and migrations, PostgreSQL JSONField, existing commerce public boundary, unittest/Django test runner, Docker Compose.

**Spec:** `docs/superpowers/specs/2026-09-26-fulfillment-package-data.md`

## Global Constraints

- No CDEK, payment, payout, waybill, delivery quote, carrier, or deployment calls.
- Web and external callers use `open_marketplace.commerce.public`; protected model imports stay inside commerce.
- Package rows use positive integer grams and centimetres; empty manifests remain allowed.
- Use TDD and run the full disposable Docker suite before commit.

---

### Task 1: Domain contract and persistence

**Files:**
- Modify: `open_marketplace/commerce/models.py`
- Create: `open_marketplace/commerce/migrations/0008_fulfillmentshipment_packages.py`
- Modify: `open_marketplace/commerce/fulfillment.py`
- Modify: `open_marketplace/commerce/public.py`
- Test: `open_marketplace/commerce/tests/test_fulfillment.py`

**Interfaces:**
- Produce `set_fulfillment_packages(*, shipment_id, packages, context)` returning the seller-facing shipment snapshot.
- Add `packages` to shipment snapshots; keep it absent from buyer read views.

- [x] Write tests for default empty manifests, valid seller replacement, invalid data, foreign seller rejection, immutable-state rejection, and buyer redaction.
- [x] Run the focused fulfillment tests and confirm failure because the public function and field are missing.
- [x] Add the JSON field, migration, validator, locked replacement service, public export, and role-aware read redaction.
- [x] Run focused domain tests, Django checks, migration drift, and import-linter.

### Task 2: Documentation and validation

**Files:**
- Modify: `README.md`
- Modify: `README.ru.md`
- Modify: `docs/integrations/commerce-readiness.md`
- Modify: `docs/integrations/cdek-client.md`

- [x] Document package manifests as local preparation data and preserve provider/live-shipping limitations.
- [x] Run `python -m compileall -q open_marketplace` and `git diff --check`.
- [x] Prepare the search model cache and run the complete Docker suite.
- [x] Commit locally only; do not push or create a PR.
