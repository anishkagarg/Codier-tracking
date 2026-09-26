from sqlalchemy import Boolean, CHAR, Column, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB

from .db import Base


class Department(Base):
    __tablename__ = "departments"
    department_code = Column(String(30), primary_key=True, nullable=False)
    display_name = Column(String(80), nullable=False, unique=True)


class StaffRole(Base):
    __tablename__ = "staff_roles"
    role_code = Column(String(30), primary_key=True, nullable=False)
    display_name = Column(String(80), nullable=False, unique=True)


class DeliveryType(Base):
    __tablename__ = "delivery_types"
    delivery_type_code = Column(String(20), primary_key=True, nullable=False)
    display_name = Column(String(80), nullable=False, unique=True)


class ShipmentStatus(Base):
    __tablename__ = "shipment_statuses"
    status_code = Column(String(30), primary_key=True, nullable=False)
    display_name = Column(String(80), nullable=False, unique=True)
    is_terminal = Column(Boolean, nullable=False)


class AssignmentStatus(Base):
    __tablename__ = "assignment_statuses"
    status_code = Column(String(20), primary_key=True, nullable=False)
    display_name = Column(String(80), nullable=False, unique=True)


class TaskType(Base):
    __tablename__ = "task_types"
    task_type_code = Column(String(20), primary_key=True, nullable=False)
    display_name = Column(String(80), nullable=False, unique=True)
    task_type_id = Column(String(10), nullable=False, unique=True)


class PaymentMethod(Base):
    __tablename__ = "payment_methods"
    method_code = Column(String(30), primary_key=True, nullable=False)
    display_name = Column(String(80), nullable=False, unique=True)


class PaymentStatus(Base):
    __tablename__ = "payment_statuses"
    status_code = Column(String(30), primary_key=True, nullable=False)
    display_name = Column(String(80), nullable=False, unique=True)


class RefundStatus(Base):
    __tablename__ = "refund_statuses"
    status_code = Column(String(20), primary_key=True, nullable=False)
    display_name = Column(String(80), nullable=False, unique=True)


class SettlementStatus(Base):
    __tablename__ = "settlement_statuses"
    status_code = Column(String(20), primary_key=True, nullable=False)
    display_name = Column(String(80), nullable=False, unique=True)


class NotificationType(Base):
    __tablename__ = "notification_types"
    type_code = Column(String(30), primary_key=True, nullable=False)
    display_name = Column(String(80), nullable=False, unique=True)


class NotificationChannel(Base):
    __tablename__ = "notification_channels"
    channel_code = Column(String(20), primary_key=True, nullable=False)
    display_name = Column(String(80), nullable=False, unique=True)


class NotificationStatus(Base):
    __tablename__ = "notification_statuses"
    status_code = Column(String(20), primary_key=True, nullable=False)
    display_name = Column(String(80), nullable=False, unique=True)


class ComplaintStatus(Base):
    __tablename__ = "complaint_statuses"
    status_code = Column(String(20), primary_key=True, nullable=False)
    display_name = Column(String(80), nullable=False, unique=True)


class User(Base):
    __tablename__ = "users"
    user_id = Column(String(12), primary_key=True, nullable=False)
    name = Column(String(120), nullable=False)
    email = Column(String(254), nullable=False, unique=True, index=True)
    phone = Column(String(30), nullable=False)
    password_hash = Column(String(255), nullable=False)
    active = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False)


class Customer(Base):
    __tablename__ = "customers"
    customer_id = Column(String(40), primary_key=True, nullable=False)
    customer_type = Column(String(40), nullable=False)
    name = Column(String(120), nullable=False)
    customer_no = Column(String(30), nullable=False, unique=True)
    user_id = Column(String(12), ForeignKey("users.user_id"), nullable=False, unique=True)


