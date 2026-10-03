from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from starlette.middleware.sessions import SessionMiddleware
from fastapi.testclient import TestClient

from app.db import Base
from app.security import hash_otp, hash_password, verify_otp, verify_password
from app.services import STATUS_TRANSITIONS, apply_shipping_offers, create_booking, price_for_weight
from app.models import Address, AdminRecoveryState, Customer, Department, Invoice, PasswordResetOTP, Staff, StaffRole, User
from app.main import AddressIn, AdminRecoveryIn, AuthIn, PasswordResetIn, PasswordResetRequestIn, PriceQuoteIn, StaffPasswordResetIn, admin_reset_staff_password, confirm_password_reset, create_address, demo_online_enabled, list_addresses, location_cities, login, public_pricing_quote, razorpay_test_keys_ready, recover_admin_access, request_password_reset, validate_startup_configuration
from starlette.requests import Request


def test_password_is_one_way_and_verifies():
    stored = hash_password("CorrectHorseBatteryStaple!")
    assert stored != "CorrectHorseBatteryStaple!"
    assert verify_password("CorrectHorseBatteryStaple!", stored)
    assert not verify_password("wrong-password", stored)


def test_imported_bcrypt_hashes_verify_with_the_declared_runtime_dependency():
    import bcrypt

    encoded = bcrypt.hashpw(b"ImportedAccountTest123!", bcrypt.gensalt()).decode("ascii")
    assert encoded.startswith("$2b$")
    assert verify_password("ImportedAccountTest123!", encoded)
    assert not verify_password("not-the-password", encoded)


def test_customer_login_creates_session_without_exposing_internal_ids_and_rejects_wrong_password():
    import bcrypt
    from fastapi import HTTPException

    encoded = bcrypt.hashpw(b"TemporarySessionTest123!", bcrypt.gensalt()).decode("ascii")
    user = SimpleNamespace(
        user_id="TESTUSR001", name="Test Customer", email="test@example.test",
        phone="9000000000", password_hash=encoded, active=True,
    )
    request = Request({"type": "http", "session": {}, "headers": []})
    db = Mock()
    db.scalar.side_effect = [user, None, None]

    result = login(AuthIn(email="TEST@example.test", password="TemporarySessionTest123!"), request, db)

    assert result["account"]["email"] == user.email
    assert "user_id" not in result["account"]
    assert "customer_id" not in result["account"]
    assert request.session["user_id"] == user.user_id
    assert "password_hash" not in result["account"]

    wrong_request = Request({"type": "http", "session": {}, "headers": []})
    wrong_db = Mock()
    wrong_db.scalar.return_value = user
    with pytest.raises(HTTPException) as failed:
        login(AuthIn(email=user.email, password="incorrect-password"), wrong_request, wrong_db)
    assert failed.value.status_code == 401
    assert not wrong_request.session


def test_customer_login_rejects_optigo_user_id():
    user = SimpleNamespace(
        user_id="OBUUSR123456", name="Test Customer", email="test@example.test",
        phone="9000000000", password_hash=hash_password("CustomerPassword123!"), active=True,
    )
    request = Request({"type": "http", "session": {}, "headers": []})
    db = Mock()
    db.scalar.side_effect = [user, None, None]

    with pytest.raises(HTTPException) as failed:
        login(AuthIn(email="obuusr123456", password="CustomerPassword123!"), request, db)
    assert failed.value.status_code == 401
    assert not request.session


def test_staff_login_accepts_optigo_user_id_and_keeps_staff_identifier_available():
    user = SimpleNamespace(
        user_id="OBUUSR654321", name="Test Courier", email="courier@example.test",
        phone="9000000000", password_hash=hash_password("CourierPassword123!"), active=True,
    )
    staff = SimpleNamespace(staff_id="OBUSTF654321", role_code="DELIVERY_AGENT", department_code="DELIVERY")
    request = Request({"type": "http", "session": {}, "headers": []})
    db = Mock()
    # User lookup, staff authorization for the user-ID sign-in, then account view.
    db.scalar.side_effect = [user, staff, None, staff]

    result = login(AuthIn(email="obuusr654321", password="CourierPassword123!"), request, db)

    assert result["account"]["user_id"] == user.user_id
    assert result["account"]["staff_id"] == staff.staff_id
    assert request.session["user_id"] == user.user_id


