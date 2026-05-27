"""
Import healthcare providers from the NPPES NPI Registry.
Reads directly from ZIP file — no extraction needed.

Usage: python manage.py import_nppes --states FL,CA,TX
       python manage.py import_nppes --file /path/to/npidata.csv
"""
import csv
import os
import zipfile
import requests
import re
from io import TextIOWrapper
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from healthcare.models import Provider, Location, ProviderType

TAXONOMY_MAP = {
    '208200000X': ('plastic-surgery-practice', 'Plastic Surgery Practice'),
    '207KA0200X': ('plastic-surgery-practice', 'Plastic Surgery Practice'),
    '2086S0105X': ('plastic-surgery-practice', 'Plastic Surgery Practice'),
    '122300000X': ('dental-office', 'Dental Office'),
    '1223G0001X': ('dental-office', 'Dental Office'),
    '1223P0221X': ('dental-office', 'Dental Office'),
    '1223E0200X': ('dental-office', 'Dental Office'),
    '1223P0106X': ('dental-office', 'Dental Office'),
    '1223D0001X': ('dental-office', 'Dental Office'),
    '1223P0700X': ('dental-office', 'Dental Office'),
    '1223S0112X': ('dental-office', 'Dental Office'),
    '1223D0004X': ('dental-office', 'Dental Office'),
    '1223X0008X': ('dental-office', 'Dental Office'),
    '204E00000X': ('dental-office', 'Dental Office'),
    '207W00000X': ('eye-center', 'Eye Center'),
    '207WX0200X': ('eye-center', 'Eye Center'),
    '152100000X': ('eye-center', 'Eye Center'),
    '207N00000X': ('dermatology', 'Dermatology'),
    '207ND0101X': ('dermatology', 'Dermatology'),
    '207NI0002X': ('dermatology', 'Dermatology'),
    '207ND0900X': ('dermatology', 'Dermatology'),
    '207NS0135X': ('dermatology', 'Dermatology'),
    '207RE0101X': ('fertility-clinic', 'Fertility Clinic'),
    '207VG0400X': ('fertility-clinic', 'Fertility Clinic'),
    '207X00000X': ('orthopedic-surgery', 'Orthopedic Surgery'),
    '207XS0114X': ('orthopedic-surgery', 'Orthopedic Surgery'),
    '207XS0106X': ('orthopedic-surgery', 'Orthopedic Surgery'),
    '207XX0004X': ('orthopedic-surgery', 'Orthopedic Surgery'),
    '207XX0801X': ('orthopedic-surgery', 'Orthopedic Surgery'),
    '207RG0300X': ('weight-loss-clinic', 'Weight Loss Clinic'),
    '111N00000X': ('chiropractor', 'Chiropractor'),
    '111NI0013X': ('chiropractor', 'Chiropractor'),
    '111NI0900X': ('chiropractor', 'Chiropractor'),
    '225100000X': ('physical-therapy', 'Physical Therapy'),
    '225101000X': ('physical-therapy', 'Physical Therapy'),
    '261QU0200X': ('urgent-care', 'Urgent Care'),
    '261QR0200X': ('imaging-center', 'Imaging Center'),
    '261QA1903X': ('surgery-center', 'Surgery Center'),
    '103T00000X': ('mental-health', 'Mental Health'),
    '103TA0400X': ('mental-health', 'Mental Health'),
    '103TA0700X': ('mental-health', 'Mental Health'),
    '1041C0700X': ('mental-health', 'Mental Health'),
    '213E00000X': ('podiatry', 'Podiatry'),
    '213ES0131X': ('podiatry', 'Podiatry'),
    '213ES0103X': ('podiatry', 'Podiatry'),
    # Gastroenterology
    '207RG0100X': ('gastroenterology', 'Gastroenterology'),
    # Cardiology (diagnostics)
    '207RC0000X': ('cardiology', 'Cardiology'),
    '207RC0001X': ('cardiology', 'Cardiology'),
    '207RI0011X': ('cardiology', 'Cardiology'),
    # OB/GYN
    '207V00000X': ('obgyn', 'OB/GYN'),
    '207VB0002X': ('obgyn', 'OB/GYN'),
    '207VX0000X': ('obgyn', 'OB/GYN'),
    # Diagnostic Radiology
    '2085R0202X': ('diagnostic-radiology', 'Diagnostic Radiology'),
    '2085R0001X': ('diagnostic-radiology', 'Diagnostic Radiology'),
    '2085D0003X': ('diagnostic-radiology', 'Diagnostic Radiology'),
    # Urology
    '208800000X': ('urology', 'Urology'),
    '2088P0231X': ('urology', 'Urology'),
    # ENT / Otolaryngology
    '207Y00000X': ('ent', 'ENT / Otolaryngology'),
    '207YS0123X': ('ent', 'ENT / Otolaryngology'),
    '207YX0602X': ('ent', 'ENT / Otolaryngology'),
    '207YX0905X': ('ent', 'ENT / Otolaryngology'),
    '207YX0901X': ('ent', 'ENT / Otolaryngology'),
    # General Surgery
    '208600000X': ('general-surgery', 'General Surgery'),
    '2086S0120X': ('general-surgery', 'General Surgery'),
    '2086S0127X': ('general-surgery', 'General Surgery'),
    '2086X0206X': ('general-surgery', 'General Surgery'),
    # Psychiatry (assessments, evaluations)
    '2084P0800X': ('psychiatry', 'Psychiatry'),
    '2084P0804X': ('psychiatry', 'Psychiatry'),
    '2084N0400X': ('psychiatry', 'Psychiatry'),
    '2084P0015X': ('psychiatry', 'Psychiatry'),
    # Optometry (expand)
    '152W00000X': ('eye-center', 'Eye Center'),
    '152WC0802X': ('eye-center', 'Eye Center'),
    '152WP0200X': ('eye-center', 'Eye Center'),
    # Sleep Medicine
    '207QS1201X': ('sleep-medicine', 'Sleep Medicine'),
    '2084S0012X': ('sleep-medicine', 'Sleep Medicine'),
    # Labs / Diagnostics
    '291U00000X': ('clinical-lab', 'Clinical Laboratory'),
    '293D00000X': ('clinical-lab', 'Clinical Laboratory'),
    # Allergy / Immunology
    '207K00000X': ('allergy-immunology', 'Allergy & Immunology'),
    '207KI0005X': ('allergy-immunology', 'Allergy & Immunology'),
}

