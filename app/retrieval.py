"""As-of retrieval: search only the law that was in force on a given date."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import LegalAct, Provision, ProvisionVersion

_WORD = re.compile(r"[^\w\s]", re.UNICODE)


def to_or_query(query: str) -> str:
    """Turn a natural-language question into a disjunctive tsquery.

    PostgreSQL's `plainto_tsquery` ANDs every term, which is wrong for questions. A user
    asks "how long does a consumer have to withdraw from a distance contract"; the statute
    says "The consumer shall have a period of 14 days to withdraw...". The word "long" never
    appears in the law, so an AND query matches nothing and the system reports — with total
    confidence — that no such provision exists.

    That is the worst possible failure for a legal search: silence indistinguishable from
    "there is no such law". So terms are ORed and `ts_rank` decides ordering. Recall first;
    ranking sorts it out.

    Found by the eval harness, not by the unit tests — the unit tests were querying with
    keywords a lawyer would never type.
    """
    cleaned = _WORD.sub(" ", query)
    terms = [t for t in cleaned.split() if t]
    return " | ".join(terms)


@dataclass(frozen=True)
class Citation:
    """A retrieved provision version, carrying everything needed to cite it."""

    celex: str
    act_title: str
    label: str
    text: str
    in_force_from: date
    in_force_to: date | None
    source_url: str

    def reference(self) -> str:
        """Human-readable citation, explicit about which version this is."""
        until = self.in_force_to.isoformat() if self.in_force_to else "in force"
        return f"{self.act_title}, {self.label} (version {self.in_force_from.isoformat()}–{until})"


def search(session: Session, query: str, as_of: date, limit: int = 5) -> list[Citation]:
    """Full-text search restricted to versions in force on `as_of`.

    The date filter is applied in SQL, not after ranking. Retrieving the top-k across all
    history and *then* discarding out-of-force hits would silently shrink the result set —
    a query could return two results when five in-force provisions matched, because three
    superseded versions outranked them.
    """
    in_force = (
        ProvisionVersion.in_force_from <= as_of,
        or_(ProvisionVersion.in_force_to.is_(None), ProvisionVersion.in_force_to > as_of),
    )

    or_query = to_or_query(query)
    if not or_query:
        return []

    ts_vector = func.to_tsvector("english", ProvisionVersion.text)
    ts_query = func.to_tsquery("english", or_query)

    stmt = (
        select(
            LegalAct.celex,
            LegalAct.title,
            Provision.label,
            ProvisionVersion.text,
            ProvisionVersion.in_force_from,
            ProvisionVersion.in_force_to,
            ProvisionVersion.source_url,
        )
        .join(Provision, Provision.id == ProvisionVersion.provision_id)
        .join(LegalAct, LegalAct.id == Provision.act_id)
        .where(*in_force, ts_vector.op("@@")(ts_query))
        .order_by(func.ts_rank(ts_vector, ts_query).desc())
        .limit(limit)
    )

    return [
        Citation(
            celex=row.celex,
            act_title=row.title,
            label=row.label,
            text=row.text,
            in_force_from=row.in_force_from,
            in_force_to=row.in_force_to,
            source_url=row.source_url,
        )
        for row in session.execute(stmt)
    ]
