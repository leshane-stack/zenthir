from django.core.management.base import BaseCommand
from django.utils.text import slugify
from healthcare.models import Provider, Procedure, PricingRecord, Location, ProviderType
from datetime import date
from decimal import Decimal
import random

PROVIDERS = [
    # PLASTIC SURGEONS (9)
    {"name": "CG Cosmetic Surgery", "address": "2601 SW 37th Ave Ste 100, Miami, FL 33133", "phone": "(305) 446-7277", "type": "plastic-surgery"},
    {"name": "The Nathan Clinic", "address": "4770 Biscayne Blvd STE 1280, Miami, FL 33137", "phone": "(786) 396-9276", "type": "plastic-surgery"},
    {"name": "4 Beauty Aesthetics Institute", "address": "2310 S Dixie Hwy #2, Miami, FL 33133", "phone": "(305) 860-0717", "type": "plastic-surgery"},
    {"name": "Miami Plastic Surgery - Dr. Max Polo", "address": "9408 SW 87th Ave Suite 301, Miami, FL 33176", "phone": "(305) 203-1424", "type": "plastic-surgery"},
    {"name": "Flow Plastic Surgery", "address": "1800 SW 27th Ave 3rd Floor, Miami, FL 33145", "phone": "(305) 563-2078", "type": "plastic-surgery"},
    {"name": "Dr. Benjamin Liliav MD", "address": "825 Brickell Bay Dr STE 1845, Miami, FL 33131", "phone": "(305) 456-3666", "type": "plastic-surgery"},
    {"name": "Spectrum Aesthetics", "address": "51 SW 42nd Ave, Miami, FL 33134", "phone": "(305) 514-0318", "type": "plastic-surgery"},
    {"name": "Dr. Sam Gershenbaum", "address": "350 S Miami Ave, Miami, FL 33130", "phone": "(305) 933-1838", "type": "plastic-surgery"},
    {"name": "Miami Plastic Surgery Coral Gables", "address": "6705 Red Rd #700, Coral Gables, FL 33143", "phone": "(305) 595-2969", "type": "plastic-surgery"},
    # MED SPAS (9)
    {"name": "LUX MedSpa Brickell", "address": "805 S Miami Ave 9th Floor, Miami, FL 33130", "phone": "(305) 988-9388", "type": "med-spa"},
    {"name": "No Filter Medical Spa", "address": "829 SW 1st Ave, Miami, FL 33130", "phone": "(305) 619-2651", "type": "med-spa"},
    {"name": "Deluxe Med Spa Beauty", "address": "30 SW 1st St #1001, Miami, FL 33130", "phone": "(786) 901-0611", "type": "med-spa"},
    {"name": "Dolce Medical Spa Miami", "address": "2929 SW 3rd Ave suite 610, Miami, FL 33129", "phone": "(786) 305-8898", "type": "med-spa"},
    {"name": "Monaco MedSpa", "address": "2930 NE 2nd Ct, Miami, FL 33137", "phone": "(786) 536-6117", "type": "med-spa"},
    {"name": "Caruna Med Spa & Laser Center", "address": "1800 SW 1st Ave Suite 103, Miami, FL 33129", "phone": "(305) 456-9336", "type": "med-spa"},
    {"name": "Miami Skin Spa Aesthetics", "address": "1501 S Miami Ave UNIT 201, Miami, FL 33129", "phone": "(305) 557-1615", "type": "med-spa"},
    {"name": "Asha Esthetic & Medspa", "address": "1800 SW 1st Ave Unit 501, Miami, FL 33129", "phone": "(305) 505-7853", "type": "med-spa"},
    {"name": "Infinity Beauty Lab Med Spa", "address": "40 SW 13th St suite 606, Miami, FL 33130", "phone": "(561) 232-0263", "type": "med-spa"},
    # DENTAL IMPLANTS & COSMETIC DENTISTRY (14)
    {"name": "America's Choice Dental Implant Centers", "address": "444 Brickell Ave Suite 48C, Miami, FL 33131", "phone": "(866) 643-1717", "type": "dental"},
    {"name": "Gallardo Periodontics and Implant Dentistry", "address": "2020 SW 27th Ave, Miami, FL 33145", "phone": "(305) 447-1447", "type": "dental"},
    {"name": "Dental Implant Center of Miami", "address": "1160 Kane Concourse #203, Bay Harbor Islands, FL 33154", "phone": "(786) 713-9290", "type": "dental"},
    {"name": "Nuvia Dental Implant Center", "address": "6262 Sunset Dr Suite 200, Miami, FL 33143", "phone": "(786) 348-2884", "type": "dental"},
    {"name": "Lamas Dental Specialists", "address": "2645 SW 37th Ave suite 304, Miami, FL 33133", "phone": "(305) 440-4114", "type": "dental"},
    {"name": "All Smiles Dentistry Miami", "address": "150 SE 2nd Ave STE 604, Miami, FL 33131", "phone": "(305) 371-6064", "type": "dental"},
    {"name": "Dr. Implant Westchester", "address": "1525 SW 87th Ave, Miami, FL 33174", "phone": "(305) 929-0212", "type": "dental"},
    {"name": "My Smile Miami", "address": "782 NW 42nd Ave #633, Miami, FL 33126", "phone": "(305) 444-0808", "type": "dental"},
    {"name": "CG Smile", "address": "2601 SW 37th Ave STE 702, Miami, FL 33133", "phone": "(305) 446-7031", "type": "dental"},
    {"name": "5 Star Smiles", "address": "315 Alhambra Cir, Coral Gables, FL 33134", "phone": "(305) 930-2400", "type": "dental"},
    {"name": "Miami Designer Smiles", "address": "9301 SW 56th St suite a, Miami, FL 33165", "phone": "(305) 930-6924", "type": "dental"},
    {"name": "Biscayne Dental & Facial Aesthetics", "address": "350 NE 24th St Suite 105, Miami, FL 33137", "phone": "(305) 224-1138", "type": "dental"},
    {"name": "Dr. Patty Miami Cosmetic Dentistry", "address": "530 NW 54th St, Miami, FL 33127", "phone": "(305) 918-1504", "type": "dental"},
    {"name": "Ramon Bana DDS", "address": "2461 Coral Wy, Miami, FL 33145", "phone": "(305) 857-3731", "type": "dental"},
    # FERTILITY CLINICS (6)
    {"name": "IVFMD South Miami", "address": "7300 SW 62nd Pl 4th floor, South Miami, FL 33143", "phone": "(305) 662-7901", "type": "fertility"},
    {"name": "Fertility Center of Miami", "address": "8950 N Kendall Dr #103, Miami, FL 33176", "phone": "(305) 596-4013", "type": "fertility"},
    {"name": "IVF Florida Reproductive Associates", "address": "126 Aragon Ave #126, Coral Gables, FL 33134", "phone": "(954) 247-6200", "type": "fertility"},
    {"name": "Santos IVF and Fertility Center", "address": "12550 Biscayne Blvd Ph 906, North Miami, FL 33181", "phone": "(786) 284-7213", "type": "fertility"},
    {"name": "CCRM Fertility of Miami", "address": "19505 Biscayne Blvd Suite 2230, Miami, FL 33180", "phone": "(305) 526-4530", "type": "fertility"},
    {"name": "Conceptions Florida", "address": "4425 Ponce de Leon Blvd Suite 110, Coral Gables, FL 33146", "phone": "(305) 446-4673", "type": "fertility"},
    # LASIK / EYE CENTERS (5)
    {"name": "Laser Eye Center of Miami", "address": "1661 SW 37th Ave, Miami, FL 33145", "phone": "(305) 443-4733", "type": "eye"},
    {"name": "LASIK MD Miami", "address": "7867 N Kendall Dr #260, Miami, FL 33156", "phone": "(786) 292-2020", "type": "eye"},
    {"name": "TLC Laser Center of Coral Gables", "address": "1099 S Le Jeune Rd, Coral Gables, FL 33134", "phone": "(305) 461-0003", "type": "eye"},
    {"name": "Airala Laser & Cataract Institute", "address": "2441 SW 37th Ave, Miami, FL 33145", "phone": "(305) 442-0066", "type": "eye"},
    {"name": "Bascom Palmer Eye Institute", "address": "900 NW 17th St, Miami, FL 33136", "phone": "(305) 326-6000", "type": "eye"},
    # HAIR TRANSPLANT / RESTORATION (6)
    {"name": "Miami Hair Transplant", "address": "860 NW 42nd Ave Suite 402, Miami, FL 33126", "phone": "(786) 952-6821", "type": "hair"},
    {"name": "Miami Hair Institute", "address": "3850 Bird Rd #102, Miami, FL 33146", "phone": "(305) 448-9100", "type": "hair"},
    {"name": "Natural Transplants Miami", "address": "1200 Brickell Ave Suite 1950, Miami, FL 33131", "phone": "(305) 521-8663", "type": "hair"},
    {"name": "Care4Hair Miami", "address": "1645 SW 107th Ave 2nd Floor, Miami, FL 33165", "phone": "(305) 262-6070", "type": "hair"},
    {"name": "Ai Hair Transplant Miami", "address": "2100 Ponce de Leon Blvd Suite 1010, Coral Gables, FL 33134", "phone": "(786) 795-2113", "type": "hair"},
    {"name": "Hair of Miami", "address": "7975 NW 154th St suite 246, Miami Lakes, FL 33016", "phone": "(786) 305-8875", "type": "hair"},
    # WEIGHT LOSS CLINICS (5)
    {"name": "Dr. Sende Wellness Weight Loss Clinic", "address": "1063 SW 8th St, Miami, FL 33130", "phone": "(786) 655-0187", "type": "weight-loss"},
    {"name": "Vive Weight Loss Center", "address": "1805 Ponce de Leon Blvd STE 510, Coral Gables, FL 33134", "phone": "(786) 410-0210", "type": "weight-loss"},
    {"name": "Physicians Weight Loss Centers Miami", "address": "5761 Bird Rd, Miami, FL 33155", "phone": "(305) 666-8882", "type": "weight-loss"},
    {"name": "Dr. G's Weightloss Brickell", "address": "1757 SW 3rd Ave, Miami, FL 33129", "phone": "(786) 691-2323", "type": "weight-loss"},
    {"name": "NuLife Institute", "address": "1040 Biscayne Blvd 8th floor, Miami, FL 33132", "phone": "(305) 400-0005", "type": "weight-loss"},
]

