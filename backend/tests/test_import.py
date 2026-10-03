def test_app_imports():
    from app.main import app
    assert app.title == "OptiGo Courier Tracking API"
    paths = {route.path for route in app.routes}
    assert "/api/auth/login" in paths
    assert "/api/track/{tracking_id}" in paths
    assert "/api/notifications" in paths
    assert "/api/complaints" in paths
    assert "/api/complaints/{complaint_id}" in paths
    assert "/api/shipments/{shipment_id}/assessment" in paths
    assert "/api/reports/delays" in paths
    assert "/api/payments/demo/complete" in paths
    assert "/api/admin/staff" in paths


def test_booking_accepts_no_charge_demo_payment_mode():
    from app.main import AddressIn, BookingIn

    address = AddressIn(
        line1="12 Example Road",
        city="Rudrapur",
        state="Uttarakhand",
        postal_code="263153",
        contact_name="Test Customer",
        contact_phone="9000000000",
    )
    booking = BookingIn(
        sender=address,
        receiver=address,
        weight_kg="1",
        length_cm="10",
        width_cm="10",
        height_cm="10",
        payment_mode="DEMO",
    )
    assert booking.payment_mode == "DEMO"


def test_staff_account_input_supports_warehouse_officer():
    from app.main import StaffAccountIn

    staff = StaffAccountIn(
        name="Warehouse Demo",
        email="warehouse.demo@example.test",
        password="WarehouseDemo123!",
        phone="9000000000",
        department_code="WAREHOUSE",
        role_code="WAREHOUSE_OFFICER",
    )
    assert staff.role_code == "WAREHOUSE_OFFICER"
