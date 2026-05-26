from django.shortcuts import render, get_object_or_404
from django.db import models
from django.http import HttpResponse
from .models import (
    Provider, Procedure, PricingRecord, Vertical, Location,
    SafetyEvent, DataSource
)


def home(request):
    verticals = Vertical.objects.filter(tier__lte=2).order_by('sort_order')
    recent_providers = Provider.objects.order_by('-created_at')[:10]
    procedures = Procedure.objects.filter(is_cash_pay_common=True)[:12]
    return render(request, 'healthcare/home.html', {
        'verticals': verticals,
        'recent_providers': recent_providers,
        'procedures': procedures,
    })


def provider_detail(request, slug):
    provider = get_object_or_404(Provider, slug=slug)
    pricing = provider.pricing_records.select_related('procedure').order_by('procedure__name')
    safety_events = provider.safety_events.all()[:10]
    sources = provider.data_sources.all()
    insurance = provider.insurance_acceptance.all()
    return render(request, 'healthcare/provider_detail.html', {
        'provider': provider,
        'pricing': pricing,
        'safety_events': safety_events,
        'sources': sources,
        'insurance': insurance,
    })


def procedure_detail(request, slug):
    procedure = get_object_or_404(Procedure, slug=slug)
    pricing = procedure.pricing_records.select_related('provider', 'provider__location').order_by('cash_price')
    locations = Location.objects.filter(
        provider__pricing_records__procedure=procedure
    ).distinct().order_by('state', 'city')
    return render(request, 'healthcare/procedure_detail.html', {
        'procedure': procedure,
        'pricing': pricing,
        'locations': locations,
    })


def city_detail(request, state, city_slug):
    location = get_object_or_404(Location, slug=city_slug, state=state.upper())
    providers = Provider.objects.filter(location=location).order_by('name')
    return render(request, 'healthcare/city_detail.html', {
        'location': location,
        'providers': providers,
    })


def procedure_city(request, procedure_slug, state, city_slug):
    procedure = get_object_or_404(Procedure, slug=procedure_slug)
    location = get_object_or_404(Location, slug=city_slug, state=state.upper())
    pricing = PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location
    ).select_related('provider', 'provider__provider_type').order_by('cash_price')

    # Calculate savings between cheapest and most expensive
    savings = 0
    if pricing.count() >= 2:
        prices = [r.cash_price for r in pricing if r.cash_price]
        if len(prices) >= 2:
            savings = prices[-1] - prices[0]

    # Find other cities that have this procedure, sorted by most providers
    from django.db.models import Count
    other_cities = Location.objects.filter(
        provider__pricing_records__procedure=procedure
    ).exclude(id=location.id).annotate(
        proc_count=Count('provider__pricing_records', filter=models.Q(provider__pricing_records__procedure=procedure))
    ).order_by('-proc_count').distinct()[:12]

    return render(request, 'healthcare/procedure_city.html', {
        'procedure': procedure,
        'location': location,
        'pricing': pricing,
        'savings': savings,
        'other_cities': other_cities,
    })


def vertical_detail(request, slug):
    vertical = get_object_or_404(Vertical, slug=slug)
    providers = Provider.objects.filter(verticals=vertical).order_by('name')
    procedures = Procedure.objects.filter(verticals=vertical).order_by('name')
    return render(request, 'healthcare/vertical_detail.html', {
        'vertical': vertical,
        'providers': providers,
        'procedures': procedures,
    })


def search(request):
    query = request.GET.get('q', '')
    providers = Provider.objects.none()
    procedures = Procedure.objects.none()
    if query:
        providers = Provider.objects.filter(name__icontains=query)[:20]
        procedures = Procedure.objects.filter(name__icontains=query)[:20]
    return render(request, 'healthcare/search.html', {
        'query': query,
        'providers': providers,
        'procedures': procedures,
    })


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "Sitemap: https://zenthir.com/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def procedures_index(request):
    procedures = Procedure.objects.order_by('category', 'name')
    provider_count = Provider.objects.count()
    city_count = Location.objects.count()
    return render(request, 'healthcare/procedures_index.html', {
        'procedures': procedures,
        'provider_count': provider_count,
        'city_count': city_count,
    })


def cities_index(request):
    from django.db.models import Count
    locations = Location.objects.annotate(
        provider_count=Count('provider')
    ).order_by('state_full', 'city')
    total_providers = Provider.objects.count()
    return render(request, 'healthcare/cities_index.html', {
        'locations': locations,
        'total_providers': total_providers,
    })
