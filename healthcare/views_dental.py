"""
Dental-implant / Miami lead wedge — a faithful replica of the Botox wedge
(views_botox.py) for the single-dental-implant market. Same page architecture,
capture hooks, schema, and trust signals; dental-specific data + copy.

Data reality (differs from Botox):
  * One cash-pay variant exists: ``dental-implant-single`` (no All-on-4 / mini
    implant in the dataset), so there is no per-unit vs treatment split.
  * One provider type: ``Dental Office`` (no generic "Clinic" contamination, so
    no aesthetic-name recovery, no provider-type premium, no type-filter pages).

Pages (routed BEFORE the generic /cash/<proc>/<city>/ pattern so they intercept
without touching the existing /cash/dental-implant-single/<city>/ variant page):
    /cash/dental-implant/miami-fl/            -> dental_miami_hub
    /cash/dental-implant/miami-fl/cheapest/   -> dental_miami_cheapest
    /cash/dental-implant/miami-fl/best/       -> dental_miami_best
    /cash/dental-implant/miami-fl/report/     -> dental_miami_report
    /cash/dental-implant/                       -> dental_national

Captures reuse the shared, procedure-aware /wedge/ endpoints (the templates post
procedure_slug='dental-implant'), so there is one lead pipeline across wedges.
"""
import json
from collections import Counter, defaultdict

from django.shortcuts import render, get_object_or_404
from django.views.decorators.cache import cache_page
from django.http import Http404
from django.db.models import Avg, Count, Max

from healthcare.models import Procedure, Location, PricingRecord
from healthcare.market_utils import price_stats, dedupe_ranked_providers, faq_jsonld
from healthcare.provider_whitelist import allowed_provider_types
from healthcare.location_quality import is_malformed_location
from healthcare.views_botox import (
    _mark_lead_enabled, _assign_bands, _annotate_market_position, _price_bands, _procedure_counts,
    _neighborhood_districts, _assign_best_tiers,
    MIAMI_ZIP_DISTRICT, REPORT_MIN_DISTRICT, REPORT_COMPARE_METROS,
    BEST_W_PRICE, BEST_W_BREADTH, BEST_W_VERIFIED, BEST_W_TYPE, BEST_PROC_CAP,
)

# --- Wedge constants --------------------------------------------------------
DENTAL_HUB_SLUG = 'dental-implant'          # hub/national URL slug (NOT a procedure slug)
DENTAL_CITY_SLUG = 'miami-fl'
DENTAL_VARIANT_SLUGS = ['dental-implant-single']  # only cash-pay implant variant in the data
DENTAL_PROCEDURE_LABEL = 'dental implant'
THIN_DATA_THRESHOLD = 10
COST_EXPLAINER_URL = "/guides/why-prices-vary/"
# Credible provider types for dental implants. Only "Dental Office" appears in the
# data today; the surgical/specialist types are listed so the wedge picks them up
# automatically if they ever carry implant pricing.
DENTAL_WHITELIST = sorted(set(
    (allowed_provider_types('dental-implant-single') or ['Dental Office'])
    + ['Oral Surgery', 'Oral & Maxillofacial Surgery', 'Periodontics', 'Prosthodontics']
))
DENTAL_RELEVANT_TYPES = set(DENTAL_WHITELIST)
# Report decision-support thresholds (computed against this market, not editorial).
GOOD_DEAL_MAX = 3000   # a "good deal" ceiling — below the ~$3,200 Miami median
MID_BAND_LOW = 2500    # the "realistic budget" band most patients fall into
MID_BAND_HIGH = 3500
REPORT_MIN_DISTRICT_DENTAL = REPORT_MIN_DISTRICT


# ---------------------------------------------------------------------------
# Market aggregation
# ---------------------------------------------------------------------------

def _dental_variants():
    return list(Procedure.objects.filter(slug__in=DENTAL_VARIANT_SLUGS))


def _dental_records(location):
    """Cash-price records for dental implants, optionally scoped to one location
    (location=None = national). Prefers rows tagged price_category='cash_price'."""
    procs = _dental_variants()
    base = PricingRecord.objects.filter(
        procedure__in=procs, cash_price__isnull=False,
    ).exclude(cash_price=0)
    if location is not None:
        base = base.filter(provider__location=location)
    if DENTAL_WHITELIST:
        base = base.filter(provider__provider_type__name__in=DENTAL_WHITELIST)
    tagged = base.filter(price_category='cash_price')
    return tagged if tagged.exists() else base


