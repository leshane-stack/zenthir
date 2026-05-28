"""
Take a snapshot of all current pricing into PriceSnapshot.
Run weekly/daily to build pricing history over time.

Usage: python manage.py snapshot_prices
"""
from django.core.management.base import BaseCommand
from healthcare.models import PricingRecord, PriceSnapshot


class Command(BaseCommand):
    help = 'Snapshot all current pricing records into price history'

    def handle(self, *args, **options):
        records = PricingRecord.objects.select_related('provider', 'procedure').all()
        total = records.count()
        self.stdout.write(f'Snapshotting {total:,} pricing records...')

        batch = []
        created = 0
        for record in records.iterator(chunk_size=2000):
            batch.append(PriceSnapshot(
                provider_id=record.provider_id,
                procedure_id=record.procedure_id,
                cash_price=record.cash_price,
                insured_price=record.insured_price,
                price_type=record.price_type,
                source_name=record.source_name,
            ))
            if len(batch) >= 2000:
                PriceSnapshot.objects.bulk_create(batch)
                created += len(batch)
                batch = []
                self.stdout.write(f'  {created:,} snapshots...')

        if batch:
            PriceSnapshot.objects.bulk_create(batch)
            created += len(batch)

        self.stdout.write(self.style.SUCCESS(f'Done: {created:,} price snapshots created'))
