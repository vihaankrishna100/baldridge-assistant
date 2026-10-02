"""SQLAlchemy wiring for the SQLite backend.

The engine is built lazily, and that is load-bearing rather than tidiness.
`models.py` imports `Base` from here, `deps.py` imports `models`, and every
route imports `deps` — so importing the application used to construct a
SQLAlchemy engine from DATABASE_URL before anything had decided which backend
was in play. With a Postgres DSN that makes SQLAlchemy import psycopg2, which
this project does not use (psycopg 3 talks to Neon directly, through
repo/postgres_repo.py) and does not ship. The app would fail at import on the
first request.

Now nothing connects until something actually asks for a session, which only
the SQLite repository ever does.
"""

from pathlib import Path

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from config import BASE_DIR, settings


class Base(DeclarativeBase):
    """Declarative base. Importing this must not require a database."""


_engine = None
_session_factory = None


def _resolve_url() -> str:
    url = settings.database_url
    if url.startswith("sqlite:///./"):
        db_path = BASE_DIR / url.replace("sqlite:///./", "")
        db_path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite:///{db_path}"
    return url


def _ensure() -> None:
    global _engine, _session_factory
    if _engine is None:
        url = _resolve_url()
        _engine = create_engine(
            url,
            connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        )
        _session_factory = sessionmaker(bind=_engine, autoflush=False, autocommit=False)


def __getattr__(name: str):
    """Lazy module attributes.

    `database.engine` and `database.SessionLocal` keep working for every
    existing caller, including selftest.py, which assigns over them to point
    at an in-memory database. A direct assignment creates a real module
    attribute, which shadows this hook from then on.
    """
    if name == "engine":
        _ensure()
        return _engine
    if name == "SessionLocal":
        _ensure()
        return _session_factory
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def get_db():
    _ensure()
    db = _session_factory()
    try:
        yield db
    finally:
        db.close()


# Columns added after the first release. Adding them here (rather than dropping
# the DB) keeps existing document/audit history intact across upgrades.
MIGRATIONS: list[tuple[str, str, str]] = [
    # (table, column, DDL type)
]


def run_migrations() -> None:
    _ensure()
    inspector = inspect(_engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, ddl in MIGRATIONS:
            if table not in existing_tables:
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
