from datetime import datetime, timezone

from app.security import hash_otp, hash_password, verify_otp, verify_password
from app.services import STATUS_TRANSITIONS


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

