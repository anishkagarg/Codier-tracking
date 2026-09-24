# Frontend integration test report

- `node --check js/app.js` → passed.
- Static server served `index.html`, CSS and JavaScript successfully at `http://127.0.0.1:5173`.
- Browser login against the live FastAPI session → passed.
- Browser registration and follow-up API login → passed; the account was persisted with OBU user/customer IDs.
- Customer dashboard displayed the real database-backed booking `OBUTRK292210`.
- Tracking view displayed the real delivered timeline for `OBUTRK000001`.
- Browser runtime error log during the smoke flow → empty.
- Staff-only report access was rejected by the backend with `403` for the customer session.
