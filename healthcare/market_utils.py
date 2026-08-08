"""
Shared helpers for market-style pricing pages (insurance/hospital market pages
and cash-pay shopping pages).

Everything here is computed from a page's own data so each page is unique —
no boilerplate prose, no hard-coded numbers.

Cost/safety: callers pass an already-filtered, location-scoped queryset. We pull
only the single ``cash_price`` column into Python for percentile math (bounded to
one city's providers — hundreds, not millions). Never select whole rows in bulk.
"""
import json
import re


# ---------------------------------------------------------------------------
# Percentile / distribution stats
# ---------------------------------------------------------------------------

def _nearest_rank(sorted_prices, q):
    """q in [0,1]; nearest-rank percentile on a pre-sorted list."""
    if not sorted_prices:
        return 0
    idx = int(round(q * (len(sorted_prices) - 1)))
    idx = max(0, min(idx, len(sorted_prices) - 1))
    return sorted_prices[idx]


def price_stats(prices):
    """
    Given an iterable of numeric prices, return a dict of distribution stats.
    Returns None if empty.
    """
    sp = sorted(float(p) for p in prices)
    if not sp:
        return None
    n = len(sp)
    median = _nearest_rank(sp, 0.50)
    p5 = _nearest_rank(sp, 0.05)
    p25 = _nearest_rank(sp, 0.25)
    p75 = _nearest_rank(sp, 0.75)
    p95 = _nearest_rank(sp, 0.95)
    avg = sum(sp) / n
    range_multiplier = round(p95 / p5, 1) if p5 > 0 else 0
    return {
        'count': n,
        'min': round(sp[0]),
        'max': round(sp[-1]),
        'median': round(median),
        'avg': round(avg),
        'p5': round(p5),
        'p25': round(p25),
        'p75': round(p75),
        'p95': round(p95),
        'range_multiplier': range_multiplier,
    }


# ---------------------------------------------------------------------------
# Provider de-duplication for ranked lists
# ---------------------------------------------------------------------------

def _normalize_phone(phone):
    if not phone:
        return ''
    return re.sub(r'\D', '', phone)


