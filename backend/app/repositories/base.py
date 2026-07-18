"""Base repository and shared query primitives (Req 15.1).

Every repository owns a single SQLAlchemy :class:`~sqlalchemy.orm.Session`
and is the *only* place data-store queries are issued. Services receive
repository instances through FastAPI dependency injection (see
``app.repositories.dependencies``) and therefore never import ``sqlalchemy``
or touch a session directly, satisfying the repository-boundary rule.

Repositories do not commit or roll back: the request-scoped
``get_session`` dependency wraps each request in a unit of work that commits
on success and rolls back on failure (Req 16.2). ``flush`` is used where a
generated primary key or a uniqueness constraint must be observed before the
request completes.
"""

from __future__ import annotations

import uuid
from typing import Generic, TypeVar

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)

# The ascending/descending ordering helpers accept these string tokens so
# callers (services) express intent without importing SQLAlchemy operators.
ASC = "asc"
DESC = "desc"


class BaseRepository(Generic[ModelT]):
    """Common create/read/count helpers over a single ORM model.

    Subclasses set :attr:`model` and add domain-specific queries. All
    persistence flows through the injected ``session``; transaction control
    stays with the request-scoped session dependency.
    """

    model: type[ModelT]

    def __init__(self, session: Session) -> None:
        self.session = session

    # -- writes ---------------------------------------------------------
    def add(self, entity: ModelT) -> ModelT:
        """Stage ``entity`` for insertion and flush so its key is assigned.

        Flushing surfaces database-level constraints (e.g. the unique phone
        index) within the current transaction while leaving the final
        commit/rollback decision to the session dependency.
        """
        self.session.add(entity)
        self.session.flush()
        return entity

    def flush(self) -> None:
        """Flush pending changes so updates/constraints take effect now."""
        self.session.flush()

    # -- reads ----------------------------------------------------------
    def get(self, entity_id: uuid.UUID) -> ModelT | None:
        """Return the entity with ``entity_id`` or ``None`` if absent."""
        return self.session.get(self.model, entity_id)

    def list_all(self) -> list[ModelT]:
        """Return every row for this model (small tables / admin views)."""
        return list(self.session.scalars(select(self.model)).all())

    def count(self) -> int:
        """Return the total number of rows for this model."""
        return int(
            self.session.scalar(select(func.count()).select_from(self.model)) or 0
        )
