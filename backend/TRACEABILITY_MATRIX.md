# Phase 2 → OptiGo backend traceability matrix

| ID | Requirement | Backend implementation | Evidence |
|---|---|---|---|
| B1 | Create booking | `create_booking`, `POST /api/shipments` | `test_backend.py`, live schema read |
| B2 | Sender/receiver details | `Address`, origin/destination rows | booking contract test |
| B3/A6 | Parcel details and automatic charge | `PricingRule`, `price_for_weight` | booking response charge |
| B4 | Unique tracking number | `OBUTRK` generator plus live unique key | booking service |
| B5 | Standard/express/same-day | `delivery_types`, `delivery_type_code` | booking validation |
| B6 | Receipt/invoice record | `Invoice` created with booking | invoice query |
| B7/T3 | Search bookings/tracking ID | `/api/shipments`, `/api/track/{tracking_id}` | customer ownership and public tests |
| P1/P2/P3 | Pickup task/address/status | assignments, task routes, private shipment view | role tests |
| P4/P5 | Delivery task/status | start-delivery, delivery-failed and status history | status transition tests |
| P6 | OTP delivery proof | in-memory challenge plus `DeliveryOTP`/`ProofOfDelivery` on verification | OTP tests |
| P7 | Assign tasks | `POST /api/assignments`, role gate | assignment authorization test |
| T1 | Location updates | `LocationUpdate`, shipment location endpoint | model and endpoint test |
| T2 | Movement history | `ShipmentStatusHistory` and safe timeline | tracking response test |
| T4 | Reports | `/api/reports/summary` | live count query |
| F6 | Delay detection and ETA assessment | `delivery_assessment`, shipment assessment and delayed-report endpoints | Phase 7 validation script |
| N1/N2 | In-app shipment notifications | `Notification`, automatic status-event creation, `/api/notifications` and read action | notification service and route contract |
| C1/C2 | Customer complaints and staff resolution | `Complaint`, `/api/complaints` and protected status update | customer/staff role gates |
| W1/W5 | Warehouse scanning/status | `WarehouseScan`, scan read/write surface | model mapping, scan creation, and operations lookup |
| W2/W6 | Routes/vehicles | exact `Route`, `Vehicle`, assignment foreign keys | ORM catalog validation |
| A1/A2 | Invoice/payment access | exact read models and finance summary | finance endpoint |
| A3 | COD access | exact `CodCollection` mapping and shipment COD projection | live count verification |
| A4/A5/A7 | Revenue/refund/export basis | finance summary and report totals; export is CSV follow-up | limitations |
