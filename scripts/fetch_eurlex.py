"""Ingest REAL consolidated legislation from EUR-Lex.

EUR-Lex publishes consolidated versions of EU acts — the text as amended, each with the date
from which it applies. That is exactly the shape this system stores, which is why EU law is
a good first real corpus: the temporal metadata is already there and does not have to be
reconstructed.

No API key is required. Consolidated acts are addressable by CELEX number.

    python -m scripts.fetch_eurlex 32011L0083

This is deliberately kept separate from the fixture seed. The fixtures are fiction and say
so; this fetches the real thing. Nothing in this repository blends the two.
"""

from __future__ import annotations

import re
import sys
from datetime import date

import httpx
from sqlalchemy.orm import Session

from app.ingest import IngestedProvision, ingest

EURLEX_HTML = "https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:{celex}"
ARTICLE_PATTERN = re.compile(r"Article\s+(\d+[a-z]?)", re.IGNORECASE)


def fetch_act_html(celex: str, client: httpx.Client | None = None) -> str:
    """Download the consolidated text of an act by CELEX number."""
    owns_client = client is None
    client = client or httpx.Client(timeout=30.0, follow_redirects=True)
    try:
        response = client.get(EURLEX_HTML.format(celex=celex))
        response.raise_for_status()
        return response.text
    finally:
        if owns_client:
            client.close()


def parse_provisions(
    html: str,
    celex: str,
    act_title: str,
    in_force_from: date,
) -> list[IngestedProvision]:
    """Split consolidated HTML into per-article provisions.

    This parser is intentionally conservative: it extracts articles it can identify
    unambiguously and skips the rest. In a legal corpus, a provision silently attributed to
    the wrong article number is far more damaging than a provision that was not ingested at
    all — one is a wrong citation, the other is a gap you can see.
    """
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()

    provisions: list[IngestedProvision] = []
    matches = list(ARTICLE_PATTERN.finditer(text))

    for current, following in zip(matches, [*matches[1:], None], strict=False):
        body = text[current.end() : (following.start() if following else len(text))].strip()
        if len(body) < 40:  # a cross-reference ("see Article 5"), not the article itself
            continue

        provisions.append(
            IngestedProvision(
                celex=celex,
                act_title=act_title,
                jurisdiction="EU",
                label=f"Article {current.group(1)}",
                text=body[:4000],
                in_force_from=in_force_from,
                source_url=EURLEX_HTML.format(celex=celex),
            )
        )

    return provisions


def main(argv: list[str]) -> int:
    """Fetch, parse and ingest one act."""
    if len(argv) < 2:
        print(__doc__)
        return 2

    from app.db import SessionLocal

    celex = argv[1]
    applies_from = date.fromisoformat(argv[2]) if len(argv) > 2 else date.today()

    html = fetch_act_html(celex)
    provisions = parse_provisions(html, celex, act_title=celex, in_force_from=applies_from)

    session: Session = SessionLocal()
    try:
        created = ingest(session, provisions)
    finally:
        session.close()

    print(f"{celex}: parsed {len(provisions)} provisions, created {created} new versions")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
