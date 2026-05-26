from django.contrib.sitemaps import Sitemap
from .models import Provider, Procedure, Location


class ProviderSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.8

    def items(self):
        return Provider.objects.all()

    def location(self, obj):
        return f'/provider/{obj.slug}/'

    def lastmod(self, obj):
        return obj.updated_at


class ProcedureSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        return Procedure.objects.all()

    def location(self, obj):
        return f'/procedure/{obj.slug}/'


class StaticSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 1.0

    def items(self):
        return ['/']

    def location(self, item):
        return item


class LocationSitemap(Sitemap):
    changefreq = 'weekly'
    priority = 0.7

    def items(self):
        return Location.objects.all()

    def location(self, obj):
        return f'/city/{obj.state}/{obj.slug}/'
