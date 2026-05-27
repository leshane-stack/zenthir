"""
Import physician pricing from CMS Medicare Physician data.
Streams line by line, matches by NPI — no disk storage needed.

Usage: python manage.py import_physician_pricing
       python manage.py import_physician_pricing --limit 50000
"""
import csv
import requests
from io import StringIO
from decimal import Decimal
from datetime import date
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from healthcare.models import Provider, Procedure, PricingRecord

URL = "https://data.cms.gov/sites/default/files/2026-05/b5ebab5a-f490-418a-9bce-4b9f31419356/PHY_R26_P05_V10_D24_Prov_Svc.csv"


class Command(BaseCommand):
    help = 'Import physician pricing from CMS Medicare data via NPI matching'

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=0)

    def handle(self, *args, **options):
        limit = options.get('limit', 0)

        self.stdout.write('Loading NPI lookup...')
        npi_set = set(
            Provider.objects.filter(npi_number__gt='')
            .values_list('npi_number', flat=True)
        )
        self.stdout.write(f'  {len(npi_set):,} providers with NPI in database')

        # Build NPI -> provider_id cache in chunks to save memory
        self.stdout.write('Building NPI -> provider ID cache...')
        self.npi_to_id = {}
        for p in Provider.objects.filter(npi_number__gt='').only('id', 'npi_number'):
            self.npi_to_id[p.npi_number] = p.id
        self.stdout.write(f'  Cached {len(self.npi_to_id):,} NPI mappings')

        self.procedure_cache = {}
        self.existing_pairs = set()

        # Pre-load existing provider-procedure pairs to skip duplicates
        self.stdout.write('Loading existing pricing pairs...')
        for pr in PricingRecord.objects.values_list('provider_id', 'procedure_id'):
            self.existing_pairs.add(pr)
        self.stdout.write(f'  {len(self.existing_pairs):,} existing pricing records')

        self.stdout.write(f'Streaming physician data...')
        try:
            resp = requests.get(URL, stream=True, timeout=60)
            resp.raise_for_status()
        except Exception as e:
            self.stderr.write(f'Error: {e}')
            return

        lines = resp.iter_lines(decode_unicode=True)
        header = next(lines)

        created = 0
        skipped_npi = 0
        skipped_exists = 0
        processed = 0
        batch = []
        buffer = ''

        for line in lines:
            buffer += line
            if buffer.count('"') % 2 != 0:
                buffer += '\n'
                continue

            processed += 1
            if processed % 100000 == 0:
                self.stdout.write(f'  {processed:,} rows... ({created:,} created, {skipped_npi:,} no NPI match)')

            try:
                reader = csv.DictReader(StringIO(header + '\n' + buffer))
                row = next(reader)
            except Exception:
                buffer = ''
                continue
            buffer = ''

            npi = row.get('Rndrng_NPI', '').strip()
            if not npi or npi not in self.npi_to_id:
                skipped_npi += 1
                continue

            provider_id = self.npi_to_id[npi]

            hcpcs = row.get('HCPCS_Cd', '').strip()
            desc = row.get('HCPCS_Desc', '').strip()
            charge_str = row.get('Avg_Sbmtd_Chrg', '').strip()
            allowed_str = row.get('Avg_Mdcr_Alowd_Amt', '').strip()

            if not desc or not charge_str:
                continue

            try:
                charge = Decimal(str(round(float(charge_str), 2)))
                allowed = Decimal(str(round(float(allowed_str), 2))) if allowed_str else None
            except (ValueError, TypeError):
                continue

            # Skip very low charges (likely admin codes)
            if charge < 10:
                continue

            procedure = self._get_procedure(hcpcs, desc)
            if not procedure:
                continue

            pair = (provider_id, procedure.id)
            if pair in self.existing_pairs:
                skipped_exists += 1
                continue

            self.existing_pairs.add(pair)
            batch.append(PricingRecord(
                provider_id=provider_id,
                procedure=procedure,
                cash_price=charge,
                insured_price=allowed,
                price_type='published',
                confidence='high',
                source_name='CMS Medicare Physician Data 2024',
                last_verified=date.today(),
            ))
            created += 1

            if len(batch) >= 1000:
                PricingRecord.objects.bulk_create(batch, ignore_conflicts=True)
                batch = []

            if limit and created >= limit:
                break

        if batch:
            PricingRecord.objects.bulk_create(batch, ignore_conflicts=True)

        self.stdout.write(self.style.SUCCESS(
            f'\nDone!\n'
            f'  Rows processed: {processed:,}\n'
            f'  Pricing created: {created:,}\n'
            f'  Skipped (no NPI match): {skipped_npi:,}\n'
            f'  Skipped (already exists): {skipped_exists:,}'
        ))

    def _get_procedure(self, hcpcs, description):
        slug = slugify(description[:80])[:200]
        if not slug:
            return None
        if slug in self.procedure_cache:
            return self.procedure_cache[slug]

        clean_name = description.strip()
        if len(clean_name) > 200:
            clean_name = clean_name[:197] + '...'

        proc, _ = Procedure.objects.get_or_create(
            slug=slug,
            defaults={
                'name': clean_name,
                'category': 'Physician Services',
                'description': f'HCPCS: {hcpcs}',
            }
        )
        self.procedure_cache[slug] = proc
        return proc
