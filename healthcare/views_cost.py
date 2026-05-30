from django.shortcuts import render, get_object_or_404
from django.db.models import Avg, Min, Max, Count, Q
from healthcare.models import Procedure, Location, PricingRecord, Provider


def cost_by_city(request, procedure_slug, location_slug):
    procedure = get_object_or_404(Procedure, slug=procedure_slug)
    location = get_object_or_404(Location, slug=location_slug)

    # Get all pricing records for this procedure in this city
    records = PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location,
    ).select_related('provider', 'provider__provider_type')

    if not records.exists():
        return render(request, 'healthcare/cost_by_city.html', {
            'procedure': procedure,
            'location': location,
            'no_data': True,
        })

    # Aggregate stats
    stats = records.aggregate(
        avg_price=Avg('cash_price'),
        min_price=Min('cash_price'),
        max_price=Max('cash_price'),
        avg_medicare=Avg('insured_price'),
        total=Count('id'),
    )

    # Breakdown by provider type
    by_type = records.values(
        'provider__provider_type__name',
        'provider__provider_type__slug',
    ).annotate(
        avg_price=Avg('cash_price'),
        min_price=Min('cash_price'),
        max_price=Max('cash_price'),
        avg_medicare=Avg('insured_price'),
        count=Count('id'),
    ).order_by('avg_price')

    # Individual providers with this procedure
    providers = []
    seen = set()
    for r in records.order_by('cash_price'):
        if r.provider_id not in seen:
            seen.add(r.provider_id)
            providers.append({
                'name': r.provider.name,
                'slug': r.provider.slug,
                'type': r.provider.provider_type.name if r.provider.provider_type else '',
                'price': r.cash_price,
                'medicare': r.insured_price,
                'source': r.source_name,
                'confidence': r.confidence,
            })

    # Median calculation
    prices = sorted([r.cash_price for r in records if r.cash_price])
    median = prices[len(prices) // 2] if prices else 0

    # Percentile buckets
    if prices:
        p25 = prices[len(prices) // 4]
        p75 = prices[3 * len(prices) // 4]
    else:
        p25 = p75 = 0

    return render(request, 'healthcare/cost_by_city.html', {
        'procedure': procedure,
        'location': location,
        'stats': stats,
        'by_type': by_type,
        'providers': providers[:50],
        'total_providers': len(providers),
        'median': median,
        'p25': p25,
        'p75': p75,
        'no_data': False,
        'has_medicare': any(p['medicare'] for p in providers[:50]),
        'p25_pct': round(p25 / stats['max_price'] * 100) if stats['max_price'] else 0,
        'median_pct': round(median / stats['max_price'] * 100) if stats['max_price'] else 0,
        'iqr_pct': round((p75 - p25) / stats['max_price'] * 100) if stats['max_price'] else 0,
    })
