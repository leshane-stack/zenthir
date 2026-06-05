from django.contrib import admin
from django.urls import path, include
from django.views.generic.base import RedirectView
from healthcare.views import robots_txt

urlpatterns = [
    path('admin/', admin.site.urls),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', RedirectView.as_view(url='/static/sitemaps/sitemap.xml', permanent=True)),
    path('', include('healthcare.urls')),
]
