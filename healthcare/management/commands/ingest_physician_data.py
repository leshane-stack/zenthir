"""
Ingest CMS Physician & Other Practitioners data.
Streams 9.7M rows but only keeps rows matching our target CPT codes.
This fills the imaging/outpatient gap with real facility-level pricing.
"""
import csv
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from healthcare.models import Provider, Procedure, PricingRecord, Location, ProviderType
from datetime import date


# CPT codes we care about mapped to procedure slugs
CPT_MAP = {
    # MRI
    '70551': 'mri-brain',
    '70553': 'mri-brain',
    '73721': 'mri-knee',
    '73723': 'mri-knee',
    # CT
    '74177': 'ct-scan-abdomen',
    '74176': 'ct-scan-abdomen',
    '74178': 'ct-scan-abdomen',
    # X-Ray
    '71045': 'x-ray-chest',
    '71046': 'x-ray-chest',
    '71047': 'x-ray-chest',
    '71048': 'x-ray-chest',
    # Ultrasound
    '76700': 'ultrasound-abdominal',
    '76705': 'ultrasound-abdominal',
    # Mammogram
    '77065': 'mammogram',
    '77066': 'mammogram',
    '77067': 'mammogram',
    # Colonoscopy
    '45378': 'colonoscopy',
    '45380': 'colonoscopy',
    '45385': 'colonoscopy',
    # Echocardiogram
    '93306': 'echocardiogram',
    '93307': 'echocardiogram',
    '93308': 'echocardiogram',
    # EKG
    '93000': 'ekg',
    '93005': 'ekg',
    '93010': 'ekg',
    # Labs
    '85025': 'cbc-blood-test',
    '85027': 'cbc-blood-test',
    '80053': 'metabolic-panel',
    '80048': 'metabolic-panel',
    # Hip/Knee (additional CPT codes beyond DRG)
    '27447': 'knee-replacement',
    '27130': 'hip-replacement',
    '29888': 'acl-reconstruction',
}