def build_dental_miami(location):
    """Aggregate the dental-implant market in one city into a snapshot dict, or
    {'thin_data': True, ...} when too sparse to render confidently."""
    records = _dental_records(location)
    ranked, dropped = dedupe_ranked_providers(records)
    provider_count = len(ranked)
    if provider_count < THIN_DATA_THRESHOLD:
        return {'thin_data': True, 'provider_count': provider_count}
    stats = price_stats([p['price'] for p in ranked])
    _assign_bands(ranked, stats['p25'], stats['p75'])
    _annotate_market_position(ranked, stats['median'])
    _mark_lead_enabled(ranked)
    return {
        'thin_data': False, 'location': location, 'stats': stats,
        'provider_count': provider_count, 'ranked': ranked, 'records': records,
        'dropped': dropped, 'updated_at': records.aggregate(m=Max('updated_at'))['m'],
    }


def _dental_insights(market, national_median, location):
    """Rule-based insights computed from this page's own data."""
    insights = []
    stats = market['stats']
    n = market['provider_count']
    if national_median > 0 and stats['median'] > 0:
        diff = round((stats['median'] - national_median) / national_median * 100)
        if diff > 8:
            insights.append(f"A single dental implant in {location.city} costs {abs(diff)}% more than the national median (${national_median:,}).")
        elif diff < -8:
            insights.append(f"A single dental implant in {location.city} costs {abs(diff)}% less than the national median (${national_median:,}).")
        else:
            insights.append(f"Single dental implant pricing in {location.city} is close to the national median (${national_median:,}).")
    if n > 60:
        insights.append(f"With {n} dental offices advertising cash implant prices, {location.city} is a competitive market, more options and pricing leverage for shoppers.")
    elif n > 30:
        insights.append(f"{location.city} has a moderately competitive dental implant market with {n} providers advertising cash prices.")
    return insights


def _dental_national_snapshot():
    """National median + per-city (median/count) across the dental-implant
    variants. City counts are not phone-deduped; medians are dedup-robust."""
    records = _dental_records(None)
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
            'slug': slug, 'city': city, 'state': state, 'count': len(pl),
            'median': round(pl[len(pl) // 2]), 'low': round(pl[0]), 'high': round(pl[-1]),
            'url': ('/cash/dental-implant/miami-fl/' if slug == DENTAL_CITY_SLUG
                    else f'/cash/dental-implant-single/{slug}/'),
        }
    return nat_median, cities, len(cp), records


# ---------------------------------------------------------------------------
# Distribution / decision support
# ---------------------------------------------------------------------------

def _dental_distribution(prices):
    """Share of providers in each price band (dental-scaled), computed not assumed."""
    n = len(prices)
    bands = [
        ('Under $2,500', lambda p: p < 2500),
        ('$2,500–$3,000', lambda p: 2500 <= p < 3000),
        ('$3,000–$3,500', lambda p: 3000 <= p < 3500),
        ('$3,500 and up', lambda p: p >= 3500),
    ]
    out = []
    for label, fn in bands:
        c = sum(1 for p in prices if fn(p))
        out.append({'label': label, 'count': c, 'pct': round(c / n * 100) if n else 0})
    return out


# ---------------------------------------------------------------------------
# Composite ranking (Best page) — same weights as the Botox wedge.
# ---------------------------------------------------------------------------

def _rank_best_dental(ranked, stats):
    """Transparent composite score (0–100): price 35, procedures listed 25,
    verification 25, provider-type relevance 15. Never influenced by payment."""
    median, mn, mx = stats['median'], stats['min'], stats['max']
    for p in ranked:
        price = p['price']
        if price <= median:
            below = (median - price) / (median - mn) if median > mn else 0.0
            price_score = BEST_W_PRICE * (0.85 + 0.15 * below)
        else:
            span = mx - median
            price_score = BEST_W_PRICE * max(0.0, 1 - (price - median) / span) if span > 0 else 0.0
        breadth = BEST_W_BREADTH * min(1.0, p.get('proc_count', 1) / BEST_PROC_CAP)
        verified = BEST_W_VERIFIED if p.get('lead_enabled') else 0
        type_score = BEST_W_TYPE if (p['type'] or '') in DENTAL_RELEVANT_TYPES else BEST_W_TYPE * 0.5
        p['score'] = round(price_score + breadth + verified + type_score, 1)


# ---------------------------------------------------------------------------
# Schema (JSON-LD)
# ---------------------------------------------------------------------------

_DENTAL_DEF = (
    "A dental implant is a titanium post surgically placed in the jawbone to "
    "replace a missing tooth root, topped with an abutment and a crown. It is "
    "typically an elective, cash-pay procedure priced per implant."
)


def _dental_hub_schema(stats, provider_count, updated_at, page_url, is_cheapest=False):
    crumbs = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://zenthir.com/"},
        {"@type": "ListItem", "position": 2, "name": "Dental Implants", "item": "https://zenthir.com/cash/dental-implant/"},
        {"@type": "ListItem", "position": 3, "name": "Miami, FL", "item": "https://zenthir.com/cash/dental-implant/miami-fl/"},
    ]
    if is_cheapest:
        crumbs.append({"@type": "ListItem", "position": 4, "name": "Cheapest Dental Implants", "item": page_url})
    graph = [
        {
            "@type": "AggregateOffer",
            "name": "Cash-pay single dental implant in Miami, FL",
            "priceCurrency": "USD",
            "lowPrice": stats['min'], "highPrice": stats['max'],
            "offerCount": provider_count,
            "availabilityStarts": updated_at.isoformat() if updated_at else None,
            "validFrom": updated_at.isoformat() if updated_at else None,
            "category": "Single dental implant (endosteal implant)",
        },
        {"@type": "BreadcrumbList", "itemListElement": crumbs},
        {"@type": "DefinedTerm", "name": "Dental implant", "description": _DENTAL_DEF,
         "inDefinedTermSet": "https://zenthir.com/cash/dental-implant/miami-fl/"},
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)


