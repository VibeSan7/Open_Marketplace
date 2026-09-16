# Buyer convenience implementation plan

Spec: `docs/superpowers/specs/2026-09-16-readiness-buyer-conveniences.md`.
Lead implements directly; keep the installer coder's files untouched.

- [ ] Saved-product ownership/visibility/idempotency regressions RED.
- [ ] Minimal catalogue model + migration and public operations; GREEN.
- [ ] Saved HTTP/CSRF/escaped live state regressions RED then UI integration GREEN.
- [ ] Read-only seller storefront and public links, no private seller fields, RED/GREEN.
- [ ] Budget validation/multi-offer eligibility/default selection/order/cursor/facet regressions RED then backend GREEN.
- [ ] Search URL controls/no-JS/keyboard/browser regressions RED then frontend GREEN.
- [ ] Restore round trip for newly persisted saved preferences; schema/import checks and full suite.

Do not implement orders, live payment adapters or legal licence grants as part of these steps. Do not alter current catalogue admission or business snapshot/version semantics.
