from django.contrib import admin
from django.urls import path, include
from django.views.static import serve
from django.conf import settings
from healthcare.views import robots_txt
import os

SITEMAP_DIR = os.path.join(settings.BASE_DIR, 'static_src', 'sitemaps')

urlpatterns = [
    path('admin/', admin.site.urls),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', serve, {'document_root': SITEMAP_DIR, 'path': 'sitemap.xml'}),
    path('', include('healthcare.urls')),
]
