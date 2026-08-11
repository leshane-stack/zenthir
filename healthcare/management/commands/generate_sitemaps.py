import os
from django.core.management.base import BaseCommand
from django.conf import settings
from healthcare.models import Provider, Procedure, Location, PricingRecord
from django.db.models import Count
from healthcare.sitemap_utils import is_individual_slug


class Command(BaseCommand):
    help = 'Generate static sitemap XML files into STATIC_ROOT/sitemaps'

    def handle(self, *args, **options):
        output_dir = os.path.join(settings.BASE_DIR, 'static_src', 'sitemaps')
        os.makedirs(output_dir, exist_ok=True)

        base_url = 'https://zenthir.com'
        sm_prefix = f'{base_url}/static/sitemaps'

        self.stdout.write('Generating provider sitemaps...')
        all_slugs = list(Provider.objects.filter(
            pricing_records__isnull=False
        ).distinct().values_list('slug', flat=True))
        # Exclude individual practitioners — their pages should not be actively
        # submitted to Google (conservative name-based classifier).
        providers = [s for s in all_slugs if not is_individual_slug(s)]
        dropped = len(all_slugs) - len(providers)
        self.stdout.write(f'  {len(providers):,} business providers with pricing '
                          f'({dropped:,} individuals excluded)')

        provider_files = []
        chunk_size = 50000  # sitemaps.org hard limit is 50,000 URLs per file
        for i in range(0, len(providers), chunk_size):
            chunk = providers[i:i + chunk_size]
            page = (i // chunk_size) + 1
            filename = f'sitemap-providers-{page}.xml'
            with open(os.path.join(output_dir, filename), 'w') as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                f.write('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
                for slug in chunk:
                    f.write(f'<url><loc>{base_url}/provider/{slug}/</loc><changefreq>monthly</changefreq><priority>0.6</priority></url>\n')
                f.write('</urlset>\n')
            provider_files.append(filename)
        self.stdout.write(f'  {len(provider_files)} provider files')

        procedures = list(Procedure.objects.filter(
            pricing_records__isnull=False
        ).distinct().values_list('slug', flat=True))
        with open(os.path.join(output_dir, 'sitemap-procedures.xml'), 'w') as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
            for slug in procedures:
                f.write(f'<url><loc>{base_url}/procedure/{slug}/</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>\n')
            f.write('</urlset>\n')
        self.stdout.write(f'  {len(procedures):,} procedures')

        # Only cities with at least 5 business (non-individual) providers that
        # have pricing data. Thin/empty city pages are low value, render noindex,
        # and waste crawl budget, so they are kept out of the sitemap.
        from django.db.models import Q
        LOCATION_MIN_BUSINESS = 5
        locations = list(Location.objects.annotate(
            biz=Count('provider', filter=Q(
                provider__is_individual=False,
                provider__pricing_records__isnull=False,
            ), distinct=True)
        ).filter(biz__gte=LOCATION_MIN_BUSINESS).values_list('state', 'slug'))
        with open(os.path.join(output_dir, 'sitemap-locations.xml'), 'w') as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
            for state, slug in locations:
                f.write(f'<url><loc>{base_url}/city/{state}/{slug}/</loc><changefreq>monthly</changefreq><priority>0.7</priority></url>\n')
            f.write('</urlset>\n')
        self.stdout.write(f'  {len(locations):,} locations')

        consumer_slugs = [
            'mri-scan-of-brain-before-and-after-contrast',
            'mri-scan-of-brain-without-contrast',
            'mri-scan-of-leg-joint-without-contrast',
            'mri-scan-of-lower-spinal-canal-without-contrast',
            'ct-scan-head-or-brain-without-contrast',
            'ct-scan-of-abdomen-and-pelvis-with-contrast',
            'diagnostic-mammography-of-both-breasts',
            'colonoscopy',
            'biopsy-of-large-bowel-using-a-flexible-endoscope',
            'established-patient-office-or-other-outpatient-visit-with-moderate-level-of-deci',
            'established-patient-office-or-other-outpatient-visit-with-low-level-od-decision',
            'complete-blood-cell-count-red-cells-white-blood-cell-platelets-automated-te',
            'blood-test-comprehensive-group-of-blood-chemicals',
            'routine-electrocardiogram-ecg-using-at-least-12-leads-with-interpretation-and',
            'psychotherapy-45-minutes',
            'psychotherapy-30-minutes',
            'removal-of-cataract-with-insertion-of-prosthetic-lens',
        ]
        # Only procedure+city pages backed by at least this many providers.
        # Long-procedure-name / tiny-city combos below the threshold are low value
        # and are kept out of the sitemap.
        MARKET_MIN_PROVIDERS = 5
        combos = list(PricingRecord.objects.filter(
            procedure__slug__in=consumer_slugs,
        ).values(
            'procedure__slug', 'provider__location__slug'
        ).annotate(
            providers=Count('provider_id', distinct=True)
        ).filter(providers__gte=MARKET_MIN_PROVIDERS))

        market_files = []
        for i in range(0, len(combos), chunk_size):
            chunk = combos[i:i + chunk_size]
            page = (i // chunk_size) + 1
            filename = f'sitemap-market-{page}.xml'
            with open(os.path.join(output_dir, filename), 'w') as f:
                f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
                f.write('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
                for c in chunk:
                    f.write(f'<url><loc>{base_url}/market/{c["procedure__slug"]}/{c["provider__location__slug"]}/</loc><changefreq>monthly</changefreq><priority>0.8</priority></url>\n')
                f.write('</urlset>\n')
            market_files.append(filename)
        self.stdout.write(f'  {len(combos):,} market pages in {len(market_files)} files')

        with open(os.path.join(output_dir, 'sitemap-static.xml'), 'w') as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
            for path in ['/', '/overcharged/', '/guides/', '/guides/facility-fees/', '/guides/good-faith-estimate/', '/guides/no-surprises-act/', '/guides/why-prices-vary/']:
                f.write(f'<url><loc>{base_url}{path}</loc><changefreq>weekly</changefreq><priority>0.9</priority></url>\n')
            f.write('</urlset>\n')

        with open(os.path.join(output_dir, 'sitemap.xml'), 'w') as f:
            f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            f.write('<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n')
            for pf in provider_files:
                f.write(f'<sitemap><loc>{sm_prefix}/{pf}</loc></sitemap>\n')
            f.write(f'<sitemap><loc>{sm_prefix}/sitemap-procedures.xml</loc></sitemap>\n')
            f.write(f'<sitemap><loc>{sm_prefix}/sitemap-locations.xml</loc></sitemap>\n')
            for mf in market_files:
                f.write(f'<sitemap><loc>{sm_prefix}/{mf}</loc></sitemap>\n')
            f.write(f'<sitemap><loc>{sm_prefix}/sitemap-static.xml</loc></sitemap>\n')
            f.write('</sitemapindex>\n')

        self.stdout.write(self.style.SUCCESS(f'Done! Files in {output_dir}'))
