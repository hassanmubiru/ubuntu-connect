"""Unit tests for the Trust Engine service and endpoints (Task 7.1).

Covers the deterministic four-factor score (Req 5.1, 5.5), the recorded
reason set written on each recalculation (Req 5.6), the current-score and
explanation endpoints (Req 5.1, 5.7), and the no-explanation error path
(Req 5.8). These are example-based sanity checks for the implementation;
the exhaustive property tests live in their own tasks.
"""

from __future__ import annotations

import uuid

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app import db
from app.models import Base, Message, Report, User
from app.repositories.message_repository import MessageRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.trust_reason_repository import TrustReasonRepository
from app.repositories.user_repository import UserRepository
from app.routers import trust as trust_router
from app.schemas.errors import NotFoundError, register_exception_handlers
from app.services.trust_engine import (
    FACTOR_ACTIVITY,
    FACTOR_CONFIRMED_REPORTS,
    FACTOR_PHONE_VERIFICATION,
    FACTOR_PROFILE_COMPLETENESS,
    TrustEngine,
)

ZAINAB_PHONE = "+254712345678"
AMARA_PHONE = "+2348031234567"


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite://",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db.configure_engine(eng)
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        Base.metadata.drop_all(eng)
        db.reset_engine()


def _seed_user(**overrides) -> User:
    data = {
        "full_name": "Zainab Abdullahi",
        "phone": ZAINAB_PHONE,
        "verified_phone": False,
        "trust_score": 0,
    }
    data.update(overrides)
    session = db.get_session_factory()()
    try:
        user = User(**data)
        session.add(user)
        session.commit()
        session.refresh(user)
        return user
    finally:
        session.close()


def _add_messages(sender_id: uuid.UUID, receiver_id: uuid.UUID, n: int) -> None:
    session = db.get_session_factory()()
    try:
        for i in range(n):
            session.add(
                Message(
                    sender_id=sender_id,
                    receiver_id=receiver_id,
                    content=f"message {i}",
                    moderation_result="approved",
                    scam_score=0,
                    delivered=True,
                )
            )
        session.commit()
    finally:
        session.close()


def _add_confirmed_report(reporter: uuid.UUID, reported: uuid.UUID) -> None:
    session = db.get_session_factory()()
    try:
        session.add(
            Report(
                reporter=reporter,
                reported_user=reported,
                reason="confirmed bad behaviour",
                status="confirmed",
            )
        )
        session.commit()
    finally:
        session.close()


def _engine_for_session() -> tuple[TrustEngine, object]:
    session = db.get_session_factory()()
    eng = TrustEngine(
        UserRepository(session),
        MessageRepository(session),
        ReportRepository(session),
        TrustReasonRepository(session),
    )
    return eng, session


# --- Service: scoring and reasons ------------------------------------------


def test_recalculate_computes_documented_score(engine):
    # Unverified, 1 populated field (bio), 15 messages, 0 confirmed reports.
    # raw = 0 + 10 + min(15,40) - 0 = 25
    user = _seed_user(bio="isiZulu poetry lover", verified_phone=False)
    other = _seed_user(phone=AMARA_PHONE, full_name="Amara Okafor")
    _add_messages(user.id, other.id, 15)

    eng, session = _engine_for_session()
    try:
        result = eng.recalculate(user.id)
        session.commit()
    finally:
        session.close()

    assert result.trust_score == 25
    factors = {f: c for f, c, _d in result.reasons}
    assert factors[FACTOR_PHONE_VERIFICATION] == 0
    assert factors[FACTOR_PROFILE_COMPLETENESS] == 10
    assert factors[FACTOR_ACTIVITY] == 15
    assert factors[FACTOR_CONFIRMED_REPORTS] == 0


def test_recalculate_clamps_and_caps(engine):
    # Verified (+30), 3 fields (+30), 100 messages capped at 40 → 100, no reports.
    user = _seed_user(
        verified_phone=True,
        bio="fintech meetups",
        interests=["afrobeats", "swahili"],
        profile_photo="s3://bucket/photo.jpg",
    )
    other = _seed_user(phone=AMARA_PHONE, full_name="Amara Okafor")
    _add_messages(user.id, other.id, 100)

    eng, session = _engine_for_session()
    try:
        result = eng.recalculate(user.id)
        session.commit()
    finally:
        session.close()

    # 30 + 30 + 40 = 100, clamped stays 100.
    assert result.trust_score == 100
    activity = {f: c for f, c, _d in result.reasons}[FACTOR_ACTIVITY]
    assert activity == 40


def test_confirmed_reports_lower_the_score(engine):
    user = _seed_user(verified_phone=True)  # +30 only
    reporter = _seed_user(phone=AMARA_PHONE, full_name="Amara Okafor")
    _add_confirmed_report(reporter.id, user.id)  # -15
    _add_confirmed_report(reporter.id, user.id)  # another -15 → 30-30 = 0

    eng, session = _engine_for_session()
    try:
        result = eng.recalculate(user.id)
        session.commit()
    finally:
        session.close()

    assert result.trust_score == 0
    assert {f: c for f, c, _d in result.reasons}[FACTOR_CONFIRMED_REPORTS] == -30


def test_recalculate_records_one_row_per_factor_and_replaces_prior(engine):
    user = _seed_user(verified_phone=True)

    eng, session = _engine_for_session()
    try:
        eng.recalculate(user.id)
        session.commit()
        eng.recalculate(user.id)  # second run must not duplicate rows
        session.commit()
        reasons = TrustReasonRepository(session).list_for_user(user.id)
    finally:
        session.close()

    assert len(reasons) == 4
    assert {r.factor for r in reasons} == {
        FACTOR_PHONE_VERIFICATION,
        FACTOR_PROFILE_COMPLETENESS,
        FACTOR_ACTIVITY,
        FACTOR_CONFIRMED_REPORTS,
    }


def test_recalculate_unknown_user_raises_not_found(engine):
    eng, session = _engine_for_session()
    try:
        with pytest.raises(NotFoundError):
            eng.recalculate(uuid.uuid4())
    finally:
        session.close()


# --- Endpoints -------------------------------------------------------------


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(trust_router.router)
    return app


@pytest.fixture()
def client(engine) -> TestClient:
    return TestClient(_build_app())


def test_get_score_endpoint_returns_current_score(client, engine):
    user = _seed_user(trust_score=42)
    resp = client.get(f"/api/trust/{user.id}")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == str(user.id)
    assert body["trust_score"] == 42


def test_get_score_unknown_user_returns_not_found(client, engine):
    resp = client.get(f"/api/trust/{uuid.uuid4()}")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_explanation_endpoint_returns_recorded_reasons(client, engine):
    user = _seed_user(verified_phone=True, bio="Swahili literature")

    eng, session = _engine_for_session()
    try:
        eng.recalculate(user.id)
        session.commit()
    finally:
        session.close()

    resp = client.get(f"/api/trust/{user.id}/explanation")
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == str(user.id)
    assert len(body["reasons"]) == 4
    factors = {r["factor"] for r in body["reasons"]}
    assert FACTOR_PHONE_VERIFICATION in factors


def test_explanation_without_reasons_returns_no_explanation_error(client, engine):
    user = _seed_user()  # never recalculated → no reason rows
    resp = client.get(f"/api/trust/{user.id}/explanation")
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"