class Staff(Base):
    __tablename__ = "staff"
    staff_id = Column(String(12), primary_key=True, nullable=False, unique=True)
    employee_id = Column(String(30), nullable=False, unique=True)
    department_code = Column(String(30), ForeignKey("departments.department_code"), nullable=False)
    role_code = Column(String(30), ForeignKey("staff_roles.role_code"), nullable=False)
    active = Column(Boolean, nullable=False)
    user_id = Column(String(12), ForeignKey("users.user_id"), nullable=False, unique=True)


class Address(Base):
    __tablename__ = "addresses"
    address_id = Column(String(40), primary_key=True, nullable=False)
    customer_id = Column(String(40), ForeignKey("customers.customer_id"), nullable=False)
    address_role = Column(String(20), nullable=False)
    line1 = Column(Text, nullable=False)
    city = Column(Text, nullable=False)
    state = Column(Text, nullable=False)
    postal_code = Column(Text, nullable=False)
    country = Column(CHAR(2), nullable=False)
    contact_name = Column(String(120), nullable=False)
    contact_phone = Column(String(30), nullable=False)


class Hub(Base):
    __tablename__ = "hubs"
    hub_id = Column(String(12), primary_key=True, nullable=False, unique=True)
    name = Column(String(120), nullable=False, unique=True)
    city = Column(String(80), nullable=False)
    state = Column(String(80), nullable=False)
    postal_code = Column(String(20), nullable=False)
    country = Column(CHAR(2), nullable=False)
    capacity = Column(Integer, nullable=False)
    active = Column(Boolean, nullable=False)


class Route(Base):
    __tablename__ = "routes"
    route_id = Column(String(40), primary_key=True, nullable=False)
    route_code = Column(String(30), nullable=False, unique=True)
    destination_zone = Column(String(100), nullable=False)
    active = Column(Boolean, nullable=False)
    origin_hub_id = Column(String(12), ForeignKey("hubs.hub_id"), nullable=False)
    destination_hub_id = Column(String(12), ForeignKey("hubs.hub_id"), nullable=False)


class Vehicle(Base):
    __tablename__ = "vehicles"
    vehicle_id = Column(String(12), primary_key=True, nullable=False)
    registration_no = Column(String(30), nullable=False, unique=True)
    capacity_kg = Column(Numeric(12, 2), nullable=False)
    active = Column(Boolean, nullable=False)
    vehicle_name = Column(String(120), nullable=False)
    vehicle_type = Column(String(30), nullable=False)
    home_hub_id = Column(String(12), ForeignKey("hubs.hub_id"), nullable=False)


class PricingRule(Base):
    __tablename__ = "pricing_rules"
    pricing_rule_id = Column(String(40), primary_key=True, nullable=False)
    version = Column(String(30), nullable=False, unique=True)
    destination_zone = Column(String(100), nullable=False)
    delivery_type_code = Column(String(20), ForeignKey("delivery_types.delivery_type_code"), nullable=False)
    rate_parameters = Column(JSONB, nullable=False)
    currency = Column(CHAR(3), nullable=False)
    effective_from = Column(Date, nullable=False)
    effective_to = Column(Date, nullable=False)


class Shipment(Base):
    __tablename__ = "shipments"
    shipment_id = Column(String(40), primary_key=True, nullable=False)
    tracking_id = Column(Text, nullable=False, unique=True)
    customer_id = Column(String(40), ForeignKey("customers.customer_id"), nullable=False)
    sender_address_id = Column(String(40), ForeignKey("addresses.address_id"), nullable=False)
    receiver_address_id = Column(String(40), ForeignKey("addresses.address_id"), nullable=False)
    booking_date = Column(DateTime(timezone=True), nullable=False)
    expected_delivery_at = Column(DateTime(timezone=True), nullable=False)
    delivery_reference_at = Column(DateTime(timezone=True), nullable=False)
    current_status = Column(String(30), nullable=False)
    weight_kg = Column(Numeric(12, 3), nullable=False)
    length_cm = Column(Numeric(12, 2), nullable=False)
    width_cm = Column(Numeric(12, 2), nullable=False)
    height_cm = Column(Numeric(12, 2), nullable=False)
    parcel_type = Column(String(80), nullable=False)
    delivery_mode = Column(String(40), nullable=False)
    charge = Column(Numeric(14, 2), nullable=False)
    currency = Column(CHAR(3), nullable=False)
    payment_amount = Column(Numeric(14, 2), nullable=False)
    pricing_rule_id = Column(String(40), ForeignKey("pricing_rules.pricing_rule_id"), nullable=False)
    fragile = Column(Boolean, nullable=False)
    priority = Column(Boolean, nullable=False)
    delivery_type_code = Column(String(20), ForeignKey("delivery_types.delivery_type_code"), nullable=False)
    expected_delivery = Column(Date, nullable=False)
    delivery_reference_type = Column(String(30), nullable=False)
    cod_amount_due = Column(Numeric(14, 2), nullable=False)
    created_by = Column(String(12), ForeignKey("users.user_id"), nullable=False)


