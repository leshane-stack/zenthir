"""
Botox-in-Miami test wedge.

Scope: ONE wedge only — Botox, Miami. The goal is to capture real consumer
leads (the billable event) so medspas can be pitched on paying for them. These
views are deliberately isolated from the generic cash-pay views (views_cash.py)
so the wedge can be tuned without touching every cash page.

Pages (routed explicitly, BEFORE the generic /cash/<proc>/<city>/ pattern):
    /cash/botox/miami-fl/            -> botox_miami_hub       (head-term hub)
    /cash/botox/miami-fl/best/       -> botox_miami_best      ("best botox" head-term)
    /cash/botox/miami-fl/cheapest/   -> botox_miami_cheapest  (highest-intent)
    /cash/botox/miami-fl/<type>/     -> botox_type_filter     (provider-type facets)

The type-filter view is a REUSABLE pattern: /cash/<hub>/<city>/<type>/ maps a
type slug (med-spas, plastic-surgeons, dermatologists, clinics) to a provider
type and renders a stats-from-the-subset page. Only Botox+Miami is wired today,
but the view works for any procedure hub + city + type once the hub's variants
are configured.

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
from collections import Counter

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

# --- Provider-type facets ---------------------------------------------------
# URL type-slug -> ProviderType.name. The generic 'Clinic' bucket is included
# but is served through the aesthetic-name recovery filter (see build_botox_type)
# so it isn't the contaminated raw bucket.
TYPE_SLUG_MAP = {
    'med-spas': 'Med Spa',
    'plastic-surgeons': 'Plastic Surgery Practice',
    'dermatologists': 'Dermatology',
    'clinics': 'Clinic',
}
# Display metadata per provider-type name (headings, pill labels, prose).
TYPE_META = {
    'Med Spa': {
        'slug': 'med-spas', 'plural': 'Med Spas', 'singular': 'Med Spa',
        'pill': 'Med Spas',
    },
    'Plastic Surgery Practice': {
        'slug': 'plastic-surgeons', 'plural': 'Plastic Surgery Practices',
        'singular': 'Plastic Surgery Practice', 'pill': 'Plastic Surgeons',
    },
    'Dermatology': {
        'slug': 'dermatologists', 'plural': 'Dermatology Practices',
        'singular': 'Dermatology Practice', 'pill': 'Dermatologists',
    },
    'Clinic': {
        'slug': 'clinics', 'plural': 'Aesthetic Clinics', 'singular': 'Aesthetic Clinic',
        'pill': 'Clinics',
    },
}
# Order the provider-type pills render in on the hub.
TYPE_PILL_ORDER = ['Med Spa', 'Plastic Surgery Practice', 'Dermatology', 'Clinic']
# A type facet needs at least this many providers to get a pill / an indexable page.
TYPE_MIN_PROVIDERS = 3

# --- Best-provider composite (transparent, documented on-page) --------------
# Weights sum to 100. Every input is public page data; ranking is never buyable.
BEST_W_PRICE = 35     # price competitiveness (at/below the median scores highest)
BEST_W_BREADTH = 25   # number of procedures listed (more = more established)
BEST_W_VERIFIED = 25  # claimed / verified provider profile
BEST_W_TYPE = 15      # provider-type relevance for Botox
BEST_PROC_CAP = 10    # procedures listed beyond this add no further score

# --- Miami Botox Price Report -----------------------------------------------
# ZIP -> Miami district. Each ZIP maps to exactly one district; ZIP->district is
# a factual geographic grouping (Miami-Dade), not fabricated. Districts with
# fewer than REPORT_MIN_DISTRICT providers are omitted (not enough data).
MIAMI_ZIP_DISTRICT = {
    '33131': 'Brickell & Downtown', '33129': 'Brickell & Downtown',
    '33130': 'Brickell & Downtown', '33132': 'Brickell & Downtown',
    '33128': 'Brickell & Downtown',
    '33137': 'Edgewater, Midtown & Wynwood', '33127': 'Edgewater, Midtown & Wynwood',
    '33150': 'Edgewater, Midtown & Wynwood', '33136': 'Edgewater, Midtown & Wynwood',
    '33133': 'Coconut Grove',
    '33134': 'Coral Gables', '33146': 'Coral Gables', '33145': 'Coral Gables',
    '33143': 'Coral Gables', '33156': 'Coral Gables', '33158': 'Coral Gables',
    '33114': 'Coral Gables',
    '33139': 'Miami Beach', '33140': 'Miami Beach', '33141': 'Miami Beach',
    '33154': 'Miami Beach', '33109': 'Miami Beach', '33119': 'Miami Beach',
    '33125': 'Little Havana & West', '33135': 'Little Havana & West',
    '33126': 'Little Havana & West', '33144': 'Little Havana & West',
    '33155': 'Little Havana & West', '33142': 'Little Havana & West',
    '33165': 'Kendall & South Miami', '33173': 'Kendall & South Miami',
    '33176': 'Kendall & South Miami', '33183': 'Kendall & South Miami',
    '33186': 'Kendall & South Miami', '33175': 'Kendall & South Miami',
    '33174': 'Kendall & South Miami',
}
REPORT_MIN_DISTRICT = 8
# Metros compared against Miami in the report (medians are dedup-robust).
REPORT_COMPARE_METROS = [
    'new-york-ny', 'los-angeles-ca', 'houston-tx', 'chicago-il', 'dallas-tx', 'atlanta-ga',
]


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
        insights.append(f"With {provider_count} providers, {location.city} is a highly competitive Botox market, with more options and pricing leverage for shoppers.")
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
    """ItemList JSON-LD for a ranked provider table — each provider a ListItem
    with position, name, and its advertised Botox price (as an Offer)."""
    items = [{
        "@type": "ListItem",
        "position": i,
        "item": {
            "@type": "MedicalBusiness",
            "name": p['name'],
            "url": f"https://zenthir.com/provider/{p['slug']}/",
            "makesOffer": {
                "@type": "Offer",
                "priceCurrency": "USD",
                "price": p['price'],
                "category": "Botox (onabotulinumtoxinA) cosmetic injection",
            },
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
                f"Botox prices in {city_state} span ${stats['min']:,} to ${stats['max']:,}, "
                f"about {stats['range_multiplier']}x, across {provider_count} providers. "
                "The differences reflect how many units and areas are treated, injector "
                "experience, and whether the quote is a flat treatment price or priced per unit."
            ),
        },
        {
            'q': "Does insurance cover Botox?",
            'a': (
                "Cosmetic Botox is not covered by insurance. It is an elective procedure "
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
    type_pills = _type_pills(market['ranked'], city_slug=location.slug)

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
        'type_pills': type_pills,
        'best_url': '/cash/botox/miami-fl/best/',
        'report_url': '/cash/botox/miami-fl/report/',
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
        f"The cheapest cash-pay Botox in {city_state} starts at ${cheapest_price:,}. "
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
        'itemlist_jsonld': _provider_itemlist(below, f"Cheapest Botox providers in {city_state}"),
        'explainer_url': COST_EXPLAINER_URL,
        'methodology_url': '/methodology/',
        'hub_url': '/cash/botox/miami-fl/',
        'canonical_url': page_url,
    }
    return render(request, 'healthcare/botox_cheapest.html', context)


def _price_bands(ranked, stats):
    return {
        'below': {'range': f"Under ${stats['p25']:,}",
                  'count': sum(1 for p in ranked if p['price'] < stats['p25'])},
        'typical': {'range': f"${stats['p25']:,} to ${stats['p75']:,}",
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
                "Cosmetic Botox is not covered by insurance. It is an elective, cash-pay procedure. "
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
# Provider-type facet pages — /cash/botox/miami-fl/<type>/
#
# One reusable view over a (procedure hub, city, provider type). Stats are
# computed from the filtered subset ONLY, so each facet page is unique. The
# generic 'Clinic' bucket is served through the same aesthetic-name recovery
# filter the hub uses, so it stays clean.
# ---------------------------------------------------------------------------

def _type_pills(ranked, city_slug):
    """Provider-type facet pills for the hub — only types with >= TYPE_MIN_PROVIDERS
    providers in the ranked set, in a fixed order, each linking to its facet page."""
    counts = Counter(p['type'] for p in ranked)
    pills = []
    for tname in TYPE_PILL_ORDER:
        n = counts.get(tname, 0)
        if n >= TYPE_MIN_PROVIDERS and tname in TYPE_META:
            meta = TYPE_META[tname]
            pills.append({
                'label': meta['pill'], 'count': n,
                'url': f"/cash/{WEDGE_PROCEDURE_SLUG}/{city_slug}/{meta['slug']}/",
            })
    return pills


def build_botox_type(location, type_name):
    """Botox market snapshot for ONE provider type in one city — the engine
    behind the facet pages. Stats come from the filtered subset only. Returns
    None if the subset is empty."""
    variants = _wedge_variants()
    treatment_procs = [v for v in variants if v.slug.startswith('botox')]
    if not treatment_procs:
        return None

    base = PricingRecord.objects.filter(
        procedure__in=treatment_procs, cash_price__isnull=False,
        provider__location=location,
    ).exclude(cash_price=0)
    if type_name == 'Clinic':
        # Don't render the raw contaminated 'Clinic' bucket — keep only names that
        # classify as credible aesthetic providers (same rule as the hub).
        base = base.filter(provider_id__in=_recovered_ids(treatment_procs, location))
    else:
        base = base.filter(provider__provider_type__name=type_name)

    tagged = base.filter(price_category='cash_price')
    records = tagged if tagged.exists() else base
    ranked, _dropped = dedupe_ranked_providers(records)
    if not ranked:
        return None

    stats = price_stats([p['price'] for p in ranked])
    _assign_bands(ranked, stats['p25'], stats['p75'])
    _mark_lead_enabled(ranked)
    return {
        'stats': stats, 'ranked': ranked, 'provider_count': len(ranked),
        'records': records, 'updated_at': _market_updated_at(records),
    }


# Type-specific FAQ Q&A (safety + differentiation). A computed price question is
# prepended per-page. Answers are static factual copy, not editorial claims.
TYPE_FAQ_BANK = {
    'Med Spa': [
        ("Are med spas safe for Botox?",
         "Yes, when Botox is administered by a licensed injector (a nurse, nurse "
         "practitioner, physician assistant, or physician) working under medical "
         "supervision. Med spas perform a high volume of injectables, so their "
         "injectors are often very experienced with Botox specifically. Confirm who "
         "will perform your injection and that a supervising physician is on record."),
        ("What's the difference between med spa and plastic surgeon Botox?",
         "The product and technique are the same; the setting differs. Med spas focus "
         "on non-surgical aesthetics and often price Botox lower, while plastic "
         "surgery practices offer Botox alongside surgical options and may charge a "
         "premium for the surgeon's involvement. For a routine Botox treatment, a "
         "reputable med spa and a plastic surgeon deliver comparable results."),
        ("Do med spas use the same Botox?",
         "Yes. Botox (onabotulinumtoxinA) is a single FDA-approved product from "
         "Allergan; a med spa buys the identical vials a dermatologist or plastic "
         "surgeon does. Price differences reflect units used, injector time, and "
         "overhead, not a different or 'watered-down' product. Ask how many units "
         "your quote covers so you're comparing like for like."),
    ],
    'Plastic Surgery Practice': [
        ("Are plastic surgery practices good for Botox?",
         "Yes. Botox at a plastic surgery practice is typically performed by or under "
         "a board-certified plastic surgeon or dermatologist, and the practice can "
         "advise on surgical options if Botox alone won't achieve your goal. Prices "
         "often sit at the higher end of the market, reflecting that clinical depth."),
        ("What's the difference between a plastic surgeon and a med spa for Botox?",
         "The Botox itself is identical. A plastic surgery practice offers it within a "
         "surgical setting and may price at a premium for the physician's involvement, "
         "while med spas specialize in non-surgical aesthetics and often price lower. "
         "For a standard Botox treatment both can deliver comparable results."),
        ("Do plastic surgeons use the same Botox?",
         "Yes, the same FDA-approved onabotulinumtoxinA product. What you pay for at a "
         "plastic surgery practice is the injector's expertise and the practice's "
         "clinical setting, not a different product. Confirm the unit count in your "
         "quote to compare prices accurately."),
    ],
    'Dermatology': [
        ("Are dermatologists good for Botox?",
         "Yes. Dermatologists are physicians who specialize in skin and are among the "
         "most experienced Botox injectors. A dermatology practice can also treat the "
         "underlying skin conditions that affect how your results look."),
        ("What's the difference between a dermatologist and a med spa for Botox?",
         "The product is the same. Dermatology practices bring physician-level skin "
         "expertise and often price in the middle of the market, while med spas focus "
         "on aesthetics and frequently price lower. Both use identical Botox."),
        ("Do dermatologists use the same Botox?",
         "Yes, the identical FDA-approved onabotulinumtoxinA. Price differences reflect "
         "units, injector time, and overhead, not the product itself."),
    ],
    'Clinic': [
        ("Are aesthetic clinics safe for Botox?",
         "A credible aesthetic clinic with a licensed injector under medical supervision "
         "is a safe setting for Botox. Confirm the injector's credentials and that a "
         "supervising physician is on record before booking."),
        ("What's the difference between a clinic and a med spa for Botox?",
         "The Botox is the same. Terminology varies, and many aesthetic clinics operate "
         "much like med spas. Focus on the injector's experience and the all-in unit "
         "price rather than the label."),
        ("Do clinics use the same Botox?",
         "Yes, the same FDA-approved onabotulinumtoxinA product. Ask how many units "
         "your quote covers so you can compare prices fairly."),
    ],
}


def _type_faqs(type_name, type_meta, city_state, city, stats, overall_median):
    """Facet FAQ: a computed price question drawn from the subset, then the
    type-specific safety/difference Q&A."""
    compare_line = ""
    if overall_median and stats['avg']:
        diff = stats['avg'] - overall_median
        if abs(diff) / overall_median >= 0.03:
            pct = round(abs(diff) / overall_median * 100)
            word = "above" if diff > 0 else "below"
            compare_line = (f" That averages about {pct}% {word} the ${overall_median:,} "
                            f"overall {city} median.")
        else:
            compare_line = f" That is close to the ${overall_median:,} overall {city} median."
    faqs = [{
        'q': f"How much does Botox cost at {type_meta['plural'].lower()} in {city}?",
        'a': (
            f"Across {stats['count']} {type_meta['plural'].lower()} advertising cash "
            f"prices in {city_state}, the median Botox price is ${stats['median']:,}, "
            f"with most between ${stats['p25']:,} and ${stats['p75']:,} and a full range "
            f"of ${stats['min']:,} to ${stats['max']:,}.{compare_line}"
        ),
    }]
    for q, a in TYPE_FAQ_BANK.get(type_name, []):
        faqs.append({'q': q, 'a': a})
    return faqs


def _type_schema(stats, provider_count, updated_at, page_url, type_meta, city_state):
    """AggregateOffer (with validFrom) + BreadcrumbList as one graph. FAQPage is
    emitted separately by the template."""
    crumbs = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://zenthir.com/"},
        {"@type": "ListItem", "position": 2, "name": "Botox", "item": "https://zenthir.com/cash/botox/"},
        {"@type": "ListItem", "position": 3, "name": "Miami, FL", "item": "https://zenthir.com/cash/botox/miami-fl/"},
        {"@type": "ListItem", "position": 4, "name": type_meta['plural'], "item": page_url},
    ]
    graph = [
        {
            "@type": "AggregateOffer",
            "name": f"Cash-pay Botox at {type_meta['plural']} in {city_state}",
            "priceCurrency": "USD",
            "lowPrice": stats['min'],
            "highPrice": stats['max'],
            "offerCount": provider_count,
            "availabilityStarts": updated_at.isoformat() if updated_at else None,
            "validFrom": updated_at.isoformat() if updated_at else None,
            "category": "Botox (onabotulinumtoxinA) cosmetic injection",
        },
        {"@type": "BreadcrumbList", "itemListElement": crumbs},
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)


@cache_page(86400)
def botox_type_filter(request, procedure_hub_slug, city_slug, type_slug):
    """Reusable provider-type facet page. Wired for the 'botox' hub today; other
    hubs 404 until their variants are configured."""
    if procedure_hub_slug != WEDGE_PROCEDURE_SLUG:
        raise Http404("Unknown procedure hub")
    type_name = TYPE_SLUG_MAP.get(type_slug)
    if not type_name:
        raise Http404("Unknown provider type")

    location = get_object_or_404(Location, slug=city_slug)
    display_name = "Botox"
    city_state = f"{location.city}, {location.state}"
    type_meta = TYPE_META[type_name]

    overall = build_botox_miami(location)
    overall_median = 0 if overall.get('thin_data') else overall['stats']['median']
    market = build_botox_type(location, type_name)
    count = market['provider_count'] if market else 0

    if not market or count < TYPE_MIN_PROVIDERS:
        return render(request, 'healthcare/botox_type.html', {
            'thin_data': True, 'noindex': True,
            'provider_count': count, 'thin_threshold': TYPE_MIN_PROVIDERS,
            'display_name': display_name, 'city_state': city_state,
            'type_meta': type_meta, 'location': location,
            'hub_url': f'/cash/botox/{city_slug}/',
        })

    stats = market['stats']
    updated_at = market['updated_at']
    shown = market['ranked'][:25]

    answer = (
        f"Cash-pay Botox at {type_meta['plural'].lower()} in {city_state} costs "
        f"${stats['min']:,} to ${stats['max']:,}, median ${stats['median']:,}, "
        f"across {count} providers."
    )

    # How this type compares to the overall city median.
    compare = None
    if overall_median:
        diff = stats['avg'] - overall_median
        pct = round(abs(diff) / overall_median * 100)
        if diff > 0:
            direction, cheaper = 'more expensive than', False
        elif diff < 0:
            direction, cheaper = 'cheaper than', True
        else:
            direction, cheaper = 'in line with', None
        compare = {
            'avg': stats['avg'], 'overall_median': overall_median,
            'pct': pct, 'direction': direction, 'cheaper': cheaper,
        }

    faqs = _type_faqs(type_name, type_meta, city_state, location.city, stats, overall_median)
    page_url = f"https://zenthir.com/cash/{WEDGE_PROCEDURE_SLUG}/{city_slug}/{type_slug}/"

    # Sibling facets to link across (other types with a page).
    other_types = [
        {'label': TYPE_META[t]['pill'], 'url': f"/cash/{WEDGE_PROCEDURE_SLUG}/{city_slug}/{TYPE_META[t]['slug']}/"}
        for t in TYPE_PILL_ORDER if t != type_name
    ]

    context = {
        'thin_data': False, 'noindex': False,
        'location': location, 'display_name': display_name, 'city_state': city_state,
        'type_meta': type_meta, 'type_slug': type_slug,
        'answer': answer, 'stats': stats, 'provider_count': count,
        'ranked_providers': shown, 'total_ranked': count,
        'price_bands': _price_bands(market['ranked'], stats),
        'compare': compare, 'updated_at': updated_at,
        'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'type_schema': _type_schema(stats, count, updated_at, page_url, type_meta, city_state),
        'itemlist_jsonld': _provider_itemlist(
            shown, f"Botox at {type_meta['plural']} in {city_state} ranked by price"),
        'other_types': other_types,
        'methodology_url': '/methodology/',
        'hub_url': f'/cash/botox/{city_slug}/',
        'best_url': f'/cash/botox/{city_slug}/best/',
        'cheapest_url': f'/cash/botox/{city_slug}/cheapest/',
        'national_url': '/cash/botox/',
        'canonical_url': page_url,
    }
    return render(request, 'healthcare/botox_type.html', context)


# ---------------------------------------------------------------------------
# Best-providers page — /cash/botox/miami-fl/best/
#
# Data-ranked, never editorial: a transparent composite over price
# competitiveness, procedures listed, verification, and provider-type
# relevance. Ranking position is never influenced by payment.
# ---------------------------------------------------------------------------

def _procedure_counts(provider_ids):
    """Distinct cash-pay procedures listed per provider — a rough 'how
    established' signal for the Best ranking. One bounded GROUP BY, ids only."""
    if not provider_ids:
        return {}
    rows = (PricingRecord.objects
            .filter(provider_id__in=provider_ids, cash_price__gt=0)
            .values('provider_id')
            .annotate(n=Count('procedure', distinct=True)))
    return {r['provider_id']: r['n'] for r in rows}


