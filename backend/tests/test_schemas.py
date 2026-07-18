"""Unit tests for the Pydantic request/response schemas (task 3.1).

These verify the field constraints drawn from the requirements: full name
2-100 (trimmed), E.164 phone, six-digit OTP, bio <=500, interests <=20 items
each <=50, message content 1-2000, report reason 1-1000, and the admin
resolution decision enumeration.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.admin import ReportResolutionRequest
from app.schemas.auth import (
    LoginRequest,
    RegisterRequest,
    ResendOtpRequest,
    VerifyOtpRequest,
)
from app.schemas.common import (
    BIO_MAX,
    FULL_NAME_MAX,
    INTEREST_ITEM_MAX,
    INTERESTS_MAX_ITEMS,
    MESSAGE_CONTENT_MAX,
    REPORT_REASON_MAX,
)
from app.schemas.message import MessageSendRequest
from app.schemas.profile import BioUpdateRequest, InterestsUpdateRequest
from app.schemas.report import ReportRequest

VALID_PHONE = "+2348031234567"


# --- Registration / full name ------------------------------------------------


def test_register_accepts_valid_name_and_phone():
    req = RegisterRequest(full_name="Amara Okafor", phone=VALID_PHONE)
    assert req.full_name == "Amara Okafor"
    assert req.phone == VALID_PHONE


def test_register_trims_full_name():
    req = RegisterRequest(full_name="  Thandiwe Nkosi  ", phone="+27821234567")
    assert req.full_name == "Thandiwe Nkosi"


@pytest.mark.parametrize("name", ["", " ", "  ", "A", " x "])
def test_register_rejects_short_or_blank_name(name):
    with pytest.raises(ValidationError) as exc:
        RegisterRequest(full_name=name, phone=VALID_PHONE)
    assert any(e["loc"][-1] == "full_name" for e in exc.value.errors())


def test_register_rejects_overlong_name():
    with pytest.raises(ValidationError):
        RegisterRequest(full_name="x" * (FULL_NAME_MAX + 1), phone=VALID_PHONE)


@pytest.mark.parametrize(
    "phone",
    ["2348031234567", "+0348031234567", "+abc", "0803 123 4567", "+", "++234"],
)
def test_register_rejects_non_e164_phone(phone):
    with pytest.raises(ValidationError) as exc:
        RegisterRequest(full_name="Amara Okafor", phone=phone)
    assert any(e["loc"][-1] == "phone" for e in exc.value.errors())


@pytest.mark.parametrize(
    "phone", ["+2348031234567", "+27821234567", "+233201234567", "+254712345678"]
)
def test_register_accepts_african_e164_prefixes(phone):
    req = RegisterRequest(full_name="Kwame Mensah", phone=phone)
    assert req.phone == phone


def test_register_missing_fields():
    with pytest.raises(ValidationError) as exc:
        RegisterRequest()
    missing = {e["loc"][-1] for e in exc.value.errors()}
    assert {"full_name", "phone"} <= missing


# --- OTP verify / resend / login --------------------------------------------


def test_verify_otp_accepts_six_digits():
    req = VerifyOtpRequest(phone=VALID_PHONE, code="012345")
    assert req.code == "012345"


@pytest.mark.parametrize("code", ["12345", "1234567", "abcdef", "12 456", ""])
def test_verify_otp_rejects_bad_code(code):
    with pytest.raises(ValidationError) as exc:
        VerifyOtpRequest(phone=VALID_PHONE, code=code)
    assert any(e["loc"][-1] == "code" for e in exc.value.errors())


def test_resend_and_login_require_phone():
    with pytest.raises(ValidationError):
        ResendOtpRequest()
    with pytest.raises(ValidationError):
        LoginRequest()
    assert LoginRequest(phone=VALID_PHONE).phone == VALID_PHONE


# --- Profile: bio and interests ---------------------------------------------


def test_bio_accepts_max_length_and_empty():
    assert BioUpdateRequest(bio="").bio == ""
    assert len(BioUpdateRequest(bio="a" * BIO_MAX).bio) == BIO_MAX


def test_bio_rejects_overlong():
    with pytest.raises(ValidationError) as exc:
        BioUpdateRequest(bio="a" * (BIO_MAX + 1))
    assert any(e["loc"][-1] == "bio" for e in exc.value.errors())


def test_interests_accepts_within_limits():
    interests = [f"interest-{i}" for i in range(INTERESTS_MAX_ITEMS)]
    req = InterestsUpdateRequest(interests=interests)
    assert req.interests == interests


def test_interests_rejects_too_many_items():
    with pytest.raises(ValidationError) as exc:
        InterestsUpdateRequest(interests=["x"] * (INTERESTS_MAX_ITEMS + 1))
    assert any("interests" in e["loc"] for e in exc.value.errors())


def test_interests_rejects_overlong_item():
    with pytest.raises(ValidationError) as exc:
        InterestsUpdateRequest(interests=["ok", "y" * (INTEREST_ITEM_MAX + 1)])
    assert any("interests" in e["loc"] for e in exc.value.errors())


# --- Message send ------------------------------------------------------------


def test_message_accepts_bounds():
    rid = uuid.uuid4()
    assert MessageSendRequest(receiver_id=rid, content="a").content == "a"
    long_ok = MessageSendRequest(receiver_id=rid, content="a" * MESSAGE_CONTENT_MAX)
    assert len(long_ok.content) == MESSAGE_CONTENT_MAX


@pytest.mark.parametrize("content", ["", "a" * (MESSAGE_CONTENT_MAX + 1)])
def test_message_rejects_out_of_range_content(content):
    with pytest.raises(ValidationError) as exc:
        MessageSendRequest(receiver_id=uuid.uuid4(), content=content)
    assert any(e["loc"][-1] == "content" for e in exc.value.errors())


# --- Report ------------------------------------------------------------------


def test_report_accepts_bounds():
    rid = uuid.uuid4()
    assert ReportRequest(reported_user=rid, reason="x").reason == "x"
    assert len(
        ReportRequest(reported_user=rid, reason="x" * REPORT_REASON_MAX).reason
    ) == REPORT_REASON_MAX


@pytest.mark.parametrize("reason", ["", "x" * (REPORT_REASON_MAX + 1)])
def test_report_rejects_out_of_range_reason(reason):
    with pytest.raises(ValidationError) as exc:
        ReportRequest(reported_user=uuid.uuid4(), reason=reason)
    assert any(e["loc"][-1] == "reason" for e in exc.value.errors())


def test_report_missing_fields():
    with pytest.raises(ValidationError) as exc:
        ReportRequest()
    missing = {e["loc"][-1] for e in exc.value.errors()}
    assert {"reported_user", "reason"} <= missing


# --- Admin resolution --------------------------------------------------------


@pytest.mark.parametrize("decision", ["confirmed", "dismissed"])
def test_resolution_accepts_valid_decisions(decision):
    assert ReportResolutionRequest(decision=decision).decision == decision


@pytest.mark.parametrize("decision", ["approved", "pending", "", "Confirmed"])
def test_resolution_rejects_other_decisions(decision):
    with pytest.raises(ValidationError) as exc:
        ReportResolutionRequest(decision=decision)
    assert any(e["loc"][-1] == "decision" for e in exc.value.errors())