class BookingIdempotency(Base):
    """Persist client booking keys so retries cannot create another shipment."""
    __tablename__ = "booking_idempotency"
    idempotency_key = Column(String(100), primary_key=True, nullable=False)
    user_id = Column(String(12), ForeignKey("users.user_id"), nullable=False)
    shipment_id = Column(String(40), ForeignKey("shipments.shipment_id"), nullable=False, unique=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class LocationUpdate(Base):
    __tablename__ = "location_updates"
    location_id = Column(String(40), primary_key=True, nullable=False)
    shipment_id = Column(String(40), ForeignKey("shipments.shipment_id"), nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False)
    location_text = Column(String(200), nullable=False)
    scan_type = Column(String(40), nullable=False)
    recorded_by = Column(String(12), ForeignKey("users.user_id"), nullable=False)


class ShipmentStatusHistory(Base):
    __tablename__ = "shipment_status_history"
    event_id = Column(String(40), primary_key=True, nullable=False)
    shipment_id = Column(String(40), ForeignKey("shipments.shipment_id", ondelete="CASCADE"), nullable=False)
    sequence_no = Column(Integer, nullable=False)
    previous_status = Column(String(30), ForeignKey("shipment_statuses.status_code"), nullable=False)
    new_status = Column(String(30), ForeignKey("shipment_statuses.status_code"), nullable=False)
    event_at = Column(DateTime(timezone=True), nullable=False)
    event_provenance = Column(String(30), nullable=False)
    location_id = Column(String(40), ForeignKey("location_updates.location_id"), nullable=False)
    remarks = Column(String(500), nullable=False)
    updated_by = Column(String(12), ForeignKey("users.user_id"), nullable=False)
    __table_args__ = (UniqueConstraint("shipment_id", "sequence_no"),)


class ShipmentAssignment(Base):
    __tablename__ = "shipment_assignments"
    assignment_id = Column(String(40), primary_key=True, nullable=False)
    shipment_id = Column(String(40), ForeignKey("shipments.shipment_id"), nullable=False)
    task_type_code = Column(String(20), ForeignKey("task_types.task_type_code"), nullable=False)
    route_id = Column(String(40), ForeignKey("routes.route_id"), nullable=False)
    assigned_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=False)
    status_code = Column(String(20), ForeignKey("assignment_statuses.status_code"), nullable=False)
    failure_reason = Column(String(500), nullable=False)
    completion_reference_type = Column(String(30), nullable=False)
    vehicle_id = Column(String(12), ForeignKey("vehicles.vehicle_id"), nullable=False)
    staff_id = Column(String(12), ForeignKey("staff.staff_id"), nullable=False)
    assigned_by_id = Column(String(12), ForeignKey("staff.staff_id"), nullable=False)
    __table_args__ = (UniqueConstraint("shipment_id", "task_type_code"),)