def _rank_best(ranked, stats):
    """Assign a transparent composite score (0–100) to each ranked provider dict,
    in place. All inputs are public page data; ranking is never buyable."""
    median, mn, mx = stats['median'], stats['min'], stats['max']
    for p in ranked:
        price = p['price']
        # 1. Price competitiveness — at/below the median scores highest.
        if price <= median:
            below = (median - price) / (median - mn) if median > mn else 0.0
            price_score = BEST_W_PRICE * (0.85 + 0.15 * below)
        else:
            span = mx - median
            price_score = BEST_W_PRICE * max(0.0, 1 - (price - median) / span) if span > 0 else 0.0
        # 2. Procedures listed — more = more established (capped).
        breadth = BEST_W_BREADTH * min(1.0, p.get('proc_count', 1) / BEST_PROC_CAP)
        # 3. Verification — claimed/verified providers rank higher.
        verified = BEST_W_VERIFIED if p.get('lead_enabled') else 0
        # 4. Provider-type relevance for Botox.
        t = p['type'] or ''
        if t in ('Med Spa', 'Plastic Surgery Practice'):
            type_score = BEST_W_TYPE
        elif t == 'Dermatology':
            type_score = BEST_W_TYPE * 0.8
        else:
            type_score = BEST_W_TYPE * 0.4
        p['score'] = round(price_score + breadth + verified + type_score, 1)


