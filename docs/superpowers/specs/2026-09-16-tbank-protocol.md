# T-Bank Safe Deal protocol adapter

This slice implements the publicly documented EACQ Safe Deal transport and signed notification boundary. It does **not** implement the full mixed-recipient Multi-calculation Service or authorize activating it.

## Verified primary contracts

Personally retrieved and read:
- [Safe Deal product, 16 May 2025](https://cdn.tbank.ru/static/documents/bezopasnaya_sdelka.pdf), section 9: NN uses root `CreateDealWithType` or `DealId`; the deal identifier appears as `SpAccumulationId` in signed notifications. Deal lifetime is contractual. With an earlier payout, expiry closes the deal and transfers its remaining balance to the platform; without payouts, payments are cancelled.
- [EACQ Safe Deal, 18 September 2025](https://cdn.tbank.ru/static/documents/oplata_bezopasnaya_sdelka.pdf), sections 2.3, 2.10, 2.11 and 4.2: Init/GetState/CheckOrder/Confirm/Cancel, `ExternalRequestId` deduplication for Cancel, notification signature and HTTP 200 `OK` acknowledgement. `AUTHORIZED` is a card hold, not a seller payout or completed fulfillment.
- [Signature algorithm](https://developer.tbank.ru/eacq/intro/developer/token): root scalar fields only, add Password, sort by field name, concatenate values, SHA-256 UTF-8; nested objects/arrays are not signed.
- [A2C Safe Deal payout protocol](https://cdn.tbank.ru/static/documents/vyplata_bezopasnaya_sdelka.pdf) is a distinct payout contract. This slice does not invent the missing association between an NN deal and a delayed payout to a legal entity/sole trader.

The legacy acdn.tinkoff.ru download failed local certificate validation; the same named official document was retrieved from cdn.tbank.ru with TLS validation enabled. No certificate checks were disabled. API authentication and payment methods were not called.

## Implementation boundary and interfaces

Create `open_marketplace/payments/tbank.py` and `payments/tests/test_tbank.py`; do not wire routes or modify active settings. Use only Python stdlib. The author remains the leading Hermes model. These tests are local HTTP protocol fixtures, not evidence of bank acceptance.

- `TBankClient(terminal_key=..., password=..., environment=..., live_enabled=False, timeout=15)` accepts only explicit `sandbox`/`production`. Production requires `live_enabled=True`. `from_environment()` reads TBANK_ENVIRONMENT, TBANK_TERMINAL_KEY, TBANK_PASSWORD and exact TBANK_LIVE_ENABLED=true. Missing configuration fails before networking. No default terminal, demo credentials or fallback origin.
- `create_deal(deal_type)` permits the documented N1/1N/NN; `initialize_payment(payload)` requires positive integer kopecks (at least 100), explicit Currency=643, PayType=T and either a valid DealId or root CreateDealWithType=NN, not both. It does not supply shipping prices, taxes, payout recipients, receipts or deadlines on behalf of the application. Application-supplied return/notification URLs and expiry must be explicit in payload; financial/fiscal onboarding remains a launch gate.
- `get_payment(payment_id)`, `check_order(order_id)`, `confirm_payment(payment_id, amount)`, `cancel_payment(payment_id, amount, operation_id)` call the documented endpoints once. Cancel requires a stable nonempty ExternalRequestId; no automatic retry, deal closing or payout is implemented. A timeout or ambiguous mutation response raises TBankUnknownResult, never 'failed/no charge'.
- Never follow HTTP redirects, log credentials/request/response bodies, or include them in exception text/chains. Bound socket timeout and response reads (2 MiB adapter resource ceiling). Reject nonfinite JSON and malformed/non-object replies.
- `signature(payload, password)` implements the published Token algorithm without mutating input; root Token is excluded, root Password is rejected, JSON booleans become lowercase, optional nested objects/arrays are excluded. Unsupported root scalars fail closed.
- `verify_notification(raw, terminal_key, password, expected_order_id, expected_payment_id, expected_amount, expected_deal_id)` strictly parses an object, rejects duplicate keys/nonfinite numbers, verifies Token in constant time and validates the persisted local identity bindings. AUTHORIZED/CONFIRMED amounts equal the stored amount; cancellation/refund notifications may have a reduced current amount, never above the original. Preserve status and success without granting access or settling stock. Return only the payment/order/deal IDs, status, success and current amount, excluding card data. Limit a notification to 64 KiB as an explicit local resource bound.

## Verification plan

1. Write missing-feature tests and run `python -m unittest open_marketplace.payments.tests.test_tbank -v`, recording the failing result.
2. Implement only the above documented operations, then exercise real HTTP requests against a loopback ThreadingHTTPServer. Generate test secrets at runtime. Verify exact paths/payloads, NN fields, boolean signatures, order/amount/deal mismatches, partial refund notices, duplicate JSON keys, redirect refusal, HTTP/network errors, no retry, and fail-closed live settings.
3. Run new tests and the complete Django/contract/migration suite. Do not announce payment, payout, delivery, or digital fulfillment as complete from an adapter test.

## Required before integration or activation

Bank-confirmed Multi-calculation contracts for all approved seller legal forms, recipient onboarding, fiscal receipt responsibilities, deal lifetime and close/expiry policy, payout reconciliation/idempotency, commission allocation, cancellation/refund coordination, access to test terminals, authoritative reconciliation after uncertain results, persistent webhook deduplication, account-level authorization, inventory expiry handling and private-file revocation. These are not supplied by a SuccessURL or a valid signature alone.
