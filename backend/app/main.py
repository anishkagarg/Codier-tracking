from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from contextlib import asynccontextmanager
from functools import lru_cache
import hashlib
import hmac
import logging
import json
import os
import re
import secrets
from urllib.parse import quote
from urllib.request import Request as UrlRequest, urlopen

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware
from typing import Literal

from .db import SessionLocal, engine, get_db
from .models import Address, AdminRecoveryState, AssignmentStatus, BookingIdempotency, CodCollection, Complaint, ComplaintMessage, ComplaintStatus, Customer, DeliveryOTP, DeliveryType, Department, FinancePosition, FinanceTransaction, Hub, Invoice, LocationUpdate, Notification, PasswordResetOTP, Payment, PricingRule, ProofOfDelivery, Refund, Route, Shipment, ShipmentAssignment, ShipmentStatusHistory, Staff, StaffRole, User, Vehicle, WarehouseScan
from .security import hash_otp, hash_password, verify_otp, verify_password
from .services import add_location_and_history, apply_shipping_offers, assign_task, auto_assign_task, create_booking, delivery_assessment, haversine_km, latest_gps_location, new_id, optimize_route, parse_gps_location, price_for_weight, public_tracking, request_delivery_otp, send_password_reset_email, transition_assignment, verify_delivery

logger = logging.getLogger(__name__)


def validate_startup_configuration() -> None:
    """Fail closed when secrets or deployment settings are missing or unsafe."""
    from sqlalchemy.engine import make_url

    try:
        import bcrypt  # noqa: F401 -- imported here so the service cannot silently serve broken bcrypt logins.
    except (ImportError, OSError) as exc:
        raise RuntimeError("bcrypt is required for imported account login. Install backend/requirements.txt in this Python environment.") from exc

    if not os.getenv("DATABASE_URL", "").strip():
        raise RuntimeError("DATABASE_URL is required before OptiGo can start.")
    secret = os.getenv("SESSION_SECRET", "").strip()
    if len(secret) < 32 or secret.lower() in {"change-this-session-secret", "replace-with-a-long-random-secret"}:
        raise RuntimeError("SESSION_SECRET must be a unique random value of at least 32 characters.")
    environment = os.getenv("OPTIGO_ENV", "development").strip().lower()
    if environment not in {"development", "test", "demo", "production"}:
        raise RuntimeError("OPTIGO_ENV must be development, test, demo, or production.")
    database_url = make_url(os.environ["DATABASE_URL"])
    if environment == "production":
        if not database_url.drivername.startswith("postgresql"):
            raise RuntimeError("Production requires a PostgreSQL DATABASE_URL.")
        if os.getenv("COOKIE_SECURE", "").strip().lower() != "true":
            raise RuntimeError("COOKIE_SECURE=true is required in production.")
        frontend_origins = [origin.strip() for origin in os.getenv("FRONTEND_ORIGINS", "").split(",") if origin.strip()]
        if not frontend_origins or "*" in frontend_origins or any(not origin.startswith("https://") for origin in frontend_origins):
            raise RuntimeError("FRONTEND_ORIGINS must contain only explicit HTTPS origins in production.")
        if os.getenv("DEMO_ONLINE_ENABLED", "false").strip().lower() == "true":
            raise RuntimeError("Simulated online payment cannot be enabled in production.")
        if os.getenv("RAZORPAY_MODE", "test").strip().lower() != "test":
            raise RuntimeError("Only explicitly configured Razorpay test mode is supported.")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    validate_startup_configuration()
    # Additive migration: creates only the new table and leaves existing records untouched.
    BookingIdempotency.__table__.create(bind=engine, checkfirst=True)
    PasswordResetOTP.__table__.create(bind=engine, checkfirst=True)
    AdminRecoveryState.__table__.create(bind=engine, checkfirst=True)
    FinanceTransaction.__table__.create(bind=engine, checkfirst=True)
    FinancePosition.__table__.create(bind=engine, checkfirst=True)
    ComplaintMessage.__table__.create(bind=engine, checkfirst=True)
    # Initialize a persistent one-use latch. Concurrent instances may race on
    # first startup; a unique primary key makes the losing insert harmless.
    with SessionLocal() as db:
        if not db.get(AdminRecoveryState, "admin"):
            db.add(AdminRecoveryState(singleton_id="admin"))
        # The complaints table has a foreign key to these operational states.
        # Older deployed databases may contain the table but not its lookup
        # rows, which would reject every customer complaint on insert.
        for code, label in (("OPEN", "Open"), ("IN_PROGRESS", "In progress"), ("RESOLVED", "Resolved"), ("CLOSED", "Closed")):
            if not db.get(ComplaintStatus, code):
                db.add(ComplaintStatus(status_code=code, display_name=label))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE invoices ADD COLUMN IF NOT EXISTS preferred_payment_mode VARCHAR(20)"))
        connection.execute(text("ALTER TABLE notifications ALTER COLUMN read_at DROP NOT NULL"))
        connection.execute(text("ALTER TABLE delivery_otps ALTER COLUMN verified_at DROP NOT NULL"))
        connection.execute(text("ALTER TABLE delivery_otps ALTER COLUMN consumed_at DROP NOT NULL"))
        # A newly submitted complaint can be general (no shipment) and has
        # neither an assigned support officer nor a resolution timestamp yet.
        connection.execute(text("ALTER TABLE complaints ALTER COLUMN shipment_id DROP NOT NULL"))
        connection.execute(text("ALTER TABLE complaints ALTER COLUMN handled_by_id DROP NOT NULL"))
        connection.execute(text("ALTER TABLE complaints ALTER COLUMN resolved_at DROP NOT NULL"))
        connection.execute(text("ALTER TABLE complaint_messages ADD COLUMN IF NOT EXISTS audience VARCHAR(20) NOT NULL DEFAULT 'CUSTOMER'"))
    yield


app = FastAPI(title="OptiGo Courier Tracking API", version="1.0.0", description="OptiGo backend connected to the configured PostgreSQL database.", lifespan=lifespan)
origins = [x.strip() for x in os.getenv("FRONTEND_ORIGINS", "").split(",") if x.strip()]
cookie_secure = os.getenv("COOKIE_SECURE", "false").lower() == "true"
# GitHub Pages and Render are different sites, so the authenticated session
# cookie must be allowed on cross-site API requests in production.
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", ""), same_site="none" if cookie_secure else "lax", https_only=cookie_secure)
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class AuthIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=200)


class PasswordResetRequestIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)


class PasswordResetIn(PasswordResetRequestIn):
    code: str = Field(pattern=r"^[0-9]{6}$")
    new_password: str = Field(min_length=8, max_length=200)


class RegisterIn(AuthIn):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=30)


class StaffAccountIn(AuthIn):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=30)
    employee_id: str = Field(min_length=2, max_length=30)
    department_code: str = Field(min_length=2, max_length=30)
    role_code: str = Field(min_length=2, max_length=30)


class StaffPasswordResetIn(BaseModel):
    password: str = Field(min_length=12, max_length=200)


class AdminRecoveryIn(BaseModel):
    recovery_key: str = Field(min_length=32, max_length=256)
    email: str = Field(min_length=5, max_length=254, pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=12, max_length=200)


def external_json(url: str, payload: dict | None = None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = UrlRequest(url, data=body, headers={"Content-Type": "application/json", "User-Agent": "OptiGo/1.0 address lookup"}, method="POST" if body else "GET")
    with urlopen(request, timeout=8) as response:
        return json.loads(response.read().decode())


@app.get("/api/locations/cities")
def location_cities(state: str = Query(min_length=2, max_length=100)):
    try:
        result = external_json("https://countriesnow.space/api/v0.1/countries/state/cities", {"country": "India", "state": state})
        return {"cities": sorted(set(result.get("data") or []))}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("City lookup unavailable (%s)", type(exc).__name__)
        return {"cities": [], "available": False, "message": "City suggestions are unavailable; you can enter the city manually."}


@app.get("/api/locations/search")
def location_search(q: str = Query(min_length=3, max_length=240)):
    try:
        result = external_json("https://photon.komoot.io/api/?q=" + quote(q) + "&limit=6")
        features = [feature for feature in result.get("features", []) if feature.get("properties", {}).get("country") == "India"]
        return {"features": features}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Address lookup unavailable (%s)", type(exc).__name__)
        return {"features": [], "available": False, "message": "Address suggestions are unavailable; you can enter the address manually."}


@lru_cache(maxsize=256)
def _search_post_offices(query: str) -> list[dict]:
    result = external_json("https://api.pincodeapi.in/api/v1/search?q=" + quote(query) + "&limit=100&offset=0")
    return result.get("data", {}).get("post_offices", [])


@app.get("/api/locations/post-offices")
def location_post_offices(city: str = Query(min_length=2, max_length=100), state: str = Query(min_length=2, max_length=100)):
    """Offer matching delivery post offices so their PIN is selected, never typed."""
    try:
        offices = _search_post_offices(f"{city} {state}")
        normalized_state = state.strip().casefold()
        normalized_city = city.strip().casefold()
        matches = [
            {"name": office.get("office_name", "Post office"), "pincode": office.get("pincode", ""), "district": office.get("district", ""), "state": office.get("state", "")}
            for office in offices
            if str(office.get("state", "")).strip().casefold() == normalized_state
            and str(office.get("pincode", "")).isdigit()
            and len(str(office.get("pincode"))) == 6
            and str(office.get("delivery_status", "Delivery")).strip().casefold() == "delivery"
            and (str(office.get("district", "")).strip().casefold() == normalized_city or normalized_city in str(office.get("office_name", "")).strip().casefold())
        ]
        unique = {(item["name"], item["pincode"]): item for item in matches}
        return {"post_offices": list(unique.values())}
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Post-office lookup unavailable (%s)", type(exc).__name__)
        return {"post_offices": [], "available": False, "message": "PIN suggestions are unavailable; you can enter the 6-digit PIN manually."}


class AddressIn(BaseModel):
    line1: str = Field(min_length=2, max_length=300)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=100)
    postal_code: str = Field(pattern=r"^\d{6}$", min_length=6, max_length=6)
    country: str = Field(default="IN", min_length=2, max_length=2)
    contact_name: str = Field(min_length=2, max_length=120)
    contact_phone: str = Field(min_length=7, max_length=30)


class BookingIn(BaseModel):
    sender: AddressIn
    receiver: AddressIn
    weight_kg: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    length_cm: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    width_cm: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    height_cm: Decimal = Field(gt=0, max_digits=12, decimal_places=2)
    parcel_type: str = Field(default="Parcel", min_length=2, max_length=80)
    delivery_type_code: str = Field(default="STANDARD", max_length=20)
    destination_zone: str = Field(default="LOCAL", max_length=100)
    fragile: bool = False
    priority: bool = False
    cod_amount_due: Decimal = Field(default=Decimal("0"), ge=0, max_digits=14, decimal_places=2)
    payment_mode: Literal["CASH", "DEMO", "RAZORPAY"] = "CASH"


class PriceQuoteIn(BaseModel):
    weight_kg: Decimal = Field(gt=0, max_digits=12, decimal_places=3)
    delivery_type_code: str = Field(default="STANDARD", max_length=20)
    destination_zone: str = Field(default="LOCAL", max_length=100)


