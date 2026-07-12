"""HTTP surface.

`as_of` is a required query parameter on /ask. It has no default — deliberately.

Defaulting it to `date.today()` would make the dangerous query the easy one: a user asking
about a 2019 dispute would silently be handed 2026 law, and nothing in the response would
tell them. Forcing the caller to state the date makes the temporal assumption explicit at
the only place it can be checked.
"""

from __future__ import annotations

from datetime import date

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.answers import answer
from app.db import get_session
from app.observability import instrument
from app.retrieval import search

app = FastAPI(
    title="lex-asof",
    description="Point-in-time legal retrieval: cite the law as it stood on the date that matters.",
)
instrument(app)


class CitationOut(BaseModel):
    """A citation, serialised."""

    celex: str
    act_title: str
    label: str
    text: str
    reference: str
    in_force_from: date
    in_force_to: date | None
    source_url: str


class AnswerOut(BaseModel):
    """A grounded answer, or a refusal."""

    question: str
    as_of: date
    answer: str
    grounded: bool
    citations: list[CitationOut]


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness."""
    return {"status": "ok"}


@app.get("/ask", response_model=AnswerOut)
async def ask(
    q: str = Query(..., description="The legal question."),
    as_of: date = Query(..., description="Answer as the law stood on this date. Required."),
    session: Session = Depends(get_session),
) -> AnswerOut:
    """Answer a question against the law in force on `as_of`."""
    citations = search(session, q, as_of=as_of)
    result = answer(q, citations, as_of=as_of)

    return AnswerOut(
        question=q,
        as_of=as_of,
        answer=result.text,
        grounded=result.is_grounded,
        citations=[
            CitationOut(
                celex=c.celex,
                act_title=c.act_title,
                label=c.label,
                text=c.text,
                reference=c.reference(),
                in_force_from=c.in_force_from,
                in_force_to=c.in_force_to,
                source_url=c.source_url,
            )
            for c in result.citations
        ],
    )
