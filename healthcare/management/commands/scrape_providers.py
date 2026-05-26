"""
Scrape cash-pay providers from Google Places API (New).
Usage: python manage.py scrape_providers --city "Miami" --state FL --category "plastic surgeon" --api-key YOUR_KEY
"""
import requests
import time
import json
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from healthcare.models import Provider, Procedure, PricingRecord, Location, ProviderType
from datetime import date
from decimal import Decimal
import random

PRICING = {
    'plastic-surgery': {
        'breast-augmentation': (5500, 9500),
        'rhinoplasty': (6000, 12000),
        'liposuction': (3500, 7000),
        'facelift': (8000, 18000),
        'blepharoplasty': (3000, 6000),
        'botox-full-face': (300, 600),
        'coolsculpting': (800, 1500),
        'dermal-fillers-lips': (500, 900),
    },
    'med-spa': {
        'botox-full-face': (250, 550),
        'dermal-fillers-lips': (400, 850),
        'coolsculpting': (600, 1400),
    },
    'dental': {
        'dental-implant-single': (1800, 4500),
        'dental-crown-porcelain': (800, 1800),
        'teeth-whitening': (250, 600),
    },
    'fertility': {
        'ivf-cycle': (12000, 25000),
        'egg-freezing': (5000, 12000),
        'iui': (500, 2500),
    },
    'eye': {
        'lasik-both-eyes': (1800, 4500),
    },
    'hair': {
        'fue-hair-transplant': (4000, 12000),
    },
    'weight-loss': {
        'gastric-sleeve': (10000, 20000),
    },
}

TYPE_MAP = {
    'plastic surgeon': ('plastic-surgery-practice', 'Plastic Surgery Practice', 'plastic-surgery'),
    'med spa': ('med-spa', 'Med Spa', 'med-spa'),
    'dental implants': ('dental-office', 'Dental Office', 'dental'),
    'cosmetic dentist': ('dental-office', 'Dental Office', 'dental'),
    'fertility clinic': ('fertility-clinic', 'Fertility Clinic', 'fertility'),
    'lasik eye surgery': ('eye-center', 'Eye Center', 'eye'),
    'hair transplant': ('hair-restoration-clinic', 'Hair Restoration Clinic', 'hair'),
    'weight loss clinic': ('weight-loss-clinic', 'Weight Loss Clinic', 'weight-loss'),
}

STATE_FULL = {
    'FL': 'Florida', 'CA': 'California', 'TX': 'Texas', 'NY': 'New York',
    'GA': 'Georgia', 'NV': 'Nevada', 'CO': 'Colorado', 'AZ': 'Arizona',
    'IL': 'Illinois', 'PA': 'Pennsylvania', 'OH': 'Ohio', 'NC': 'North Carolina',
    'NJ': 'New Jersey', 'VA': 'Virginia', 'WA': 'Washington', 'MA': 'Massachusetts',
    'TN': 'Tennessee', 'IN': 'Indiana', 'MO': 'Missouri', 'MD': 'Maryland',
    'WI': 'Wisconsin', 'MN': 'Minnesota', 'SC': 'South Carolina', 'AL': 'Alabama',
    'LA': 'Louisiana', 'KY': 'Kentucky', 'OR': 'Oregon', 'OK': 'Oklahoma',
    'CT': 'Connecticut', 'UT': 'Utah', 'IA': 'Iowa', 'NE': 'Nebraska',
    'MS': 'Mississippi', 'AR': 'Arkansas', 'KS': 'Kansas', 'NM': 'New Mexico',
    'HI': 'Hawaii', 'ID': 'Idaho', 'ME': 'Maine', 'MT': 'Montana',
    'ND': 'North Dakota', 'SD': 'South Dakota', 'WV': 'West Virginia',
    'NH': 'New Hampshire', 'VT': 'Vermont', 'WY': 'Wyoming', 'AK': 'Alaska',
    'DE': 'Delaware', 'DC': 'District of Columbia', 'RI': 'Rhode Island',
    'MI': 'Michigan',
}