class Command(BaseCommand):
    help = 'Ingest CMS Physician & Other Practitioners data for imaging and outpatient procedures'

    def add_arguments(self, parser):
        parser.add_argument('--file', type=str, required=True, help='Path to physician CSV')
        parser.add_argument('--states', type=str, help='Comma-separated state codes to filter')
        parser.add_argument('--facility-only', action='store_true', help='Only include facility/org providers (not individual physicians)')

    def handle(self, *args, **options):
        filepath = options['file']
        state_filter = None
        if options['states']:
            state_filter = [s.strip().upper() for s in options['states'].split(',')]

        facility_only = options.get('facility_only', False)

        self.stdout.write(f'Streaming {filepath}...')
        self.stdout.write(f'Looking for CPT codes: {", ".join(sorted(CPT_MAP.keys()))}')
        if state_filter:
            self.stdout.write(f'Filtering states: {", ".join(state_filter)}')
        if facility_only:
            self.stdout.write('Facility/organization providers only')

        imaging_type, _ = ProviderType.objects.get_or_create(
            slug='imaging-center', defaults={'name': 'Imaging Center'}
        )
        clinic_type, _ = ProviderType.objects.get_or_create(
            slug='clinic', defaults={'name': 'Clinic'}
        )

        matched = 0
        created = 0
        skipped = 0
        processed = 0

        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                processed += 1
                if processed % 500000 == 0:
                    self.stdout.write(f'  Processed {processed:,} rows... ({matched} matched)')

                # Check CPT code
                cpt = row.get('HCPCS_Cd', '').strip()
                if cpt not in CPT_MAP:
                    continue

                # State filter
                state = row.get('Rndrng_Prvdr_State_Abrvtn', '').strip()
                if state_filter and state not in state_filter:
                    skipped += 1
                    continue

                # Facility only filter - entity code 'O' = organization
                if facility_only:
                    entity = row.get('Rndrng_Prvdr_Ent_Cd', '').strip()
                    if entity != 'O':
                        skipped += 1
                        continue

                # Get price
                avg_charge = self.parse_price(row.get('Avg_Sbmtd_Chrg', ''))
                avg_allowed = self.parse_price(row.get('Avg_Mdcr_Alowd_Amt', ''))
                avg_payment = self.parse_price(row.get('Avg_Mdcr_Pymt_Amt', ''))

                if not avg_charge:
                    skipped += 1
                    continue

                # Get or create provider
                name = row.get('Rndrng_Prvdr_Last_Org_Name', '').strip()
                first_name = row.get('Rndrng_Prvdr_First_Name', '').strip()
                city = row.get('Rndrng_Prvdr_City', '').strip()
                npi = row.get('Rndrng_NPI', '').strip()
                entity_code = row.get('Rndrng_Prvdr_Ent_Cd', '').strip()
                provider_type_raw = row.get('Rndrng_Prvdr_Type', '').strip()

                # Build display name
                if entity_code == 'O':
                    display_name = name.title()
                else:
                    if first_name:
                        display_name = f'{first_name} {name}'.title()
                    else:
                        display_name = name.title()

                if not display_name or not city:
                    skipped += 1
                    continue

                # Determine provider type
                if entity_code == 'O':
                    ptype = self.guess_provider_type(provider_type_raw, display_name)
                else:
                    ptype, _ = ProviderType.objects.get_or_create(
                        slug='physician', defaults={'name': 'Physician'}
                    )

                location = self.get_or_create_location(city, state)

                slug = slugify(f'{display_name}-{city}-{state}')
                if not slug:
                    slug = f'provider-{npi}'

                provider, _ = Provider.objects.get_or_create(
                    slug=slug,
                    defaults={
                        'name': display_name,
                        'provider_type': ptype,
                        'location': location,
                        'npi_number': npi,
                        'transparency_compliant': True,
                    }
                )

                # Get procedure
                proc_slug = CPT_MAP[cpt]
                try:
                    procedure = Procedure.objects.get(slug=proc_slug)
                except Procedure.DoesNotExist:
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
                        'source_name': 'CMS Medicare Physician Data 2024',
                        'last_verified': date.today(),
                    }
                )
                created += 1

        self.stdout.write(f'\n  Total processed: {processed:,}')
        self.stdout.write(f'  Matched: {matched}, Created: {created}, Skipped: {skipped}')
        self.stdout.write(self.style.SUCCESS(
            f'\nDone. Total providers: {Provider.objects.count()}, Total pricing: {PricingRecord.objects.count()}'
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

    def guess_provider_type(self, provider_type_raw, name):
        name_lower = name.lower()
        type_lower = provider_type_raw.lower() if provider_type_raw else ''

        if any(k in name_lower for k in ['imaging', 'radiology', 'diagnostic', 'mri', 'scan']):
            pt, _ = ProviderType.objects.get_or_create(
                slug='imaging-center', defaults={'name': 'Imaging Center'}
            )
        elif any(k in name_lower for k in ['hospital', 'medical center', 'health system']):
            pt, _ = ProviderType.objects.get_or_create(
                slug='hospital', defaults={'name': 'Hospital'}
            )
        elif any(k in name_lower for k in ['surgery center', 'surgical', 'ambulatory']):
            pt, _ = ProviderType.objects.get_or_create(
                slug='surgery-center', defaults={'name': 'Surgery Center'}
            )
        elif any(k in name_lower for k in ['clinic', 'medical group', 'physicians', 'associates']):
            pt, _ = ProviderType.objects.get_or_create(
                slug='clinic', defaults={'name': 'Clinic'}
            )
        elif 'diagnostic' in type_lower or 'radiology' in type_lower:
            pt, _ = ProviderType.objects.get_or_create(
                slug='imaging-center', defaults={'name': 'Imaging Center'}
            )
        else:
            pt, _ = ProviderType.objects.get_or_create(
                slug='clinic', defaults={'name': 'Clinic'}
            )
        return pt