def test_registration_persists_internal_customer_id_but_customer_uses_email_to_sign_in():
    from app import main

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    tables = [Department.__table__, StaffRole.__table__, User.__table__, Customer.__table__, Staff.__table__]
    Base.metadata.create_all(engine, tables=tables)
    test_app = FastAPI()
    test_app.add_middleware(SessionMiddleware, secret_key="test-session-secret-long-enough-for-local-test")
    test_app.post("/api/auth/register", status_code=201)(main.register)
    test_app.post("/api/auth/login")(main.login)

    def override_get_db():
        with Session(engine) as db:
            yield db

    test_app.dependency_overrides[main.get_db] = override_get_db
    payload = {"name": "Test Customer", "email": "signup@example.test", "phone": "9000000000", "password": "SignupPassword123!"}
    with TestClient(test_app) as client:
        response = client.post("/api/auth/register", json=payload)
        assert response.status_code == 201, response.text
        created = response.json()
        assert created["account_created"] is True
        assert created["account"]["email"] == payload["email"]
        assert "user_id" not in created["account"]
        with Session(engine) as db:
            user = db.query(User).filter_by(email=payload["email"]).one()
            assert user.user_id.startswith("OBUUSR")
            assert db.query(Customer).filter_by(user_id=user.user_id).one()

        signed_in = client.post("/api/auth/login", json={"email": payload["email"], "password": payload["password"]})
        assert signed_in.status_code == 200, signed_in.text
        assert signed_in.json()["account"]["email"] == payload["email"]
        assert "user_id" not in signed_in.json()["account"]
        assert "session" in signed_in.headers.get("set-cookie", "")
    engine.dispose()


def test_customer_address_book_uses_authenticated_customer_api():
    from app import main

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    tables = [Department.__table__, StaffRole.__table__, User.__table__, Customer.__table__, Staff.__table__, Address.__table__]
    Base.metadata.create_all(engine, tables=tables)
    test_app = FastAPI()
    test_app.add_middleware(SessionMiddleware, secret_key="test-session-secret-long-enough-for-local-test")
    test_app.post("/api/auth/register", status_code=201)(main.register)
    test_app.post("/api/auth/login")(main.login)
    test_app.get("/api/addresses")(list_addresses)
    test_app.post("/api/addresses", status_code=201)(create_address)

    def override_get_db():
        with Session(engine) as db:
            yield db

    test_app.dependency_overrides[main.get_db] = override_get_db
    with TestClient(test_app) as client:
        address_payload = {
            "line1": "12 Example Street", "city": "Pune", "state": "Maharashtra",
            "postal_code": "411001", "country": "IN", "contact_name": "Test Customer",
            "contact_phone": "9000000000",
        }
        assert client.get("/api/addresses").status_code == 401
        registered = client.post("/api/auth/register", json={
            "name": "Test Customer", "email": "addressbook@example.test",
            "phone": "9000000000", "password": "AddressBookPassword123!",
        })
        assert registered.status_code == 201, registered.text
        login_response = client.post("/api/auth/login", json={
            "email": "addressbook@example.test", "password": "AddressBookPassword123!",
        })
        assert login_response.status_code == 200, login_response.text
        created = client.post("/api/addresses", json=address_payload)
        assert created.status_code == 201, created.text
        assert created.json()["line1"] == address_payload["line1"]
        assert client.get("/api/addresses").json() == [created.json()]
    engine.dispose()


