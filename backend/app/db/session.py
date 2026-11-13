from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import Request
from sqlalchemy import MetaData, create_engine, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.db.base import Base


class Database:
    """One engine per process; a fresh Session per request or worker context."""

    def __init__(self, settings: Settings):
        Path(make_url(settings.database_url).database).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False, "timeout": 5, "autocommit": False},
            echo=False,
            hide_parameters=True,
        )

        @event.listens_for(self.engine, "connect")
        def configure_sqlite(connection, _record):
            original = connection.autocommit
            connection.autocommit = True
            try:
                cursor = connection.cursor()
                try:
                    cursor.execute("PRAGMA busy_timeout=5000")
                    cursor.execute("PRAGMA journal_mode=WAL")
                    if cursor.fetchone()[0].lower() != "wal":
                        raise RuntimeError("SQLite WAL unavailable")
                    cursor.execute("PRAGMA foreign_keys=ON")
                    cursor.execute("PRAGMA foreign_keys")
                    if cursor.fetchone()[0] != 1:
                        raise RuntimeError("SQLite foreign key enforcement unavailable")
                finally:
                    cursor.close()
            finally:
                connection.autocommit = original

        self.session_factory = sessionmaker(bind=self.engine, expire_on_commit=False)

    def initialize(self, metadata: MetaData | None = None) -> None:
        # No drop/reset and no automatic seed data. At T007 Base has no domain tables.
        (metadata if metadata is not None else Base.metadata).create_all(self.engine)

    @contextmanager
    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def dispose(self) -> None:
        self.engine.dispose()


def get_session(request: Request) -> Iterator[Session]:
    with request.app.state.database.session() as session:
        # The caller controls short commit boundaries. No implicit success commit.
        yield session
