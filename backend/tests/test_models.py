"""Unit tests for the ORM models and DB session wiring (Task 2.1).

These verify the declarative models import and map cleanly, that the schema
creates on an in-memory SQLite engine, that requirement-driven defaults are
applied (verified_phone false, trust_score 0, created_at set), that the
unique-phone constraint holds, that the JSONB ``interests`` column round-trips
a list of strings, and that the transactional ``get_session`` dependency
commits on success and rolls back on error.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError

from app import db
from app.models import (
    Base,
    Message,
    NotificationFailure,
    OtpCode,
    Report,
    TrustReason,
    User,
)


@pytest.fixture()
def session_factory():
    """Bind an isolated in-memory SQLite engine and create the schema."""
    engine = create_engine(
        "sqlite://", future=True, connect_args={"check_same_thread": False}
    )
    db.configure_engine(engine)
    Base.metadata.create_all(engine)
    try:
        yield db.get_session_factory()
    finally:
        Base.metadata.drop_all(engine)
        db.reset_engine()


def _make_user(**overrides) -> User:
    data = {
        "full_name": "Amara Okafor",
        "phone": "+2348031234567",
        "interests": ["Afrobeats production", "community gardening"],
    }
    data.update(overrides)
    return User(**data)


def test_all_models_import_and_map() -> None:
    # Importing the package must register every table on the shared metadata.
    tables = set(Base.metadata.tables)
    assert {
        "users",
        "messages",
        "reports",
        "trust_reasons",
        "otp_codes",
        "notification_failures",
    } <= tables


def test_user_defaults_and_roundtrip(session_factory) -> None:
    session = session_factory()
    try:
        user = _make_user()
        session.add(user)
        session.commit()
        session.refresh(user)

        assert isinstance(user.id, uuid.UUID)
        assert user.verified_phone is False
        assert user.trust_score == 0
        assert user.is_admin is False
        assert user.bio is None
        assert user.profile_photo is None
        assert isinstance(user.created_at, datetime)
        # JSONB interests round-trips as the same list of strings.
        assert user.interests == ["Afrobeats production", "community gardening"]
    finally:
        session.close()


def test_phone_unique_constraint(session_factory) -> None:
    session = session_factory()
    try:
        session.add(_make_user(phone="+27821234567", full_name="Thandiwe Nkosi"))
        session.commit()
        session.add(_make_user(phone="+27821234567", full_name="Someone Else"))
        with pytest.raises(IntegrityError):
            session.commit()
    finally:
        session.rollback()
        session.close()


def test_related_entities_persist(session_factory) -> None:
    session = session_factory()
    try:
        sender = _make_user(phone="+233201234567", full_name="Kwame Mensah")
        receiver = _make_user(phone="+254712345678", full_name="Zainab Abdullahi")
        session.add_all([sender, receiver])
        session.commit()

        message = Message(
            sender_id=sender.id,
            receiver_id=receiver.id,
            content="I need you to send airtime to unlock your prize before midnight.",
            moderation_result="approved",
            scam_score=88,
        )
        report = Report(
            reporter=receiver.id,
            reported_user=sender.id,
            reason="Requested money under false pretenses.",
        )
        reason = TrustReason(
            user_id=sender.id,
            factor="phone_verification",
            contribution=30,
            description="Phone verification: verified (+30)",
        )
        otp = OtpCode(
            user_id=sender.id,
            code="042198",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=10),
        )
        failure = NotificationFailure(
            phone=receiver.phone, notification_type="safety_alert"
        )
        session.add_all([message, report, reason, otp, failure])
        session.commit()

        # scam_score is nullable but stored when provided; defaults applied.
        assert message.scam_score == 88
        assert message.delivered is False
        assert report.status == "pending"
        assert otp.failed_attempts == 0
        assert otp.invalidated is False
    finally:
        session.close()


def test_scam_score_nullable(session_factory) -> None:
    session = session_factory()
    try:
        u = _make_user(phone="+2348030000001")
        v = _make_user(phone="+2348030000002")
        session.add_all([u, v])
        session.commit()
        msg = Message(
            sender_id=u.id,
            receiver_id=v.id,
            content="hello there",
            moderation_result="flagged",
        )
        session.add(msg)
        session.commit()
        session.refresh(msg)
        assert msg.scam_score is None
    finally:
        session.close()


def test_get_session_commits_on_success(session_factory) -> None:
    gen = db.get_session()
    session = next(gen)
    session.add(_make_user(phone="+2348039999999"))
    # Closing the generator (no exception) triggers commit.
    with pytest.raises(StopIteration):
        next(gen)

    verify = session_factory()
    try:
        stored = verify.scalar(
            select(User).where(User.phone == "+2348039999999")
        )
        assert stored is not None
    finally:
        verify.close()


def test_get_session_rolls_back_on_exception(session_factory) -> None:
    gen = db.get_session()
    session = next(gen)
    session.add(_make_user(phone="+2348038888888"))
    # Throwing into the generator must roll the transaction back.
    with pytest.raises(RuntimeError):
        gen.throw(RuntimeError("boom"))

    verify = session_factory()
    try:
        stored = verify.scalar(
            select(User).where(User.phone == "+2348038888888")
        )
        assert stored is None
    finally:
        verify.close()
