"""Run with OPTIGO_INTEGRATION_TEST=1 against a disposable or local PostgreSQL DB.

The outer transaction is rolled back; this test does not leave a shipment behind.
"""

import os
import re
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request

from app.db import engine
from app.main import AddressIn, BookingIn, DeliveryIn, FinancePositionIn, FinanceTransactionIn, StaffAccountIn, WarehouseScanIn, admin_staff, book_shipment, create_finance_transaction, create_otp, create_staff_account, create_warehouse_scan, deliver, finance_summary, finance_workbench, operations_lookups, pickup_complete, record_finance_position, start_delivery, warehouse_scans
from app.models import Customer, FinancePosition, FinanceTransaction, Hub, Invoice, Notification, Payment, PricingRule, Shipment, ShipmentAssignment, Staff, User


pytestmark = pytest.mark.skipif(os.getenv("OPTIGO_INTEGRATION_TEST") != "1", reason="requires the local PostgreSQL fixture")


def request_for(user_id, key=None):
    headers = [(b"idempotency-key", key.encode())] if key else []
    return Request({"type": "http", "session": {"user_id": user_id}, "headers": headers})


def test_booking_passes_once_through_pickup_warehouse_and_delivery():
    with engine.connect() as connection:
        outer = connection.begin()
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            rule = db.scalar(select(PricingRule).where(PricingRule.delivery_type_code == "STANDARD", PricingRule.destination_zone == "LOCAL"))
            assert rule is not None
            rule.rate_parameters = {"base_charge": "1200", "per_kg": "0"}
            db.flush()
            customer_user = db.scalar(select(User).join(Customer, Customer.user_id == User.user_id).where(User.active.is_(True)).limit(1))
            assert customer_user is not None
            key = f"integration-{uuid4()}"
            address = AddressIn(line1="Test House, Test Road", city="Rudrapur", state="Uttarakhand", postal_code="263153", contact_name="Test Recipient", contact_phone="9000000000")
            payload = BookingIn(sender=address, receiver=address, weight_kg="1", length_cm="10", width_cm="10", height_cm="10", delivery_type_code="STANDARD", destination_zone="LOCAL", payment_mode="CASH")
            placed = book_shipment(payload, request_for(customer_user.user_id, key), db)
            shipment = db.get(Shipment, placed["shipment_id"])
            assert placed["tracking_id"] == shipment.tracking_id
            assert shipment.charge == 1090
            invoice = db.scalar(select(Invoice).where(Invoice.shipment_id == shipment.shipment_id))
            assert invoice.subtotal == 1200
            assert invoice.total == 1090
            assert shipment.cod_amount_due == 1090
            assert shipment.current_status == "BOOKED"
            pickup = db.scalar(select(ShipmentAssignment).where(ShipmentAssignment.shipment_id == shipment.shipment_id, ShipmentAssignment.task_type_code == "PICKUP"))
            assert pickup is not None
            assert db.get(Staff, pickup.staff_id).role_code == "PICKUP_AGENT"

            from fastapi import HTTPException
            with pytest.raises(HTTPException) as duplicate:
                book_shipment(payload, request_for(customer_user.user_id, key), db)
            assert duplicate.value.status_code == 409
            assert db.scalar(select(Shipment).where(Shipment.tracking_id == placed["tracking_id"])).shipment_id == shipment.shipment_id

            pickup_user = db.get(Staff, pickup.staff_id).user_id
            pickup_complete(pickup.assignment_id, request_for(pickup_user), db)
            db.refresh(shipment)
            assert shipment.current_status == "PICKED_UP"
            warehouse = db.scalar(select(ShipmentAssignment).where(ShipmentAssignment.shipment_id == shipment.shipment_id, ShipmentAssignment.task_type_code == "WAREHOUSE"))
            assert warehouse is not None
            assert db.get(Staff, warehouse.staff_id).role_code == "WAREHOUSE_OFFICER"

            hub = db.scalar(select(Hub).where(Hub.active.is_(True)))
            receipt = create_warehouse_scan(WarehouseScanIn(shipment_id=shipment.shipment_id, hub_id=hub.hub_id, scan_type="RECEIVED"), request_for(db.get(Staff, warehouse.staff_id).user_id), db)
            assert receipt["tracking_id"] == shipment.tracking_id
            assert receipt["shipment_status"] == "IN_TRANSIT"
            assert receipt["next_task"] == "DELIVERY"
            db.refresh(shipment)
            assert shipment.current_status == "IN_TRANSIT"
            delivery = db.scalar(select(ShipmentAssignment).where(ShipmentAssignment.shipment_id == shipment.shipment_id, ShipmentAssignment.task_type_code == "DELIVERY"))
            assert delivery is not None
            assert db.get(Staff, delivery.staff_id).role_code == "DELIVERY_AGENT"

            delivery_user = db.get(Staff, delivery.staff_id).user_id
            start_delivery(delivery.assignment_id, request_for(delivery_user), db)
            db.refresh(shipment)
            assert shipment.current_status == "OUT_FOR_DELIVERY"
            create_otp(delivery.assignment_id, request_for(delivery_user), db)
            notice = db.scalar(select(Notification).where(Notification.shipment_id == shipment.shipment_id, Notification.type_code == "OTP"))
            assert notice is not None
            code = re.search(r"\b\d{6}\b", notice.message).group(0)
            deliver(delivery.assignment_id, DeliveryIn(code=code, remarks="Test handover", cash_collected=True), request_for(delivery_user), db)
            db.refresh(shipment)
            assert shipment.current_status == "DELIVERED"
            assert shipment.cod_amount_due == 0
            invoice = db.scalar(select(Invoice).where(Invoice.shipment_id == shipment.shipment_id))
            assert invoice.payment_status_code == "PAID"
            assert db.scalar(select(Payment).where(Payment.invoice_no == invoice.invoice_no)).amount == invoice.total
            assert db.scalar(select(ShipmentAssignment).where(ShipmentAssignment.shipment_id == shipment.shipment_id, ShipmentAssignment.task_type_code == "PICKUP")).status_code == "COMPLETED"
            assert db.scalar(select(ShipmentAssignment).where(ShipmentAssignment.shipment_id == shipment.shipment_id, ShipmentAssignment.task_type_code == "WAREHOUSE")).status_code == "COMPLETED"
            assert db.scalar(select(ShipmentAssignment).where(ShipmentAssignment.shipment_id == shipment.shipment_id, ShipmentAssignment.task_type_code == "DELIVERY")).status_code == "COMPLETED"
        finally:
            db.close()
            outer.rollback()


