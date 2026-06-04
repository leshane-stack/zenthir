from django.contrib import admin
from django.urls import path, include
from django.views.static import serve
from healthcare.views import robots_txt
import os

SITEMAP_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static_sitemaps')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', serve, {'document_root': SITEMAP_DIR, 'path': 'sitemap.xml'}),
    path('sitemaps/<path:path>', serve, {'document_root': SITEMAP_DIR}),
    path('', include('healthcare.urls')),
]
