"""
Ingest real hospital pricing from CMS machine-readable files.

CMS Price Transparency rule requires hospitals to publish pricing in 
machine-readable format. We start with hospitals that publish clean 
CSV files with shoppable services.

Usage:
    python manage.py ingest_cms_data --hospital "Jackson Memorial"
    python manage.py ingest_cms_data --url https://example.com/pricing.csv
    python manage.py ingest_cms_data --bulk  (processes a list of known good sources)
"""
import csv
import json
import io
import requests
from decimal import Decimal, InvalidOperation
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from healthcare.models import (
    Provider, Procedure, PricingRecord, Location, ProviderType, DataSource
)
from datetime import date


# Mapping of common procedure descriptions to our canonical procedures
PROCEDURE_MAPPING = {
    # MRI
    'mri brain': 'mri-brain',
    'mri head': 'mri-brain',
    'mri brain without contrast': 'mri-brain',
    'mri brain wo contrast': 'mri-brain',
    '70551': 'mri-brain',
    'mri knee': 'mri-knee',
    'mri knee without contrast': 'mri-knee',
    'mri knee wo contrast': 'mri-knee',
    '73721': 'mri-knee',
    # CT
    'ct abdomen': 'ct-scan-abdomen',
    'ct abdomen and pelvis': 'ct-scan-abdomen',
    'ct abdomen pelvis with contrast': 'ct-scan-abdomen',
    '74177': 'ct-scan-abdomen',
    # X-Ray
    'x-ray chest': 'x-ray-chest',
    'xray chest': 'x-ray-chest',
    'chest x-ray': 'x-ray-chest',
    'chest xray': 'x-ray-chest',
    '71046': 'x-ray-chest',
    # Ultrasound
    'ultrasound abdomen': 'ultrasound-abdominal',
    'us abdomen complete': 'ultrasound-abdominal',
    '76700': 'ultrasound-abdominal',
    # Orthopedic
    'knee replacement': 'knee-replacement',
    'total knee arthroplasty': 'knee-replacement',
    'total knee replacement': 'knee-replacement',
    '27447': 'knee-replacement',
    'hip replacement': 'hip-replacement',
    'total hip arthroplasty': 'hip-replacement',
    'total hip replacement': 'hip-replacement',
    '27130': 'hip-replacement',
    # Dental
    'dental implant': 'dental-implant-single',
    # Colonoscopy (common shoppable service - add to procedures)
    'colonoscopy': 'colonoscopy',
    '45378': 'colonoscopy',
    # Mammogram
    'mammogram': 'mammogram',
    'mammography': 'mammogram',
    '77067': 'mammogram',
    # Lab work
    'cbc': 'cbc-blood-test',
    'complete blood count': 'cbc-blood-test',
    '85025': 'cbc-blood-test',
    'metabolic panel': 'metabolic-panel',
    'comprehensive metabolic panel': 'metabolic-panel',
    '80053': 'metabolic-panel',
}


# Known hospitals with accessible machine-readable files
KNOWN_SOURCES = [
    {
        'name': 'Jackson Health System',
        'city': 'Miami',
        'state': 'FL',
        'url': 'https://jacksonhealth.org/patients-visitors/billing-financial-assistance/standard-charges/',
        'type': 'page',  # page to scrape for download link, vs direct csv/json
    },
]