def test_administrator_can_provision_a_warehouse_officer_login():
    with engine.connect() as connection:
        outer = connection.begin()
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            administrator = db.scalar(select(Staff).where(Staff.role_code == "ADMINISTRATOR", Staff.active.is_(True)))
            assert administrator is not None
            suffix = uuid4().hex[:8]
            created = create_staff_account(
                StaffAccountIn(
                    name="Warehouse Workflow Test",
                    email=f"warehouse-{suffix}@example.test",
                    password="WarehouseTest123!",
                    phone="9000000000",
                    employee_id=f"WH-{suffix}",
                    department_code="WAREHOUSE",
                    role_code="WAREHOUSE_OFFICER",
                ),
                request_for(administrator.user_id),
                db,
            )
            assert created["role_code"] == "WAREHOUSE_OFFICER"
            listing = admin_staff(request_for(administrator.user_id), db)
            assert any(row["staff_id"] == created["staff_id"] for row in listing["staff"])
            customer_user = db.scalar(select(User).join(Customer, Customer.user_id == User.user_id).where(User.active.is_(True)).limit(1))
            from fastapi import HTTPException
            with pytest.raises(HTTPException) as forbidden:
                admin_staff(request_for(customer_user.user_id), db)
            assert forbidden.value.status_code == 403
        finally:
            db.close()
            outer.rollback()