def test_only_administrator_can_reset_existing_staff_passwords_including_own():
    from app import main

    from datetime import datetime, timezone

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    tables = [Department.__table__, StaffRole.__table__, User.__table__, Customer.__table__, Staff.__table__]
    Base.metadata.create_all(engine, tables=tables)
    old_password = "OriginalPassword123!"
    admin_id, admin_email = "OBUUSR000001", "admin@example.test"
    worker_id, worker_email = "OBUUSR000002", "pickup@example.test"
    admin = User(user_id=admin_id, name="Test Admin", email=admin_email, phone="9000000000", password_hash=hash_password(old_password), active=True, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    worker = User(user_id=worker_id, name="Test Pickup", email=worker_email, phone="9000000001", password_hash=hash_password(old_password), active=True, created_at=datetime.now(timezone.utc), updated_at=datetime.now(timezone.utc))
    with Session(engine) as db:
        db.add_all([
            Department(department_code="ADMIN", display_name="Administration"),
            Department(department_code="PICKUP", display_name="Pickup"),
            StaffRole(role_code="ADMINISTRATOR", display_name="Administrator"),
            StaffRole(role_code="PICKUP_AGENT", display_name="Pickup Agent"),
            admin, worker,
        ])
        db.flush()
        db.add_all([
            Staff(staff_id="OBUSTF000001", employee_id="TEST-ADMIN", department_code="ADMIN", role_code="ADMINISTRATOR", active=True, user_id=admin.user_id),
            Staff(staff_id="OBUSTF000002", employee_id="TEST-PICKUP", department_code="PICKUP", role_code="PICKUP_AGENT", active=True, user_id=worker.user_id),
        ])
        db.commit()

    test_app = FastAPI()
    test_app.add_middleware(SessionMiddleware, secret_key="test-session-secret-long-enough-for-local-test")
    test_app.post("/api/auth/login")(main.login)
    test_app.post("/api/admin/staff/{staff_id}/password")(admin_reset_staff_password)

    def override_get_db():
        with Session(engine) as db:
            yield db

    test_app.dependency_overrides[main.get_db] = override_get_db
    with TestClient(test_app) as unauthenticated:
        assert unauthenticated.post("/api/admin/staff/OBUSTF000002/password", json={"password": "NewTemporaryPassword123!"}).status_code == 401

    with TestClient(test_app) as administrator:
        assert administrator.post("/api/auth/login", json={"email": admin_email, "password": old_password}).status_code == 200
        reset = administrator.post("/api/admin/staff/OBUSTF000001/password", json={"password": "NewAdminPassword123!"})
        assert reset.status_code == 200, reset.text
        assert reset.json()["password_reset"] is True
        assert "password" not in reset.json()
        with Session(engine) as db:
            assert verify_password("NewAdminPassword123!", db.get(User, admin_id).password_hash)
        assert administrator.post("/api/auth/login", json={"email": admin_email, "password": "NewAdminPassword123!"}).status_code == 200
        worker_reset = administrator.post("/api/admin/staff/OBUSTF000002/password", json={"password": "NewPickupPassword123!"})
        assert worker_reset.status_code == 200, worker_reset.text
        with Session(engine) as db:
            assert verify_password("NewPickupPassword123!", db.get(User, worker_id).password_hash)

    with TestClient(test_app) as non_admin:
        assert non_admin.post("/api/auth/login", json={"email": worker_email, "password": "NewPickupPassword123!"}).status_code == 200
        denied = non_admin.post("/api/admin/staff/OBUSTF000002/password", json={"password": "AnotherTempPassword123!"})
        assert denied.status_code == 403
    engine.dispose()


def test_password_reset_request_emails_hashed_one_time_code(monkeypatch):
    from app import main

    monkeypatch.setenv("EMAIL_TRANSPORT", "smtp")
    monkeypatch.setenv("SMTP_HOST", "smtp.example.test")
    user = SimpleNamespace(user_id="OBUUSR123456", email="reset@example.test", active=True)
    db = Mock()
    db.scalar.side_effect = [user]
    db.get.side_effect = [None]
    monkeypatch.setattr(main, "send_password_reset_email", lambda target, code: True)

    result = request_password_reset(PasswordResetRequestIn(email="reset@example.test"), db)

    recovery = db.add.call_args.args[0]
    assert result["message"].startswith("If that email address is active")
    assert recovery.user_id == user.user_id
    assert recovery.code_hash != ""
    assert len(recovery.code_hash) > 20
    assert recovery.attempt_count == 0
    db.commit.assert_called_once()


def test_password_reset_rejects_invalid_code_then_accepts_valid_code():
    user = SimpleNamespace(
        user_id="OBUUSR123456", email="reset@example.test", active=True, password_hash=hash_password("OldPassword123!"),
        updated_at=datetime.now(timezone.utc),
    )
    recovery = PasswordResetOTP(
        user_id=user.user_id, code_hash=hash_otp("123456"),
        expires_at=datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year + 1),
        attempt_count=0, created_at=datetime.now(timezone.utc),
    )
    db = Mock()
    db.scalar.side_effect = [user, user]
    db.get.side_effect = [recovery, recovery]

    with pytest.raises(Exception) as failed:
        confirm_password_reset(PasswordResetIn(email=user.email, code="654321", new_password="NewPassword123!"), db)
    assert getattr(failed.value, "status_code", None) == 400
    assert recovery.attempt_count == 1
    db.commit.assert_called_once()

    result = confirm_password_reset(PasswordResetIn(email=user.email, code="123456", new_password="NewPassword123!"), db)
    assert result["password_reset"] is True
    assert verify_password("NewPassword123!", user.password_hash)
    db.delete.assert_called_once_with(recovery)


