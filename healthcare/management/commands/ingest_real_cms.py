"""
Ingest real CMS data from three files:
1. Hospital General Information — 5,400+ hospitals with metadata
2. Medicare Inpatient by Provider and Service — inpatient charges by DRG
3. Medicare Outpatient by Provider and Service — outpatient charges by APC
"""
import csv
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from healthcare.models import (
    Provider, Procedure, PricingRecord, Location, ProviderType, DataSource
)
from datetime import date
from collections import defaultdict


# DRG code to procedure slug mapping
DRG_MAPPING = {
    '469': 'knee-replacement',  # Major Hip and Knee Joint Replacement with MCC
    '470': 'knee-replacement',  # Major Hip and Knee Joint Replacement without MCC
    '521': 'hip-replacement',   # Hip Replacement with principal diagnosis of hip fracture
    '522': 'hip-replacement',   # Hip Replacement without principal diagnosis
    '473': 'acl-reconstruction', # Cervical Spinal Fusion (closest match)
    '619': 'colonoscopy',       # O.R. Procedures for Obesity (approximate)
    '621': 'gastric-bypass',    # O.R. Procedures for Obesity without CC/MCC
    '620': 'gastric-sleeve',    # O.R. Procedures for Obesity with CC
    '377': 'colonoscopy',       # G.I. Hemorrhage with MCC (involves colonoscopy)
    '378': 'colonoscopy',       # G.I. Hemorrhage with CC
    '379': 'colonoscopy',       # G.I. Hemorrhage without CC/MCC
    '216': 'cardiac-valve',     # Cardiac Valve procedures
    '266': 'breast-augmentation', # Breast procedures (approximate)
}

# DRG description keyword matching (fallback)
DRG_KEYWORDS = {
    'knee replacement': 'knee-replacement',
    'knee joint replacement': 'knee-replacement',
    'hip replacement': 'hip-replacement',
    'hip joint replacement': 'hip-replacement',
    'hip & femur': 'hip-replacement',
    'gastric bypass': 'gastric-bypass',
    'bariatric': 'gastric-sleeve',
    'obesity': 'gastric-sleeve',
    'spinal fusion': 'acl-reconstruction',
    'colonoscopy': 'colonoscopy',
    'breast proc': 'breast-augmentation',
}

# APC description keyword matching for outpatient
APC_KEYWORDS = {
    'mri brain': 'mri-brain',
    'mri head': 'mri-brain',
    'mri cranial': 'mri-brain',
    'mri - brain': 'mri-brain',
    'mr brain': 'mri-brain',
    'mri knee': 'mri-knee',
    'mri lower extremity': 'mri-knee',
    'mri joint lower': 'mri-knee',
    'mri musculoskeletal': 'mri-knee',
    'ct abdomen': 'ct-scan-abdomen',
    'ct pelvis': 'ct-scan-abdomen',
    'ct abd': 'ct-scan-abdomen',
    'ct - abdomen': 'ct-scan-abdomen',
    'chest x-ray': 'x-ray-chest',
    'x-ray chest': 'x-ray-chest',
    'radiologic chest': 'x-ray-chest',
    'ultrasound abdom': 'ultrasound-abdominal',
    'echo abdom': 'ultrasound-abdominal',
    'us abdomen': 'ultrasound-abdominal',
    'mammograph': 'mammogram',
    'mammogram': 'mammogram',
    'screening mamm': 'mammogram',
    'diagnostic mamm': 'mammogram',
    'colonoscopy': 'colonoscopy',
    'echocardiog': 'echocardiogram',
    'transthoracic echo': 'echocardiogram',
    'electrocardiog': 'ekg',
    'ekg': 'ekg',
    'ecg': 'ekg',
    'complete blood': 'cbc-blood-test',
    'cbc': 'cbc-blood-test',
    'metabolic panel': 'metabolic-panel',
    'comprehensive metabolic': 'metabolic-panel',
    'level iv mri': 'mri-brain',
    'level iii mri': 'mri-knee',
    'level ii ct': 'ct-scan-abdomen',
    'level iii ct': 'ct-scan-abdomen',
}

