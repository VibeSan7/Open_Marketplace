# Fulfillment package manifest browser plan

**Goal:** Add a seller-only browser form for the existing pending-shipment package manifest operation.

**Architecture:** Keep validation and ownership in `commerce.public.set_fulfillment_packages`. Use a Django formset at the web boundary for repeated package rows, exact POST-key checks, and CSRF. Render package data only from the actor-aware fulfillment snapshot.

**Spec:** `docs/superpowers/specs/2026-09-26-fulfillment-package-web.md`

## Constraints

- No provider calls, carrier evidence, delivery quotes, package-to-line allocation, payments, or deployment.
- Web code uses `open_marketplace.commerce.public` and does not import protected commerce models.
- Empty manifests are allowed; each submitted row uses positive integer grams and centimetres.
- Seller edits are allowed only while the shipment is `pending`.

## Tasks

- [x] Add package form/formset and strict POST field validation.
- [x] Add seller-only package route and detail-page form without exposing it to buyers.
- [x] Add journey tests for save, clear, invalid input, buyer denial, foreign denial, and non-pending denial.
- [x] Update commerce readiness documentation.
- [x] Run focused tests, import contracts, migration checks, full suite, compileall, and diff check.
- [x] Commit locally only; do not push or create a PR.
