# OptiGo — Frontend Integration

This is the VS Code-ready OptiGo frontend connected to the FastAPI backend. It does not contain hard-coded production shipment values. Dashboard metrics, bookings, tracking timelines, tasks, reports, warehouse scans and finance totals are fetched from the real API.

## Visual direction

The layout keeps OptiGo’s focused sidebar + workspace pattern and uses the requested professional palette:

| Purpose | Color |
|---|---|
| Primary / brand | `#034365` |
| Primary hover | `#02354F` |
| Delivered / success | `#6AB073` |
| In transit / accent | `#E58A3A` |
| Delayed / attention | `#D5A327` |
| Failed / cancelled | `#8A1A49` |
| Main background | `#F5F7F9` |
| Cards | `#FFFFFF` |
| Primary text | `#1D2935` |
| Secondary text | `#66737E` |
| Borders | `#DCE3E8` |

## Run locally

1. Start the backend on port 8000.
2. Open this folder in VS Code.
3. Serve the static site on port 5173:

```powershell
python -m http.server 5173
```

4. Open `http://127.0.0.1:5173`.

The frontend sends `credentials: include` and calls `http://127.0.0.1:8000` by default. Set `window.OPTIGO_API_BASE` before `js/app.js` if the API is hosted elsewhere. The backend CORS allow-list must contain the frontend origin.

## Integrated screens

- Login and customer registration.
- Customer overview, real shipment list, booking and private history.
- Customer notifications and shipment-linked/general complaints, plus support-staff complaint resolution.
- Public tracking by OBU tracking ID.
- Rule-based ETA/delay assessment in public tracking and staff reporting.
- Staff task view for pickup, delivery start, OTP request and proof verification.
- Manager/admin assignment screen.
- Role-aware reports, warehouse scans and finance summary.

No passwords, password hashes, OTP hashes or fabricated production metrics are placed in the frontend bundle.
