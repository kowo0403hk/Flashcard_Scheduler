from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from typing import Any

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from assignment.models import Card, CardState, Review, User
from assignment.scheduler import schedule
from assignment.services import record_review

pytestmark: pytest.MarkDecorator = pytest.mark.django_db


@pytest.fixture
def client() -> APIClient:
    return APIClient()


@pytest.fixture
def user() -> User:
    return User.objects.create(username="alice")


@pytest.fixture
def card() -> Card:
    return Card.objects.create(front="犬", back="dog")


def body(user, card, rating=2, key="k1") -> dict[str, Any]:
    return {
        "user_id": user.id,
        "card_id": card.id,
        "rating": rating,
        "idempotency_key": key,
    }


def test_first_post_201_retry_200_identical(client, user, card) -> None:
    first = client.post("/reviews", body(user, card), format="json")
    second = client.post("/reviews", body(user, card), format="json")
    assert first.status_code == 201
    assert second.status_code == 200
    assert first.content == second.content
    assert Review.objects.count() == 1


def test_same_key_different_body_409(client, user, card) -> None:
    client.post("/reviews", body(user, card, rating=2), format="json")
    r = client.post("/reviews", body(user, card, rating=1), format="json")
    assert r.status_code == 409
    assert Review.objects.count() == 1


@pytest.mark.parametrize("rating", [-1, 3, "x"])
def test_invalid_rating_400(client, user, card, rating) -> None:
    r = client.post("/reviews", body(user, card, rating=rating), format="json")
    assert r.status_code == 400


def test_missing_key_400(client, user, card) -> None:
    data = body(user, card)
    del data["idempotency_key"]
    assert client.post("/reviews", data, format="json").status_code == 400


def test_unknown_user_or_card_404(client, user, card) -> None:
    data = body(user, card)
    data["card_id"] = card.id + 999
    assert client.post("/reviews", data, format="json").status_code == 404
    data = body(user, card)
    data["user_id"] = user.id + 999
    assert client.post("/reviews", data, format="json").status_code == 404


def test_response_uses_jst_offset(client, user, card) -> None:
    r = client.post("/reviews", body(user, card), format="json")
    assert r.json()["next_review"].endswith("+09:00")


def test_due_cards_filters_by_until(client, user, card) -> None:
    client.post("/reviews", body(user, card, rating=0), format="json")
    url = f"/users/{user.id}/due-cards"

    # Due in 60 s, so not due yet.
    assert client.get(url).json()["cards"] == []

    later = (timezone.now() + timedelta(minutes=2)).isoformat()
    cards = client.get(url, {"until": later}).json()["cards"]
    assert [c["card_id"] for c in cards] == [card.id]


def test_due_cards_excludes_other_users(client, user, card) -> None:
    other = User.objects.create(username="bob")
    client.post("/reviews", body(other, card, rating=0), format="json")
    later = (timezone.now() + timedelta(minutes=2)).isoformat()
    r = client.get(f"/users/{user.id}/due-cards", {"until": later})
    assert r.json()["cards"] == []


def test_due_cards_bad_until_400(client, user) -> None:
    r = client.get(f"/users/{user.id}/due-cards", {"until": "not-a-date"})
    assert r.status_code == 400


def test_due_cards_unknown_user_404(client) -> None:
    assert client.get("/users/999999/due-cards").status_code == 404


def run_in_threads(fn, args_list) -> list[Any]:
    def wrapped(args):
        try:
            return fn(*args)
        finally:
            connection.close()  # each thread has its own connection

    with ThreadPoolExecutor(max_workers=len(args_list)) as pool:
        return list(pool.map(wrapped, args_list))


@pytest.mark.django_db(transaction=True)
def test_concurrent_same_key_processed_once(user, card) -> None:
    def call(_):
        return record_review(
            key="same", user_id=user.id, card_id=card.id, rating=2
        )

    results = run_in_threads(call, [(i,) for i in range(10)])
    assert Review.objects.count() == 1
    assert sum(created for _, created in results) == 1
    assert len({review.id for review, _ in results}) == 1


@pytest.mark.django_db(transaction=True)
def test_concurrent_different_keys_serialised(user, card) -> None:
    def call(i):
        return record_review(
            key=f"k{i}", user_id=user.id, card_id=card.id, rating=1
        )

    run_in_threads(call, [(i,) for i in range(10)])

    # Same result as 10 sequential reviews: no lost updates.
    expected, floor = [], None
    for _ in range(10):
        interval, floor, _ = schedule(floor, 1, timezone.now())
        expected.append(interval)
    got = list(
        Review.objects.order_by("id").values_list(
            "interval_seconds", flat=True
        )
    )
    assert got == expected
    state = CardState.objects.get(user=user, card=card)
    assert state.reps == 10
    assert state.interval_seconds == expected[-1]
