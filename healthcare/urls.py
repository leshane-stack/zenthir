from django.urls import path
from . import views, views_cost, views_market, views_billing, views_cash

urlpatterns = [
    path('checkout/', views_billing.create_checkout, name='create_checkout'),
    path('report/success/', views_billing.report_success, name='report_success'),
    path('market/<slug:procedure_slug>/<slug:location_slug>/', views_market.procedure_market, name='procedure_market'),
    path('cash/<slug:procedure_slug>/<slug:location_slug>/', views_cash.cash_procedure_city, name='cash_procedure_city'),
    path('cash/<slug:procedure_slug>/', views_cash.cash_procedure_national, name='cash_procedure_national'),
    path('', views.home, name='home'),
    path('provider/<slug:slug>/', views.provider_detail, name='provider_detail'),
    path('procedure/<slug:slug>/', views.procedure_detail, name='procedure_detail'),
    path('vertical/<slug:slug>/', views.vertical_detail, name='vertical_detail'),
    path('city/<str:state>/<slug:city_slug>/', views.city_detail, name='city_detail'),
    path('cost/<slug:procedure_slug>/<slug:location_slug>/', views_cost.cost_by_city, name='cost_by_city'),
    path('search/', views.search, name='search'),
    path('procedures/', views.procedures_index, name='procedures_index'),
    path('cities/', views.cities_index, name='cities_index'),
    path('provider/<slug:slug>/claim/', views.claim_profile, name='claim_profile'),
    path('methodology/', views.methodology, name='methodology'),
    path('guides/', views.guides_index, name='guides_index'),
    path('guides/no-surprises-act/', views.guide_no_surprises, name='guide_no_surprises'),
    path('guides/good-faith-estimate/', views.guide_good_faith_estimate, name='guide_good_faith_estimate'),
    path('guides/facility-fees/', views.guide_facility_fee, name='guide_facility_fee'),
    path('guides/why-prices-vary/', views.guide_price_variance, name='guide_price_variance'),
    path('overcharged/', views.overcharged, name='overcharged'),
    path('api/procedures/', views.procedure_api, name='procedure_api'),
]
