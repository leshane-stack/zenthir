"""
Detect and record provider metadata changes.
Run after each data import to track ownership, status, and rating changes.

Usage: python manage.py snapshot_providers
"""
from django.core.management.base import BaseCommand
from healthcare.models import Provider, ProviderSnapshot


TRACKED_FIELDS = [
    'ownership_type',
    'parent_organization',
    'cms_star_rating',
    'transparency_compliant',
    'license_status',
    'accreditation',
    'address',
    'name',
]


class Command(BaseCommand):
    help = 'Detect and snapshot provider metadata changes'

    def handle(self, *args, **options):
        providers = Provider.objects.all()
        total = providers.count()
        self.stdout.write(f'Checking {total:,} providers for metadata changes...')

        changes = 0
        checked = 0

        for provider in providers.iterator(chunk_size=2000):
            checked += 1
            if checked % 100000 == 0:
                self.stdout.write(f'  Checked {checked:,}... ({changes} changes found)')

            last_snapshot = ProviderSnapshot.objects.filter(
                provider=provider
            ).order_by('-changed_at').first()

            if not last_snapshot:
                continue

            for field in TRACKED_FIELDS:
                current_value = str(getattr(provider, field, '') or '')
                if last_snapshot.field_name == field and last_snapshot.new_value != current_value:
                    ProviderSnapshot.objects.create(
                        provider=provider,
                        field_name=field,
                        old_value=last_snapshot.new_value,
                        new_value=current_value,
                        source='automated_detection',
                    )
                    changes += 1

        self.stdout.write(self.style.SUCCESS(f'Done: {changes} metadata changes recorded'))
