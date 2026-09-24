# OptiGo frontend smoke-test evidence

The frontend was built as a static VS Code project and uses the backend session cookie and API; it does not use demo objects or local shipment arrays. The API smoke run completed against the live database with:

- `GET /health/live` → `200`.
- `GET /health/ready` → `200`, database `seneca_phase3`.
- `GET /api/track/OBUTRK000001` → `200`, status `DELIVERED`, real history and `OBULOC` location IDs.
- `POST /api/auth/register` → `201`, generated `OBUUSR` and `OBUCUS` IDs.
- `POST /api/auth/login` → `200`, session account returned.
- OptiGo browser registration → succeeded; follow-up login from a new API session returned `200` for the created account `OBUUSR243910` / `OBUCUS773111`.
- `POST /api/shipments` → `201`, generated `OBUSHP885243`, `OBUTRK292210`, origin/destination `OBUADR` IDs, `BOOKED` history and live pricing charge `INR 91.25`.
- `GET /api/shipments` in the authenticated session → `200`, the newly booked OBU shipment was returned.
- Customer access to staff-only reports is denied by the backend role guard (`403`).

The smoke account and booking are valid OBU records created specifically to verify the requested registration/booking path; they were not used as replacement database seed data. Existing database records were not overwritten.
