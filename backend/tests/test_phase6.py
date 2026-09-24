from datetime import date
from types import SimpleNamespace

from app.services import delivery_assessment


def shipment(status: str, expected: date):
    return SimpleNamespace(current_status=status, expected_delivery=expected)


def test_delivery_assessment_marks_overdue_active_shipment_delayed():
    result = delivery_assessment(shipment("IN_TRANSIT", date(2026, 9, 20)), date(2026, 9, 24))
    assert result["state"] == "DELAYED"
    assert result["is_delayed"] is True
    assert result["days_overdue"] == 4


def test_delivery_assessment_does_not_mark_delivered_shipment_delayed():
    result = delivery_assessment(shipment("DELIVERED", date(2026, 9, 20)), date(2026, 9, 24))
    assert result["state"] == "DELIVERED"
    assert result["is_delayed"] is False
    assert result["days_overdue"] == 0


def test_delivery_assessment_identifies_due_today():
    result = delivery_assessment(shipment("OUT_FOR_DELIVERY", date(2026, 9, 24)), date(2026, 9, 24))
    assert result["state"] == "DUE_TODAY"
