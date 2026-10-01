# OptiGo — FastAPI Backend

This folder contains the OptiGo courier tracking backend. It is aligned to the live PostgreSQL database `seneca_phase3`; that database name is retained because it is the actual configured PostgreSQL source.

## Source-of-truth decision

The ORM models were checked against the live PostgreSQL catalog on 24 September 2026. IDs are text OBU identifiers such as `OBUUSR000005`, `OBUSTF0004`, `OBUSHP000001`, `OBUTRK000001`, `OBUHUB0001`, and `OBUVEH000001`. No UUID conversion, SQLite replacement, mock production data, or database schema modification is included.

The existing application schema contains 38 operational tables, including users/customers/staff, addresses, shipments/items, shipment history, assignments, hubs/routes/vehicles, warehouse scans, OTP/proof, invoices/payments/refunds, COD, notifications, complaints, and operational observations. OptiGo adds two isolated tables for its append-only finance transaction register and dated balance snapshots; the startup migration creates them without changing existing records. `app/models.py` maps the existing live column names and PostgreSQL types exactly for the original domains.

## Run in VS Code

1. Open this folder in VS Code.
2. Create and activate a virtual environment.
3. Install dependencies: `python -m pip install -r requirements.txt`.
4. Copy `.env.example` to `.env` and set the PostgreSQL password and a strong `SESSION_SECRET`.
5. Do not run a schema migration: the existing PostgreSQL database is the authority. The `migrations/` folder documents that no schema change is required.
6. Start the API from this folder:

```powershell
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Open Swagger at `http://127.0.0.1:8000/docs`.

## Roles

- Customer: registration, login, addresses, booking, own shipments, tracking and history.
- Administrator / Operations Manager: operational search, assignment, task oversight, reports and finance read access.
- Delivery Agent / Pickup Agent: assigned task view, pickup/delivery status and delivery proof flow.
- Warehouse Officer: warehouse scan and operational lookup access.
- Accounts Officer: invoice/payment review, collection and refund/COD follow-up, append-only expense/other-income entry, and dated balance-sheet asset/liability snapshots.
- Booking, Tracking and Support Officers: role-scoped operational capabilities matching the live lookup rows.

Authentication uses signed server sessions. Passwords are stored as one-way PBKDF2 hashes for new registrations; the verifier also supports existing bcrypt hashes if the `bcrypt` dependency is installed. Password hashes and OTP hashes are never returned by the API.

## Main API groups

- `/api/auth/*` — registration, login, logout and current account.
- `/api/notifications` and `/api/complaints` — in-app shipment updates, customer support requests and staff resolution workflow.
- `/api/shipments/*/assessment` and `/api/reports/delays` — transparent schedule-based delay detection.
- `/api/dashboard`, `/api/addresses`, `/api/shipments` — customer and staff views.
- `/api/track/{tracking_id}` — safe public tracking projection.
- `/api/tasks`, `/api/assignments/*` — staff tasks, pickup, delivery, OTP and failure handling.
- `/api/reports/summary` — status, invoice and delivery-time summary.
- `/api/operations/lookups` — staff, hubs, routes and vehicles.
- `/api/warehouse/scans` — warehouse scan history and live scan creation.
- `/api/finance/workbench` — date-filtered operational P&L, unpaid invoices, COD/refund follow-up and balance-sheet snapshots.
- `/api/finance/transactions` and `/api/finance/positions` — finance/admin-only append operations for documented costs/income and dated asset/liability balances.

Full request and response details are in `API_DOCUMENTATION.md`.

## Tests and smoke evidence

Run automated tests with `python -m pytest -q`. `tests/` covers password hashing, role gates, public tracking privacy, status transition rules and API contract behavior. `scripts/live_smoke.py` runs non-destructive read-only checks against the configured PostgreSQL database and verifies the live schema counts. The live smoke result is recorded in `LIVE_SMOKE_TEST.md`.

## Additive recovery-state table

At startup the service creates the small `admin_recovery_state` table if it is absent. It contains only a one-use recovery latch and does not modify existing users, staff, or operational records. Other live-schema limitations affecting new writes are documented in `LIMITATIONS.md`.

The emergency recovery page is documented in `API_DOCUMENTATION.md`. Configure a high-entropy `ADMIN_RECOVERY_KEY` in Render only when needed, complete recovery once, then remove the environment variable. The persistent database latch prevents reuse even if the environment variable is accidentally left configured.