TARGET_TAXONOMIES = set(TAXONOMY_MAP.keys())

STATE_FULL = {
    'AL': 'Alabama', 'AK': 'Alaska', 'AZ': 'Arizona', 'AR': 'Arkansas',
    'CA': 'California', 'CO': 'Colorado', 'CT': 'Connecticut', 'DE': 'Delaware',
    'DC': 'District of Columbia', 'FL': 'Florida', 'GA': 'Georgia', 'HI': 'Hawaii',
    'ID': 'Idaho', 'IL': 'Illinois', 'IN': 'Indiana', 'IA': 'Iowa',
    'KS': 'Kansas', 'KY': 'Kentucky', 'LA': 'Louisiana', 'ME': 'Maine',
    'MD': 'Maryland', 'MA': 'Massachusetts', 'MI': 'Michigan', 'MN': 'Minnesota',
    'MS': 'Mississippi', 'MO': 'Missouri', 'MT': 'Montana', 'NE': 'Nebraska',
    'NV': 'Nevada', 'NH': 'New Hampshire', 'NJ': 'New Jersey', 'NM': 'New Mexico',
    'NY': 'New York', 'NC': 'North Carolina', 'ND': 'North Dakota', 'OH': 'Ohio',
    'OK': 'Oklahoma', 'OR': 'Oregon', 'PA': 'Pennsylvania', 'RI': 'Rhode Island',
    'SC': 'South Carolina', 'SD': 'South Dakota', 'TN': 'Tennessee', 'TX': 'Texas',
    'UT': 'Utah', 'VT': 'Vermont', 'VA': 'Virginia', 'WA': 'Washington',
    'WV': 'West Virginia', 'WI': 'Wisconsin', 'WY': 'Wyoming',
}


