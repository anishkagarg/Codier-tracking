# OptiGo API documentation

All JSON endpoints use a signed session cookie. Login first, then send the cookie with `credentials: include` from the frontend.

| Method | Path | Access | Purpose |
|---|---|---|---|
| GET | `/health/live` | Public | Process health |
| GET | `/health/ready` | Public | PostgreSQL readiness |
| POST | `/api/auth/register` | Public | Create customer account |
| POST | `/api/auth/login` | Public | Start session |
| POST | `/api/auth/logout` | Authenticated | End session |
| GET | `/api/auth/me` | Public | Current account projection |
| GET | `/api/notifications` | Authenticated | Customer notifications or staff notification overview |
| POST | `/api/notifications/{id}/read` | Owner/staff | Mark an in-app notification as read |
| GET | `/api/complaints` | Customer/support staff | List owned or operational complaints |
| POST | `/api/complaints` | Customer | Submit a shipment-linked or general complaint |
| PATCH | `/api/complaints/{id}` | Support/manager/admin | Change complaint status and resolution owner |
| GET | `/api/dashboard` | Authenticated | Role-aware metrics and recent records |
| GET/POST | `/api/addresses` | Customer | Read/create saved addresses |
| GET | `/api/locations/cities` | Public | List cities for an Indian state |
| GET | `/api/locations/post-offices` | Public | Find post-office areas and PINs for a city/state |
| POST | `/api/pricing/quote` | Authenticated | Quote the current shipping charge before booking |
| GET | `/api/payments/options` | Authenticated | Whether Razorpay test checkout is configured |
| GET | `/api/finance/invoices` | Accounts/manager/admin | Recent invoices with payment and cash-due status |
| GET | `/api/shipments` | Authenticated | Customer-owned or staff operational search |
| POST | `/api/shipments` | Customer | Create shipment, addresses, initial history and invoice; requires `Idempotency-Key` header |
| GET | `/api/shipments/{shipment_id}` | Owner/staff | Private shipment detail |
| GET | `/api/shipments/{shipment_id}/assessment` | Owner/staff | Rule-based ETA and delay assessment |
| GET | `/api/track/{tracking_id}` | Public | Current status and safe timeline |
| GET | `/api/tasks` | Staff | Assigned task list |
| POST | `/api/assignments` | Manager/admin/booking/warehouse | Assign pickup, delivery or warehouse task |
| POST | `/api/assignments/{id}/pickup-complete` | Assigned agent | Complete pickup |
| POST | `/api/assignments/{id}/pickup-failed` | Assigned agent | Fail pickup with reason |
| POST | `/api/assignments/{id}/start-delivery` | Assigned agent/manager | Set shipment Out for Delivery |
| POST | `/api/assignments/{id}/otp` | Assigned delivery agent | Issue short-lived OTP challenge |
| POST | `/api/assignments/{id}/deliver` | Assigned delivery agent | Verify OTP and create proof of delivery |
| POST | `/api/assignments/{id}/delivery-failed` | Assigned delivery agent/manager | Record failed delivery |
| POST | `/api/shipments/{id}/locations` | Staff | Record internal location observation |
| GET | `/api/reports/summary` | Staff | Live status and financial summary |
| GET | `/api/reports/delays` | Staff | Active shipments past their stored expected-delivery date |
| GET | `/api/operations/lookups` | Operations roles | Staff, hubs, routes and vehicles |
| GET | `/api/warehouse/scans` | Warehouse/manager/admin | Live warehouse scan records |
| POST | `/api/warehouse/scans` | Warehouse/manager/admin | Record a scan against a live shipment and active hub |
| GET | `/api/finance/summary` | Accounts/manager/admin | Invoice/payment/refund totals |
| POST | `/api/shipments/{id}/locations` | Staff | Record manual or browser GPS location |
| GET | `/api/shipments/{id}/locations/latest` | Owner/staff | Read latest GPS coordinate |
| POST | `/api/routes/optimize` | Operations staff | No-cost Haversine nearest-neighbour route ordering |
| POST | `/api/payments/razorpay/order` | Owner/staff | Create Razorpay Test Mode order or local fallback |
| POST | `/api/payments/razorpay/verify` | Owner/staff | Verify Razorpay signature and mark invoice paid |

## Booking request

```json
{
  "sender": {"line1":"1 Main Road","city":"Mumbai","state":"MH","postal_code":"400001","country":"IN","contact_name":"Sender","contact_phone":"9000000000"},
  "receiver": {"line1":"2 Market Road","city":"Pune","state":"MH","postal_code":"411001","country":"IN","contact_name":"Receiver","contact_phone":"9000000001"},
  "weight_kg": 1.25,
  "length_cm": 20,
  "width_cm": 15,
  "height_cm": 10,
  "delivery_type_code":"STANDARD",
  "destination_zone":"LOCAL",
  "fragile":false,
  "priority":false,
  "payment_mode":"CASH"
}
```

The `Idempotency-Key` header must remain the same for retries of one booking attempt. Reusing it returns HTTP 409 with the original tracking ID instead of creating another shipment. The response includes a database-generated OBU tracking ID, charge, invoice total, current status `BOOKED`, and the initial status history event. `payment_mode` is `CASH` (cash on delivery; the amount due is derived from the shipping charge) or `RAZORPAY` (online checkout). The customer-facing form does not submit a COD amount or parcel type.

New bookings create a pickup assignment. Completing pickup creates a warehouse assignment; recording its `RECEIVED` scan moves the shipment to `IN_TRANSIT` and creates a delivery assignment. The delivery agent starts delivery, requests an OTP (stored in PostgreSQL and shown in the customer's Notifications), and verifies it at handover. Cash bookings require explicit cash-collection confirmation before delivery; the payment and invoice are then updated together. Existing unassigned bookings are not silently backfilled.

Razorpay test mode requires configured `rzp_test_` keys. Without them, online checkout is disabled; a local simulation cannot mark an invoice paid. Verification checks the Checkout signature and fetches the Razorpay order and payment to confirm the invoice receipt, amount, currency, and captured status before updating payment records.

`POST /api/pricing/quote` accepts `weight_kg`, `delivery_type_code`, and `destination_zone` and returns the amount/currency from the same active rate calculation used by booking.

## Privacy boundary

Public tracking excludes sender/receiver contacts, staff identities, OTP values, proof references, payment data and refund data. Private address and finance projections are returned only after ownership or staff authorization checks.
