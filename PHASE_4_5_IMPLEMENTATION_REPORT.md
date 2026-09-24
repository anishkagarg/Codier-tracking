# OptiGo Phase 4 and Phase 5 Implementation Report

## 1. Project identity

The Phase 3 backend has been integrated and branded as **OptiGo**.

The deliverable is the `OptiGo_Integration` folder:

- `backend/` — FastAPI, SQLAlchemy and PostgreSQL integration.
- `frontend/` — responsive static OptiGo interface.
- `backend/.env` — local PostgreSQL connection configuration; excluded from version control.

The existing PostgreSQL database name `seneca_phase3` is retained only as the compatibility name of the supplied database. The application, API title, interface and documentation use OptiGo.

## 2. Phase 4 — Backend Development

Phase 4 implements the server-side business logic and protected APIs required by the project plan:

| Capability | Implementation |
|---|---|
| Authentication and authorization | Registration, login, logout, signed sessions and role gates |
| Shipment booking | Address creation, pricing-rule calculation, invoice creation and unique tracking ID |
| Tracking | Public privacy-safe tracking and authenticated shipment history |
| Status management | Atomic status transitions, location updates and status history |
| Delivery operations | Pickup, assignment, delivery start, delivery failure and OTP proof of delivery |
| Notifications | In-app notifications generated for booking and shipment-status changes, with read action |
| Complaints | Customer complaint submission and protected support/manager resolution workflow |
| Reports | Shipment status, invoice totals and average delivery summaries |
| Operations | Staff, hub, route, vehicle and warehouse-scan APIs |

## 3. Phase 5 — Frontend Development

Phase 5 implements the connected OptiGo user interface:

- Login and customer registration.
- Customer dashboard and shipment history.
- Shipment booking with backend-generated charge and tracking ID.
- Public shipment tracking and timeline.
- Delivery-agent task queue with pickup, delivery, OTP and failure actions.
- Staff assignment, reports, warehouse and finance views.
- Customer notifications and support/complaints.
- Role-aware navigation, empty states, error states and responsive layout.

The frontend calls `http://127.0.0.1:8000` with session credentials, and the backend allows the configured frontend origins through CORS.

## 4. PostgreSQL connection

The local backend `.env` is configured for the supplied PostgreSQL database. The password is intentionally not repeated in this report.

The connection was verified on 24 September 2026:

- Database connection: successful.
- Current database: `seneca_phase3`.
- Current database user: `postgres`.
- Account lookup: `kavya.nair@gmail.com` found as `OBUUSR000005`.
- OptiGo `/health/live`: HTTP 200.
- OptiGo `/health/ready`: HTTP 200.
- OptiGo application login for the supplied Kavya account: HTTP 200.

## 5. Run instructions

Backend:

```powershell
cd backend
py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend, in a second terminal:

```powershell
cd frontend
py -3 -m http.server 5173
```

Open `http://127.0.0.1:5173`.

## 6. Security note

The PostgreSQL password is stored only in the local ignored `.env` file and is not included in this report, frontend files or API responses. Replace the local session secret before sharing the project or deploying it.
