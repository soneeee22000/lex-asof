"""The grounding rule: no citation, no answer.

These tests exist because the failure mode they prevent is the one that gets legal-tech
products sued — a fluent, confident, unsourced answer.
"""

from datetime import date

from app.answers import REFUSAL, DeterministicProvider, GroundedAnswer, answer
from app.retrieval import Citation


def _citation() -> Citation:
    return Citation(
        celex="FIXTURE-DSD-001",
        act_title="Model Distance Selling Directive (synthetic fixture)",
        label="Article 9",
        text="The consumer shall have a period of 14 days to withdraw.",
        in_force_from=date(2014, 6, 13),
        in_force_to=date(2022, 5, 28),
        source_url="https://example.invalid/fixtures/dsd-001",
    )


class _InventingProvider:
    """A stand-in for a model that will happily answer with nothing to go on."""

    def synthesise(self, question: str, citations: list[Citation], as_of: date) -> str:
        return "You have 30 days, I'm fairly sure."


def test_empty_retrieval_produces_a_refusal_not_an_answer() -> None:
    result = answer("how long to withdraw?", citations=[], as_of=date(2019, 1, 1))

    assert result.text == REFUSAL.format(as_of="2019-01-01")
    assert result.is_grounded is False


def test_the_provider_is_never_consulted_when_retrieval_is_empty() -> None:
    """The refusal is decided before the model is reached. A model given an empty context
    cannot be trusted to refuse on its own — so it is never asked."""
    result = answer(
        "how long to withdraw?",
        citations=[],
        as_of=date(2019, 1, 1),
        provider=_InventingProvider(),
    )

    assert "30 days" not in result.text
    assert result.is_grounded is False


def test_a_grounded_answer_carries_its_citations() -> None:
    result = answer("how long to withdraw?", [_citation()], as_of=date(2019, 1, 1))

    assert result.is_grounded is True
    assert len(result.citations) == 1
    assert result.citations[0].label == "Article 9"


def test_the_deterministic_provider_quotes_rather_than_paraphrases() -> None:
    """A paraphrase of a provision is a new legal claim. This provider makes none."""
    text = DeterministicProvider().synthesise(
        "how long to withdraw?", [_citation()], as_of=date(2019, 1, 1)
    )

    assert "14 days" in text  # the actual statutory text, verbatim
    assert "Article 9" in text
    assert "example.invalid" in text  # provenance is in the output, not just the metadata


def test_the_answer_states_the_date_it_is_answering_as_of() -> None:
    """An answer that does not say which date it is good for invites the reader to assume
    'today' — which is exactly the mistake this system exists to prevent."""
    result = answer("how long to withdraw?", [_citation()], as_of=date(2019, 1, 1))

    assert "2019-01-01" in result.text


def test_grounded_answer_with_no_citations_is_not_grounded() -> None:
    result = GroundedAnswer(text="anything", citations=[], as_of=date(2019, 1, 1))

    assert result.is_grounded is False
