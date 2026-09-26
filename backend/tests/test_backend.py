from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import Mock

from app.security import hash_otp, hash_password, verify_otp, verify_password
from app.services import STATUS_TRANSITIONS, price_for_weight
from app.main import razorpay_test_keys_ready


def test_password_is_one_way_and_verifies():
    stored = hash_password("CorrectHorseBatteryStaple!")
    assert stored != "CorrectHorseBatteryStaple!"
    assert verify_password("CorrectHorseBatteryStaple!", stored)
    assert not verify_password("wrong-password", stored)


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


def test_razorpay_checkout_requires_test_keys(monkeypatch):
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_live_example")
    monkeypatch.setenv("RAZORPAY_KEY_SECRET", "example-secret")
    assert not razorpay_test_keys_ready()
    monkeypatch.setenv("RAZORPAY_KEY_ID", "rzp_test_example")
    assert razorpay_test_keys_ready()
