from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import hashlib
import hmac
import os

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

from .db import get_db
from .models import Address, AssignmentStatus, Complaint, Customer, DeliveryType, Hub, Invoice, LocationUpdate, Notification, Payment, PricingRule, Refund, Route, Shipment, ShipmentAssignment, ShipmentStatusHistory, Staff, StaffRole, User, Vehicle, WarehouseScan
from .security import hash_password, verify_password
from .services import add_location_and_history, assign_task, create_booking, delivery_assessment, haversine_km, latest_gps_location, new_id, optimize_route, public_tracking, request_delivery_otp, transition_assignment, verify_delivery

app = FastAPI(title="OptiGo Courier Tracking API", version="1.0.0", description="OptiGo backend connected to the configured PostgreSQL database.")
origins = [x.strip() for x in os.getenv("FRONTEND_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if x.strip()]
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "change-this-session-secret"), same_site="lax", https_only=os.getenv("COOKIE_SECURE", "false").lower() == "true")
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


class AuthIn(BaseModel):
    email: str = Field(min_length=5, max_length=254)
    password: str = Field(min_length=8, max_length=200)


class RegisterIn(AuthIn):
    name: str = Field(min_length=2, max_length=120)
    phone: str = Field(min_length=7, max_length=30)


class AddressIn(BaseModel):
    line1: str = Field(min_length=2, max_length=300)
    city: str = Field(min_length=2, max_length=100)
    state: str = Field(min_length=2, max_length=100)
    postal_code: str = Field(min_length=3, max_length=20)
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


class RazorpayVerifyIn(BaseModel):
    shipment_id: str = Field(min_length=3, max_length=50)
    order_id: str = Field(min_length=3, max_length=100)
    payment_id: str = Field(min_length=3, max_length=100)
    signature: str = Field(min_length=3, max_length=200)


class DeliveryIn(BaseModel):
    code: str = Field(min_length=6, max_length=6)
    remarks: str = Field(default="OTP verified", max_length=500)


class FailureIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class ComplaintIn(BaseModel):
    shipment_id: str | None = None
    subject: str = Field(min_length=3, max_length=150)
    description: str = Field(min_length=5, max_length=4000)


class ComplaintUpdateIn(BaseModel):
    status_code: str = Field(pattern="^(OPEN|IN_PROGRESS|RESOLVED|CLOSED)$")


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


def required_staff(request: Request, db: Session, roles: set[str] | None = None) -> tuple[User, Staff]:
    user = required_user(request, db)
    staff = staff_for(db, user)
    if not staff or (roles and staff.role_code not in roles):
        raise HTTPException(status_code=403, detail="Your role is not authorized for this operation")
    return user, staff


def account_view(db: Session, user: User) -> dict:
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    staff = staff_for(db, user)
    return {"user_id": user.user_id, "name": user.name, "email": user.email, "phone": user.phone, "role": staff.role_code if staff else "CUSTOMER", "department": staff.department_code if staff else None, "customer_id": customer.customer_id if customer else None, "staff_id": staff.staff_id if staff else None}


def address_view(db: Session, address_id: str) -> dict:
    address = db.get(Address, address_id)
    if not address:
        return {}
    return {"address_id": address.address_id, "address_role": address.address_role, "line1": address.line1, "city": address.city, "state": address.state, "postal_code": address.postal_code, "country": address.country.strip(), "contact_name": address.contact_name, "contact_phone": address.contact_phone}


def shipment_view(db: Session, shipment: Shipment, include_private: bool = True) -> dict:
    data = {"shipment_id": shipment.shipment_id, "tracking_id": shipment.tracking_id, "customer_id": shipment.customer_id, "status": shipment.current_status, "delivery_type_code": shipment.delivery_type_code, "delivery_mode": shipment.delivery_mode, "parcel_type": shipment.parcel_type, "weight_kg": str(shipment.weight_kg), "dimensions_cm": {"length": str(shipment.length_cm), "width": str(shipment.width_cm), "height": str(shipment.height_cm)}, "charge": str(shipment.charge), "currency": shipment.currency.strip(), "payment_amount": str(shipment.payment_amount), "cod_amount_due": str(shipment.cod_amount_due), "fragile": shipment.fragile, "priority": shipment.priority, "booking_date": shipment.booking_date.isoformat(), "expected_delivery": shipment.expected_delivery.isoformat()}
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


def complaint_view(complaint: Complaint) -> dict:
    return {
        "complaint_id": complaint.complaint_id,
        "customer_id": complaint.customer_id,
        "shipment_id": complaint.shipment_id,
        "subject": complaint.subject,
        "description": complaint.description,
        "status_code": complaint.status_code,
        "created_at": complaint.created_at.isoformat(),
        "resolved_at": complaint.resolved_at.isoformat() if complaint.resolved_at else None,
        "handled_by_id": complaint.handled_by_id,
    }


@app.get("/health/live")
def health_live():
    return {"status": "ok", "service": "optigo-backend"}


