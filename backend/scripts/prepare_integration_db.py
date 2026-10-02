"""Create a clean, disposable PostgreSQL fixture for workflow integration tests."""

import os
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import Base, make_engine
from app.models import (
    AssignmentStatus, ComplaintStatus, Customer, Department, DeliveryType, Hub, NotificationChannel,
    NotificationStatus, NotificationType, PaymentMethod, PaymentStatus, PricingRule,
    Route, SettlementStatus, ShipmentStatus, Staff, StaffRole, TaskType, User, Vehicle,
)
from app.security import hash_password


def main() -> None:
    url = os.getenv("OPTIGO_TEST_DATABASE_URL", "").strip()
    if not url:
        raise SystemExit("Set OPTIGO_TEST_DATABASE_URL to a disposable PostgreSQL database ending in _test.")
    engine = make_engine(url)
    parsed = engine.url
    if not parsed.drivername.startswith("postgresql") or not (parsed.database or "").lower().endswith("_test"):
        raise SystemExit("Refusing to initialize: test database must be PostgreSQL and its name must end in _test.")
    existing = set(inspect(engine).get_table_names(schema="public"))
    if existing:
        raise SystemExit(f"Refusing to initialize non-empty test database ({len(existing)} existing tables). Use a fresh disposable database.")

    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE delivery_otps ALTER COLUMN verified_at DROP NOT NULL"))
        connection.execute(text("ALTER TABLE delivery_otps ALTER COLUMN consumed_at DROP NOT NULL"))

    now = datetime.now(timezone.utc)
    names = {
        "departments": ["ADMINISTRATION", "OPERATIONS", "ACCOUNTS", "BOOKING", "PICKUP", "WAREHOUSE", "DELIVERY", "SUPPORT", "TRACKING"],
        "roles": ["ADMINISTRATOR", "OPERATIONS_MANAGER", "ACCOUNTS_OFFICER", "BOOKING_OFFICER", "PICKUP_AGENT", "WAREHOUSE_OFFICER", "DELIVERY_AGENT", "SUPPORT_OFFICER", "TRACKING_OFFICER"],
    }
    with Session(engine) as db:
        for code in names["departments"]:
            db.add(Department(department_code=code, display_name=code.title()))
        for code in names["roles"]:
            db.add(StaffRole(role_code=code, display_name=code.replace("_", " ").title()))
        db.add_all([
            DeliveryType(delivery_type_code="STANDARD", display_name="Standard"),
            ShipmentStatus(status_code="INITIAL", display_name="Initial", is_terminal=False),
            ShipmentStatus(status_code="BOOKED", display_name="Booked", is_terminal=False),
            ShipmentStatus(status_code="PICKED_UP", display_name="Picked up", is_terminal=False),
            ShipmentStatus(status_code="IN_TRANSIT", display_name="In transit", is_terminal=False),
            ShipmentStatus(status_code="OUT_FOR_DELIVERY", display_name="Out for delivery", is_terminal=False),
            ShipmentStatus(status_code="DELIVERED", display_name="Delivered", is_terminal=True),
            AssignmentStatus(status_code="ASSIGNED", display_name="Assigned"),
            AssignmentStatus(status_code="IN_PROGRESS", display_name="In progress"),
            AssignmentStatus(status_code="COMPLETED", display_name="Completed"),
            TaskType(task_type_code="PICKUP", display_name="Pickup", task_type_id="T001"),
            TaskType(task_type_code="WAREHOUSE", display_name="Warehouse", task_type_id="T002"),
            TaskType(task_type_code="DELIVERY", display_name="Delivery", task_type_id="T003"),
            PaymentMethod(method_code="CASH", display_name="Cash"),
            PaymentStatus(status_code="PENDING", display_name="Pending"),
            PaymentStatus(status_code="PAID", display_name="Paid"),
            SettlementStatus(status_code="PENDING", display_name="Pending"),
            SettlementStatus(status_code="SETTLED", display_name="Settled"),
            NotificationType(type_code="STATUS_UPDATE", display_name="Status update"),
            NotificationType(type_code="OTP", display_name="Delivery OTP"),
            NotificationChannel(channel_code="IN_APP", display_name="In app"),
            NotificationStatus(status_code="SENT", display_name="Sent"),
            ComplaintStatus(status_code="OPEN", display_name="Open"),
            ComplaintStatus(status_code="IN_PROGRESS", display_name="In progress"),
            ComplaintStatus(status_code="RESOLVED", display_name="Resolved"),
            ComplaintStatus(status_code="CLOSED", display_name="Closed"),
        ])
        db.flush()
        rule = PricingRule(pricing_rule_id="TEST-PRICE-1", version="TEST-1", destination_zone="LOCAL", delivery_type_code="STANDARD", rate_parameters={"base_charge": "40", "per_kg": "10"}, currency="INR", effective_from=date(2020, 1, 1), effective_to=date(2099, 12, 31))
        hub = Hub(hub_id="TESTHUB001", name="OptiGo Test Hub", city="Rudrapur", state="Uttarakhand", postal_code="263153", country="IN", capacity=100, active=True)
        db.add_all([rule, hub])
        db.flush()
        db.add_all([
            Route(route_id="TEST-ROUTE-1", route_code="TEST-LOCAL", destination_zone="LOCAL", active=True, origin_hub_id=hub.hub_id, destination_hub_id=hub.hub_id),
            Vehicle(vehicle_id="TESTVEH001", registration_no="TEST-OPTIGO-1", capacity_kg=Decimal("100"), active=True, vehicle_name="Test van", vehicle_type="VAN", home_hub_id=hub.hub_id),
        ])
        roles = [
            ("ADMIN", "ADMINISTRATOR", "ADMINISTRATION"),
            ("OPERATIONS", "OPERATIONS_MANAGER", "OPERATIONS"),
            ("ACCOUNTS", "ACCOUNTS_OFFICER", "ACCOUNTS"),
            ("BOOKING", "BOOKING_OFFICER", "BOOKING"),
            ("PICKUP", "PICKUP_AGENT", "PICKUP"),
            ("WAREHOUSE", "WAREHOUSE_OFFICER", "WAREHOUSE"),
            ("DELIVERY", "DELIVERY_AGENT", "DELIVERY"),
            ("SUPPORT", "SUPPORT_OFFICER", "SUPPORT"),
            ("TRACKING", "TRACKING_OFFICER", "TRACKING"),
        ]
        for idx, (suffix, role, department) in enumerate(roles, start=1):
            user_id = f"TESTUSR{idx:03d}"
            user = User(user_id=user_id, name=f"Test {suffix.title()}", email=f"{suffix.lower()}@optigo.example.test", phone="9000000000", password_hash=hash_password("DisposableTest123!"), active=True, created_at=now, updated_at=now)
            db.add(user)
            db.flush()
            db.add(Staff(staff_id=f"TESTSTF{idx:03d}", employee_id=f"TEST-EMP-{idx:03d}", department_code=department, role_code=role, active=True, user_id=user.user_id))
        customer_user = User(user_id="TESTCUS001", name="Test Customer", email="customer@optigo.example.test", phone="9000000001", password_hash=hash_password("DisposableTest123!"), active=True, created_at=now, updated_at=now)
        db.add(customer_user)
        db.flush()
        db.add(Customer(customer_id="TESTCUST001", customer_type="INDIVIDUAL", name=customer_user.name, customer_no="TESTCNO001", user_id=customer_user.user_id))
        db.commit()
    print("Disposable PostgreSQL workflow fixture created successfully.")


if __name__ == "__main__":
    main()
