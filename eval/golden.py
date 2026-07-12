"""Golden set and evaluation gate.

Two metrics, and the second is the one that matters.

**Citation accuracy** — did we cite the right provision *version*? Citing the correct article
but the wrong version is still a wrong answer: it tells the user the law is 30 days when, on
the date they care about, it was 14.

**Refusal correctness** — when nothing was in force, did we refuse? A system that scores well
on accuracy but invents an answer when the law is silent is more dangerous than one that
scores worse and knows when to stop. This is scored separately and gated separately, because
averaging it into a single number would let a good accuracy score hide a hallucination.

Both are deterministic. No LLM grades another LLM here — grading a non-deterministic system
with a non-deterministic system produces a number nobody should act on.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date

from sqlalchemy.orm import Session

from app.answers import answer
from app.retrieval import search

CITATION_ACCURACY_THRESHOLD = 0.80
REFUSAL_CORRECTNESS_THRESHOLD = 1.00  # must be perfect: never invent law


@dataclass(frozen=True)
class GoldenCase:
    """One question, with the provision version that should be cited."""

    question: str
    as_of: date
    expected_label: str | None  # None => the system must refuse
    expected_in_force_from: date | None = None


GOLDEN_SET: list[GoldenCase] = [
    GoldenCase(
        question="how long does a consumer have to withdraw from a distance contract",
        as_of=date(2019, 1, 1),
        expected_label="Article 9",
        expected_in_force_from=date(2014, 6, 13),
    ),
    GoldenCase(
        question="how long does a consumer have to withdraw from a distance contract",
        as_of=date(2024, 1, 1),
        expected_label="Article 9",
        expected_in_force_from=date(2022, 5, 28),
    ),
    GoldenCase(
        question="how long does a consumer have to withdraw from a distance contract",
        as_of=date(2022, 5, 28),  # boundary: the day the amendment enters into force
        expected_label="Article 9",
        expected_in_force_from=date(2022, 5, 28),
    ),
    GoldenCase(
        question="how long does a consumer have to withdraw from a distance contract",
        as_of=date(2010, 1, 1),  # before the directive applied
        expected_label=None,  # must refuse
    ),
    GoldenCase(
        question="what are the rules on interplanetary mining permits",
        as_of=date(2024, 1, 1),
        expected_label=None,  # no such law: must refuse, not improvise
    ),
]


@dataclass
class EvalReport:
    """Scores, and whether the build may ship."""

    citation_accuracy: float
    refusal_correctness: float
    failures: list[str]

    @property
    def passed(self) -> bool:
        return (
            self.citation_accuracy >= CITATION_ACCURACY_THRESHOLD
            and self.refusal_correctness >= REFUSAL_CORRECTNESS_THRESHOLD
        )


def evaluate(session: Session) -> EvalReport:
    """Run the golden set and score it."""
    cited_cases = [c for c in GOLDEN_SET if c.expected_label is not None]
    refusal_cases = [c for c in GOLDEN_SET if c.expected_label is None]

    citation_hits = 0
    refusal_hits = 0
    failures: list[str] = []

    for case in cited_cases:
        hits = search(session, case.question, as_of=case.as_of)
        result = answer(case.question, hits, as_of=case.as_of)

        top = result.citations[0] if result.citations else None
        if (
            top is not None
            and top.label == case.expected_label
            and top.in_force_from == case.expected_in_force_from
        ):
            citation_hits += 1
        else:
            got = f"{top.label} @ {top.in_force_from}" if top else "nothing"
            failures.append(
                f"[citation] as_of={case.as_of}: expected "
                f"{case.expected_label} @ {case.expected_in_force_from}, got {got}"
            )

    for case in refusal_cases:
        hits = search(session, case.question, as_of=case.as_of)
        result = answer(case.question, hits, as_of=case.as_of)

        if not result.is_grounded:
            refusal_hits += 1
        else:
            failures.append(
                f"[refusal] as_of={case.as_of}: expected a refusal, but the system answered "
                f'"{case.question}" citing {result.citations[0].label}'
            )

    return EvalReport(
        citation_accuracy=citation_hits / len(cited_cases) if cited_cases else 1.0,
        refusal_correctness=refusal_hits / len(refusal_cases) if refusal_cases else 1.0,
        failures=failures,
    )


def main() -> int:
    """Run the gate. Non-zero exit fails CI."""
    from app.db import SessionLocal
    from scripts.seed import seed

    session = SessionLocal()
    try:
        seed(session)
        report = evaluate(session)
    finally:
        session.close()

    print(
        f"citation accuracy  : {report.citation_accuracy:.0%} "
        f"(gate {CITATION_ACCURACY_THRESHOLD:.0%})"
    )
    print(
        f"refusal correctness: {report.refusal_correctness:.0%} "
        f"(gate {REFUSAL_CORRECTNESS_THRESHOLD:.0%})"
    )
    for failure in report.failures:
        print(f"  FAIL {failure}")

    if not report.passed:
        print("\nEVAL GATE FAILED - not shippable")
        return 1

    print("\nEVAL GATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
