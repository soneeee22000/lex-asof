"""Retrieval must answer as of a date, not as of today."""

from datetime import date

from sqlalchemy.orm import Session

from app.ingest import IngestedProvision, ingest
from app.retrieval import search


def _seed(session: Session) -> None:
    ingest(
        session,
        [
            IngestedProvision(
                celex="FIXTURE-DSD-001",
                act_title="Model Distance Selling Directive (synthetic fixture)",
                jurisdiction="EU",
                label="Article 9",
                text=(
                    "The consumer shall have a period of 14 days to withdraw from a "
                    "distance contract."
                ),
                in_force_from=date(2014, 6, 13),
                source_url="https://example.invalid/fixtures/dsd-001",
            )
        ],
    )
    ingest(
        session,
        [
            IngestedProvision(
                celex="FIXTURE-DSD-001",
                act_title="Model Distance Selling Directive (synthetic fixture)",
                jurisdiction="EU",
                label="Article 9",
                text=(
                    "The consumer shall have a period of 30 days to withdraw from a "
                    "distance contract."
                ),
                in_force_from=date(2022, 5, 28),
                source_url="https://example.invalid/fixtures/dsd-001",
                amended_by="FIXTURE-AMD-002",
            )
        ],
    )


def test_query_before_the_amendment_returns_the_old_text(session: Session) -> None:
    _seed(session)

    hits = search(session, "withdraw distance contract", as_of=date(2019, 1, 1))

    assert len(hits) == 1
    assert "14 days" in hits[0].text


def test_query_after_the_amendment_returns_the_new_text(session: Session) -> None:
    _seed(session)

    hits = search(session, "withdraw distance contract", as_of=date(2024, 1, 1))

    assert len(hits) == 1
    assert "30 days" in hits[0].text


def test_the_same_query_yields_different_law_on_different_dates(session: Session) -> None:
    """This single assertion is the entire point of the repository."""
    _seed(session)

    before = search(session, "withdraw distance contract", as_of=date(2019, 1, 1))
    after = search(session, "withdraw distance contract", as_of=date(2024, 1, 1))

    assert before[0].text != after[0].text


def test_boundary_date_belongs_to_the_new_version(session: Session) -> None:
    """Half-open intervals: on the day an amendment enters into force, the new text governs
    and exactly one version matches."""
    _seed(session)

    hits = search(session, "withdraw distance contract", as_of=date(2022, 5, 28))

    assert len(hits) == 1
    assert "30 days" in hits[0].text


def test_query_before_the_law_existed_returns_nothing(session: Session) -> None:
    """Better to return no law than to return law that had not been enacted yet."""
    _seed(session)

    hits = search(session, "withdraw distance contract", as_of=date(2010, 1, 1))

    assert hits == []


def test_citation_names_the_version_it_came_from(session: Session) -> None:
    _seed(session)

    hits = search(session, "withdraw distance contract", as_of=date(2019, 1, 1))

    reference = hits[0].reference()
    assert "Article 9" in reference
    assert "2014-06-13" in reference
    assert "2022-05-28" in reference  # the date this version stopped being the law


def test_a_natural_language_question_matches_even_when_words_are_absent_from_the_statute(
    session: Session,
) -> None:
    """Regression: `plainto_tsquery` ANDs every term, so a question containing a word the
    statute never uses ("long") matched nothing — and silence in legal search is
    indistinguishable from "no such law exists". Caught by the eval harness, not by the
    keyword-shaped unit tests above."""
    _seed(session)

    hits = search(
        session,
        "how long does a consumer have to withdraw from a distance contract",
        as_of=date(2019, 1, 1),
    )

    assert len(hits) == 1
    assert "14 days" in hits[0].text


def test_a_question_sharing_no_vocabulary_with_the_corpus_still_returns_nothing(
    session: Session,
) -> None:
    """ORing the terms must not turn retrieval into a machine that always finds something.
    Recall is not the goal; correct recall is."""
    _seed(session)

    hits = search(session, "interplanetary mining permits", as_of=date(2024, 1, 1))

    assert hits == []