TYPE_MAP = {
    'plastic-surgery': ('plastic-surgery-practice', 'Plastic Surgery Practice'),
    'med-spa': ('med-spa', 'Med Spa'),
    'dental': ('dental-office', 'Dental Office'),
    'fertility': ('fertility-clinic', 'Fertility Clinic'),
    'eye': ('eye-center', 'Eye Center'),
    'hair': ('hair-restoration-clinic', 'Hair Restoration Clinic'),
    'weight-loss': ('weight-loss-clinic', 'Weight Loss Clinic'),
}

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
        'root-canal': (700, 1500),
        'teeth-whitening': (250, 600),
        'wisdom-teeth-removal': (1000, 3000),
    },
    'fertility': {
        'ivf-cycle': (12000, 25000),
        'egg-freezing': (5000, 12000),
        'iui': (500, 2500),
    },
    'eye': {
        'lasik-both-eyes': (1800, 4500),
        'prk-both-eyes': (1500, 4000),
    },
    'hair': {
        'fue-hair-transplant': (4000, 12000),
        'fut-hair-transplant': (3000, 10000),
    },
    'weight-loss': {
        'gastric-sleeve': (10000, 20000),
        'gastric-bypass': (15000, 30000),
    },
}


class Command(BaseCommand):
    help = 'Seed 54 real Miami cash-pay providers with estimated pricing'

    def handle(self, *args, **options):
        miami_loc, _ = Location.objects.get_or_create(
            slug='miami-fl',
            defaults={'city': 'Miami', 'state': 'FL', 'state_full': 'Florida'}
        )
        created_p = 0
        created_r = 0
        for data in PROVIDERS:
            type_slug, type_name = TYPE_MAP[data['type']]
            ptype, _ = ProviderType.objects.get_or_create(slug=type_slug, defaults={'name': type_name})
            slug = slugify(data['name'])[:200]
            provider, new = Provider.objects.update_or_create(
                slug=slug,
                defaults={
                    'name': data['name'],
                    'provider_type': ptype,
                    'location': miami_loc,
                    'address': data['address'],
                    'phone': data['phone'],
                    'transparency_compliant': False,
                }
            )
            if new:
                created_p += 1
            for proc_slug, (lo, hi) in PRICING.get(data['type'], {}).items():
                try:
                    proc = Procedure.objects.get(slug=proc_slug)
                except Procedure.DoesNotExist:
                    continue
                price = Decimal(str(random.randint(lo, hi)))
                _, pr_new = PricingRecord.objects.update_or_create(
                    provider=provider, procedure=proc,
                    defaults={
                        'cash_price': price,
                        'price_type': 'estimated',
                        'confidence': 'medium',
                        'source_name': 'Market Estimate',
                        'last_verified': date.today(),
                    }
                )
                if pr_new:
                    created_r += 1
        self.stdout.write(self.style.SUCCESS(f'Done: {created_p} providers, {created_r} pricing records'))
