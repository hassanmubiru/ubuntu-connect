"""Unit tests for the repository layer against a test database (Task 2.3).

These exercise the repository classes over an isolated in-memory SQLite
engine (the same fixture pattern used by ``test_models.py``). They cover the
create/read round-trips, the unique-phone existence check (Req 1.2), the
ascending conversation ordering (Req 6.3) and descending admin-view helpers
(Req 11.2, 11.3, 11.7), the count helpers consumed by the Trust Engine
(messages sent Req 5.5, confirmed reports Req 5.4) and OTP resend throttle
(trailing 60-minute window Req 2.7/2.8), and the trust-reason
add/list/clear lifecycle (Req 5.6, 5.7).

Fixtures use realistic African data: Amara Okafor (+2348031234567),
Thandiwe Nkosi (+27821234567), Kwame Mensah (+233201234567), and
Zainab Abdullahi (+254712345678).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine

from app import db
from app.models import Base
from app.repositories.message_repository import MessageRepository
from app.repositories.otp_repository import OtpRepository
from app.repositories.report_repository import ReportRepository
from app.repositories.trust_reason_repository import TrustReasonRepository
from app.repositories.user_repository import UserRepository


@pytest.fixture()
def session():
    """Bind an isolated in-memory SQLite engine and yield a live session."""
    engine = create_engine(
        "sqlite://", future=True, connect_args={"check_same_thread": False}
    )
    db.configure_engine(engine)
    Base.metadata.create_all(engine)
    sess = db.get_session_factory()()
    try:
        yield sess
    finally:
        sess.close()
        Base.metadata.drop_all(engine)
        db.reset_engine()


# Realistic African fixture identities used across the tests.
AMARA = ("Amara Okafor", "+2348031234567")
THANDIWE = ("Thandiwe Nkosi", "+27821234567")
KWAME = ("Kwame Mensah", "+233201234567")
ZAINAB = ("Zainab Abdullahi", "+254712345678")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# UserRepository: create/read round-trip and unique-phone existence check
# ---------------------------------------------------------------------------
def test_user_create_read_roundtrip(session) -> None:
    repo = UserRepository(session)
    created = repo.create(
        full_name=AMARA[0],
        phone=AMARA[1],
        bio="Afrobeats producer and mentor.",
        interests=["Afrobeats production", "community gardening"],
    )
    session.commit()

    # Read back by id and by phone; the persisted values round-trip.
    by_id = repo.get_by_id(created.id)
    by_phone = repo.get_by_phone(AMARA[1])
    assert by_id is not None
    assert by_id.id == created.id
    assert by_phone is not None
    assert by_phone.id == created.id
    assert by_id.full_name == AMARA[0]
    assert by_id.phone == AMARA[1]
    assert by_id.bio == "Afrobeats producer and mentor."
    assert by_id.interests == ["Afrobeats production", "community gardening"]
    # Registration defaults (Req 1.1, 1.6).
    assert by_id.verified_phone is False
    assert by_id.trust_score == 0
    assert by_id.is_admin is False
    assert isinstance(by_id.created_at, datetime)


def test_user_get_missing_returns_none(session) -> None:
    repo = UserRepository(session)
    import uuid

    assert repo.get_by_id(uuid.uuid4()) is None
    assert repo.get_by_phone("+2340000000000") is None


def test_user_unique_phone_existence_check(session) -> None:
    repo = UserRepository(session)
    assert repo.exists_by_phone(THANDIWE[1]) is False
    assert repo.count_users() == 0

    repo.create(full_name=THANDIWE[0], phone=THANDIWE[1])
    session.commit()

    # The existence check reports the phone as taken (Req 1.2) and the count
    # helper reflects exactly one user.
    assert repo.exists_by_phone(THANDIWE[1]) is True
    assert repo.exists_by_phone(KWAME[1]) is False
    assert repo.count_users() == 1


# ---------------------------------------------------------------------------
# MessageRepository: ascending history, descending admin helpers, counts
# ---------------------------------------------------------------------------
def _two_users(session) -> tuple:
    users = UserRepository(session)
    a = users.create(full_name=KWAME[0], phone=KWAME[1])
    b = users.create(full_name=AMARA[0], phone=AMARA[1])
    session.flush()
    return a, b


def test_conversation_ordering_ascending(session) -> None:
    # Req 6.3: opening a conversation returns exactly the messages between the
    # two users ordered by created_at ascending.
    a, b = _two_users(session)
    messages = MessageRepository(session)
    base = _now()

    # Insert out of chronological order to prove the query does the ordering.
    m_mid = messages.create(
        sender_id=a.id, receiver_id=b.id, content="second", moderation_result="approved"
    )
    m_mid.created_at = base + timedelta(minutes=5)
    m_old = messages.create(
        sender_id=b.id, receiver_id=a.id, content="first", moderation_result="approved"
    )
    m_old.created_at = base + timedelta(minutes=1)
    m_new = messages.create(
        sender_id=a.id, receiver_id=b.id, content="third", moderation_result="approved"
    )
    m_new.created_at = base + timedelta(minutes=9)
    session.flush()

    convo = messages.conversation_between(a.id, b.id)
    assert [m.content for m in convo] == ["first", "second", "third"]
    # Symmetric: same conversation regardless of argument order.
    assert [m.id for m in messages.conversation_between(b.id, a.id)] == [
        m.id for m in convo
    ]


def test_conversation_excludes_other_pairs(session) -> None:
    a, b = _two_users(session)
    users = UserRepository(session)
    c = users.create(full_name=ZAINAB[0], phone=ZAINAB[1])
    session.flush()
    messages = MessageRepository(session)
    messages.create(
        sender_id=a.id, receiver_id=b.id, content="ab", moderation_result="approved"
    )
    messages.create(
        sender_id=a.id, receiver_id=c.id, content="ac", moderation_result="approved"
    )
    session.flush()

    convo = messages.conversation_between(a.id, b.id)
    assert [m.content for m in convo] == ["ab"]


def test_high_scam_list_descending(session) -> None:
    # Req 8.4/11.7: scam alerts are messages with scam_score >= 70, newest first.
    a, b = _two_users(session)
    messages = MessageRepository(session)
    base = _now()

    low = messages.create(
        sender_id=a.id, receiver_id=b.id, content="benign", moderation_result="approved",
        scam_score=20,
    )
    low.created_at = base + timedelta(minutes=1)
    hi_old = messages.create(
        sender_id=a.id, receiver_id=b.id, content="airtime prize", moderation_result="approved",
        scam_score=88,
    )
    hi_old.created_at = base + timedelta(minutes=2)
    boundary = messages.create(
        sender_id=a.id, receiver_id=b.id, content="urgent money", moderation_result="approved",
        scam_score=70,
    )
    boundary.created_at = base + timedelta(minutes=3)
    unscored = messages.create(
        sender_id=a.id, receiver_id=b.id, content="pending", moderation_result="approved",
    )
    unscored.created_at = base + timedelta(minutes=4)
    session.flush()

    high = messages.list_high_scam()
    # Only >=70 scored messages, ordered created_at descending.
    assert [m.content for m in high] == ["urgent money", "airtime prize"]


def test_list_flagged_descending(session) -> None:
    # Req 7.4/11.2: flagged messages available to admin, newest first.
    a, b = _two_users(session)
    messages = MessageRepository(session)
    base = _now()
    f_old = messages.create(
        sender_id=a.id, receiver_id=b.id, content="flagged old", moderation_result="flagged"
    )
    f_old.created_at = base + timedelta(minutes=1)
    approved = messages.create(
        sender_id=a.id, receiver_id=b.id, content="ok", moderation_result="approved"
    )
    approved.created_at = base + timedelta(minutes=2)
    f_new = messages.create(
        sender_id=a.id, receiver_id=b.id, content="flagged new", moderation_result="flagged"
    )
    f_new.created_at = base + timedelta(minutes=3)
    session.flush()

    flagged = messages.list_flagged()
    assert [m.content for m in flagged] == ["flagged new", "flagged old"]


def test_count_sent_by(session) -> None:
    # Req 5.5: activity factor is the count of messages the user has sent.
    a, b = _two_users(session)
    messages = MessageRepository(session)
    for i in range(3):
        messages.create(
            sender_id=a.id, receiver_id=b.id, content=f"m{i}", moderation_result="approved"
        )
    messages.create(
        sender_id=b.id, receiver_id=a.id, content="reply", moderation_result="approved"
    )
    session.flush()

    assert messages.count_sent_by(a.id) == 3
    assert messages.count_sent_by(b.id) == 1


def test_recent_for_receiver_limit_and_order(session) -> None:
    # Req 13.7: USSD inbox preview shows at most the 5 most recent, newest first.
    a, b = _two_users(session)
    messages = MessageRepository(session)
    base = _now()
    for i in range(7):
        m = messages.create(
            sender_id=a.id, receiver_id=b.id, content=f"msg{i}", moderation_result="approved"
        )
        m.created_at = base + timedelta(minutes=i)
    session.flush()

    recent = messages.recent_for_receiver(b.id, limit=5)
    assert len(recent) == 5
    assert [m.content for m in recent] == ["msg6", "msg5", "msg4", "msg3", "msg2"]


# ---------------------------------------------------------------------------
# ReportRepository: descending list, pending existence, confirmed count
# ---------------------------------------------------------------------------
def test_reports_list_descending(session) -> None:
    # Req 11.3: reports view ordered by created_at descending.
    a, b = _two_users(session)
    reports = ReportRepository(session)
    base = _now()
    r_old = reports.create(reporter=a.id, reported_user=b.id, reason="old reason")
    r_old.created_at = base + timedelta(minutes=1)
    r_new = reports.create(reporter=b.id, reported_user=a.id, reason="new reason")
    r_new.created_at = base + timedelta(minutes=5)
    session.flush()

    ordered = reports.list_ordered()
    assert [r.reason for r in ordered] == ["new reason", "old reason"]


def test_report_defaults_and_has_pending(session) -> None:
    # Req 12.1: new report defaults to status "pending". Req 12.6: duplicate
    # pending existence check.
    a, b = _two_users(session)
    reports = ReportRepository(session)
    assert reports.has_pending(a.id, b.id) is False

    created = reports.create(
        reporter=a.id, reported_user=b.id, reason="Requested money under false pretenses."
    )
    session.flush()
    assert created.status == "pending"
    assert reports.has_pending(a.id, b.id) is True
    # A different reporter has no pending report against b yet.
    assert reports.has_pending(b.id, a.id) is False


def test_count_confirmed_against(session) -> None:
    # Req 5.4: Trust Engine's confirmed-report count factor.
    a, b = _two_users(session)
    reports = ReportRepository(session)
    r1 = reports.create(reporter=a.id, reported_user=b.id, reason="one")
    r2 = reports.create(reporter=a.id, reported_user=b.id, reason="two")
    reports.create(reporter=a.id, reported_user=b.id, reason="pending one")
    session.flush()

    # Only confirmed reports are counted.
    assert reports.count_confirmed_against(b.id) == 0
    reports.set_status(r1, "confirmed")
    reports.set_status(r2, "confirmed")
    session.flush()
    assert reports.count_confirmed_against(b.id) == 2
    assert reports.count_confirmed_against(a.id) == 0


# ---------------------------------------------------------------------------
# OtpRepository: trailing 60-minute request-count window
# ---------------------------------------------------------------------------
def test_count_requests_since_trailing_window(session) -> None:
    # Req 2.7/2.8: resend cap counts OTP requests in the trailing 60 minutes.
    users = UserRepository(session)
    user = users.create(full_name=ZAINAB[0], phone=ZAINAB[1])
    session.flush()
    otps = OtpRepository(session)
    now = _now()

    # Three requests inside the window, two older than 60 minutes.
    inside = [now - timedelta(minutes=m) for m in (1, 30, 59)]
    outside = [now - timedelta(minutes=61), now - timedelta(minutes=120)]
    for created in inside + outside:
        otp = otps.create(
            user_id=user.id,
            code="042198",
            expires_at=created + timedelta(minutes=10),
        )
        otp.created_at = created
    session.flush()

    since = now - timedelta(minutes=60)
    assert otps.count_requests_since(user.id, since) == 3


def test_get_active_for_user_and_invalidate(session) -> None:
    users = UserRepository(session)
    user = users.create(full_name=ZAINAB[0], phone=ZAINAB[1])
    session.flush()
    otps = OtpRepository(session)
    now = _now()

    old = otps.create(
        user_id=user.id, code="111111", expires_at=now + timedelta(minutes=10)
    )
    old.created_at = now - timedelta(minutes=5)
    new = otps.create(
        user_id=user.id, code="222222", expires_at=now + timedelta(minutes=10)
    )
    new.created_at = now
    session.flush()

    # The most recent non-invalidated OTP is authoritative.
    active = otps.get_active_for_user(user.id)
    assert active is not None
    assert active.code == "222222"

    # Invalidating all active OTPs leaves no active code.
    otps.invalidate_all_for_user(user.id)
    session.flush()
    assert otps.get_active_for_user(user.id) is None


def test_increment_failed_attempts(session) -> None:
    users = UserRepository(session)
    user = users.create(full_name=ZAINAB[0], phone=ZAINAB[1])
    session.flush()
    otps = OtpRepository(session)
    otp = otps.create(
        user_id=user.id, code="333333", expires_at=_now() + timedelta(minutes=10)
    )
    session.flush()

    assert otp.failed_attempts == 0
    for _ in range(3):
        otps.increment_failed_attempts(otp)
    session.flush()
    assert otp.failed_attempts == 3


# ---------------------------------------------------------------------------
# TrustReasonRepository: add/list/clear lifecycle
# ---------------------------------------------------------------------------
def test_trust_reason_add_list_clear(session) -> None:
    # Req 5.6/5.7: one row per factor, read back in recorded order; a
    # recalculation clears the prior set first.
    users = UserRepository(session)
    user = users.create(full_name=AMARA[0], phone=AMARA[1])
    session.flush()
    reasons = TrustReasonRepository(session)

    assert reasons.count_for_user(user.id) == 0
    assert reasons.list_for_user(user.id) == []

    reasons.add_many(
        user.id,
        [
            ("phone_verification", 30, "Phone verification: verified (+30)"),
            ("profile_completeness", 20, "Profile completeness: 2 of 3 fields (+20)"),
            ("activity", 15, "Activity: 15 messages (+15)"),
            ("confirmed_reports", 0, "Confirmed reports: 0 (-0)"),
        ],
    )
    session.flush()

    listed = reasons.list_for_user(user.id)
    assert reasons.count_for_user(user.id) == 4
    assert [r.factor for r in listed] == [
        "phone_verification",
        "profile_completeness",
        "activity",
        "confirmed_reports",
    ]
    assert listed[0].contribution == 30
    assert listed[1].description == "Profile completeness: 2 of 3 fields (+20)"

    # Clearing removes the user's reasons ahead of a fresh recalculation.
    reasons.clear_for_user(user.id)
    session.flush()
    assert reasons.count_for_user(user.id) == 0
    assert reasons.list_for_user(user.id) == []


def test_trust_reason_create_single(session) -> None:
    users = UserRepository(session)
    user = users.create(full_name=KWAME[0], phone=KWAME[1])
    session.flush()
    reasons = TrustReasonRepository(session)

    created = reasons.create(
        user_id=user.id,
        factor="activity",
        contribution=40,
        description="Activity: 55 messages capped at +40",
    )
    session.flush()
    assert created.id is not None
    fetched = reasons.list_for_user(user.id)
    assert len(fetched) == 1
    assert fetched[0].contribution == 40