class DeliveryOTP(Base):
    __tablename__ = "delivery_otps"
    otp_id = Column(String(40), primary_key=True, nullable=False)
    assignment_id = Column(String(40), ForeignKey("shipment_assignments.assignment_id"), nullable=False, unique=True)
    code_hash = Column(String(255), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    attempt_count = Column(Integer, nullable=False)
    verified_at = Column(DateTime(timezone=True), nullable=False)
    consumed_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class ProofOfDelivery(Base):
    __tablename__ = "proof_of_delivery"
    proof_id = Column(String(40), primary_key=True, nullable=False)
    shipment_id = Column(String(40), ForeignKey("shipments.shipment_id"), nullable=False, unique=True)
    assignment_id = Column(String(40), ForeignKey("shipment_assignments.assignment_id"), nullable=False, unique=True)
    otp_id = Column(String(40), ForeignKey("delivery_otps.otp_id"), nullable=False, unique=True)
    proof_reference = Column(String(200), nullable=False)
    otp_verified = Column(Boolean, nullable=False)
    captured_at = Column(DateTime(timezone=True), nullable=False)
    remarks = Column(String(500), nullable=False)
    captured_by_id = Column(String(12), ForeignKey("staff.staff_id"), nullable=False)


class Invoice(Base):
    __tablename__ = "invoices"
    invoice_no = Column(String(40), primary_key=True, nullable=False)
    shipment_id = Column(String(40), ForeignKey("shipments.shipment_id"), nullable=False, unique=True)
    issued_at = Column(DateTime(timezone=True), nullable=False)
    subtotal = Column(Numeric(14, 2), nullable=False)
    tax = Column(Numeric(14, 2), nullable=False)
    total = Column(Numeric(14, 2), nullable=False)
    currency = Column(CHAR(3), nullable=False)
    payment_status_code = Column(String(30), ForeignKey("payment_statuses.status_code"), nullable=False)
    preferred_payment_mode = Column(String(20), nullable=True)


class Payment(Base):
    __tablename__ = "payments"
    payment_id = Column(String(40), primary_key=True, nullable=False)
    invoice_no = Column(String(40), ForeignKey("invoices.invoice_no"), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    method_code = Column(String(30), ForeignKey("payment_methods.method_code"), nullable=False)
    paid_at = Column(DateTime(timezone=True), nullable=False)
    reference_no = Column(String(100), nullable=False, unique=True)
    recorded_by_id = Column(String(12), ForeignKey("staff.staff_id"), nullable=False)


class Refund(Base):
    __tablename__ = "refunds"
    refund_id = Column(String(40), primary_key=True, nullable=False)
    payment_id = Column(String(40), ForeignKey("payments.payment_id"), nullable=False, unique=True)
    amount = Column(Numeric(14, 2), nullable=False)
    reason = Column(String(500), nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=False)
    reference_no = Column(String(100), nullable=False, unique=True)
    status_code = Column(String(20), ForeignKey("refund_statuses.status_code"), nullable=False)
    processed_by_id = Column(String(12), ForeignKey("staff.staff_id"), nullable=False)


class CodCollection(Base):
    __tablename__ = "cod_collections"
    collection_id = Column(String(40), primary_key=True, nullable=False)
    shipment_id = Column(String(40), ForeignKey("shipments.shipment_id"), nullable=False)
    amount = Column(Numeric(14, 2), nullable=False)
    collected_at = Column(DateTime(timezone=True), nullable=False)
    settlement_status_code = Column(String(20), ForeignKey("settlement_statuses.status_code"), nullable=False)
    settled_at = Column(DateTime(timezone=True), nullable=False)
    settlement_reference = Column(String(100), nullable=False, unique=True)
    collected_by_id = Column(String(12), ForeignKey("staff.staff_id"), nullable=False)
    settled_by_id = Column(String(12), ForeignKey("staff.staff_id"), nullable=False)


class WarehouseScan(Base):
    __tablename__ = "warehouse_scans"
    scan_id = Column(String(16), primary_key=True, nullable=False, unique=True)
    shipment_id = Column(String(40), ForeignKey("shipments.shipment_id"), nullable=False)
    scan_type = Column(String(40), nullable=False)
    scanned_at = Column(DateTime(timezone=True), nullable=False)
    hub_id = Column(String(12), ForeignKey("hubs.hub_id"), nullable=False)
    scanned_by = Column(String(12), ForeignKey("staff.staff_id"), nullable=False)


class ShipmentItem(Base):
    __tablename__ = "shipment_items"
    shipment_item_id = Column(String(40), primary_key=True, nullable=False)
    shipment_id = Column(String(40), ForeignKey("shipments.shipment_id", ondelete="CASCADE"), nullable=False)
    product_id = Column(String(40), ForeignKey("products.product_id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    unit_price = Column(Numeric(14, 2), nullable=False)
    freight_value = Column(Numeric(14, 2), nullable=False)
    currency = Column(CHAR(3), nullable=False)


class Product(Base):
    __tablename__ = "products"
    product_id = Column(String(40), primary_key=True, nullable=False)
    category = Column(String(80), nullable=False)
    weight_kg = Column(Numeric(12, 3), nullable=False)
    length_cm = Column(Numeric(12, 2), nullable=False)
    width_cm = Column(Numeric(12, 2), nullable=False)
    height_cm = Column(Numeric(12, 2), nullable=False)


class OperationalObservation(Base):
    __tablename__ = "operational_observations"
    observation_id = Column(String(40), primary_key=True, nullable=False)
    order_date = Column(DateTime(timezone=True), nullable=False)
    order_time = Column(Text, nullable=False)
    pickup_time = Column(Text, nullable=False)
    store_latitude = Column(Numeric(10, 6), nullable=False)
    store_longitude = Column(Numeric(10, 6), nullable=False)
    drop_latitude = Column(Numeric(10, 6), nullable=False)
    drop_longitude = Column(Numeric(10, 6), nullable=False)
    weather = Column(Text, nullable=False)
    traffic = Column(Text, nullable=False)
    vehicle = Column(Text, nullable=False)
    area = Column(Text, nullable=False)
    delivery_time_minutes = Column(Numeric(12, 2), nullable=False)
    category = Column(String(80), nullable=False)
    agent_age = Column(Numeric(5, 2), nullable=False)
    agent_rating = Column(Numeric(4, 2), nullable=False)


class NotificationPreference(Base):
    __tablename__ = "notification_preferences"
    preference_id = Column(String(40), primary_key=True, nullable=False)
    customer_id = Column(String(40), ForeignKey("customers.customer_id"), nullable=False, unique=True)
    channel_code = Column(String(20), ForeignKey("notification_channels.channel_code"), nullable=False)
    enabled = Column(Boolean, nullable=False)
    preference_source = Column(String(30), nullable=False)


class Notification(Base):
    __tablename__ = "notifications"
    notification_id = Column(String(40), primary_key=True, nullable=False)
    shipment_id = Column(String(40), ForeignKey("shipments.shipment_id"), nullable=False)
    customer_id = Column(String(40), ForeignKey("customers.customer_id"), nullable=False)
    type_code = Column(String(30), ForeignKey("notification_types.type_code"), nullable=False)
    channel_code = Column(String(20), ForeignKey("notification_channels.channel_code"), nullable=False)
    message = Column(Text, nullable=False)
    status_code = Column(String(20), ForeignKey("notification_statuses.status_code"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    sent_at = Column(DateTime(timezone=True), nullable=True)
    read_at = Column(DateTime(timezone=True), nullable=True)


class Complaint(Base):
    __tablename__ = "complaints"
    complaint_id = Column(String(40), primary_key=True, nullable=False)
    customer_id = Column(String(40), ForeignKey("customers.customer_id"), nullable=False)
    shipment_id = Column(String(40), ForeignKey("shipments.shipment_id"), nullable=True)
    subject = Column(String(150), nullable=False)
    description = Column(Text, nullable=False)
    status_code = Column(String(20), ForeignKey("complaint_statuses.status_code"), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    handled_by_id = Column(String(12), ForeignKey("staff.staff_id"), nullable=True)
