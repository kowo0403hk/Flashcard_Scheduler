from rest_framework.response import Response


from rest_framework.response import Response


from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import NotFound
from rest_framework.response import Response
from rest_framework.request import Request
from rest_framework.views import APIView

from assignment.models import Card, CardState, User
from assignment.serializers import (
    DueCardsQuerySerializer,
    ReviewRequestSerializer,
    due_card_response,
    review_response,
    to_jst,
)
from assignment.services import IdempotencyConflict, record_review


class ReviewCreateView(APIView):
    # no auth
    authentication_classes = []

    def post(self, request: Request) -> Response:
        serializer = ReviewRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if not User.objects.filter(pk=data["user_id"]).exists():
            raise NotFound("User not found.")
        if not Card.objects.filter(pk=data["card_id"]).exists():
            raise NotFound("Card not found.")

        try:
            review, created = record_review(
                key=data["idempotency_key"],
                user_id=data["user_id"],
                card_id=data["card_id"],
                rating=data["rating"],
            )
        except IdempotencyConflict:
            return Response(
                {"detail": "idempotency_key was used for another request."},
                status=status.HTTP_409_CONFLICT,
            )
        code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
        return Response(review_response(review), status=code)


class DueCardsView(APIView):
    # no auth
    authentication_classes = []

    def get(self, request: Request, user_id: int) -> Response:
        query = DueCardsQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        if not User.objects.filter(pk=user_id).exists():
            raise NotFound("User not found.")

        until = query.validated_data.get("until") or timezone.now()
        states = (
            CardState.objects.filter(user_id=user_id, next_review__lte=until)
            .select_related("card")
            .order_by("next_review", "card_id")[
                : query.validated_data["limit"]
            ]
        )
        return Response(
            {
                "user_id": user_id,
                "until": to_jst(until),
                "cards": [due_card_response(s) for s in states],
            }
        )