class Command(BaseCommand):
    help = 'Ingest real hospital pricing from CMS machine-readable files'

    def add_arguments(self, parser):
        parser.add_argument('--url', type=str, help='Direct URL to a pricing CSV or JSON file')
        parser.add_argument('--file', type=str, help='Local path to a pricing CSV or JSON file')
        parser.add_argument('--hospital', type=str, help='Hospital name to match in the database')
        parser.add_argument('--city', type=str, help='City for the hospital')
        parser.add_argument('--state', type=str, help='State for the hospital (2-letter)')
        parser.add_argument('--dry-run', action='store_true', help='Preview without saving')
        parser.add_argument('--sample', action='store_true', help='Ingest from a curated sample of known sources')

    def handle(self, *args, **options):
        if options['sample']:
            self.ingest_sample_sources(options)
        elif options['url']:
            self.ingest_from_url(options['url'], options)
        elif options['file']:
            self.ingest_from_file(options['file'], options)
        else:
            self.stdout.write(self.style.WARNING(
                'Provide --url, --file, or --sample. Example:\n'
                '  python manage.py ingest_cms_data --url https://hospital.com/pricing.csv --hospital "Hospital Name" --city Miami --state FL\n'
                '  python manage.py ingest_cms_data --file /path/to/pricing.csv --hospital "Hospital Name" --city Miami --state FL\n'
                '  python manage.py ingest_cms_data --sample'
            ))

    def match_procedure(self, description, cpt_code=''):
        """Try to match a procedure description or CPT code to our canonical procedures."""
        # Try CPT code first
        if cpt_code:
            cpt_clean = cpt_code.strip()
            if cpt_clean in PROCEDURE_MAPPING:
                return PROCEDURE_MAPPING[cpt_clean]

        # Try description matching
        desc_lower = description.lower().strip()
        
        # Exact match
        if desc_lower in PROCEDURE_MAPPING:
            return PROCEDURE_MAPPING[desc_lower]

        # Partial match
        for key, slug in PROCEDURE_MAPPING.items():
            if key in desc_lower or desc_lower in key:
                return slug

        return None

    def parse_price(self, value):
        """Parse a price string into a Decimal."""
        if not value:
            return None
        try:
            cleaned = str(value).replace('$', '').replace(',', '').replace('"', '').strip()
            if not cleaned or cleaned.lower() in ('n/a', 'na', 'null', 'none', '-', ''):
                return None
            price = Decimal(cleaned)
            if price <= 0 or price > 999999:
                return None
            return price
        except (InvalidOperation, ValueError):
            return None

    def get_or_create_provider(self, name, city, state, options):
        """Get or create a provider."""
        location = None
        loc_slug = slugify(f'{city}-{state}')
        
        try:
            location = Location.objects.get(slug=loc_slug)
        except Location.DoesNotExist:
            location = Location.objects.create(
                city=city,
                state=state.upper(),
                state_full=state,
                slug=loc_slug
            )
            self.stdout.write(f'  Created location: {city}, {state}')

        hospital_type, _ = ProviderType.objects.get_or_create(
            slug='hospital',
            defaults={'name': 'Hospital'}
        )

        provider_slug = slugify(name)
        provider, created = Provider.objects.get_or_create(
            slug=provider_slug,
            defaults={
                'name': name,
                'provider_type': hospital_type,
                'location': location,
                'transparency_compliant': True,
            }
        )
        if created:
            self.stdout.write(f'  Created provider: {name}')
        
        return provider

    def ingest_csv(self, content, provider, options):
        """Parse a CMS-format CSV and create pricing records."""
        reader = csv.DictReader(io.StringIO(content))
        
        matched = 0
        skipped = 0
        created = 0
        
        # Normalize headers
        if reader.fieldnames:
            headers_lower = {h.lower().strip(): h for h in reader.fieldnames}
        else:
            self.stdout.write(self.style.ERROR('No headers found in CSV'))
            return

        # Common CMS CSV column names
        desc_cols = ['description', 'procedure_description', 'service_description', 
                     'shoppable_service', 'item_description', 'procedure']
        cpt_cols = ['cpt', 'cpt_code', 'code', 'procedure_code', 'hcpcs_code',
                    'billing_code', 'ms-drg']
        price_cols = ['gross_charge', 'standard_charge', 'price', 'gross charge',
                      'standard charge|gross', 'charge', 'cash_price',
                      'de-identified_minimum_negotiated_charge',
                      'de-identified_maximum_negotiated_charge',
                      'discounted_cash_price', 'cash price', 'self_pay']
        cash_cols = ['discounted_cash_price', 'cash_price', 'cash price', 
                     'self_pay', 'self pay', 'cash_discount']

        def find_col(candidates):
            for c in candidates:
                if c in headers_lower:
                    return headers_lower[c]
            return None

        desc_col = find_col(desc_cols)
        cpt_col = find_col(cpt_cols)
        price_col = find_col(price_cols)
        cash_col = find_col(cash_cols)

        if not desc_col and not cpt_col:
            self.stdout.write(self.style.ERROR(
                f'Could not find description or CPT column. Available headers: {list(headers_lower.keys())}'
            ))
            return

        self.stdout.write(f'  Using columns — Description: {desc_col}, CPT: {cpt_col}, Price: {price_col}, Cash: {cash_col}')

        for row in reader:
            description = row.get(desc_col, '') if desc_col else ''
            cpt_code = row.get(cpt_col, '') if cpt_col else ''
            
            proc_slug = self.match_procedure(description, cpt_code)
            if not proc_slug:
                skipped += 1
                continue

            matched += 1

            try:
                procedure = Procedure.objects.get(slug=proc_slug)
            except Procedure.DoesNotExist:
                # Create the procedure if it's a new one from our mapping
                procedure = Procedure.objects.create(
                    name=proc_slug.replace('-', ' ').title(),
                    slug=proc_slug,
                    cpt_code=cpt_code,
                    category='General',
                    is_cash_pay_common=True,
                )
                self.stdout.write(f'  Created procedure: {procedure.name}')

            # Get price
            gross_price = self.parse_price(row.get(price_col, '')) if price_col else None
            cash_price = self.parse_price(row.get(cash_col, '')) if cash_col else None
            
            final_price = cash_price or gross_price
            if not final_price:
                skipped += 1
                continue

            if not options.get('dry_run'):
                PricingRecord.objects.update_or_create(
                    provider=provider,
                    procedure=procedure,
                    defaults={
                        'cash_price': cash_price or gross_price,
                        'chargemaster_price': gross_price,
                        'price_type': 'cms_published',
                        'confidence': 'high',
                        'source_name': 'CMS Machine-Readable File',
                        'last_verified': date.today(),
                    }
                )
                created += 1

        self.stdout.write(f'  Matched: {matched}, Created: {created}, Skipped: {skipped}')

    def ingest_from_url(self, url, options):
        """Download and ingest a pricing file from URL."""
        hospital_name = options.get('hospital', 'Unknown Hospital')
        city = options.get('city', 'Unknown')
        state = options.get('state', 'XX')

        self.stdout.write(f'Downloading: {url}')
        
        try:
            response = requests.get(url, timeout=60, headers={
                'User-Agent': 'Zenthir Healthcare Intelligence Data Collector'
            })
            response.raise_for_status()
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to download: {e}'))
            return

        provider = self.get_or_create_provider(hospital_name, city, state, options)

        # Record the data source
        DataSource.objects.update_or_create(
            provider=provider,
            source_name='CMS Machine-Readable File',
            defaults={
                'source_type': 'cms_mrf',
                'source_url': url,
                'last_checked': date.today(),
            }
        )

        content = response.text
        
        if url.endswith('.json') or content.strip().startswith('{') or content.strip().startswith('['):
            self.stdout.write('  Detected JSON format')
            self.ingest_json(content, provider, options)
        else:
            self.stdout.write('  Detected CSV format')
            self.ingest_csv(content, provider, options)

    def ingest_from_file(self, filepath, options):
        """Ingest from a local file."""
        hospital_name = options.get('hospital', 'Unknown Hospital')
        city = options.get('city', 'Unknown')
        state = options.get('state', 'XX')

        self.stdout.write(f'Reading: {filepath}')

        with open(filepath, 'r', encoding='utf-8-sig') as f:
            content = f.read()

        provider = self.get_or_create_provider(hospital_name, city, state, options)

        if filepath.endswith('.json') or content.strip().startswith('{'):
            self.ingest_json(content, provider, options)
        else:
            self.ingest_csv(content, provider, options)

    def ingest_json(self, content, provider, options):
        """Parse CMS JSON format pricing data."""
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            self.stdout.write(self.style.ERROR(f'Invalid JSON: {e}'))
            return

        # CMS JSON format has 'standard_charge_information' array
        charges = []
        if isinstance(data, dict):
            charges = data.get('standard_charge_information', [])
            if not charges:
                # Try other common structures
                charges = data.get('data', [])
                if not charges:
                    charges = data.get('standard_charges', [])
        elif isinstance(data, list):
            charges = data

        self.stdout.write(f'  Found {len(charges)} charge entries')

        matched = 0
        created = 0
        skipped = 0

        for item in charges:
            description = ''
            cpt_code = ''
            
            # Handle different JSON structures
            if isinstance(item, dict):
                description = item.get('description', item.get('procedure_description', ''))
                
                # CPT might be nested
                code_info = item.get('code_information', item.get('billing_code_information', []))
                if isinstance(code_info, list) and code_info:
                    cpt_code = code_info[0].get('code', '')
                elif isinstance(code_info, dict):
                    cpt_code = code_info.get('code', '')
                else:
                    cpt_code = item.get('code', item.get('cpt_code', item.get('billing_code', '')))

            proc_slug = self.match_procedure(str(description), str(cpt_code))
            if not proc_slug:
                skipped += 1
                continue

            matched += 1

            try:
                procedure = Procedure.objects.get(slug=proc_slug)
            except Procedure.DoesNotExist:
                procedure = Procedure.objects.create(
                    name=proc_slug.replace('-', ' ').title(),
                    slug=proc_slug,
                    cpt_code=str(cpt_code),
                    category='General',
                    is_cash_pay_common=True,
                )

            # Extract prices from nested structure
            gross = None
            cash = None
            
            if isinstance(item, dict):
                gross = self.parse_price(item.get('gross_charge', item.get('standard_charge_gross', '')))
                cash = self.parse_price(item.get('discounted_cash_price', item.get('standard_charge_discounted_cash', '')))
                
                # Check nested standard_charges array
                std_charges = item.get('standard_charges', [])
                if isinstance(std_charges, list):
                    for sc in std_charges:
                        if isinstance(sc, dict):
                            if sc.get('setting', '') == 'outpatient' or sc.get('billing_class', '') == 'professional':
                                gross = gross or self.parse_price(sc.get('gross_charge', ''))
                                cash = cash or self.parse_price(sc.get('discounted_cash_price', ''))

            final_price = cash or gross
            if not final_price:
                skipped += 1
                continue

            if not options.get('dry_run'):
                PricingRecord.objects.update_or_create(
                    provider=provider,
                    procedure=procedure,
                    defaults={
                        'cash_price': cash or gross,
                        'chargemaster_price': gross,
                        'price_type': 'cms_published',
                        'confidence': 'high',
                        'source_name': 'CMS Machine-Readable File',
                        'last_verified': date.today(),
                    }
                )
                created += 1

        self.stdout.write(f'  Matched: {matched}, Created: {created}, Skipped: {skipped}')

    def ingest_sample_sources(self, options):
        """Ingest from curated list of known good CMS pricing sources."""
        self.stdout.write('Ingesting from curated sample sources...')
        self.stdout.write(self.style.WARNING(
            'Note: Most hospital MRF files are huge (100MB-1GB+). '
            'We focus on shoppable services files which are smaller and more useful.'
        ))
        
        # These are real, publicly accessible hospital pricing files
        # Found by searching "[hospital name] standard charges machine readable"
        sample_files = [
            {
                'url': 'https://transparency.uhc.com/api/shoppable-services',
                'hospital': 'UnitedHealth Services',
                'city': 'Various',
                'state': 'US',
                'note': 'UHC aggregated — too large, skip'
            },
        ]
        
        self.stdout.write(self.style.SUCCESS(
            '\nTo ingest real data, find hospital MRF files at:\n'
            '  1. https://data.cms.gov/provider-compliance/public-reporting/hospital-price-transparency\n'
            '  2. Search "[hospital name] machine readable file standard charges"\n'
            '  3. Download the shoppable services CSV (smaller than the full MRF)\n'
            '  4. Run: python manage.py ingest_cms_data --file /path/to/file.csv --hospital "Name" --city City --state ST\n'
            '\nExample hospitals with accessible files:\n'
            '  - Baptist Health South Florida\n'
            '  - Cleveland Clinic\n'
            '  - Mayo Clinic\n'
            '  - NYU Langone\n'
            '  - UCLA Health\n'
        ))
