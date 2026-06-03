from django.shortcuts import render, get_object_or_404
from django.db.models import Avg, Count, Min, Max, Q
from healthcare.models import Procedure, Location, PricingRecord, Provider, ProviderType
from statistics import median as calc_median


def procedure_market(request, procedure_slug, location_slug):
    """
    Market report page: "Most Affordable [Procedure] in [City]"
    Shows ranked providers, price bands, facility breakdown.
    """
    procedure = get_object_or_404(Procedure, slug=procedure_slug)
    location = get_object_or_404(Location, slug=location_slug)
    display_name = procedure.display_name or procedure.name

    # Get all pricing records for this procedure in this city
    records = PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location,
        cash_price__isnull=False,
    ).exclude(cash_price=0).select_related('provider', 'provider__provider_type')

    total_records = records.count()
    if total_records == 0:
        return render(request, 'healthcare/procedure_market.html', {
            'procedure': procedure,
            'location': location,
            'display_name': display_name,
            'no_data': True,
        })

    # Aggregate stats
    prices = sorted([float(r.cash_price) for r in records])
    provider_count = records.values('provider_id').distinct().count()
    median_price = round(calc_median(prices))
    p5 = round(prices[len(prices) // 20])
    p25 = round(prices[len(prices) // 4])
    p75 = round(prices[3 * len(prices) // 4])
    p95 = round(prices[19 * len(prices) // 20])
    avg_price = round(sum(prices) / len(prices))

    # Price bands
    price_bands = {
        'below_typical': {'label': 'Below typical', 'range': f'Under ${p25:,}', 'count': sum(1 for p in prices if p < p25)},
        'typical': {'label': 'Typical range', 'range': f'${p25:,} — ${p75:,}', 'count': sum(1 for p in prices if p25 <= p <= p75)},
        'above_typical': {'label': 'Above typical', 'range': f'Over ${p75:,}', 'count': sum(1 for p in prices if p > p75)},
    }

    # Ranked providers - one per provider, lowest price
    # Group by provider, take lowest price
    from django.db.models import Min as DbMin
    provider_prices = records.values(
        'provider_id',
        'provider__name',
        'provider__slug',
        'provider__provider_type__name',
        'provider__address',
    ).annotate(
        lowest_price=DbMin('cash_price'),
        record_count=Count('id'),
    ).order_by('lowest_price')

    # Add rank and percentile
    ranked_providers = []
    for i, p in enumerate(provider_prices):
        price = float(p['lowest_price'])
        if price <= p25:
            band = 'below'
            band_label = 'Below typical'
        elif price <= p75:
            band = 'typical'
            band_label = 'Typical'
        else:
            band = 'above'
            band_label = 'Above typical'

        ranked_providers.append({
            'rank': i + 1,
            'name': p['provider__name'],
            'slug': p['provider__slug'],
            'type': p['provider__provider_type__name'],
            'address': p['provider__address'],
            'price': round(price),
            'band': band,
            'band_label': band_label,
        })

    # Facility type breakdown
    type_stats = records.values(
        'provider__provider_type__name'
    ).annotate(
        avg=Avg('cash_price'),
        mn=Min('cash_price'),
        mx=Max('cash_price'),
        providers=Count('provider_id', distinct=True),
    ).order_by('avg')

    facility_breakdown = []
    for t in type_stats:
        if t['providers'] >= 2:
            facility_breakdown.append({
                'name': t['provider__provider_type__name'],
                'avg': round(float(t['avg'])),
                'low': round(float(t['mn'])),
                'high': round(float(t['mx'])),
                'providers': t['providers'],
            })

    # Savings potential
    savings = round(p75 - p25) if p75 > p25 else 0

    # Page context
    context = {
        'procedure': procedure,
        'location': location,
        'display_name': display_name,
        'no_data': False,
        'provider_count': provider_count,
        'total_records': total_records,
        'median_price': median_price,
        'avg_price': avg_price,
        'p5': p5,
        'p25': p25,
        'p75': p75,
        'p95': p95,
        'price_bands': price_bands,
        'ranked_providers': ranked_providers[:50],
        'total_ranked': len(ranked_providers),
        'facility_breakdown': facility_breakdown,
        'savings': savings,
    }

    return render(request, 'healthcare/procedure_market.html', context)