def test_admin_recovery_updates_only_existing_admin_once_and_rejects_wrong_key(monkeypatch):
    from app import main

    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    tables = [Department.__table__, StaffRole.__table__, User.__table__, Staff.__table__, AdminRecoveryState.__table__]
    Base.metadata.create_all(engine, tables=tables)
    now = datetime.now(timezone.utc)
    original_admin = User(
        user_id="OBUUSR000001", name="Existing Admin", email="old-admin@example.test", phone="9000000000",
        password_hash=hash_password("OldAdminPassword123!"), active=True, created_at=now, updated_at=now,
    )
    with Session(engine) as db:
        db.add_all([
            Department(department_code="ADMIN", display_name="Administration"),
            StaffRole(role_code="ADMINISTRATOR", display_name="Administrator"),
            original_admin,
            Staff(staff_id="OBUSTF000001", employee_id="ADMIN-1", department_code="ADMIN", role_code="ADMINISTRATOR", active=True, user_id=original_admin.user_id),
            AdminRecoveryState(singleton_id="admin"),
        ])
        db.commit()
        # Deleting the administrator is a soft delete. Recovery must restore
        # that same account rather than requiring a second administrator.
        original_admin.active = False
        db.query(Staff).filter_by(user_id=original_admin.user_id).one().active = False
        db.commit()

    test_app = FastAPI()
    test_app.post("/api/admin/recovery")(main.recover_admin_access)

    def override_get_db():
        with Session(engine) as db:
            yield db

    test_app.dependency_overrides[main.get_db] = override_get_db
    monkeypatch.setenv("ADMIN_RECOVERY_KEY", "a-long-one-time-recovery-key-for-tests")
    payload = {
        "recovery_key": "a-long-one-time-recovery-key-for-tests",
        "email": "new-admin@example.test",
        "password": "NewAdministratorPassword123!",
    }
    with TestClient(test_app) as client:
        assert client.post("/api/admin/recovery", json={**payload, "recovery_key": "incorrect-recovery-key-value-000000"}).status_code == 403
        recovered = client.post("/api/admin/recovery", json=payload)
        assert recovered.status_code == 200, recovered.text
        assert recovered.json()["user_id"] == "OBUUSR000001"
        assert recovered.json()["email"] == "new-admin@example.test"
        with Session(engine) as db:
            admin = db.get(User, "OBUUSR000001")
            assert admin.email == "new-admin@example.test"
            assert admin.active is True
            assert verify_password(payload["password"], admin.password_hash)
            restored_staff = db.query(Staff).filter_by(user_id=admin.user_id, role_code="ADMINISTRATOR").one()
            assert restored_staff.active is True
        assert client.post("/api/admin/recovery", json=payload).status_code == 410
    engine.dispose()


def test_otp_hash_is_not_the_otp():
    stored = hash_otp("123456")
    assert "123456" not in stored
    assert verify_otp("123456", stored)
    assert not verify_otp("654321", stored)


def test_phase2_status_transitions_are_explicit():
    assert "BOOKED" in STATUS_TRANSITIONS["INITIAL"]
    assert "PICKED_UP" in STATUS_TRANSITIONS["BOOKED"]
    assert "DELIVERED" in STATUS_TRANSITIONS["OUT_FOR_DELIVERY"]
    assert "DELIVERED" not in STATUS_TRANSITIONS["BOOKED"]


