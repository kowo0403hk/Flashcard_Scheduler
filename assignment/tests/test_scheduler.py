from datetime import UTC, datetime, timedelta
from itertools import product

import pytest
from assignment.scheduler import (
    BASE_INTERVAL_WITH_RATING_1,
    CAP,
    RATING_0_INTERVAL_SECONDS,
    SECONDS_IN_ONE_DAY,
    schedule,
)

NOW = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("floor", [None, 2 * SECONDS_IN_ONE_DAY])
def test_wrong_answer_returns_within_one_minute(floor: int | None) -> None:
    _, new_floor, next_review = schedule(floor, 0, NOW)
    assert next_review - NOW <= timedelta(minutes=1)
    assert new_floor == floor


def test_first_review_ordering() -> None:
    rating_2_interval, _, _ = schedule(None, 2, NOW)
    rating_1_interval, _, _ = schedule(None, 1, NOW)
    assert rating_2_interval > rating_1_interval > RATING_0_INTERVAL_SECONDS


@pytest.mark.parametrize("ratings", list(product([0, 1, 2], repeat=6)))
def test_monotonic_interval_pattern(ratings: list[int]) -> None:
    floor = None
    prev_correct = None
    for rating in ratings:
        interval, floor, _ = schedule(floor, rating, NOW)
        if rating > 0:
            if prev_correct is not None:
                assert interval >= prev_correct
            prev_correct = interval


def test_first_review_wrong_then_correct_gets_first_interval() -> None:
    _, floor, _ = schedule(None, 0, NOW)
    assert floor is None
    interval, _, _ = schedule(floor, 1, NOW)
    assert interval == BASE_INTERVAL_WITH_RATING_1


def test_interval_is_capped() -> None:
    interval, _, _ = schedule(300 * SECONDS_IN_ONE_DAY, 2, NOW)
    assert interval == CAP
    interval, _, _ = schedule(CAP, 1, NOW)
    assert interval == CAP


@pytest.mark.parametrize("rating", [-1, 3])
def test_invalid_rating_raises_exception(rating: int) -> None:
    with pytest.raises(ValueError):
        schedule(None, rating, NOW)
