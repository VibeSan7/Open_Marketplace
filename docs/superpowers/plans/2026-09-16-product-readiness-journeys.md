# Product Readiness — Existing Journeys Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A visitor can start at the home page, understand the closed demo, and follow working account/seller/product paths without losing their form data or guessing internal labels.

**Architecture:** Extend the existing Django presentation layer and read-only catalogue projections. Keep domain authorization, the participant gate, public-boundary imports and existing write commands. The leading Hermes integrates a bounded coder invocation for identity/seller copy and forms.

**Tech Stack:** Python 3.13, Django 5.2, PostgreSQL, Docker Compose, existing Playwright/Chromium test image.

**Spec:** `docs/superpowers/specs/2026-09-16-product-readiness-design.md`

## Global Constraints

- Preserve all 47 CAT decisions and the closed participant admission.
- No real payments, new live deployment, real-data registration or unapproved licence grant.
- CSRF, neutral foreign/unknown responses, current-session ownership, MFA and recent authentication stay enforced.
- Never print or commit working `.env`, tokens, passwords or personal data.
- No new dependencies or unrelated refactoring. No worker commit/push/runtime mutation.
- Use the isolated test services; never target the running demonstration database.

## Task 1: Baseline and isolated work

- [x] Create branch `product/readiness` from the observed `origin/main` in the existing linked worktree.
- [x] Inspect settings, catalogue public boundary, projections, search, seller views and regression fixtures.
- [ ] Run the existing complete suite and record the real result in `artifacts/readiness/baseline.log`.

Command (working directory is this worktree):

```bash
docker compose -p omp-phase2-20260915 -f compose.yaml -f compose.test.yaml run --rm --no-deps --pull never -T -e DATABASE_NAME=omp_readiness_baseline -v 'D:/Open_Marketplace/.worktrees/ui-presentation/open_marketplace:/app/open_marketplace' -v 'D:/Open_Marketplace/.worktrees/phase2-catalog/model-cache:/app/model-cache' test python manage.py test --noinput --verbosity 1
```

## Task 2: Russian identity/seller experience and safe form errors

**Files:** `web/forms.py`, `web/identity_views.py`, `web/seller_views.py`, `web/urls.py`, `templates/identity/`, `templates/registration/`, `templates/seller/`, focused `web/tests/`; copy-only changes to `web/staff_views.py`/`web/errors.py`; `LANGUAGE_CODE` in `config/settings.py`.

**Interfaces:** Produces `/seller/` named `seller-start`; reuses existing public identity/seller operations and existing named action routes. Does not modify base navigation, catalogue code or domain schemas.

- [ ] Add failing copy/label and seller-start regressions in `web/tests/test_user_journeys.py`.
- [ ] Add a permitted own-invalid-draft regression to `test_seller_pages.py` that checks posted display name/contact retention and field errors.
- [ ] Add invalid foreign/unknown equivalence and no-write regressions, retaining existing CSRF/security assertions.
- [ ] Run focused tests with `DATABASE_NAME=omp_readiness_journeys`, record expected RED.
- [ ] Render bound own invalid forms only after the existing ownership check, keeping neutral responses elsewhere. Translate visible strings and labels without changing enum/audit/route values. Add the read-only seller-start guide and explicit test-data instructions.
- [ ] Run all existing identity/seller/sessions/TOTP/sensitive-link page regressions plus new tests and record GREEN.

Regression shape, adapted to the existing `SellerPageTests` fixture methods:

```python
def test_invalid_own_draft_preserves_safe_fields(self):
    account = self._account()
    self._bind(self.client, account)
    application_id = self._create_application()
    response = self._post(
        self.client, "seller-application-edit",
        data={**self.draft, "contact_email": "invalid-address"},
        kwargs={"application_id": application_id},
    )
    self.assertEqual(response.status_code, 200)
    self.assertContains(response, self.draft["display_name"])
    self.assertTrue(response.context["form"].errors["contact_email"])
```

## Task 3: Working public home and navigation

**Files:** create `web/home_views.py`, `templates/home.html`, `web/tests/test_home.py`; modify `config/urls.py`, `templates/base.html`; reuse existing stylesheet classes.

**Interfaces:** Consumes the existing `secure_render` and named routes plus `seller-start` from Task 2. Produces `/` named `home`; no catalogue data or private account query for anonymous visitors.

- [ ] Add regression and run RED:

```python
from django.test import SimpleTestCase

class HomeTests(SimpleTestCase):
    def test_home_has_real_next_actions_and_demo_notice(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        for text in ("Каталог", "Стать продавцом", "демонстрацион"):
            self.assertContains(response, text)
        self.assertContains(response, 'href="/catalog/"')
        self.assertContains(response, 'href="/seller/"')
```

- [ ] Add the read-only home view and route, then a page with existing layout styles and working next-action links. Keep closed-demo and no-real-payments text explicit.
- [ ] Make the brand link lead home and expose seller-start in navigation; do not add a global POST/CSRF form to error-page layout.
- [ ] Run new home tests and existing neutral-response/browser layout tests.

## Task 4: Seller catalogue readiness

**Files:** `catalog/queries.py`, `catalog/public.py`, `catalog/tests/test_readiness.py`, `templates/catalog/own.html`, `templates/catalog/editor.html`, `web/catalog_views.py`, relevant web/browser tests.

**Interfaces:** Extend own-product projection with presentation-only `status_label`, price/availability summary and checklist entries derived from the actual publication requirements. Keep public snapshots and write-command signatures unchanged.

- [ ] Read `catalog/application.py` publication validation before defining checklist cases.
- [ ] Add failing assertions for draft/published/blocked/withdrawn states, zero price, missing versus zero stock, changed draft versus published snapshot, and foreign-account isolation.
- [ ] Derive status and missing publication conditions from real current state. Display them in own-list/editor without mutating or publishing anything.
- [ ] Expose an existing permitted public view when published; never create an anonymous draft-preview bypass.
- [ ] Run focused catalogue/web tests, then browser checks for headings, mobile overflow and all next-action links.

## Task 5: Integration acceptance

- [ ] Inspect the full diff and every worker change; self-review without launching another reviewing model.
- [ ] Resolve Russian number formatting explicitly without changing numeric protocol values or accepted domain input silently.
- [ ] Run the entire suite serially, migrations checks, import contracts, JavaScript syntax and whitespace validation.
- [ ] Exercise the live user journeys on a disposable test instance before replacing the running demonstration.
- [ ] Record the tested boundaries and exact results; follow with the separately specified buyer/seller conveniences. Do not claim the order/payment phase is complete merely because this package passes.
