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
from app.main import AddressIn, BookingIn, DeliveryIn, WarehouseScanIn, book_shipment, create_otp, create_warehouse_scan, deliver, pickup_complete, start_delivery
from app.models import Customer, Hub, Invoice, Notification, Payment, Shipment, ShipmentAssignment, Staff, User


pytestmark = pytest.mark.skipif(os.getenv("OPTIGO_INTEGRATION_TEST") != "1", reason="requires the local PostgreSQL fixture")


def request_for(user_id, key=None):
    headers = [(b"idempotency-key", key.encode())] if key else []
    return Request({"type": "http", "session": {"user_id": user_id}, "headers": headers})


def test_booking_passes_once_through_pickup_warehouse_and_delivery():
    with engine.connect() as connection:
        outer = connection.begin()
        db = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            customer_user = db.scalar(select(User).join(Customer, Customer.user_id == User.user_id).where(User.active.is_(True)).limit(1))
            assert customer_user is not None
            key = f"integration-{uuid4()}"
            address = AddressIn(line1="Test House, Test Road", city="Rudrapur", state="Uttarakhand", postal_code="263153", contact_name="Test Recipient", contact_phone="9000000000")
            payload = BookingIn(sender=address, receiver=address, weight_kg="1", length_cm="10", width_cm="10", height_cm="10", delivery_type_code="STANDARD", destination_zone="LOCAL", payment_mode="CASH")
            placed = book_shipment(payload, request_for(customer_user.user_id, key), db)
            shipment = db.get(Shipment, placed["shipment_id"])
            assert placed["tracking_id"] == shipment.tracking_id
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
            create_warehouse_scan(WarehouseScanIn(shipment_id=shipment.shipment_id, hub_id=hub.hub_id, scan_type="RECEIVED"), request_for(db.get(Staff, warehouse.staff_id).user_id), db)
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
