import random
from django.core.management.base import BaseCommand
from django.utils.text import slugify
from healthcare.models import (
    Provider, ProviderType, Location, Procedure, PricingRecord, Vertical
)


class Command(BaseCommand):
    help = 'Seed 50+ providers across all cities with realistic pricing'

    def handle(self, *args, **options):
        self.seed_providers()
        self.seed_pricing()
        self.stdout.write(self.style.SUCCESS(
            f'Done. {Provider.objects.count()} providers, {PricingRecord.objects.count()} pricing records.'
        ))

    def seed_providers(self):
        hospital = ProviderType.objects.get(slug='hospital')
        surgery = ProviderType.objects.get(slug='surgery-center')
        imaging = ProviderType.objects.get(slug='imaging-center')
        dental = ProviderType.objects.get(slug='dental-office')
        medspa = ProviderType.objects.get(slug='med-spa')
        fertility_clinic = ProviderType.objects.get(slug='fertility-clinic')
        eye = ProviderType.objects.get(slug='eye-center')
        hair_clinic = ProviderType.objects.get(slug='hair-restoration-clinic')
        urgent = ProviderType.objects.get(slug='urgent-care')

        providers = [
            # --- MIAMI ---
            ('Mount Sinai Medical Center', hospital, 'miami-fl', 'nonprofit', '', 1949, 672, True, 3.5),
            ('Mercy Hospital Miami', hospital, 'miami-fl', 'hospital_system', 'HCA Healthcare', 1950, 488, True, 3.0),
            ('South Florida Spine & Ortho', surgery, 'miami-fl', 'physician_group', '', 2011, None, True, None),
            ('Coral Gables Imaging', imaging, 'miami-fl', 'independent', '', 2009, None, True, None),
            ('Miami Fertility Institute', fertility_clinic, 'miami-fl', 'physician_group', '', 2004, None, False, None),
            ('Brickell Aesthetics', medspa, 'miami-fl', 'independent', '', 2016, None, False, None),
            ('Miami LASIK Center', eye, 'miami-fl', 'independent', '', 2008, None, False, None),

            # --- HOUSTON ---
            ('St. Lukes Hospital', hospital, 'houston-tx', 'nonprofit', 'CHI St. Lukes Health', 1954, 610, True, 3.5),
            ('HCA Houston Healthcare', hospital, 'houston-tx', 'hospital_system', 'HCA Healthcare', 1975, 520, True, 3.0),
            ('Houston Surgical Center', surgery, 'houston-tx', 'physician_group', '', 2006, None, True, None),
            ('Gulf Coast Imaging', imaging, 'houston-tx', 'independent', '', 2010, None, True, None),
            ('Houston IVF Center', fertility_clinic, 'houston-tx', 'physician_group', '', 2003, None, False, None),
            ('Texas Hair Restoration', hair_clinic, 'houston-tx', 'independent', '', 2012, None, False, None),
            ('Katy Urgent Care', urgent, 'houston-tx', 'franchise', 'CareNow', 2015, None, False, None),

            # --- LOS ANGELES ---
            ('Providence Saint Johns', hospital, 'los-angeles-ca', 'nonprofit', 'Providence Health', 1942, 266, True, 4.0),
            ('Good Samaritan Hospital LA', hospital, 'los-angeles-ca', 'nonprofit', '', 1885, 408, True, 3.0),
            ('Beverly Hills Surgical Center', surgery, 'los-angeles-ca', 'physician_group', '', 2001, None, True, None),
            ('West LA Imaging', imaging, 'los-angeles-ca', 'independent', '', 2007, None, True, None),
            ('LA Reproductive Center', fertility_clinic, 'los-angeles-ca', 'physician_group', '', 2005, None, False, None),
            ('Beverly Hills Aesthetics', medspa, 'los-angeles-ca', 'independent', '', 2010, None, False, None),
            ('SoCal LASIK Institute', eye, 'los-angeles-ca', 'physician_group', '', 2006, None, False, None),
            ('LA Hair Transplant Center', hair_clinic, 'los-angeles-ca', 'independent', '', 2014, None, False, None),

            # --- NEW YORK ---
            ('NYU Langone Medical Center', hospital, 'new-york-ny', 'nonprofit', 'NYU Langone Health', 1882, 806, True, 5.0),
            ('Mount Sinai Hospital', hospital, 'new-york-ny', 'nonprofit', 'Mount Sinai Health System', 1852, 1139, True, 4.5),
            ('NewYork-Presbyterian Hospital', hospital, 'new-york-ny', 'nonprofit', 'NewYork-Presbyterian', 1771, 2600, True, 4.5),
            ('Manhattan Surgical Arts', surgery, 'new-york-ny', 'physician_group', '', 2008, None, True, None),
            ('NYC Advanced Imaging', imaging, 'new-york-ny', 'independent', '', 2011, None, True, None),
            ('Manhattan Fertility Center', fertility_clinic, 'new-york-ny', 'physician_group', '', 2002, None, False, None),
            ('Park Avenue Aesthetics', medspa, 'new-york-ny', 'independent', '', 2013, None, False, None),
            ('NYC Dental Studio', dental, 'new-york-ny', 'independent', '', 2009, None, False, None),

            # --- CHICAGO ---
            ('Northwestern Memorial Hospital', hospital, 'chicago-il', 'nonprofit', 'Northwestern Medicine', 1926, 894, True, 5.0),
            ('Rush University Medical Center', hospital, 'chicago-il', 'nonprofit', 'Rush University System', 1837, 664, True, 4.5),
            ('Chicago Outpatient Surgery', surgery, 'chicago-il', 'physician_group', '', 2010, None, True, None),
            ('Lakeshore Imaging Center', imaging, 'chicago-il', 'independent', '', 2012, None, True, None),
            ('Midwest Fertility Center', fertility_clinic, 'chicago-il', 'physician_group', '', 2006, None, False, None),

            # --- DALLAS ---
            ('Baylor University Medical Center', hospital, 'dallas-tx', 'nonprofit', 'Baylor Scott & White', 1903, 914, True, 4.0),
            ('Medical City Dallas', hospital, 'dallas-tx', 'hospital_system', 'HCA Healthcare', 1974, 661, True, 3.5),
            ('North Texas Surgical Center', surgery, 'dallas-tx', 'physician_group', '', 2009, None, True, None),
            ('DFW Open MRI', imaging, 'dallas-tx', 'independent', '', 2011, None, True, None),
            ('Dallas Cosmetic Surgery Center', surgery, 'dallas-tx', 'physician_group', '', 2007, None, False, None),

            # --- ATLANTA ---
            ('Emory University Hospital', hospital, 'atlanta-ga', 'nonprofit', 'Emory Healthcare', 1904, 733, True, 4.5),
            ('Piedmont Atlanta Hospital', hospital, 'atlanta-ga', 'nonprofit', 'Piedmont Healthcare', 1905, 529, True, 4.0),
            ('Atlanta Imaging Associates', imaging, 'atlanta-ga', 'independent', '', 2008, None, True, None),
            ('Peachtree Dental Arts', dental, 'atlanta-ga', 'independent', '', 2011, None, False, None),

            # --- PHOENIX ---
            ('Mayo Clinic Phoenix', hospital, 'phoenix-az', 'nonprofit', 'Mayo Clinic', 1998, 304, True, 5.0),
            ('Banner University Medical Center', hospital, 'phoenix-az', 'nonprofit', 'Banner Health', 1911, 699, True, 3.5),
            ('Arizona Spine & Joint', surgery, 'phoenix-az', 'physician_group', '', 2005, None, True, None),
            ('Desert Imaging Center', imaging, 'phoenix-az', 'independent', '', 2010, None, True, None),
            ('Phoenix Fertility Institute', fertility_clinic, 'phoenix-az', 'physician_group', '', 2007, None, False, None),

            # --- TAMPA ---
            ('Tampa General Hospital', hospital, 'tampa-fl', 'nonprofit', '', 1927, 1041, True, 4.0),
            ('AdventHealth Tampa', hospital, 'tampa-fl', 'nonprofit', 'AdventHealth', 1908, 541, True, 3.5),
            ('Bay Area Imaging', imaging, 'tampa-fl', 'independent', '', 2013, None, True, None),

            # --- DENVER ---
            ('UCHealth University of Colorado Hospital', hospital, 'denver-co', 'nonprofit', 'UCHealth', 2004, 620, True, 4.5),
            ('Denver Health Medical Center', hospital, 'denver-co', 'government', '', 1860, 525, True, 3.5),
            ('Mile High Imaging', imaging, 'denver-co', 'independent', '', 2011, None, True, None),
            ('Rocky Mountain Dental Group', dental, 'denver-co', 'physician_group', '', 2008, None, False, None),

            # --- LAS VEGAS ---
            ('Sunrise Hospital', hospital, 'las-vegas-nv', 'hospital_system', 'HCA Healthcare', 1958, 690, True, 3.0),
            ('UMC Las Vegas', hospital, 'las-vegas-nv', 'government', '', 1931, 541, True, 3.5),
            ('Vegas Valley Imaging', imaging, 'las-vegas-nv', 'independent', '', 2014, None, True, None),

            # --- ORLANDO ---
            ('AdventHealth Orlando', hospital, 'orlando-fl', 'nonprofit', 'AdventHealth', 1908, 1368, True, 4.0),
            ('Orlando Health ORMC', hospital, 'orlando-fl', 'nonprofit', 'Orlando Health', 1918, 808, True, 3.5),

            # --- SAN DIEGO ---
            ('UC San Diego Medical Center', hospital, 'san-diego-ca', 'nonprofit', 'UC San Diego Health', 1966, 412, True, 4.5),
            ('Scripps Mercy Hospital', hospital, 'san-diego-ca', 'nonprofit', 'Scripps Health', 1890, 511, True, 4.0),
            ('San Diego Imaging Center', imaging, 'san-diego-ca', 'independent', '', 2009, None, True, None),

            # --- NASHVILLE ---
            ('Vanderbilt University Medical Center', hospital, 'nashville-tn', 'nonprofit', 'VUMC', 1874, 1091, True, 4.5),
            ('TriStar Centennial Medical Center', hospital, 'nashville-tn', 'hospital_system', 'HCA Healthcare', 1967, 657, True, 3.5),

            # --- AUSTIN ---
            ('Dell Seton Medical Center', hospital, 'austin-tx', 'nonprofit', 'Ascension Seton', 2017, 211, True, 4.0),
            ('St. Davids Medical Center', hospital, 'austin-tx', 'hospital_system', 'HCA Healthcare', 1924, 350, True, 3.5),
            ('Austin Fertility Center', fertility_clinic, 'austin-tx', 'physician_group', '', 2009, None, False, None),

            # --- CHARLOTTE ---
            ('Atrium Health Carolinas Medical Center', hospital, 'charlotte-nc', 'nonprofit', 'Advocate Health', 1940, 1169, True, 4.0),
            ('Novant Health Presbyterian', hospital, 'charlotte-nc', 'nonprofit', 'Novant Health', 1903, 607, True, 4.0),

            # --- SEATTLE ---
            ('UW Medical Center', hospital, 'seattle-wa', 'nonprofit', 'UW Medicine', 1959, 529, True, 4.5),
            ('Virginia Mason Medical Center', hospital, 'seattle-wa', 'nonprofit', 'CommonSpirit Health', 1920, 336, True, 4.0),
            ('Puget Sound Imaging', imaging, 'seattle-wa', 'independent', '', 2010, None, True, None),

            # --- BOSTON ---
            ('Massachusetts General Hospital', hospital, 'boston-ma', 'nonprofit', 'Mass General Brigham', 1811, 1011, True, 5.0),
            ('Brigham and Womens Hospital', hospital, 'boston-ma', 'nonprofit', 'Mass General Brigham', 1832, 793, True, 5.0),
            ('Boston IVF', fertility_clinic, 'boston-ma', 'physician_group', '', 1986, None, False, None),

            # --- SAN FRANCISCO ---
            ('UCSF Medical Center', hospital, 'san-francisco-ca', 'nonprofit', 'UCSF Health', 1907, 600, True, 5.0),
            ('California Pacific Medical Center', hospital, 'san-francisco-ca', 'nonprofit', 'Sutter Health', 1854, 455, True, 3.5),
            ('Bay Area Fertility Center', fertility_clinic, 'san-francisco-ca', 'physician_group', '', 2003, None, False, None),

            # --- DETROIT ---
            ('Henry Ford Hospital', hospital, 'detroit-mi', 'nonprofit', 'Henry Ford Health', 1915, 877, True, 4.0),
            ('Beaumont Hospital Royal Oak', hospital, 'detroit-mi', 'nonprofit', 'Corewell Health', 1955, 1131, True, 4.0),
            ('Metro Detroit Imaging', imaging, 'detroit-mi', 'independent', '', 2012, None, True, None),
        ]

        for name, ptype, loc_slug, ownership, parent, year, beds, transparent, stars in providers:
            slug = slugify(name)
            loc = Location.objects.get(slug=loc_slug)
            Provider.objects.update_or_create(
                slug=slug,
                defaults={
                    'name': name, 'provider_type': ptype, 'location': loc,
                    'ownership_type': ownership, 'parent_organization': parent,
                    'year_established': year, 'beds': beds,
                    'transparency_compliant': transparent,
                    'cms_star_rating': stars,
                }
            )

        self.stdout.write(f'  {len(providers)} additional providers seeded')

    def seed_pricing(self):
        # Price ranges by procedure and provider type (realistic variance)
        # Format: (procedure_slug, {provider_type_slug: (low, high)})
        pricing_map = {
            'mri-brain': {
                'hospital': (800, 2800),
                'surgery-center': (500, 1500),
                'imaging-center': (200, 650),
            },
            'mri-knee': {
                'hospital': (900, 3000),
                'surgery-center': (500, 1600),
                'imaging-center': (250, 700),
            },
            'ct-scan-abdomen': {
                'hospital': (700, 3500),
                'surgery-center': (400, 1200),
                'imaging-center': (180, 600),
            },
            'x-ray-chest': {
                'hospital': (150, 750),
                'imaging-center': (50, 200),
            },
            'ultrasound-abdominal': {
                'hospital': (200, 1200),
                'imaging-center': (100, 350),
            },
            'knee-replacement': {
                'hospital': (18000, 65000),
                'surgery-center': (15000, 35000),
            },
            'hip-replacement': {
                'hospital': (17000, 60000),
                'surgery-center': (14000, 32000),
            },
            'acl-reconstruction': {
                'hospital': (12000, 45000),
                'surgery-center': (10000, 25000),
            },
            'dental-implant-single': {
                'dental-office': (1500, 5500),
            },
            'root-canal': {
                'dental-office': (700, 1600),
            },
            'dental-crown-porcelain': {
                'dental-office': (800, 1800),
            },
            'wisdom-teeth-removal': {
                'dental-office': (900, 3500),
            },
            'rhinoplasty': {
                'hospital': (6000, 15000),
                'surgery-center': (4000, 12000),
            },
            'breast-augmentation': {
                'hospital': (5500, 12000),
                'surgery-center': (4000, 9000),
            },
            'liposuction': {
                'hospital': (3500, 8000),
                'surgery-center': (2000, 6000),
            },
            'lasik-both-eyes': {
                'eye-center': (1500, 4500),
                'hospital': (2000, 5000),
            },
            'ivf-cycle': {
                'fertility-clinic': (10000, 28000),
                'hospital': (15000, 30000),
            },
            'egg-freezing': {
                'fertility-clinic': (5000, 14000),
            },
            'iui': {
                'fertility-clinic': (500, 2500),
            },
            'fue-hair-transplant': {
                'hair-restoration-clinic': (4000, 14000),
            },
            'botox-full-face': {
                'med-spa': (200, 700),
            },
            'dermal-fillers-lips': {
                'med-spa': (400, 1100),
            },
            'coolsculpting': {
                'med-spa': (600, 1800),
            },
            'gastric-sleeve': {
                'hospital': (10000, 22000),
                'surgery-center': (9000, 18000),
            },
            'gastric-bypass': {
                'hospital': (18000, 35000),
                'surgery-center': (15000, 28000),
            },
        }

        # City-level cost multipliers (reflects real regional variance)
        city_multipliers = {
            'new-york-ny': 1.45,
            'san-francisco-ca': 1.40,
            'boston-ma': 1.35,
            'los-angeles-ca': 1.25,
            'seattle-wa': 1.20,
            'san-diego-ca': 1.15,
            'denver-co': 1.10,
            'chicago-il': 1.10,
            'miami-fl': 1.05,
            'austin-tx': 1.00,
            'dallas-tx': 0.95,
            'houston-tx': 0.95,
            'nashville-tn': 0.95,
            'atlanta-ga': 0.95,
            'charlotte-nc': 0.90,
            'phoenix-az': 0.90,
            'tampa-fl': 0.90,
            'orlando-fl': 0.90,
            'las-vegas-nv': 0.95,
            'detroit-mi': 0.85,
        }

        # Star rating affects pricing (higher rated hospitals tend to charge more)
        def star_multiplier(stars):
            if not stars:
                return 1.0
            if stars >= 5.0:
                return 1.20
            if stars >= 4.0:
                return 1.10
            if stars >= 3.0:
                return 1.0
            return 0.90

        created = 0
        providers = Provider.objects.select_related('provider_type', 'location').all()

        for provider in providers:
            if not provider.provider_type or not provider.location:
                continue

            ptype_slug = provider.provider_type.slug
            city_slug = provider.location.slug
            city_mult = city_multipliers.get(city_slug, 1.0)
            star_mult = star_multiplier(provider.cms_star_rating)

            for proc_slug, type_ranges in pricing_map.items():
                if ptype_slug not in type_ranges:
                    continue

                try:
                    procedure = Procedure.objects.get(slug=proc_slug)
                except Procedure.DoesNotExist:
                    continue

                low, high = type_ranges[ptype_slug]
                base = random.randint(low, high)
                adjusted = int(base * city_mult * star_mult)

                # Add some noise
                adjusted = int(adjusted * random.uniform(0.92, 1.08))

                # Determine confidence based on provider type
                if provider.transparency_compliant and ptype_slug == 'hospital':
                    confidence = 'high'
                    price_type = 'cms_published'
                    source = 'CMS Price Transparency'
                elif ptype_slug == 'imaging-center':
                    confidence = 'medium'
                    price_type = 'provider_website'
                    source = 'Provider Website'
                else:
                    confidence = 'medium'
                    price_type = 'estimated'
                    source = 'Aggregated Estimate'

                # Calculate insured price (typically 40-70% of cash)
                insured_mult = random.uniform(0.40, 0.70)
                insured = int(adjusted * insured_mult)

                # Calculate vs regional median
                regional_providers = PricingRecord.objects.filter(
                    procedure=procedure,
                    provider__location__state=provider.location.state
                )
                # Skip median calc for now, set after all records created

                PricingRecord.objects.update_or_create(
                    provider=provider,
                    procedure=procedure,
                    defaults={
                        'cash_price': adjusted,
                        'insured_price': insured,
                        'price_type': price_type,
                        'confidence': confidence,
                        'source_name': source,
                    }
                )
                created += 1

        self.stdout.write(f'  {created} pricing records created')

        # Now calculate vs_regional_median for all records
        self.stdout.write('  Calculating regional medians...')
        procedures = Procedure.objects.all()
        locations = Location.objects.all()

        for procedure in procedures:
            for location in locations:
                records = PricingRecord.objects.filter(
                    procedure=procedure,
                    provider__location=location
                )
                prices = [r.cash_price for r in records if r.cash_price]
                if len(prices) < 2:
                    continue

                prices.sort()
                n = len(prices)
                if n % 2 == 0:
                    median = (prices[n // 2 - 1] + prices[n // 2]) / 2
                else:
                    median = prices[n // 2]

                if median > 0:
                    for record in records:
                        if record.cash_price:
                            record.vs_regional_median = round(float(record.cash_price) / float(median), 2)
                            record.save(update_fields=['vs_regional_median'])

        self.stdout.write('  Regional medians calculated')
