# OptiGo User Manual

## Customer

1. Open the OptiGo frontend and choose **Create an account**, or sign in.
2. Select **New booking** and enter sender, receiver and parcel details.
3. Submit the booking. The backend returns a charge, expected date and unique Tracking ID.
4. Use **Shipments** to review owned bookings.
5. Use **Track shipment** to view the public timeline and ETA assessment.
6. Use **Notifications** to read shipment updates.
7. Use **Support & complaints** to report a shipment issue or ask for general support.

## Delivery agent

1. Sign in with a staff account.
2. Open **My tasks** to see assignments limited to your staff identity.
3. Complete pickup, start delivery, request the recipient OTP and verify delivery.
4. Record a delivery failure when the recipient cannot be served.

## Operations and support staff

- **Assignments** creates pickup, delivery or warehouse tasks.
- **Reports** displays live status totals, invoice totals and delayed shipments.
- **Warehouse** records hub-linked scans.
- **Finance** gives Accounts Officers an operational workbench: review unpaid invoices, open COD settlements and refund statuses; record courier operating costs and other income with source references; and enter dated asset/liability balances. Choose a period for the operating result and a separate date for the balance snapshot. The values use live OptiGo records and staff-entered data; they are not audited or statutory accounts. Reconcile balances with source documents and have a qualified accountant review them before relying on them externally.
- **Support & complaints** allows authorized support staff to move complaints through OPEN, IN_PROGRESS, RESOLVED or CLOSED.

## Administrator: create a warehouse officer login

1. Sign in with an **Administrator** account.
2. Open **Staff accounts**.
3. Enter the employee's name, work email, phone and employee ID.
4. Select the warehouse department and **Warehouse Officer** role.
5. Set a temporary password and select **Create staff login**.
6. Sign out. The warehouse officer can now sign in with the new work email and temporary password.

Customer registration deliberately creates only customer accounts. Staff roles can be issued only by an authenticated administrator.

## Warehouse officer workflow

1. A customer places an order; OptiGo creates a pickup task.
2. The assigned pickup agent selects **Complete pickup** from **My tasks**.
3. OptiGo changes the shipment to `PICKED_UP` and creates a warehouse assignment.
4. The warehouse officer signs in and opens **Warehouse**.
5. Under **Parcels awaiting receipt**, select the parcel and receiving hub.
6. Select **Confirm receipt**.
7. OptiGo records the warehouse scan, changes the shipment to `IN_TRANSIT`, completes the warehouse task and creates a delivery task.
8. The receipt appears under **Recent warehouse receipts**.

If the Warehouse page says that no parcel is ready, the pickup task has not been completed yet. An administrator or operations manager can inspect **Team tasks**.

## Public tracking privacy

Tracking by ID exposes shipment movement, status history and ETA assessment only. It does not expose customer contacts, OTP values, proof references, staff identities or finance records.
