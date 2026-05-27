import csv
import requests
import re
from io import StringIO
from decimal import Decimal
from datetime import date
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from healthcare.models import Provider, Procedure, PricingRecord

INPATIENT_URL = "https://data.cms.gov/sites/default/files/2026-04/828defb5-c9e6-4442-8c1b-f27bc0799daf/MUP_INP_RY26_P03_V10_DY24_PrvSvc.CSV"
OUTPATIENT_URL = "https://data.cms.gov/sites/default/files/2025-08/bceaa5e1-e58c-4109-9f05-832fc5e6bbc8/MUP_OUT_RY25_P04_V10_DY23_Prov_Svc.csv"


class Command(BaseCommand):
    help = 'Import real hospital pricing from CMS Medicare data'

    def add_arguments(self, parser):
        parser.add_argument('--inpatient-only', action='store_true')
        parser.add_argument('--outpatient-only', action='store_true')
        parser.add_argument('--limit', type=int, default=0)

    def handle(self, *args, **options):
        self.stdout.write('Building hospital lookup...')
        self.hospital_cache = {}
        self.hospital_slug_cache = {}
        for p in Provider.objects.filter(provider_type__slug='hospital').select_related('location'):
            state = p.location.state if p.location else ''
            key = (p.name.upper().strip(), state.upper().strip())
            self.hospital_cache[key] = p
            self.hospital_slug_cache[p.slug] = p
            normalized = self._normalize(p.name)
            norm_key = (normalized, state.upper().strip())
            if norm_key not in self.hospital_cache:
                self.hospital_cache[norm_key] = p
        self.stdout.write(f'  {len(self.hospital_cache)} hospital keys cached')

        self.procedure_cache = {}

        if not options.get('outpatient_only'):
            self.stdout.write('\n=== INPATIENT ===')
            self._import(INPATIENT_URL, 'inpatient', options.get('limit', 0))

        if not options.get('inpatient_only'):
            self.stdout.write('\n=== OUTPATIENT ===')
            self._import(OUTPATIENT_URL, 'outpatient', options.get('limit', 0))

    def _normalize(self, name):
        n = name.upper().strip()
        for s in [', INC.', ', INC', ' INC.', ' INC', ' LLC', ' LP', ' LTD',
                  ' CORP.', ' CORP', ' CORPORATION', ' AUTHORITY', ' DISTRICT']:
            n = n.replace(s, '')
        n = re.sub(r'[^A-Z0-9 ]', '', n)
        n = re.sub(r'\s+', ' ', n).strip()
        return n

    def _find_hospital(self, name, state):
        state = state.upper().strip()
        key = (name.upper().strip(), state)
        if key in self.hospital_cache:
            return self.hospital_cache[key]

        norm_key = (self._normalize(name), state)
        if norm_key in self.hospital_cache:
            return self.hospital_cache[norm_key]

        slug = slugify(name)[:200]
        if slug in self.hospital_slug_cache:
            p = self.hospital_slug_cache[slug]
            if p.location and p.location.state.upper() == state:
                return p

        match = Provider.objects.filter(
            provider_type__slug='hospital',
            name__iexact=name,
            location__state=state,
        ).first()
        if match:
            self.hospital_cache[key] = match
            return match

        return None

    def _get_procedure(self, code, description, proc_type):
        slug = slugify(description[:80])[:200]
        if not slug:
            return None
        if slug in self.procedure_cache:
            return self.procedure_cache[slug]

        clean_name = description.strip().title()
        if len(clean_name) > 200:
            clean_name = clean_name[:197] + '...'

        category = 'Inpatient' if proc_type == 'inpatient' else 'Outpatient'
        proc, _ = Procedure.objects.get_or_create(
            slug=slug,
            defaults={
                'name': clean_name,
                'category': category,
                'description': f'CMS {proc_type} code: {code}',
            }
        )
        self.procedure_cache[slug] = proc
        return proc

    def _import(self, url, proc_type, limit):
        self.stdout.write(f'Downloading {proc_type} data...')
        try:
            resp = requests.get(url, timeout=300)
            resp.raise_for_status()
        except Exception as e:
            self.stderr.write(f'Error: {e}')
            return

        self.stdout.write(f'  Downloaded {len(resp.content) // 1048576}MB, parsing...')

        created = 0
        updated = 0
        skipped = 0
        processed = 0
        batch_create = []

        reader = csv.DictReader(StringIO(resp.text))
        for row in reader:
            processed += 1
            if processed % 10000 == 0:
                self.stdout.write(f'  {processed:,} rows... ({created:,} created, {skipped:,} no match)')

            name = row.get('Rndrng_Prvdr_Org_Name', '').strip()
            state = row.get('Rndrng_Prvdr_State_Abrvtn', '').strip()
            if not name or not state:
                continue

            hospital = self._find_hospital(name, state)
            if not hospital:
                skipped += 1
                continue

            if proc_type == 'inpatient':
                code = row.get('DRG_Cd', '').strip()
                desc = row.get('DRG_Desc', '').strip()
                charge_str = row.get('Avg_Submtd_Cvrd_Chrg', '').strip()
                payment_str = row.get('Avg_Tot_Pymt_Amt', '').strip()
            else:
                code = row.get('APC_Cd', '').strip()
                desc = row.get('APC_Desc', '').strip()
                charge_str = row.get('Avg_Tot_Sbmtd_Chrgs', '').strip()
                payment_str = row.get('Avg_Mdcr_Alowd_Amt', '').strip()

            if not desc or not charge_str:
                continue

            try:
                charge = Decimal(str(round(float(charge_str), 2)))
                payment = Decimal(str(round(float(payment_str), 2))) if payment_str else None
            except (ValueError, TypeError):
                continue

            procedure = self._get_procedure(code, desc, proc_type)
            if not procedure:
                continue

            existing = PricingRecord.objects.filter(provider=hospital, procedure=procedure).first()
            if existing:
                if existing.cash_price != charge:
                    existing.cash_price = charge
                    existing.insured_price = payment
                    existing.last_verified = date.today()
                    existing.source_name = 'CMS Medicare Provider Charge Data 2024'
                    existing.confidence = 'high'
                    existing.price_type = 'published'
                    existing.save()
                    updated += 1
            else:
                batch_create.append(PricingRecord(
                    provider=hospital,
                    procedure=procedure,
                    cash_price=charge,
                    insured_price=payment,
                    price_type='published',
                    confidence='high',
                    source_name='CMS Medicare Provider Charge Data 2024',
                    last_verified=date.today(),
                ))
                created += 1

            if len(batch_create) >= 500:
                PricingRecord.objects.bulk_create(batch_create, ignore_conflicts=True)
                batch_create = []

            if limit and (created + updated) >= limit:
                break

        if batch_create:
            PricingRecord.objects.bulk_create(batch_create, ignore_conflicts=True)

        self.stdout.write(self.style.SUCCESS(
            f'\n{proc_type.upper()} Done!\n'
            f'  Rows: {processed:,}\n'
            f'  Created: {created:,}\n'
            f'  Updated: {updated:,}\n'
            f'  No match: {skipped:,}'
        ))
