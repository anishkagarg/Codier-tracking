# OptiGo integration project

This folder is the canonical combined project for the Mini Project location.

- `backend` is the rebuilt FastAPI service connected to PostgreSQL database `seneca_phase3`.
- `frontend` is the delivered OptiGo static frontend and is connected to `http://127.0.0.1:8000` by default.
- Phase 4 includes authentication/RBAC, booking, tracking, status history, assignments, OTP delivery proof, reports, warehouse scans, finance summaries, in-app notifications and complaints.
- Phase 5 includes role-aware dashboards, booking, shipment history, public tracking, task operations, notifications and support/complaint screens.
- Phase 6 includes transparent schedule-based delay assessment; Phase 7 includes repeatable PostgreSQL-backed validation in `backend/scripts/phase7_checks.py`.
- Phase 6 enhancements include browser GPS sharing, no-cost route optimization, rule-based delivery prediction, optional SMTP email transport and Razorpay Test Mode with a local no-cost fallback. Hosting remains intentionally deferred.
- Phase 8 documentation is in `DEPLOYMENT_GUIDE.md`, `USER_MANUAL.md`, `PRESENTATION_OUTLINE.md` and `FINAL_PROJECT_AUDIT.md`.

## Run in VS Code

Backend terminal:

```powershell
cd backend
Copy-Item .env.example .env
# Set DATABASE_URL to the real PostgreSQL seneca_phase3 connection and set SESSION_SECRET
py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Frontend terminal:

```powershell
cd frontend
py -3 -m http.server 5173
```

Open `http://127.0.0.1:5173`. Login and registration use the FastAPI session API. A successful registration is committed to PostgreSQL and returns readable OBU user/customer IDs.
