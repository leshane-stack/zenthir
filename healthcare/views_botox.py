"""
Botox-in-Miami test wedge.

Scope: ONE wedge only — Botox, Miami. The goal is to capture real consumer
leads (the billable event) so medspas can be pitched on paying for them. These
views are deliberately isolated from the generic cash-pay views (views_cash.py)
so the wedge can be tuned without touching every cash page.

Pages (routed explicitly, BEFORE the generic /cash/<proc>/<city>/ pattern):
    /cash/botox/miami-fl/            -> botox_miami_hub       (head-term hub)
    /cash/botox/miami-fl/cheapest/   -> botox_miami_cheapest  (highest-intent)

The hub AGGREGATES every Botox variant (full-face, per-unit, forehead, lip-flip,
…) that exists as a cash-pay procedure. Because per-unit pricing (~$12/unit) and
treatment totals (~$500) are different units, the citable headline stat is built
only from *treatment-total* variants; per-unit variants are surfaced separately.

Capture hooks (the point of the test):
    /wedge/lead/     -> capture_lead    (consumer lead — the billable event)
    /wedge/notify/   -> capture_notify  (consumer email — price-drop alerts)
    /wedge/event/    -> track_event     (funnel instrumentation beacon)

Capture endpoints are csrf_exempt JSON endpoints: the hub/cheapest pages are
cache_page'd, which makes a rendered {% csrf_token %} stale/shared, so we skip
CSRF here and defend public lead forms with a honeypot + email validation.

Data/cost safety: mirrors views_cash — only the cash_price column is pulled into
Python for percentile math, bounded to Miami's providers. No bulk row selects.
"""
import json
import re
import uuid

from django.shortcuts import render, get_object_or_404
from django.views.decorators.cache import cache_page
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.http import JsonResponse, Http404
from django.db.models import Avg, Count, Min, Max

from healthcare.models import (
    Procedure, Location, Provider, PricingRecord,
    ConsumerLead, PriceAlertSignup, WedgeEvent, ClaimRequest,
)
from healthcare.market_utils import (
    price_stats, dedupe_ranked_providers, faq_jsonld,
)
from healthcare.provider_whitelist import allowed_provider_types
from healthcare.location_quality import is_malformed_location

# --- Wedge constants --------------------------------------------------------
WEDGE_PROCEDURE_SLUG = 'botox'
WEDGE_CITY_SLUG = 'miami-fl'
# A variant whose median is at/below this is priced per-unit, not per-treatment.
PER_UNIT_MAX = 75
# Below this many clean providers we don't render a confident, indexable page.
THIN_DATA_THRESHOLD = 10
COST_EXPLAINER_URL = "/guides/why-prices-vary/"
VISITOR_COOKIE = 'zwid'   # first-party anonymous visitor id (not localStorage)


# ---------------------------------------------------------------------------
# Lead-enablement (honesty gate)
#
# A per-provider "Request this price" lead form implies the provider agreed to
# receive leads through Zenthir. We only show it when that's true: the provider
# has an APPROVED claim (ClaimRequest.status='verified') or is flagged verified.
# Unclaimed providers get a "call/visit them directly" card instead — never a
# lead form. Market-level and email capture are unaffected.
# ---------------------------------------------------------------------------

def _lead_enabled(provider):
    """True if this provider has opted in to receive leads (claimed/verified)."""
    if getattr(provider, 'verified', False):
        return True
    return ClaimRequest.objects.filter(provider=provider, status='verified').exists()


def _mark_lead_enabled(ranked):
    """Annotate each ranked provider dict with lead_enabled (one bounded query)."""
    ids = [p['provider_id'] for p in ranked]
    if not ids:
        return
    claimed = set(
        ClaimRequest.objects.filter(provider_id__in=ids, status='verified')
        .values_list('provider_id', flat=True)
    )
    verified = set(
        Provider.objects.filter(id__in=ids, verified=True).values_list('id', flat=True)
    ) if _provider_has_verified_field() else set()
    for p in ranked:
        p['lead_enabled'] = p['provider_id'] in claimed or p['provider_id'] in verified


def _provider_has_verified_field():
    """Whether the Provider model exposes a `verified` field (future-proof)."""
    try:
        Provider._meta.get_field('verified')
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Visitor id + event logging
# ---------------------------------------------------------------------------

def _visitor_id(request):
    """Read the first-party visitor cookie; return '' if absent."""
    vid = request.COOKIES.get(VISITOR_COOKIE, '')
    if vid and re.fullmatch(r'[0-9a-f]{32}', vid):
        return vid
    return ''


def _visitor_and_cookie(request, response):
    """Return the visitor id, minting + setting the cookie on `response` if absent.

    Called ONLY from the uncached /wedge/ endpoints. The hub/cheapest pages are
    cache_page'd, so they must never Set-Cookie (a cached cookie would be shared
    across all visitors and destroy funnel attribution) — the client-side beacon
    to /wedge/event/ establishes the cookie on first load instead.
    """
    vid = _visitor_id(request)
    if not vid:
        vid = uuid.uuid4().hex
        response.set_cookie(
            VISITOR_COOKIE, vid, max_age=60 * 60 * 24 * 365,
            samesite='Lax', secure=request.is_secure(), httponly=False,
        )
    return vid