class AssignmentIn(BaseModel):
    shipment_id: str
    staff_id: str
    task_type_code: str = Field(pattern="^(PICKUP|DELIVERY|WAREHOUSE)$")


class WarehouseScanIn(BaseModel):
    shipment_id: str
    hub_id: str
    scan_type: str = Field(min_length=1, max_length=40)


class LocationIn(BaseModel):
    location_text: str = Field(default="GPS update", min_length=2, max_length=200)
    scan_type: str = Field(default="MANUAL", max_length=40)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)


class RouteStopIn(BaseModel):
    stop_id: str = Field(min_length=1, max_length=80)
    label: str = Field(min_length=1, max_length=160)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


class RouteOptimizeIn(BaseModel):
    start_latitude: float = Field(ge=-90, le=90)
    start_longitude: float = Field(ge=-180, le=180)
    stops: list[RouteStopIn] = Field(min_length=1, max_length=100)


class RazorpayOrderIn(BaseModel):
    shipment_id: str = Field(min_length=3, max_length=50)


class DemoPaymentIn(BaseModel):
    shipment_id: str = Field(min_length=3, max_length=50)


class RazorpayVerifyIn(BaseModel):
    shipment_id: str = Field(min_length=3, max_length=50)
    order_id: str = Field(min_length=3, max_length=100)
    payment_id: str = Field(min_length=3, max_length=100)
    signature: str = Field(min_length=3, max_length=200)


class DeliveryIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    remarks: str = Field(default="OTP verified", max_length=500)
    cash_collected: bool = False


class FailureIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ComplaintIn(BaseModel):
    shipment_id: str | None = None
    subject: str = Field(min_length=3, max_length=150)
    description: str = Field(min_length=5, max_length=4000)


class ComplaintUpdateIn(BaseModel):
    status_code: str = Field(pattern="^(OPEN|IN_PROGRESS|RESOLVED|CLOSED)$")


class ComplaintMessageIn(BaseModel):
    message: str = Field(min_length=2, max_length=4000)
    audience: Literal["CUSTOMER", "INTERNAL"] = "CUSTOMER"


class FinanceTransactionIn(BaseModel):
    entry_type: Literal["EXPENSE", "OTHER_INCOME"]
    category: str = Field(min_length=2, max_length=40, pattern="^[A-Z_]+$")
    description: str = Field(min_length=3, max_length=500)
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    entry_date: date
    reference_no: str | None = Field(default=None, max_length=100)


class FinancePositionIn(BaseModel):
    position_type: Literal["ASSET", "LIABILITY"]
    category: str = Field(min_length=2, max_length=40, pattern="^[A-Z_]+$")
    account_name: str = Field(min_length=2, max_length=120)
    amount: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    balance_date: date
    notes: str = Field(default="", max_length=500)


FINANCE_TRANSACTION_CATEGORIES = {
    "EXPENSE": {"FUEL_TRANSPORT", "VEHICLE_MAINTENANCE", "SALARIES_WAGES", "HUB_WAREHOUSE", "PACKAGING_SUPPLIES", "TECHNOLOGY", "INSURANCE", "TAXES_FEES", "OTHER_EXPENSE"},
    "OTHER_INCOME": {"OTHER_SERVICE_INCOME", "MISCELLANEOUS_INCOME"},
}
FINANCE_POSITION_CATEGORIES = {
    "ASSET": {"CASH_BANK", "CUSTOMER_RECEIVABLES", "VEHICLES_EQUIPMENT", "PREPAID", "OTHER_ASSET"},
    "LIABILITY": {"SUPPLIER_PAYABLES", "LOANS", "TAXES_PAYABLE", "CUSTOMER_ADVANCES", "OTHER_LIABILITY"},
}


def user_from_request(request: Request, db: Session) -> User | None:
    uid = request.session.get("user_id")
    return db.get(User, uid) if uid else None


def required_user(request: Request, db: Session) -> User:
    user = user_from_request(request, db)
    if not user or not user.active:
        raise HTTPException(status_code=401, detail="Authentication is required")
    return user


def staff_for(db: Session, user: User) -> Staff | None:
    return db.scalar(select(Staff).where(Staff.user_id == user.user_id, Staff.active.is_(True)))


def delivery_agent_owns_shipment(db: Session, staff: Staff, shipment_id: str) -> bool:
    if staff.role_code != "DELIVERY_AGENT":
        return True
    return db.scalar(select(ShipmentAssignment.assignment_id).where(
        ShipmentAssignment.shipment_id == shipment_id,
        ShipmentAssignment.task_type_code == "DELIVERY",
        ShipmentAssignment.staff_id == staff.staff_id,
    )) is not None


def required_staff(request: Request, db: Session, roles: set[str] | None = None) -> tuple[User, Staff]:
    user = required_user(request, db)
    staff = staff_for(db, user)
    if not staff or (roles and staff.role_code not in roles):
        raise HTTPException(status_code=403, detail="Your role is not authorized for this operation")
    return user, staff


def account_view(db: Session, user: User) -> dict:
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    staff = staff_for(db, user)
    # Customer account IDs are operational references, not customer-facing
    # credentials. Keep them in the database and staff workflows, but never
    # send them to the customer browser.
    if not staff:
        return {"name": user.name, "email": user.email, "phone": user.phone, "role": "CUSTOMER", "department": None, "staff_id": None}
    return {"user_id": user.user_id, "name": user.name, "email": user.email, "phone": user.phone, "role": staff.role_code, "department": staff.department_code, "staff_id": staff.staff_id}


def address_view(db: Session, address_id: str) -> dict:
    address = db.get(Address, address_id)
    if not address:
        return {}
    return {"address_id": address.address_id, "address_role": address.address_role, "line1": address.line1, "city": address.city, "state": address.state, "postal_code": address.postal_code, "country": address.country.strip(), "contact_name": address.contact_name, "contact_phone": address.contact_phone}


def shipment_view(db: Session, shipment: Shipment, include_private: bool = True) -> dict:
    data = {"shipment_id": shipment.shipment_id, "tracking_id": shipment.tracking_id, "customer_id": shipment.customer_id, "status": shipment.current_status, "delivery_type_code": shipment.delivery_type_code, "delivery_mode": shipment.delivery_mode, "parcel_type": shipment.parcel_type, "weight_kg": str(shipment.weight_kg), "dimensions_cm": {"length": str(shipment.length_cm), "width": str(shipment.width_cm), "height": str(shipment.height_cm)}, "charge": str(shipment.charge), "currency": shipment.currency.strip(), "payment_amount": str(shipment.payment_amount), "cod_amount_due": str(shipment.cod_amount_due), "fragile": shipment.fragile, "priority": shipment.priority, "booking_date": shipment.booking_date.isoformat(), "expected_delivery": shipment.expected_delivery.isoformat()}
    invoice = db.scalar(select(Invoice).where(Invoice.shipment_id == shipment.shipment_id))
    data["payment_mode"] = invoice.preferred_payment_mode if invoice else None
    data["payment_status"] = invoice.payment_status_code if invoice else None
    if include_private:
        data["sender"] = address_view(db, shipment.sender_address_id)
        data["receiver"] = address_view(db, shipment.receiver_address_id)
    data["history"] = [{"sequence_no": e.sequence_no, "previous_status": e.previous_status, "status": e.new_status, "event_at": e.event_at.isoformat(), "location_id": e.location_id, "remarks": e.remarks} for e in db.scalars(select(ShipmentStatusHistory).where(ShipmentStatusHistory.shipment_id == shipment.shipment_id).order_by(ShipmentStatusHistory.sequence_no)).all()]
    return data


def notification_view(notification: Notification) -> dict:
    return {
        "notification_id": notification.notification_id,
        "shipment_id": notification.shipment_id,
        "type_code": notification.type_code,
        "channel_code": notification.channel_code,
        "message": notification.message,
        "status_code": notification.status_code,
        "created_at": notification.created_at.isoformat(),
        "sent_at": notification.sent_at.isoformat() if notification.sent_at else None,
        "read_at": notification.read_at.isoformat() if notification.read_at else None,
        "is_read": notification.read_at is not None,
    }


def complaint_view(db: Session, complaint: Complaint, include_internal: bool = False) -> dict:
    delivery_assignment = db.scalar(select(ShipmentAssignment).where(
        ShipmentAssignment.shipment_id == complaint.shipment_id,
        ShipmentAssignment.task_type_code == "DELIVERY",
    )) if complaint.shipment_id else None
    message_stmt = select(ComplaintMessage).where(ComplaintMessage.complaint_id == complaint.complaint_id)
    if not include_internal:
        message_stmt = message_stmt.where(ComplaintMessage.audience == "CUSTOMER")
    messages = db.scalars(message_stmt.order_by(ComplaintMessage.created_at, ComplaintMessage.message_id)).all()
    created_at = complaint.created_at if complaint.created_at.tzinfo else complaint.created_at.replace(tzinfo=timezone.utc)
    return {
        "complaint_id": complaint.complaint_id,
        "customer_id": complaint.customer_id,
        "shipment_id": complaint.shipment_id,
        "subject": complaint.subject,
        "description": complaint.description,
        "status_code": complaint.status_code,
        "created_at": complaint.created_at.isoformat(),
        "due_at": (created_at + timedelta(hours=24)).isoformat(),
        "resolved_at": complaint.resolved_at.isoformat() if complaint.resolved_at else None,
        "handled_by_id": complaint.handled_by_id,
        "case_owner_department": "SUPPORT",
        "action_department": "DELIVERY" if delivery_assignment else None,
        "messages": [{"message_id": row.message_id, "sender_role": row.sender_role, "audience": row.audience, "message": row.message, "created_at": row.created_at.isoformat()} for row in messages],
    }


def delivery_agent_complaint_ids(db: Session, staff: Staff) -> set[str]:
    if staff.role_code != "DELIVERY_AGENT":
        return set()
    return set(db.scalars(select(Complaint.complaint_id).join(
        ShipmentAssignment, ShipmentAssignment.shipment_id == Complaint.shipment_id
    ).where(
        ShipmentAssignment.task_type_code == "DELIVERY",
        ShipmentAssignment.staff_id == staff.staff_id,
        Complaint.status_code.not_in(["RESOLVED", "CLOSED"]),
    )).all())


def complaint_accessible_to(db: Session, complaint: Complaint, user: User, customer: Customer | None, staff: Staff | None) -> bool:
    if customer and complaint.customer_id == customer.customer_id:
        return True
    if staff and staff.role_code in {"ADMINISTRATOR", "OPERATIONS_MANAGER", "SUPPORT_OFFICER"}:
        return True
    return bool(staff and complaint.complaint_id in delivery_agent_complaint_ids(db, staff))


@app.get("/health/live")
def health_live():
    return {"status": "ok", "service": "optigo-backend"}


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("select 1"))
        return {"status": "ready", "database": "connected"}
    except Exception as exc:
        logger.error("Database readiness check failed (%s)", type(exc).__name__)
        raise HTTPException(503, "Database is not ready") from exc


