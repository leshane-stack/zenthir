from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('provider/<slug:slug>/', views.provider_detail, name='provider_detail'),
    path('procedure/<slug:slug>/', views.procedure_detail, name='procedure_detail'),
    path('vertical/<slug:slug>/', views.vertical_detail, name='vertical_detail'),
    path('city/<str:state>/<slug:city_slug>/', views.city_detail, name='city_detail'),
    path('cost/<slug:procedure_slug>/<str:state>/<slug:city_slug>/', views.procedure_city, name='procedure_city'),
    path('search/', views.search, name='search'),
    path('procedures/', views.procedures_index, name='procedures_index'),
    path('cities/', views.cities_index, name='cities_index'),
    path('provider/<slug:slug>/claim/', views.claim_profile, name='claim_profile'),
]
