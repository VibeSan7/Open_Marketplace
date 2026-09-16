# Real commerce: implementation and activation boundary

Status: **incomplete local foundation, not a release or an operational commerce feature**.

The owner approved T-Bank Multi-calculation, CDEK plus seller-arranged delivery, and versioned private digital-file delivery. This approves development, not account changes, contracts, real payments, shipments, external deployment, or publication of this branch.

## Implemented locally

- Physical inventory reservations, immutable purchase snapshots, stock allocation across storage locations, request replay protection, and atomic commit/release.
- PostgreSQL row locks and database constraints protecting the final available item, stock edits and terminal reservation transitions.
- Availability views based on on-hand minus reserved quantities. Existing demo inventory remains separate.
- Durable physical multi-seller order records with immutable reservation snapshots, buyer-scoped replay/cancellation, and atomic order events.
- A provider-independent payment intent/event ledger that accepts only normalized verified T-Bank notifications, deduplicates callbacks, commits stock on `CONFIRMED`, and releases pre-payment reservations on rejection/reversal.
- A provider-independent physical fulfillment plan: one immutable pending shipment snapshot per seller for a paid order, explicit `cdek` or seller-arranged delivery mode, provider-safe client reference, and a local seller-arranged lifecycle through buyer receipt confirmation. It does not call CDEK or claim carrier evidence.
- An EACQ **Safe Deal** protocol adapter for the documented creation/initiation/status/confirmation/cancellation operations, signed notifications, order/payment/deal/amount binding, and uncertain-outcome handling. This is not a full mixed-recipient Multi-calculation integration.
- A [CDEK protocol adapter](cdek-client.md) for OAuth, tariff calculation, shipment creation/read/delete and conservative parsing of async/tracking responses.
- Both clients fail closed without explicit configuration and separate production enablement. Neither is invoked by web routes, startup hooks or the demo checkout.

## Not implemented

- The real multi-seller order/payment coordinator, durable provider intents and reconciliation jobs, payout ledger, refunds by order line, fiscalization, recipient onboarding and permissioned operational controls.
- Address forms, package data, CDEK courier pickup/refusal/returns, verified CDEK lifecycle events, and browser screens for shipment operations. Seller-arranged lifecycle transitions and buyer receipt confirmation exist only in the internal service boundary; they do not create carrier evidence.
- Private digital upload/scanning/version retention, paid-order entitlement creation, protected downloads and entitlement revocation. Existing catalog photos are not a digital-delivery system.
- End-to-end real-commerce browser flows, authenticated provider sandbox checks, real bank/delivery operations or a production migration/deployment.

No test count in this branch changes these limits. Existing release/demo claims must not be rewritten as though these features were already available.

## T-Bank sources personally checked

- [Safe Deal product description, 2025-05-16](https://cdn.tbank.ru/static/documents/bezopasnaya_sdelka.pdf), particularly sections 8–11: N:N identity, notification signature, deadlines, deal creation and closure.
- [EACQ Safe Deal protocol, 2025-09-18](https://cdn.tbank.ru/static/documents/oplata_bezopasnaya_sdelka.pdf), particularly Init, Confirm, Cancel, GetState, CheckOrder and HTTP notifications.
- [A2C_V2 Safe Deal protocol, 2025-09-03](https://cdn.tbank.ru/static/documents/vyplata_bezopasnaya_sdelka.pdf): card/SBP payout transport and its required configuration.
- [Token algorithm](https://developer.tbank.ru/eacq/intro/developer/token): sorted primitive root values, nested structures excluded, terminal password supplied locally, SHA-256.
- [Nominal accounts](https://developer.tbank.ru/docs/products/nominal): a separately documented beneficiary/billing/deal integration with its own permissions and mTLS certificate. The page warns that operations through other payment methods or the personal account break its billing logic.

Public bank documentation exists. It would be incorrect to claim that all documentation is available only from a manager. Equally, these sources do not justify silently combining EACQ Safe Deal, nominal-account billing, ordinary account transfers, and marketplace `Shops` into one supported Multi-calculation contract.

`CONFIRMED` is the buyer charge, not a seller payout. Closing an N:N deal can direct its remaining balance to the platform. Contractual expiration is not unlimited escrow: the public N:N description distinguishes the no-payout case from the case in which a payout has already occurred. There is deliberately no automatic payout or deal-closing implementation here.

## Exact provider information still needed

Obtain the contract-specific integration package or written technical confirmation for the chosen Multi-calculation arrangement, covering:

1. Which bank product/API combination is approved for this marketplace, including the exact connection between hosted buyer payment, held deal funds and delayed payouts to legal entities, sole traders and other supported seller categories.
2. Required recipient onboarding/checks, payout endpoints and fields, supported signature/authentication modes, and fiscal/receipt obligations.
3. How to reconcile a payout or deal creation when its response was lost, including actual provider idempotency guarantees and lookup keys. An `OrderId` alone does not establish a guarantee.
4. Deal/hold deadlines and consequences after partial payouts, refund funding and commission rules. Platform leftovers must not be accepted as revenue by an invented default.
5. Test terminal access and any IP allowlisting. Sandbox access and real activation are separate from approving the provider direction.

This is a provider-contract gap, not a request to choose the bank again. Do not work around it with ordinary acquiring, an unrelated transfer API, test secrets, simulated successful payments, or an unapproved switch to nominal accounts.

## Configuration and continuation

`.env.example` contains names only, with empty credentials and false production flags. Never copy secrets into documentation, logs, fixtures, source code, comments or model prompts. Do not enable these variables on the running demo as a shortcut to integration.

After the provider contract is settled, finish the application coordinator and persistence before exposing checkout or granting file access. A signed notification is one authenticated message, not an idempotent payment ledger; processing must prevent stale notifications from resurrecting refunded/cancelled purchases. An uncertain payment result must be reconciled before releasing stock. Retain the exact bought file version and revoke access according to the implemented refund state, not a browser redirect.

Keep this foundation local and preserve the existing public demo until the missing work and verification are complete. Test evidence is recorded separately; it proves only the exercised local behavior.
