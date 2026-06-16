from django.shortcuts import render, get_object_or_404
from django.views.decorators.cache import cache_page
from django.db.models import Avg, Min, Max, Count
from healthcare.models import Procedure, Location, PricingRecord


@cache_page(86400)
def cost_by_city(request, procedure_slug, location_slug):
    procedure = get_object_or_404(Procedure, slug=procedure_slug)
    location = get_object_or_404(Location, slug=location_slug)
    display_name = procedure.display_name or procedure.name

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
            'display_name': display_name,
            'location': location,
            'no_data': True,
        })

    prices = list(PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location,
    ).order_by('cash_price').values_list('cash_price', flat=True))

    median = float(prices[len(prices) // 2]) if prices else 0
    p25 = float(prices[len(prices) // 4]) if prices else 0
    p75 = float(prices[3 * len(prices) // 4]) if prices else 0
    max_price = float(stats['max_price'] or 1)
    min_price = float(stats['min_price'] or 0)

    price_ratio = round(max_price / min_price, 1) if min_price > 0 else 0

    by_type = list(PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location,
    ).values(
        'provider__provider_type__name',
    ).annotate(
        avg_price=Avg('cash_price'),
        min_price=Min('cash_price'),
        max_price=Max('cash_price'),
        count=Count('provider_id', distinct=True),
    ).filter(count__gte=3).order_by('-count')[:5])

    for t in by_type:
        avg = float(t['avg_price'])
        if median > 0:
            pct = round((avg - median) / median * 100)
            if pct > 10:
                t['vs_median'] = f'{pct}% above median'
                t['vs_class'] = 'above'
            elif pct < -10:
                t['vs_median'] = f'{abs(pct)}% below median'
                t['vs_class'] = 'below'
            else:
                t['vs_median'] = 'Near median'
                t['vs_class'] = 'near'
        else:
            t['vs_median'] = ''
            t['vs_class'] = ''

    # Only show provider types that appear 3+ times for this procedure in this city
    valid_type_names = [t['provider__provider_type__name'] for t in by_type] if by_type else []
    price_floor = max(p25 * 0.5, 50) if p25 > 0 else 50
    prov_qs = PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location,
        cash_price__gte=price_floor,
    ).select_related(
        'provider', 'provider__provider_type'
    )
    if valid_type_names:
        prov_qs = prov_qs.filter(provider__provider_type__name__in=valid_type_names)
    provider_records = prov_qs.order_by('cash_price')[:50]

    providers = []
    seen = set()
    for r in provider_records:
        if r.provider_id not in seen:
            seen.add(r.provider_id)
            if len(providers) >= 25:
                break
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

    lowest = providers[0] if providers else None
    highest_record = PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location,
    ).select_related('provider', 'provider__provider_type').order_by('-cash_price').first()
    highest = {
        'name': highest_record.provider.name,
        'slug': highest_record.provider.slug,
        'type': highest_record.provider.provider_type.name if highest_record and highest_record.provider.provider_type else '',
        'price': highest_record.cash_price,
    } if highest_record else None

    compare_cities = list(PricingRecord.objects.filter(
        procedure=procedure,
    ).exclude(
        provider__location=location,
    ).values(
        'provider__location__city',
        'provider__location__state',
        'provider__location__slug',
    ).annotate(
        median_price=Avg('cash_price'),
        provider_count=Count('provider_id', distinct=True),
    ).filter(provider_count__gte=10).order_by('median_price')[:8])

    insights = []
    insights.append(f'{display_name} prices in {location.city} range from ${min_price:,.0f} to ${max_price:,.0f}.')
    insights.append(f'Most providers charge between ${p25:,.0f} and ${p75:,.0f}.')
    insights.append(f'The median price is ${median:,.0f}.')
    if price_ratio >= 3:
        insights.append(f'The most expensive providers charge {price_ratio}x more than the lowest-priced providers.')
    elif price_ratio >= 2:
        insights.append(f'There is a {price_ratio}x price difference between the lowest and highest providers.')

    # Savings opportunity
    savings_amount = round(p75 - p25)
    savings_pct = round((p75 - p25) / p75 * 100) if p75 > 0 else 0

    # Mark cheapest and most expensive facility types
    if by_type:
        by_type[0]['is_lowest'] = True
        by_type[-1]['is_highest'] = True if len(by_type) > 1 else False

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
        'no_data': False,
        'has_medicare': has_medicare,
        'p25_pct': round(p25 / max_price * 100) if max_price else 0,
        'median_pct': round(median / max_price * 100) if max_price else 0,
        'iqr_pct': round((p75 - p25) / max_price * 100) if max_price else 0,
        'price_ratio': price_ratio,
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
