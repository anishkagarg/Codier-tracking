# OptiGo integration project

This folder is the canonical combined project for the Mini Project location.

- `backend` is the OptiGo FastAPI service. The configured PostgreSQL database is retained as the source of truth (`seneca_phase3` in the current local setup).
- `frontend` is the delivered OptiGo static frontend. Local development uses `http://127.0.0.1:8000`; GitHub Pages receives its API URL from the `OPTIGO_API_BASE` repository variable.
- Phase 4 includes authentication/RBAC, booking, tracking, status history, assignments, OTP delivery proof, reports, warehouse scans, an operational accounts workbench, in-app notifications and complaints.
- Phase 5 includes role-aware dashboards, booking, shipment history, public tracking, task operations, notifications and support/complaint screens.
- Phase 6 includes transparent schedule-based delay assessment; Phase 7 includes repeatable PostgreSQL-backed validation in `backend/scripts/phase7_checks.py`.
- The academic phase labels below describe the project history; the product and user interface are branded OptiGo. Enhancements include browser GPS sharing, no-cost route optimization, rule-based delivery prediction, optional SMTP email transport and Razorpay Test Mode. Simulated online payment is disabled unless explicitly enabled for a local/demo environment.
- Phase 8 documentation is in `DEPLOYMENT_GUIDE.md`, `USER_MANUAL.md`, `PRESENTATION_OUTLINE.md` and `FINAL_PROJECT_AUDIT.md`.

## Run in VS Code

Backend terminal (Windows PowerShell; install and run with the same virtual-environment interpreter):

```powershell
cd backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Set DATABASE_URL and replace SESSION_SECRET with a unique random value of at least 32 characters.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Keep the backend running. Start the separate frontend server in a second terminal:

```powershell
cd frontend
py -3 -m http.server 5173
```

Open `http://127.0.0.1:5173`. Login and registration use the FastAPI session API. The service fails at startup if its database URL or session secret is missing or unsafe. Simulated checkout is disabled by default; enable `DEMO_ONLINE_ENABLED=true` only with `OPTIGO_ENV=demo` (or local development), never in production.

## Tests

From `backend`, run unit tests with `python -m pytest -q`. GitHub Actions also runs the PostgreSQL lifecycle tests against a fresh `optigo_test` database. Its fixture script refuses non-PostgreSQL URLs, database names without the `_test` suffix, and non-empty databases; never point it at `seneca_phase3`.