def _log_event(event_type, *, request, visitor_id='', page='', provider=None,
               provider_slug='', procedure_slug=WEDGE_PROCEDURE_SLUG,
               city_slug=WEDGE_CITY_SLUG):
    """Insert one WedgeEvent row. Best-effort — never breaks a page render."""
    try:
        WedgeEvent.objects.create(
            event_type=event_type,
            page=page,
            procedure_slug=procedure_slug,
            city_slug=city_slug,
            provider=provider,
            provider_slug=provider_slug or (provider.slug if provider else ''),
            visitor_id=visitor_id or _visitor_id(request),
            referrer=(request.META.get('HTTP_REFERER', '') or '')[:500],
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Market aggregation across Botox variants
# ---------------------------------------------------------------------------

# Extra Botox procedures that don't share the 'botox' slug prefix (and aren't
# flagged is_cash_pay_common) but belong on the hub — e.g. the per-unit CPT.
WEDGE_EXTRA_SLUGS = ['injection-onabotulinumtoxina-1-unit']

# Friendlier labels for the treatments table (clinical procedure names -> shopper terms).
WEDGE_VARIANT_NAMES = {
    'injection-onabotulinumtoxina-1-unit': 'Botox Injection (Per Unit)',
    'botox-full-face': 'Botox (Full Face)',
}


def _wedge_variants():
    """Every Botox variant on the hub — cash-pay 'botox*' procedures plus the
    per-unit CPT (which is priced per unit and isn't flagged cash-pay)."""
    from django.db.models import Q
    return list(
        Procedure.objects.filter(
            Q(slug__startswith='botox', is_cash_pay_common=True)
            | Q(slug__in=WEDGE_EXTRA_SLUGS)
        ).order_by('slug')
    )


def _whitelist_for(procedure):
    """Credible provider-type whitelist for one variant, or None (no filter).

    - Explicit entry in provider_whitelist.py wins.
    - Any other 'botox*' variant falls back to the injectables whitelist so it
      isn't polluted by the generic 'Clinic' bucket.
    - Everything else (e.g. the per-unit CPT, billed by medical specialties, not
      medspas) gets NO whitelist — filtering it to medspas would zero it out.
    """
    wl = allowed_provider_types(procedure.slug)
    if wl:
        return wl
    if procedure.slug.startswith('botox'):
        return allowed_provider_types('botox-full-face')
    return None


def _variant_whitelist(procedures):
    """Union of credible provider-type names across the given Botox variants.

    Falls back to the botox-full-face whitelist so newly-added variants that
    aren't in provider_whitelist.py still get the injectables filter, not the
    contaminated generic 'Clinic' bucket.
    """
    wl = set()
    for p in procedures:
        w = allowed_provider_types(p.slug)
        if w:
            wl.update(w)
    if not wl:
        wl.update(allowed_provider_types('botox-full-face') or [])
    return sorted(wl)


# --- Clinic-bucket recovery -------------------------------------------------
# The scraped data bulk-assigned Botox prices to a generic 'Clinic' provider
# type that mixes real medspas/derms with contamination (orthodontists,
# endocrinologists, spine centers). We recover the credible aesthetic ones by
# name: a provider is recovered iff its name matches an aesthetic term AND none
# of the non-Botox terms (the denylist wins). This is a name classifier, not a
# DB flag — deterministic and auditable via _recovered_ids().
CLINIC_ALLOW = [
    'med spa', 'medspa', 'med-spa', 'aesthetic', 'esthetic', 'laser', 'derm',
    'skin', 'cosmetic', 'plastic', 'rejuven', 'glow', 'beauty', 'injectable',
    'botox', 'filler', ' lip', 'wellness', 'spa ', 'facial', 'face', 'aura',
    'luxe', 'glam', 'contour', 'sculpt', 'ageless', 'radiance', 'vida',
    'revive', 'allure', 'lux ',
]
CLINIC_DENY = [
    'ortho', 'brace', 'invisalign', 'dental', 'dentist', 'smile', 'whiten',
    'endocrin', 'diabet', 'hormone', 'weight', 'bariatr', 'orthoped',
    'sports medicine', 'chiro', 'physical therapy', 'urolog', 'cardio', 'vein',
    'optical', 'ophthalm', ' eye', 'vision', 'podiatr', 'foot', 'fertility',
    'pediatr', 'psych', 'gastro', 'pain ', 'vascular', 'imaging', 'radiolog',
    'surgery associates', 'general surgery', 'spine',
    # Not injectable-Botox providers even though names read "aesthetic":
    'massage', 'lymphatic', 'hair removal', 'post lipo',
]


def _is_aesthetic_clinic_name(name):
    """True if a 'Clinic'-typed provider's name reads as a credible aesthetic
    Botox provider (allowlist match, no denylist match)."""
    low = (name or '').lower()
    if any(k in low for k in CLINIC_DENY):
        return False
    return any(k in low for k in CLINIC_ALLOW)


def _recovered_ids(procedures, location=None):
    """Provider ids from the generic 'Clinic' bucket whose names classify as
    credible aesthetic providers. location=None scopes it nationally."""
    qs = PricingRecord.objects.filter(
        procedure__in=procedures, cash_price__gt=0,
        provider__provider_type__name='Clinic',
    )
    if location is not None:
        qs = qs.filter(provider__location=location)
    rows = qs.values_list('provider_id', 'provider__name').distinct()
    return {pid for pid, name in rows if _is_aesthetic_clinic_name(name)}


def _records_for(procedures, location, whitelist, extra_ids=None):
    """Cash-price records for the given procedures, optionally in one location
    (location=None = national).

    Providers are kept if their type is whitelisted OR their id is in extra_ids
    (recovered aesthetic 'Clinic' providers). Prefers rows explicitly tagged
    price_category='cash_price'; falls back to any populated cash_price (legacy).
    """
    from django.db.models import Q
    base = PricingRecord.objects.filter(
        procedure__in=procedures,
        cash_price__isnull=False,
    ).exclude(cash_price=0)
    if location is not None:
        base = base.filter(provider__location=location)
    if whitelist:
        cond = Q(provider__provider_type__name__in=whitelist)
        if extra_ids:
            cond = cond | Q(provider_id__in=extra_ids)
        base = base.filter(cond)
    tagged = base.filter(price_category='cash_price')
    if tagged.exists():
        return tagged
    return base


def _variant_summary(procedure, location):
    """Per-variant stats block, or None if the variant has no clean providers.

    Uses a per-variant whitelist so the per-unit CPT (medical specialties) isn't
    filtered out by the medspa whitelist that full-face uses. Botox treatment
    variants also recover credible aesthetic providers from the 'Clinic' bucket
    so this row's count matches the headline."""
    extra = _recovered_ids([procedure], location) if procedure.slug.startswith('botox') else None
    records = _records_for([procedure], location, _whitelist_for(procedure), extra_ids=extra)
    ranked, _dropped = dedupe_ranked_providers(records)
    if not ranked:
        return None
    stats = price_stats([p['price'] for p in ranked])
    return {
        'slug': procedure.slug,
        'name': WEDGE_VARIANT_NAMES.get(procedure.slug) or procedure.display_name or procedure.name,
        'provider_count': len(ranked),
        'stats': stats,
        'per_unit': stats['median'] <= PER_UNIT_MAX,
    }


def build_botox_miami(location):
    """Aggregate every Botox variant in Miami into one market snapshot.

    Returns a context dict, or {'thin_data': True, ...} when the combined
    treatment market is too sparse to render confidently.
    """
    variants = _wedge_variants()

    # Per-variant breakdown (for the "all variants on one page" table + insights).
    # Each variant uses its own whitelist (per-unit CPT gets none).
    variant_rows = []
    treatment_procs = []
    per_unit_rows = []
    for v in variants:
        vs = _variant_summary(v, location)
        if not vs:
            continue
        variant_rows.append(vs)
        if vs['per_unit']:
            per_unit_rows.append(vs)
        else:
            treatment_procs.append(v)

    # The citable headline is treatment totals only (consistent units) — the
    # per-unit variant (~$14/unit) is excluded so it can't skew the median. If no
    # variant clears the per-unit threshold (unexpected), fall back to all
    # variants so the page still renders rather than 404.
    headline_procs = treatment_procs or variants
    whitelist = _variant_whitelist(headline_procs)
    recovered = _recovered_ids(headline_procs, location)
    records = _records_for(headline_procs, location, whitelist, extra_ids=recovered)
    ranked, dropped = dedupe_ranked_providers(records)
    provider_count = len(ranked)

    if provider_count < THIN_DATA_THRESHOLD:
        return {
            'thin_data': True,
            'provider_count': provider_count,
            'variant_rows': variant_rows,
        }

    stats = price_stats([p['price'] for p in ranked])
    _assign_bands(ranked, stats['p25'], stats['p75'])
    _mark_lead_enabled(ranked)

    return {
        'thin_data': False,
        'location': location,
        'stats': stats,
        'provider_count': provider_count,
        'ranked': ranked,
        'variant_rows': variant_rows,
        'per_unit_rows': per_unit_rows,
        'headline_procs': headline_procs,
        'records': records,
        'dropped': dropped,
        'whitelist': whitelist,
        'updated_at': _market_updated_at(records),
    }


def _assign_bands(ranked, p25, p75):
    for p in ranked:
        if p['price'] <= p25:
            p['band'], p['band_label'] = 'below', 'Below typical'
        elif p['price'] <= p75:
            p['band'], p['band_label'] = 'typical', 'Typical'
        else:
            p['band'], p['band_label'] = 'above', 'Above typical'


def _market_updated_at(records):
    """Most recent updated_at across the market's records (for schema validFrom)."""
    return records.aggregate(m=Max('updated_at'))['m']


def _national_botox_median(headline_procs, whitelist):
    """National median across the same treatment variants (bounded pull)."""
    qs = PricingRecord.objects.filter(
        procedure__in=headline_procs, cash_price__isnull=False,
    ).exclude(cash_price=0)
    if whitelist:
        qs = qs.filter(provider__provider_type__name__in=whitelist)
    tagged = qs.filter(price_category='cash_price')
    if tagged.exists():
        qs = tagged
    prices = list(qs.values_list('cash_price', flat=True)[:5000])
    if not prices:
        return 0, qs
    prices.sort()
    return round(float(prices[len(prices) // 2])), qs


def _build_insights(market, national_median, location):
    """Carry-forward rule-based insights: national comparison, variant/type
    comparison, competition level — all computed from this page's own data."""
    insights = []
    stats = market['stats']
    provider_count = market['provider_count']

    if national_median > 0 and stats['median'] > 0:
        diff_pct = round((stats['median'] - national_median) / national_median * 100)
        if diff_pct > 15:
            insights.append(f"Botox in {location.city} costs {abs(diff_pct)}% more than the national median (${national_median:,}).")
        elif diff_pct < -15:
            insights.append(f"Botox in {location.city} costs {abs(diff_pct)}% less than the national median (${national_median:,}).")
        else:
            insights.append(f"Botox in {location.city} is priced near the national median (${national_median:,}).")

    # Variant comparison (e.g. lip flip vs full face) — cheapest vs priciest treatment
    treatment_variants = [v for v in market['variant_rows'] if not v['per_unit']]
    if len(treatment_variants) >= 2:
        cheapest = min(treatment_variants, key=lambda v: v['stats']['median'])
        priciest = max(treatment_variants, key=lambda v: v['stats']['median'])
        if priciest['stats']['median'] > cheapest['stats']['median']:
            insights.append(
                f"{cheapest['name']} is the most affordable Botox treatment in {location.city} "
                f"(median ${cheapest['stats']['median']:,}), while {priciest['name']} is the priciest "
                f"(median ${priciest['stats']['median']:,})."
            )

    # Provider-type comparison
    type_stats = list(market['records'].values('provider__provider_type__name').annotate(
        avg=Avg('cash_price'), count=Count('provider_id', distinct=True)
    ).filter(count__gte=3).order_by('avg'))
    if len(type_stats) >= 2:
        cheap_t, pricey_t = type_stats[0], type_stats[-1]
        if float(pricey_t['avg']) > 0:
            savings = round((1 - float(cheap_t['avg']) / float(pricey_t['avg'])) * 100)
            if savings > 0:
                insights.append(
                    f"{cheap_t['provider__provider_type__name']}s (${int(cheap_t['avg']):,} avg) are "
                    f"{savings}% cheaper than {pricey_t['provider__provider_type__name']}s "
                    f"(${int(pricey_t['avg']):,} avg) for Botox in {location.city}."
                )

    if provider_count > 80:
        insights.append(f"With {provider_count} providers, {location.city} is a highly competitive Botox market — more options and pricing leverage for shoppers.")
    elif provider_count > 40:
        insights.append(f"{location.city} has moderate Botox competition with {provider_count} providers advertising cash prices.")

    return insights


def _nearby_cities(national_qs, location):
    """Carry-forward nearby-cities block: same-state Botox markets."""
    if not location.state:
        return []
    rows = national_qs.filter(
        provider__location__state=location.state,
    ).exclude(provider__location=location).values(
        'provider__location__slug', 'provider__location__city', 'provider__location__state',
    ).annotate(
        avg=Avg('cash_price'), count=Count('provider_id', distinct=True),
    ).filter(count__gte=5).order_by('-count')[:6]
    return [{
        'slug': r['provider__location__slug'],
        'city': r['provider__location__city'],
        'state': r['provider__location__state'],
        'avg': round(float(r['avg'])),
        'count': r['count'],
    } for r in rows if r['provider__location__slug']]


# ---------------------------------------------------------------------------
# Schema (JSON-LD)
# ---------------------------------------------------------------------------

def _hub_schema(stats, provider_count, updated_at, page_url, is_cheapest=False):
    """AggregateOffer + BreadcrumbList + DefinedTerm(Botox) as one JSON-LD graph.
    Breadcrumbs: Home > Botox (national) > Miami, FL [> Cheapest]."""
    crumbs = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://zenthir.com/"},
        {"@type": "ListItem", "position": 2, "name": "Botox", "item": "https://zenthir.com/cash/botox/"},
        {"@type": "ListItem", "position": 3, "name": "Miami, FL", "item": "https://zenthir.com/cash/botox/miami-fl/"},
    ]
    if is_cheapest:
        crumbs.append({"@type": "ListItem", "position": 4, "name": "Cheapest Botox", "item": page_url})

    graph = [
        {
            "@type": "AggregateOffer",
            "name": "Cash-pay Botox in Miami, FL",
            "priceCurrency": "USD",
            "lowPrice": stats['min'],
            "highPrice": stats['max'],
            "offerCount": provider_count,
            "availabilityStarts": updated_at.isoformat() if updated_at else None,
            "validFrom": updated_at.isoformat() if updated_at else None,
            "category": "Botox (onabotulinumtoxinA) cosmetic injection",
        },
        {
            "@type": "BreadcrumbList",
            "itemListElement": crumbs,
        },
        {
            "@type": "DefinedTerm",
            "name": "Botox",
            "description": (
                "Botox is a cosmetic injectable (onabotulinumtoxinA) used to "
                "temporarily relax facial muscles and soften dynamic wrinkles. It "
                "is typically an elective, cash-pay procedure priced per treated "
                "area or per unit."
            ),
            "inDefinedTermSet": "https://zenthir.com/cash/botox/miami-fl/",
        },
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)


def _provider_itemlist(providers, list_name):
    """ItemList JSON-LD for the ranked provider table (top rows shown)."""
    items = [{
        "@type": "ListItem",
        "position": i,
        "item": {
            "@type": "MedicalBusiness",
            "name": p['name'],
            "url": f"https://zenthir.com/provider/{p['slug']}/",
        },
    } for i, p in enumerate(providers, 1)]
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": list_name,
        "numberOfItems": len(items),
        "itemListElement": items,
    }, ensure_ascii=False)


def _botox_faqs(city_state, city, stats, cheapest_name, provider_count):
    """Per-page FAQ Q&A for the Botox wedge, drawn entirely from this page's
    aggregated data so answers are unique and citable. Mirrors build_cash_faq
    but with Botox-Miami-specific phrasing (incl. 'why prices vary')."""
    return [
        {
            'q': f"How much does Botox cost in {city}?",
            'a': (
                f"Across {provider_count} providers advertising cash prices in {city_state}, "
                f"the median price for Botox is ${stats['median']:,}. Most fall between "
                f"${stats['p25']:,} and ${stats['p75']:,}, and the full range runs "
                f"${stats['min']:,} to ${stats['max']:,}."
            ),
        },
        {
            'q': f"What is the cheapest Botox provider in {city}?",
            'a': (
                f"The lowest advertised Botox price in {city_state} is ${stats['min']:,}"
                + (f", listed by {cheapest_name}." if cheapest_name else ".")
                + " A lower price may cover fewer units or areas, so confirm exactly what's "
                "included before booking."
            ),
        },
        {
            'q': f"Why do Botox prices vary in {city}?",
            'a': (
                f"Botox prices in {city_state} span ${stats['min']:,} to ${stats['max']:,} — "
                f"about {stats['range_multiplier']}x — across {provider_count} providers. "
                "The differences reflect how many units and areas are treated, injector "
                "experience, and whether the quote is a flat treatment price or priced per unit."
            ),
        },
        {
            'q': "Does insurance cover Botox?",
            'a': (
                "Cosmetic Botox is not covered by insurance — it is an elective procedure "
                "you pay for out of pocket. Medical Botox for conditions like chronic "
                "migraines, hyperhidrosis (excessive sweating), or TMJ is sometimes covered, "
                "but requires a diagnosis and prior authorization from your insurer. All "
                "prices shown here are cash-pay advertised market estimates."
            ),
        },
    ]


# ---------------------------------------------------------------------------
# Page views
# ---------------------------------------------------------------------------

@cache_page(86400)
def botox_miami_hub(request):
    location = get_object_or_404(Location, slug=WEDGE_CITY_SLUG)
    market = build_botox_miami(location)
    display_name = "Botox"
    city_state = f"{location.city}, {location.state}"

    if market['thin_data']:
        return render(request, 'healthcare/botox_hub.html', {
            'thin_data': True, 'noindex': True,
            'provider_count': market['provider_count'],
            'thin_threshold': THIN_DATA_THRESHOLD,
            'display_name': display_name, 'city_state': city_state,
            'location': location, 'explainer_url': COST_EXPLAINER_URL,
        })

    stats = market['stats']
    updated_at = market['updated_at']
    national_median, national_qs = _national_botox_median(market['headline_procs'], market['whitelist'])
    insights = _build_insights(market, national_median, location)
    nearby = _nearby_cities(national_qs, location)

    # Answer-first citable sentence — formatted for featured-snippet extraction:
    # short, factual, self-contained, no "we found"/"updated" clause.
    answer = (
        f"Cash-pay Botox in {city_state} costs ${stats['min']:,} to ${stats['max']:,}, "
        f"median ${stats['median']:,}, across {market['provider_count']} providers."
    )

    cheapest_name = market['ranked'][0]['name'] if market['ranked'] else None
    faqs = _botox_faqs(city_state, location.city, stats, cheapest_name, market['provider_count'])
    shown = market['ranked'][:25]

    page_url = "https://zenthir.com/cash/botox/miami-fl/"
    context = {
        'thin_data': False, 'noindex': False,
        'location': location, 'display_name': display_name, 'city_state': city_state,
        'answer': answer, 'stats': stats, 'provider_count': market['provider_count'],
        'annual_low': stats['median'] * 3, 'annual_high': stats['median'] * 4,
        'ranked_providers': shown, 'total_ranked': market['provider_count'],
        'variant_rows': market['variant_rows'], 'per_unit_rows': market['per_unit_rows'],
        'price_bands': _price_bands(market['ranked'], stats),
        'insights': insights, 'nearby_cities': nearby,
        'national_median': national_median or None,
        'updated_at': updated_at,
        'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'hub_schema': _hub_schema(stats, market['provider_count'], updated_at, page_url),
        'itemlist_jsonld': _provider_itemlist(shown, f"Botox providers in {city_state} ranked by price"),
        'explainer_url': COST_EXPLAINER_URL,
        'methodology_url': '/methodology/',
        'national_url': '/cash/botox/',
        'canonical_url': page_url,
    }
    # No Set-Cookie here — this response is cache_page'd; the /wedge/event/
    # beacon establishes the per-visitor cookie on first load.
    return render(request, 'healthcare/botox_hub.html', context)


@cache_page(86400)
def botox_miami_cheapest(request):
    location = get_object_or_404(Location, slug=WEDGE_CITY_SLUG)
    market = build_botox_miami(location)
    display_name = "Botox"
    city_state = f"{location.city}, {location.state}"

    if market['thin_data']:
        return render(request, 'healthcare/botox_cheapest.html', {
            'thin_data': True, 'noindex': True,
            'provider_count': market['provider_count'],
            'thin_threshold': THIN_DATA_THRESHOLD,
            'display_name': display_name, 'city_state': city_state,
            'location': location, 'explainer_url': COST_EXPLAINER_URL,
        })

    stats = market['stats']
    updated_at = market['updated_at']
    # Highest-intent shopper page: below-median providers, ranked cheapest first.
    below = [p for p in market['ranked'] if p['price'] <= stats['median']]
    for p in below:
        p['save'] = stats['median'] - p['price']
    cheapest_price = below[0]['price'] if below else stats['min']
    savings = stats['median'] - cheapest_price

    answer = (
        f"The cheapest cash-pay Botox in {city_state} starts at ${cheapest_price:,} — "
        f"{len(below)} of {market['provider_count']} providers price at or below the "
        f"${stats['median']:,} median."
    )

    page_url = "https://zenthir.com/cash/botox/miami-fl/cheapest/"
    faqs = _botox_faqs(city_state, location.city, stats,
                       below[0]['name'] if below else None, market['provider_count'])
    context = {
        'thin_data': False, 'noindex': False,
        'location': location, 'display_name': display_name, 'city_state': city_state,
        'answer': answer, 'stats': stats, 'provider_count': market['provider_count'],
        'below_providers': below, 'below_count': len(below),
        'cheapest_price': cheapest_price, 'savings': savings,
        'updated_at': updated_at,
        'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'hub_schema': _hub_schema(stats, len(below), updated_at, page_url, is_cheapest=True),
        'explainer_url': COST_EXPLAINER_URL,
        'methodology_url': '/methodology/',
        'canonical_url': page_url,
    }
    return render(request, 'healthcare/botox_cheapest.html', context)


def _price_bands(ranked, stats):
    return {
        'below': {'range': f"Under ${stats['p25']:,}",
                  'count': sum(1 for p in ranked if p['price'] < stats['p25'])},
        'typical': {'range': f"${stats['p25']:,} — ${stats['p75']:,}",
                    'count': sum(1 for p in ranked if stats['p25'] <= p['price'] <= stats['p75'])},
        'above': {'range': f"Over ${stats['p75']:,}",
                  'count': sum(1 for p in ranked if p['price'] > stats['p75'])},
    }


# ---------------------------------------------------------------------------
# National page — /cash/botox/
# ---------------------------------------------------------------------------

NATIONAL_CITY_THRESHOLD = 15  # min providers for a city to appear in tables
# Major metros guaranteed a spot in the national "Top Cities" table.
REQUIRED_METROS = [
    'miami-fl', 'new-york-ny', 'los-angeles-ca', 'houston-tx', 'chicago-il',
    'dallas-tx', 'atlanta-ga', 'phoenix-az', 'denver-co', 'seattle-wa',
]


def _national_schema(stats, provider_count, updated_at, page_url):
    """AggregateOffer + BreadcrumbList(Home > Botox) + DefinedTerm + graph for
    the national Botox page."""
    graph = [
        {
            "@type": "AggregateOffer",
            "name": "Cash-pay Botox in the United States",
            "priceCurrency": "USD",
            "lowPrice": stats['min'],
            "highPrice": stats['max'],
            "offerCount": provider_count,
            "availabilityStarts": updated_at.isoformat() if updated_at else None,
            "validFrom": updated_at.isoformat() if updated_at else None,
            "category": "Botox (onabotulinumtoxinA) cosmetic injection",
        },
        {
            "@type": "BreadcrumbList",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://zenthir.com/"},
                {"@type": "ListItem", "position": 2, "name": "Botox", "item": page_url},
            ],
        },
        {
            "@type": "DefinedTerm",
            "name": "Botox",
            "description": (
                "Botox is a cosmetic injectable (onabotulinumtoxinA) used to temporarily "
                "relax facial muscles and soften dynamic wrinkles. It is typically an "
                "elective, cash-pay procedure priced per treated area or per unit."
            ),
            "inDefinedTermSet": page_url,
        },
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)


