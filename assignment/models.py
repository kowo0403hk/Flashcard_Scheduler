from django.db.models import (
    Q,
    CheckConstraint,
    Model,
    CharField,
    BigIntegerField,
    DateTimeField,
    PositiveIntegerField,
    PositiveSmallIntegerField,
    ForeignKey,
    CASCADE,
    PROTECT,
    UniqueConstraint,
    Index,
)
from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """
    Custom User model that extends the default Django User model.
    This can be used to add additional fields or methods in the future.
    """

    pass


class Card(Model):
    front = CharField(max_length=100)
    back = CharField(max_length=100)

    class Meta:
        constraints = [
            UniqueConstraint(fields=["front"], name="card_front_uniq")
        ]


class CardState(Model):
    id: int
    user_id: int
    card_id: int
    user = ForeignKey(User, on_delete=CASCADE)
    card = ForeignKey(Card, on_delete=CASCADE)
    interval_seconds = BigIntegerField()
    last_correct_interval = BigIntegerField(null=True)
    reps = PositiveIntegerField(default=0)
    last_rating = PositiveSmallIntegerField()
    next_review = DateTimeField()
    updated_at = DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            UniqueConstraint(
                fields=["user", "card"], name="card_state_user_card_uniq"
            )
        ]
        indexes = [
            Index(fields=["user", "next_review"], name="card_state_due")
        ]


class Review(Model):
    id: int
    user_id: int
    card_id: int
    idempotency_key = CharField(max_length=64, unique=True)
    user = ForeignKey(User, on_delete=PROTECT)
    card = ForeignKey(Card, on_delete=PROTECT)
    rating = PositiveSmallIntegerField()
    reviewed_at = DateTimeField()
    interval_seconds = BigIntegerField()
    next_review = DateTimeField()

    class Meta:
        constraints = [
            CheckConstraint(
                condition=Q(rating__in=[0, 1, 2]), name="review_rating_valid"
            ),
        ]
