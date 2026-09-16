# CDEK API v2 protocol adapter

This is a low-level transport and response boundary in `open_marketplace/shipping/cdek.py`, not an end-to-end delivery feature. There are no shipping routes, shipment records, checkout integration, courier pickups, or seller-arranged delivery screens in this slice.

## Contract and configuration

Primary source: [official CDEK OpenAPI v2](https://gateway.cdek.ru/api-cdek-docs/web/docs/merged/file/openapi_api_v2_integration.json), also exposed through [the documentation portal](https://apidoc.cdek.ru/). The implementation was checked against the downloaded document, including the nested DTOs and appendix tables.

- Fixed origins: `https://api.edu.cdek.ru` (sandbox) and `https://api.cdek.ru` (production).
- `from_environment()` reads `CDEK_ENVIRONMENT`, `CDEK_CLIENT_ID`, `CDEK_CLIENT_SECRET`, and `CDEK_LIVE_ENABLED`.
- There is no environment or credential default. Production needs the exact string `true` in the environment factory; direct construction additionally needs `live_enabled=True`.
- Configuring these variables alone does not connect the adapter to checkout. Keep them empty/disabled in the current foundation build. Activation and contracts remain separate approvals.
- Timeouts must be positive and at most 120 seconds; default is 15 seconds. Responses are capped at 2 MiB. These are adapter safety limits.
- OAuth uses the officially documented query parameters at `POST /v2/oauth/token`. The full authentication URL, request headers, credentials and response bodies must never be logged.
- The access token is held only in memory until its monotonic-clock deadline, based on the provider's `expires_in`. A failed order operation is not automatically replayed, including after HTTP 401. Use a separate client per worker; the client is not a shared concurrent token manager.

## Operations

- `calculate_tariff(payload)` — `POST /v2/calculator/tariff`, expected HTTP 200.
- `create_order(payload)` — `POST /v2/orders`, expected HTTP 202.
- `get_order(order_uuid=...)` — `GET /v2/orders/{uuid}`, expected HTTP 200.
- `find_order(number=...)` — `GET /v2/orders?im_number=...`, expected HTTP 200.
- `delete_order(order_uuid=...)` — `DELETE /v2/orders/{uuid}`, expected HTTP 202.

The caller supplies the complete official payload. No sender, cost, tariff, package dimensions, pickup point, destination, payment-on-receipt amount or default financial data is invented. Basic shape, explicit type/currency, mutually exclusive routes, canonical UUIDs, and printable ASCII order-number boundaries are enforced. The caller still owns complete domestic/international field validation and the contract-specific business rules.

**Currency is provider-specific.** CDEK appendix 14 uses request currency `1` for RUB and returns `RUB`. Do not copy T-Bank's ISO numeric `643` into a CDEK tariff request. `delivery_sum` is not a substitute for the documented tax-inclusive `total_sum`; neither should be treated as an approved buyer charge without application-level validation.

A CDEK type `2` order is still transported by CDEK. It does not implement seller-arranged delivery. Creating an order with a door origin does not request a courier; that is a separate API workflow and is not implemented here.

## Response safety

- HTTP 202 and `ACCEPTED`/`WAITING` only mean processing is pending. They never mean a shipment has been successfully created or delivered.
- CREATE requires a valid entity UUID and uniquely identifiable CREATE request metadata. DELETE verifies DELETE metadata and any returned entity identity.
- `request_state(response, operation=..., request_uuid=...)` selects the intended operation rather than an unrelated successful GET or a historical failed UPDATE. Ambiguous metadata is rejected.
- GET-by-UUID and GET-by-number verify the returned identity.
- `delivery_status(response, expected_uuid=..., expected_number=...)` checks both identifiers, validates timestamps and `deleted` booleans, ignores deleted statuses, and returns the newest unambiguous active status code. It has no money or fulfillment side effect.
- A tracking response is not a signed delivery document. CDEK's photo-document workflow requires its own service/contract and is not implemented.
- Redirects are not followed. Duplicate JSON object keys, non-finite JSON literals, oversized content, broken HTTP bodies and malformed bearer tokens are rejected.
- Errors remain errors. An unknown mutation outcome must not release inventory, declare failure, or trigger a replacement shipment. Reconcile first by stored UUID or the original client number and compare shipment data.
- CDEK permits reuse of old client numbers after terminal shipment states. A client number is not a universal idempotency key; this adapter does not invent retry guarantees or silently truncate identifiers.

## Evidence boundary

The tests use an actual local `ThreadingHTTPServer` on `127.0.0.1` and random unprivileged ports, with clearly artificial protocol fixtures. They exercise serialization, OAuth caching, HTTP methods and paths, unknown outcomes, response identity, async request selection, status deletion, configuration gates, size/timeout bounds and credential-safe errors. They are **not** evidence that CDEK accepted a shipment, validated real addresses, applied a contract tariff or delivered a parcel.

See [commerce readiness](commerce-readiness.md) for the remaining integration and activation work.
