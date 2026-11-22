from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from rest_framework.serializers import (
    Serializer,
    IntegerField,
    ChoiceField,
    CharField,
    DateTimeField,
)

from assignment.models import CardState, Review

JST = ZoneInfo("Asia/Tokyo")


def to_jst(value: datetime) -> str:
    """Stored time in UTC and return as ISO-8601 with JST offset."""
    return value.astimezone(JST).isoformat(timespec="seconds")


class ReviewRequestSerializer(Serializer[Any]):
    user_id = IntegerField(min_value=1)
    card_id = IntegerField(min_value=1)
    rating = ChoiceField(choices=[0, 1, 2])
    idempotency_key = CharField(max_length=64)


class DueCardsQuerySerializer(Serializer[Any]):
    until = DateTimeField(required=False, default_timezone=JST)
    limit = IntegerField(min_value=1, max_value=200, default=50)


def review_response(review: Review) -> dict[str, int | str]:
    return {
        "review_id": review.id,
        "user_id": review.user_id,
        "card_id": review.card_id,
        "rating": review.rating,
        "interval_seconds": review.interval_seconds,
        "next_review": to_jst(review.next_review),
    }


def due_card_response(state: CardState) -> dict[str, int | str]:
    return {
        "card_id": state.card_id,
        "front": state.card.front,
        "back": state.card.back,
        "interval_seconds": state.interval_seconds,
        "next_review": to_jst(state.next_review),
    }
