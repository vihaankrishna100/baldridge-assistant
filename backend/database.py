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


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
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
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, column, ddl in MIGRATIONS:
            if table not in existing_tables:
                continue
            cols = {c["name"] for c in inspector.get_columns(table)}
            if column not in cols:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
