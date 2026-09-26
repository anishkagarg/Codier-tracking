from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import math
import os
import secrets
import smtplib
from email.message import EmailMessage

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Address, Customer, DeliveryOTP, Hub, Invoice, LocationUpdate, Notification, Payment, PricingRule, ProofOfDelivery, Route, Shipment, ShipmentAssignment, ShipmentStatusHistory, Staff, User, Vehicle
from .security import hash_otp, verify_otp

STATUS_TRANSITIONS = {
    "INITIAL": {"BOOKED"},
    "BOOKED": {"PICKED_UP", "CANCELLED", "CONFIRMED"},
    "CONFIRMED": {"PICKED_UP", "CANCELLED"},
    "PICKED_UP": {"IN_TRANSIT"},
    "IN_TRANSIT": {"OUT_FOR_DELIVERY", "DELIVERED", "UNAVAILABLE"},
    "OUT_FOR_DELIVERY": {"DELIVERED", "DELIVERY_FAILED", "UNAVAILABLE"},
    "UNAVAILABLE": {"OUT_FOR_DELIVERY", "IN_TRANSIT", "DELIVERY_FAILED"},
    "DELIVERY_FAILED": {"OUT_FOR_DELIVERY", "IN_TRANSIT", "CANCELLED"},
}

NOTIFICATION_TYPES = {status: "STATUS_UPDATE" for status in (
    "BOOKED", "PICKED_UP", "IN_TRANSIT", "OUT_FOR_DELIVERY",
    "DELIVERED", "DELIVERY_FAILED", "UNAVAILABLE",
)}


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def new_id(db: Session, model, field: str, prefix: str, width: int = 6) -> str:
    column = getattr(model, field)
    for _ in range(40):
        candidate = f"{prefix}{secrets.randbelow(10 ** width):0{width}d}"
        if db.scalar(select(model).where(column == candidate)) is None:
            return candidate
    raise RuntimeError(f"Could not create a unique {prefix} identifier")


def price_for_weight(db: Session, delivery_type: str, zone: str, weight: Decimal) -> tuple[Decimal, PricingRule]:
    rule = db.scalar(select(PricingRule).where(PricingRule.delivery_type_code == delivery_type, PricingRule.destination_zone == zone))
    if not rule:
        rule = db.scalar(select(PricingRule).where(PricingRule.delivery_type_code == delivery_type).order_by(PricingRule.effective_from.desc()))
    if not rule:
        raise ValueError(f"No pricing rule is configured for {delivery_type}")
    params = rule.rate_parameters or {}
    base = Decimal(str(params.get("base_charge", params.get("base", 0))))
    per_kg = Decimal(str(params.get("per_kg", params.get("per_kg_rate", 0))))
    if base == 0 and per_kg == 0:
        # The database is authoritative; this branch is only defensive for an empty rate JSON object.
        raise ValueError("The selected pricing rule has no usable rate parameters")
    return money(base + per_kg * weight), rule


def create_notification(db: Session, shipment: Shipment, type_code: str, message: str) -> Notification | None:
    """Record an in-app notification without making shipment writes depend on it.

    The supplied live database is authoritative and has been used with more than
    one notification-table revision. A savepoint keeps a legacy mismatch from
    rolling back a valid booking or status transition; successful installations
    still receive a durable SENT notification.
    """
    now = datetime.now(timezone.utc)
    try:
        with db.begin_nested():
            notification = Notification(
                notification_id=new_id(db, Notification, "notification_id", "OBUNOT"),
                shipment_id=shipment.shipment_id,
                customer_id=shipment.customer_id,
                type_code=type_code,
                channel_code="IN_APP",
                message=message.strip(),
                status_code="SENT",
                created_at=now,
                sent_at=now,
                read_at=None,
            )
            db.add(notification)
            db.flush()
        return notification
    except Exception as exc:
        if type_code == "OTP":
            raise ValueError("The verification code could not be delivered to the customer's notifications") from exc
        return None