def _dental_national_schema(stats, provider_count, updated_at, page_url):
    graph = [
        {
            "@type": "AggregateOffer",
            "name": "Cash-pay single dental implant in the United States",
            "priceCurrency": "USD",
            "lowPrice": stats['min'], "highPrice": stats['max'],
            "offerCount": provider_count,
            "availabilityStarts": updated_at.isoformat() if updated_at else None,
            "validFrom": updated_at.isoformat() if updated_at else None,
            "category": "Single dental implant (endosteal implant)",
        },
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://zenthir.com/"},
            {"@type": "ListItem", "position": 2, "name": "Dental Implants", "item": page_url},
        ]},
        {"@type": "DefinedTerm", "name": "Dental implant", "description": _DENTAL_DEF, "inDefinedTermSet": page_url},
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)


def _crumb_schema(fourth_name, page_url):
    crumbs = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://zenthir.com/"},
        {"@type": "ListItem", "position": 2, "name": "Dental Implants", "item": "https://zenthir.com/cash/dental-implant/"},
        {"@type": "ListItem", "position": 3, "name": "Miami, FL", "item": "https://zenthir.com/cash/dental-implant/miami-fl/"},
        {"@type": "ListItem", "position": 4, "name": fourth_name, "item": page_url},
    ]
    return json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": crumbs}, ensure_ascii=False)


