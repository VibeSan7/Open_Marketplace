# Fulfillment event timeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose and render a sanitized, ordered local state timeline for authorized fulfillment shipments.

**Architecture:** The fulfillment domain adds a read-only event projection to its existing snapshot. The projection strips actor identifiers and packages remain controlled by the existing buyer/seller redaction. The fulfillment web view maps event states/actions to Russian labels and renders a timeline on the existing detail page.

**Tech Stack:** Django domain services, existing `FulfillmentEvent` model, public commerce boundary, Django templates and Test Client, disposable Docker Compose services.

**Spec:** `docs/superpowers/specs/2026-09-26-fulfillment-event-timeline.md`

## Global Constraints

- No provider calls, delivery quotes, waybills, payments, refunds, payouts, deployment, or migrations.
- Event output contains only `sequence`, `state`, `action`, and `occurred_at`.
- Buyer package manifests remain absent from buyer snapshots.
- Web code uses `open_marketplace.commerce.public` and does not import protected commerce models.

---

### Task 1: Add failing domain and web tests

**Files:**
- Modify: `open_marketplace/commerce/tests/test_fulfillment.py`
- Modify: `open_marketplace/web/tests/test_commerce_fulfillment_journey.py`

**Interfaces:**
- Consumes: existing `create_fulfillment_plan`, `transition_fulfillment`, and authorized shipment screens.
- Produces: regression coverage for sanitized event snapshots and initial web rendering.

- [x] Update the exact fulfillment snapshot-key assertion to include `events`.
- [x] Assert a new shipment has one event with sequence `1`, action `planned`, and state `pending`, without `actor_id`.
- [x] Assert a seller transition appends sequence `2` with the new state and action `ready`.
- [x] Assert the authorized fulfillment detail page renders the timeline and planned-event label.
- [x] Run the focused tests before implementation and confirm they fail because snapshots and templates do not expose the event timeline.

### Task 2: Add the sanitized event projection

**Files:**
- Modify: `open_marketplace/commerce/fulfillment.py`

**Interfaces:**
- Consumes: related `FulfillmentEvent` rows ordered by `sequence`.
- Produces: snapshot key `events`, a tuple/list of mappings with exactly `sequence`, `state`, `action`, and ISO `occurred_at`.

- [x] Add the event projection to `_snapshot` in persisted sequence order.
- [x] Preserve `_snapshot_for_actor` package redaction and do not include actor IDs.
- [x] Keep transition persistence unchanged so every accepted transition appends one event.
- [x] Run focused domain tests and confirm the sanitized projection passes.

### Task 3: Render the timeline in the fulfillment detail view

**Files:**
- Modify: `open_marketplace/web/commerce_fulfillment_views.py`
- Modify: `open_marketplace/templates/commerce_fulfillment/detail.html`

**Interfaces:**
- Consumes: public shipment snapshots containing sanitized `events`.
- Produces: `events_with_labels` with action/state labels and the existing timestamp.

- [x] Add event action labels for planned, ready, in-transit and delivered states.
- [x] Map event rows without changing their order or adding protected fields.
- [x] Render the timeline on the authorized detail page and keep the local-operation notice.
- [x] Run focused fulfillment and cart journeys and confirm green.

### Task 4: Verify and commit locally

**Files:**
- No additional files.

- [x] Run compileall, JavaScript syntax check, diff check, focused tests, Django checks, migration drift check, import contracts, and the full suite.
- [x] Mark this plan complete.
- [x] Commit locally with `feat: show fulfillment event timeline`.
- [x] Do not push or create a PR.
