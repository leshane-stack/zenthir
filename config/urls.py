from django.contrib import admin
from django.urls import path, include
from django.contrib.sitemaps.views import sitemap
from healthcare.sitemaps import ProviderSitemap, ProcedureSitemap, StaticSitemap, LocationSitemap
from healthcare.views import robots_txt

sitemaps = {
    'providers': ProviderSitemap,
    'procedures': ProcedureSitemap,
    'static': StaticSitemap,
    'locations': LocationSitemap,
}

urlpatterns = [
    path('admin/', admin.site.urls),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', sitemap, {'sitemaps': sitemaps}, name='django.contrib.sitemaps.views.sitemap'),
    path('', include('healthcare.urls')),
]
