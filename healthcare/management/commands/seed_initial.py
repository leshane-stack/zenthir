from django.core.management.base import BaseCommand
from healthcare.models import (
    Vertical, Location, ProviderType, Provider, Procedure, PricingRecord
)
from django.utils.text import slugify


class Command(BaseCommand):
    help = 'Seed initial verticals, procedures, locations, and sample providers'

    def handle(self, *args, **options):
        self.seed_verticals()
        self.seed_provider_types()
        self.seed_locations()
        self.seed_procedures()
        self.seed_sample_providers()
        self.stdout.write(self.style.SUCCESS('Initial seed complete.'))

    def seed_verticals(self):
        verticals = [
            # Tier 1 — Launch
            ('Plastic Surgery', 'Cosmetic and reconstructive surgery pricing and provider intelligence.', 1, 1),
            ('Dental', 'Dental procedure pricing from implants to orthodontics.', 1, 2),
            ('Hair Transplants', 'Hair restoration procedure pricing and surgeon credentials.', 1, 3),
            ('Fertility & IVF', 'IVF, egg freezing, and reproductive medicine costs.', 1, 4),
            ('Med Spas & Aesthetics', 'Botox, fillers, laser treatments, and aesthetic procedure pricing.', 1, 5),
            ('LASIK & Vision', 'Laser eye surgery and vision correction procedure costs.', 1, 6),
            # Tier 2 — Fast follow
            ('Hospitals & Imaging', 'Hospital pricing, MRI, CT scans, X-rays, and imaging costs.', 2, 7),
            ('Orthopedics', 'Joint replacement, sports medicine, and orthopedic surgery costs.', 2, 8),
            ('Urgent Care', 'Walk-in clinic and urgent care visit pricing.', 2, 9),
            ('Bariatric Surgery', 'Weight loss surgery pricing and surgeon credentials.', 2, 10),
            # Tier 3 — Expansion
            ('Mental Health', 'Therapy, psychiatry, and mental health service costs.', 3, 11),
            ('Physical Therapy', 'PT session pricing and rehabilitation costs.', 3, 12),
            ('Senior Care', 'Assisted living, nursing home, and elder care costs.', 3, 13),
            ('Womens Health', 'OB-GYN, mammography, and womens health procedure pricing.', 3, 14),
        ]
        for name, desc, tier, order in verticals:
            Vertical.objects.update_or_create(
                slug=slugify(name),
                defaults={'name': name, 'description': desc, 'tier': tier, 'sort_order': order}
            )
        self.stdout.write(f'  {len(verticals)} verticals seeded')

    def seed_provider_types(self):
        types = [
            'Hospital', 'Surgery Center', 'Private Practice', 'Imaging Center',
            'Dental Office', 'Med Spa', 'Fertility Clinic', 'Urgent Care',
            'Rehabilitation Center', 'Eye Center', 'Hair Restoration Clinic',
        ]
        for t in types:
            ProviderType.objects.update_or_create(slug=slugify(t), defaults={'name': t})
        self.stdout.write(f'  {len(types)} provider types seeded')

    def seed_locations(self):
        cities = [
            ('Miami', 'FL', 'Florida', 'South Florida', 25.7617, -80.1918, 470000),
            ('Houston', 'TX', 'Texas', 'Houston Metro', 29.7604, -95.3698, 2300000),
            ('Los Angeles', 'CA', 'California', 'Greater Los Angeles', 34.0522, -118.2437, 3900000),
            ('New York', 'NY', 'New York', 'NYC Metro', 40.7128, -74.0060, 8300000),
            ('Chicago', 'IL', 'Illinois', 'Chicagoland', 41.8781, -87.6298, 2700000),
            ('Dallas', 'TX', 'Texas', 'DFW Metro', 32.7767, -96.7970, 1300000),
            ('Atlanta', 'GA', 'Georgia', 'Metro Atlanta', 33.7490, -84.3880, 500000),
            ('Phoenix', 'AZ', 'Arizona', 'Phoenix Metro', 33.4484, -112.0740, 1600000),
            ('Tampa', 'FL', 'Florida', 'Tampa Bay', 27.9506, -82.4572, 400000),
            ('Denver', 'CO', 'Colorado', 'Denver Metro', 39.7392, -104.9903, 715000),
            ('Las Vegas', 'NV', 'Nevada', 'Las Vegas Valley', 36.1699, -115.1398, 640000),
            ('Orlando', 'FL', 'Florida', 'Central Florida', 28.5383, -81.3792, 300000),
            ('San Diego', 'CA', 'California', 'San Diego County', 32.7157, -117.1611, 1400000),
            ('Nashville', 'TN', 'Tennessee', 'Nashville Metro', 36.1627, -86.7816, 690000),
            ('Austin', 'TX', 'Texas', 'Austin Metro', 30.2672, -97.7431, 960000),
            ('Charlotte', 'NC', 'North Carolina', 'Charlotte Metro', 35.2271, -80.8431, 870000),
            ('Seattle', 'WA', 'Washington', 'Seattle Metro', 47.6062, -122.3321, 750000),
            ('Boston', 'MA', 'Massachusetts', 'Greater Boston', 42.3601, -71.0589, 690000),
            ('San Francisco', 'CA', 'California', 'SF Bay Area', 37.7749, -122.4194, 870000),
            ('Detroit', 'MI', 'Michigan', 'Metro Detroit', 42.3314, -83.0458, 640000),
        ]
        for city, state, state_full, metro, lat, lng, pop in cities:
            Location.objects.update_or_create(
                slug=slugify(f'{city}-{state}'),
                defaults={
                    'city': city, 'state': state, 'state_full': state_full,
                    'metro_area': metro, 'latitude': lat, 'longitude': lng,
                    'population': pop
                }
            )
        self.stdout.write(f'  {len(cities)} locations seeded')

    def seed_procedures(self):
        imaging = Vertical.objects.filter(slug='hospitals-imaging').first()
        dental = Vertical.objects.filter(slug='dental').first()
        plastic = Vertical.objects.filter(slug='plastic-surgery').first()
        lasik = Vertical.objects.filter(slug='lasik-vision').first()
        fertility = Vertical.objects.filter(slug='fertility-ivf').first()
        hair = Vertical.objects.filter(slug='hair-transplants').first()
        medspa = Vertical.objects.filter(slug='med-spas-aesthetics').first()
        ortho = Vertical.objects.filter(slug='orthopedics').first()
        bariatric = Vertical.objects.filter(slug='bariatric-surgery').first()

        procedures = [
            # Imaging
            ('MRI (Brain)', 'Magnetic resonance imaging of the brain without contrast.', 'Imaging', '70551', True, True, 250, 450, 2500, [imaging]),
            ('MRI (Knee)', 'Magnetic resonance imaging of the knee without contrast.', 'Imaging', '73721', True, True, 250, 500, 3000, [imaging]),
            ('CT Scan (Abdomen)', 'Computed tomography of abdomen and pelvis with contrast.', 'Imaging', '74177', True, True, 200, 550, 4000, [imaging]),
            ('X-Ray (Chest)', 'Standard chest X-ray, two views.', 'Imaging', '71046', True, True, 50, 150, 750, [imaging]),
            ('Ultrasound (Abdominal)', 'Abdominal ultrasound, complete.', 'Imaging', '76700', True, True, 100, 300, 1500, [imaging]),
            # Dental
            ('Dental Implant (Single)', 'Single tooth dental implant with abutment and crown.', 'Dental', 'D6010', True, True, 1500, 3500, 6500, [dental]),
            ('Root Canal', 'Endodontic therapy on a molar.', 'Dental', 'D3330', True, True, 700, 1100, 1800, [dental]),
            ('Dental Crown (Porcelain)', 'Porcelain/ceramic crown, single tooth.', 'Dental', 'D2740', True, True, 800, 1200, 2000, [dental]),
            ('Teeth Whitening', 'In-office professional teeth whitening.', 'Dental', 'D9972', True, True, 200, 500, 1000, [dental, medspa]),
            ('Wisdom Teeth Removal', 'Extraction of 4 impacted wisdom teeth.', 'Dental', 'D7240', True, True, 800, 1800, 4000, [dental]),
            # Plastic Surgery
            ('Rhinoplasty', 'Cosmetic nose reshaping surgery.', 'Surgery', '30400', True, True, 3000, 7500, 15000, [plastic]),
            ('Breast Augmentation', 'Breast augmentation with silicone implants.', 'Surgery', '19325', True, True, 4000, 6500, 12000, [plastic]),
            ('Liposuction', 'Liposuction, single area.', 'Surgery', '15876', True, True, 2000, 4000, 8000, [plastic]),
            ('Blepharoplasty', 'Eyelid surgery, upper and lower.', 'Surgery', '15822', True, True, 2000, 4500, 8000, [plastic]),
            ('Facelift', 'Rhytidectomy, full facelift.', 'Surgery', '15828', True, True, 7000, 12000, 25000, [plastic]),
            # LASIK
            ('LASIK (Both Eyes)', 'Laser-assisted in-situ keratomileusis, bilateral.', 'Vision', '65760', True, True, 1500, 2500, 5000, [lasik]),
            ('PRK (Both Eyes)', 'Photorefractive keratectomy, bilateral.', 'Vision', '65760', True, True, 1500, 2200, 4500, [lasik]),
            # Fertility
            ('IVF Cycle', 'Single in-vitro fertilization cycle including medications.', 'Reproductive', '', True, True, 10000, 15000, 30000, [fertility]),
            ('Egg Freezing', 'Oocyte cryopreservation cycle.', 'Reproductive', '', True, True, 5000, 8000, 15000, [fertility]),
            ('IUI', 'Intrauterine insemination procedure.', 'Reproductive', '', True, True, 500, 1000, 3000, [fertility]),
            # Hair
            ('FUE Hair Transplant', 'Follicular unit extraction, 2000 grafts.', 'Surgery', '', True, True, 4000, 8000, 15000, [hair]),
            ('FUT Hair Transplant', 'Follicular unit transplantation, strip method.', 'Surgery', '', True, True, 3000, 6000, 12000, [hair]),
            # Med Spa
            ('Botox (Full Face)', 'Botulinum toxin injections, full face treatment.', 'Aesthetic', '', True, True, 200, 400, 800, [medspa]),
            ('Dermal Fillers (Lips)', 'Hyaluronic acid filler, lip augmentation.', 'Aesthetic', '', True, True, 400, 700, 1200, [medspa]),
            ('CoolSculpting', 'Cryolipolysis fat reduction, single area.', 'Aesthetic', '', True, True, 600, 1000, 2000, [medspa]),
            # Orthopedics
            ('Knee Replacement', 'Total knee arthroplasty.', 'Surgery', '27447', True, True, 15000, 35000, 70000, [ortho]),
            ('Hip Replacement', 'Total hip arthroplasty.', 'Surgery', '27130', True, True, 15000, 32000, 65000, [ortho]),
            ('ACL Reconstruction', 'Anterior cruciate ligament reconstruction.', 'Surgery', '29888', True, True, 10000, 20000, 50000, [ortho]),
            # Bariatric
            ('Gastric Sleeve', 'Laparoscopic sleeve gastrectomy.', 'Surgery', '43775', True, True, 9000, 15000, 25000, [bariatric]),
            ('Gastric Bypass', 'Roux-en-Y gastric bypass.', 'Surgery', '43644', True, True, 15000, 23000, 35000, [bariatric]),
        ]

        for name, desc, cat, cpt, elective, cash_common, low, median, high, verts in procedures:
            proc, _ = Procedure.objects.update_or_create(
                slug=slugify(name),
                defaults={
                    'name': name, 'description': desc, 'category': cat,
                    'cpt_code': cpt, 'is_elective': elective,
                    'is_cash_pay_common': cash_common,
                    'cost_range_low': low, 'national_median_cost': median,
                    'cost_range_high': high,
                }
            )
            if verts:
                proc.verticals.set([v for v in verts if v])

        self.stdout.write(f'  {len(procedures)} procedures seeded')

    def seed_sample_providers(self):
        hospital = ProviderType.objects.get(slug='hospital')
        surgery_center = ProviderType.objects.get(slug='surgery-center')
        imaging = ProviderType.objects.get(slug='imaging-center')
        dental_office = ProviderType.objects.get(slug='dental-office')

        miami = Location.objects.get(slug='miami-fl')
        houston = Location.objects.get(slug='houston-tx')
        la = Location.objects.get(slug='los-angeles-ca')

        providers_data = [
            # Miami
            ('Jackson Memorial Hospital', hospital, miami, 'nonprofit', '', 1918, 1550, True, 4.0,
             'Major academic medical center and Level 1 trauma center.'),
            ('Baptist Health South Florida', hospital, miami, 'nonprofit', '', 1960, 728, True, 3.5,
             'Large nonprofit health system serving South Florida.'),
            ('Miami Imaging Center', imaging, miami, 'independent', '', 2005, None, True, None,
             'Independent imaging center offering competitive MRI and CT pricing.'),
            ('South Beach Dental', dental_office, miami, 'independent', '', 2010, None, False, None,
             'Private dental practice specializing in cosmetic dentistry.'),
            # Houston
            ('Houston Methodist Hospital', hospital, houston, 'nonprofit', '', 1919, 1000, True, 4.5,
             'Top-ranked hospital and academic medical center.'),
            ('Memorial Hermann', hospital, houston, 'nonprofit', 'Memorial Hermann Health System', 1925, 800, True, 4.0,
             'Major hospital system serving the greater Houston area.'),
            ('Texas Medical Center Imaging', imaging, houston, 'independent', '', 2008, None, True, None,
             'Outpatient imaging center in the Texas Medical Center area.'),
            # LA
            ('Cedars-Sinai Medical Center', hospital, la, 'nonprofit', '', 1902, 886, True, 4.5,
             'Premier academic medical center in Los Angeles.'),
            ('UCLA Medical Center', hospital, la, 'nonprofit', 'UCLA Health', 1955, 520, True, 5.0,
             'Top-ranked academic medical center and research institution.'),
            ('LA Outpatient Surgery Center', surgery_center, la, 'physician_group', '', 2012, None, True, None,
             'Physician-owned ambulatory surgery center offering competitive pricing.'),
        ]

        mri_brain = Procedure.objects.get(slug='mri-brain')
        mri_knee = Procedure.objects.get(slug='mri-knee')
        ct_abdomen = Procedure.objects.get(slug='ct-scan-abdomen')
        knee_replacement = Procedure.objects.get(slug='knee-replacement')

        for name, ptype, loc, ownership, parent, year, beds, transparent, stars, summary in providers_data:
            provider, _ = Provider.objects.update_or_create(
                slug=slugify(name),
                defaults={
                    'name': name, 'provider_type': ptype, 'location': loc,
                    'ownership_type': ownership, 'parent_organization': parent,
                    'year_established': year, 'beds': beds,
                    'transparency_compliant': transparent,
                    'cms_star_rating': stars, 'summary_line': summary,
                }
            )

        # Sample pricing records
        import random
        hospitals = Provider.objects.filter(provider_type__slug='hospital')
        imaging_centers = Provider.objects.filter(provider_type__slug='imaging-center')

        for provider in hospitals:
            for proc, base_low, base_high in [
                (mri_brain, 300, 2200),
                (mri_knee, 350, 2500),
                (ct_abdomen, 250, 3500),
                (knee_replacement, 18000, 55000),
            ]:
                cash = random.randint(base_low, base_high)
                PricingRecord.objects.update_or_create(
                    provider=provider, procedure=proc,
                    defaults={
                        'cash_price': cash,
                        'insured_price': int(cash * 0.6),
                        'price_type': 'cms_published',
                        'confidence': 'high',
                        'source_name': 'CMS Price Transparency',
                    }
                )

        for provider in imaging_centers:
            for proc, base_low, base_high in [
                (mri_brain, 200, 800),
                (mri_knee, 250, 900),
                (ct_abdomen, 180, 700),
            ]:
                cash = random.randint(base_low, base_high)
                PricingRecord.objects.update_or_create(
                    provider=provider, procedure=proc,
                    defaults={
                        'cash_price': cash,
                        'insured_price': int(cash * 0.7),
                        'price_type': 'provider_website',
                        'confidence': 'medium',
                        'source_name': 'Provider Website',
                    }
                )

        self.stdout.write(f'  {Provider.objects.count()} providers seeded with pricing')