def send_email_if_configured(db: Session, shipment: Shipment, message: str) -> bool:
    """Send email only when SMTP is explicitly configured; otherwise remain in-app."""
    if os.getenv("EMAIL_TRANSPORT", "in_app").lower() != "smtp" or not os.getenv("SMTP_HOST"):
        return False
    user = db.scalar(select(User).join(Customer, Customer.user_id == User.user_id).where(Customer.customer_id == shipment.customer_id))
    if not user or not user.email:
        return False
    email = EmailMessage()
    email["Subject"] = f"OptiGo shipment update: {shipment.tracking_id}"
    email["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USERNAME")
    email["To"] = user.email
    email.set_content(message)
    try:
        with smtplib.SMTP(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT", "587")), timeout=10) as client:
            client.starttls()
            if os.getenv("SMTP_USERNAME"):
                client.login(os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD", ""))
            client.send_message(email)
        return True
    except Exception:
        return False


def notify_status_change(db: Session, shipment: Shipment, status_code: str, remarks: str) -> None:
    type_code = NOTIFICATION_TYPES.get(status_code)
    if not type_code:
        return
    message = f"Shipment {shipment.tracking_id} is now {status_code.replace('_', ' ').title()}."
    if remarks.strip():
        message += f" {remarks.strip()}"
    create_notification(db, shipment, type_code, message)
    send_email_if_configured(db, shipment, message)


def delivery_assessment(shipment: Shipment, today: date | None = None) -> dict:
    """Return a transparent rule-based ETA and delay assessment.

    This deliberately reports the stored schedule and its variance; it does not
    pretend to be an ML prediction or live GPS signal.
    """
    today = today or datetime.now(timezone.utc).date()
    expected = shipment.expected_delivery
    terminal = shipment.current_status in {"DELIVERED", "CANCELLED", "RETURNED"}
    overdue_days = max((today - expected).days, 0) if not terminal else 0
    if shipment.current_status == "DELIVERED":
        state = "DELIVERED"
    elif expected < today:
        state = "DELAYED"
    elif expected == today:
        state = "DUE_TODAY"
    else:
        state = "ON_SCHEDULE"
    return {
        "state": state,
        "is_delayed": state == "DELAYED",
        "days_overdue": overdue_days,
        "expected_delivery": expected.isoformat(),
        "status": shipment.current_status,
        "basis": "Stored expected-delivery date and current shipment status",
        "prediction_method": "transparent rule-based ETA; no paid ML or mapping API",
    }


def parse_gps_location(location_text: str) -> tuple[float, float] | None:
    """Read the compact GPS representation stored in location_text."""
    if not location_text.startswith("GPS:"):
        return None
    try:
        latitude, longitude = [float(value.strip()) for value in location_text[4:].split(",", 1)]
        if -90 <= latitude <= 90 and -180 <= longitude <= 180:
            return latitude, longitude
    except (TypeError, ValueError):
        return None
    return None


def latest_gps_location(db: Session, shipment_id: str) -> dict | None:
    row = db.scalar(select(LocationUpdate).where(LocationUpdate.shipment_id == shipment_id, LocationUpdate.scan_type == "GPS").order_by(LocationUpdate.recorded_at.desc()))
    if not row:
        return None
    coords = parse_gps_location(row.location_text)
    if not coords:
        return None
    return {"latitude": coords[0], "longitude": coords[1], "recorded_at": row.recorded_at.isoformat(), "location_id": row.location_id}


def haversine_km(start_latitude: float, start_longitude: float, end_latitude: float, end_longitude: float) -> float:
    radius_km = 6371.0088
    phi1, phi2 = math.radians(start_latitude), math.radians(end_latitude)
    d_phi = math.radians(end_latitude - start_latitude)
    d_lambda = math.radians(end_longitude - start_longitude)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def optimize_route(start: dict, stops: list[dict]) -> dict:
    """No-cost nearest-neighbour route ordering using supplied coordinates."""
    remaining = [dict(stop) for stop in stops]
    current = {"latitude": float(start["latitude"]), "longitude": float(start["longitude"])}
    ordered = []
    total = 0.0
    while remaining:
        next_stop = min(remaining, key=lambda stop: haversine_km(current["latitude"], current["longitude"], float(stop["latitude"]), float(stop["longitude"])))
        distance = haversine_km(current["latitude"], current["longitude"], float(next_stop["latitude"]), float(next_stop["longitude"]))
        next_stop["distance_from_previous_km"] = round(distance, 2)
        total += distance
        ordered.append(next_stop)
        current = {"latitude": float(next_stop["latitude"]), "longitude": float(next_stop["longitude"])}
        remaining.remove(next_stop)
    return {"algorithm": "nearest-neighbour / Haversine; no external map API", "total_distance_km": round(total, 2), "stops": ordered}


def add_location_and_history(db: Session, shipment: Shipment, actor: UserLike, new_status: str, location_text: str, remarks: str) -> ShipmentStatusHistory:
    latest = db.scalar(select(ShipmentStatusHistory).where(ShipmentStatusHistory.shipment_id == shipment.shipment_id).order_by(ShipmentStatusHistory.sequence_no.desc()))
    prior = latest.new_status if latest else "INITIAL"
    if new_status not in STATUS_TRANSITIONS.get(prior, set()):
        raise ValueError(f"Invalid status transition {prior} -> {new_status}")
    now = datetime.now(timezone.utc)
    location = LocationUpdate(location_id=new_id(db, LocationUpdate, "location_id", "OBULOC"), shipment_id=shipment.shipment_id, recorded_at=now, location_text=location_text.strip(), scan_type="APPLICATION", recorded_by=actor.user_id)
    db.add(location)
    db.flush()
    event = ShipmentStatusHistory(event_id=new_id(db, ShipmentStatusHistory, "event_id", "OBUEVT"), shipment_id=shipment.shipment_id, sequence_no=(latest.sequence_no + 1 if latest else 1), previous_status=prior, new_status=new_status, event_at=now, event_provenance="APPLICATION_RECORDED", location_id=location.location_id, remarks=remarks.strip(), updated_by=actor.user_id)
    db.add(event)
    shipment.current_status = new_status
    db.flush()
    notify_status_change(db, shipment, new_status, remarks)
    return event


class UserLike:
    user_id: str


def create_booking(db: Session, customer: Customer, actor: UserLike, sender: dict, receiver: dict, parcel: dict) -> Shipment:
    for key in ("weight_kg", "length_cm", "width_cm", "height_cm"):
        if Decimal(str(parcel[key])) <= 0:
            raise ValueError("Weight and all parcel dimensions must be positive")
    delivery_type = parcel["delivery_type_code"]
    zone = parcel.get("destination_zone", "LOCAL")
    weight = Decimal(str(parcel["weight_kg"]))
    charge, rule = price_for_weight(db, delivery_type, zone, weight)
    now = datetime.now(timezone.utc)
    eta_days = 1 if delivery_type == "SAME_DAY" else (2 if delivery_type == "EXPRESS" else 5)
    eta = now + timedelta(days=eta_days)
    def address(data, role):
        obj = Address(address_id=new_id(db, Address, "address_id", "OBUADR"), customer_id=customer.customer_id, address_role=role, line1=data["line1"].strip(), city=data["city"].strip(), state=data["state"].strip(), postal_code=data["postal_code"].strip(), country=data.get("country", "IN")[:2].upper(), contact_name=data["contact_name"].strip(), contact_phone=data["contact_phone"].strip())
        db.add(obj)
        db.flush()
        return obj
    sender_address = address(sender, "ORIGIN")
    receiver_address = address(receiver, "DESTINATION")
    cash_due = charge if parcel.get("payment_mode", "RAZORPAY") == "CASH" else Decimal("0.00")
    shipment = Shipment(shipment_id=new_id(db, Shipment, "shipment_id", "OBUSHP"), tracking_id=new_id(db, Shipment, "tracking_id", "OBUTRK"), customer_id=customer.customer_id, sender_address_id=sender_address.address_id, receiver_address_id=receiver_address.address_id, booking_date=now, expected_delivery_at=eta, delivery_reference_at=eta, current_status="BOOKED", weight_kg=weight, length_cm=parcel["length_cm"], width_cm=parcel["width_cm"], height_cm=parcel["height_cm"], parcel_type=parcel.get("parcel_type", "Parcel"), delivery_mode=delivery_type, charge=charge, currency=rule.currency, payment_amount=Decimal("0.00"), pricing_rule_id=rule.pricing_rule_id, fragile=bool(parcel.get("fragile")), priority=bool(parcel.get("priority")), delivery_type_code=delivery_type, expected_delivery=eta.date(), delivery_reference_type="SCHEDULED_REFERENCE", cod_amount_due=money(cash_due), created_by=actor.user_id)
    db.add(shipment)
    db.flush()
    add_location_and_history(db, shipment, actor, "BOOKED", sender_address.city, "Customer booking created")
    invoice = Invoice(invoice_no=new_id(db, Invoice, "invoice_no", "OBUINV"), shipment_id=shipment.shipment_id, issued_at=now, subtotal=charge, tax=Decimal("0.00"), total=charge, currency=rule.currency, payment_status_code="PENDING", preferred_payment_mode=parcel.get("payment_mode", "RAZORPAY"))
    db.add(invoice)
    return shipment


def public_tracking(db: Session, tracking_id: str) -> dict | None:
    shipment = db.scalar(select(Shipment).where(Shipment.tracking_id == tracking_id.strip()))
    if not shipment:
        return None
    events = db.scalars(select(ShipmentStatusHistory).where(ShipmentStatusHistory.shipment_id == shipment.shipment_id).order_by(ShipmentStatusHistory.sequence_no)).all()
    return {"shipment_id": shipment.shipment_id, "tracking_id": shipment.tracking_id, "status": shipment.current_status, "delivery_type": shipment.delivery_type_code, "expected_delivery": shipment.expected_delivery.isoformat(), "delivery_assessment": delivery_assessment(shipment), "latest_location": latest_gps_location(db, shipment.shipment_id), "history": [{"sequence_no": e.sequence_no, "status": e.new_status, "previous_status": e.previous_status, "event_at": e.event_at.isoformat(), "location_id": e.location_id, "remarks": e.remarks} for e in events]}


TASK_ROLES = {"PICKUP": "PICKUP_AGENT", "WAREHOUSE": "WAREHOUSE_OFFICER", "DELIVERY": "DELIVERY_AGENT"}


def assign_task(db: Session, shipment: Shipment, assignee: Staff, assigned_by: Staff, task_type: str, *, commit: bool = True) -> ShipmentAssignment:
    if task_type not in TASK_ROLES:
        raise ValueError("Unknown shipment task type")
    if assignee.role_code != TASK_ROLES[task_type]:
        raise ValueError(f"{task_type.title()} tasks must be assigned to a {TASK_ROLES[task_type].replace('_', ' ').lower()}")
    if db.scalar(select(ShipmentAssignment).where(ShipmentAssignment.shipment_id == shipment.shipment_id, ShipmentAssignment.task_type_code == task_type)):
        raise ValueError("This shipment already has an assignment for that task type")
    route = db.scalar(select(Route).where(Route.active.is_(True)).order_by(Route.route_code))
    vehicle = db.scalar(select(Vehicle).where(Vehicle.active.is_(True)).order_by(Vehicle.vehicle_id))
    if not route or not vehicle:
        raise ValueError("An active route and vehicle are required by the database schema")
    now = datetime.now(timezone.utc)
    assignment = ShipmentAssignment(assignment_id=new_id(db, ShipmentAssignment, "assignment_id", "OBUASN"), shipment_id=shipment.shipment_id, task_type_code=task_type, route_id=route.route_id, assigned_at=now, completed_at=shipment.expected_delivery_at, status_code="ASSIGNED", failure_reason="No failure recorded", completion_reference_type="SCHEDULED_REFERENCE", vehicle_id=vehicle.vehicle_id, staff_id=assignee.staff_id, assigned_by_id=assigned_by.staff_id)
    db.add(assignment)
    if commit:
        db.commit()
        db.refresh(assignment)
    else:
        db.flush()
    return assignment


def auto_assign_task(db: Session, shipment: Shipment, task_type: str) -> ShipmentAssignment:
    """Dispatch each lifecycle step to its own department in the current transaction."""
    if task_type not in TASK_ROLES:
        raise ValueError("Unknown shipment task type")
    existing = db.scalar(select(ShipmentAssignment).where(ShipmentAssignment.shipment_id == shipment.shipment_id, ShipmentAssignment.task_type_code == task_type))
    if existing:
        return existing
    assignee = db.scalar(select(Staff).where(Staff.active.is_(True), Staff.role_code == TASK_ROLES[task_type]).order_by(Staff.staff_id))
    dispatcher = db.scalar(select(Staff).where(Staff.active.is_(True), Staff.role_code.in_(["ADMINISTRATOR", "OPERATIONS_MANAGER"])).order_by(Staff.staff_id))
    if not assignee or not dispatcher:
        raise ValueError(f"No active {TASK_ROLES[task_type].replace('_', ' ').lower()} or dispatcher is available")
    return assign_task(db, shipment, assignee, dispatcher, task_type, commit=False)


def transition_assignment(db: Session, assignment: ShipmentAssignment, actor: UserLike, success: bool, reason: str | None = None, *, commit: bool = True) -> ShipmentAssignment:
    shipment = db.get(Shipment, assignment.shipment_id)
    if not shipment:
        raise ValueError("Shipment not found")
    staff = db.scalar(select(Staff).where(Staff.user_id == actor.user_id))
    if not staff or (staff.staff_id != assignment.staff_id and staff.role_code not in {"ADMINISTRATOR", "OPERATIONS_MANAGER"}):
        raise PermissionError("You are not authorized for this assignment")
    if assignment.status_code == "COMPLETED":
        raise ValueError("This task has already been completed")
    now = datetime.now(timezone.utc)
    assignment.completed_at = now
    if not success:
        assignment.status_code = "FAILED"
        assignment.failure_reason = (reason or "The operation could not be completed").strip()
        if commit:
            db.commit()
        return assignment
    assignment.status_code = "COMPLETED"
    assignment.failure_reason = "Completed successfully"
    if assignment.task_type_code == "PICKUP":
        add_location_and_history(db, shipment, actor, "PICKED_UP", "Pickup confirmed", "Pickup completed")
    elif assignment.task_type_code == "DELIVERY":
        add_location_and_history(db, shipment, actor, "DELIVERED", "Delivery address", "Delivery completed")
    if commit:
        db.commit()
    return assignment


def request_delivery_otp(db: Session, assignment: ShipmentAssignment, actor: UserLike) -> str:
    shipment = db.get(Shipment, assignment.shipment_id)
    staff = db.scalar(select(Staff).where(Staff.user_id == actor.user_id))
    if not shipment or not staff or staff.staff_id != assignment.staff_id:
        raise PermissionError("Only the assigned delivery agent can request an OTP")
    if shipment.current_status != "OUT_FOR_DELIVERY" or assignment.status_code != "IN_PROGRESS":
        raise ValueError("A delivery OTP can only be requested for an active delivery")
    code = f"{secrets.randbelow(1_000_000):06d}"
    now = datetime.now(timezone.utc)
    otp = db.scalar(select(DeliveryOTP).where(DeliveryOTP.assignment_id == assignment.assignment_id))
    if not otp:
        otp = DeliveryOTP(otp_id=new_id(db, DeliveryOTP, "otp_id", "OBUOTP"), assignment_id=assignment.assignment_id, code_hash=hash_otp(code), expires_at=now + timedelta(minutes=10), attempt_count=0, verified_at=None, consumed_at=None, created_at=now)
        db.add(otp)
    else:
        otp.code_hash = hash_otp(code)
        otp.expires_at = now + timedelta(minutes=10)
        otp.attempt_count = 0
        otp.verified_at = None
        otp.consumed_at = None
        otp.created_at = now
    message = f"Delivery code for shipment {shipment.tracking_id}: {code}. Share it with the recipient only when the parcel arrives. This code expires in 10 minutes."
    if create_notification(db, shipment, "OTP", message) is None:
        db.rollback()
        raise ValueError("The verification code could not be delivered to the customer's notifications")
    db.commit()
    send_email_if_configured(db, shipment, message)
    return code


def verify_delivery(db: Session, assignment: ShipmentAssignment, actor: UserLike, code: str, remarks: str, cash_collected: bool = False) -> ProofOfDelivery:
    shipment = db.get(Shipment, assignment.shipment_id)
    staff = db.scalar(select(Staff).where(Staff.user_id == actor.user_id))
    if not shipment or not staff or staff.staff_id != assignment.staff_id:
        raise PermissionError("Only the assigned delivery agent can verify the OTP")
    if shipment.current_status != "OUT_FOR_DELIVERY" or assignment.status_code != "IN_PROGRESS":
        raise ValueError("Delivery has not been started or is already complete")
    cash_due = money(shipment.cod_amount_due)
    if cash_due > 0 and not cash_collected:
        raise ValueError("Confirm that the cash delivery charge was collected before completing delivery")
    otp = db.scalar(select(DeliveryOTP).where(DeliveryOTP.assignment_id == assignment.assignment_id))
    now = datetime.now(timezone.utc)
    if not otp or otp.consumed_at or otp.expires_at < now or otp.attempt_count >= 5:
        raise ValueError("OTP is invalid, expired, or not requested")
    if not verify_otp(code.strip(), otp.code_hash):
        otp.attempt_count += 1
        db.commit()
        raise ValueError("OTP is invalid, expired, or not requested")
    otp.verified_at = now
    otp.consumed_at = now
    db.flush()
    proof = ProofOfDelivery(proof_id=new_id(db, ProofOfDelivery, "proof_id", "OBUPOD"), shipment_id=shipment.shipment_id, assignment_id=assignment.assignment_id, otp_id=otp.otp_id, proof_reference=f"{shipment.tracking_id}-POD", otp_verified=True, captured_at=now, remarks=remarks.strip() or "OTP verified", captured_by_id=staff.staff_id)
    db.add(proof)
    if cash_due > 0:
        invoice = db.scalar(select(Invoice).where(Invoice.shipment_id == shipment.shipment_id))
        if not invoice:
            raise ValueError("Invoice missing for cash collection")
        db.add(Payment(payment_id=new_id(db, Payment, "payment_id", "OBUPAY"), invoice_no=invoice.invoice_no, amount=cash_due, method_code="CASH", paid_at=now, reference_no=f"{shipment.tracking_id}-CASH", recorded_by_id=staff.staff_id))
        invoice.payment_status_code = "PAID"
        shipment.payment_amount = cash_due
        shipment.cod_amount_due = Decimal("0.00")
    assignment.status_code = "COMPLETED"
    assignment.completed_at = now
    assignment.failure_reason = "Completed successfully"
    add_location_and_history(db, shipment, actor, "DELIVERED", "Delivery address", "Delivered with OTP proof")
    db.commit()
    return proof
