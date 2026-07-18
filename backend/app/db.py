"""Database engine, session factory, and the transactional session dependency.

The engine and session factory are created lazily so that importing this
module (and the ORM models) never requires a live ``DATABASE_URL``; the URL
is read from :class:`app.config.Config` only when a session is first needed.
This keeps model imports and unit tests independent of a configured database.

Routers depend on :func:`get_session`, which yields a SQLAlchemy ``Session``
wrapped in a unit-of-work: the transaction commits when the handler returns
normally and rolls back if it raises, so a failed request never leaves a
partial write behind (Req 16.2).

Tests (and any embedded/alternate database) call :func:`configure_engine`
to bind a specific engine (e.g. an in-memory SQLite database) before use.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Config
from app.models.base import Base

_engine: Engine | None = None
_session_factory: sessionmaker[Session] | None = None


def _resolve_database_url() -> str:
    """Read ``DATABASE_URL`` from the environment via :class:`Config`."""
    return Config.from_env().database_url


def create_db_engine(url: str | None = None, **engine_kwargs) -> Engine:
    """Create a SQLAlchemy :class:`Engine` for ``url`` (or the configured URL).

    SQLite URLs receive ``check_same_thread=False`` so the same in-memory
    database can be shared across the request/dependency threads used in tests.
    """
    resolved = url or _resolve_database_url()
    connect_args: dict[str, object] = {}
    if resolved.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    return create_engine(
        resolved, future=True, connect_args=connect_args, **engine_kwargs
    )


def get_engine() -> Engine:
    """Return the process-wide engine, creating it on first use."""
    global _engine
    if _engine is None:
        _engine = create_db_engine()
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide session factory, creating it on first use."""
    global _session_factory
    if _session_factory is None:
        _session_factory = sessionmaker(
            bind=get_engine(), class_=Session, expire_on_commit=False, future=True
        )
    return _session_factory


def configure_engine(engine: Engine) -> Engine:
    """Bind ``engine`` as the active engine and rebuild the session factory.

    Intended for tests and alternate runtimes that need to inject a specific
    engine (such as an in-memory SQLite database) instead of the one derived
    from ``DATABASE_URL``.
    """
    global _engine, _session_factory
    _engine = engine
    _session_factory = sessionmaker(
        bind=engine, class_=Session, expire_on_commit=False, future=True
    )
    return engine


def reset_engine() -> None:
    """Discard the cached engine/session factory (used to isolate tests)."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


def create_all() -> None:
    """Create every table on the active engine (dev/test convenience)."""
    Base.metadata.create_all(get_engine())


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a transactional session.

    Commits on normal completion, rolls back on any exception, and always
    closes the session. Routers use this so each request runs as one atomic
    unit of work with no partial writes on failure (Req 16.2).
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
