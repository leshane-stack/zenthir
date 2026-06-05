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

    # Get pricing records for this procedure in this city - facility-component, apples-to-apples
    from healthcare.procedure_groups import get_related_procedure_ids

    base_records = PricingRecord.objects.filter(
        provider__location=location,
        cash_price__isnull=False,
    ).exclude(cash_price=0)

    # Prefer facility/global charges (what patients actually pay), exclude gross/min/max extremes
    def clean_facility(qs):
        return qs.filter(
            billing_component__in=['global', 'technical']
        ).exclude(
            source_name__icontains='Gross'
        ).exclude(
            source_name__icontains='Max Rate'
        ).exclude(
            source_name__icontains='Min Rate'
        )

    comparison_basis = 'facility'

    # First try this exact procedure, facility component
    records = clean_facility(base_records.filter(procedure=procedure)).select_related('provider', 'provider__provider_type')

    if records.count() < 10:
        # Expand to related procedures (e.g. all MRI brain variants) for facility data
        related_ids = get_related_procedure_ids(procedure)
        if len(related_ids) > 1:
            grouped = clean_facility(base_records.filter(procedure_id__in=related_ids)).select_related('provider', 'provider__provider_type')
            if grouped.count() >= 10:
                records = grouped
                comparison_basis = 'facility_grouped'

    # Fall back to professional component for this procedure if no facility data exists
    if records.count() < 10:
        records = base_records.filter(
            procedure=procedure,
            billing_component='professional',
        ).select_related('provider', 'provider__provider_type')
        comparison_basis = 'professional'

    # Final fallback: any records for this procedure
    if records.count() == 0:
        records = base_records.filter(procedure=procedure).select_related('provider', 'provider__provider_type')
        comparison_basis = 'mixed'

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

    # Market snapshot prose
    snapshot_lines = []
    snapshot_lines.append(f"{provider_count} providers report pricing data for {display_name} in {location.city}.")
    snapshot_lines.append(f"The median price is ${median_price:,}, with a typical range of ${p25:,} to ${p75:,}.")
    if facility_breakdown and len(facility_breakdown) >= 2:
        cheapest_type = facility_breakdown[0]
        most_expensive = facility_breakdown[-1]
        if cheapest_type['avg'] < most_expensive['avg']:
            pct_diff = round((most_expensive['avg'] - cheapest_type['avg']) / cheapest_type['avg'] * 100)
            snapshot_lines.append(f"{most_expensive['name']} providers average ${most_expensive['avg']:,}, which is {pct_diff}% more than {cheapest_type['name']} providers (${cheapest_type['avg']:,}).")
        if cheapest_type['providers'] > 0 and most_expensive['providers'] > 0:
            snapshot_lines.append(f"{cheapest_type['name']} accounts for {cheapest_type['providers']} of {provider_count} reporting providers.")

    # Price check benchmarks
    price_benchmarks = [
        {'amount': p5, 'label': 'Well below typical'},
        {'amount': p25, 'label': 'Below typical'},
        {'amount': median_price, 'label': 'Typical'},
        {'amount': p75, 'label': 'Above typical'},
        {'amount': p95, 'label': 'Well above typical'},
    ]

    # Range multiplier
    if p5 > 0:
        range_multiplier = round(p95 / p5, 1)
    else:
        range_multiplier = 0

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
        'comparison_basis': comparison_basis,
        'snapshot_lines': snapshot_lines,
        'price_benchmarks': price_benchmarks,
        'range_multiplier': range_multiplier,
    }

    return render(request, 'healthcare/procedure_market.html', context)