def _assign_best_tiers(best, stats):
    """Attach a rank number + a single tier badge to each top provider."""
    p25 = stats['p25']
    for i, p in enumerate(best, 1):
        p['best_rank'] = i
        if i <= 5:
            p['tier'], p['tier_class'] = 'Top Rated', 'tier-top'
        elif p.get('lead_enabled'):
            p['tier'], p['tier_class'] = 'Verified', 'tier-verified'
        elif p['price'] <= p25:
            p['tier'], p['tier_class'] = 'Great Value', 'tier-value'
        else:
            p['tier'], p['tier_class'] = '', ''


def _best_faqs(city_state, city, stats, provider_count):
    """FAQ for the Best page — methodology-forward, drawn from page data."""
    return [
        {
            'q': "What makes a Botox provider the best?",
            'a': (
                f"On Zenthir, “best” is data-ranked, not editorial. A provider ranks "
                f"higher when its advertised cash price is competitive against the "
                f"${stats['median']:,} {city_state} median, it lists more procedures (a sign "
                f"of an established practice), it has claimed or verified its profile, and its "
                f"provider type (med spa, plastic surgery practice, or dermatology) is "
                f"relevant to Botox."
            ),
        },
        {
            'q': "How are the rankings calculated?",
            'a': (
                f"Each of the {provider_count} providers gets a composite score from four "
                f"public signals: price competitiveness ({BEST_W_PRICE}%), number of "
                f"procedures listed ({BEST_W_BREADTH}%), verification status "
                f"({BEST_W_VERIFIED}%), and provider-type relevance ({BEST_W_TYPE}%). Scores "
                f"are computed from advertised market data only, with no reviews, ads, or "
                f"editorial opinion."
            ),
        },
        {
            'q': "Can providers pay for a higher ranking?",
            'a': (
                "No, never. Ranking position cannot be bought. Claiming a profile lets a "
                "provider correct its information and receive quote requests, but it does not "
                "move it up the list. Payment never influences rank."
            ),
        },
        {
            'q': f"Who is the highest-ranked Botox provider in {city}?",
            'a': (
                f"Rankings update as pricing data changes, so the order reflects the latest "
                f"snapshot. The table above lists the current top-ranked providers in "
                f"{city_state}, each with its price, type, and tier. Always confirm the all-in "
                f"price directly with the provider before booking."
            ),
        },
    ]


