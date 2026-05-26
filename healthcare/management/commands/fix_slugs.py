from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Fix slug column lengths'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            cursor.execute("ALTER TABLE healthcare_provider ALTER COLUMN slug TYPE varchar(200);")
            cursor.execute("ALTER TABLE healthcare_location ALTER COLUMN slug TYPE varchar(200);")
        self.stdout.write(self.style.SUCCESS("Slug columns altered to varchar(200)"))