def test_delivery_agent_task_query_is_limited_to_their_staff_id(monkeypatch):
    from app import main

    user = SimpleNamespace(user_id="DELIVERYUSER")
    staff = SimpleNamespace(staff_id="DELIVERY001", role_code="DELIVERY_AGENT")
    monkeypatch.setattr(main, "required_staff", lambda *_args, **_kwargs: (user, staff))
    monkeypatch.setattr(main, "account_view", lambda *_args: {})
    db = Mock()
    db.scalars.return_value.all.return_value = []

    result = main.tasks(Request({"type": "http", "session": {}, "headers": []}), db)

    statement = db.scalars.call_args.args[0]
    assert statement.whereclause.left.name == "staff_id"
    assert statement.whereclause.right.value == staff.staff_id
    assert result["tasks"] == []


def test_delivery_agent_shipment_list_is_limited_to_assigned_deliveries(monkeypatch):
    from app import main

    user = SimpleNamespace(user_id="DELIVERYUSER")
    staff = SimpleNamespace(staff_id="DELIVERY001", role_code="DELIVERY_AGENT")
    monkeypatch.setattr(main, "required_user", lambda *_args, **_kwargs: user)
    monkeypatch.setattr(main, "staff_for", lambda *_args, **_kwargs: staff)
    db = Mock()
    db.scalars.return_value.all.return_value = []

    assert main.list_shipments(Request({"type": "http", "session": {}, "headers": []}), search=None, db=db) == []

    statement = db.scalars.call_args.args[0]
    sql = str(statement.compile()).lower()
    assert "shipment_assignments" in sql
    assert "DELIVERY" in statement.compile().params.values()
    assert staff.staff_id in statement.compile().params.values()


@pytest.mark.parametrize("endpoint_name", ["get_shipment", "shipment_tracking_detail"])
def test_delivery_agent_cannot_open_another_agents_shipment(monkeypatch, endpoint_name):
    from fastapi import HTTPException
    from app import main

    user = SimpleNamespace(user_id="DELIVERYUSER")
    staff = SimpleNamespace(staff_id="DELIVERY001", role_code="DELIVERY_AGENT")
    shipment = SimpleNamespace(shipment_id="SHIP000001", customer_id="CUSTOMER001")
    monkeypatch.setattr(main, "required_user", lambda *_args, **_kwargs: user)
    monkeypatch.setattr(main, "staff_for", lambda *_args, **_kwargs: staff)
    db = Mock()
    db.get.return_value = shipment
    db.scalar.return_value = None

    with pytest.raises(HTTPException) as forbidden:
        getattr(main, endpoint_name)(shipment.shipment_id, Request({"type": "http", "session": {}, "headers": []}), db)

    assert forbidden.value.status_code == 404


def test_delivery_verification_rejects_another_agents_account():
    from app.services import verify_delivery

    assignment = SimpleNamespace(assignment_id="ASSIGN001", shipment_id="SHIP000001", staff_id="ASSIGNED001", status_code="IN_PROGRESS")
    shipment = SimpleNamespace(current_status="OUT_FOR_DELIVERY")
    another_agent = SimpleNamespace(user_id="OTHERUSER")
    db = Mock()
    db.get.return_value = shipment
    db.scalar.return_value = SimpleNamespace(staff_id="OTHER001")

    with pytest.raises(PermissionError, match="Only the assigned delivery agent"):
        verify_delivery(db, assignment, another_agent, "123456", "test")

    db.scalar.assert_called_once()


def test_price_quote_uses_the_current_rule_and_rounds_to_currency():
    rule = SimpleNamespace(rate_parameters={"base_charge": "40", "per_kg": "10"}, currency="INR")
    db = Mock()
    db.scalar.return_value = rule

    amount, matched_rule = price_for_weight(db, "STANDARD", "LOCAL", Decimal("2.555"))

    assert amount == Decimal("65.55")
    assert matched_rule is rule


def test_shipping_offers_use_strict_original_inr_thresholds_and_stack():
    at_first_threshold = apply_shipping_offers(Decimal("500.00"), "INR")
    above_first_threshold = apply_shipping_offers(Decimal("500.01"), "INR")
    at_second_threshold = apply_shipping_offers(Decimal("1000.00"), "INR")
    above_second_threshold = apply_shipping_offers(Decimal("1200.00"), "INR")
    non_inr = apply_shipping_offers(Decimal("1200.00"), "USD")

    assert at_first_threshold["total"] == Decimal("500.00")
    assert above_first_threshold["discount"] == Decimal("25.00")
    assert above_first_threshold["total"] == Decimal("475.01")
    assert [offer["code"] for offer in at_second_threshold["discounts"]] == ["SHIP5"]
    assert at_second_threshold["total"] == Decimal("950.00")
    assert [offer["code"] for offer in above_second_threshold["discounts"]] == ["SHIP5", "SHIP50"]
    assert above_second_threshold["discount"] == Decimal("110.00")
    assert above_second_threshold["total"] == Decimal("1090.00")
    assert non_inr["discount"] == Decimal("0.00")
    assert non_inr["total"] == Decimal("1200.00")


