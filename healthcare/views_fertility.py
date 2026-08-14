"""
Fertility / Miami lead wedge — a cluster of three shared-ecosystem procedures
(IVF, egg freezing, IUI), replicating the Botox/dental wedge architecture.

Data reality:
  * Three cash-pay procedures share one provider ecosystem: Fertility Clinic
    (+ Hospital for IVF only).
      - ivf-cycle    : 48 Miami providers (44 Fertility Clinic + 4 Hospital), median ~$18.9k
      - egg-freezing : 44 Miami providers (Fertility Clinic only),             median ~$8.5k
      - iui          : 44 Miami providers (Fertility Clinic only),             median ~$1.2k
  * The Fertility-Clinic-vs-Hospital price comparison exists ONLY for IVF
    (egg freezing / IUI have no hospital pricing in the data), so that section is
    IVF-only and single-type procedures say so plainly.

Pages (routed BEFORE the generic /cash/<proc>/<city>/ and botox type-facet routes):
    /cash/fertility/miami-fl/            -> cluster_hub
    /cash/ivf/miami-fl/[cheapest|best|report]/, /cash/ivf/            (IVF: full set)
    /cash/egg-freezing/miami-fl/[cheapest]/, /cash/egg-freezing/      (hub+cheapest+national)
    /cash/iui/miami-fl/[cheapest]/, /cash/iui/                        (hub+cheapest+national)

Note: /cash/egg-freezing/* and /cash/iui/* intercept the generic cash pages for
those procedures in Miami + national (an upgrade to the richer wedge); other
cities still fall through to views_cash. Captures reuse the shared procedure-aware
/wedge/ endpoints (procedure_slug = the procedure's slug).
"""
import json
from collections import defaultdict, Counter

from django.shortcuts import render, get_object_or_404
from django.views.decorators.cache import cache_page
from django.http import Http404
from django.db.models import Max

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

FERTILITY_CITY_SLUG = 'miami-fl'
THIN_DATA_THRESHOLD = 10
DENTAL_RELEVANT = {'Fertility Clinic', 'Hospital'}  # relevant provider types for ranking


# ---------------------------------------------------------------------------
# Per-procedure config (keyed by URL slug). Content is fertility-specific.
# ---------------------------------------------------------------------------

_AFFECTS_IVF = [
    ("Medications", "IVF meds commonly run $3,000–$5,000 per cycle and are usually NOT in the quoted price. Dosage varies by protocol and age."),
    ("Monitoring", "Bloodwork and ultrasound monitoring during stimulation may be bundled or billed separately; confirm which."),
    ("Egg retrieval and anesthesia", "The retrieval procedure (with sedation) is the core of the cycle cost; anesthesia is sometimes a separate line."),
    ("Embryo transfer", "A fresh transfer is often included; a frozen embryo transfer (FET) in a later cycle is typically an added fee."),
    ("PGT genetic testing", "Preimplantation genetic testing (PGT-A/PGT-M) adds roughly $3,000–$6,000 and is almost never included in a base price."),
    ("ICSI", "Intracytoplasmic sperm injection is an add-on (often $1,000–$2,500) when sperm quality requires it."),
    ("Frozen storage", "Annual cryostorage for embryos or eggs is billed yearly and is not part of the cycle price."),
    ("Donor eggs or sperm", "Donor eggs can add $15,000–$45,000; donor sperm is far less. These sit entirely outside a standard cycle quote."),
    ("Number of cycles", "Many patients need more than one cycle; some clinics offer multi-cycle or refund packages that change the per-cycle math."),
]
_AFFECTS_EGG = [
    ("Retrieval process", "Egg freezing uses the same stimulation and retrieval as an IVF cycle; the price difference is mostly the fertilization and transfer steps IVF adds."),
    ("Medications", "Stimulation meds ($3,000–$5,000) are usually separate from the retrieval price."),
    ("Number of cycles", "Getting enough eggs sometimes takes more than one retrieval cycle, especially at older ages."),
    ("Annual storage", "Cryostorage is billed per year (commonly $500–$1,000/year) and continues until eggs are used or discarded."),
    ("Thaw and later IVF", "Using frozen eggs later requires thawing, fertilization, and transfer, a separate IVF-style cost down the road."),
]
_AFFECTS_IUI = [
    ("Monitoring", "Ultrasound and bloodwork monitoring may be bundled or billed per visit."),
    ("Medications", "A natural-cycle IUI uses few or no meds; a medicated cycle (Clomid, letrozole, or injectables) adds cost, with injectables the priciest."),
    ("Sperm washing / prep", "Lab preparation of the sperm sample is part of the procedure and is usually included."),
    ("Donor sperm", "Using donor sperm adds a per-vial cost from a sperm bank, separate from the IUI fee."),
    ("Number of cycles", "IUI is often repeated for a few cycles before moving to IVF, so budget per cycle times the expected attempts."),
]

