"""Engine and session wiring."""

from __future__ import annotations

import os
from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql+psycopg://lex:lex@localhost:5433/lex"
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a scoped session."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
