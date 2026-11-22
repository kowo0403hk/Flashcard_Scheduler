import json
import os

from django.core.management.base import BaseCommand
from assignment.models import Card, User


class Command(BaseCommand):
    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            default="MOCK_DATA.json",
            help="JSON file name to load data from",
        )

    def handle(self, *args, **options):
        file_name = options.get("file")
        json_file_path = os.path.join(os.path.dirname(__file__), file_name)

        with open(json_file_path, encoding="utf-8") as json_file:
            data = json.load(json_file)

        for row in data:
            Card.objects.get_or_create(
                front=row["front"], defaults={"back": row["back"]}
            )

        if not User.objects.filter(username="testuser").exists():
            User.objects.create_superuser(
                "testuser",
                email="testuser@example.com",
                password="testpassword",
            )

        for i in range(1, 6):
            user, created = User.objects.get_or_create(
                username=f"testuser{i}",
                defaults={"email": f"testuser{i}@example.com"},
            )
            if created:
                user.set_password("testpassword")
                user.save()

        self.stdout.write(
            self.style.SUCCESS(
                f"Mock data loaded successfully from {file_name} with {User.objects.count()} users and {Card.objects.count()} cards"
            )
        )