def _botox_national_faqs(stats, provider_count, n_cities, by_type):
    """National-level FAQ answers drawn from the aggregated national data."""
    type_line = ""
    if len(by_type) >= 2:
        cheap, pricey = by_type[0], by_type[-1]
        type_line = (f" By provider type, {cheap['name'].lower()}s average ${cheap['avg']:,} "
                     f"versus ${pricey['avg']:,} at {pricey['name'].lower()}s.")
    return [
        {
            'q': "How much does Botox cost in the US?",
            'a': (
                f"Across {provider_count:,} providers advertising cash prices in {n_cities} US cities, "
                f"the median price for a full-face Botox treatment is ${stats['median']:,}. Most "
                f"providers charge between ${stats['p25']:,} and ${stats['p75']:,}, with a national "
                f"range of ${stats['min']:,} to ${stats['max']:,}."
            ),
        },
        {
            'q': "What is the average price of Botox?",
            'a': (
                f"The national average cash price for a full-face Botox treatment is about "
                f"${stats['avg']:,}, and the median is ${stats['median']:,}.{type_line} Botox is also "
                "commonly priced per unit at roughly $10–$20 per unit, with a full face needing 40–60 units."
            ),
        },
        {
            'q': "Why does Botox cost more in some cities?",
            'a': (
                "City-to-city differences reflect local cost of living, competition, and provider mix "
                "(med spas versus plastic surgery practices). High-cost metros tend to price above the "
                f"${stats['median']:,} national median, while smaller markets often price below it."
            ),
        },
        {
            'q': "Does insurance cover Botox?",
            'a': (
                "Cosmetic Botox is not covered by insurance — it is an elective, cash-pay procedure. "
                "Medical Botox for conditions like chronic migraines, hyperhidrosis, or TMJ is sometimes "
                "covered, but requires a diagnosis and prior authorization. All prices shown here are cash-pay."
            ),
        },
    ]


