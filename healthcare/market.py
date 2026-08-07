"""Market Position — consumer-facing 'is this a good price?' comparison.

The Zillow-Zestimate equivalent for a provider's procedures. For each priced
procedure we compare the provider's price to a benchmark median and classify it
into a quartile. Benchmarks, in priority order:

  1. ProcedureMedian for (procedure, provider.location, provider.provider_type)
     — a same-type city median with p25/p75 (true quartiles). Pre-computed.
  2. Procedure.national_median (+ national_p25/p75) — national fallback.

No sales language, no editorial ranking — just where the price sits.
"""
from dataclasses import dataclass, field


@dataclass
class ProcedurePosition:
    slug: str
    name: str
    price: int
    median: int
    benchmark: str          # 'city' | 'national'
    provider_count: int     # peers behind a city benchmark (0 for national)
    pct: int                # abs % distance from median
    direction: str          # 'below' | 'above' | 'at'
    quartile: str           # 'Lowest quartile' | 'Below average' | 'Above average' | 'Highest quartile' | 'Near median'
    is_common: bool
    search_volume: int      # recognizability proxy (0 when unknown)

    @property
    def summary(self):
        if self.direction == 'at':
            return "At the median"
        return f"{self.pct}% {self.direction} median"


def _quartile(price, median, p25, p75):
    """Quartile label. Uses p25/p75 when available (true quartiles); otherwise a
    coarse below/above-median band."""
    if p25 and p75 and p25 > 0 and p75 > 0:
        if price <= p25:
            return 'Lowest quartile'
        if price <= median:
            return 'Below average'
        if price <= p75:
            return 'Above average'
        return 'Highest quartile'
    ratio = price / median if median else 1.0
    if ratio < 0.9:
        return 'Below average'
    if ratio > 1.1:
        return 'Above average'
    return 'Near median'


def _position(record, median, p25, p75, benchmark, provider_count):
    price = float(record.cash_price)
    median = float(median)
    pct = abs(round((median - price) / median * 100)) if median else 0
    if price < median:
        direction = 'below'
    elif price > median:
        direction = 'above'
    else:
        direction = 'at'
    proc = record.procedure
    return ProcedurePosition(
        slug=proc.slug,
        name=(proc.display_name or proc.name),
        price=round(price),
        median=round(median),
        benchmark=benchmark,
        provider_count=provider_count or 0,
        pct=pct,
        direction=direction,
        quartile=_quartile(price, median, p25, p75),
        is_common=bool(proc.is_cash_pay_common),
        search_volume=proc.search_volume_estimate or 0,
    )


def market_position(provider, pricing):
    """Build Market Position data from a provider's deduped priced records.

    Returns {'headline', 'top': [..up to 3..], 'all': [...], 'count': N} or None
    if nothing has a usable benchmark. `pricing` is the already-deduped list of
    PricingRecord the view computed (one per procedure).
    """
    from .models import ProcedureMedian

    priced = [r for r in pricing if r.cash_price and float(r.cash_price) > 0]
    if not priced:
        return None

    # One bounded query for same-type city medians.
    city_medians = {}
    if provider.location and provider.provider_type:
        city_medians = {
            m.procedure_id: m for m in ProcedureMedian.objects.filter(
                procedure_id__in=[r.procedure_id for r in priced],
                location=provider.location,
                provider_type=provider.provider_type,
            )
        }

    positions = []
    for r in priced:
        m = city_medians.get(r.procedure_id)
        if m and m.median_price and float(m.median_price) > 0:
            positions.append(_position(
                r, m.median_price, m.p25, m.p75, 'city', m.provider_count))
            continue
        nm = r.procedure.national_median
        if nm and float(nm) > 0:
            positions.append(_position(
                r, nm, r.procedure.national_p25, r.procedure.national_p75,
                'national', 0))

    if not positions:
        return None

    # Headline = the most recognizable procedure a consumer would shop for.
    # Ranking, all descending: a real city benchmark first (apples-to-apples),
    # then search volume (recognizability, when populated), then cash-pay-common,
    # then the CHEAPEST such procedure — the accessible entry point (e.g. Botox),
    # not the priciest. provider_count is constant per (type, city) so it's no
    # help as a tiebreak here.
    positions.sort(key=lambda p: (
        p.benchmark == 'city',
        p.search_volume,
        p.is_common,
        -p.price,          # negated so cheapest sorts first under reverse=True
    ), reverse=True)

    return {
        'headline': positions[0],
        'top': positions[:3],
        'all': positions,
        'count': len(positions),
    }