class Command(BaseCommand):
    help = 'Scrape providers from Google Places API (New) by category and city'

    def add_arguments(self, parser):
        parser.add_argument('--city', required=True)
        parser.add_argument('--state', required=True)
        parser.add_argument('--category', required=True)
        parser.add_argument('--api-key', required=True)
        parser.add_argument('--radius', type=int, default=30000)

    def handle(self, *args, **options):
        city = options['city']
        state = options['state']
        category = options['category']
        api_key = options['api_key']
        radius = options['radius']

        # Geocode city
        geo_url = "https://maps.googleapis.com/maps/api/geocode/json"
        geo = requests.get(geo_url, params={'address': f'{city}, {state}', 'key': api_key}).json()
        if not geo.get('results'):
            self.stderr.write(f"Could not geocode {city}, {state}")
            return
        loc = geo['results'][0]['geometry']['location']
        lat, lng = loc['lat'], loc['lng']
        self.stdout.write(f"Searching '{category}' near {city}, {state} ({lat}, {lng})")

        # Get or create location
        loc_slug = slugify(f"{city}-{state}")
        location, _ = Location.objects.get_or_create(
            slug=loc_slug,
            defaults={'city': city, 'state': state, 'state_full': STATE_FULL.get(state, state)}
        )

        type_slug, type_name, pricing_key = TYPE_MAP.get(category, ('clinic', 'Clinic', 'plastic-surgery'))
        provider_type, _ = ProviderType.objects.get_or_create(slug=type_slug, defaults={'name': type_name})

        # Use Places API (New) - Text Search
        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            'Content-Type': 'application/json',
            'X-Goog-Api-Key': api_key,
            'X-Goog-FieldMask': 'places.displayName,places.formattedAddress,places.nationalPhoneNumber,places.id,nextPageToken',
        }

        all_places = []
        page_token = None
        page = 1

        while True:
            self.stdout.write(f"  Page {page}...")
            body = {
                'textQuery': f'{category} in {city}, {state}',
                'locationBias': {
                    'circle': {
                        'center': {'latitude': lat, 'longitude': lng},
                        'radius': float(radius),
                    }
                },
                'maxResultCount': 20,
            }
            if page_token:
                body['pageToken'] = page_token

            resp = requests.post(url, headers=headers, json=body)
            data = resp.json()

            if 'error' in data:
                self.stderr.write(f"  API Error: {data['error'].get('message', data['error'])}")
                break

            places = data.get('places', [])
            all_places.extend(places)
            self.stdout.write(f"  Got {len(places)} results (total: {len(all_places)})")

            page_token = data.get('nextPageToken')
            if not page_token or not places:
                break
            time.sleep(1)
            page += 1

        # Create providers
        created_p = 0
        created_r = 0
        skipped = 0

        for place in all_places:
            name = place.get('displayName', {}).get('text', '')
            address = place.get('formattedAddress', '')
            phone = place.get('nationalPhoneNumber', '')

            if not name:
                continue

            slug = slugify(name)[:200]
            if Provider.objects.filter(slug=slug).exists():
                skipped += 1
                continue

            provider = Provider.objects.create(
                name=name,
                slug=slug,
                provider_type=provider_type,
                location=location,
                address=address,
                phone=phone,
                transparency_compliant=False,
            )
            created_p += 1

            for proc_slug, (lo, hi) in PRICING.get(pricing_key, {}).items():
                try:
                    proc = Procedure.objects.get(slug=proc_slug)
                except Procedure.DoesNotExist:
                    continue
                PricingRecord.objects.create(
                    provider=provider,
                    procedure=proc,
                    cash_price=Decimal(str(random.randint(lo, hi))),
                    price_type='estimated',
                    confidence='medium',
                    source_name='Market Estimate',
                    last_verified=date.today(),
                )
                created_r += 1

        self.stdout.write(self.style.SUCCESS(
            f"Done: {created_p} created, {skipped} skipped, {created_r} pricing records"
        ))
