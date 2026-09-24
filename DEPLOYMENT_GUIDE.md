# OptiGo Deployment Guide

## Local deployment

### Prerequisites

- Python 3.12 or newer.
- PostgreSQL running locally with the supplied OptiGo-compatible database.
- A browser.

### Backend

From the `backend` directory:

```powershell
py -3 -m pip install -r requirements.txt
Copy-Item .env.example .env
# Set DATABASE_URL and SESSION_SECRET in .env.
py -3 -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The configured local `.env` is intentionally excluded from ZIP files because it contains a database secret.

### Frontend

From the `frontend` directory, in a second terminal:

```powershell
py -3 -m http.server 5173
```

Open `http://127.0.0.1:5173`.

## Deployment verification

Run from `backend`:

```powershell
py -3 scripts/phase7_checks.py
```

The script validates PostgreSQL readiness, account presence, API routes, authentication primitives and public tracking.

## Production checklist

- Use a dedicated least-privilege PostgreSQL role.
- Store `DATABASE_URL` and `SESSION_SECRET` in the deployment secret manager.
- Set `COOKIE_SECURE=true` behind HTTPS.
- Restrict `FRONTEND_ORIGINS` to the deployed frontend origin.
- Add CSRF protection, rate limiting, structured logging, backups and restore testing.
- Serve the frontend through a production web server instead of Python’s development server.
- Configure external email/SMS notification providers only after their credentials and consent rules are approved.