def test_public_quote_is_the_exact_booking_charge():
    rule = SimpleNamespace(
        rate_parameters={"base_charge": "250", "per_kg": "20"},
        currency="INR",
        version="STD-INR-2026",
    )
    db = Mock()
    db.scalar.return_value = rule

    result = public_pricing_quote(
        PriceQuoteIn(weight_kg="3", delivery_type_code="STANDARD", destination_zone="LOCAL"),
        db,
    )

    assert result["amount"] == "310.00"
    assert result["subtotal"] == "310.00"
    assert result["discount"] == "0.00"
    assert result["discounts"] == []
    assert result["total"] == "310.00"
    assert result["tax"] == "0.00"
    assert result["is_final_charge"] is True


def test_public_quote_includes_both_eligible_offers_in_the_payable_total():
    rule = SimpleNamespace(
        rate_parameters={"base_charge": "1200", "per_kg": "0"},
        currency="INR",
        version="STD-INR-2026",
    )
    db = Mock()
    db.scalar.return_value = rule

    result = public_pricing_quote(
        PriceQuoteIn(weight_kg="1", delivery_type_code="STANDARD", destination_zone="LOCAL"),
        db,
    )

    assert result["subtotal"] == "1200.00"
    assert result["discount"] == "110.00"
    assert [offer["code"] for offer in result["discounts"]] == ["SHIP5", "SHIP50"]
    assert result["amount"] == result["total"] == "1090.00"
    assert result["is_final_charge"] is True


def test_booking_persists_discounted_charge_and_invoice_total(monkeypatch):
    import app.services as services

    rule = SimpleNamespace(
        rate_parameters={"base_charge": "1200", "per_kg": "0"},
        currency="INR",
        pricing_rule_id="TEST-RULE",
    )
    db = Mock()
    db.scalar.return_value = rule
    ids = iter(f"TEST-{index}" for index in range(10))
    monkeypatch.setattr(services, "new_id", lambda *args, **kwargs: next(ids))
    monkeypatch.setattr(services, "add_location_and_history", lambda *args, **kwargs: None)
    address = {
        "line1": "10 Test Road", "city": "Pune", "state": "Maharashtra",
        "postal_code": "411001", "country": "IN", "contact_name": "Test Recipient",
        "contact_phone": "9000000000",
    }

    shipment = create_booking(
        db,
        SimpleNamespace(customer_id="TEST-CUSTOMER"),
        SimpleNamespace(user_id="TEST-ACTOR"),
        address,
        address,
        {
            "weight_kg": "1", "length_cm": "10", "width_cm": "10", "height_cm": "10",
            "delivery_type_code": "STANDARD", "destination_zone": "LOCAL", "payment_mode": "CASH",
        },
    )

    invoice = next(call.args[0] for call in db.add.call_args_list if isinstance(call.args[0], Invoice))
    assert shipment.charge == Decimal("1090.00")
    assert shipment.cod_amount_due == Decimal("1090.00")
    assert invoice.subtotal == Decimal("1200.00")
    assert invoice.total == Decimal("1090.00")