class Command(BaseCommand):
    help = 'Import providers from NPPES NPI Registry'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=str, help='Path to npidata CSV file')
        parser.add_argument('--states', type=str, help='Comma-separated state codes (e.g. FL,CA,TX)')
        parser.add_argument('--limit', type=int, default=0, help='Max providers to import')

    def handle(self, *args, **options):
        csv_path = options.get('file')
        state_filter = None
        if options.get('states'):
            state_filter = set(options['states'].upper().split(','))

        # If no file provided, look for the ZIP we downloaded
        zip_path = None
        if not csv_path:
            home = os.path.expanduser('~')
            for f in os.listdir(home):
                if f.startswith('NPPES_Data_Dissemination') and f.endswith('.zip'):
                    zip_path = os.path.join(home, f)
                    break
            if not zip_path:
                self.stderr.write('No NPPES file found. Run with --download-only first or provide --file')
                return

        # Setup type cache
        type_cache = {}
        for slug, name in set(TAXONOMY_MAP.values()):
            pt, _ = ProviderType.objects.get_or_create(slug=slug, defaults={'name': name})
            type_cache[slug] = pt

        existing_npis = set(Provider.objects.filter(npi_number__gt='').values_list('npi_number', flat=True))
        existing_slugs = set(Provider.objects.values_list('slug', flat=True))
        location_cache = {}
        self.stdout.write(f'Existing providers with NPI: {len(existing_npis)}')

        # Open file — either from ZIP or direct CSV
        if zip_path:
            self.stdout.write(f'Reading from ZIP: {zip_path}')
            zf = zipfile.ZipFile(zip_path, 'r')
            csv_name = None
            for name in zf.namelist():
                if name.startswith('npidata_pfile') and name.endswith('.csv'):
                    csv_name = name
                    break
            if not csv_name:
                self.stderr.write('No npidata CSV found in ZIP')
                return
            self.stdout.write(f'Found: {csv_name}')
            raw = zf.open(csv_name)
            file_handle = TextIOWrapper(raw, encoding='utf-8', errors='replace')
        else:
            self.stdout.write(f'Reading from CSV: {csv_path}')
            zf = None
            file_handle = open(csv_path, 'r', encoding='utf-8', errors='replace')

        created = 0
        skipped_npi = 0
        skipped_state = 0
        skipped_taxonomy = 0
        skipped_deactivated = 0
        processed = 0
        batch = []
        limit = options.get('limit', 0)

        reader = csv.DictReader(file_handle)

        for row in reader:
            processed += 1

            if processed % 100000 == 0:
                self.stdout.write(f'  Processed {processed:,} rows... ({created:,} created, {skipped_npi:,} existing)')

            if row.get('NPI Deactivation Date', '').strip():
                skipped_deactivated += 1
                continue

            npi = row.get('NPI', '').strip()
            if not npi:
                continue

            if npi in existing_npis:
                skipped_npi += 1
                continue

            matched_type = None
            for i in range(1, 16):
                tax = row.get(f'Healthcare Provider Taxonomy Code_{i}', '').strip()
                if tax in TARGET_TAXONOMIES:
                    matched_type = TAXONOMY_MAP[tax]
                    break

            if not matched_type:
                skipped_taxonomy += 1
                continue

            state = row.get('Provider Business Practice Location Address State Name', '').strip()
            if not state:
                state = row.get('Provider Business Mailing Address State Name', '').strip()
            if not state or len(state) != 2:
                continue

            if state_filter and state not in state_filter:
                skipped_state += 1
                continue

            entity_type = row.get('Entity Type Code', '').strip()
            if entity_type == '1':
                first = row.get('Provider First Name', '').strip()
                last = row.get('Provider Last Name (Legal Name)', '').strip()
                credential = row.get('Provider Credential Text', '').strip()
                if not last:
                    continue
                name = f"{first} {last}".strip()
                if credential:
                    name = f"{name}, {credential}"
            else:
                name = row.get('Provider Organization Name (Legal Business Name)', '').strip()
                if not name:
                    continue

            city = row.get('Provider Business Practice Location Address City Name', '').strip()
            if not city:
                city = row.get('Provider Business Mailing Address City Name', '').strip()
            if not city:
                continue
            city = city.title()

            addr1 = row.get('Provider First Line Business Practice Location Address', '').strip()
            addr2 = row.get('Provider Second Line Business Practice Location Address', '').strip()
            zipcode = row.get('Provider Business Practice Location Address Postal Code', '').strip()[:5]
            address = addr1
            if addr2:
                address = f"{address}, {addr2}"
            address = f"{address}, {city}, {state} {zipcode}"

            phone = row.get('Provider Business Practice Location Address Telephone Number', '').strip()
            if phone and len(phone) == 10:
                phone = f"({phone[:3]}) {phone[3:6]}-{phone[6:]}"

            loc_key = f"{city.lower()}-{state.lower()}"
            if loc_key not in location_cache:
                loc_slug = slugify(f"{city}-{state}")[:200]
                location, _ = Location.objects.get_or_create(
                    slug=loc_slug,
                    defaults={
                        'city': city,
                        'state': state,
                        'state_full': STATE_FULL.get(state, state),
                    }
                )
                location_cache[loc_key] = location

            location = location_cache[loc_key]
            base_slug = slugify(name)[:190]
            slug = base_slug
            counter = 1
            while slug in existing_slugs:
                slug = f"{base_slug}-{counter}"
                counter += 1
            existing_slugs.add(slug)

            type_slug, type_name = matched_type
            provider_type = type_cache[type_slug]

            provider = Provider(
                name=name,
                slug=slug,
                npi_number=npi,
                provider_type=provider_type,
                location=location,
                address=address,
                phone=phone,
                transparency_compliant=False,
            )
            batch.append(provider)

            if len(batch) >= 1000:
                Provider.objects.bulk_create(batch, ignore_conflicts=True)
                created += len(batch)
                batch = []
                self.stdout.write(f'  Created {created:,} providers...')

            if limit and created >= limit:
                break

        if batch:
            Provider.objects.bulk_create(batch, ignore_conflicts=True)
            created += len(batch)

        file_handle.close()
        if zf:
            zf.close()

        self.stdout.write(self.style.SUCCESS(
            f'\nDone!\n'
            f'  Rows processed: {processed:,}\n'
            f'  Providers created: {created:,}\n'
            f'  Skipped (existing NPI): {skipped_npi:,}\n'
            f'  Skipped (wrong state): {skipped_state:,}\n'
            f'  Skipped (wrong taxonomy): {skipped_taxonomy:,}\n'
            f'  Skipped (deactivated): {skipped_deactivated:,}\n'
            f'  Locations: {len(location_cache)}'
        ))
