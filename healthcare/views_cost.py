from django.shortcuts import render, get_object_or_404
from django.db.models import Avg, Min, Max, Count
from django.views.decorators.cache import cache_page
from healthcare.models import Procedure, Location, PricingRecord


@cache_page(86400)
def cost_by_city(request, procedure_slug, location_slug):
    procedure = get_object_or_404(Procedure, slug=procedure_slug)
    location = get_object_or_404(Location, slug=location_slug)
    display_name = procedure.display_name or procedure.name

    # Valid provider types: 3+ providers for this procedure in this city
    by_type = list(PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location,
        cash_price__isnull=False,
        provider__is_individual=False,
    ).exclude(cash_price=0).values(
        'provider__provider_type__name',
    ).annotate(
        avg_price=Avg('cash_price'),
        min_price=Min('cash_price'),
        max_price=Max('cash_price'),
        count=Count('provider_id', distinct=True),
    ).filter(count__gte=3).order_by('-count')[:5])

    valid_type_names = [t['provider__provider_type__name'] for t in by_type]

    if not valid_type_names:
        return render(request, 'healthcare/cost_by_city.html', {
            'procedure': procedure,
            'display_name': display_name,
            'location': location,
            'no_data': True,
        })

    # Base queryset: filtered to valid types only
    base_qs = PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location,
        cash_price__isnull=False,
        provider__provider_type__name__in=valid_type_names,
        provider__is_individual=False,
    ).exclude(cash_price=0)

    # Stats from filtered data
    stats = base_qs.aggregate(
        avg_price=Avg('cash_price'),
        min_price=Min('cash_price'),
        max_price=Max('cash_price'),
        avg_medicare=Avg('insured_price'),
        total=Count('id'),
    )

    if stats['total'] == 0:
        return render(request, 'healthcare/cost_by_city.html', {
            'procedure': procedure,
            'display_name': display_name,
            'location': location,
            'no_data': True,
        })

    # Percentiles from filtered data
    prices = list(base_qs.order_by('cash_price').values_list('cash_price', flat=True))
    median = float(prices[len(prices) // 2]) if prices else 0
    p25 = float(prices[len(prices) // 4]) if prices else 0
    p75 = float(prices[3 * len(prices) // 4]) if prices else 0
    p5 = float(prices[len(prices) // 20]) if prices else 0
    p95 = float(prices[19 * len(prices) // 20]) if prices else 0

    # Use p5/p95 as reported min/max to filter outliers
    price_floor = max(p25 * 0.5, 50) if p25 > 0 else 50

    # vs median labels for facility types
    for t in by_type:
        avg = float(t['avg_price'])
        if median > 0:
            pct = round((avg - median) / median * 100)
            if pct > 10:
                t['vs_median'] = str(abs(pct)) + '% above median'
                t['vs_class'] = 'above'
            elif pct < -10:
                t['vs_median'] = str(abs(pct)) + '% below median'
                t['vs_class'] = 'below'
            else:
                t['vs_median'] = 'Near median'
                t['vs_class'] = 'near'
        else:
            t['vs_median'] = ''
            t['vs_class'] = ''

    if by_type:
        sorted_by_price = sorted(by_type, key=lambda x: float(x['avg_price']))
        cheapest_name = sorted_by_price[0]['provider__provider_type__name']
        priciest_name = sorted_by_price[-1]['provider__provider_type__name'] if len(sorted_by_price) > 1 else None
        for t in by_type:
            t['is_lowest'] = t['provider__provider_type__name'] == cheapest_name
            t['is_highest'] = t['provider__provider_type__name'] == priciest_name if priciest_name else False

    # Deduplicated provider list, filtered, capped at 25
    provider_records = base_qs.filter(
        cash_price__gte=price_floor,
    ).select_related(
        'provider', 'provider__provider_type'
    ).order_by('cash_price')[:100]

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
        if len(providers) >= 15:
            break

    total_providers = base_qs.values('provider_id').distinct().count()
    has_medicare = any(p['medicare'] for p in providers)

    lowest = providers[0] if providers else None
    highest_record = base_qs.order_by('-cash_price').select_related('provider', 'provider__provider_type').first()
    highest = {
        'name': highest_record.provider.name,
        'slug': highest_record.provider.slug,
        'type': highest_record.provider.provider_type.name if highest_record and highest_record.provider.provider_type else '',
        'price': highest_record.cash_price,
    } if highest_record else None

    # Compare cities - use same state only for speed
    compare_cities = list(PricingRecord.objects.filter(
        procedure=procedure,
        provider__location__state=location.state,
        cash_price__isnull=False,
    ).exclude(cash_price=0).exclude(
        provider__location=location,
    ).values(
        'provider__location__city',
        'provider__location__state',
        'provider__location__slug',
    ).annotate(
        median_price=Avg('cash_price'),
        provider_count=Count('provider_id', distinct=True),
    ).filter(provider_count__gte=5).order_by('-provider_count')[:8])

    # Insights using cleaned data
    insights = []
    insights.append(display_name + ' prices in ' + location.city + ' range from $' + f'{p5:,.0f}' + ' to $' + f'{p95:,.0f}' + '.')
    insights.append('Most providers charge between $' + f'{p25:,.0f}' + ' and $' + f'{p75:,.0f}' + '.')
    insights.append('The median price is $' + f'{median:,.0f}' + '.')

    savings_amount = round(median - p25) if median > p25 else 0
    savings_pct = round((median - p25) / median * 100) if median > 0 else 0

    band_low = round(p25)
    band_high = round(p75)
    lowest_providers = [p for p in providers if float(p['price']) < p25][:5]
    typical_providers = [p for p in providers if p25 <= float(p['price']) <= p75][:5]

    return render(request, 'healthcare/cost_by_city.html', {
        'procedure': procedure,
        'display_name': display_name,
        'location': location,
        'stats': stats,
        'by_type': by_type,
        'providers': providers,
        'total_providers': total_providers,
        'median': median,
        'p25': p25,
        'p75': p75,
        'p5': p5,
        'p95': p95,
        'no_data': False,
        'has_medicare': has_medicare,
        'p25_pct': round(p25 / p95 * 100) if p95 else 0,
        'median_pct': round(median / p95 * 100) if p95 else 0,
        'iqr_pct': round((p75 - p25) / p95 * 100) if p95 else 0,
        'price_ratio': round(p95 / p5, 1) if p5 > 0 else 0,
        'lowest': lowest,
        'highest': highest,
        'compare_cities': compare_cities,
        'insights': insights,
        'band_low': band_low,
        'band_high': band_high,
        'lowest_providers': lowest_providers,
        'savings_amount': savings_amount,
        'savings_pct': savings_pct,
        'typical_providers': typical_providers,
    })
