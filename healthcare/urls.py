from django.urls import path
from . import views, views_cost, views_market, views_billing, views_cash, views_botox, views_dental, views_fertility

urlpatterns = [
    path('checkout/', views_billing.create_checkout, name='create_checkout'),
    path('report/success/', views_billing.report_success, name='report_success'),

    # --- Botox/Miami test wedge (MUST precede the generic cash patterns) ---
    # Explicit facet routes come BEFORE the generic type-facet route so best/
    # cheapest aren't captured as a <type_slug>.
    path('cash/botox/miami-fl/report/', views_botox.botox_miami_report, name='botox_miami_report'),
    path('cash/botox/miami-fl/best/', views_botox.botox_miami_best, name='botox_miami_best'),
    path('cash/botox/miami-fl/cheapest/', views_botox.botox_miami_cheapest, name='botox_miami_cheapest'),
    path('cash/botox/miami-fl/', views_botox.botox_miami_hub, name='botox_miami_hub'),
    path('cash/botox/', views_botox.botox_national, name='botox_national'),

    # --- Dental-implant/Miami wedge (explicit routes BEFORE the generic type-facet
    #     route below, so report/best/cheapest aren't captured as a <type_slug>) ---
    path('cash/dental-implant/miami-fl/report/', views_dental.dental_miami_report, name='dental_miami_report'),
    path('cash/dental-implant/miami-fl/best/', views_dental.dental_miami_best, name='dental_miami_best'),
    path('cash/dental-implant/miami-fl/cheapest/', views_dental.dental_miami_cheapest, name='dental_miami_cheapest'),
    path('cash/dental-implant/miami-fl/', views_dental.dental_miami_hub, name='dental_miami_hub'),
    path('cash/dental-implant/', views_dental.dental_national, name='dental_national'),

    # --- Fertility/Miami wedge cluster (IVF, egg freezing, IUI). Explicit routes
    #     BEFORE the generic cash + type-facet routes; egg-freezing/iui intercept
    #     their generic cash pages for Miami + national (an upgrade to the wedge). ---
    path('cash/fertility/miami-fl/', views_fertility.cluster_hub, name='fertility_cluster'),
    path('cash/ivf/miami-fl/report/', views_fertility.ivf_report, name='ivf_report'),
    path('cash/ivf/miami-fl/best/', views_fertility.ivf_best, name='ivf_best'),
    path('cash/ivf/miami-fl/cheapest/', views_fertility.proc_cheapest, {'key': 'ivf'}, name='ivf_cheapest'),
    path('cash/ivf/miami-fl/', views_fertility.proc_hub, {'key': 'ivf'}, name='ivf_hub'),
    path('cash/ivf/', views_fertility.proc_national, {'key': 'ivf'}, name='ivf_national'),
    path('cash/egg-freezing/miami-fl/cheapest/', views_fertility.proc_cheapest, {'key': 'egg-freezing'}, name='egg_cheapest'),
    path('cash/egg-freezing/miami-fl/', views_fertility.proc_hub, {'key': 'egg-freezing'}, name='egg_hub'),
    path('cash/egg-freezing/', views_fertility.proc_national, {'key': 'egg-freezing'}, name='egg_national'),
    path('cash/iui/miami-fl/cheapest/', views_fertility.proc_cheapest, {'key': 'iui'}, name='iui_cheapest'),
    path('cash/iui/miami-fl/', views_fertility.proc_hub, {'key': 'iui'}, name='iui_hub'),
    path('cash/iui/', views_fertility.proc_national, {'key': 'iui'}, name='iui_national'),

    # Reusable provider-type facet: /cash/<hub>/<city>/<type>/ (Botox+Miami wired today).
    path('cash/<slug:procedure_hub_slug>/<slug:city_slug>/<slug:type_slug>/',
         views_botox.botox_type_filter, name='botox_type_filter'),
    path('wedge/lead/', views_botox.capture_lead, name='wedge_capture_lead'),
    path('wedge/notify/', views_botox.capture_notify, name='wedge_capture_notify'),
    path('wedge/event/', views_botox.track_event, name='wedge_track_event'),

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
    # Provider subscription (Claim -> Verified -> Paid). The provider_detail
    # slug pattern above can't swallow these — its slug converter won't match
    # the extra /upgrade/ path segment (same as the claim route).
    path('provider/<slug:slug>/upgrade/success/', views_billing.provider_upgrade_success, name='provider_upgrade_success'),
    path('provider/<slug:slug>/upgrade/', views_billing.provider_upgrade, name='provider_upgrade'),
    path('stripe/webhook/', views_billing.stripe_webhook, name='stripe_webhook'),
    path('methodology/', views.methodology, name='methodology'),
    path('guides/', views.guides_index, name='guides_index'),
    path('guides/no-surprises-act/', views.guide_no_surprises, name='guide_no_surprises'),
    path('guides/good-faith-estimate/', views.guide_good_faith_estimate, name='guide_good_faith_estimate'),
    path('guides/facility-fees/', views.guide_facility_fee, name='guide_facility_fee'),
    path('guides/why-prices-vary/', views.guide_price_variance, name='guide_price_variance'),
    path('overcharged/', views.overcharged, name='overcharged'),
    path('api/procedures/', views.procedure_api, name='procedure_api'),
]