def test_razorpay_checkout_requires_test_keys(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_example")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "example-secret")
    assert not razorpay_test_keys_ready()
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_example")
    assert razorpay_test_keys_ready()


def test_simulated_payment_requires_explicit_nonproduction_opt_in(monkeypatch):
    monkeypatch.setenv("DEMO_ONLINE_ENABLED", "false")
    monkeypatch.setenv("OPTIGO_ENV", "development")
    assert not demo_online_enabled()
    monkeypatch.setenv("DEMO_ONLINE_ENABLED", "true")
    assert demo_online_enabled()
    monkeypatch.setenv("OPTIGO_ENV", "production")
    assert not demo_online_enabled()


def test_production_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://optigo:example@db.example.test/optigo")
    monkeypatch.setenv("SESSION_SECRET", "a-unique-test-session-secret-that-is-long-enough")
    monkeypatch.setenv("OPTIGO_ENV", "production")
    monkeypatch.setenv("COOKIE_SECURE", "true")
    monkeypatch.setenv("FRONTEND_ORIGINS", "https://example.test")
    monkeypatch.setenv("DEMO_ONLINE_ENABLED", "true")
    with pytest.raises(RuntimeError, match="cannot be enabled in production"):
        validate_startup_configuration()


def test_location_lookup_failure_keeps_manual_entry_available(monkeypatch):
    from app import main

    def unavailable(*_args, **_kwargs):
        raise TimeoutError("provider unavailable")

    monkeypatch.setattr(main, "external_json", unavailable)
    result = location_cities("Uttarakhand")
    assert result["cities"] == []
    assert result["available"] is False
    assert "manually" in result["message"]


def test_shipment_tracking_detail_returns_all_recorded_gps_points_and_hub_scans(monkeypatch):
    from app import main

    user = SimpleNamespace(user_id="STAFF000001")
    staff = SimpleNamespace(staff_id="STAFF000001", role_code="TRACKING_OFFICER")
    shipment = SimpleNamespace(shipment_id="SHIP000001", customer_id="CUSTOMER001", current_status="OUT_FOR_DELIVERY")
    start = datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)
    locations = [
        SimpleNamespace(location_id="LOC-BOOKED", recorded_at=start, location_text="Mumbai", scan_type="APPLICATION"),
        SimpleNamespace(location_id="LOC-GPS-1", recorded_at=start.replace(hour=9), location_text="GPS:19.076000, 72.877700", scan_type="GPS"),
        SimpleNamespace(location_id="LOC-GPS-2", recorded_at=start.replace(hour=10), location_text="GPS:19.117600, 72.906000", scan_type="GPS"),
    ]
    history = [SimpleNamespace(location_id="LOC-BOOKED", new_status="BOOKED", event_at=start, remarks="Booking created")]
    scan = SimpleNamespace(scan_id="SCAN000001", scan_type="RECEIVED", scanned_at=start.replace(hour=8, minute=30), hub_id="HUB000001")
    hub = SimpleNamespace(hub_id="HUB000001", name="Andheri Sorting Hub", city="Mumbai", state="Maharashtra", postal_code="400053")
    monkeypatch.setattr(main, "required_user", lambda *_args: user)
    monkeypatch.setattr(main, "staff_for", lambda *_args: staff)
    monkeypatch.setattr(main, "shipment_view", lambda *_args, **_kwargs: {"shipment_id": shipment.shipment_id, "sender": {"city": "Mumbai"}, "receiver": {"city": "Pune"}})
    monkeypatch.setattr(main, "delivery_assessment", lambda *_args: {"state": "ON_SCHEDULE"})
    monkeypatch.setattr(main, "latest_gps_location", lambda *_args: {"latitude": 19.1176, "longitude": 72.906})
    db = Mock()
    db.get.return_value = shipment
    db.scalar.return_value = None
    db.scalars.side_effect = [SimpleNamespace(all=lambda: locations), SimpleNamespace(all=lambda: history)]
    db.execute.return_value.all.return_value = [(scan, hub)]

    result = main.shipment_tracking_detail(shipment.shipment_id, Mock(), db)

    points = [event for event in result["movement_events"] if event["kind"] == "GPS"]
    assert len(points) == 2
    assert [(point["latitude"], point["longitude"]) for point in points] == [(19.076, 72.8777), (19.1176, 72.906)]
    assert result["warehouse_scans"][0]["hub_name"] == "Andheri Sorting Hub"
    assert result["movement_events"][-1]["event_at"] == start.replace(hour=10).isoformat()
    assert result["delivery_proof"] is None