PROCS = {
    'ivf': {
        'proc_slug': 'ivf-cycle', 'label': 'IVF', 'noun': 'an IVF cycle', 'noun_plain': 'IVF',
        'h1': 'IVF Prices', 'city_url': '/cash/ivf/miami-fl/', 'nat_url': '/cash/ivf/',
        'full': True,  # gets best + report
        'schema_cat': 'In vitro fertilization (IVF) cycle',
        'defterm': ("IVF (in vitro fertilization) is a fertility treatment in which eggs are retrieved, "
                    "fertilized in a lab, and an embryo is transferred to the uterus. It is typically an "
                    "elective, cash-pay procedure priced per cycle."),
        'affects_title': 'What Affects IVF Cost',
        'affects': _AFFECTS_IVF,
        'good_deal': 15000, 'mid_low': 15000, 'mid_high': 25000,
        'dist_bands': [('Under $15,000', 0, 15000), ('$15,000–$20,000', 15000, 20000),
                       ('$20,000–$25,000', 20000, 25000), ('$25,000 and up', 25000, 10**9)],
    },
    'egg-freezing': {
        'proc_slug': 'egg-freezing', 'label': 'Egg Freezing', 'noun': 'egg freezing', 'noun_plain': 'egg freezing',
        'h1': 'Egg Freezing Prices', 'city_url': '/cash/egg-freezing/miami-fl/', 'nat_url': '/cash/egg-freezing/',
        'full': False,
        'schema_cat': 'Oocyte (egg) cryopreservation cycle',
        'defterm': ("Egg freezing (oocyte cryopreservation) retrieves and freezes a patient's eggs for future "
                    "use. It uses the same stimulation and retrieval as IVF, then stores the eggs instead of "
                    "fertilizing and transferring them. It is typically an elective, cash-pay procedure."),
        'affects_title': 'What Affects Egg Freezing Cost',
        'affects': _AFFECTS_EGG,
    },
    'iui': {
        'proc_slug': 'iui', 'label': 'IUI', 'noun': 'an IUI cycle', 'noun_plain': 'IUI',
        'h1': 'IUI Prices', 'city_url': '/cash/iui/miami-fl/', 'nat_url': '/cash/iui/',
        'full': False,
        'schema_cat': 'Intrauterine insemination (IUI) cycle',
        'defterm': ("IUI (intrauterine insemination) places prepared sperm directly into the uterus around "
                    "ovulation. It is a lower-cost, less invasive fertility treatment often tried before IVF, "
                    "and is typically an elective, cash-pay procedure priced per cycle."),
        'affects_title': 'What Affects IUI Cost',
        'affects': _AFFECTS_IUI,
    },
}

# What's-included copy (the #1 source of fertility price confusion).
INCLUDED_NOTE = {
    'ivf': ("Most quoted IVF prices cover monitoring, egg retrieval, lab fertilization, and one fresh embryo "
            "transfer. They usually do NOT include medications ($3,000–$5,000), PGT genetic testing, ICSI, "
            "frozen embryo transfers, annual storage, or donor eggs/sperm. Always ask for an itemized quote."),
    'egg-freezing': ("Most quoted egg-freezing prices cover monitoring, retrieval, and the freezing step. They "
                     "usually do NOT include medications ($3,000–$5,000) or annual storage, and thawing plus a "
                     "future IVF cycle is a separate cost later."),
    'iui': ("Most quoted IUI prices cover the insemination and basic sperm prep. Monitoring, fertility "
            "medications, and donor sperm may be extra, so confirm what a cycle price includes."),
}


def _cfg(key):
    cfg = PROCS.get(key)
    if not cfg:
        raise Http404("Unknown fertility procedure")
    return cfg


# ---------------------------------------------------------------------------
# Market aggregation
# ---------------------------------------------------------------------------

def _records(proc_slug, location):
    proc = get_object_or_404(Procedure, slug=proc_slug)
    wl = allowed_provider_types(proc_slug)
    base = PricingRecord.objects.filter(procedure=proc, cash_price__isnull=False).exclude(cash_price=0)
    if location is not None:
        base = base.filter(provider__location=location)
    if wl:
        base = base.filter(provider__provider_type__name__in=wl)
    tagged = base.filter(price_category='cash_price')
    return tagged if tagged.exists() else base


