# Fulfillment lifecycle boundary

This slice adds local state transitions for a previously planned physical shipment:

- `pending -> ready` is a seller operation;
- seller-arranged delivery may continue `ready -> in_transit`;
- `in_transit -> delivered` is a buyer receipt confirmation;
- CDEK `in_transit` and `delivered` transitions remain provider-driven and are rejected here.

Every accepted transition appends one event. Repeating the current state is idempotent. Skips, reversals, foreign actors, and cross-seller operations are rejected. No provider request, address update, waybill creation, payout, refund, or file delivery is performed.
