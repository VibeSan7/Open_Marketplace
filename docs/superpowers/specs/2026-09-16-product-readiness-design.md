# Product readiness: existing user journeys and catalogue usability

## Authorization and scope

The owner approved implementing the role-based product review and working through it to a verified result. This subordinate design covers improvements to the existing identity/seller/catalogue product without changing admission or financial rules. The overall specification and all 47 CAT decisions remain constraints. The initial user-journey fixes do not imply authorization for a real payment provider, live deployment, real seller onboarding or a new copyright licence.

## Decisions

1. Keep the current linked worktree on branch `product/readiness`, based on `0639b90c7d0464704204c3e363c5fd0e5671e105`. The running demonstration remains unchanged until acceptance and a reversible runtime update.
2. `/` becomes a public informational home, route name `home`, implemented in `web/home_views.py`. It explains the closed demonstration, has working catalogue/login/register/seller-start links and does not expose catalogue records or personal data.
3. `/seller/`, route name `seller-start`, is an informational entry point, implemented in `web/seller_views.py`, registered in `web/urls.py`. Anonymous visitors receive public instructions and login/register links; an authenticated owner can see only their own progress. Service accounts are told to use an ordinary account, never granted selling rights.
4. Existing identity and seller pages use complete Russian copy, meaningful field labels and explanations. The intended default Django language is `ru`; preserve machine-level identifiers, audit codes, URL names and numeric protocol values. Password/TOTP recovery setup secrets retain their existing protected flow and must not be echoed into logs or reports.
5. Before redisplaying a bound invalid seller application, establish that the current account can read/edit that own draft through the existing public boundary. Redisplay safe submitted fields with inline errors only for the permitted own draft. Foreign and unknown objects remain indistinguishable, including invalid submissions; no CSRF markup is added to global neutral/error responses.
6. The seller entry shows the sequence email → account protection → test-data application → review → catalogue admission → first product. Describe the existing test-data requirement explicitly; do not remove it, check it automatically, auto-admit users, expand roles or relax reauthentication.
7. Own catalogue rows show human-readable kind, publication state, current available price range and availability, with a clear next action. The editor explains separate draft, price/stock and publication operations and exposes a readiness checklist. It must not conflate no price with zero price or auto-publish drafts.
8. Buyer convenience changes keep the participant gate. Saved products belong to an ordinary account and are never listed for another account; visibility is rechecked against current catalogue policy. Price filtering and sorting use available authorized offers, remain deterministic and travel in search URLs/cursors; default relevance remains unchanged. New price controls describe product prices, not an unimplemented delivery-inclusive total.
9. Seller storefront information is explicitly entered public content, separate from private registration data. It never republishes contact email or legal registration fields implicitly, nor claims verified purchases or delivery quality without corresponding evidence.
10. Installer guidance explains the real existing bootstrap and role boundaries. No public unauthenticated administrator-creation endpoint is added. Public code-use documentation may clarify the absence of an approved licence but must not grant new copyright rights. A CI workflow must use read-only permissions and disposable test settings, not working secrets.

## Ownership and integration

- `coder-luna`, one explicit invocation: `web/forms.py`, `web/identity_views.py`, `web/seller_views.py`, `web/staff_views.py` (copy only), `web/errors.py` (copy only), `web/urls.py` (seller-start only), `templates/identity/`, `templates/registration/`, `templates/seller/`, focused web tests, and only the language setting in `config/settings.py`.
- Hermes: home, base navigation, catalogue/backend/buyer features, setup guidance, tests for those, documentation, integration and runtime acceptance.
- Shared-file hotspots: `config/settings.py`, `web/urls.py`, and later `web/catalog_views.py`/`catalog/models.py` are edited sequentially across work packages, never concurrently by different writers. No worker commits, pushes or changes runtime services.

## Verification

Start from an executed clean baseline. Each change gets an expected failing regression before implementation. Preserve all permission, CSRF, neutral-response and concurrency tests. Use different `DATABASE_NAME` values for parallel isolated focused test runs; the final complete suite is serialized. Verify navigation from the home page and browser user journeys, not just direct URLs. Before runtime replacement preserve the old image/configuration, database/media and local demonstration data; never remove their volumes.

## Separate order/payment gate

The overall specification sections 16–17 require researched decisions about the partner, legal model, reservation/protection periods, order limits, delivery proof and financial operations before that phase. Those are not silently replaced by invented numbers or by a fake successful payment. A test adapter, if separately designed and implemented, must be explicitly labelled simulation and cannot establish readiness for real trade. This work does not claim the entire Russian public beta is complete.
