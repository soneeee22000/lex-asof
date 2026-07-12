# lex-asof

**Point-in-time legal retrieval: cite the law as it stood on the date that matters.**

```
GET /ask?q=how long to withdraw from a distance contract&as_of=2019-01-01
  → "14 days"   — Article 9, version 2014-06-13–2022-05-28

GET /ask?q=how long to withdraw from a distance contract&as_of=2024-01-01
  → "30 days"   — Article 9, version 2022-05-28–in force
```

Same question. Different law. **Both answers correct.**

## The problem

Almost every legal RAG system stores "the current text of Article 9" and overwrites it when
the law is amended. That system will confidently tell a user the answer is 30 days — even
when the dispute they are asking about arose in 2019, when it was 14.

It is not a retrieval failure. Retrieval worked perfectly. The **data model** threw away the
only thing a legal answer actually needs: _when was this true?_

## The design

**A provision is not a row. It is a sequence of versions, each in force over a half-open
interval `[from, to)`.**

- `Provision` — the stable, citable identity ("Article 9"). Holds **no text at all**.
- `ProvisionVersion` — the text, plus `in_force_from` / `in_force_to`, plus its source URL.

Every retrieval is filtered by an as-of date **in SQL**, before ranking. Filtering after
ranking would silently shrink the result set: superseded versions would win top-k slots and
then be discarded, so a query matching five in-force provisions might return two.

Three consequences worth defending in review:

**1. `as_of` is a required parameter with no default.** Defaulting it to `today()` would make
the dangerous query the easy one — a user asking about a 2019 dispute would silently receive
2026 law, and nothing in the response would tell them. Forcing the caller to state the date
puts the temporal assumption where it can be checked.

**2. Ingestion is idempotent and never destructive.** Re-running the pipeline over an
unchanged source is a no-op (content-hashed, whitespace-normalised — publishers reflow
paragraphs without changing the law, and that must not register as an amendment). Re-running
it over an amended source _closes_ the outgoing version and opens a new one. A backdated
amendment is **rejected**, not absorbed: accepting it would produce overlapping intervals —
two contradictory texts valid on the same date — and it is better to fail loudly than to
serve one of them.

**3. No citation, no answer.** If nothing was in force on the given date, the system returns
an explicit refusal. The refusal is decided _before_ any model is consulted, because a model
handed an empty context cannot be trusted to refuse on its own. In law, an unsourced answer
is worse than no answer — it is indistinguishable from a sourced one to the person who most
needs the difference.

## The evaluation gate

Two metrics, scored separately, both blocking CI:

| Metric                  | Gate     | Why                                                                                                             |
| ----------------------- | -------- | --------------------------------------------------------------------------------------------------------------- |
| **Citation accuracy**   | ≥ 80%    | Did we cite the right provision _version_? Right article, wrong version is still a wrong answer.                |
| **Refusal correctness** | **100%** | When no law was in force, did we refuse? Gated at 100% because inventing law is never an acceptable regression. |

They are **not averaged into one number** — averaging would let a good accuracy score hide a
hallucination. Both are deterministic: no LLM grades another LLM here, because grading a
non-deterministic system with a non-deterministic system produces a number nobody should act
on.

### The gate earned its keep on day one

The unit tests passed. The eval gate failed at **0% citation accuracy**, and it was right.

PostgreSQL's `plainto_tsquery` **ANDs** every term. The unit tests queried
`"withdraw distance contract"` — every word appears in the statute, so they passed. The golden
set asks the question a person would actually type: _"how long does a consumer have to
withdraw from a distance contract"_. The word **"long" never appears in the provision**, the
AND failed, and retrieval returned **nothing** — reporting, with total confidence, that no
such law existed.

Silence is the worst failure mode in legal search: it is indistinguishable from _"there is no
such law"_. Terms are now ORed with `ts_rank` deciding order, and there is a regression test
for it. A keyword-shaped unit test would never have caught this.

## Run it

Runs fully offline. **No API key, no model, no network.**

```bash
docker compose up -d              # PostgreSQL
pip install -e ".[dev]"
python -m scripts.seed            # load the fixture corpus
uvicorn app.main:app --reload

pytest -q                         # 27 tests, 97% coverage
python -m eval.golden             # the release gate
```

## ⚠️ The fixture corpus is synthetic, and says so

`scripts/seed.py` loads **invented** legislation. The act names, CELEX identifiers, article
text and amendment dates are all fictional, and they are named (`FIXTURE-DSD-001`,
_"Model Distance Selling Directive (synthetic fixture)"_) so they cannot be mistaken for real
instruments.

This is deliberate. The repository demonstrates a _mechanism_, and the mechanism has to be
demonstrable offline. Shipping plausible-looking but subtly-wrong real legislation would be
worse than shipping obvious fiction — a reader might believe it. **Nothing here blends the
two.**

For real data, `scripts/fetch_eurlex.py` ingests actual consolidated acts from EUR-Lex (no API
key; consolidated EU acts already carry the date-of-application metadata this model needs):

```bash
python -m scripts.fetch_eurlex 32011L0083 2014-06-13
```

The pipeline is identical. Only the source changes.

## Stack

Python 3.12 · FastAPI · **SQLAlchemy 2.0** (typed, `Mapped[...]`) · PostgreSQL 17 (full-text
search, `ts_rank`) · Sentry · Datadog (`ddtrace`) · Codecov · GitHub Actions · Docker

Sentry and Datadog are opt-in via environment variables and are **no-ops when unset** —
observability that forces a vendor account on every contributor is observability nobody runs.
Sentry is configured with `send_default_pii=False`: legal questions are sensitive and never
leave the process.
