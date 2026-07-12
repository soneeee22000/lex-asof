"""API contract tests."""

from collections.abc import Iterator
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db import get_session
from app.main import app
from scripts.seed import seed


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    seed(session)
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_healthz(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}


def test_as_of_is_required_not_defaulted_to_today(client: TestClient) -> None:
    """The single most important line of the HTTP contract.

    Defaulting as_of to today would make the dangerous query the easy one: someone asking
    about a 2019 dispute would silently receive 2026 law. Omitting it must be an error.
    """
    response = client.get("/ask", params={"q": "withdraw distance contract"})

    assert response.status_code == 422


def test_the_same_question_returns_different_law_on_different_dates(client: TestClient) -> None:
    before = client.get(
        "/ask", params={"q": "withdraw distance contract", "as_of": "2019-01-01"}
    ).json()
    after = client.get(
        "/ask", params={"q": "withdraw distance contract", "as_of": "2024-01-01"}
    ).json()

    assert "14 days" in before["citations"][0]["text"]
    assert "30 days" in after["citations"][0]["text"]
    assert before["grounded"] is True
    assert after["grounded"] is True


def test_every_answer_carries_a_resolvable_citation(client: TestClient) -> None:
    body = client.get(
        "/ask", params={"q": "withdraw distance contract", "as_of": "2024-01-01"}
    ).json()

    citation = body["citations"][0]
    assert citation["label"] == "Article 9"
    assert citation["source_url"]
    assert citation["in_force_from"] == "2022-05-28"
    assert "Article 9" in citation["reference"]


def test_a_question_with_no_matching_law_is_refused(client: TestClient) -> None:
    body = client.get(
        "/ask", params={"q": "interplanetary mining permits", "as_of": "2024-01-01"}
    ).json()

    assert body["grounded"] is False
    assert body["citations"] == []
    assert "will not answer without a citation" in body["answer"]


def test_a_date_before_the_law_existed_is_refused(client: TestClient) -> None:
    body = client.get(
        "/ask", params={"q": "withdraw distance contract", "as_of": "2010-01-01"}
    ).json()

    assert body["grounded"] is False


def test_the_response_echoes_the_as_of_date_it_answered_for(client: TestClient) -> None:
    body = client.get(
        "/ask", params={"q": "withdraw distance contract", "as_of": "2019-01-01"}
    ).json()

    assert body["as_of"] == date(2019, 1, 1).isoformat()
