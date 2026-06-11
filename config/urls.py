from django.contrib import admin
from django.urls import path, include
from django.contrib.sitemaps.views import sitemap, index as sitemap_index
from healthcare.views import robots_txt
from healthcare.sitemaps import ProviderSitemap, ProcedureSitemap, StaticSitemap, MarketPageSitemap

sitemaps = {
    'providers': ProviderSitemap,
    'procedures': ProcedureSitemap,
    'static': StaticSitemap,
    'locations': CitySitemap,
    'market': MarketPageSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', sitemap_index, {'sitemaps': sitemaps, 'sitemap_url_name': 'sitemaps'}),
    path('sitemap-<section>.xml', sitemap, {'sitemaps': sitemaps}, name='sitemaps'),
    path('', include('healthcare.urls')),
]