def dedupe_ranked_providers(records, low_outlier_factor=0.10):
    """
    Build a clean, price-ranked provider list from a pricing queryset.

    Cleaning rules (the two visible bugs this addresses):
      * One row per provider (lowest cash_price for that provider).
      * Collapse providers that share a phone number — a shared main line
        (e.g. a hospital switchboard) shows up as many "providers"; keep the
        single cheapest entry for that phone.
      * Drop obviously-wrong low outliers: prices below
        ``low_outlier_factor`` * median (catches a stray $78 line on an
        otherwise four-figure procedure).

    Returns (ranked, dropped_outliers) where ranked is a list of dicts.
    Pulls only the columns it needs via .values() — no bulk row selects.
    """
    from django.db.models import Min as DbMin, Count

    rows = records.values(
        'provider_id',
        'provider__name',
        'provider__slug',
        'provider__provider_type__name',
        'provider__address',
        'provider__phone',
    ).annotate(
        lowest_price=DbMin('cash_price'),
        record_count=Count('id'),
    ).order_by('lowest_price')

    # Median for outlier floor (cheap: reuse already-fetched prices)
    prices = [float(r['lowest_price']) for r in rows if r['lowest_price'] is not None]
    median = sorted(prices)[len(prices) // 2] if prices else 0
    floor = median * low_outlier_factor if median else 0

    seen_phones = set()
    ranked = []
    dropped = 0
    for r in rows:
        price = float(r['lowest_price'])
        if floor and price < floor:
            dropped += 1
            continue
        phone_key = _normalize_phone(r['provider__phone'])
        if phone_key and phone_key in seen_phones:
            continue  # duplicate phone — already have the cheaper one
        if phone_key:
            seen_phones.add(phone_key)
        ranked.append({
            'provider_id': r['provider_id'],
            'name': r['provider__name'],
            'slug': r['provider__slug'],
            'type': r['provider__provider_type__name'],
            'address': r['provider__address'],
            'phone': r['provider__phone'],
            'price': round(price),
        })

    # Re-rank after cleaning and tag price band relative to cleaned set
    for i, p in enumerate(ranked):
        p['rank'] = i + 1
    return ranked, dropped


# ---------------------------------------------------------------------------
# Computed FAQ blocks (per-page-unique) + FAQPage JSON-LD
# ---------------------------------------------------------------------------

def _money(n):
    return f"${int(round(n)):,}"


def build_cash_faq(display_name, city_state, stats, cheapest_name):
    """
    Build per-page FAQ Q&A for a cash-pay shopping page. Every answer is drawn
    from this page's own computed stats, so no two pages share answer text.
    city_state e.g. "Miami, FL".
    """
    faqs = [
        {
            'q': f"How much does {display_name} cost in {city_state}?",
            'a': (
                f"Across {stats['count']} advertised cash-pay listings in {city_state}, "
                f"the median price for {display_name} is {_money(stats['median'])}. "
                f"Most providers fall between {_money(stats['p25'])} and {_money(stats['p75'])}."
            ),
        },
        {
            'q': f"What is the cheapest {display_name} provider in {city_state}?",
            'a': (
                f"The lowest advertised price in {city_state} is {_money(stats['min'])}"
                + (f", listed by {cheapest_name}." if cheapest_name else ".")
                + " A lower listed price does not always mean a lower total cost — "
                "confirm exactly what is included with the provider before booking."
            ),
        },
        {
            'q': f"How much do {display_name} prices vary in {city_state}?",
            'a': (
                f"Prices range from {_money(stats['min'])} to {_money(stats['max'])}, "
                f"about {stats['range_multiplier']}x, across providers in {city_state}. "
                "Differences reflect technique, materials, provider experience, and what is bundled into the quoted price."
            ),
        },
        {
            'q': f"Is {display_name} covered by insurance?",
            'a': (
                f"{display_name} is typically an elective, cash-pay procedure that most "
                "insurance plans do not cover. The prices shown are advertised market "
                "estimates; ask the provider for an itemized quote and check your plan if a medical indication may apply."
            ),
        },
    ]
    return faqs


def build_market_faq(display_name, city_state, stats, cheapest_name):
    """
    Build per-page FAQ Q&A for an existing insurance/hospital market page.
    Bill-audit framing (not shopping). Drawn entirely from page stats.
    """
    faqs = [
        {
            'q': f"How much does {display_name} cost in {city_state}?",
            'a': (
                f"Based on {stats['count']} pricing records in {city_state}, the median "
                f"reported price for {display_name} is {_money(stats['median'])}, with a "
                f"typical range of {_money(stats['p25'])} to {_money(stats['p75'])}. "
                "Reported prices are submitted charges or negotiated rates and may not equal out-of-pocket cost."
            ),
        },
        {
            'q': f"Who reports the lowest {display_name} price in {city_state}?",
            'a': (
                f"The lowest reported price in {city_state} is {_money(stats['min'])}"
                + (f", from {cheapest_name}." if cheapest_name else ".")
                + " Lower reported prices can reflect different billing structures or facility fees, "
                "so request a Good Faith Estimate before scheduling."
            ),
        },
        {
            'q': f"How much do {display_name} prices vary in {city_state}?",
            'a': (
                f"Reported prices span {_money(stats['min'])} to {_money(stats['max'])}, "
                f"roughly {stats['range_multiplier']}x, in {city_state}. Variation is driven by "
                "facility type, location, and insurer contracts; hospital outpatient departments often add facility fees."
            ),
        },
    ]
    return faqs


def faq_jsonld(faqs):
    """Render a list of {q,a} dicts as a FAQPage JSON-LD string (safe to inline)."""
    data = {
        "@context": "https://schema.org",
        "@type": "FAQPage",
        "mainEntity": [
            {
                "@type": "Question",
                "name": f["q"],
                "acceptedAnswer": {"@type": "Answer", "text": f["a"]},
            }
            for f in faqs
        ],
    }
    return json.dumps(data, ensure_ascii=False)
