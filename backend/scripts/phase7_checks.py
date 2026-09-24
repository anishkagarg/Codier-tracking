"""Deterministic Phase 7 checks for the OptiGo MVP and Phase 6 extensions."""

from datetime import date
from pathlib import Path
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import engine
from app.main import app
from app.security import hash_otp, hash_password, verify_otp, verify_password
from app.services import STATUS_TRANSITIONS, delivery_assessment, optimize_route, parse_gps_location


def check(condition: bool, label: str) -> None:
    if not condition:
        raise AssertionError(label)
    print(f"PASS: {label}")


def main() -> None:
    password_hash = hash_password("Phase7-Local-Test!")
    otp_hash = hash_otp("123456")
    check(verify_password("Phase7-Local-Test!", password_hash), "password hashing and verification")
    check(verify_otp("123456", otp_hash), "OTP hashing and verification")
    check("DELIVERED" not in STATUS_TRANSITIONS["BOOKED"], "invalid status transition is rejected by the transition map")

    delayed = delivery_assessment(SimpleNamespace(current_status="IN_TRANSIT", expected_delivery=date(2026, 9, 20)), date(2026, 9, 24))
    check(delayed["state"] == "DELAYED" and delayed["days_overdue"] == 4, "delay assessment")
    check(parse_gps_location("GPS: 19.076000, 72.877700") == (19.076, 72.8777), "GPS coordinate parser")
    route = optimize_route({"latitude": 19.076, "longitude": 72.8777}, [{"stop_id": "A", "label": "A", "latitude": 19.08, "longitude": 72.88}])
    check(route["stops"][0]["stop_id"] == "A" and route["total_distance_km"] > 0, "no-cost route optimization")

    paths = {route.path for route in app.routes}
    check("/api/shipments/{shipment_id}/assessment" in paths, "shipment assessment route contract")
    check("/api/reports/delays" in paths, "delayed report route contract")
    check("/api/routes/optimize" in paths and "/api/payments/razorpay/order" in paths, "route and Razorpay contracts")

    with engine.connect() as connection:
        check(connection.execute(text("select 1")).scalar() == 1, "PostgreSQL readiness")
        account = connection.execute(text("select user_id from users where lower(email)=lower(:email)"), {"email": "kavya.nair@gmail.com"}).scalar()
        check(account == "OBUUSR000005", "Kavya account exists in PostgreSQL")

    client = TestClient(app)
    ready = client.get("/health/ready")
    check(ready.status_code == 200, "HTTP readiness endpoint")
    tracking = client.get("/api/track/OBUTRK000001")
    check(tracking.status_code == 200 and "delivery_assessment" in tracking.json(), "public tracking assessment")
    print("Phase 7 checks completed successfully.")


if __name__ == "__main__":
    main()