# Hospital ownership mapping
OWNERSHIP_MAP = {
    'Government - Hospital District or Authority': 'government',
    'Government - State': 'government',
    'Government - Local': 'government',
    'Government - Federal': 'government',
    'Voluntary non-profit - Church': 'nonprofit',
    'Voluntary non-profit - Private': 'nonprofit',
    'Voluntary non-profit - Other': 'nonprofit',
    'Proprietary': 'hospital_system',
    'Physician': 'physician_group',
    'Tribal': 'government',
}


class Command(BaseCommand):
    help = 'Ingest real CMS hospital and pricing data'

    def add_arguments(self, parser):
        parser.add_argument('--hospitals', type=str, required=True, help='Path to Hospital_General_Information.csv')
        parser.add_argument('--inpatient', type=str, help='Path to inpatient charges CSV')
        parser.add_argument('--outpatient', type=str, help='Path to outpatient charges CSV')
        parser.add_argument('--limit', type=int, help='Limit number of hospitals to process')
        parser.add_argument('--states', type=str, help='Comma-separated state codes to filter (e.g., FL,TX,CA)')

    def handle(self, *args, **options):
        state_filter = None
        if options['states']:
            state_filter = [s.strip().upper() for s in options['states'].split(',')]

        self.stdout.write('=' * 60)
        self.stdout.write('ZENTHIR CMS DATA INGESTION')
        self.stdout.write('=' * 60)

        # Step 1: Ingest hospitals
        hospital_map = self.ingest_hospitals(options['hospitals'], state_filter, options.get('limit'))

        # Step 2: Ingest inpatient charges
        if options.get('inpatient'):
            self.ingest_inpatient(options['inpatient'], hospital_map, state_filter)

        # Step 3: Ingest outpatient charges
        if options.get('outpatient'):
            self.ingest_outpatient(options['outpatient'], hospital_map, state_filter)

        # Step 4: Calculate regional medians
        self.calculate_medians()

        self.stdout.write(self.style.SUCCESS(
            f'\nDone. {Provider.objects.count()} providers, {PricingRecord.objects.count()} pricing records.'
        ))

    def parse_price(self, value):
        if not value:
            return None
        try:
            cleaned = str(value).replace('$', '').replace(',', '').replace('"', '').strip()
            if not cleaned or cleaned.lower() in ('n/a', 'na', 'null', 'none', '-', ''):
                return None
            price = Decimal(cleaned)
            if price <= 0 or price > 9999999:
                return None
            return price
        except (InvalidOperation, ValueError):
            return None

    def parse_rating(self, value):
        if not value or value.strip() in ('Not Available', '', 'N/A'):
            return None
        try:
            return Decimal(value.strip())
        except:
            return None

    def get_or_create_location(self, city, state):
        if not city or not state:
            return None
        slug = slugify(f'{city}-{state}')
        location, created = Location.objects.get_or_create(
            slug=slug,
            defaults={
                'city': city.title(),
                'state': state.upper(),
                'state_full': state.upper(),
            }
        )
        return location

    def ingest_hospitals(self, filepath, state_filter, limit):
        self.stdout.write(f'\n--- Ingesting hospitals from {filepath} ---')

        hospital_type, _ = ProviderType.objects.get_or_create(
            slug='hospital', defaults={'name': 'Hospital'}
        )

        hospital_map = {}  # facility_id -> provider
        count = 0
        created = 0
        skipped = 0

        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                state = row.get('State', '').strip()
                if state_filter and state not in state_filter:
                    skipped += 1
                    continue

                facility_id = row.get('Facility ID', '').strip()
                name = row.get('Facility Name', '').strip()
                if not name:
                    continue

                city = row.get('City/Town', '').strip()
                address = row.get('Address', '').strip()
                zipcode = row.get('ZIP Code', '').strip()
                phone = row.get('Telephone Number', '').strip()
                ownership_raw = row.get('Hospital Ownership', '').strip()
                rating = self.parse_rating(row.get('Hospital overall rating', ''))
                hospital_type_raw = row.get('Hospital Type', '').strip()
                emergency = row.get('Emergency Services', '').strip()

                ownership = OWNERSHIP_MAP.get(ownership_raw, 'hospital_system')
                location = self.get_or_create_location(city, state)

                slug = slugify(name)
                if not slug:
                    continue

                # Handle duplicate slugs
                if Provider.objects.filter(slug=slug).exclude(
                    location__state=state.upper() if location else None
                ).exists():
                    slug = slugify(f'{name}-{city}-{state}')

                provider, was_created = Provider.objects.update_or_create(
                    slug=slug,
                    defaults={
                        'name': name.title(),
                        'provider_type': hospital_type,
                        'location': location,
                        'address': f'{address}, {city}, {state} {zipcode}',
                        'phone': phone,
                        'ownership_type': ownership,
                        'cms_star_rating': rating,
                        'transparency_compliant': True,
                        'npi_number': facility_id,
                    }
                )

                hospital_map[facility_id] = provider
                count += 1
                if was_created:
                    created += 1

                if limit and count >= limit:
                    break

        self.stdout.write(f'  Processed: {count}, Created: {created}, Skipped: {skipped}')
        self.stdout.write(f'  Locations: {Location.objects.count()}')
        return hospital_map

    def match_drg_to_procedure(self, drg_code, drg_desc):
        # Try direct DRG code mapping
        if drg_code in DRG_MAPPING:
            return DRG_MAPPING[drg_code]

        # Try keyword matching on description
        desc_lower = drg_desc.lower()
        for keyword, slug in DRG_KEYWORDS.items():
            if keyword in desc_lower:
                return slug

        return None

    def match_apc_to_procedure(self, apc_code, apc_desc):
        desc_lower = apc_desc.lower()
        for keyword, slug in APC_KEYWORDS.items():
            if keyword in desc_lower:
                return slug
        return None

    def ingest_inpatient(self, filepath, hospital_map, state_filter):
        self.stdout.write(f'\n--- Ingesting inpatient charges from {filepath} ---')

        matched = 0
        created = 0
        skipped = 0

        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                state = row.get('Rndrng_Prvdr_State_Abrvtn', '').strip()
                if state_filter and state not in state_filter:
                    skipped += 1
                    continue

                ccn = row.get('Rndrng_Prvdr_CCN', '').strip()
                drg_code = row.get('DRG_Cd', '').strip()
                drg_desc = row.get('DRG_Desc', '').strip()

                proc_slug = self.match_drg_to_procedure(drg_code, drg_desc)
                if not proc_slug:
                    skipped += 1
                    continue

                # Find or create provider
                provider = hospital_map.get(ccn)
                if not provider:
                    name = row.get('Rndrng_Prvdr_Org_Name', '').strip()
                    city = row.get('Rndrng_Prvdr_City', '').strip()
                    if not name:
                        skipped += 1
                        continue
                    provider = self.get_or_create_provider_from_row(name, city, state, ccn)
                    hospital_map[ccn] = provider

                # Find procedure
                try:
                    procedure = Procedure.objects.get(slug=proc_slug)
                except Procedure.DoesNotExist:
                    skipped += 1
                    continue

                avg_charge = self.parse_price(row.get('Avg_Submtd_Cvrd_Chrg', ''))
                avg_payment = self.parse_price(row.get('Avg_Tot_Pymt_Amt', ''))
                avg_medicare = self.parse_price(row.get('Avg_Mdcr_Pymt_Amt', ''))

                if not avg_charge:
                    skipped += 1
                    continue

                matched += 1

                PricingRecord.objects.update_or_create(
                    provider=provider,
                    procedure=procedure,
                    defaults={
                        'cash_price': avg_charge,
                        'chargemaster_price': avg_charge,
                        'insured_price': avg_payment,
                        'negotiated_rate': avg_medicare,
                        'insurer_name': 'Medicare',
                        'price_type': 'cms_published',
                        'confidence': 'high',
                        'source_name': 'CMS Medicare Inpatient Data 2024',
                        'last_verified': date.today(),
                    }
                )
                created += 1

        self.stdout.write(f'  Matched: {matched}, Created: {created}, Skipped: {skipped}')

    def ingest_outpatient(self, filepath, hospital_map, state_filter):
        self.stdout.write(f'\n--- Ingesting outpatient charges from {filepath} ---')

        matched = 0
        created = 0
        skipped = 0

        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                state = row.get('Rndrng_Prvdr_State_Abrvtn', '').strip()
                if state_filter and state not in state_filter:
                    skipped += 1
                    continue

                ccn = row.get('Rndrng_Prvdr_CCN', '').strip()
                apc_code = row.get('APC_Cd', '').strip()
                apc_desc = row.get('APC_Desc', '').strip()

                proc_slug = self.match_apc_to_procedure(apc_code, apc_desc)
                if not proc_slug:
                    skipped += 1
                    continue

                provider = hospital_map.get(ccn)
                if not provider:
                    name = row.get('Rndrng_Prvdr_Org_Name', '').strip()
                    city = row.get('Rndrng_Prvdr_City', '').strip()
                    if not name:
                        skipped += 1
                        continue
                    provider = self.get_or_create_provider_from_row(name, city, state, ccn)
                    hospital_map[ccn] = provider

                try:
                    procedure = Procedure.objects.get(slug=proc_slug)
                except Procedure.DoesNotExist:
                    skipped += 1
                    continue

                avg_charge = self.parse_price(row.get('Avg_Tot_Sbmtd_Chrgs', ''))
                avg_allowed = self.parse_price(row.get('Avg_Mdcr_Alowd_Amt', ''))
                avg_payment = self.parse_price(row.get('Avg_Mdcr_Pymt_Amt', ''))

                if not avg_charge:
                    skipped += 1
                    continue

                matched += 1

                PricingRecord.objects.update_or_create(
                    provider=provider,
                    procedure=procedure,
                    defaults={
                        'cash_price': avg_charge,
                        'chargemaster_price': avg_charge,
                        'insured_price': avg_allowed,
                        'negotiated_rate': avg_payment,
                        'insurer_name': 'Medicare',
                        'price_type': 'cms_published',
                        'confidence': 'high',
                        'source_name': 'CMS Medicare Outpatient Data 2023',
                        'last_verified': date.today(),
                    }
                )
                created += 1

        self.stdout.write(f'  Matched: {matched}, Created: {created}, Skipped: {skipped}')

    def get_or_create_provider_from_row(self, name, city, state, ccn):
        hospital_type, _ = ProviderType.objects.get_or_create(
            slug='hospital', defaults={'name': 'Hospital'}
        )
        location = self.get_or_create_location(city, state)
        slug = slugify(name)
        if not slug:
            slug = f'hospital-{ccn}'

        provider, _ = Provider.objects.get_or_create(
            slug=slug,
            defaults={
                'name': name.title(),
                'provider_type': hospital_type,
                'location': location,
                'transparency_compliant': True,
                'npi_number': ccn,
            }
        )
        return provider

    def calculate_medians(self):
        self.stdout.write('\n--- Calculating regional medians ---')

        procedures = Procedure.objects.all()
        locations = Location.objects.all()
        updated = 0

        for procedure in procedures:
            for location in locations:
                records = list(PricingRecord.objects.filter(
                    procedure=procedure,
                    provider__location=location,
                    cash_price__isnull=False
                ))

                if len(records) < 2:
                    continue

                prices = sorted([r.cash_price for r in records])
                n = len(prices)
                if n % 2 == 0:
                    median = (prices[n // 2 - 1] + prices[n // 2]) / 2
                else:
                    median = prices[n // 2]

                if median > 0:
                    for record in records:
                        record.vs_regional_median = round(float(record.cash_price) / float(median), 2)
                        record.save(update_fields=['vs_regional_median'])
                        updated += 1

        self.stdout.write(f'  Updated {updated} records with regional medians')