@app.get("/api/auth/me")
def auth_me(request: Request, db: Session = Depends(get_db)):
    user = user_from_request(request, db)
    return {"authenticated": bool(user and user.active), "account": account_view(db, user) if user and user.active else None}


@app.post("/api/auth/register", status_code=201)
def register(payload: RegisterIn, request: Request, db: Session = Depends(get_db)):
    email = str(payload.email).lower().strip()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with that email already exists")
    now = datetime.now(timezone.utc)
    user = User(user_id=__import__("app.services", fromlist=["new_id"]).new_id(db, User, "user_id", "OBUUSR"), name=payload.name.strip(), email=email, phone=payload.phone.strip(), password_hash=hash_password(payload.password), active=True, created_at=now, updated_at=now)
    db.add(user)
    db.flush()
    customer = Customer(customer_id=__import__("app.services", fromlist=["new_id"]).new_id(db, Customer, "customer_id", "OBUCUS"), customer_type="INDIVIDUAL", name=user.name, customer_no=__import__("app.services", fromlist=["new_id"]).new_id(db, Customer, "customer_no", "OBUCUS"), user_id=user.user_id)
    db.add(customer)
    db.commit()
    # Registration creates the customer account but does not authenticate it.
    # The user must explicitly sign in after receiving the success message.
    return {"account_created": True, "account": account_view(db, user)}


@app.post("/api/auth/login")
def login(payload: AuthIn, request: Request, db: Session = Depends(get_db)):
    identifier = str(payload.email).strip()
    user = db.scalar(select(User).where((User.email == identifier.lower()) | (User.user_id == identifier.upper())))
    if not user or not user.active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    # Staff retain their internal OptiGo user-ID login. Customer IDs are never
    # a customer login credential: customers must sign in with their email.
    if "@" not in identifier and not staff_for(db, user):
        raise HTTPException(401, "Customers must sign in with their email address")
    request.session.clear()
    request.session["user_id"] = user.user_id
    return {"account": account_view(db, user)}


@app.post("/api/auth/password-reset/request", status_code=202)
def request_password_reset(payload: PasswordResetRequestIn, db: Session = Depends(get_db)):
    if os.getenv("EMAIL_TRANSPORT", "in_app").lower() != "smtp" or not os.getenv("SMTP_HOST"):
        raise HTTPException(503, "Password reset email is not configured. Contact OptiGo support.")
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    if user and user.active:
        now = datetime.now(timezone.utc)
        existing = db.get(PasswordResetOTP, user.user_id)
        if existing:
            created_at = existing.created_at
            if created_at.tzinfo is None:
                created_at = created_at.replace(tzinfo=timezone.utc)
            if now - created_at < timedelta(seconds=60):
                raise HTTPException(429, "Please wait one minute before requesting another code.")
        code = f"{secrets.randbelow(1_000_000):06d}"
        if not send_password_reset_email(user, code):
            raise HTTPException(503, "We could not send a reset code right now. Please try again later.")
        recovery = existing or PasswordResetOTP(user_id=user.user_id, code_hash=hash_otp(code), expires_at=now + timedelta(minutes=10), attempt_count=0, created_at=now)
        recovery.code_hash = hash_otp(code)
        recovery.expires_at = now + timedelta(minutes=10)
        recovery.attempt_count = 0
        recovery.created_at = now
        db.add(recovery)
        db.commit()
    return {"message": "If that email address is active, a reset code has been sent."}


@app.post("/api/admin/recovery")
def recover_admin_access(payload: AdminRecoveryIn, db: Session = Depends(get_db)):
    """One-time, secret-gated recovery of the existing administrator login.

    The Render-only ADMIN_RECOVERY_KEY must be a high-entropy random value.
    The operation changes only the existing admin account's email/password,
    then permanently consumes the database latch.
    """
    expected_key = os.getenv("ADMIN_RECOVERY_KEY", "")
    if len(expected_key) < 32 or not hmac.compare_digest(payload.recovery_key, expected_key):
        raise HTTPException(403, "Recovery is unavailable or the recovery key is invalid")

    recovery_state = db.scalar(
        select(AdminRecoveryState)
        .where(AdminRecoveryState.singleton_id == "admin")
        .with_for_update()
    )
    if not recovery_state:
        raise HTTPException(503, "Admin recovery is not initialized. Contact OptiGo support.")
    if recovery_state.completed_at:
        raise HTTPException(410, "The one-time administrator recovery has already been used")

    administrators = db.execute(
        select(Staff, User)
        .join(User, Staff.user_id == User.user_id)
        .where(
            Staff.role_code == "ADMINISTRATOR",
        )
        .with_for_update()
    ).all()
    if len(administrators) != 1:
        raise HTTPException(409, "Recovery requires exactly one administrator account")

    admin_staff, admin_user = administrators[0]
    email = payload.email.strip().lower()
    email_owner = db.scalar(select(User).where(func.lower(User.email) == email))
    if email_owner and email_owner.user_id != admin_user.user_id:
        raise HTTPException(409, "That email is already assigned to another account")

    now = datetime.now(timezone.utc)
    admin_staff.active = True
    admin_user.active = True
    admin_user.email = email
    admin_user.password_hash = hash_password(payload.password)
    admin_user.updated_at = now
    recovery_state.completed_at = now
    recovery_state.admin_user_id = admin_user.user_id
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "The recovery could not be completed because the account changed") from exc
    return {
        "recovered": True,
        "user_id": admin_user.user_id,
        "email": admin_user.email,
        "message": "Administrator access recovered. Sign in with the new email and password.",
    }


@app.post("/api/auth/password-reset/confirm")
def confirm_password_reset(payload: PasswordResetIn, db: Session = Depends(get_db)):
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    recovery = db.get(PasswordResetOTP, user.user_id) if user else None
    now = datetime.now(timezone.utc)
    if not user or not user.active or not recovery:
        raise HTTPException(400, "The reset code is invalid or expired. Request a new code and try again.")
    expires_at = recovery.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if recovery.attempt_count >= 5 or expires_at <= now:
        db.delete(recovery)
        db.commit()
        raise HTTPException(400, "The reset code is invalid or expired. Request a new code and try again.")
    if not verify_otp(payload.code, recovery.code_hash):
        recovery.attempt_count += 1
        db.commit()
        raise HTTPException(400, "The reset code is invalid or expired. Request a new code and try again.")
    user.password_hash = hash_password(payload.new_password)
    user.updated_at = now
    db.delete(recovery)
    db.commit()
    return {"password_reset": True, "message": "Password updated. Sign in with your new password."}


@app.post("/api/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"logged_out": True}


@app.get("/api/admin/staff")
def admin_staff(request: Request, db: Session = Depends(get_db)):
    """Give administrators a safe UI-backed way to provision staff logins."""
    required_staff(request, db, {"ADMINISTRATOR"})
    rows = db.execute(
        select(Staff, User)
        .join(User, Staff.user_id == User.user_id)
        .order_by(Staff.employee_id)
    ).all()
    return {
        "staff": [
            {
                "staff_id": staff.staff_id,
                "employee_id": staff.employee_id,
                "name": user.name,
                "email": user.email,
                "phone": user.phone,
                "department_code": staff.department_code,
                "role_code": staff.role_code,
                "active": bool(staff.active and user.active),
            }
            for staff, user in rows
        ],
        "roles": [
            {"code": role.role_code, "name": role.display_name}
            for role in db.scalars(select(StaffRole).order_by(StaffRole.display_name)).all()
        ],
        "departments": [
            {"code": department.department_code, "name": department.display_name}
            for department in db.scalars(select(Department).order_by(Department.display_name)).all()
        ],
    }


@app.post("/api/admin/staff", status_code=201)
def create_staff_account(payload: StaffAccountIn, request: Request, db: Session = Depends(get_db)):
    """Create a separate staff login without weakening customer self-registration."""
    required_staff(request, db, {"ADMINISTRATOR"})
    email = str(payload.email).lower().strip()
    employee_id = payload.employee_id.strip()
    role_code = payload.role_code.strip().upper()
    department_code = payload.department_code.strip().upper()
    if db.scalar(select(User).where(User.email == email)):
        raise HTTPException(409, "An account with that email already exists")
    if db.scalar(select(Staff).where(Staff.employee_id == employee_id)):
        raise HTTPException(409, "That employee ID is already in use")
    if not db.get(StaffRole, role_code):
        raise HTTPException(400, "Select a valid staff role")
    if not db.get(Department, department_code):
        raise HTTPException(400, "Select a valid department")
    now = datetime.now(timezone.utc)
    user = User(
        user_id=new_id(db, User, "user_id", "OBUUSR"),
        name=payload.name.strip(),
        email=email,
        phone=payload.phone.strip(),
        password_hash=hash_password(payload.password),
        active=True,
        created_at=now,
        updated_at=now,
    )
    db.add(user)
    db.flush()
    staff = Staff(
        staff_id=new_id(db, Staff, "staff_id", "OBUSTF"),
        employee_id=employee_id,
        department_code=department_code,
        role_code=role_code,
        active=True,
        user_id=user.user_id,
    )
    try:
        db.add(staff)
        db.commit()
        db.refresh(staff)
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "The staff account conflicts with an existing record") from exc
    return {
        "staff_id": staff.staff_id,
        "employee_id": staff.employee_id,
        "name": user.name,
        "email": user.email,
        "department_code": staff.department_code,
        "role_code": staff.role_code,
        "active": True,
    }


@app.post("/api/admin/staff/{staff_id}/password")
def admin_reset_staff_password(staff_id: str, payload: StaffPasswordResetIn, request: Request, db: Session = Depends(get_db)):
    """Set an existing active staff login password; only an administrator can do this."""
    required_staff(request, db, {"ADMINISTRATOR"})
    staff = db.get(Staff, staff_id)
    if not staff or not staff.active:
        raise HTTPException(404, "Active staff account not found")
    user = db.get(User, staff.user_id)
    if not user or not user.active:
        raise HTTPException(404, "Active staff account not found")
    user.password_hash = hash_password(payload.password)
    user.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"password_reset": True, "staff_id": staff.staff_id, "user_id": user.user_id, "name": user.name, "email": user.email, "role_code": staff.role_code}


