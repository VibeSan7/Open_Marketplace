# Fulfillment package manifest browser boundary

Expose the existing seller-owned package manifest operation through the authenticated local fulfillment screen. This remains preparation data only: it does not calculate delivery, call CDEK, create a waybill, or prove carrier movement.

## Scope

- Seller can replace the complete package manifest from a pending shipment detail screen.
- The form supports zero or more package rows with positive integer grams and centimetres.
- Buyer can view the shipment but cannot see package data or the seller package form.
- The existing commerce service remains the authorization and validation boundary.
- Browser requests remain POST-only, CSRF-protected, exact-field validated, and redirect after success.
- Package editing is unavailable after the shipment leaves `pending`.

## Invariants

- No web code imports protected commerce models.
- A foreign seller receives the same neutral denial as an unknown shipment.
- Invalid form data does not mutate the stored manifest.
- The form does not expose buyer delivery address data or provider evidence.
- CDEK transitions and provider-disabled behavior remain unchanged.

## Acceptance

1. Seller can open the package form, add multiple rows, save them, and see the saved manifest.
2. Empty submission clears the manifest.
3. Buyer detail pages omit the manifest and form; buyer POST attempts are denied.
4. Invalid, duplicate, unknown, and non-CSRF fields are rejected without mutation.
5. Non-pending and foreign-shipment updates are rejected without mutation.
6. Focused web tests, import contracts, migration checks, full suite, compileall, and whitespace checks pass.

## Deferred

Package-to-line allocation, tariff calculation, CDEK payload construction, shipment creation, pickup/refusal/returns, and verified carrier lifecycle events remain separate slices.
