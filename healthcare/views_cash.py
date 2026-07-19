"""
Cash-pay shopping pages.

These are a different page type from the insurance/hospital market pages
(views_market.py). Intent is comparison/shopping for elective procedures people
buy out of pocket (LASIK, Botox, dental implants, cosmetic surgery) — "find
affordable providers / see the price range", NOT "were you overcharged".

URLs:
    /cash/<procedure>/<city>/   -> cash_procedure_city   (e.g. LASIK Prices in Miami)
    /cash/<procedure>/          -> cash_procedure_national (national overview + by-city)

Data/cost safety: only the cash_price column is pulled into Python for
percentile math (bounded to one city's providers). By-city aggregation uses a
single GROUP BY. No bulk row selects.
"""
from django.shortcuts import render, get_object_or_404
from django.views.decorators.cache import cache_page
from django.http import Http404
from django.db.models import Avg, Count, Min, Max

from healthcare.models import Procedure, Location, PricingRecord
from healthcare.market_utils import (
    price_stats, dedupe_ranked_providers, build_cash_faq, faq_jsonld,
)
from healthcare.location_quality import is_malformed_location
from healthcare.provider_whitelist import allowed_provider_types

# Below this many clean providers we do not render a confident, indexable page.
THIN_DATA_THRESHOLD = 10

# One canonical explainer per page type (kept thin & data-anchored on the page).
COST_EXPLAINER_URL = "/guides/why-prices-vary/"


def _get_cash_procedure(slug):
    """A cash-pay page only exists for procedures flagged as cash-pay/elective."""
    procedure = get_object_or_404(Procedure, slug=slug)
    if not procedure.is_cash_pay_common:
        raise Http404("Not a cash-pay procedure")
    return procedure


def _cash_records(procedure, location=None):
    """
    Cash-pay records for a procedure (optionally in one location).

    Production tags these ``price_category='cash_price'``; we prefer that. Older
    data has the cash_price value populated but tagged differently, so when no
    explicitly-tagged rows exist we fall back to populated cash_price for this
    (cash-pay-flagged) procedure. Returns (queryset, basis).
    """
    base = PricingRecord.objects.filter(
        procedure=procedure,
        cash_price__isnull=False,
    ).exclude(cash_price=0)
    if location is not None:
        base = base.filter(provider__location=location)

    # Provider-type whitelist: only show credible provider types for this
    # procedure, dropping the contaminated generic "Clinic" bucket (orthodontists,
    # endocrinologists, etc. that don't offer the procedure). Applied before
    # stats/ranking so the median and counts reflect only credible providers.
    whitelist = allowed_provider_types(procedure.slug)
    if whitelist:
        base = base.filter(provider__provider_type__name__in=whitelist)

    tagged = base.filter(price_category='cash_price')
    if tagged.exists():
        return tagged, 'cash_price'
    return base, 'cash_price_legacy'


def _assign_bands(ranked, p25, p75):
    for p in ranked:
        if p['price'] <= p25:
            p['band'], p['band_label'] = 'below', 'Below typical'
        elif p['price'] <= p75:
            p['band'], p['band_label'] = 'typical', 'Typical'
        else:
            p['band'], p['band_label'] = 'above', 'Above typical'