def test_customer_notifications_surface_only_live_delivery_codes(monkeypatch):
    from app import main

    user = SimpleNamespace(user_id="CUSTOMER0001")
    customer = SimpleNamespace(customer_id="CUSTOMER0001")
    now = datetime.now(timezone.utc)
    notice = SimpleNamespace(
        notification_id="NOTICE001", shipment_id="SHIP000001", type_code="OTP",
        channel_code="IN_APP", message="Delivery code for shipment OBUTRK001: 123456. Expires soon.",
        status_code="SENT", created_at=now, sent_at=now, read_at=None,
    )
    assignment = SimpleNamespace(assignment_id="ASSIGN001", status_code="IN_PROGRESS")
    otp = SimpleNamespace(created_at=now, consumed_at=None, expires_at=now + timedelta(minutes=8), attempt_count=0)
    monkeypatch.setattr(main, "required_user", lambda *_args: user)
    monkeypatch.setattr(main, "staff_for", lambda *_args: None)
    db = Mock()
    db.get.return_value = SimpleNamespace(current_status="OUT_FOR_DELIVERY", tracking_id="OBUTRK001")
    db.scalar.side_effect = [customer, assignment, otp]
    db.scalars.return_value.all.return_value = [notice]

    result = main.notifications(Mock(), db)

    assert result["notifications"][0]["delivery_code"] == "123456"
    assert "123456" not in result["notifications"][0]["message"]
    assert result["notifications"][0]["code_active"] is True


def test_staff_notifications_never_include_delivery_otp(monkeypatch):
    from app import main

    user = SimpleNamespace(user_id="STAFF000001")
    staff = SimpleNamespace(staff_id="STAFF000001")
    ordinary_notice = SimpleNamespace(
        notification_id="NOTICE002", shipment_id="SHIP000001", type_code="STATUS",
        channel_code="IN_APP", message="Shipment in transit.", status_code="SENT",
        created_at=datetime.now(timezone.utc), sent_at=None, read_at=None,
    )
    monkeypatch.setattr(main, "required_user", lambda *_args: user)
    monkeypatch.setattr(main, "staff_for", lambda *_args: staff)
    db = Mock()
    db.scalars.return_value.all.return_value = [ordinary_notice]

    result = main.notifications(Mock(), db)

    assert [item["type_code"] for item in result["notifications"]] == ["STATUS"]


def test_warehouse_can_record_an_inter_hub_arrival(monkeypatch):
    from app import main, services

    user = SimpleNamespace(user_id="WAREHOUSEUSER")
    staff = SimpleNamespace(staff_id="WAREHOUSE001", role_code="WAREHOUSE_OFFICER")
    shipment = SimpleNamespace(shipment_id="SHIP000001", tracking_id="OBUTRK001", current_status="IN_TRANSIT")
    hub = SimpleNamespace(hub_id="HUB000002", name="Pune Sorting Hub", city="Pune", state="Maharashtra", postal_code="411001", active=True)
    delivery_assignment = SimpleNamespace(status_code="ASSIGNED")
    payload = SimpleNamespace(shipment_id=shipment.shipment_id, hub_id=hub.hub_id, scan_type="RECEIVED")
    ids = iter(["OBUSCN000001", "OBULOC000001"])
    monkeypatch.setattr(main, "required_staff", lambda *_args, **_kwargs: (user, staff))
    monkeypatch.setattr(services, "new_id", lambda *_args, **_kwargs: next(ids))
    db = Mock()
    db.get.side_effect = [shipment, hub]
    db.scalar.return_value = delivery_assignment

    result = main.create_warehouse_scan(payload, Mock(), db)

    assert result["shipment_status"] == "IN_TRANSIT"
    assert result["next_task"] == "IN_TRANSIT"
    assert db.add.call_count == 2
    location = db.add.call_args_list[1].args[0]
    assert location.scan_type == "WAREHOUSE"
    assert location.location_text == "Pune Sorting Hub, Pune, Maharashtra 411001"


def test_shipment_tracking_detail_hides_another_customers_shipment(monkeypatch):
    from fastapi import HTTPException
    from app import main

    user = SimpleNamespace(user_id="CUSTOMER0001")
    shipment = SimpleNamespace(shipment_id="SHIP000001", customer_id="ANOTHER001")
    monkeypatch.setattr(main, "required_user", lambda *_args: user)
    monkeypatch.setattr(main, "staff_for", lambda *_args: None)
    db = Mock()
    db.get.return_value = shipment
    db.scalar.return_value = None

    with pytest.raises(HTTPException) as error:
        main.shipment_tracking_detail(shipment.shipment_id, Mock(), db)
    assert error.value.status_code == 404
