from django.shortcuts import render, get_object_or_404
from django.db.models import Avg, Min, Max, Count, Q
from healthcare.models import Procedure, Location, PricingRecord, Provider


def cost_by_city(request, procedure_slug, location_slug):
    procedure = get_object_or_404(Procedure, slug=procedure_slug)
    location = get_object_or_404(Location, slug=location_slug)

    # Fast aggregate stats first
    stats = PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location,
    ).aggregate(
        avg_price=Avg('cash_price'),
        min_price=Min('cash_price'),
        max_price=Max('cash_price'),
        avg_medicare=Avg('insured_price'),
        total=Count('id'),
    )

    if stats['total'] == 0:
        return render(request, 'healthcare/cost_by_city.html', {
            'procedure': procedure,
            'location': location,
            'no_data': True,
        })

    # Breakdown by provider type
    by_type = PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location,
    ).values(
        'provider__provider_type__name',
    ).annotate(
        avg_price=Avg('cash_price'),
        min_price=Min('cash_price'),
        max_price=Max('cash_price'),
        count=Count('provider_id', distinct=True),
    ).order_by('avg_price')

    # Get prices for distribution calc - just the numbers
    prices = list(PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location,
    ).order_by('cash_price').values_list('cash_price', flat=True))

    median = prices[len(prices) // 2] if prices else 0
    p25 = prices[len(prices) // 4] if prices else 0
    p75 = prices[3 * len(prices) // 4] if prices else 0

    # Providers - limited query, only top 50
    provider_records = PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location,
    ).select_related(
        'provider', 'provider__provider_type'
    ).order_by('cash_price')[:50]

    providers = []
    seen = set()
    for r in provider_records:
        if r.provider_id not in seen:
            seen.add(r.provider_id)
            providers.append({
                'name': r.provider.name,
                'slug': r.provider.slug,
                'type': r.provider.provider_type.name if r.provider.provider_type else '',
                'price': r.cash_price,
                'medicare': r.insured_price,
            })

    total_providers = PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location,
    ).values('provider_id').distinct().count()

    has_medicare = any(p['medicare'] for p in providers)
    max_price = stats['max_price'] or 1

    return render(request, 'healthcare/cost_by_city.html', {
        'procedure': procedure,
        'location': location,
        'stats': stats,
        'by_type': by_type,
        'providers': providers,
        'total_providers': total_providers,
        'median': median,
        'p25': p25,
        'p75': p75,
        'no_data': False,
        'has_medicare': has_medicare,
        'p25_pct': round(float(p25) / float(max_price) * 100),
        'median_pct': round(float(median) / float(max_price) * 100),
        'iqr_pct': round(float(p75 - p25) / float(max_price) * 100),
    })
