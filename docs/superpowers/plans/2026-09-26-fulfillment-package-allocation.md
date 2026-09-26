# Fulfillment package-to-line allocation plan

**Goal:** Make local seller package manifests identify their shipment contents and validate exact line quantities.

**Architecture:** Extend the existing `packages` JSON snapshot with `items` entries keyed by immutable shipment-local `line_index`. Validate against `FulfillmentShipment.lines` under the existing shipment/order lock. Extend the seller formset with one optional quantity field per shipment line; the commerce service remains authoritative.

**Spec:** `docs/superpowers/specs/2026-09-26-fulfillment-package-allocation.md`

## Constraints

- No CDEK, provider requests, delivery quotes, payments, refunds, disputes, payouts, or deployment.
- No schema migration is required because the manifest is already JSON; existing new writes use the extended shape.
- Empty manifests remain valid for preparation-clearing and legacy unallocated shipments.
- Web code stays on the public commerce boundary and never imports protected commerce models.

## Tasks

- [x] Add failing domain tests for valid split allocation, exact totals, invalid indexes/quantities, and no mutation.
- [x] Add failing web tests for multi-line form submission, buyer/foreign denial, and state lock.
- [x] Implement domain allocation validation and normalize package item snapshots.
- [x] Extend the seller formset and detail UI with shipment-line quantity fields.
- [x] Update documentation and prior package tests/fixtures to the new manifest shape.
- [x] Run focused tests, import contracts, migration checks, full suite, compileall, and diff check.
- [ ] Commit locally only; do not push or create a PR.
