# Buyer commerce cart

## Scope

Add a production-oriented buyer cart that is separate from `demo_orders`.
It may create a durable `CommerceOrder` and inventory reservation locally, but
it must not call payment/shipping providers or claim that payment occurred.

## Invariants

- A cart belongs to exactly one authenticated ordinary buyer.
- A cart line stores a server-confirmed catalog snapshot and decimal quantities as strings.
- Add/update revalidates the published physical offer and available stock.
- Checkout revalidates every line and uses the cart intent as the durable order intent.
- One multi-seller cart creates one durable order; fulfillment groups it later by seller.
- Replaying a completed cart intent returns the same order and creates no second reservation.
- A stale intent, changed price, unavailable offer, duplicate field, or foreign cart is rejected.
- The demo cart and demo order feature flag remain untouched.

## Explicit non-goals

- No payment provider call or hosted checkout URL.
- No shipping quote or shipment creation.
- No address, digital delivery, payout, refund, or browser UI in this slice.
