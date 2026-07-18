"""Unit tests for ProfileService and the profile router (Task 6.1).

Covers bio save/round-trip and over-length rejection (Req 4.1, 4.2), interests
save/round-trip plus over-limit rejection that leaves existing interests
unchanged (Req 4.3, 4.4), photo format/size validation and storage (Req 4.5,
4.6, 4.7), the profile view including Trust_Score and Verified_Phone (Req 4.8,
9.4), and that a successful update triggers the Trust Engine recalculation hook
(Req 5.3). AI/OTP are out of scope here.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.pool import StaticPool

from app import db
from app.models import Base, User
from app.repositories.user_repository import UserRepository
from app.routers import auth as auth_router
from app.routers import profiles as profiles_router
from app.routers import trust as trust_router
from app.schemas.common import BIO_MAX, INTEREST_ITEM_MAX, INTERESTS_MAX_ITEMS, MAX_PHOTO_BYTES
from app.schemas.errors import ValidationAppError, register_exception_handlers
from app.services.profile_service import ProfileService

OWNER_PHONE = "+2348031234567"
OTHER_PHONE = "+27821234567"

# Minimal valid magic-byte prefixes for the accepted formats.
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"payload-bytes"
PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"payload-bytes"


@pytest.fixture()
def engine():
    """Bind an isolated in-memory SQLite engine shared across requests."""
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
        "full_name": "Amara Okafor",
        "phone": OWNER_PHONE,
        "verified_phone": True,
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


def _build_app() -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(auth_router.router)
    app.include_router(profiles_router.router)
    app.include_router(trust_router.router)
    return app


@pytest.fixture()
def client(engine) -> TestClient:
    return TestClient(_build_app())


def _token(client: TestClient, phone: str) -> str:
    return client.post("/api/auth/login", json={"phone": phone}).json()["jwt"]


def _auth(client: TestClient, phone: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {_token(client, phone)}"}


# --- Bio (Req 4.1, 4.2) -----------------------------------------------------


def test_bio_saved_and_round_trips_through_profile(client, engine):
    user = _seed_user()
    headers = _auth(client, OWNER_PHONE)
    bio = "Afrobeats producer and community gardener."

    put = client.put("/api/profile/bio", json={"bio": bio}, headers=headers)
    assert put.status_code == 200
    assert put.json()["bio"] == bio

    got = client.get(f"/api/profile/{user.id}", headers=headers)
    assert got.status_code == 200
    assert got.json()["bio"] == bio


def test_bio_at_limit_is_accepted(client, engine):
    _seed_user()
    headers = _auth(client, OWNER_PHONE)
    resp = client.put(
        "/api/profile/bio", json={"bio": "x" * BIO_MAX}, headers=headers
    )
    assert resp.status_code == 200


def test_bio_over_limit_rejected_identifying_bio_field(client, engine):
    _seed_user()
    headers = _auth(client, OWNER_PHONE)
    resp = client.put(
        "/api/profile/bio", json={"bio": "x" * (BIO_MAX + 1)}, headers=headers
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["error"]["code"] == "validation"
    assert any(f["field"] == "bio" for f in body["error"]["fields"])


# --- Interests (Req 4.3, 4.4) -----------------------------------------------


def test_interests_saved_and_round_trips(client, engine):
    user = _seed_user()
    headers = _auth(client, OWNER_PHONE)
    interests = ["Afrobeats production", "community gardening", "mentoring"]

    put = client.put(
        "/api/profile/interests", json={"interests": interests}, headers=headers
    )
    assert put.status_code == 200
    assert put.json()["interests"] == interests

    got = client.get(f"/api/profile/{user.id}", headers=headers)
    assert got.json()["interests"] == interests


def test_interests_at_limits_accepted(client, engine):
    _seed_user()
    headers = _auth(client, OWNER_PHONE)
    interests = ["x" * INTEREST_ITEM_MAX for _ in range(INTERESTS_MAX_ITEMS)]
    resp = client.put(
        "/api/profile/interests", json={"interests": interests}, headers=headers
    )
    assert resp.status_code == 200
    assert len(resp.json()["interests"]) == INTERESTS_MAX_ITEMS


def test_interests_too_many_rejected_and_existing_unchanged(client, engine):
    user = _seed_user(interests=["existing"])
    headers = _auth(client, OWNER_PHONE)
    too_many = [f"i{n}" for n in range(INTERESTS_MAX_ITEMS + 1)]

    resp = client.put(
        "/api/profile/interests", json={"interests": too_many}, headers=headers
    )
    assert resp.status_code == 422
    assert any(f["field"] == "interests" for f in resp.json()["error"]["fields"])

    got = client.get(f"/api/profile/{user.id}", headers=headers)
    assert got.json()["interests"] == ["existing"]


def test_interest_item_too_long_rejected_and_existing_unchanged(client, engine):
    user = _seed_user(interests=["existing"])
    headers = _auth(client, OWNER_PHONE)
    too_long = ["x" * (INTEREST_ITEM_MAX + 1)]

    resp = client.put(
        "/api/profile/interests", json={"interests": too_long}, headers=headers
    )
    assert resp.status_code == 422
    assert any(f["field"] == "interests" for f in resp.json()["error"]["fields"])

    got = client.get(f"/api/profile/{user.id}", headers=headers)
    assert got.json()["interests"] == ["existing"]


def test_interests_rejection_at_service_leaves_stored_value_unchanged(engine):
    """The service validates before writing, so a rejected update never mutates."""
    user = _seed_user(interests=["kept"])
    session = db.get_session_factory()()
    try:
        repo = UserRepository(session)
        fresh = repo.get_by_id(user.id)
        service = ProfileService(repo, "test-bucket")
        with pytest.raises(ValidationAppError):
            service.update_interests(fresh, [f"i{n}" for n in range(21)])
        assert repo.get_by_id(user.id).interests == ["kept"]
    finally:
        session.close()


# --- Photo (Req 4.5, 4.6, 4.7) ----------------------------------------------


@pytest.mark.parametrize(
    "content,content_type,ext",
    [
        (JPEG_BYTES, "image/jpeg", "jpg"),
        (PNG_BYTES, "image/png", "png"),
    ],
)
def test_photo_valid_format_stored(client, engine, content, content_type, ext):
    user = _seed_user()
    headers = {**_auth(client, OWNER_PHONE), "content-type": content_type}
    resp = client.post("/api/profile/photo", content=content, headers=headers)
    assert resp.status_code == 200
    stored = resp.json()["profile_photo"]
    assert stored.endswith(f".{ext}")
    assert str(user.id) in stored

    session = db.get_session_factory()()
    try:
        persisted = session.scalar(select(User).where(User.id == user.id))
        assert persisted.profile_photo == stored
    finally:
        session.close()


def test_photo_wrong_format_rejected_identifying_formats(client, engine):
    _seed_user()
    headers = {**_auth(client, OWNER_PHONE), "content-type": "image/gif"}
    resp = client.post(
        "/api/profile/photo", content=b"GIF89a-not-an-accepted-image", headers=headers
    )
    assert resp.status_code == 422
    body = resp.json()
    reasons = " ".join(f["reason"] for f in body["error"]["fields"])
    assert "JPEG" in reasons and "PNG" in reasons


def test_photo_over_size_limit_rejected_identifying_size(client, engine):
    _seed_user()
    headers = {**_auth(client, OWNER_PHONE), "content-type": "image/jpeg"}
    oversized = b"\xff\xd8\xff\xe0" + b"0" * MAX_PHOTO_BYTES
    resp = client.post("/api/profile/photo", content=oversized, headers=headers)
    assert resp.status_code == 422
    reasons = " ".join(f["reason"] for f in resp.json()["error"]["fields"])
    assert "5 MB" in reasons


def test_photo_at_size_limit_accepted(client, engine):
    _seed_user()
    headers = {**_auth(client, OWNER_PHONE), "content-type": "image/png"}
    body = b"\x89PNG\r\n\x1a\n"
    at_limit = body + b"0" * (MAX_PHOTO_BYTES - len(body))
    assert len(at_limit) == MAX_PHOTO_BYTES
    resp = client.post("/api/profile/photo", content=at_limit, headers=headers)
    assert resp.status_code == 200


# --- Profile view contents (Req 4.8, 9.4) -----------------------------------


def test_profile_view_includes_trust_and_verification(client, engine):
    user = _seed_user(trust_score=82, verified_phone=True)
    headers = _auth(client, OWNER_PHONE)
    resp = client.get(f"/api/profile/{user.id}", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["trust_score"] == 82
    assert body["verified_phone"] is True


def test_profile_view_unknown_user_returns_not_found(client, engine):
    import uuid

    _seed_user()
    headers = _auth(client, OWNER_PHONE)
    resp = client.get(f"/api/profile/{uuid.uuid4()}", headers=headers)
    assert resp.status_code == 404
    assert resp.json()["error"]["code"] == "not_found"


def test_profile_endpoints_require_authentication(client, engine):
    user = _seed_user()
    assert client.get(f"/api/profile/{user.id}").status_code == 401
    assert client.put("/api/profile/bio", json={"bio": "hi"}).status_code == 401


# --- Trust Engine recalculation hook (Req 5.3) ------------------------------


def test_successful_update_triggers_trust_recalc_hook(engine):
    user = _seed_user()
    session = db.get_session_factory()()
    try:
        repo = UserRepository(session)
        fresh = repo.get_by_id(user.id)
        called: list = []
        service = ProfileService(
            repo, "test-bucket", trust_recalc=lambda u: called.append(u.id)
        )
        service.update_bio(fresh, "a new bio")
        service.update_interests(fresh, ["one", "two"])
        service.update_photo(fresh, JPEG_BYTES, "image/jpeg")
        assert called == [user.id, user.id, user.id]
    finally:
        session.close()


def test_rejected_update_does_not_trigger_trust_recalc_hook(engine):
    user = _seed_user()
    session = db.get_session_factory()()
    try:
        repo = UserRepository(session)
        fresh = repo.get_by_id(user.id)
        called: list = []
        service = ProfileService(
            repo, "test-bucket", trust_recalc=lambda u: called.append(u.id)
        )
        with pytest.raises(ValidationAppError):
            service.update_bio(fresh, "x" * (BIO_MAX + 1))
        assert called == []
    finally:
        session.close()
