from django.contrib import admin
from django.urls import path

from assignment.views import DueCardsView, ReviewCreateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("reviews", ReviewCreateView.as_view()),
    path("users/<int:user_id>/due-cards", DueCardsView.as_view()),
]