@app.delete("/api/auth/account")
def delete_account(request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    staff = db.scalar(select(Staff).where(Staff.user_id == user.user_id))
    # Retain shipment history for operational integrity while disabling access
    # and removing the account's identifying login details.
    user.active = False
    user.email = f"deleted+{user.user_id}@invalid.optigo"
    user.name = "Deleted account"
    user.phone = ""
    user.password_hash = hash_password(f"deleted-{user.user_id}-{datetime.now(timezone.utc).isoformat()}")
    if customer:
        customer.name = "Deleted account"
    if staff:
        staff.active = False
    db.commit()
    request.session.clear()
    return {"account_deleted": True}


@app.get("/api/notifications")
def notifications(request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    staff = staff_for(db, user)
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(250)
    if customer and not staff:
        stmt = stmt.where(Notification.customer_id == customer.customer_id)
    elif staff:
        # Delivery codes are recipient-only. Never expose them in staff notification feeds.
        stmt = stmt.where(Notification.type_code != "OTP")
    else:
        raise HTTPException(403, "A customer or staff profile is required")
    rows = db.scalars(stmt).all()
    items = []
    for row in rows:
        item = notification_view(row)
        if customer and not staff and row.type_code == "OTP":
            # The notification stores its original message, but only surface its code
            # while the matching delivery OTP is still valid and unused.
            assignment = db.scalar(select(ShipmentAssignment).where(
                ShipmentAssignment.shipment_id == row.shipment_id,
                ShipmentAssignment.task_type_code == "DELIVERY",
            ))
            otp = db.scalar(select(DeliveryOTP).where(DeliveryOTP.assignment_id == assignment.assignment_id)) if assignment else None
            shipment = db.get(Shipment, row.shipment_id)
            item["tracking_id"] = shipment.tracking_id if shipment else None
            match = re.search(r"Delivery code for shipment [^:]+:\s*(\d{6})", row.message)
            now = datetime.now(timezone.utc)
            same_issue = bool(otp and abs((otp.created_at - row.created_at).total_seconds()) <= 60)
            active = bool(otp and match and same_issue and assignment and assignment.status_code == "IN_PROGRESS"
                          and shipment and shipment.current_status == "OUT_FOR_DELIVERY"
                          and otp.consumed_at is None and otp.expires_at > now and otp.attempt_count < 5)
            item["message"] = "A delivery verification code was requested for this shipment."
            item["delivery_code"] = match.group(1) if active else None
            item["expires_at"] = otp.expires_at.isoformat() if active else None
            item["code_active"] = active
        items.append(item)
    return {"notifications": items, "unread_count": sum(row.read_at is None for row in rows)}


@app.post("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: str, request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    notification = db.get(Notification, notification_id)
    if not notification:
        raise HTTPException(404, "Notification not found")
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    staff = staff_for(db, user)
    if notification.type_code == "OTP" and (not customer or notification.customer_id != customer.customer_id):
        raise HTTPException(404, "Notification not found")
    if not staff and (not customer or notification.customer_id != customer.customer_id):
        raise HTTPException(404, "Notification not found")
    notification.read_at = notification.read_at or datetime.now(timezone.utc)
    db.commit()
    result = notification_view(notification)
    if notification.type_code == "OTP":
        result["message"] = "A delivery verification code was requested for this shipment."
    return result


@app.get("/api/complaints")
def complaints(request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    staff = staff_for(db, user)
    stmt = select(Complaint).order_by(Complaint.created_at.desc()).limit(100)
    if not staff:
        if not customer:
            raise HTTPException(403, "A customer profile is required")
        stmt = stmt.where(Complaint.customer_id == customer.customer_id)
    elif staff.role_code == "DELIVERY_AGENT":
        complaint_ids = delivery_agent_complaint_ids(db, staff)
        stmt = stmt.where(Complaint.complaint_id.in_(complaint_ids))
    elif staff.role_code not in {"ADMINISTRATOR", "OPERATIONS_MANAGER", "SUPPORT_OFFICER"}:
        raise HTTPException(403, "Your role is not authorized to view complaints")
    return {"complaints": [complaint_view(db, row, include_internal=bool(staff)) for row in db.scalars(stmt).all()]}


@app.post("/api/complaints", status_code=201)
def create_complaint(payload: ComplaintIn, request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    if not customer:
        raise HTTPException(403, "A customer profile is required")
    if payload.shipment_id:
        shipment = db.scalar(select(Shipment).where(Shipment.shipment_id == payload.shipment_id, Shipment.customer_id == customer.customer_id))
        if not shipment:
            raise HTTPException(404, "Shipment not found")
    complaint = Complaint(
        complaint_id=new_id(db, Complaint, "complaint_id", "OBUCMP"),
        customer_id=customer.customer_id,
        shipment_id=payload.shipment_id,
        subject=payload.subject.strip(),
        description=payload.description.strip(),
        status_code="OPEN",
        created_at=datetime.now(timezone.utc),
        resolved_at=None,
        handled_by_id=None,
    )
    db.add(complaint)
    db.commit()
    return complaint_view(db, complaint)


@app.patch("/api/complaints/{complaint_id}")
def update_complaint(complaint_id: str, payload: ComplaintUpdateIn, request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    staff = staff_for(db, user)
    if not staff:
        raise HTTPException(403, "Your role is not authorized to update complaints")
    complaint = db.get(Complaint, complaint_id)
    if not complaint:
        raise HTTPException(404, "Complaint not found")
    if staff.role_code == "DELIVERY_AGENT":
        if not complaint_accessible_to(db, complaint, user, None, staff):
            raise HTTPException(404, "Complaint not found")
        if payload.status_code != "IN_PROGRESS":
            raise HTTPException(403, "Mark the case in progress and report the completed action to Support. Support confirms resolution with the customer.")
    elif staff.role_code not in {"ADMINISTRATOR", "OPERATIONS_MANAGER", "SUPPORT_OFFICER"}:
        raise HTTPException(403, "Your role is not authorized to update complaints")
    complaint.status_code = payload.status_code
    complaint.handled_by_id = staff.staff_id
    complaint.resolved_at = datetime.now(timezone.utc) if payload.status_code in {"RESOLVED", "CLOSED"} else None
    db.commit()
    return complaint_view(db, complaint, include_internal=True)


@app.post("/api/complaints/{complaint_id}/messages", status_code=201)
def create_complaint_message(complaint_id: str, payload: ComplaintMessageIn, request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    staff = staff_for(db, user)
    complaint = db.get(Complaint, complaint_id)
    if not complaint or not complaint_accessible_to(db, complaint, user, customer, staff):
        raise HTTPException(404, "Complaint not found")
    sender_role = staff.role_code if staff else "CUSTOMER"
    if not staff and payload.audience != "CUSTOMER":
        raise HTTPException(403, "Customers can only send messages to Support")
    if staff and staff.role_code == "DELIVERY_AGENT" and payload.audience != "INTERNAL":
        raise HTTPException(403, "Delivery updates are sent to Support as internal case notes")
    db.add(ComplaintMessage(
        message_id=new_id(db, ComplaintMessage, "message_id", "OBUCMT"),
        complaint_id=complaint.complaint_id,
        sender_user_id=user.user_id,
        sender_role=sender_role,
        audience=payload.audience,
        message=payload.message.strip(),
        created_at=datetime.now(timezone.utc),
    ))
    if complaint.status_code == "OPEN":
        complaint.status_code = "IN_PROGRESS"
    db.commit()
    return complaint_view(db, complaint, include_internal=bool(staff))


@app.get("/api/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    staff = staff_for(db, user)
    if customer:
        base = select(func.count(Shipment.shipment_id)).where(Shipment.customer_id == customer.customer_id)
        metrics = {"total": db.scalar(base) or 0, "delivered": db.scalar(base.where(Shipment.current_status == "DELIVERED")) or 0, "in_transit": db.scalar(base.where(Shipment.current_status.in_(["PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"]))) or 0, "attention": db.scalar(base.where(Shipment.current_status.in_(["DELIVERY_FAILED", "UNAVAILABLE"]))) or 0}
        recent = db.scalars(select(Shipment).where(Shipment.customer_id == customer.customer_id).order_by(Shipment.booking_date.desc()).limit(6)).all()
    else:
        metrics = {"total": db.scalar(select(func.count(Shipment.shipment_id))) or 0, "delivered": db.scalar(select(func.count(Shipment.shipment_id)).where(Shipment.current_status == "DELIVERED")) or 0, "in_transit": db.scalar(select(func.count(Shipment.shipment_id)).where(Shipment.current_status.in_(["PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY"]))) or 0, "attention": db.scalar(select(func.count(Shipment.shipment_id)).where(Shipment.current_status.in_(["DELIVERY_FAILED", "UNAVAILABLE"]))) or 0}
        recent = db.scalars(select(Shipment).order_by(Shipment.booking_date.desc()).limit(8)).all()
    return {"account": account_view(db, user), "metrics": metrics, "recent_shipments": [shipment_view(db, s, include_private=bool(staff)) for s in recent]}


@app.get("/api/addresses")
def list_addresses(request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    if not customer:
        raise HTTPException(403, "Customer profile required")
    return [address_view(db, a.address_id) for a in db.scalars(select(Address).where(Address.customer_id == customer.customer_id).order_by(Address.address_id.desc()).limit(50)).all()]


@app.post("/api/addresses", status_code=201)
def create_address(payload: AddressIn, request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    if not customer:
        raise HTTPException(403, "Customer profile required")
    from .services import new_id
    address = Address(address_id=new_id(db, Address, "address_id", "OBUADR"), customer_id=customer.customer_id, address_role="DESTINATION", line1=payload.line1.strip(), city=payload.city.strip(), state=payload.state.strip(), postal_code=payload.postal_code.strip(), country=payload.country.upper(), contact_name=payload.contact_name.strip(), contact_phone=payload.contact_phone.strip())
    db.add(address)
    db.commit()
    return address_view(db, address.address_id)


@app.get("/api/shipments")
def list_shipments(request: Request, search: str | None = Query(default=None), db: Session = Depends(get_db)):
    user = required_user(request, db)
    staff = staff_for(db, user)
    stmt = select(Shipment).order_by(Shipment.booking_date.desc()).limit(100)
    if not staff:
        customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
        if not customer:
            return []
        stmt = stmt.where(Shipment.customer_id == customer.customer_id)
    elif staff.role_code == "DELIVERY_AGENT":
        own_delivery_shipments = select(ShipmentAssignment.shipment_id).where(
            ShipmentAssignment.staff_id == staff.staff_id,
            ShipmentAssignment.task_type_code == "DELIVERY",
        )
        stmt = stmt.where(Shipment.shipment_id.in_(own_delivery_shipments))
    if search:
        stmt = stmt.where(Shipment.tracking_id.ilike(f"%{search.strip()}%"))
    return [shipment_view(db, s, include_private=bool(staff)) for s in db.scalars(stmt).all()]


@app.post("/api/shipments", status_code=201)
def book_shipment(payload: BookingIn, request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    if payload.payment_mode == "DEMO" and not demo_online_enabled():
        raise HTTPException(400, "Simulated checkout is disabled; choose cash or configured Razorpay test checkout")
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    if not customer:
        raise HTTPException(403, "Customer profile required")
    idempotency_key = request.headers.get("Idempotency-Key", "").strip()
    if not idempotency_key or len(idempotency_key) > 100:
        raise HTTPException(400, "A valid Idempotency-Key is required. Please retry from the booking form.")
    existing = db.get(BookingIdempotency, idempotency_key)
    if existing:
        if existing.user_id != user.user_id:
            raise HTTPException(409, "This booking request key has already been used.")
        prior = db.get(Shipment, existing.shipment_id)
        tracking = f" Tracking ID: {prior.tracking_id}." if prior else ""
        raise HTTPException(409, f"You have already placed this order.{tracking}")
    try:
        shipment = create_booking(db, customer, user, payload.sender.model_dump(), payload.receiver.model_dump(), payload.model_dump())
        db.add(BookingIdempotency(idempotency_key=idempotency_key, user_id=user.user_id, shipment_id=shipment.shipment_id, created_at=datetime.now(timezone.utc)))
        auto_assign_task(db, shipment, "PICKUP")
        db.commit()
        db.refresh(shipment)
        return shipment_view(db, shipment)
    except IntegrityError as exc:
        db.rollback()
        # Handles simultaneous retries: the unique key means only one transaction wins.
        existing = db.get(BookingIdempotency, idempotency_key)
        if existing and existing.user_id == user.user_id:
            prior = db.get(Shipment, existing.shipment_id)
            tracking = f" Tracking ID: {prior.tracking_id}." if prior else ""
            raise HTTPException(409, f"You have already placed this order.{tracking}")
        raise HTTPException(409, "The booking could not be recorded because it conflicts with an existing order.") from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(409, str(exc))


@app.post("/api/pricing/quote")
def pricing_quote(payload: PriceQuoteIn, request: Request, db: Session = Depends(get_db)):
    required_user(request, db)
    try:
        subtotal, rule = price_for_weight(db, payload.delivery_type_code, payload.destination_zone, payload.weight_kg)
        pricing = apply_shipping_offers(subtotal, rule.currency)
        return {"amount": str(pricing["total"]), "subtotal": str(pricing["subtotal"]), "discount": str(pricing["discount"]), "discounts": [{**offer, "amount": str(offer["amount"])} for offer in pricing["discounts"]], "currency": rule.currency.strip(), "delivery_type_code": payload.delivery_type_code, "weight_kg": str(payload.weight_kg), "pricing_rule_version": rule.version}
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/public/pricing/quote")
def public_pricing_quote(payload: PriceQuoteIn, db: Session = Depends(get_db)):
    """Return the exact post-offer charge produced by the booking rule."""
    try:
        subtotal, rule = price_for_weight(db, payload.delivery_type_code, payload.destination_zone, payload.weight_kg)
        pricing = apply_shipping_offers(subtotal, rule.currency)
        return {"amount": str(pricing["total"]), "subtotal": str(pricing["subtotal"]), "discount": str(pricing["discount"]), "discounts": [{**offer, "amount": str(offer["amount"])} for offer in pricing["discounts"]], "total": str(pricing["total"]), "tax": "0.00", "currency": rule.currency.strip(), "delivery_type_code": payload.delivery_type_code, "weight_kg": str(payload.weight_kg), "pricing_rule_version": rule.version, "is_final_charge": True}
    except ValueError as exc:
        raise HTTPException(409, str(exc))


@app.get("/api/shipments/{shipment_id}")
def get_shipment(shipment_id: str, request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    shipment = db.get(Shipment, shipment_id)
    staff = staff_for(db, user)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    if not shipment or (staff and not delivery_agent_owns_shipment(db, staff, shipment_id)) or (not staff and (not customer or shipment.customer_id != customer.customer_id)):
        raise HTTPException(404, "Shipment not found")
    return shipment_view(db, shipment, include_private=True)


@app.get("/api/shipments/{shipment_id}/tracking")
def shipment_tracking_detail(shipment_id: str, request: Request, db: Session = Depends(get_db)):
    """Return the authenticated shipment journey, including all recorded GPS points and warehouse receipts."""
    user = required_user(request, db)
    shipment = db.get(Shipment, shipment_id)
    staff = staff_for(db, user)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    if not shipment or (staff and not delivery_agent_owns_shipment(db, staff, shipment_id)) or (not staff and (not customer or shipment.customer_id != customer.customer_id)):
        raise HTTPException(404, "Shipment not found")

    locations = db.scalars(
        select(LocationUpdate)
        .where(LocationUpdate.shipment_id == shipment_id)
        .order_by(LocationUpdate.recorded_at, LocationUpdate.location_id)
    ).all()
    location_by_id = {location.location_id: location for location in locations}
    history = db.scalars(
        select(ShipmentStatusHistory)
        .where(ShipmentStatusHistory.shipment_id == shipment_id)
        .order_by(ShipmentStatusHistory.sequence_no)
    ).all()
    movement_events = []
    history_location_ids = set()
    for event in history:
        location = location_by_id.get(event.location_id)
        if location:
            history_location_ids.add(location.location_id)
        address = None
        if event.new_status == "PICKED_UP":
            address = "sender"
        elif event.new_status == "DELIVERED":
            address = "receiver"
        movement_events.append({
            "kind": "STATUS",
            "status": event.new_status,
            "event_at": event.event_at.isoformat(),
            "location_text": location.location_text if location else None,
            "address_role": address,
            "scan_type": location.scan_type if location else None,
            "remarks": event.remarks,
        })
    for location in locations:
        if location.location_id in history_location_ids:
            continue
        event = {
            "kind": "GPS" if location.scan_type.upper() == "GPS" else "LOCATION",
            "event_at": location.recorded_at.isoformat(),
            "scan_type": location.scan_type,
            "remarks": "Courier GPS point recorded" if location.scan_type.upper() == "GPS" else "Additional location scan recorded",
        }
        if location.scan_type.upper() == "GPS":
            coordinates = parse_gps_location(location.location_text)
            if coordinates:
                event.update({"latitude": coordinates[0], "longitude": coordinates[1]})
        else:
            event["location_text"] = location.location_text
        movement_events.append(event)
    movement_events.sort(key=lambda event: datetime.fromisoformat(event["event_at"]))

    warehouse_rows = db.execute(
        select(WarehouseScan, Hub)
        .join(Hub, WarehouseScan.hub_id == Hub.hub_id)
        .where(WarehouseScan.shipment_id == shipment_id)
        .order_by(WarehouseScan.scanned_at, WarehouseScan.scan_id)
    ).all()
    warehouse_scans = [{
        "scan_id": scan.scan_id,
        "scan_type": scan.scan_type,
        "scanned_at": scan.scanned_at.isoformat(),
        "hub_id": hub.hub_id,
        "hub_name": hub.name,
        "city": hub.city,
        "state": hub.state,
        "postal_code": hub.postal_code,
    } for scan, hub in warehouse_rows]

    data = shipment_view(db, shipment, include_private=True)
    data["delivery_assessment"] = delivery_assessment(shipment)
    data["latest_location"] = latest_gps_location(db, shipment_id)
    data["movement_events"] = movement_events
    data["warehouse_scans"] = warehouse_scans
    proof = db.scalar(select(ProofOfDelivery).where(ProofOfDelivery.shipment_id == shipment_id))
    data["delivery_proof"] = ({
        "otp_verified": proof.otp_verified,
        "captured_at": proof.captured_at.isoformat(),
        "remarks": proof.remarks,
    } if proof else None)
    return data


@app.get("/api/shipments/tracking/{tracking_id}")
def shipment_tracking_by_tracking_id(tracking_id: str, request: Request, db: Session = Depends(get_db)):
    """Look up the authenticated detail view using a customer-facing tracking ID."""
    user = required_user(request, db)
    shipment = db.scalar(select(Shipment).where(Shipment.tracking_id == tracking_id.strip().upper()))
    staff = staff_for(db, user)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    if not shipment or (not staff and (not customer or shipment.customer_id != customer.customer_id)):
        raise HTTPException(404, "Shipment not found")
    return shipment_tracking_detail(shipment.shipment_id, request, db)


@app.get("/api/track/{tracking_id}")
def track(tracking_id: str, db: Session = Depends(get_db)):
    result = public_tracking(db, tracking_id)
    if not result:
        raise HTTPException(404, "Tracking ID not found")
    return result


@app.get("/api/shipments/{shipment_id}/assessment")
def shipment_assessment(shipment_id: str, request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    shipment = db.get(Shipment, shipment_id)
    staff = staff_for(db, user)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    if not shipment or (not staff and (not customer or shipment.customer_id != customer.customer_id)):
        raise HTTPException(404, "Shipment not found")
    return {"shipment_id": shipment.shipment_id, "tracking_id": shipment.tracking_id, "assessment": delivery_assessment(shipment)}


@app.get("/api/shipments/{shipment_id}/locations/latest")
def shipment_latest_location(shipment_id: str, request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    shipment = db.get(Shipment, shipment_id)
    staff = staff_for(db, user)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    if not shipment or (not staff and (not customer or shipment.customer_id != customer.customer_id)):
        raise HTTPException(404, "Shipment not found")
    return {"shipment_id": shipment_id, "latest_location": latest_gps_location(db, shipment_id)}


@app.post("/api/routes/optimize")
def route_optimize(payload: RouteOptimizeIn, request: Request, db: Session = Depends(get_db)):
    required_staff(request, db, {"ADMINISTRATOR", "OPERATIONS_MANAGER", "BOOKING_OFFICER", "WAREHOUSE_OFFICER"})
    stops = [stop.model_dump() for stop in payload.stops]
    return optimize_route({"latitude": payload.start_latitude, "longitude": payload.start_longitude}, stops)


def razorpay_test_keys_ready() -> bool:
    return os.getenv("RAZORPAY_MODE", "test").strip().lower() == "test" and os.getenv("RAZORPAY_KEY_ID", "").strip().startswith("rzp_test_") and bool(os.getenv("RAZORPAY_KEY_SECRET", "").strip())


def demo_online_enabled() -> bool:
    return os.getenv("DEMO_ONLINE_ENABLED", "false").strip().lower() == "true" and os.getenv("OPTIGO_ENV", "development").strip().lower() in {"development", "demo"}


@app.get("/api/payments/options")
def payment_options(request: Request, db: Session = Depends(get_db)):
    required_user(request, db)
    demo_enabled = demo_online_enabled()
    return {
        "cash_available": True,
        "demo_online_available": demo_enabled,
        "razorpay_available": razorpay_test_keys_ready(),
        "razorpay_mode": os.getenv("RAZORPAY_MODE", "test"),
    }


@app.post("/api/payments/demo/complete")
def complete_demo_payment(payload: DemoPaymentIn, request: Request, db: Session = Depends(get_db)):
    """Confirm a no-charge demo checkout without creating a financial payment."""
    user = required_user(request, db)
    if not demo_online_enabled():
        raise HTTPException(404, "Simulated checkout is not enabled")
    shipment = db.get(Shipment, payload.shipment_id)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    staff = staff_for(db, user)
    if not shipment or (not staff and (not customer or shipment.customer_id != customer.customer_id)):
        raise HTTPException(404, "Shipment not found")
    invoice = db.scalar(select(Invoice).where(Invoice.shipment_id == shipment.shipment_id).order_by(Invoice.issued_at.desc()))
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    if invoice.preferred_payment_mode != "DEMO":
        raise HTTPException(409, "This invoice is not set up for online payment")
    if invoice.payment_status_code == "PAID":
        raise HTTPException(409, "This invoice has already been paid")
    return {
        "simulated": True,
        "provider": "demo",
        "invoice_no": invoice.invoice_no,
        "payment_status": invoice.payment_status_code,
        "message": "Demo checkout completed. No money was charged, transferred, or recorded.",
    }


@app.post("/api/payments/razorpay/order")
def razorpay_order(payload: RazorpayOrderIn, request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    shipment = db.get(Shipment, payload.shipment_id)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    staff = staff_for(db, user)
    if not shipment or (not staff and (not customer or shipment.customer_id != customer.customer_id)):
        raise HTTPException(404, "Shipment not found")
    invoice = db.scalar(select(Invoice).where(Invoice.shipment_id == shipment.shipment_id).order_by(Invoice.issued_at.desc()))
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    if invoice.preferred_payment_mode != "RAZORPAY" or invoice.payment_status_code == "PAID":
        raise HTTPException(409, "This invoice is not awaiting an online payment")
    amount_paise = int(Decimal(str(invoice.total)) * 100)
    key_id, key_secret = os.getenv("RAZORPAY_KEY_ID", "").strip(), os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not razorpay_test_keys_ready():
        raise HTTPException(503, "Razorpay test checkout is unavailable until test keys are configured. Choose cash for now.")
    import httpx
    try:
        response = httpx.post("https://api.razorpay.com/v1/orders", auth=(key_id, key_secret), json={"amount": amount_paise, "currency": invoice.currency.strip(), "receipt": invoice.invoice_no, "notes": {"shipment_id": shipment.shipment_id}}, timeout=15)
        response.raise_for_status()
        order = response.json()
    except Exception as exc:
        raise HTTPException(502, f"Razorpay test order could not be created: {exc}")
    return {"provider": "razorpay", "mode": os.getenv("RAZORPAY_MODE", "test"), "key_id": key_id, "order_id": order["id"], "amount": order["amount"], "currency": order["currency"], "shipment_id": shipment.shipment_id}


@app.post("/api/payments/razorpay/verify")
def razorpay_verify(payload: RazorpayVerifyIn, request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    shipment = db.get(Shipment, payload.shipment_id)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    staff = staff_for(db, user)
    if not shipment or (not staff and (not customer or shipment.customer_id != customer.customer_id)):
        raise HTTPException(404, "Shipment not found")
    invoice = db.scalar(select(Invoice).where(Invoice.shipment_id == shipment.shipment_id).order_by(Invoice.issued_at.desc()))
    if not invoice:
        raise HTTPException(404, "Invoice not found")
    if invoice.preferred_payment_mode != "RAZORPAY" or invoice.payment_status_code == "PAID":
        raise HTTPException(409, "This invoice is not awaiting an online payment")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not razorpay_test_keys_ready() or payload.order_id.startswith("local_order_"):
        raise HTTPException(503, "A signed Razorpay test payment is required")
    expected = hmac.new(key_secret.encode(), f"{payload.order_id}|{payload.payment_id}".encode(), hashlib.sha256).hexdigest()
    verified = hmac.compare_digest(expected, payload.signature)
    if not verified:
        raise HTTPException(400, "Razorpay payment signature is invalid")
    import httpx
    try:
        auth = (os.getenv("RAZORPAY_KEY_ID", "").strip(), key_secret)
        order_response = httpx.get(f"https://api.razorpay.com/v1/orders/{payload.order_id}", auth=auth, timeout=15)
        payment_response = httpx.get(f"https://api.razorpay.com/v1/payments/{payload.payment_id}", auth=auth, timeout=15)
        order_response.raise_for_status()
        payment_response.raise_for_status()
        order, payment = order_response.json(), payment_response.json()
    except Exception as exc:
        raise HTTPException(502, "Razorpay could not confirm this payment") from exc
    expected_paise = int(Decimal(str(invoice.total)) * 100)
    if order.get("receipt") != invoice.invoice_no or order.get("amount") != expected_paise or order.get("currency") != invoice.currency.strip() or order.get("status") != "paid" or payment.get("order_id") != payload.order_id or payment.get("amount") != expected_paise or payment.get("currency") != invoice.currency.strip() or payment.get("status") != "captured":
        raise HTTPException(409, "Razorpay payment does not match this invoice or is not captured")
    invoice.payment_status_code = "PAID"
    shipment.payment_amount = invoice.total
    db.commit()
    return {"verified": True, "provider": "razorpay", "invoice_no": invoice.invoice_no, "payment_status": invoice.payment_status_code}


@app.get("/api/reports/delays")
def delayed_shipments(request: Request, db: Session = Depends(get_db)):
    user, _ = required_staff(request, db)
    rows = db.scalars(select(Shipment).where(Shipment.current_status.not_in(["DELIVERED", "CANCELLED", "RETURNED"]), Shipment.expected_delivery < date.today()).order_by(Shipment.expected_delivery)).all()
    return {"account": account_view(db, user), "checked_on": date.today().isoformat(), "total_delayed": len(rows), "shipments": [{"shipment_id": row.shipment_id, "tracking_id": row.tracking_id, "status": row.current_status, "assessment": delivery_assessment(row)} for row in rows]}


@app.get("/api/tasks")
def tasks(request: Request, db: Session = Depends(get_db)):
    user, staff = required_staff(request, db)
    stmt = select(ShipmentAssignment).order_by(ShipmentAssignment.assigned_at.desc()).limit(200)
    if staff.role_code not in {"ADMINISTRATOR", "OPERATIONS_MANAGER"}:
        stmt = stmt.where(ShipmentAssignment.staff_id == staff.staff_id)
    result = []
    for a in db.scalars(stmt).all():
        s = db.get(Shipment, a.shipment_id)
        result.append({"assignment_id": a.assignment_id, "shipment_id": a.shipment_id, "tracking_id": s.tracking_id if s else None, "task_type_code": a.task_type_code, "status_code": a.status_code, "shipment_status": s.current_status if s else None, "staff_id": a.staff_id, "assigned_at": a.assigned_at.isoformat(), "scheduled_reference_at": a.completed_at.isoformat(), "completed_at": a.completed_at.isoformat() if a.status_code in {"COMPLETED", "FAILED"} else None, "failure_reason": a.failure_reason if a.status_code == "FAILED" else None, "sender": address_view(db, s.sender_address_id) if s else {}, "receiver": address_view(db, s.receiver_address_id) if s else {}, "cash_due": str(s.cod_amount_due) if s else "0"})
    return {"account": account_view(db, user), "tasks": result}


@app.post("/api/assignments", status_code=201)
def create_assignment(payload: AssignmentIn, request: Request, db: Session = Depends(get_db)):
    user, manager = required_staff(request, db, {"ADMINISTRATOR", "OPERATIONS_MANAGER", "BOOKING_OFFICER", "WAREHOUSE_OFFICER"})
    shipment, assignee = db.get(Shipment, payload.shipment_id), db.get(Staff, payload.staff_id)
    if not shipment or not assignee or not assignee.active:
        raise HTTPException(404, "Shipment or active staff member not found")
    required_status = {"PICKUP": {"BOOKED", "CONFIRMED"}, "WAREHOUSE": {"PICKED_UP"}, "DELIVERY": {"IN_TRANSIT"}}
    if shipment.current_status not in required_status.get(payload.task_type_code, set()):
        raise HTTPException(409, f"A {payload.task_type_code.lower()} task cannot be assigned while this shipment is {shipment.current_status.lower()}")
    try:
        assignment = assign_task(db, shipment, assignee, manager, payload.task_type_code)
        return {"assignment_id": assignment.assignment_id, "status_code": assignment.status_code, "tracking_id": shipment.tracking_id}
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(409, str(exc))


def assignment_for(db: Session, assignment_id: str) -> ShipmentAssignment:
    assignment = db.get(ShipmentAssignment, assignment_id)
    if not assignment:
        raise HTTPException(404, "Assignment not found")
    return assignment


@app.post("/api/assignments/{assignment_id}/pickup-complete")
def pickup_complete(assignment_id: str, request: Request, db: Session = Depends(get_db)):
    actor = required_user(request, db)
    assignment = assignment_for(db, assignment_id)
    if assignment.task_type_code != "PICKUP":
        raise HTTPException(400, "This is not a pickup assignment")
    try:
        transition_assignment(db, assignment, actor, True, commit=False)
        auto_assign_task(db, db.get(Shipment, assignment.shipment_id), "WAREHOUSE")
        db.commit()
        return {"assignment_id": assignment_id, "status_code": "COMPLETED"}
    except (ValueError, PermissionError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(403 if isinstance(exc, PermissionError) else 409, str(exc))


@app.post("/api/assignments/{assignment_id}/pickup-failed")
def pickup_failed(assignment_id: str, payload: FailureIn, request: Request, db: Session = Depends(get_db)):
    actor = required_user(request, db)
    assignment = assignment_for(db, assignment_id)
    if assignment.task_type_code != "PICKUP":
        raise HTTPException(400, "This is not a pickup assignment")
    try:
        transition_assignment(db, assignment, actor, False, payload.reason)
        return {"assignment_id": assignment_id, "status_code": "FAILED", "reason": payload.reason}
    except (ValueError, PermissionError) as exc:
        raise HTTPException(403 if isinstance(exc, PermissionError) else 409, str(exc))


@app.post("/api/assignments/{assignment_id}/start-delivery")
def start_delivery(assignment_id: str, request: Request, db: Session = Depends(get_db)):
    actor = required_user(request, db)
    assignment = assignment_for(db, assignment_id)
    if assignment.task_type_code != "DELIVERY":
        raise HTTPException(400, "This is not a delivery assignment")
    staff = staff_for(db, actor)
    if not staff or (staff.staff_id != assignment.staff_id and staff.role_code not in {"ADMINISTRATOR", "OPERATIONS_MANAGER"}):
        raise HTTPException(403, "You are not authorized for this assignment")
    shipment = db.get(Shipment, assignment.shipment_id)
    try:
        add_location_and_history(db, shipment, actor, "OUT_FOR_DELIVERY", "Destination hub", "Delivery route started")
        assignment.status_code = "IN_PROGRESS"
        db.commit()
        return {"assignment_id": assignment_id, "status_code": assignment.status_code, "shipment_status": shipment.current_status}
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(409, str(exc))


@app.post("/api/assignments/{assignment_id}/otp")
def create_otp(assignment_id: str, request: Request, db: Session = Depends(get_db)):
    actor = required_user(request, db)
    assignment = assignment_for(db, assignment_id)
    staff = staff_for(db, actor)
    if not staff or staff.role_code != "DELIVERY_AGENT" or staff.staff_id != assignment.staff_id:
        raise HTTPException(403, "Only the assigned delivery agent can request an OTP")
    try:
        request_delivery_otp(db, assignment, actor, staff)
        return {"assignment_id": assignment_id, "expires_in_seconds": 600, "delivery_otp_requested": True, "delivery_channel": "customer_notifications"}
    except (ValueError, PermissionError) as exc:
        raise HTTPException(403 if isinstance(exc, PermissionError) else 409, str(exc))


@app.post("/api/assignments/{assignment_id}/deliver")
def deliver(assignment_id: str, payload: DeliveryIn, request: Request, db: Session = Depends(get_db)):
    actor = required_user(request, db)
    assignment = assignment_for(db, assignment_id)
    staff = staff_for(db, actor)
    if not staff or staff.role_code != "DELIVERY_AGENT" or staff.staff_id != assignment.staff_id:
        raise HTTPException(403, "Only the assigned delivery agent can verify the OTP")
    try:
        proof = verify_delivery(db, assignment, actor, payload.code, payload.remarks, payload.cash_collected, staff)
        return {"proof_id": proof.proof_id, "assignment_id": assignment_id, "status": "DELIVERED"}
    except (ValueError, PermissionError) as exc:
        raise HTTPException(403 if isinstance(exc, PermissionError) else 409, str(exc))


@app.post("/api/assignments/{assignment_id}/delivery-failed")
def delivery_failed(assignment_id: str, payload: FailureIn, request: Request, db: Session = Depends(get_db)):
    actor = required_user(request, db)
    assignment = assignment_for(db, assignment_id)
    staff = staff_for(db, actor)
    if not staff or (staff.staff_id != assignment.staff_id and staff.role_code not in {"ADMINISTRATOR", "OPERATIONS_MANAGER"}):
        raise HTTPException(403, "You are not authorized for this assignment")
    shipment = db.get(Shipment, assignment.shipment_id)
    try:
        add_location_and_history(db, shipment, actor, "DELIVERY_FAILED", "Delivery address", payload.reason)
        assignment.status_code = "FAILED"
        assignment.completed_at = datetime.now(timezone.utc)
        assignment.failure_reason = payload.reason
        db.commit()
        return {"assignment_id": assignment_id, "status": "DELIVERY_FAILED", "reason": payload.reason}
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(409, str(exc))


@app.post("/api/shipments/{shipment_id}/locations", status_code=201)
def add_location(shipment_id: str, payload: LocationIn, request: Request, db: Session = Depends(get_db)):
    actor, staff = required_staff(request, db)
    shipment = db.get(Shipment, shipment_id)
    if not shipment:
        raise HTTPException(404, "Shipment not found")
    if staff.role_code == "DELIVERY_AGENT" and not delivery_agent_owns_shipment(db, staff, shipment_id):
        raise HTTPException(403, "Delivery agents can only update their assigned deliveries")
    now = datetime.now(timezone.utc)
    from .services import new_id
    location_text = payload.location_text.strip()
    scan_type = payload.scan_type.upper()
    if scan_type == "GPS" or payload.latitude is not None or payload.longitude is not None:
        if payload.latitude is None or payload.longitude is None:
            raise HTTPException(400, "Both GPS coordinates are required")
        delivery_assignment = db.scalar(select(ShipmentAssignment).where(ShipmentAssignment.shipment_id == shipment_id, ShipmentAssignment.task_type_code == "DELIVERY"))
        if not delivery_assignment or delivery_assignment.staff_id != staff.staff_id or delivery_assignment.status_code != "IN_PROGRESS" or shipment.current_status != "OUT_FOR_DELIVERY":
            raise HTTPException(403, "Only the active assigned delivery agent can share GPS for this shipment")
        location_text = f"GPS: {payload.latitude:.6f}, {payload.longitude:.6f}"
        scan_type = "GPS"
    location = LocationUpdate(location_id=new_id(db, LocationUpdate, "location_id", "OBULOC"), shipment_id=shipment_id, recorded_at=now, location_text=location_text, scan_type=scan_type, recorded_by=actor.user_id)
    db.add(location)
    db.commit()
    return {"location_id": location.location_id, "recorded": True, "latest_location": latest_gps_location(db, shipment_id)}


@app.get("/api/reports/summary")
def report_summary(request: Request, db: Session = Depends(get_db)):
    user, _ = required_staff(request, db)
    counts = {status_code: count for status_code, count in db.execute(select(Shipment.current_status, func.count(Shipment.shipment_id)).group_by(Shipment.current_status)).all()}
    total_revenue = db.scalar(select(func.coalesce(func.sum(Invoice.total), 0))) or 0
    avg_days = db.scalar(select(func.avg(func.extract("epoch", Shipment.delivery_reference_at - Shipment.booking_date) / 86400)).where(Shipment.current_status == "DELIVERED"))
    return {"account": account_view(db, user), "total_shipments": sum(counts.values()), "by_status": counts, "invoice_total": str(total_revenue), "average_delivery_days": round(float(avg_days), 2) if avg_days is not None else None}


@app.get("/api/operations/lookups")
def operations_lookups(request: Request, db: Session = Depends(get_db)):
    required_staff(request, db, {"ADMINISTRATOR", "OPERATIONS_MANAGER", "BOOKING_OFFICER", "WAREHOUSE_OFFICER", "TRACKING_OFFICER"})
    return {"staff": [{"staff_id": s.staff_id, "employee_id": s.employee_id, "role_code": s.role_code, "department_code": s.department_code} for s in db.scalars(select(Staff).where(Staff.active.is_(True)).order_by(Staff.employee_id)).all()], "hubs": [{"hub_id": h.hub_id, "name": h.name, "city": h.city} for h in db.scalars(select(Hub).where(Hub.active.is_(True)).order_by(Hub.name)).all()], "routes": [{"route_id": r.route_id, "route_code": r.route_code, "destination_zone": r.destination_zone} for r in db.scalars(select(Route).where(Route.active.is_(True)).order_by(Route.route_code)).all()], "vehicles": [{"vehicle_id": v.vehicle_id, "registration_no": v.registration_no, "vehicle_type": v.vehicle_type} for v in db.scalars(select(Vehicle).where(Vehicle.active.is_(True)).order_by(Vehicle.vehicle_id)).all()]}


@app.get("/api/warehouse/scans")
def warehouse_scans(request: Request, db: Session = Depends(get_db)):
    required_staff(request, db, {"ADMINISTRATOR", "OPERATIONS_MANAGER", "WAREHOUSE_OFFICER"})
    rows = db.execute(select(WarehouseScan, Shipment).join(Shipment, Shipment.shipment_id == WarehouseScan.shipment_id).order_by(WarehouseScan.scanned_at.desc()).limit(100)).all()
    return [{"scan_id": scan.scan_id, "shipment_id": scan.shipment_id, "tracking_id": shipment.tracking_id, "hub_id": scan.hub_id, "scan_type": scan.scan_type, "scanned_at": scan.scanned_at.isoformat()} for scan, shipment in rows]


@app.get("/api/warehouse/in-transit")
def warehouse_in_transit(request: Request, db: Session = Depends(get_db)):
    required_staff(request, db, {"ADMINISTRATOR", "OPERATIONS_MANAGER", "WAREHOUSE_OFFICER"})
    rows = db.scalars(
        select(Shipment)
        .where(Shipment.current_status == "IN_TRANSIT")
        .order_by(Shipment.booking_date.desc())
        .limit(200)
    ).all()
    return [{
        "shipment_id": shipment.shipment_id,
        "tracking_id": shipment.tracking_id,
        "receiver": address_view(db, shipment.receiver_address_id),
    } for shipment in rows]


@app.post("/api/warehouse/scans")
def create_warehouse_scan(payload: WarehouseScanIn, request: Request, db: Session = Depends(get_db)):
    user, staff = required_staff(request, db, {"ADMINISTRATOR", "OPERATIONS_MANAGER", "WAREHOUSE_OFFICER"})
    shipment = db.get(Shipment, payload.shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found")
    hub = db.get(Hub, payload.hub_id)
    if hub is None or not hub.active:
        raise HTTPException(status_code=404, detail="Active hub not found")
    if shipment.current_status not in {"PICKED_UP", "IN_TRANSIT"}:
        raise HTTPException(status_code=409, detail="Warehouse arrivals can only be recorded before final delivery")
    first_receipt = shipment.current_status == "PICKED_UP"
    assignment = None
    if first_receipt:
        assignment = db.scalar(select(ShipmentAssignment).where(ShipmentAssignment.shipment_id == shipment.shipment_id, ShipmentAssignment.task_type_code == "WAREHOUSE"))
        if not assignment or assignment.status_code == "COMPLETED":
            raise HTTPException(status_code=409, detail="An active warehouse assignment is required")
        if staff.staff_id != assignment.staff_id and staff.role_code not in {"ADMINISTRATOR", "OPERATIONS_MANAGER"}:
            raise HTTPException(status_code=403, detail="This shipment is assigned to another warehouse officer")
    else:
        delivery_assignment = db.scalar(select(ShipmentAssignment).where(ShipmentAssignment.shipment_id == shipment.shipment_id, ShipmentAssignment.task_type_code == "DELIVERY"))
        if delivery_assignment and delivery_assignment.status_code == "IN_PROGRESS":
            raise HTTPException(status_code=409, detail="An inter-hub arrival cannot be recorded after final-mile delivery has started")
    if payload.scan_type.strip().upper() != "RECEIVED":
        raise HTTPException(status_code=400, detail="Record a RECEIVED scan to hand off the parcel")
    from .services import new_id
    row = WarehouseScan(scan_id=new_id(db, WarehouseScan, "scan_id", "OBUSCN", width=6), shipment_id=shipment.shipment_id, scan_type=payload.scan_type.strip().upper(), scanned_at=datetime.now(timezone.utc), hub_id=hub.hub_id, scanned_by=staff.staff_id)
    try:
        db.add(row)
        if first_receipt:
            add_location_and_history(db, shipment, user, "IN_TRANSIT", hub.name, "Received and dispatched from warehouse")
            assignment.status_code = "COMPLETED"
            assignment.completed_at = row.scanned_at
            assignment.failure_reason = "Completed successfully"
            auto_assign_task(db, shipment, "DELIVERY")
        else:
            hub_location = f"{hub.name}, {hub.city}, {hub.state} {hub.postal_code}"
            db.add(LocationUpdate(location_id=new_id(db, LocationUpdate, "location_id", "OBULOC"), shipment_id=shipment.shipment_id, recorded_at=row.scanned_at, location_text=hub_location, scan_type="WAREHOUSE", recorded_by=user.user_id))
        db.commit()
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc))
    return {"scan_id": row.scan_id, "shipment_id": row.shipment_id, "tracking_id": shipment.tracking_id, "hub_id": row.hub_id, "scan_type": row.scan_type, "scanned_at": row.scanned_at.isoformat(), "shipment_status": shipment.current_status, "next_task": "DELIVERY" if first_receipt else "IN_TRANSIT"}


@app.get("/api/finance/summary")
def finance_summary(request: Request, db: Session = Depends(get_db)):
    required_staff(request, db, {"ADMINISTRATOR", "OPERATIONS_MANAGER", "ACCOUNTS_OFFICER"})
    return {"invoices": db.scalar(select(func.count(Invoice.invoice_no))) or 0, "invoice_total": str(db.scalar(select(func.coalesce(func.sum(Invoice.total), 0))) or 0), "payments": db.scalar(select(func.count(Invoice.invoice_no)).where(Invoice.payment_status_code == "PAID")) or 0, "payments_total": str(db.scalar(select(func.coalesce(func.sum(Invoice.total), 0)).where(Invoice.payment_status_code == "PAID")) or 0), "refunds": db.scalar(select(func.count(Refund.refund_id))) or 0}


@app.get("/api/finance/invoices")
def finance_invoices(request: Request, db: Session = Depends(get_db)):
    required_staff(request, db, {"ADMINISTRATOR", "OPERATIONS_MANAGER", "ACCOUNTS_OFFICER"})
    rows = db.execute(select(Invoice, Shipment).join(Shipment, Invoice.shipment_id == Shipment.shipment_id).order_by(Invoice.issued_at.desc()).limit(100)).all()
    return {"invoices": [{"invoice_no": invoice.invoice_no, "shipment_id": shipment.shipment_id, "tracking_id": shipment.tracking_id, "issued_at": invoice.issued_at.isoformat(), "total": str(invoice.total), "currency": invoice.currency.strip(), "payment_mode": invoice.preferred_payment_mode or "UNSPECIFIED", "payment_status": invoice.payment_status_code, "cash_due": str(shipment.cod_amount_due)} for invoice, shipment in rows]}


@app.get("/api/finance/workbench")
def finance_workbench(
    request: Request,
    period_start: date | None = Query(default=None),
    period_end: date | None = Query(default=None),
    as_of: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Operational finance workbench; deliberately not a statutory ledger."""
    required_staff(request, db, {"ADMINISTRATOR", "OPERATIONS_MANAGER", "ACCOUNTS_OFFICER"})
    today = date.today()
    period_end = period_end or today
    period_start = period_start or period_end.replace(day=1)
    as_of = as_of or today
    if period_start > period_end:
        raise HTTPException(422, "Period start must be on or before period end")

    range_start = datetime(period_start.year, period_start.month, period_start.day, tzinfo=timezone.utc)
    day_after_end = period_end + timedelta(days=1)
    range_end = datetime(day_after_end.year, day_after_end.month, day_after_end.day, tzinfo=timezone.utc)
    invoices = db.scalars(select(Invoice).where(Invoice.issued_at >= range_start, Invoice.issued_at < range_end).order_by(Invoice.issued_at.desc())).all()
    inr_invoices = [row for row in invoices if row.currency.strip().upper() == "INR"]
    other_income_rows = db.scalars(select(FinanceTransaction).where(FinanceTransaction.entry_type == "OTHER_INCOME", FinanceTransaction.entry_date >= period_start, FinanceTransaction.entry_date <= period_end)).all()
    expense_rows = db.scalars(select(FinanceTransaction).where(FinanceTransaction.entry_type == "EXPENSE", FinanceTransaction.entry_date >= period_start, FinanceTransaction.entry_date <= period_end)).all()
    recognized_refund_statuses = {"COMPLETED", "PROCESSED", "REFUNDED", "SUCCESS", "SUCCEEDED"}
    refund_rows = db.scalars(select(Refund).where(Refund.processed_at >= range_start, Refund.processed_at < range_end)).all()
    completed_refunds = [row for row in refund_rows if row.status_code.strip().upper() in recognized_refund_statuses]
    closed_refund_statuses = recognized_refund_statuses | {"FAILED", "CANCELLED", "REJECTED"}
    refund_review_count = db.scalar(select(func.count(Refund.refund_id)).where(Refund.status_code.not_in(closed_refund_statuses))) or 0
    refund_review_rows = db.execute(select(Refund, Payment, Invoice, Shipment).join(Payment, Payment.payment_id == Refund.payment_id).join(Invoice, Invoice.invoice_no == Payment.invoice_no).join(Shipment, Shipment.shipment_id == Invoice.shipment_id).where(Refund.status_code.not_in(closed_refund_statuses)).order_by(Refund.processed_at.desc()).limit(20)).all()
    money_zero = Decimal("0.00")
    billed = sum((row.total for row in inr_invoices), money_zero)
    other_income = sum((row.amount for row in other_income_rows), money_zero)
    expenses = sum((row.amount for row in expense_rows), money_zero)
    refunds = sum((row.amount for row in completed_refunds), money_zero)
    net_profit_loss = billed + other_income - refunds - expenses

    unpaid = db.scalars(select(Invoice).where(Invoice.payment_status_code != "PAID").order_by(Invoice.issued_at.desc())).all()
    paid_in_period = [row for row in inr_invoices if row.payment_status_code == "PAID"]
    unsettled_cod_filter = CodCollection.settlement_status_code.not_in(["SETTLED", "COMPLETED"])
    open_cod_count = db.scalar(select(func.count(CodCollection.collection_id)).where(unsettled_cod_filter)) or 0
    open_cod_total = db.scalar(select(func.coalesce(func.sum(CodCollection.amount), 0)).where(unsettled_cod_filter)) or money_zero
    open_cod = db.execute(select(CodCollection, Shipment).join(Shipment, Shipment.shipment_id == CodCollection.shipment_id).where(unsettled_cod_filter).order_by(CodCollection.collected_at.desc()).limit(20)).all()

    positions = db.scalars(select(FinancePosition).where(FinancePosition.balance_date <= as_of).order_by(FinancePosition.balance_date.desc(), FinancePosition.recorded_at.desc())).all()
    latest_by_account = {}
    for row in positions:
        key = (row.position_type, row.category, row.account_name.casefold())
        latest_by_account.setdefault(key, row)
    asset_positions = [row for row in latest_by_account.values() if row.position_type == "ASSET"]
    liability_positions = [row for row in latest_by_account.values() if row.position_type == "LIABILITY"]
    assets = sum((row.amount for row in asset_positions), money_zero)
    liabilities = sum((row.amount for row in liability_positions), money_zero)
    equity = assets - liabilities
    recent_transactions = db.scalars(select(FinanceTransaction).order_by(FinanceTransaction.entry_date.desc(), FinanceTransaction.recorded_at.desc()).limit(20)).all()

    return {
        "period_start": period_start.isoformat(), "period_end": period_end.isoformat(), "as_of": as_of.isoformat(),
        "pnl": {
            "shipping_revenue_billed": str(billed), "other_income": str(other_income),
            "completed_refunds": str(refunds), "operating_expenses": str(expenses),
            "net_profit_loss": str(net_profit_loss), "invoice_count": len(inr_invoices),
            "other_currency_invoice_count": len(invoices) - len(inr_invoices),
        },
        "collections": {
            "paid_invoice_count": len(paid_in_period), "paid_invoice_total": str(sum((row.total for row in paid_in_period), money_zero)),
            "unpaid_invoice_count": len(unpaid), "unpaid_invoice_total": str(sum((row.total for row in unpaid if row.currency.strip().upper() == "INR"), money_zero)),
            "pending_refund_count": refund_review_count,
            "open_cod_settlement_count": open_cod_count,
            "open_cod_settlement_total": str(open_cod_total),
        },
        "balance_sheet": {
            "assets": str(assets), "liabilities": str(liabilities), "equity": str(equity),
            "asset_positions": [{"position_type": row.position_type, "category": row.category, "account_name": row.account_name, "amount": str(row.amount), "balance_date": row.balance_date.isoformat(), "notes": row.notes} for row in asset_positions],
            "liability_positions": [{"position_type": row.position_type, "category": row.category, "account_name": row.account_name, "amount": str(row.amount), "balance_date": row.balance_date.isoformat(), "notes": row.notes} for row in liability_positions],
        },
        "unpaid_invoices": [{"invoice_no": row.invoice_no, "shipment_id": shipment.shipment_id, "tracking_id": shipment.tracking_id, "total": str(row.total), "currency": row.currency.strip(), "payment_mode": row.preferred_payment_mode or "UNSPECIFIED", "issued_at": row.issued_at.isoformat(), "payment_status": row.payment_status_code} for row, shipment in db.execute(select(Invoice, Shipment).join(Shipment, Shipment.shipment_id == Invoice.shipment_id).where(Invoice.payment_status_code != "PAID").order_by(Invoice.issued_at.desc()).limit(20)).all()],
        "open_cod_settlements": [{"shipment_id": shipment.shipment_id, "tracking_id": shipment.tracking_id, "amount": str(row.amount), "status": row.settlement_status_code, "collected_at": row.collected_at.isoformat(), "reference": row.settlement_reference} for row, shipment in open_cod],
        "refund_review_queue": [{"refund_id": refund.refund_id, "shipment_id": shipment.shipment_id, "tracking_id": shipment.tracking_id, "amount": str(refund.amount), "status": refund.status_code, "reason": refund.reason, "reference": refund.reference_no, "processed_at": refund.processed_at.isoformat()} for refund, _payment, _invoice, shipment in refund_review_rows],
        "recent_transactions": [{"entry_id": row.entry_id, "entry_type": row.entry_type, "category": row.category, "description": row.description, "amount": str(row.amount), "entry_date": row.entry_date.isoformat(), "reference_no": row.reference_no} for row in recent_transactions],
        "categories": {"transactions": {key: sorted(value) for key, value in FINANCE_TRANSACTION_CATEGORIES.items()}, "positions": {key: sorted(value) for key, value in FINANCE_POSITION_CATEGORIES.items()}},
    }


@app.post("/api/finance/transactions", status_code=201)
def create_finance_transaction(payload: FinanceTransactionIn, request: Request, db: Session = Depends(get_db)):
    _user, staff = required_staff(request, db, {"ADMINISTRATOR", "ACCOUNTS_OFFICER"})
    if payload.category not in FINANCE_TRANSACTION_CATEGORIES[payload.entry_type]:
        raise HTTPException(422, "Choose a category that matches this income or expense type")
    reference = payload.reference_no.strip() if payload.reference_no else None
    if reference and db.scalar(select(FinanceTransaction).where(FinanceTransaction.entry_type == payload.entry_type, FinanceTransaction.reference_no == reference)):
        raise HTTPException(409, "That reference has already been recorded for this entry type")
    row = FinanceTransaction(entry_id=new_id(db, FinanceTransaction, "entry_id", "OBUFIN", width=10), entry_type=payload.entry_type, category=payload.category, description=payload.description.strip(), amount=payload.amount, currency="INR", entry_date=payload.entry_date, reference_no=reference, recorded_at=datetime.now(timezone.utc), recorded_by_id=staff.staff_id)
    db.add(row)
    db.commit()
    return {"entry_id": row.entry_id, "entry_type": row.entry_type, "category": row.category, "amount": str(row.amount), "currency": row.currency.strip(), "entry_date": row.entry_date.isoformat(), "reference_no": row.reference_no}


@app.post("/api/finance/positions", status_code=201)
def record_finance_position(payload: FinancePositionIn, request: Request, db: Session = Depends(get_db)):
    _user, staff = required_staff(request, db, {"ADMINISTRATOR", "ACCOUNTS_OFFICER"})
    if payload.category not in FINANCE_POSITION_CATEGORIES[payload.position_type]:
        raise HTTPException(422, "Choose a balance-sheet category that matches asset or liability")
    row = FinancePosition(position_id=new_id(db, FinancePosition, "position_id", "OBUFP", width=10), position_type=payload.position_type, category=payload.category, account_name=payload.account_name.strip(), amount=payload.amount, currency="INR", balance_date=payload.balance_date, notes=payload.notes.strip(), recorded_at=datetime.now(timezone.utc), recorded_by_id=staff.staff_id)
    db.add(row)
    db.commit()
    return {"position_id": row.position_id, "position_type": row.position_type, "account_name": row.account_name, "amount": str(row.amount), "currency": row.currency.strip(), "balance_date": row.balance_date.isoformat()}


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    return __import__("fastapi.responses", fromlist=["JSONResponse"]).JSONResponse(status_code=409, content={"detail": "The request violates a database data-integrity rule"})