def _provider_itemlist(providers, list_name):
    items = [{
        "@type": "ListItem", "position": i,
        "item": {
            "@type": "Dentist", "name": p['name'],
            "url": f"https://zenthir.com/provider/{p['slug']}/",
            "makesOffer": {"@type": "Offer", "priceCurrency": "USD", "price": p['price'],
                           "category": "Single dental implant"},
        },
    } for i, p in enumerate(providers, 1)]
    return json.dumps({
        "@context": "https://schema.org", "@type": "ItemList", "name": list_name,
        "numberOfItems": len(items), "itemListElement": items,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# FAQ (dental-specific; data-driven where noted)
# ---------------------------------------------------------------------------

def _dental_faqs(city_state, city, stats, cheapest_name, provider_count):
    return [
        {'q': f"How much does a single dental implant cost in {city}?",
         'a': (f"Across {provider_count} dental offices advertising cash prices in {city_state}, "
               f"the median price for a single dental implant is ${stats['median']:,}. Most fall "
               f"between ${stats['p25']:,} and ${stats['p75']:,}, and the full range runs "
               f"${stats['min']:,} to ${stats['max']:,}.")},
        {'q': "What's included in dental implant pricing?",
         'a': ("Advertised implant prices vary in what they cover. A full price usually includes the "
               "implant post (the titanium screw), the abutment, and the crown. A lower price may be "
               "for the post alone. Bone grafting, tooth extraction, sedation or anesthesia, and CT "
               "imaging are frequently billed separately, so confirm whether the quote is implant-only "
               "or the complete tooth.")},
        {'q': f"What is the cheapest dental implant in {city}?",
         'a': (f"The lowest advertised single-implant price in {city_state} is ${stats['min']:,}"
               + (f", listed by {cheapest_name}." if cheapest_name else ".")
               + " A lower price may exclude the abutment, crown, bone grafting, or sedation, so confirm "
               "exactly what is included before booking.")},
        {'q': "How much does a single implant cost versus All-on-4?",
         'a': (f"A single dental implant in {city_state} runs a median of ${stats['median']:,}. All-on-4 "
               "is a different, much larger procedure, a full arch of replacement teeth supported by four "
               "implants, and typically costs several times more per arch. All-on-4 is not priced in this "
               "cash-pay dataset, so compare quotes for the same scope of work.")},
        {'q': "Does insurance cover dental implants?",
         'a': ("Many dental plans treat implants as a major or cosmetic service with partial or no coverage, "
               "often subject to an annual maximum (commonly $1,000–$2,000) that a single implant can use up. "
               "Medical insurance may contribute if the implant follows an accident or medical condition. The "
               "prices shown here are advertised cash-pay estimates; check your plan's implant benefit and annual maximum.")},
        {'q': "How long do dental implants last?",
         'a': ("The titanium implant post is designed to last decades and often a lifetime with good oral "
               "hygiene, while the crown attached to it typically lasts 10–15 years before it may need "
               "replacement. Longevity depends on bone health, oral hygiene, and habits such as smoking or grinding.")},
    ]


def _dental_report_faqs(city, city_state, stats, provider_count, national_median):
    faqs = [{
        'q': f"How much does a dental implant cost in {city} in 2026?",
        'a': (f"The median advertised cash price for a single dental implant in {city_state} is "
              f"${stats['median']:,}, across {provider_count} dental offices. Most fall between "
              f"${stats['p25']:,} and ${stats['p75']:,}, with a full range of ${stats['min']:,} to ${stats['max']:,}.")},
    ]
    if national_median:
        diff = round((stats['median'] - national_median) / national_median * 100)
        word = 'above' if diff > 0 else 'below' if diff < 0 else 'in line with'
        faqs.append({
            'q': f"How does {city} implant pricing compare to the national average?",
            'a': (f"At a ${stats['median']:,} median, {city} single-implant pricing is about {abs(diff)}% {word} "
                  f"the ${national_median:,} national median.")})
    faqs += [
        {'q': "What's included in dental implant pricing?",
         'a': ("A full price usually covers the implant post, abutment, and crown. Bone grafting, extractions, "
               "sedation, and CT imaging are often separate. Confirm whether a quote is implant-only or the complete tooth.")},
        {'q': "Does insurance cover dental implants?",
         'a': ("Many plans classify implants as major or cosmetic with limited coverage and an annual maximum "
               "(often $1,000–$2,000). The prices here are advertised cash-pay estimates; check your plan's implant benefit.")},
        {'q': "How long do dental implants last?",
         'a': ("The titanium post can last decades or a lifetime with good hygiene; the crown typically lasts "
               "10–15 years. Longevity depends on bone health, hygiene, and habits like smoking or grinding.")},
    ]
    return faqs


# ---------------------------------------------------------------------------
# Page views
# ---------------------------------------------------------------------------

def _answer_first(city_state, stats, provider_count, updated_at):
    upd = f", updated {updated_at:%B %Y}" if updated_at else ""
    return (f"Cash-pay dental implants in {city_state} cost ${stats['min']:,} to ${stats['max']:,}, "
            f"median ${stats['median']:,}, across {provider_count} providers{upd}.")


@cache_page(86400)
def dental_miami_hub(request):
    location = get_object_or_404(Location, slug=DENTAL_CITY_SLUG)
    market = build_dental_miami(location)
    city_state = f"{location.city}, {location.state}"

    if market['thin_data']:
        return render(request, 'healthcare/dental_hub.html', {
            'thin_data': True, 'noindex': True,
            'provider_count': market['provider_count'], 'thin_threshold': THIN_DATA_THRESHOLD,
            'city_state': city_state, 'location': location, 'explainer_url': COST_EXPLAINER_URL,
        })

    stats = market['stats']
    updated_at = market['updated_at']
    national_median, _cities, _n, _rec = _dental_national_snapshot()
    insights = _dental_insights(market, national_median, location)
    answer = _answer_first(city_state, stats, market['provider_count'], updated_at)
    cheapest_name = market['ranked'][0]['name'] if market['ranked'] else None
    faqs = _dental_faqs(city_state, location.city, stats, cheapest_name, market['provider_count'])
    shown = market['ranked'][:25]
    page_url = "https://zenthir.com/cash/dental-implant/miami-fl/"
    context = {
        'thin_data': False, 'noindex': False,
        'location': location, 'city_state': city_state,
        'answer': answer, 'stats': stats, 'provider_count': market['provider_count'],
        'ranked_providers': shown, 'total_ranked': market['provider_count'],
        'price_bands': _price_bands(market['ranked'], stats),
        'insights': insights, 'national_median': national_median or None,
        'updated_at': updated_at,
        'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'hub_schema': _dental_hub_schema(stats, market['provider_count'], updated_at, page_url),
        'itemlist_jsonld': _provider_itemlist(shown, f"Dental implant providers in {city_state} ranked by price"),
        'explainer_url': COST_EXPLAINER_URL, 'methodology_url': '/methodology/',
        'national_url': '/cash/dental-implant/', 'report_url': '/cash/dental-implant/miami-fl/report/',
        'best_url': '/cash/dental-implant/miami-fl/best/', 'cheapest_url': '/cash/dental-implant/miami-fl/cheapest/',
        'variant_url': f'/cash/dental-implant-single/{location.slug}/',
        'canonical_url': page_url,
    }
    return render(request, 'healthcare/dental_hub.html', context)


@cache_page(86400)
def dental_miami_cheapest(request):
    location = get_object_or_404(Location, slug=DENTAL_CITY_SLUG)
    market = build_dental_miami(location)
    city_state = f"{location.city}, {location.state}"

    if market['thin_data']:
        return render(request, 'healthcare/dental_cheapest.html', {
            'thin_data': True, 'noindex': True,
            'provider_count': market['provider_count'], 'thin_threshold': THIN_DATA_THRESHOLD,
            'city_state': city_state, 'location': location, 'explainer_url': COST_EXPLAINER_URL,
        })

    stats = market['stats']
    updated_at = market['updated_at']
    below = [p for p in market['ranked'] if p['price'] <= stats['median']]
    for p in below:
        p['save'] = stats['median'] - p['price']
    cheapest_price = below[0]['price'] if below else stats['min']
    savings = stats['median'] - cheapest_price
    answer = (f"The cheapest cash-pay dental implant in {city_state} starts at ${cheapest_price:,}. "
              f"{len(below)} of {market['provider_count']} providers price at or below the "
              f"${stats['median']:,} median.")
    faqs = _dental_faqs(city_state, location.city, stats, below[0]['name'] if below else None, market['provider_count'])
    page_url = "https://zenthir.com/cash/dental-implant/miami-fl/cheapest/"
    context = {
        'thin_data': False, 'noindex': False,
        'location': location, 'city_state': city_state,
        'answer': answer, 'stats': stats, 'provider_count': market['provider_count'],
        'below_providers': below, 'below_count': len(below),
        'cheapest_price': cheapest_price, 'savings': savings, 'updated_at': updated_at,
        'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'hub_schema': _dental_hub_schema(stats, len(below), updated_at, page_url, is_cheapest=True),
        'itemlist_jsonld': _provider_itemlist(below, f"Cheapest dental implant providers in {city_state}"),
        'explainer_url': COST_EXPLAINER_URL, 'methodology_url': '/methodology/',
        'hub_url': '/cash/dental-implant/miami-fl/', 'canonical_url': page_url,
    }
    return render(request, 'healthcare/dental_cheapest.html', context)


@cache_page(86400)
def dental_miami_best(request):
    location = get_object_or_404(Location, slug=DENTAL_CITY_SLUG)
    market = build_dental_miami(location)
    city_state = f"{location.city}, {location.state}"

    if market['thin_data']:
        return render(request, 'healthcare/dental_best.html', {
            'thin_data': True, 'noindex': True,
            'provider_count': market['provider_count'], 'thin_threshold': THIN_DATA_THRESHOLD,
            'city_state': city_state, 'location': location, 'hub_url': '/cash/dental-implant/miami-fl/',
        })

    stats = market['stats']
    updated_at = market['updated_at']
    ranked = market['ranked']
    counts = _procedure_counts([p['provider_id'] for p in ranked])
    for p in ranked:
        p['proc_count'] = counts.get(p['provider_id'], 1)
    _rank_best_dental(ranked, stats)
    full_ranked = sorted(ranked, key=lambda p: (-p['score'], p['price']))
    best = full_ranked[:25]
    _assign_best_tiers(best, stats)

    top25_avg = round(sum(p['price'] for p in best) / len(best))
    cheapest = min(ranked, key=lambda p: p['price'])
    cheapest_rank = next(i for i, p in enumerate(full_ranked, 1) if p['provider_id'] == cheapest['provider_id'])
    data_insights = {
        'top25_avg': top25_avg, 'market_avg': stats['avg'],
        'top25_below_market_pct': (round((stats['avg'] - top25_avg) / stats['avg'] * 100) if stats['avg'] else 0),
        'top25_low': min(p['price'] for p in best), 'top25_high': max(p['price'] for p in best),
        'cheapest_name': cheapest['name'], 'cheapest_price': cheapest['price'], 'cheapest_rank': cheapest_rank,
        'top_provider_name': best[0]['name'], 'top_provider_price': best[0]['price'],
    }
    answer = (f"Based on pricing, verification status, and procedure range, these are the top-ranked "
              f"dental implant providers in {location.city} across {market['provider_count']} providers.")
    faqs = _dental_best_faqs(city_state, location.city, stats, market['provider_count'])
    page_url = "https://zenthir.com/cash/dental-implant/miami-fl/best/"
    context = {
        'thin_data': False, 'noindex': False,
        'location': location, 'city_state': city_state,
        'answer': answer, 'stats': stats, 'provider_count': market['provider_count'],
        'best_providers': best, 'total_ranked': market['provider_count'],
        'updated_at': updated_at, 'data_insights': data_insights,
        'weights': {'price': BEST_W_PRICE, 'breadth': BEST_W_BREADTH, 'verified': BEST_W_VERIFIED, 'type': BEST_W_TYPE},
        'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'best_schema': _crumb_schema('Best Providers', page_url),
        'itemlist_jsonld': _provider_itemlist(best, f"Best dental implant providers in {city_state}"),
        'methodology_url': '/methodology/',
        'hub_url': '/cash/dental-implant/miami-fl/', 'cheapest_url': '/cash/dental-implant/miami-fl/cheapest/',
        'report_url': '/cash/dental-implant/miami-fl/report/', 'national_url': '/cash/dental-implant/',
        'canonical_url': page_url,
    }
    return render(request, 'healthcare/dental_best.html', context)


def _dental_best_faqs(city_state, city, stats, provider_count):
    return [
        {'q': "What makes a dental implant provider the best?",
         'a': (f"On Zenthir, “best” is data-ranked, not editorial. A provider ranks higher when its "
               f"advertised cash price is competitive against the ${stats['median']:,} {city_state} median, "
               f"it lists more procedures (a sign of an established practice), and it has claimed or verified "
               f"its profile. Ranking position is never influenced by payment.")},
        {'q': "How are the rankings calculated?",
         'a': (f"Each of the {provider_count} providers gets a composite score from four public signals: "
               f"price competitiveness ({BEST_W_PRICE}%), number of procedures listed ({BEST_W_BREADTH}%), "
               f"verification status ({BEST_W_VERIFIED}%), and provider-type relevance ({BEST_W_TYPE}%). Scores "
               f"come from advertised market data only, no reviews, ads, or editorial opinion.")},
        {'q': "Can providers pay for a higher ranking?",
         'a': ("No, never. Ranking position cannot be bought. Claiming a profile lets a provider correct its "
               "information and receive quote requests, but it does not move it up the list.")},
    ]


@cache_page(86400)
def dental_miami_report(request):
    location = get_object_or_404(Location, slug=DENTAL_CITY_SLUG)
    market = build_dental_miami(location)
    city = location.city
    city_state = f"{city}, {location.state}"

    if market['thin_data']:
        return render(request, 'healthcare/dental_report.html', {
            'thin_data': True, 'noindex': True,
            'provider_count': market['provider_count'], 'thin_threshold': THIN_DATA_THRESHOLD,
            'city_state': city_state, 'location': location, 'hub_url': '/cash/dental-implant/miami-fl/',
        })

    stats = market['stats']
    ranked = market['ranked']
    prices = [p['price'] for p in ranked]
    provider_count = market['provider_count']
    updated_at = market['updated_at']

    distribution = _dental_distribution(prices)
    districts = _neighborhood_districts(ranked)  # uses shared ZIP->district map
    good_deal_count = sum(1 for p in prices if p < GOOD_DEAL_MAX)
    good_deal_pct = round(good_deal_count / provider_count * 100) if provider_count else 0
    mid_band_pct = round(sum(1 for p in prices if MID_BAND_LOW <= p < MID_BAND_HIGH) / provider_count * 100) if provider_count else 0

    national_median, cities, n_cities, _rec = _dental_national_snapshot()
    miami_vs_national = round((stats['median'] - national_median) / national_median * 100) if national_median else 0
    metros = []
    for slug in REPORT_COMPARE_METROS:
        c = cities.get(slug)
        if not c:
            continue
        d = round((stats['median'] - c['median']) / c['median'] * 100) if c['median'] else 0
        metros.append({**c, 'diff_vs_miami': d})
    by_count = sorted(cities.values(), key=lambda c: -c['count'])
    miami_rank = next((i for i, c in enumerate(by_count, 1) if c['slug'] == DENTAL_CITY_SLUG), None)
    competition = by_count[:8]

    answer = (f"{city} consumers paid between ${stats['min']:,} and ${stats['max']:,} for a single dental "
              f"implant in 2026, with a median of ${stats['median']:,} across {provider_count} providers.")

    over_median = sum(b['pct'] for b in distribution if b['label'] in ('$3,000–$3,500', '$3,500 and up'))
    key_findings = [
        f"The median cash price for a single dental implant in {city} is ${stats['median']:,}, "
        f"with providers ranging from ${stats['min']:,} to ${stats['max']:,} across {provider_count} dental offices.",
    ]
    if national_median:
        word = 'above' if miami_vs_national > 0 else 'below' if miami_vs_national < 0 else 'even with'
        key_findings.append(f"{city} sits {abs(miami_vs_national)}% {word} the ${national_median:,} national median.")
    key_findings.append(
        f"{good_deal_pct}% of {city} providers price a single implant under ${GOOD_DEAL_MAX:,}; "
        f"about {mid_band_pct}% fall between ${MID_BAND_LOW:,} and ${MID_BAND_HIGH:,}.")
    if districts:
        key_findings.append(
            f"{districts[0]['name']} has the lowest median (${districts[0]['median']:,}, {districts[0]['count']} "
            f"providers); {districts[-1]['name']} is the highest (${districts[-1]['median']:,}).")
    if miami_rank:
        key_findings.append(
            f"{city} is one of the larger US dental-implant markets, ranked #{miami_rank} of {n_cities} cities "
            f"by the number of dental offices advertising cash prices.")

    faqs = _dental_report_faqs(city, city_state, stats, provider_count, national_median)
    page_url = "https://zenthir.com/cash/dental-implant/miami-fl/report/"
    context = {
        'thin_data': False, 'noindex': False,
        'location': location, 'city': city, 'city_state': city_state,
        'answer': answer, 'stats': stats, 'provider_count': provider_count, 'updated_at': updated_at,
        'distribution': distribution, 'good_deal_pct': good_deal_pct, 'good_deal_max': GOOD_DEAL_MAX,
        'mid_band_pct': mid_band_pct, 'mid_band_low': MID_BAND_LOW, 'mid_band_high': MID_BAND_HIGH,
        'districts': districts, 'report_min_district': REPORT_MIN_DISTRICT_DENTAL,
        'national_median': national_median or None, 'miami_vs_national': miami_vs_national, 'n_cities': n_cities,
        'metros': metros, 'competition': competition, 'miami_rank': miami_rank,
        'key_findings': key_findings, 'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'report_schema': _crumb_schema('Price Report', page_url),
        'methodology_url': '/methodology/',
        'hub_url': '/cash/dental-implant/miami-fl/', 'best_url': '/cash/dental-implant/miami-fl/best/',
        'cheapest_url': '/cash/dental-implant/miami-fl/cheapest/', 'national_url': '/cash/dental-implant/',
        'canonical_url': page_url,
    }
    return render(request, 'healthcare/dental_report.html', context)


NATIONAL_CITY_THRESHOLD = 15
REQUIRED_METROS = [
    'miami-fl', 'new-york-ny', 'los-angeles-ca', 'houston-tx', 'chicago-il',
    'dallas-tx', 'atlanta-ga', 'phoenix-az', 'denver-co', 'seattle-wa',
]


def _dental_national_faqs(stats, provider_count, n_cities):
    return [
        {'q': "How much does a single dental implant cost in the US?",
         'a': (f"Across {provider_count:,} dental offices advertising cash prices in {n_cities} US cities, the "
               f"median price for a single dental implant is ${stats['median']:,}. Most charge between "
               f"${stats['p25']:,} and ${stats['p75']:,}, with a national range of ${stats['min']:,} to ${stats['max']:,}.")},
        {'q': "What's included in a dental implant price?",
         'a': ("A complete price covers the implant post, abutment, and crown. Bone grafting, extractions, "
               "sedation, and imaging are often separate. Confirm whether a quote is implant-only or the full tooth.")},
        {'q': "Why do implant prices vary between cities?",
         'a': ("City-to-city differences reflect local cost of living, competition among dental offices, and how "
               "much of the restoration (post, abutment, crown, grafting) each quote includes.")},
        {'q': "Does insurance cover dental implants?",
         'a': ("Many dental plans treat implants as a major or cosmetic service with limited coverage and an "
               "annual maximum (often $1,000–$2,000). All prices here are advertised cash-pay estimates.")},
    ]


@cache_page(86400)
def dental_national(request):
    records = _dental_records(None)
    rows = list(records.values_list(
        'provider__location__slug', 'provider__location__city',
        'provider__location__state', 'cash_price'))
    if not rows:
        raise Http404("No dental implant pricing data")

    raw = sorted(float(r[3]) for r in rows)
    prelim_median = raw[len(raw) // 2]
    floor = prelim_median * 0.10
    prices = [p for p in raw if p >= floor]
    stats = price_stats(prices)
    provider_count = len(rows)
    updated_at = records.aggregate(m=Max('updated_at'))['m']

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
            'median': round(plist[len(plist) // 2]), 'low': round(plist[0]), 'high': round(plist[-1]),
            'url': ('/cash/dental-implant/miami-fl/' if slug == 'miami-fl'
                    else f'/cash/dental-implant-single/{slug}/'),
        })

    by_slug = {c['slug']: c for c in cities}
    chosen = {s for s in REQUIRED_METROS if s in by_slug}
    for c in sorted(cities, key=lambda c: -c['count'])[:15]:
        chosen.add(c['slug'])
    top_cities = sorted((by_slug[s] for s in chosen), key=lambda c: -c['count'])[:18]
    affordable = sorted(cities, key=lambda c: c['median'])[:8]
    expensive = sorted(cities, key=lambda c: -c['median'])[:8]

    answer = (f"Cash-pay single dental implants in the US cost ${stats['min']:,} to ${stats['max']:,}, "
              f"median ${stats['median']:,}, across {provider_count:,} providers.")
    faqs = _dental_national_faqs(stats, provider_count, len(cities))
    page_url = "https://zenthir.com/cash/dental-implant/"
    context = {
        'answer': answer, 'stats': stats, 'provider_count': provider_count,
        'n_cities': len(cities), 'updated_at': updated_at,
        'top_cities': top_cities, 'affordable': affordable, 'expensive': expensive,
        'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'national_schema': _dental_national_schema(stats, provider_count, updated_at, page_url),
        'methodology_url': '/methodology/', 'miami_url': '/cash/dental-implant/miami-fl/',
        'canonical_url': page_url,
    }
    return render(request, 'healthcare/dental_national.html', context)
