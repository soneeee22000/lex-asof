"""Grounded answer synthesis.

The rule this module enforces: **no citation, no answer.** In a legal setting an unsourced
answer is worse than no answer, because it is indistinguishable from a sourced one to the
person who most needs the difference. If retrieval returns nothing in force on the given
date, the correct output is an explicit refusal — never a fluent guess.

The default provider is deterministic and requires no API key, so the whole system runs and
is testable offline. A model provider can be swapped in without touching the grounding rule,
because the grounding rule is not the model's job.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Protocol

from app.retrieval import Citation

REFUSAL = (
    "No provision in force on {as_of} matches this question. "
    "I will not answer without a citation."
)


@dataclass(frozen=True)
class GroundedAnswer:
    """An answer that can always be traced back to the text it came from."""

    text: str
    citations: list[Citation]
    as_of: date

    @property
    def is_grounded(self) -> bool:
        """An answer with no citations is a refusal, not an answer."""
        return len(self.citations) > 0


class AnswerProvider(Protocol):
    """Synthesises prose from retrieved provisions. It never decides *whether* to answer."""

    def synthesise(self, question: str, citations: list[Citation], as_of: date) -> str: ...


class DeterministicProvider:
    """Zero-key, zero-network provider. Quotes the law rather than paraphrasing it.

    Deliberately extractive. A paraphrase of a legal provision is a new legal claim, and
    this provider has no standing to make one — so it returns the text and the reference,
    which is what a lawyer actually wants anyway.
    """

    def synthesise(self, question: str, citations: list[Citation], as_of: date) -> str:
        lines = [f"As of {as_of.isoformat()}, the following provisions were in force:", ""]
        for citation in citations:
            lines.append(f"— {citation.reference()}")
            lines.append(f'  "{citation.text}"')
            lines.append(f"  Source: {citation.source_url}")
            lines.append("")
        return "\n".join(lines).strip()


def answer(
    question: str,
    citations: list[Citation],
    as_of: date,
    provider: AnswerProvider | None = None,
) -> GroundedAnswer:
    """Produce a grounded answer, or refuse.

    The refusal path is checked *before* the provider is consulted, so no model is ever
    given the chance to fill an empty retrieval with plausible invention.
    """
    if not citations:
        return GroundedAnswer(
            text=REFUSAL.format(as_of=as_of.isoformat()), citations=[], as_of=as_of
        )

    provider = provider or DeterministicProvider()
    return GroundedAnswer(
        text=provider.synthesise(question, citations, as_of),
        citations=citations,
        as_of=as_of,
    )
