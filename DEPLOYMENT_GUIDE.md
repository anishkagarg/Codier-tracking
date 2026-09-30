# OptiGo Deployment Guide

## Local deployment

### Prerequisites

- Python 3.12.
- PostgreSQL running locally with the supplied OptiGo-compatible database.
- A browser.

### Backend

From the `backend` directory:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
# Set DATABASE_URL and replace SESSION_SECRET with a unique random value of at least 32 characters.
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The configured local `.env` is intentionally excluded from ZIP files because it contains a database secret.

### Frontend

From the `frontend` directory, in a second terminal:

```powershell
py -3 -m http.server 5173
```

Open `http://127.0.0.1:5173`.

## Free hosted deployment

The repository includes `render.yaml` for a Render FastAPI web service. Create a PostgreSQL project, restore the supplied schema/data into it, then create the Render service from the repository. Set `DATABASE_URL` to the database connection string; the other deployment variables are defined in `render.yaml`. Set the GitHub repository variable `OPTIGO_API_BASE` to the exact HTTPS URL of the Render service. The Pages build writes it into `config.js`, rather than embedding the host in the HTML. The workflow default is `https://optigo-api.onrender.com`; replace it if your service has another hostname. Keep `OPTIGO_ENV=production`, `COOKIE_SECURE=true`, a generated `SESSION_SECRET`, and `DEMO_ONLINE_ENABLED=false` on Render.

Free hosting has limitations: Render free services sleep after inactivity and Neon free projects have quotas. This is suitable for a student demonstration, not production-critical workloads.

## Deployment verification

Run from `backend`:

```powershell
py -3 scripts/phase7_checks.py
```

The script validates PostgreSQL readiness, account presence, API routes, authentication primitives and public tracking. CI additionally runs the booking → pickup → warehouse → delivery → OTP → COD lifecycle against a disposable PostgreSQL 16 database that is destroyed with the job. Do not run the fixture or opt the workflow tests into `seneca_phase3`.

## Production checklist

- Use a dedicated least-privilege PostgreSQL role.
- Store `DATABASE_URL` and `SESSION_SECRET` in the deployment secret manager.
- Set `COOKIE_SECURE=true` behind HTTPS.
- Restrict `FRONTEND_ORIGINS` to the deployed frontend origin.
- Set the GitHub Actions repository variable `OPTIGO_API_BASE`; verify `/health/live`, `/health/ready`, credentialed CORS preflight, and read-only tracking before calling a release healthy.
- Keep Razorpay on `rzp_test_` credentials while `RAZORPAY_MODE=test`; simulated checkout cannot be enabled in production.
- Add CSRF protection, rate limiting, structured logging, backups and restore testing.
- Serve the frontend through a production web server instead of Python’s development server.
- Configure external email/SMS notification providers only after their credentials and consent rules are approved.