@cache_page(86400)
def botox_national(request):
    variants = _wedge_variants()
    treatment_procs = [v for v in variants if v.slug.startswith('botox')]
    if not treatment_procs:
        raise Http404("No Botox procedures configured")

    whitelist = _variant_whitelist(treatment_procs)
    recovered = _recovered_ids(treatment_procs)  # national
    records = _records_for(treatment_procs, None, whitelist, extra_ids=recovered)

    # One bounded pull: (city_slug, city, state, price) per provider record.
    rows = list(records.values_list(
        'provider__location__slug', 'provider__location__city',
        'provider__location__state', 'cash_price',
    ))
    if not rows:
        raise Http404("No Botox pricing data")

    # National stats — drop obvious low outliers (< 10% of median) for a clean range.
    raw = sorted(float(r[3]) for r in rows)
    prelim_median = raw[len(raw) // 2]
    floor = prelim_median * 0.10
    prices = [p for p in raw if p >= floor]
    stats = price_stats(prices)
    provider_count = len(rows)
    updated_at = records.aggregate(m=Max('updated_at'))['m']

    # By-city medians (Python group; one pass).
    from collections import defaultdict
    city_prices = defaultdict(list)
    city_meta = {}
    for slug, city, state, price in rows:
        if not slug or is_malformed_location(city, state):
            continue
        city_prices[slug].append(float(price))
        city_meta[slug] = (city, state)

    cities = []
    for slug, plist in city_prices.items():
        if len(plist) < NATIONAL_CITY_THRESHOLD:
            continue
        plist.sort()
        city, state = city_meta[slug]
        cities.append({
            'slug': slug, 'city': city, 'state': state, 'count': len(plist),
            'median': round(plist[len(plist) // 2]),
            'low': round(plist[0]), 'high': round(plist[-1]),
            'url': ('/cash/botox/miami-fl/' if slug == 'miami-fl'
                    else f'/cash/botox-full-face/{slug}/'),
        })

    # Top cities = the named major metros (guaranteed) + the largest markets by
    # provider count, sorted by count. Ensures NYC/Chicago/etc. always appear.
    by_slug = {c['slug']: c for c in cities}
    chosen = {s for s in REQUIRED_METROS if s in by_slug}
    for c in sorted(cities, key=lambda c: -c['count'])[:15]:
        chosen.add(c['slug'])
    top_cities = sorted((by_slug[s] for s in chosen), key=lambda c: -c['count'])[:18]
    affordable = sorted(cities, key=lambda c: c['median'])[:8]
    expensive = sorted(cities, key=lambda c: -c['median'])[:8]

    # Average price by (credible) provider type — clean med spa vs practice compare.
    by_type = [{
        'name': r['provider__provider_type__name'],
        'avg': round(float(r['avg'])),
        'count': r['n'],
    } for r in records.filter(provider__provider_type__name__in=whitelist).values(
        'provider__provider_type__name',
    ).annotate(avg=Avg('cash_price'), n=Count('provider_id', distinct=True)).order_by('avg')]

    answer = (
        f"Cash-pay Botox in the US costs ${stats['min']:,} to ${stats['max']:,}, "
        f"median ${stats['median']:,}, across {provider_count:,} providers."
    )

    faqs = _botox_national_faqs(stats, provider_count, len(cities), by_type)
    page_url = "https://zenthir.com/cash/botox/"
    context = {
        'answer': answer, 'stats': stats, 'provider_count': provider_count,
        'n_cities': len(cities), 'updated_at': updated_at,
        'top_cities': top_cities, 'affordable': affordable, 'expensive': expensive,
        'by_type': by_type,
        'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'national_schema': _national_schema(stats, provider_count, updated_at, page_url),
        'methodology_url': '/methodology/',
        'canonical_url': page_url,
        'annual_low': stats['median'] * 3, 'annual_high': stats['median'] * 4,
    }
    return render(request, 'healthcare/botox_national.html', context)


# ---------------------------------------------------------------------------
# Capture endpoints (csrf_exempt JSON — cached pages can't carry a live token)
# ---------------------------------------------------------------------------

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def _json_body(request):
    try:
        return json.loads(request.body.decode('utf-8') or '{}')
    except (ValueError, UnicodeDecodeError):
        return {}


def _resolve_provider(slug):
    if not slug:
        return None
    return Provider.objects.filter(slug=slug).first()


@csrf_exempt
@require_POST
def capture_lead(request):
    """The billable event: a shopper asks for a price / to be connected."""
    data = _json_body(request)
    if data.get('company'):  # honeypot
        return JsonResponse({'ok': True})
    name = (data.get('name') or '').strip()[:200]
    email = (data.get('email') or '').strip()[:254]
    if not name or not EMAIL_RE.match(email):
        return JsonResponse({'ok': False, 'error': 'Enter your name and a valid email.'}, status=400)

    provider = _resolve_provider((data.get('provider_slug') or '').strip())
    resp = JsonResponse({'ok': True})
    vid = _visitor_and_cookie(request, resp)
    lead = ConsumerLead.objects.create(
        procedure_slug=WEDGE_PROCEDURE_SLUG, city_slug=WEDGE_CITY_SLUG,
        provider=provider,
        provider_name=(provider.name if provider else (data.get('provider_name') or '').strip()[:500]),
        contact_name=name, contact_email=email,
        contact_phone=(data.get('phone') or '').strip()[:40],
        variant_interest=(data.get('variant') or '').strip()[:200],
        message=(data.get('message') or '').strip()[:2000],
        source_page=(data.get('page') or '').strip()[:40],
        visitor_id=vid,
    )
    _log_event('lead_submit', request=request, visitor_id=vid, page=lead.source_page,
               provider=provider, provider_slug=lead.provider_name)
    _notify_lead(lead)
    return resp


@csrf_exempt
@require_POST
def capture_notify(request):
    """Consumer email capture — notify if Botox prices drop in Miami."""
    data = _json_body(request)
    if data.get('company'):  # honeypot
        return JsonResponse({'ok': True})
    email = (data.get('email') or '').strip()[:254]
    if not EMAIL_RE.match(email):
        return JsonResponse({'ok': False, 'error': 'Enter a valid email.'}, status=400)
    resp = JsonResponse({'ok': True})
    vid = _visitor_and_cookie(request, resp)
    PriceAlertSignup.objects.get_or_create(
        email=email, procedure_slug=WEDGE_PROCEDURE_SLUG, city_slug=WEDGE_CITY_SLUG,
        defaults={'source_page': (data.get('page') or '').strip()[:40], 'visitor_id': vid},
    )
    _log_event('email_signup', request=request, visitor_id=vid,
               page=(data.get('page') or '').strip()[:40])
    return resp


@csrf_exempt
@require_POST
def track_event(request):
    """Funnel instrumentation beacon (page_view, lead_open, provider_click, …)."""
    data = _json_body(request)
    etype = (data.get('type') or '').strip()
    valid = {t[0] for t in WedgeEvent.EVENT_TYPES}
    if etype not in valid:
        return JsonResponse({'ok': False}, status=400)
    provider = _resolve_provider((data.get('provider_slug') or '').strip())
    resp = JsonResponse({'ok': True})
    vid = _visitor_and_cookie(request, resp)
    _log_event(etype, request=request, visitor_id=vid,
               page=(data.get('page') or '').strip()[:40],
               provider=provider, provider_slug=(data.get('provider_slug') or '').strip()[:200])
    return resp


def _notify_lead(lead):
    """Email the team on a new lead (best-effort, never blocks the response)."""
    from django.core.mail import send_mail
    try:
        send_mail(
            subject=f'[Zenthir] New Botox/Miami lead: {lead.contact_name}',
            message=(
                f'Consumer lead captured.\n\n'
                f'Name: {lead.contact_name}\nEmail: {lead.contact_email}\n'
                f'Phone: {lead.contact_phone}\n'
                f'Interested provider: {lead.provider_name or "(any)"}\n'
                f'Variant: {lead.variant_interest}\n'
                f'Source page: {lead.source_page}\n'
                f'Message: {lead.message}\n'
            ),
            from_email='noreply@zenthir.com',
            recipient_list=['leshane@ethicalvista.com'],
            fail_silently=True,
        )
    except Exception:
        pass
