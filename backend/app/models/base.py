"""Declarative base and shared column types for Ubuntu Connect ORM models.

All ORM entities inherit from :class:`Base`. The module also defines the
cross-dialect column types the data model relies on so the same models run
against PostgreSQL in production (native ``JSONB`` and ``UUID``) and against
SQLite in the test suite (portable ``JSON`` and 32-char UUID storage).

The data model (see design.md "Data Models") mandates UUID primary keys,
a JSONB ``interests`` column on users, explicit VARCHAR lengths, and
timestamp columns; those decisions are centralized here.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Declarative base class shared by every ORM entity."""


# JSONB on PostgreSQL, portable JSON elsewhere (e.g. SQLite under test).
JSONBType = JSONB().with_variant(JSON(), "sqlite")

# ``sqlalchemy.Uuid`` renders as native UUID on PostgreSQL and CHAR(32) on
# dialects without a UUID type, while always mapping to ``uuid.UUID`` in Python.
UUIDType = Uuid(as_uuid=True)


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC ``datetime``.

    Used as the default for ``created_at``/``expires_at`` columns so
    persistence records a real UTC timestamp (Req 1.6, 6.1, 12.1, 2.2).
    """
    return datetime.now(timezone.utc)


def new_uuid() -> uuid.UUID:
    """Generate a random UUID4 for use as a primary key default."""
    return uuid.uuid4()