def _best_schema(page_url):
    """BreadcrumbList for the Best page: Home > Botox > Miami, FL > Best Providers.
    ItemList + FAQPage are emitted separately by the template."""
    crumbs = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://zenthir.com/"},
        {"@type": "ListItem", "position": 2, "name": "Botox", "item": "https://zenthir.com/cash/botox/"},
        {"@type": "ListItem", "position": 3, "name": "Miami, FL", "item": "https://zenthir.com/cash/botox/miami-fl/"},
        {"@type": "ListItem", "position": 4, "name": "Best Providers", "item": page_url},
    ]
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": crumbs,
    }, ensure_ascii=False)


@cache_page(86400)
def botox_miami_best(request):
    location = get_object_or_404(Location, slug=WEDGE_CITY_SLUG)
    market = build_botox_miami(location)
    display_name = "Botox"
    city_state = f"{location.city}, {location.state}"

    if market['thin_data']:
        return render(request, 'healthcare/botox_best.html', {
            'thin_data': True, 'noindex': True,
            'provider_count': market['provider_count'],
            'thin_threshold': THIN_DATA_THRESHOLD,
            'display_name': display_name, 'city_state': city_state,
            'location': location, 'hub_url': '/cash/botox/miami-fl/',
        })

    stats = market['stats']
    updated_at = market['updated_at']
    ranked = market['ranked']

    counts = _procedure_counts([p['provider_id'] for p in ranked])
    for p in ranked:
        p['proc_count'] = counts.get(p['provider_id'], 1)
    _rank_best(ranked, stats)
    full_ranked = sorted(ranked, key=lambda p: (-p['score'], p['price']))
    best = full_ranked[:25]
    _assign_best_tiers(best, stats)

    answer = (
        f"Based on pricing, verification status, and procedure range, these are the "
        f"top-ranked Botox providers in {location.city} across {market['provider_count']} providers."
    )
    faqs = _best_faqs(city_state, location.city, stats, market['provider_count'])
    page_url = "https://zenthir.com/cash/botox/miami-fl/best/"

    # --- Data-driven decision content (every number pulled from this market) ---
    top_type_counts = Counter(p['type'] for p in best)
    top25_avg = round(sum(p['price'] for p in best) / len(best))
    top_provider = best[0]
    cheapest = min(ranked, key=lambda p: p['price'])
    cheapest_rank = next(i for i, p in enumerate(full_ranked, 1)
                         if p['provider_id'] == cheapest['provider_id'])
    type_rows, _prem = _type_premium(ranked)
    type_medians = {r['type']: r for r in type_rows}
    data_insights = {
        'top25_avg': top25_avg,
        'market_avg': stats['avg'],
        'top25_below_market_pct': (round((stats['avg'] - top25_avg) / stats['avg'] * 100)
                                   if stats['avg'] else 0),
        'top25_low': min(p['price'] for p in best),
        'top25_high': max(p['price'] for p in best),
        'top_med_spa': top_type_counts.get('Med Spa', 0),
        'top_plastic': top_type_counts.get('Plastic Surgery Practice', 0),
        'top_derm': top_type_counts.get('Dermatology', 0),
        'top_clinic': top_type_counts.get('Clinic', 0),
        'dominant_type': top_type_counts.most_common(1)[0] if top_type_counts else ('', 0),
        'top_provider_name': top_provider['name'],
        'top_provider_price': top_provider['price'],
        'top_provider_type': top_provider['type'],
        'cheapest_name': cheapest['name'],
        'cheapest_price': cheapest['price'],
        'cheapest_type': cheapest['type'],
        'cheapest_rank': cheapest_rank,
        'med_spa_median': (type_medians.get('Med Spa') or {}).get('median'),
        'plastic_median': (type_medians.get('Plastic Surgery Practice') or {}).get('median'),
    }

    context = {
        'thin_data': False, 'noindex': False,
        'location': location, 'display_name': display_name, 'city_state': city_state,
        'answer': answer, 'stats': stats, 'provider_count': market['provider_count'],
        'best_providers': best, 'total_ranked': market['provider_count'],
        'updated_at': updated_at, 'data_insights': data_insights,
        'report_url': '/cash/botox/miami-fl/report/',
        'weights': {
            'price': BEST_W_PRICE, 'breadth': BEST_W_BREADTH,
            'verified': BEST_W_VERIFIED, 'type': BEST_W_TYPE,
        },
        'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'best_schema': _best_schema(page_url),
        'itemlist_jsonld': _provider_itemlist(best, f"Best Botox providers in {city_state}"),
        'methodology_url': '/methodology/',
        'hub_url': '/cash/botox/miami-fl/',
        'cheapest_url': '/cash/botox/miami-fl/cheapest/',
        'national_url': '/cash/botox/',
        'canonical_url': page_url,
    }
    return render(request, 'healthcare/botox_best.html', context)