@cache_page(86400)
@cache_page(86400)
def cash_procedure_city(request, procedure_slug, location_slug):
    procedure = _get_cash_procedure(procedure_slug)
    location = get_object_or_404(Location, slug=location_slug)
    # Don't generate city pages for malformed locations (state-doubling,
    # street-address-as-city, APO/FPO) — they render broken titles.
    if is_malformed_location(location.city, location.state):
        raise Http404("Location not eligible for pages")
    display_name = procedure.display_name or procedure.name
    city_state = f"{location.city}, {location.state}"

    records, basis = _cash_records(procedure, location)
    ranked, dropped = dedupe_ranked_providers(records)
    provider_count = len(ranked)

    # Thin-data guard: don't render a confident, indexable page on sparse data.
    if provider_count < THIN_DATA_THRESHOLD:
        return render(request, 'healthcare/cash_city.html', {
            'procedure': procedure,
            'location': location,
            'display_name': display_name,
            'city_state': city_state,
            'thin_data': True,
            'noindex': True,
            'provider_count': provider_count,
            'thin_threshold': THIN_DATA_THRESHOLD,
            'sample_providers': ranked,
            'explainer_url': COST_EXPLAINER_URL,
        })

    stats = price_stats([p['price'] for p in ranked])
    _assign_bands(ranked, stats['p25'], stats['p75'])
    cheapest_name = ranked[0]['name'] if ranked else None

    # Market-snapshot sentence — computed from this page's data.
    snapshot = (
        f"{provider_count} providers advertise cash prices for {display_name} in "
        f"{city_state}. The median is ${stats['median']:,}, most fall between "
        f"${stats['p25']:,} and ${stats['p75']:,}, and the full range runs "
        f"${stats['min']:,}–${stats['max']:,} ({stats['range_multiplier']}x)."
    )

    faqs = build_cash_faq(display_name, city_state, stats, cheapest_name)

    # Rule-based insights
    insights = []
    national_records, _ = _cash_records(procedure)
    national_prices = list(national_records.values_list('cash_price', flat=True)[:5000])
    national_median = sorted(national_prices)[len(national_prices)//2] if national_prices else 0

    if national_median > 0 and stats['median'] > 0:
        diff_pct = round((stats['median'] - float(national_median)) / float(national_median) * 100)
        if diff_pct > 15:
            insights.append(f"{display_name} in {city_state} costs {abs(diff_pct)}% more than the national average (${int(national_median):,}).")
        elif diff_pct < -15:
            insights.append(f"{display_name} in {city_state} costs {abs(diff_pct)}% less than the national average (${int(national_median):,}).")
        else:
            insights.append(f"{display_name} in {city_state} is priced near the national average (${int(national_median):,}).")

    type_stats = list(records.values('provider__provider_type__name').annotate(
        avg=Avg('cash_price'), count=Count('provider_id', distinct=True)
    ).filter(count__gte=3).order_by('avg'))
    if len(type_stats) >= 2:
        cheapest_t = type_stats[0]
        priciest_t = type_stats[-1]
        savings_pct = round((1 - float(cheapest_t['avg']) / float(priciest_t['avg'])) * 100)
        insights.append(f"{cheapest_t['provider__provider_type__name']}s (${int(cheapest_t['avg']):,} avg) are {savings_pct}% cheaper than {priciest_t['provider__provider_type__name']}s (${int(priciest_t['avg']):,} avg) in {location.city}.")

    if provider_count > 80:
        insights.append(f"With {provider_count} providers, {location.city} has high competition, giving patients more pricing options.")
    elif provider_count > 40:
        insights.append(f"{location.city} has moderate competition with {provider_count} providers advertising cash prices.")

    nearby_cities = []
    if location.state:
        nearby_qs = national_records.filter(
            provider__location__state=location.state
        ).exclude(provider__location=location).values(
            'provider__location__slug', 'provider__location__city', 'provider__location__state'
        ).annotate(
            avg=Avg('cash_price'), count=Count('provider_id', distinct=True)
        ).filter(count__gte=5).order_by('-count')[:6]
        nearby_cities = [{'slug': c['provider__location__slug'], 'city': c['provider__location__city'],
                          'state': c['provider__location__state'], 'avg': round(float(c['avg'])),
                          'count': c['count']} for c in nearby_qs]

    context = {
        'procedure': procedure,
        'location': location,
        'display_name': display_name,
        'city_state': city_state,
        'thin_data': False,
        'noindex': False,
        'insights': insights,
        'nearby_cities': nearby_cities,
        'national_median': int(national_median) if national_median else None,
        'provider_count': provider_count,
        'stats': stats,
        'snapshot': snapshot,
        'ranked_providers': ranked[:50],
        'total_ranked': provider_count,
        'price_bands': {
            'below': {'range': f"Under ${stats['p25']:,}",
                      'count': sum(1 for p in ranked if p['price'] < stats['p25'])},
            'typical': {'range': f"${stats['p25']:,} — ${stats['p75']:,}",
                        'count': sum(1 for p in ranked if stats['p25'] <= p['price'] <= stats['p75'])},
            'above': {'range': f"Over ${stats['p75']:,}",
                      'count': sum(1 for p in ranked if p['price'] > stats['p75'])},
        },
        'faqs': faqs,
        'faq_jsonld': faq_jsonld(faqs),
        'basis': basis,
        'dropped_outliers': dropped,
        'explainer_url': COST_EXPLAINER_URL,
    }
    return render(request, 'healthcare/cash_city.html', context)


@cache_page(86400)
@cache_page(86400)
def cash_procedure_national(request, procedure_slug):
    procedure = _get_cash_procedure(procedure_slug)
    display_name = procedure.display_name or procedure.name

    records, basis = _cash_records(procedure)
    total_providers = records.values('provider_id').distinct().count()

    if total_providers < THIN_DATA_THRESHOLD:
        return render(request, 'healthcare/cash_national.html', {
            'procedure': procedure,
            'display_name': display_name,
            'thin_data': True,
            'noindex': True,
            'provider_count': total_providers,
            'thin_threshold': THIN_DATA_THRESHOLD,
            'explainer_url': COST_EXPLAINER_URL,
        })

    # National percentile stats — pull only the single price column (bounded).
    prices = list(records.values_list('cash_price', flat=True))
    stats = price_stats(prices)

    # By-city breakdown — one GROUP BY, no row pull. Only cities above threshold.
    city_rows = records.values(
        'provider__location__slug',
        'provider__location__city',
        'provider__location__state',
    ).annotate(
        providers=Count('provider_id', distinct=True),
        avg=Avg('cash_price'),
        low=Min('cash_price'),
        high=Max('cash_price'),
    ).filter(providers__gte=THIN_DATA_THRESHOLD).order_by('-providers')

    by_city = [{
        'slug': c['provider__location__slug'],
        'city': c['provider__location__city'],
        'state': c['provider__location__state'],
        'providers': c['providers'],
        'avg': round(float(c['avg'])),
        'low': round(float(c['low'])),
        'high': round(float(c['high'])),
    } for c in city_rows
        if c['provider__location__slug']
        and not is_malformed_location(c['provider__location__city'], c['provider__location__state'])]

    snapshot = (
        f"{total_providers:,} providers across {len(by_city)} cities advertise cash "
        f"prices for {display_name}. The national median is ${stats['median']:,}, "
        f"with most between ${stats['p25']:,} and ${stats['p75']:,}."
    )

    # National FAQ uses "the U.S." as the geography.
    faqs = build_cash_faq(display_name, "the U.S.", stats, None)

    context = {
        'procedure': procedure,
        'display_name': display_name,
        'thin_data': False,
        'noindex': False,
        'provider_count': total_providers,
        'stats': stats,
        'snapshot': snapshot,
        'by_city': by_city,
        'faqs': faqs,
        'faq_jsonld': faq_jsonld(faqs),
        'basis': basis,
        'explainer_url': COST_EXPLAINER_URL,
    }
    return render(request, 'healthcare/cash_national.html', context)