@app.get("/health/ready")
def health_ready(db: Session = Depends(get_db)):
    try:
        db.execute(text("select 1"))
        return {"status": "ready", "database": "seneca_phase3"}
    except Exception as exc:
        raise HTTPException(503, f"Database is not ready: {exc}")


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
    request.session["user_id"] = user.user_id
    return {"account": account_view(db, user)}


@app.post("/api/auth/login")
def login(payload: AuthIn, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.email == str(payload.email).lower().strip()))
    if not user or not user.active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Invalid email or password")
    request.session.clear()
    request.session["user_id"] = user.user_id
    return {"account": account_view(db, user)}


@app.post("/api/auth/logout")
def logout(request: Request):
    request.session.clear()
    return {"logged_out": True}


@app.get("/api/notifications")
def notifications(request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    staff = staff_for(db, user)
    stmt = select(Notification).order_by(Notification.created_at.desc()).limit(100)
    if customer and not staff:
        stmt = stmt.where(Notification.customer_id == customer.customer_id)
    elif not staff:
        raise HTTPException(403, "A customer or staff profile is required")
    rows = db.scalars(stmt).all()
    return {"notifications": [notification_view(row) for row in rows], "unread_count": sum(row.read_at is None for row in rows)}


@app.post("/api/notifications/{notification_id}/read")
def mark_notification_read(notification_id: str, request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    notification = db.get(Notification, notification_id)
    if not notification:
        raise HTTPException(404, "Notification not found")
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    if not staff_for(db, user) and (not customer or notification.customer_id != customer.customer_id):
        raise HTTPException(404, "Notification not found")
    notification.read_at = notification.read_at or datetime.now(timezone.utc)
    db.commit()
    return notification_view(notification)


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
    elif staff.role_code not in {"ADMINISTRATOR", "OPERATIONS_MANAGER", "SUPPORT_OFFICER"}:
        raise HTTPException(403, "Your role is not authorized to view complaints")
    return {"complaints": [complaint_view(row) for row in db.scalars(stmt).all()]}


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
    return complaint_view(complaint)


@app.patch("/api/complaints/{complaint_id}")
def update_complaint(complaint_id: str, payload: ComplaintUpdateIn, request: Request, db: Session = Depends(get_db)):
    user, staff = required_staff(request, db, {"ADMINISTRATOR", "OPERATIONS_MANAGER", "SUPPORT_OFFICER"})
    complaint = db.get(Complaint, complaint_id)
    if not complaint:
        raise HTTPException(404, "Complaint not found")
    complaint.status_code = payload.status_code
    complaint.handled_by_id = staff.staff_id
    complaint.resolved_at = datetime.now(timezone.utc) if payload.status_code in {"RESOLVED", "CLOSED"} else None
    db.commit()
    return complaint_view(complaint)


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
    if search:
        stmt = stmt.where(Shipment.tracking_id.ilike(f"%{search.strip()}%"))
    return [shipment_view(db, s, include_private=bool(staff)) for s in db.scalars(stmt).all()]


@app.post("/api/shipments", status_code=201)
def book_shipment(payload: BookingIn, request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    if not customer:
        raise HTTPException(403, "Customer profile required")
    try:
        shipment = create_booking(db, customer, user, payload.sender.model_dump(), payload.receiver.model_dump(), payload.model_dump())
        return shipment_view(db, shipment)
    except (ValueError, IntegrityError) as exc:
        db.rollback()
        raise HTTPException(409, str(exc))


@app.get("/api/shipments/{shipment_id}")
def get_shipment(shipment_id: str, request: Request, db: Session = Depends(get_db)):
    user = required_user(request, db)
    shipment = db.get(Shipment, shipment_id)
    staff = staff_for(db, user)
    customer = db.scalar(select(Customer).where(Customer.user_id == user.user_id))
    if not shipment or (not staff and (not customer or shipment.customer_id != customer.customer_id)):
        raise HTTPException(404, "Shipment not found")
    return shipment_view(db, shipment, include_private=True)


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
    amount_paise = int(Decimal(str(invoice.total)) * 100)
    key_id, key_secret = os.getenv("RAZORPAY_KEY_ID", "").strip(), os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if not key_id or not key_secret:
        return {"provider": "local-test-fallback", "mode": "test", "order_id": f"local_order_{invoice.invoice_no}", "amount": amount_paise, "currency": invoice.currency.strip(), "shipment_id": shipment.shipment_id, "message": "Razorpay test keys are not configured; this no-cost local simulation is available."}
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
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "").strip()
    if payload.order_id.startswith("local_order_") and not key_secret:
        verified = True
    else:
        if not key_secret:
            raise HTTPException(503, "Razorpay test secret is not configured")
        expected = hmac.new(key_secret.encode(), f"{payload.order_id}|{payload.payment_id}".encode(), hashlib.sha256).hexdigest()
        verified = hmac.compare_digest(expected, payload.signature)
    if not verified:
        raise HTTPException(400, "Razorpay payment signature is invalid")
    invoice.payment_status_code = "PAID"
    db.commit()
    return {"verified": True, "provider": "razorpay" if key_secret else "local-test-fallback", "invoice_no": invoice.invoice_no, "payment_status": invoice.payment_status_code}


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
        result.append({"assignment_id": a.assignment_id, "shipment_id": a.shipment_id, "tracking_id": s.tracking_id if s else None, "task_type_code": a.task_type_code, "status_code": a.status_code, "shipment_status": s.current_status if s else None, "staff_id": a.staff_id, "assigned_at": a.assigned_at.isoformat(), "scheduled_reference_at": a.completed_at.isoformat(), "failure_reason": a.failure_reason})
    return {"account": account_view(db, user), "tasks": result}


@app.post("/api/assignments", status_code=201)
def create_assignment(payload: AssignmentIn, request: Request, db: Session = Depends(get_db)):
    user, manager = required_staff(request, db, {"ADMINISTRATOR", "OPERATIONS_MANAGER", "BOOKING_OFFICER", "WAREHOUSE_OFFICER"})
    shipment, assignee = db.get(Shipment, payload.shipment_id), db.get(Staff, payload.staff_id)
    if not shipment or not assignee or not assignee.active:
        raise HTTPException(404, "Shipment or active staff member not found")
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
        transition_assignment(db, assignment, actor, True)
        return {"assignment_id": assignment_id, "status_code": "COMPLETED"}
    except (ValueError, PermissionError) as exc:
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
    try:
        code = request_delivery_otp(db, assignment_for(db, assignment_id), actor)
        response = {"assignment_id": assignment_id, "expires_in_seconds": 600, "delivery_otp_requested": True}
        if os.getenv("SHOW_OTP_IN_RESPONSE", "false").lower() == "true":
            response["development_only_code"] = code
        return response
    except (ValueError, PermissionError) as exc:
        raise HTTPException(403 if isinstance(exc, PermissionError) else 409, str(exc))


@app.post("/api/assignments/{assignment_id}/deliver")
def deliver(assignment_id: str, payload: DeliveryIn, request: Request, db: Session = Depends(get_db)):
    actor = required_user(request, db)
    try:
        proof = verify_delivery(db, assignment_for(db, assignment_id), actor, payload.code, payload.remarks)
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
    now = datetime.now(timezone.utc)
    from .services import new_id
    location_text = payload.location_text.strip()
    scan_type = payload.scan_type.upper()
    if payload.latitude is not None and payload.longitude is not None:
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
    rows = db.scalars(select(WarehouseScan).order_by(WarehouseScan.scanned_at.desc()).limit(100)).all()
    return [{"scan_id": r.scan_id, "shipment_id": r.shipment_id, "hub_id": r.hub_id, "scan_type": r.scan_type, "scanned_at": r.scanned_at.isoformat()} for r in rows]


@app.post("/api/warehouse/scans")
def create_warehouse_scan(payload: WarehouseScanIn, request: Request, db: Session = Depends(get_db)):
    user, staff = required_staff(request, db, {"ADMINISTRATOR", "OPERATIONS_MANAGER", "WAREHOUSE_OFFICER"})
    shipment = db.get(Shipment, payload.shipment_id)
    if shipment is None:
        raise HTTPException(status_code=404, detail="Shipment not found")
    hub = db.get(Hub, payload.hub_id)
    if hub is None or not hub.active:
        raise HTTPException(status_code=404, detail="Active hub not found")
    from .services import new_id
    row = WarehouseScan(scan_id=new_id(db, WarehouseScan, "scan_id", "OBUSCN", width=6), shipment_id=shipment.shipment_id, scan_type=payload.scan_type.strip().upper(), scanned_at=datetime.now(timezone.utc), hub_id=hub.hub_id, scanned_by=staff.staff_id)
    db.add(row)
    db.commit()
    return {"scan_id": row.scan_id, "shipment_id": row.shipment_id, "hub_id": row.hub_id, "scan_type": row.scan_type, "scanned_at": row.scanned_at.isoformat()}


@app.get("/api/finance/summary")
def finance_summary(request: Request, db: Session = Depends(get_db)):
    required_staff(request, db, {"ADMINISTRATOR", "OPERATIONS_MANAGER", "ACCOUNTS_OFFICER"})
    return {"invoices": db.scalar(select(func.count(Invoice.invoice_no))) or 0, "invoice_total": str(db.scalar(select(func.coalesce(func.sum(Invoice.total), 0))) or 0), "payments": db.scalar(select(func.count(Payment.payment_id))) or 0, "payments_total": str(db.scalar(select(func.coalesce(func.sum(Payment.amount), 0))) or 0), "refunds": db.scalar(select(func.count(Refund.refund_id))) or 0}


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    return __import__("fastapi.responses", fromlist=["JSONResponse"]).JSONResponse(status_code=409, content={"detail": "The request violates a database data-integrity rule"})
