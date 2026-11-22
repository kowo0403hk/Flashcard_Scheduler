from django.contrib import admin
from django.urls import path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("reviews/"),
    path("users/<int:user_id>/due-cards")
]
