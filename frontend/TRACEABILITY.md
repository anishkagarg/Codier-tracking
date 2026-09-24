# Phase 2 → OptiGo frontend traceability

| Phase 2 use case | Screen | Live API integration |
|---|---|---|
| B1–B6 booking and receipt | New booking | `POST /api/shipments` returns OBU tracking ID, charge, expected delivery and invoice-backed confirmation |
| B7/T3 shipment search | Shipments and Track shipment | `GET /api/shipments`, `GET /api/track/{tracking_id}` |
| P1–P3 pickup work | My tasks | `GET /api/tasks`, pickup completion/failure actions |
| P4–P6 delivery work | My tasks | start delivery, OTP request and proof verification endpoints |
| P7 manager assignment | Assignments | `GET /api/operations/lookups`, `POST /api/assignments` |
| T1/T2 location and history | Track shipment/private shipment detail | API timeline and OBU location IDs |
| T4 reports | Reports | `GET /api/reports/summary` |
| W1/W5 warehouse | Warehouse | `GET /api/warehouse/scans` |
| A1–A5 accounts | Finance | `GET /api/finance/summary` |
| Customer notifications | Notifications | `GET /api/notifications`, `POST /api/notifications/{id}/read` |
| Customer complaints / staff handling | Support & complaints | `GET/POST /api/complaints`, `PATCH /api/complaints/{id}` |
| RBAC | Role-aware navigation and API errors | `/api/auth/me` plus backend role gates |