# ---------------------------------------------------------------------------
# Miami Botox Price Report — /cash/botox/miami-fl/report/
#
# Flagship market-intelligence page (Zillow-report style, not a clinic blog).
# Every figure is computed from this market's own data + the national dataset.
# No "what is Botox" education, no editorial opinion.
# ---------------------------------------------------------------------------

def _price_distribution(prices):
    """Share of providers in each price band — computed, not assumed."""
    n = len(prices)
    bands = [
        ('Under $300', lambda p: p < 300),
        ('$300–$400', lambda p: 300 <= p < 400),
        ('$400–$500', lambda p: 400 <= p < 500),
        ('$500 and up', lambda p: p >= 500),
    ]
    out = []
    for label, fn in bands:
        c = sum(1 for p in prices if fn(p))
        out.append({'label': label, 'count': c, 'pct': round(c / n * 100) if n else 0})
    return out


def _type_premium(ranked):
    """Avg/median cash price per provider type, cheapest-first, plus the premium
    of the priciest type over the cheapest."""
    from collections import defaultdict
    d = defaultdict(list)
    for p in ranked:
        d[p['type']].append(p['price'])
    rows = []
    for t, pl in d.items():
        pl = sorted(pl)
        rows.append({
            'type': t, 'count': len(pl),
            'avg': round(sum(pl) / len(pl)),
            'median': round(pl[len(pl) // 2]),
        })
    rows.sort(key=lambda r: r['avg'])
    premium = None
    if len(rows) >= 2 and rows[0]['avg'] > 0:
        cheap, pricey = rows[0], rows[-1]
        premium = {
            'cheap': cheap, 'pricey': pricey,
            'pct': round((pricey['avg'] - cheap['avg']) / cheap['avg'] * 100),
        }
    return rows, premium


def _neighborhood_districts(ranked):
    """Median/avg cash price per Miami district, cheapest-first. Districts with
    fewer than REPORT_MIN_DISTRICT providers are dropped (not enough data — never
    fabricated). ZIP->district is a factual geographic grouping."""
    from collections import defaultdict
    d = defaultdict(list)
    for p in ranked:
        addr = p.get('address') or ''
        mt = re.search(r'\b(3\d{4})\b', addr)
        if mt and mt.group(1) in MIAMI_ZIP_DISTRICT:
            d[MIAMI_ZIP_DISTRICT[mt.group(1)]].append(p['price'])
    rows = []
    for name, pl in d.items():
        if len(pl) < REPORT_MIN_DISTRICT:
            continue
        pl = sorted(pl)
        rows.append({
            'name': name, 'count': len(pl),
            'median': round(pl[len(pl) // 2]),
            'avg': round(sum(pl) / len(pl)),
            'low': round(pl[0]), 'high': round(pl[-1]),
        })
    rows.sort(key=lambda r: r['median'])
    return rows


def _botox_national_snapshot():
    """National median + per-city (median, count) across the same Botox variants.
    Used for cross-metro comparison. City counts here are NOT phone-deduped, so
    they run slightly higher than a city hub page — medians are dedup-robust and
    are what the report compares on."""
    variants = _wedge_variants()
    tp = [v for v in variants if v.slug.startswith('botox')]
    if not tp:
        return 0, {}, 0
    wl = _variant_whitelist(tp)
    rec = _recovered_ids(tp)
    records = _records_for(tp, None, wl, extra_ids=rec)
    from collections import defaultdict
    cp = defaultdict(list)
    meta = {}
    for slug, city, state, price in records.values_list(
        'provider__location__slug', 'provider__location__city',
        'provider__location__state', 'cash_price',
    ).iterator():
        if not slug or is_malformed_location(city, state):
            continue
        cp[slug].append(float(price))
        meta[slug] = (city, state)
    allp = sorted(p for l in cp.values() for p in l)
    nat_median = round(allp[len(allp) // 2]) if allp else 0
    cities = {}
    for slug, pl in cp.items():
        pl = sorted(pl)
        city, state = meta[slug]
        cities[slug] = {
            'slug': slug, 'city': city, 'state': state,
            'count': len(pl), 'median': round(pl[len(pl) // 2]),
        }
    return nat_median, cities, len(cp)


def _report_faqs(city, city_state, stats, provider_count, premium, districts,
                 national_median):
    """Data-driven FAQ — every answer drawn from the report's own figures."""
    faqs = [{
        'q': f"How much does Botox cost in {city} in 2026?",
        'a': (
            f"The median advertised cash price for a full-face Botox treatment in "
            f"{city_state} is ${stats['median']:,}, across {provider_count} providers. "
            f"Most fall between ${stats['p25']:,} and ${stats['p75']:,}, with a full "
            f"range of ${stats['min']:,} to ${stats['max']:,}."
        ),
    }]
    if premium:
        faqs.append({
            'q': f"Is Botox cheaper at med spas or plastic surgeons in {city}?",
            'a': (
                f"{premium['cheap']['type']}s advertise the lowest average price in "
                f"{city} at ${premium['cheap']['avg']:,}, while {premium['pricey']['type'].lower()}s "
                f"average ${premium['pricey']['avg']:,}, about {premium['pct']}% more for the "
                f"same treatment."
            ),
        })
    if districts:
        cheapest_d = districts[0]
        faqs.append({
            'q': f"Which {city} neighborhood has the cheapest Botox?",
            'a': (
                f"Of the districts with enough data, {cheapest_d['name']} has the lowest "
                f"median Botox price at ${cheapest_d['median']:,} across {cheapest_d['count']} "
                f"providers. {districts[-1]['name']} is the most expensive at "
                f"${districts[-1]['median']:,}."
            ),
        })
    if national_median:
        diff = round((stats['median'] - national_median) / national_median * 100)
        word = 'above' if diff > 0 else 'below' if diff < 0 else 'in line with'
        faqs.append({
            'q': f"How does {city} Botox pricing compare to the national average?",
            'a': (
                f"At a ${stats['median']:,} median, {city} Botox is about {abs(diff)}% {word} "
                f"the ${national_median:,} national median. {city} is one of the largest and "
                f"most competitive Botox markets in the US."
            ),
        })
    return faqs


def _report_schema(page_url):
    """BreadcrumbList: Home > Botox > Miami, FL > Price Report. FAQPage is emitted
    separately by the template."""
    crumbs = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://zenthir.com/"},
        {"@type": "ListItem", "position": 2, "name": "Botox", "item": "https://zenthir.com/cash/botox/"},
        {"@type": "ListItem", "position": 3, "name": "Miami, FL", "item": "https://zenthir.com/cash/botox/miami-fl/"},
        {"@type": "ListItem", "position": 4, "name": "Price Report", "item": page_url},
    ]
    return json.dumps({
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": crumbs,
    }, ensure_ascii=False)


@cache_page(86400)
def botox_miami_report(request):
    location = get_object_or_404(Location, slug=WEDGE_CITY_SLUG)
    market = build_botox_miami(location)
    city = location.city
    city_state = f"{city}, {location.state}"

    if market['thin_data']:
        return render(request, 'healthcare/botox_report.html', {
            'thin_data': True, 'noindex': True,
            'provider_count': market['provider_count'],
            'thin_threshold': THIN_DATA_THRESHOLD,
            'city_state': city_state, 'location': location,
            'hub_url': '/cash/botox/miami-fl/',
        })

    stats = market['stats']
    ranked = market['ranked']
    prices = [p['price'] for p in ranked]
    provider_count = market['provider_count']
    updated_at = market['updated_at']
    _mark_lead_enabled(ranked)

    distribution = _price_distribution(prices)
    type_rows, premium = _type_premium(ranked)
    districts = _neighborhood_districts(ranked)

    # Consumer decision support (all computed from this market's own prices).
    good_deal_count = sum(1 for p in prices if p < GOOD_DEAL_MAX)
    good_deal_pct = round(good_deal_count / provider_count * 100) if provider_count else 0
    mid_band_count = sum(1 for p in prices if MID_BAND_LOW <= p < MID_BAND_HIGH)
    mid_band_pct = round(mid_band_count / provider_count * 100) if provider_count else 0

    # District "Best for" labels — derived strictly from the data, not editorial.
    if districts:
        lowest_median = districts[0]           # districts are sorted median-ascending
        highest_median = districts[-1]
        most_providers = max(districts, key=lambda d: d['count'])
        for d in districts:
            tags = []
            if d is lowest_median:
                tags.append('Budget-friendly options')
            if d is most_providers:
                tags.append('Largest selection')
            if d is highest_median:
                tags.append('Premium providers')
            d['best_for'] = tags

    # National / cross-metro comparison (medians are dedup-robust).
    national_median, cities, n_cities = _botox_national_snapshot()
    miami_vs_national = (round((stats['median'] - national_median) / national_median * 100)
                         if national_median else 0)
    metros = []
    for slug in REPORT_COMPARE_METROS:
        c = cities.get(slug)
        if not c:
            continue
        d = round((stats['median'] - c['median']) / c['median'] * 100) if c['median'] else 0
        metros.append({**c, 'diff_vs_miami': d})

    # Competition: rank by advertised-listing count (national methodology). Miami's
    # deduped unique count (provider_count) is what the report headlines.
    by_count = sorted(cities.values(), key=lambda c: -c['count'])
    miami_rank = next((i for i, c in enumerate(by_count, 1) if c['slug'] == WEDGE_CITY_SLUG), None)
    competition = [c for c in by_count[:8]]
    miami_listings = cities.get(WEDGE_CITY_SLUG, {}).get('count', provider_count)

    # Treatment-area / variant rows (full face vs per unit) already computed.
    variant_rows = market['variant_rows']
    # Per-unit clarity: translate a per-unit rate into a full-face equivalent so
    # nobody reads "$10/unit" as a $10 treatment.
    per_unit_row = next((v for v in variant_rows if v['per_unit']), None)
    per_unit_ctx = None
    if per_unit_row:
        puem = per_unit_row['stats']['median']
        per_unit_ctx = {'median': puem, 'low': puem * 40, 'high': puem * 60}

    answer = (
        f"{city} consumers paid between ${stats['min']:,} and ${stats['max']:,} for Botox "
        f"in 2026, with a median of ${stats['median']:,} across {provider_count} providers."
    )

    # Key findings — quotable facts, generated straight from the numbers above.
    over_400 = sum(b['pct'] for b in distribution if b['label'] in ('$400–$500', '$500 and up'))
    key_findings = [
        f"The median cash price for full-face Botox in {city} is ${stats['median']:,}, "
        f"with providers ranging from ${stats['min']:,} to ${stats['max']:,} "
        f"({stats['range_multiplier']}x) across {provider_count} clinics.",
    ]
    if national_median:
        word = 'above' if miami_vs_national > 0 else 'below' if miami_vs_national < 0 else 'even with'
        key_findings.append(
            f"{city} sits {abs(miami_vs_national)}% {word} the ${national_median:,} national "
            f"median, pricier than most major metros but not the priciest."
        )
    if premium:
        key_findings.append(
            f"{premium['pricey']['type']}s (${premium['pricey']['avg']:,} avg) charge about "
            f"{premium['pct']}% more than {premium['cheap']['type'].lower()}s "
            f"(${premium['cheap']['avg']:,}) for the same treatment."
        )
    key_findings.append(
        f"{over_400}% of {city} providers price Botox at $400 or more; only "
        f"{distribution[0]['pct']}% come in under $300."
    )
    if districts:
        key_findings.append(
            f"{districts[0]['name']} is the cheapest district (median ${districts[0]['median']:,}, "
            f"{districts[0]['count']} providers); {districts[-1]['name']} is the most expensive "
            f"(median ${districts[-1]['median']:,})."
        )
    if miami_rank:
        key_findings.append(
            f"With {provider_count} providers, {city} is the largest cash-pay Botox market in "
            f"the US. No metro we track lists more."
        )

    faqs = _report_faqs(city, city_state, stats, provider_count, premium, districts, national_median)
    page_url = "https://zenthir.com/cash/botox/miami-fl/report/"
    context = {
        'thin_data': False, 'noindex': False,
        'location': location, 'city': city, 'city_state': city_state,
        'answer': answer, 'stats': stats, 'provider_count': provider_count,
        'updated_at': updated_at,
        'distribution': distribution,
        'type_rows': type_rows, 'premium': premium,
        'variant_rows': variant_rows, 'per_unit_ctx': per_unit_ctx,
        'districts': districts, 'report_min_district': REPORT_MIN_DISTRICT,
        'national_median': national_median or None,
        'miami_vs_national': miami_vs_national, 'n_cities': n_cities,
        'metros': metros,
        'competition': competition, 'miami_rank': miami_rank,
        'miami_listings': miami_listings,
        'key_findings': key_findings,
        'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'report_schema': _report_schema(page_url),
        'methodology_url': '/methodology/',
        'hub_url': '/cash/botox/miami-fl/',
        'best_url': '/cash/botox/miami-fl/best/',
        'cheapest_url': '/cash/botox/miami-fl/cheapest/',
        'medspas_url': '/cash/botox/miami-fl/med-spas/',
        'plastic_url': '/cash/botox/miami-fl/plastic-surgeons/',
        'national_url': '/cash/botox/',
        'canonical_url': page_url,
    }
    return render(request, 'healthcare/botox_report.html', context)


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
    # Which market the signup is for: 'national' from the US page, else the city.
    scope = (data.get('scope') or '').strip().lower()
    city_slug = scope if re.fullmatch(r'[a-z0-9-]{1,40}', scope) else WEDGE_CITY_SLUG
    resp = JsonResponse({'ok': True})
    vid = _visitor_and_cookie(request, resp)
    PriceAlertSignup.objects.get_or_create(
        email=email, procedure_slug=WEDGE_PROCEDURE_SLUG, city_slug=city_slug,
        defaults={'source_page': (data.get('page') or '').strip()[:40], 'visitor_id': vid},
    )
    _log_event('email_signup', request=request, visitor_id=vid, city_slug=city_slug,
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
