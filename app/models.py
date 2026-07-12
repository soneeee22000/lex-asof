"""Bitemporal-lite model for legislation.

The central claim of this repository: **a provision is not a row, it is a sequence of
versions, each in force over a half-open date interval.** Storing "the current text" and
overwriting it on amendment destroys the only thing a legal answer actually needs — the
ability to say what the law *was* on the date the dispute arose.

So `ProvisionVersion` carries `in_force_from` / `in_force_to`, and every retrieval is
filtered by an as-of date. `in_force_to IS NULL` means "still in force"; the interval is
half-open, `[from, to)`, so a version that ends the day its successor begins produces
exactly one hit, never zero and never two.
"""

from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import Date, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Declarative base."""


class LegalAct(Base):
    """A legal instrument — a regulation, directive, code, or statute."""

    __tablename__ = "legal_act"

    id: Mapped[int] = mapped_column(primary_key=True)
    celex: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(Text)
    jurisdiction: Mapped[str] = mapped_column(String(16))

    provisions: Mapped[list[Provision]] = relationship(back_populates="act")


class Provision(Base):
    """A stable, citable unit of an act — e.g. "Article 6" of the GDPR.

    The provision's *identity* is stable across amendments. Its *text* is not. That
    distinction is why this table holds no text at all.
    """

    __tablename__ = "provision"
    __table_args__ = (UniqueConstraint("act_id", "label", name="uq_provision_act_label"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    act_id: Mapped[int] = mapped_column(ForeignKey("legal_act.id"), index=True)
    label: Mapped[str] = mapped_column(String(64))

    act: Mapped[LegalAct] = relationship(back_populates="provisions")
    versions: Mapped[list[ProvisionVersion]] = relationship(back_populates="provision")


class ProvisionVersion(Base):
    """The text of a provision as it stood over one interval of time."""

    __tablename__ = "provision_version"
    __table_args__ = (
        Index("ix_version_asof", "provision_id", "in_force_from", "in_force_to"),
        UniqueConstraint("provision_id", "in_force_from", name="uq_version_provision_from"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    provision_id: Mapped[int] = mapped_column(ForeignKey("provision.id"), index=True)
    text: Mapped[str] = mapped_column(Text)

    # Content hash makes re-ingestion idempotent: re-running the pipeline over an
    # unchanged source must not create a second, identical version.
    content_hash: Mapped[str] = mapped_column(String(64), index=True)

    in_force_from: Mapped[date] = mapped_column(Date)
    in_force_to: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Provenance. An answer that cannot name where its text came from is not an answer.
    source_url: Mapped[str] = mapped_column(Text)
    amended_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    provision: Mapped[Provision] = relationship(back_populates="versions")

    @staticmethod
    def hash_text(text: str) -> str:
        """Stable content hash, whitespace-normalised.

        Legal sources reflow whitespace between publications without changing the law.
        Hashing the raw bytes would report a phantom amendment every time a publisher
        rewraps a paragraph.
        """
        normalised = " ".join(text.split())
        return hashlib.sha256(normalised.encode("utf-8")).hexdigest()
