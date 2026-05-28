from django.contrib.sitemaps import Sitemap
from .models import Provider, Procedure, Location


class ProviderSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7
    limit = 50000

    def items(self):
        return Provider.objects.only('slug').order_by('id')

    def location(self, obj):
        return f'/provider/{obj.slug}/'


class ProcedureSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return Procedure.objects.only('slug').order_by('id')

    def location(self, obj):
        return f'/procedure/{obj.slug}/'


class StaticSitemap(Sitemap):
    changefreq = 'monthly'
    priority = 1.0

    def items(self):
        return [
            '/',
            '/search/',
            '/procedures/',
            '/cities/',
            '/methodology/',
            '/overcharged/',
            '/guides/',
            '/guides/no-surprises-act/',
            '/guides/good-faith-estimate/',
        ]

    def location(self, item):
        return item


class LocationSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.6
    limit = 50000

    def items(self):
        return Location.objects.only('state', 'slug').order_by('id')

    def location(self, obj):
        return f'/city/{obj.state}/{obj.slug}/'
