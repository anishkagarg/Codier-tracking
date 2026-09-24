# Live smoke-test evidence

Executed on 24 September 2026 against the existing PostgreSQL database `seneca_phase3`.

## Database verification

`scripts/live_smoke.py` completed read-only with 17 operational tables present and no missing tables. The live database returned real records, including `OBUTRK000001` and the following counts:

| Area | Rows |
|---|---:|
| users / customers / staff | 195,363 / 195,354 / 9 |
| addresses | 201,794 |
| shipments / shipment history | 149,070 / 494,463 |
| assignments | 298,140 |
| location updates | 494,463 |
| warehouse scans | 98,765 |
| delivery OTPs / proof of delivery | 146,107 / 146,107 |
| invoices / payments | 149,070 / 149,067 |
| COD collections | 14,872 |

## HTTP and integration verification

- `GET /health/live` → `200`.
- `GET /health/ready` → `200`, database `seneca_phase3`.
- `GET /api/track/OBUTRK000001` → `200`, real `DELIVERED` history and `OBULOC` locations.
- Registration → `201`, generated readable `OBUUSR` and `OBUCUS` IDs.
- Login → `200`, signed session cookie and customer account returned.
- Registration persistence → the newly created account `OBUUSR243910` / `OBUCUS773111` logged in successfully again through a separate API session.
- Customer booking → `201`, generated `OBUSHP885243`, `OBUTRK292210`, two `OBUADR` IDs, initial `BOOKED` history, and live pricing charge `INR 91.25`.
- Authenticated shipment list → `200`, the newly created booking returned.
- Customer request to `GET /api/reports/summary` → `403`, confirming staff-only authorization.
- Browser frontend login → successful; dashboard displayed the real booking and live service indicator.
- Browser frontend tracking → successful; `OBUTRK000001` displayed the real delivered timeline.
- Browser runtime error log → empty during the smoke flow.

The smoke account and booking are deliberately retained as valid test records so the integration can be inspected in PostgreSQL. They are not seed data and no existing database record was overwritten.
