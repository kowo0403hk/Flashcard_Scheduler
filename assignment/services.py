from typing import Literal


from django.db import IntegrityError, transaction
from django.utils import timezone

from assignment.models import CardState, Review
from assignment.scheduler import schedule


class IdempotencyConflict(Exception):
    """The key was already used with a different request body."""


def _find_replay(
    key: str, user_id: int, card_id: int, rating: int
) -> Review | None:
    review = Review.objects.filter(idempotency_key=key).first()
    if review is None:
        return None
    if (review.user_id, review.card_id, review.rating) != (
        user_id,
        card_id,
        rating,
    ):
        raise IdempotencyConflict
    return review


def _record_new(key: str, user_id: int, card_id: int, rating: int) -> Review:
    with transaction.atomic():
        # Row lock: reviews of same (user, card) run one at a time
        state = (
            CardState.objects.select_for_update()
            .filter(
                user_id=user_id,
                card_id=card_id,
            )
            .first()
        )
        now = timezone.now()
        floor = state.last_correct_interval if state else None
        interval, new_floor, next_review = schedule(floor, rating, now)

        if state is None:
            state = CardState(user_id=user_id, card_id=card_id)
        state.interval_seconds = interval
        state.last_correct_interval = new_floor
        state.last_rating = rating
        state.reps += 1
        state.next_review = next_review
        state.save()

        return Review.objects.create(
            idempotency_key=key,
            user_id=user_id,
            card_id=card_id,
            rating=rating,
            reviewed_at=now,
            interval_seconds=interval,
            next_review=next_review,
        )


def record_review(
    *, key: str, user_id: int, card_id: int, rating: int
) -> tuple[Review, bool]:
    existing = _find_replay(key, user_id, card_id, rating)
    if existing is not None:
        return existing, False
    try:
        return _record_new(key, user_id, card_id, rating), True
    except IntegrityError:
        # It is possible a concurrent request committed this key first,
        # or a concurrent first review created the CardState row
        pass
    existing = _find_replay(key, user_id, card_id, rating)
    if existing is not None:
        return existing, False
    return _record_new(key, user_id, card_id, rating), True
