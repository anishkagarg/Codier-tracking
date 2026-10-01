from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI
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


def test_bcrypt_login_creates_session_and_rejects_wrong_password():
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

    assert result["account"]["user_id"] == user.user_id
    assert request.session["user_id"] == user.user_id
    assert "password_hash" not in result["account"]

    wrong_request = Request({"type": "http", "session": {}, "headers": []})
    wrong_db = Mock()
    wrong_db.scalar.return_value = user
    with pytest.raises(HTTPException) as failed:
        login(AuthIn(email=user.email, password="incorrect-password"), wrong_request, wrong_db)
    assert failed.value.status_code == 401
    assert not wrong_request.session


def test_login_accepts_optigo_user_id_and_creates_session():
    user = SimpleNamespace(
        user_id="OBUUSR123456", name="Test Customer", email="test@example.test",
        phone="9000000000", password_hash=hash_password("CustomerPassword123!"), active=True,
    )
    request = Request({"type": "http", "session": {}, "headers": []})
    db = Mock()
    db.scalar.side_effect = [user, None, None]

    result = login(AuthIn(email="obuusr123456", password="CustomerPassword123!"), request, db)

    assert result["account"]["user_id"] == user.user_id
    assert request.session["user_id"] == user.user_id


def test_registration_persists_customer_and_generated_id_can_sign_in():
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
        user_id = created["account"]["user_id"]
        assert created["account_created"] is True
        assert user_id.startswith("OBUUSR")
        with Session(engine) as db:
            assert db.get(User, user_id) is not None
            assert db.query(Customer).filter_by(user_id=user_id).one()

        signed_in = client.post("/api/auth/login", json={"email": user_id, "password": payload["password"]})
        assert signed_in.status_code == 200, signed_in.text
        assert signed_in.json()["account"]["user_id"] == user_id
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
            "email": registered.json()["account"]["user_id"], "password": "AddressBookPassword123!",
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
    user = SimpleNamespace(user_id="OBUUSR123456", active=True)
    db = Mock()
    db.get.side_effect = [user, None]
    monkeypatch.setattr(main, "send_password_reset_email", lambda target, code: True)

    result = request_password_reset(PasswordResetRequestIn(user_id="obuusr123456"), db)

    recovery = db.add.call_args.args[0]
    assert result["message"].startswith("If that user ID is active")
    assert recovery.user_id == user.user_id
    assert recovery.code_hash != ""
    assert len(recovery.code_hash) > 20
    assert recovery.attempt_count == 0
    db.commit.assert_called_once()


def test_password_reset_rejects_invalid_code_then_accepts_valid_code():
    user = SimpleNamespace(
        user_id="OBUUSR123456", active=True, password_hash=hash_password("OldPassword123!"),
        updated_at=datetime.now(timezone.utc),
    )
    recovery = PasswordResetOTP(
        user_id=user.user_id, code_hash=hash_otp("123456"),
        expires_at=datetime.now(timezone.utc).replace(year=datetime.now(timezone.utc).year + 1),
        attempt_count=0, created_at=datetime.now(timezone.utc),
    )
    db = Mock()
    db.get.side_effect = [user, recovery, user, recovery]

    with pytest.raises(Exception) as failed:
        confirm_password_reset(PasswordResetIn(user_id=user.user_id, code="654321", new_password="NewPassword123!"), db)
    assert getattr(failed.value, "status_code", None) == 400
    assert recovery.attempt_count == 1
    db.commit.assert_called_once()

    result = confirm_password_reset(PasswordResetIn(user_id=user.user_id, code="123456", new_password="NewPassword123!"), db)
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
            assert verify_password(payload["password"], admin.password_hash)
            assert db.query(Staff).filter_by(user_id=admin.user_id, role_code="ADMINISTRATOR").count() == 1
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
