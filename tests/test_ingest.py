"""Ingestion is where legal RAG is usually wrong, so it is specified first.

The failure this guards against: re-running the pipeline over an amended source and either
(a) overwriting the old text, destroying history, or (b) appending a duplicate version so
an as-of query returns two conflicting answers.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.ingest import IngestedProvision, ingest
from app.models import ProvisionVersion


def _provision(text: str, in_force_from: date) -> IngestedProvision:
    return IngestedProvision(
        celex="FIXTURE-DPR-001",
        act_title="Model Data Protection Regulation (synthetic fixture)",
        jurisdiction="EU",
        label="Article 6",
        text=text,
        in_force_from=in_force_from,
        source_url="https://example.invalid/fixtures/dpr-001",
    )


def test_first_ingestion_creates_an_open_ended_version(session: Session) -> None:
    ingest(session, [_provision("Processing shall be lawful only if...", date(2018, 5, 25))])

    versions = session.query(ProvisionVersion).all()
    assert len(versions) == 1
    assert versions[0].in_force_from == date(2018, 5, 25)
    assert versions[0].in_force_to is None  # still in force


def test_reingesting_identical_text_is_idempotent(session: Session) -> None:
    """Re-running the pipeline over an unchanged source must not fork history."""
    record = _provision("Processing shall be lawful only if...", date(2018, 5, 25))
    ingest(session, [record])
    ingest(session, [record])
    ingest(session, [record])

    assert session.query(ProvisionVersion).count() == 1


def test_whitespace_reflow_is_not_an_amendment(session: Session) -> None:
    """Publishers rewrap paragraphs. That is not a change in the law."""
    ingest(session, [_provision("Processing shall be lawful\nonly if...", date(2018, 5, 25))])
    ingest(session, [_provision("Processing shall be lawful   only if...", date(2018, 5, 25))])

    assert session.query(ProvisionVersion).count() == 1


def test_amendment_closes_the_prior_version_and_opens_a_new_one(session: Session) -> None:
    """The core contract: history is preserved, and the intervals do not overlap."""
    ingest(session, [_provision("Original text.", date(2018, 5, 25))])
    ingest(session, [_provision("Amended text.", date(2024, 1, 1))])

    versions = session.query(ProvisionVersion).order_by(ProvisionVersion.in_force_from).all()
    assert len(versions) == 2

    old, new = versions
    assert old.text == "Original text."
    assert old.in_force_to == date(2024, 1, 1)  # closed, half-open: [from, to)
    assert new.text == "Amended text."
    assert new.in_force_from == date(2024, 1, 1)
    assert new.in_force_to is None


def test_intervals_are_contiguous_and_non_overlapping(session: Session) -> None:
    """No gap, no overlap. A gap means an as-of query returns nothing for a date on which
    the law plainly existed; an overlap means it returns two conflicting texts."""
    ingest(session, [_provision("v1", date(2018, 5, 25))])
    ingest(session, [_provision("v2", date(2020, 1, 1))])
    ingest(session, [_provision("v3", date(2024, 1, 1))])

    versions = session.query(ProvisionVersion).order_by(ProvisionVersion.in_force_from).all()
    assert [v.in_force_to for v in versions] == [date(2020, 1, 1), date(2024, 1, 1), None]

    for earlier, later in zip(versions, versions[1:], strict=False):
        assert earlier.in_force_to == later.in_force_from


def test_backdated_amendment_is_rejected_rather_than_silently_corrupting_history(
    session: Session,
) -> None:
    """A source that reports an amendment older than the version already in force is a bug
    upstream. Accepting it would silently produce overlapping intervals — better to fail
    loudly than to serve two contradictory texts for one date."""
    ingest(session, [_provision("v2", date(2024, 1, 1))])

    try:
        ingest(session, [_provision("v1-late", date(2018, 5, 25))])
    except ValueError as exc:
        assert "backdated" in str(exc).lower()
    else:  # pragma: no cover
        raise AssertionError("expected a backdated amendment to be rejected")
