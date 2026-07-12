"""Test fixtures. Tests run against a real PostgreSQL, never SQLite.

The as-of filter and the ranking both rely on PostgreSQL full-text search. Testing against
SQLite would mean testing a different query than the one that runs in production - the
tests would pass and the system would still be broken.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.models import Base

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL", "postgresql+psycopg://lex:lex@localhost:5433/lex"
)


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    eng = create_engine(TEST_DATABASE_URL)
    with eng.connect() as conn:
        conn.execute(text("SELECT 1"))
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    sess = factory()
    try:
        yield sess
    finally:
        sess.close()
