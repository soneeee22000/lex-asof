"""Seed the SYNTHETIC fixture corpus.

⚠️  Everything in here is invented. The act names, the CELEX identifiers, the article text
and the amendment dates are all fictional, and they are named so that they cannot be
mistaken for real instruments.

That is deliberate. This repository demonstrates a *mechanism* — versioned ingestion and
point-in-time retrieval — and the mechanism must be demonstrable offline, with no API key
and no network. Shipping plausible-looking but subtly wrong real legislation would be worse
than shipping obvious fiction: a reader might believe it.

For real data, use `scripts/fetch_eurlex.py`, which ingests actual consolidated acts from
EUR-Lex. The pipeline is identical; only the source changes.
"""

from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

from app.ingest import IngestedProvision, ingest
from app.models import Base

FIXTURE_SOURCE = "https://example.invalid/fixtures/dsd-001"

# The same provision, before and after a fictional amendment. This pair is the whole demo:
# one question, two dates, two different answers — both correct.
ORIGINAL = IngestedProvision(
    celex="FIXTURE-DSD-001",
    act_title="Model Distance Selling Directive (synthetic fixture)",
    jurisdiction="EU",
    label="Article 9",
    text="The consumer shall have a period of 14 days to withdraw from a distance contract.",
    in_force_from=date(2014, 6, 13),
    source_url=FIXTURE_SOURCE,
)

AMENDED = IngestedProvision(
    celex="FIXTURE-DSD-001",
    act_title="Model Distance Selling Directive (synthetic fixture)",
    jurisdiction="EU",
    label="Article 9",
    text="The consumer shall have a period of 30 days to withdraw from a distance contract.",
    in_force_from=date(2022, 5, 28),
    source_url=FIXTURE_SOURCE,
    amended_by="FIXTURE-AMD-002",
)


def seed(session: Session) -> None:
    """Reset and load the fixture corpus. Idempotent by construction."""
    Base.metadata.drop_all(session.get_bind())
    Base.metadata.create_all(session.get_bind())
    ingest(session, [ORIGINAL])
    ingest(session, [AMENDED])


if __name__ == "__main__":
    from app.db import SessionLocal

    with SessionLocal() as session:
        seed(session)
    print("Seeded the synthetic fixture corpus.")
    print("Try:  /ask?q=withdraw+distance+contract&as_of=2019-01-01   -> 14 days")
    print("      /ask?q=withdraw+distance+contract&as_of=2024-01-01   -> 30 days")