def test_department_read_access_matches_staff_role_matrix():
    with engine.connect() as connection:
        outer = connection.begin()
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            staff_by_role = {row.role_code: row for row in db.scalars(select(Staff).where(Staff.active.is_(True))).all()}
            assert set(staff_by_role) >= {"ADMINISTRATOR", "OPERATIONS_MANAGER", "ACCOUNTS_OFFICER", "BOOKING_OFFICER", "PICKUP_AGENT", "WAREHOUSE_OFFICER", "DELIVERY_AGENT", "SUPPORT_OFFICER", "TRACKING_OFFICER"}

            finance_summary(request_for(staff_by_role["ACCOUNTS_OFFICER"].user_id), db)
            operations_lookups(request_for(staff_by_role["TRACKING_OFFICER"].user_id), db)
            warehouse_scans(request_for(staff_by_role["WAREHOUSE_OFFICER"].user_id), db)
            admin_staff(request_for(staff_by_role["ADMINISTRATOR"].user_id), db)

            from fastapi import HTTPException
            for endpoint, denied_role in (
                (finance_summary, "PICKUP_AGENT"),
                (operations_lookups, "SUPPORT_OFFICER"),
                (warehouse_scans, "ACCOUNTS_OFFICER"),
                (admin_staff, "OPERATIONS_MANAGER"),
            ):
                with pytest.raises(HTTPException) as forbidden:
                    endpoint(request_for(staff_by_role[denied_role].user_id), db)
                assert forbidden.value.status_code == 403
        finally:
            db.close()
            outer.rollback()


def test_accounts_officer_can_record_costs_and_build_operational_statements():
    with engine.connect() as connection:
        outer = connection.begin()
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            accounts = db.scalar(select(Staff).where(Staff.role_code == "ACCOUNTS_OFFICER", Staff.active.is_(True)))
            assert accounts is not None
            today = datetime.now(timezone.utc).date()
            actor = request_for(accounts.user_id)
            create_finance_transaction(FinanceTransactionIn(entry_type="EXPENSE", category="FUEL_TRANSPORT", description="Van fuel receipt", amount="1250.00", entry_date=today, reference_no=f"fuel-{uuid4()}"), actor, db)
            create_finance_transaction(FinanceTransactionIn(entry_type="OTHER_INCOME", category="OTHER_SERVICE_INCOME", description="Packaging service charge", amount="250.00", entry_date=today), actor, db)
            record_finance_position(FinancePositionIn(position_type="ASSET", category="CASH_BANK", account_name="Operating bank", amount="10000.00", balance_date=today), actor, db)
            record_finance_position(FinancePositionIn(position_type="LIABILITY", category="SUPPLIER_PAYABLES", account_name="Packaging supplier", amount="3000.00", balance_date=today), actor, db)

            report = finance_workbench(actor, period_start=today, period_end=today, as_of=today, db=db)
            assert report["pnl"]["shipping_revenue_billed"] == "0.00"
            assert report["pnl"]["other_income"] == "250.00"
            assert report["pnl"]["operating_expenses"] == "1250.00"
            assert report["pnl"]["net_profit_loss"] == "-1000.00"
            assert report["balance_sheet"]["assets"] == "10000.00"
            assert report["balance_sheet"]["liabilities"] == "3000.00"
            assert report["balance_sheet"]["equity"] == "7000.00"
            assert db.query(FinanceTransaction).count() == 2
            assert db.query(FinancePosition).count() == 2

            from fastapi import HTTPException
            pickup = db.scalar(select(Staff).where(Staff.role_code == "PICKUP_AGENT", Staff.active.is_(True)))
            with pytest.raises(HTTPException) as forbidden:
                create_finance_transaction(FinanceTransactionIn(entry_type="EXPENSE", category="FUEL_TRANSPORT", description="Unauthorized expense", amount="1.00", entry_date=today), request_for(pickup.user_id), db)
            assert forbidden.value.status_code == 403
        finally:
            db.close()
            outer.rollback()
