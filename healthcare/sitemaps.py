from django.contrib.sitemaps import Sitemap
from healthcare.models import Provider, Procedure, Location, PricingRecord
from django.db.models import Count


class MarketPageSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.8

    def items(self):
        """Return procedure+city combos with 10+ providers for high-intent procedures"""
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

        combos = PricingRecord.objects.filter(
            procedure__slug__in=consumer_slugs,
        ).values(
            'procedure__slug', 'provider__location__slug'
        ).annotate(
            providers=Count('provider_id', distinct=True)
        ).filter(providers__gte=10)

        return list(combos)

    def location(self, item):
        return f"/market/{item['procedure__slug']}/{item['provider__location__slug']}/"


class ProviderSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.6
    limit = 50000

    def items(self):
        """Only business-type providers with pricing (not individuals at hospitals)"""
        from django.db.models import Count
        shared_addresses = Provider.objects.values('address').annotate(
            addr_count=Count('id')
        ).filter(addr_count__gt=3).values_list('address', flat=True)
        return Provider.objects.filter(
            pricing_records__isnull=False
        ).exclude(
            address__in=shared_addresses
        ).distinct().values_list('slug', flat=True)

    def location(self, slug):
        return f"/provider/{slug}/"


class ProcedureSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.7

    def items(self):
        from django.db.models import Count
        return Procedure.objects.annotate(
            provider_count=Count('pricing_records__provider_id', distinct=True)
        ).filter(provider_count__gte=5).values_list('slug', flat=True)

    def location(self, slug):
        return f"/procedure/{slug}/"


class CitySitemap(Sitemap):
    changefreq = 'monthly'
    priority = 0.7

    def items(self):
        return Location.objects.filter(
            provider__pricing_records__isnull=False
        ).distinct().values_list('state', 'slug')

    def location(self, item):
        return f"/city/{item[0]}/{item[1]}/"


class StaticSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.9

    def items(self):
        return ['home', 'overcharged', 'guides_index']

    def location(self, item):
        if item == 'home':
            return '/'
        elif item == 'overcharged':
            return '/overcharged/'
        elif item == 'guides_index':
            return '/guides/'
        return '/'


# Alias for backwards compatibility
LocationSitemap = CitySitemap