def build_market(proc_slug, location):
    records = _records(proc_slug, location)
    ranked, dropped = dedupe_ranked_providers(records)
    n = len(ranked)
    if n < THIN_DATA_THRESHOLD:
        return {'thin_data': True, 'provider_count': n}
    stats = price_stats([p['price'] for p in ranked])
    _assign_bands(ranked, stats['p25'], stats['p75'])
    _annotate_market_position(ranked, stats['median'])
    _mark_lead_enabled(ranked)
    return {
        'thin_data': False, 'location': location, 'stats': stats, 'provider_count': n,
        'ranked': ranked, 'records': records, 'updated_at': records.aggregate(m=Max('updated_at'))['m'],
    }


def _type_compare(ranked):
    """Per-type median/avg, cheapest-first, plus a Fertility Clinic vs Hospital
    comparison when both are present (IVF only in this data)."""
    d = defaultdict(list)
    for p in ranked:
        d[p['type']].append(p['price'])
    rows = []
    for t, pl in d.items():
        pl = sorted(pl)
        rows.append({'type': t, 'count': len(pl), 'median': round(pl[len(pl) // 2]), 'avg': round(sum(pl) / len(pl))})
    rows.sort(key=lambda r: r['median'])
    fc = next((r for r in rows if r['type'] == 'Fertility Clinic'), None)
    hosp = next((r for r in rows if r['type'] == 'Hospital'), None)
    cmp = None
    if fc and hosp and fc['count'] >= 3 and hosp['count'] >= 3 and fc['median'] > 0:
        diff = round((hosp['median'] - fc['median']) / fc['median'] * 100)
        cmp = {'fc': fc, 'hosp': hosp, 'pct': abs(diff), 'hosp_pricier': diff >= 0}
    return rows, cmp


def _national_snapshot(proc_slug):
    records = _records(proc_slug, None)
    cp = defaultdict(list)
    meta = {}
    for slug, city, state, price in records.values_list(
        'provider__location__slug', 'provider__location__city',
        'provider__location__state', 'cash_price').iterator():
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
        cities[slug] = {'slug': slug, 'city': city, 'state': state, 'count': len(pl),
                        'median': round(pl[len(pl) // 2]), 'low': round(pl[0]), 'high': round(pl[-1])}
    return nat_median, cities, len(cp), records


def _distribution(prices, bands):
    n = len(prices)
    out = []
    for label, lo, hi in bands:
        c = sum(1 for p in prices if lo <= p < hi)
        out.append({'label': label, 'count': c, 'pct': round(c / n * 100) if n else 0})
    return out


def _rank_best(ranked, stats):
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
        type_score = BEST_W_TYPE if (p['type'] or '') in DENTAL_RELEVANT else BEST_W_TYPE * 0.5
        p['score'] = round(price_score + breadth + verified + type_score, 1)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def _crumbs(cfg, fourth=None, fourth_url=None):
    c = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://zenthir.com/"},
        {"@type": "ListItem", "position": 2, "name": "Fertility", "item": "https://zenthir.com/cash/fertility/miami-fl/"},
        {"@type": "ListItem", "position": 3, "name": f"{cfg['label']}, Miami, FL", "item": f"https://zenthir.com{cfg['city_url']}"},
    ]
    if fourth:
        c.append({"@type": "ListItem", "position": 4, "name": fourth, "item": fourth_url})
    return c


def _market_schema(cfg, stats, n, updated_at, crumbs, national=False):
    where = "the United States" if national else "Miami, FL"
    graph = [
        {"@type": "AggregateOffer", "name": f"Cash-pay {cfg['noun_plain']} in {where}",
         "priceCurrency": "USD", "lowPrice": stats['min'], "highPrice": stats['max'], "offerCount": n,
         "availabilityStarts": updated_at.isoformat() if updated_at else None,
         "validFrom": updated_at.isoformat() if updated_at else None, "category": cfg['schema_cat']},
        {"@type": "BreadcrumbList", "itemListElement": crumbs},
        {"@type": "DefinedTerm", "name": cfg['label'], "description": cfg['defterm'],
         "inDefinedTermSet": f"https://zenthir.com{cfg['city_url']}"},
    ]
    return json.dumps({"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False)


def _breadcrumb_schema(crumbs):
    return json.dumps({"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": crumbs}, ensure_ascii=False)


def _itemlist(cfg, providers, name):
    items = [{
        "@type": "ListItem", "position": i,
        "item": {"@type": "MedicalBusiness", "name": p['name'],
                 "url": f"https://zenthir.com/provider/{p['slug']}/",
                 "makesOffer": {"@type": "Offer", "priceCurrency": "USD", "price": p['price'], "category": cfg['schema_cat']}},
    } for i, p in enumerate(providers, 1)]
    return json.dumps({"@context": "https://schema.org", "@type": "ItemList", "name": name,
                       "numberOfItems": len(items), "itemListElement": items}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# FAQ
# ---------------------------------------------------------------------------

def _faqs(cfg, city, city_state, stats, cheapest_name, n, cmp):
    label = cfg['label']
    key = {'IVF': 'ivf', 'Egg Freezing': 'egg-freezing', 'IUI': 'iui'}[label]
    faqs = [
        {'q': f"How much does {cfg['noun_plain']} cost in {city}?",
         'a': (f"Across {n} providers advertising cash prices in {city_state}, the median price for "
               f"{cfg['noun']} is ${stats['median']:,}. Most fall between ${stats['p25']:,} and "
               f"${stats['p75']:,}, and the full range runs ${stats['min']:,} to ${stats['max']:,}.")},
        {'q': f"What's the cheapest {label} provider in {city}?",
         'a': (f"The lowest advertised {cfg['noun_plain']} price in {city_state} is ${stats['min']:,}"
               + (f", listed by {cheapest_name}." if cheapest_name else ".")
               + " A lower price often means fewer add-ons are bundled, so confirm what's included before booking.")},
        {'q': f"What's included in a {label} price, and what costs extra?",
         'a': INCLUDED_NOTE[key]},
    ]
    if label == 'IVF':
        faqs += [
            {'q': "How many IVF cycles are typical?",
             'a': ("It varies widely with age and diagnosis. Many patients need more than one cycle, which is why "
                   "some clinics offer multi-cycle or refund packages. Budget for the possibility of two or more cycles.")},
            {'q': "What's the total cost of IVF including medications?",
             'a': (f"A cycle in {city_state} has a median advertised price of ${stats['median']:,}, but medications "
                   f"typically add $3,000–$5,000 and are billed separately. PGT testing, ICSI, and frozen transfers "
                   f"add more, so an all-in single-cycle total is often several thousand dollars above the quoted price.")},
            {'q': "IUI vs IVF: when is each used?",
             'a': ("IUI is a lower-cost, less invasive option often tried first; IVF is more involved and more "
                   "expensive but has higher per-cycle success for many diagnoses. Which applies is a clinical "
                   "decision your fertility provider makes, not a cost decision alone.")},
        ]
    elif label == 'Egg Freezing':
        faqs += [
            {'q': "What does egg freezing really cost per year?",
             'a': (f"The retrieval-and-freeze price in {city_state} has a median of ${stats['median']:,}, but annual "
                   f"cryostorage (commonly $500–$1,000/year) continues for as long as the eggs are stored, and "
                   f"medications during the cycle are usually separate.")},
            {'q': "How is egg freezing different from IVF in cost?",
             'a': ("Egg freezing uses the same stimulation and retrieval as IVF, then stops at freezing, so it costs "
                   "less than a full IVF cycle. Using the eggs later requires thawing, fertilization, and transfer, an additional IVF-style cost down the road. "
                   "an additional IVF-style cost down the road.")},
        ]
    else:  # IUI
        faqs += [
            {'q': "How many IUI cycles are typical before IVF?",
             'a': ("Many patients try a few IUI cycles before moving to IVF, so multiply the per-cycle price by the "
                   "expected number of attempts. When to switch to IVF is a clinical decision your provider makes.")},
            {'q': "Does a medicated IUI cycle cost more?",
             'a': ("Yes. A natural-cycle IUI uses few or no medications, while a medicated cycle adds the cost of "
                   "oral or injectable fertility drugs, with injectables the most expensive.")},
        ]
    faqs.append({
        'q': f"Does insurance cover {cfg['noun_plain']}?",
        'a': ("Coverage varies by state and employer. Florida does not mandate IVF or fertility coverage, so most "
              "Miami patients pay cash. Some employers offer a fertility benefit; check your plan. All prices shown "
              "here are advertised cash-pay estimates.")})
    if cmp and label == 'IVF':
        faqs.append({
            'q': "Are hospital IVF programs more expensive than fertility clinics?",
            'a': (f"In {city_state}, hospital-based programs advertise a median of ${cmp['hosp']['median']:,} versus "
                  f"${cmp['fc']['median']:,} at standalone fertility clinics, about {cmp['pct']}% "
                  f"{'more' if cmp['hosp_pricier'] else 'less'}. Confirm what each quote includes, since bundling differs.")})
    return faqs


# ---------------------------------------------------------------------------
# Views — per-procedure hub / cheapest / national
# ---------------------------------------------------------------------------

def _answer(cfg, city_state, stats, n, updated_at):
    upd = f", updated {updated_at:%B %Y}" if updated_at else ""
    return (f"Cash-pay {cfg['noun_plain']} in {city_state} costs ${stats['min']:,} to ${stats['max']:,}, "
            f"median ${stats['median']:,}, across {n} providers{upd}.")


def _base_ctx(cfg, key):
    return {
        'cfg': cfg, 'proc_key': key, 'label': cfg['label'], 'noun_plain': cfg['noun_plain'],
        'proc_slug': cfg['proc_slug'], 'affects_title': cfg['affects_title'], 'affects': cfg['affects'],
        'included_note': INCLUDED_NOTE[key],
        'hub_url': cfg['city_url'], 'national_url': cfg['nat_url'],
        'cheapest_url': cfg['city_url'] + 'cheapest/',
        'best_url': (cfg['city_url'] + 'best/') if cfg['full'] else None,
        'report_url': (cfg['city_url'] + 'report/') if cfg['full'] else None,
        'cluster_url': '/cash/fertility/miami-fl/', 'methodology_url': '/methodology/',
    }


@cache_page(86400)
def proc_hub(request, key):
    cfg = _cfg(key)
    location = get_object_or_404(Location, slug=FERTILITY_CITY_SLUG)
    market = build_market(cfg['proc_slug'], location)
    city_state = f"{location.city}, {location.state}"
    if market['thin_data']:
        return render(request, 'healthcare/fertility_proc_hub.html', {
            **_base_ctx(cfg, key), 'thin_data': True, 'noindex': True,
            'provider_count': market['provider_count'], 'thin_threshold': THIN_DATA_THRESHOLD,
            'city_state': city_state, 'location': location})
    stats = market['stats']
    updated_at = market['updated_at']
    ranked = market['ranked']
    type_rows, cmp = _type_compare(ranked)
    national_median, _c, _n, _r = _national_snapshot(cfg['proc_slug'])
    shown = ranked[:25]
    cheapest_name = ranked[0]['name'] if ranked else None
    faqs = _faqs(cfg, location.city, city_state, stats, cheapest_name, market['provider_count'], cmp)
    page_url = f"https://zenthir.com{cfg['city_url']}"
    ctx = {
        **_base_ctx(cfg, key), 'thin_data': False, 'noindex': False,
        'location': location, 'city_state': city_state,
        'answer': _answer(cfg, city_state, stats, market['provider_count'], updated_at),
        'stats': stats, 'provider_count': market['provider_count'],
        'ranked_providers': shown, 'total_ranked': market['provider_count'],
        'price_bands': _price_bands(ranked, stats), 'type_rows': type_rows, 'type_compare': cmp,
        'national_median': national_median or None, 'updated_at': updated_at,
        'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'hub_schema': _market_schema(cfg, stats, market['provider_count'], updated_at, _crumbs(cfg)),
        'itemlist_jsonld': _itemlist(cfg, shown, f"{cfg['label']} providers in {city_state} ranked by price"),
        'canonical_url': page_url,
    }
    return render(request, 'healthcare/fertility_proc_hub.html', ctx)


@cache_page(86400)
def proc_cheapest(request, key):
    cfg = _cfg(key)
    location = get_object_or_404(Location, slug=FERTILITY_CITY_SLUG)
    market = build_market(cfg['proc_slug'], location)
    city_state = f"{location.city}, {location.state}"
    if market['thin_data']:
        return render(request, 'healthcare/fertility_cheapest.html', {
            **_base_ctx(cfg, key), 'thin_data': True, 'noindex': True,
            'provider_count': market['provider_count'], 'thin_threshold': THIN_DATA_THRESHOLD,
            'city_state': city_state, 'location': location})
    stats = market['stats']
    updated_at = market['updated_at']
    below = [p for p in market['ranked'] if p['price'] <= stats['median']]
    for p in below:
        p['save'] = stats['median'] - p['price']
    cheapest_price = below[0]['price'] if below else stats['min']
    savings = stats['median'] - cheapest_price
    _t, cmp = _type_compare(market['ranked'])
    faqs = _faqs(cfg, location.city, city_state, stats, below[0]['name'] if below else None, market['provider_count'], cmp)
    page_url = f"https://zenthir.com{cfg['city_url']}cheapest/"
    ctx = {
        **_base_ctx(cfg, key), 'thin_data': False, 'noindex': False,
        'location': location, 'city_state': city_state,
        'answer': (f"The cheapest cash-pay {cfg['noun_plain']} in {city_state} starts at ${cheapest_price:,}. "
                   f"{len(below)} of {market['provider_count']} providers price at or below the ${stats['median']:,} median."),
        'stats': stats, 'provider_count': market['provider_count'],
        'below_providers': below, 'below_count': len(below), 'cheapest_price': cheapest_price, 'savings': savings,
        'updated_at': updated_at, 'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'hub_schema': _market_schema(cfg, stats, len(below), updated_at, _crumbs(cfg, 'Cheapest', page_url)),
        'itemlist_jsonld': _itemlist(cfg, below, f"Cheapest {cfg['label']} providers in {city_state}"),
        'canonical_url': page_url,
    }
    return render(request, 'healthcare/fertility_cheapest.html', ctx)


@cache_page(86400)
def proc_national(request, key):
    cfg = _cfg(key)
    records = _records(cfg['proc_slug'], None)
    rows = list(records.values_list('provider__location__slug', 'provider__location__city',
                                    'provider__location__state', 'cash_price'))
    if not rows:
        raise Http404("No pricing data")
    raw = sorted(float(r[3]) for r in rows)
    floor = raw[len(raw) // 2] * 0.10
    stats = price_stats([p for p in raw if p >= floor])
    provider_count = len(rows)
    updated_at = records.aggregate(m=Max('updated_at'))['m']
    city_prices = defaultdict(list)
    meta = {}
    for slug, city, state, price in rows:
        if not slug or is_malformed_location(city, state):
            continue
        city_prices[slug].append(float(price))
        meta[slug] = (city, state)
    cities = []
    for slug, pl in city_prices.items():
        if len(pl) < 8:
            continue
        pl.sort()
        city, state = meta[slug]
        cities.append({'slug': slug, 'city': city, 'state': state, 'count': len(pl),
                       'median': round(pl[len(pl) // 2]), 'low': round(pl[0]), 'high': round(pl[-1]),
                       'url': (cfg['city_url'] if slug == 'miami-fl' else f"/cash/{cfg['proc_slug']}/{slug}/")})
    top_cities = sorted(cities, key=lambda c: -c['count'])[:18]
    affordable = sorted(cities, key=lambda c: c['median'])[:8]
    expensive = sorted(cities, key=lambda c: -c['median'])[:8]
    faqs = _faqs(cfg, 'the US', 'the US', stats, None, provider_count, None)
    page_url = f"https://zenthir.com{cfg['nat_url']}"
    crumbs = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://zenthir.com/"},
        {"@type": "ListItem", "position": 2, "name": "Fertility", "item": "https://zenthir.com/cash/fertility/miami-fl/"},
        {"@type": "ListItem", "position": 3, "name": cfg['label'], "item": page_url},
    ]
    ctx = {
        **_base_ctx(cfg, key), 'thin_data': False,
        'answer': (f"Cash-pay {cfg['noun_plain']} in the US costs ${stats['min']:,} to ${stats['max']:,}, "
                   f"median ${stats['median']:,}, across {provider_count:,} providers."),
        'stats': stats, 'provider_count': provider_count, 'n_cities': len(cities), 'updated_at': updated_at,
        'top_cities': top_cities, 'affordable': affordable, 'expensive': expensive,
        'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'national_schema': _market_schema(cfg, stats, provider_count, updated_at, crumbs, national=True),
        'miami_url': cfg['city_url'], 'canonical_url': page_url,
    }
    return render(request, 'healthcare/fertility_national.html', ctx)


# ---------------------------------------------------------------------------
# IVF best + report
# ---------------------------------------------------------------------------

def _best_faqs(cfg, city_state, stats, n):
    return [
        {'q': f"What makes an {cfg['label']} provider the best?",
         'a': (f"On Zenthir, “best” is data-ranked, not editorial. A provider ranks higher when its "
               f"advertised cash price is competitive against the ${stats['median']:,} {city_state} median, it "
               f"lists more procedures, and it has claimed or verified its profile. Ranking is never influenced by payment.")},
        {'q': "How are the rankings calculated?",
         'a': (f"Each of the {n} providers gets a composite score from four public signals: price competitiveness "
               f"({BEST_W_PRICE}%), number of procedures listed ({BEST_W_BREADTH}%), verification status "
               f"({BEST_W_VERIFIED}%), and provider-type relevance ({BEST_W_TYPE}%). Scores use advertised market data only.")},
        {'q': "Can providers pay for a higher ranking?",
         'a': ("No, never. Ranking position cannot be bought. Claiming a profile lets a provider correct its "
               "information and receive quote requests, but it does not move it up the list.")},
    ]


@cache_page(86400)
def ivf_best(request):
    cfg = _cfg('ivf')
    location = get_object_or_404(Location, slug=FERTILITY_CITY_SLUG)
    market = build_market(cfg['proc_slug'], location)
    city_state = f"{location.city}, {location.state}"
    if market['thin_data']:
        return render(request, 'healthcare/fertility_best.html', {
            **_base_ctx(cfg, 'ivf'), 'thin_data': True, 'noindex': True,
            'provider_count': market['provider_count'], 'thin_threshold': THIN_DATA_THRESHOLD,
            'city_state': city_state, 'location': location})
    stats = market['stats']
    ranked = market['ranked']
    counts = _procedure_counts([p['provider_id'] for p in ranked])
    for p in ranked:
        p['proc_count'] = counts.get(p['provider_id'], 1)
    _rank_best(ranked, stats)
    full = sorted(ranked, key=lambda p: (-p['score'], p['price']))
    best = full[:25]
    _assign_best_tiers(best, stats)
    cheapest = min(ranked, key=lambda p: p['price'])
    cheapest_rank = next(i for i, p in enumerate(full, 1) if p['provider_id'] == cheapest['provider_id'])
    di = {
        'top25_avg': round(sum(p['price'] for p in best) / len(best)), 'market_avg': stats['avg'],
        'top25_below_market_pct': (round((stats['avg'] - round(sum(p['price'] for p in best) / len(best))) / stats['avg'] * 100) if stats['avg'] else 0),
        'top25_low': min(p['price'] for p in best), 'top25_high': max(p['price'] for p in best),
        'cheapest_name': cheapest['name'], 'cheapest_price': cheapest['price'], 'cheapest_rank': cheapest_rank,
        'top_provider_name': best[0]['name'], 'top_provider_price': best[0]['price'],
    }
    faqs = _best_faqs(cfg, city_state, stats, market['provider_count'])
    page_url = f"https://zenthir.com{cfg['city_url']}best/"
    ctx = {
        **_base_ctx(cfg, 'ivf'), 'thin_data': False, 'noindex': False,
        'location': location, 'city_state': city_state,
        'answer': (f"Based on pricing, verification status, and procedure range, these are the top-ranked IVF "
                   f"providers in {location.city} across {market['provider_count']} providers."),
        'stats': stats, 'provider_count': market['provider_count'],
        'best_providers': best, 'total_ranked': market['provider_count'], 'updated_at': market['updated_at'],
        'data_insights': di, 'weights': {'price': BEST_W_PRICE, 'breadth': BEST_W_BREADTH, 'verified': BEST_W_VERIFIED, 'type': BEST_W_TYPE},
        'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'best_schema': _breadcrumb_schema(_crumbs(cfg, 'Best Providers', page_url)),
        'itemlist_jsonld': _itemlist(cfg, best, f"Best IVF providers in {city_state}"),
        'canonical_url': page_url,
    }
    return render(request, 'healthcare/fertility_best.html', ctx)


@cache_page(86400)
def ivf_report(request):
    cfg = _cfg('ivf')
    location = get_object_or_404(Location, slug=FERTILITY_CITY_SLUG)
    market = build_market(cfg['proc_slug'], location)
    city = location.city
    city_state = f"{city}, {location.state}"
    if market['thin_data']:
        return render(request, 'healthcare/fertility_report.html', {
            **_base_ctx(cfg, 'ivf'), 'thin_data': True, 'noindex': True,
            'provider_count': market['provider_count'], 'thin_threshold': THIN_DATA_THRESHOLD,
            'city_state': city_state, 'location': location})
    stats = market['stats']
    ranked = market['ranked']
    prices = [p['price'] for p in ranked]
    provider_count = market['provider_count']
    updated_at = market['updated_at']

    distribution = _distribution(prices, cfg['dist_bands'])
    type_rows, cmp = _type_compare(ranked)
    districts = _neighborhood_districts(ranked)
    gd = cfg['good_deal']
    good_deal_pct = round(sum(1 for p in prices if p < gd) / provider_count * 100) if provider_count else 0
    mid_pct = round(sum(1 for p in prices if cfg['mid_low'] <= p < cfg['mid_high']) / provider_count * 100) if provider_count else 0

    national_median, cities, n_cities, _r = _national_snapshot(cfg['proc_slug'])
    miami_vs_national = round((stats['median'] - national_median) / national_median * 100) if national_median else 0
    metros = []
    for slug in REPORT_COMPARE_METROS:
        c = cities.get(slug)
        if not c:
            continue
        d = round((stats['median'] - c['median']) / c['median'] * 100) if c['median'] else 0
        metros.append({**c, 'diff_vs_miami': d})
    by_count = sorted(cities.values(), key=lambda c: -c['count'])
    miami_rank = next((i for i, c in enumerate(by_count, 1) if c['slug'] == FERTILITY_CITY_SLUG), None)
    competition = by_count[:8]

    answer = (f"{city} patients paid between ${stats['min']:,} and ${stats['max']:,} for an IVF cycle in 2026, "
              f"with a median of ${stats['median']:,} across {provider_count} providers.")
    key_findings = [
        f"The median advertised cash price for one IVF cycle in {city} is ${stats['median']:,}, ranging "
        f"${stats['min']:,} to ${stats['max']:,} across {provider_count} providers.",
        f"Quoted prices usually exclude medications ($3,000–$5,000), PGT testing, ICSI, and frozen transfers, "
        f"so an all-in single-cycle total runs well above the sticker price.",
    ]
    if cmp:
        key_findings.append(
            f"Hospital-based programs advertise a ${cmp['hosp']['median']:,} median versus ${cmp['fc']['median']:,} "
            f"at standalone fertility clinics, about {cmp['pct']}% {'more' if cmp['hosp_pricier'] else 'less'}.")
    if national_median:
        w = 'above' if miami_vs_national > 0 else 'below' if miami_vs_national < 0 else 'even with'
        key_findings.append(f"{city} sits {abs(miami_vs_national)}% {w} the ${national_median:,} national IVF median.")
    key_findings.append(f"{good_deal_pct}% of {city} providers price a cycle under ${gd:,}; about {mid_pct}% fall "
                        f"between ${cfg['mid_low']:,} and ${cfg['mid_high']:,}.")

    faqs = _faqs(cfg, city, city_state, stats, ranked[0]['name'] if ranked else None, provider_count, cmp)
    page_url = f"https://zenthir.com{cfg['city_url']}report/"
    ctx = {
        **_base_ctx(cfg, 'ivf'), 'thin_data': False, 'noindex': False,
        'location': location, 'city': city, 'city_state': city_state,
        'answer': answer, 'stats': stats, 'provider_count': provider_count, 'updated_at': updated_at,
        'distribution': distribution, 'good_deal_pct': good_deal_pct, 'good_deal_max': gd,
        'mid_band_pct': mid_pct, 'mid_band_low': cfg['mid_low'], 'mid_band_high': cfg['mid_high'],
        'type_rows': type_rows, 'type_compare': cmp,
        'districts': districts, 'report_min_district': REPORT_MIN_DISTRICT,
        'national_median': national_median or None, 'miami_vs_national': miami_vs_national, 'n_cities': n_cities,
        'metros': metros, 'competition': competition, 'miami_rank': miami_rank,
        'key_findings': key_findings, 'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'report_schema': _breadcrumb_schema(_crumbs(cfg, 'Price Report', page_url)),
        'canonical_url': page_url,
    }
    return render(request, 'healthcare/fertility_report.html', ctx)


# ---------------------------------------------------------------------------
# Cluster hub — /cash/fertility/miami-fl/
# ---------------------------------------------------------------------------

@cache_page(86400)
def cluster_hub(request):
    location = get_object_or_404(Location, slug=FERTILITY_CITY_SLUG)
    city_state = f"{location.city}, {location.state}"
    cards = []
    for key in ('iui', 'ivf', 'egg-freezing'):   # ordered low -> high cost (a common path, not advice)
        cfg = PROCS[key]
        m = build_market(cfg['proc_slug'], location)
        if m.get('thin_data'):
            continue
        s = m['stats']
        cards.append({
            'key': key, 'label': cfg['label'], 'noun_plain': cfg['noun_plain'],
            'median': s['median'], 'min': s['min'], 'max': s['max'], 'count': m['provider_count'],
            'url': cfg['city_url'],
        })
    updated_at = None
    faqs = [
        {'q': "What fertility treatments can I compare here?",
         'a': ("This hub covers cash-pay pricing for IUI, IVF, and egg freezing in " + city_state + ", drawn from "
               "providers advertising prices. Each has its own detailed pricing page.")},
        {'q': "Does insurance cover fertility treatment in Florida?",
         'a': ("Florida does not mandate IVF or fertility coverage, so most Miami patients pay cash. Some employers "
               "offer a fertility benefit; check your plan. Prices shown are advertised cash-pay estimates.")},
        {'q': "Why is IVF so much more expensive than IUI?",
         'a': ("IUI places prepared sperm in the uterus, a simple in-office procedure. IVF adds egg retrieval, lab "
               "fertilization, embryo culture, and transfer, far more clinical work, which is why the median cost "
               "is many times higher.")},
    ]
    page_url = "https://zenthir.com/cash/fertility/miami-fl/"
    crumbs = [
        {"@type": "ListItem", "position": 1, "name": "Home", "item": "https://zenthir.com/"},
        {"@type": "ListItem", "position": 2, "name": "Fertility", "item": page_url},
        {"@type": "ListItem", "position": 3, "name": "Miami, FL", "item": page_url},
    ]
    ctx = {
        'location': location, 'city_state': city_state, 'cards': cards,
        'faqs': faqs, 'faq_jsonld': faq_jsonld(faqs),
        'cluster_schema': _breadcrumb_schema(crumbs),
        'methodology_url': '/methodology/', 'canonical_url': page_url,
        'ivf_url': '/cash/ivf/miami-fl/', 'egg_url': '/cash/egg-freezing/miami-fl/', 'iui_url': '/cash/iui/miami-fl/',
    }
    return render(request, 'healthcare/fertility_hub.html', ctx)
