"""Zenthir Summary — a data-generated, factual paragraph for each provider page.

Template-rendered from existing database fields ONLY. Not AI-generated: every
sentence is computed from PricingRecord / ProcedureMedian / Procedure /
ClaimRequest. No marketing language, no opinions. This is the paragraph search
engines and AI systems extract, so it must be defensible and provenance-clean.

Graceful degradation: if a computation can't be done (no median, no pricing),
the corresponding sentence is skipped rather than shown wrong or blank.
"""


def _money(x):
    return "${:,}".format(int(round(float(x))))


def _median_for(provider, procedure):
    """(median_value, scope) for a procedure at this provider's location+type.

    scope is 'city' when a same-type ProcedureMedian row exists, else 'national'
    from Procedure.national_median, else (None, None).
    """
    from .models import ProcedureMedian
    if provider.location and provider.provider_type:
        m = ProcedureMedian.objects.filter(
            procedure=procedure, location=provider.location,
            provider_type=provider.provider_type,
        ).first()
        if m and m.median_price and float(m.median_price) > 0:
            return float(m.median_price), 'city'
    nm = getattr(procedure, 'national_median', None)
    if nm and float(nm) > 0:
        return float(nm), 'national'
    return None, None


def _pct_dir(price, median):
    """(abs_pct, direction) where direction is 'below' | 'above' | 'near' (<=5%)."""
    pct = round((price - median) / median * 100)
    if abs(pct) <= 5:
        return 0, 'near'
    return abs(pct), ('below' if pct < 0 else 'above')


def _median_clause(pct, direction, median_word, approximate):
    """e.g. 'approximately 32% below the Miami median' / 'near the local median'."""
    if direction == 'near':
        return f"near the {median_word}"
    lead = "approximately " if approximate else ""
    return f"{lead}{pct}% {direction} the {median_word}"


def _fmt_date(d):
    """'August 7, 2026' without platform-specific strftime codes."""
    if not d:
        return ''
    return f"{d:%B} {d.day}, {d.year}"


def zenthir_summary(provider, pricing, tier, confirmed_date, has_enhanced_details):
    """Return the data-generated summary paragraph (str), or a minimal factual
    fallback. Never returns something misleading or empty of the intro sentence.
    """
    ptype = provider.provider_type.name if provider.provider_type else 'healthcare provider'
    city = provider.location.city if provider.location else ''
    state = provider.location.state if provider.location else ''
    loc = f"{city}, {state}" if city and state else (city or '')
    where = f" in {loc}" if loc else ''

    is_verified = tier in ('verified', 'paid_basic', 'paid_premium')
    is_enhanced = tier in ('paid_basic', 'paid_premium') and has_enhanced_details
    type_phrase = f"provider-verified {ptype}" if is_verified else ptype
    intro = f"{provider.name} is a {type_phrase}{where}."

    priced = [r for r in pricing if r.cash_price and float(r.cash_price) > 0]
    n = len(priced)

    # No pricing at all — degrade to the intro plus a truthful status line.
    if n == 0:
        if is_verified:
            return intro + " This provider has verified their profile with Zenthir."
        return intro + " Zenthir does not yet have pricing data for this practice."

    cheapest = min(priced, key=lambda r: float(r.cash_price))
    most_exp = max(priced, key=lambda r: float(r.cash_price))
    lowest = float(cheapest.cash_price)
    highest = float(most_exp.cash_price)
    cheapest_name = cheapest.procedure.display_name or cheapest.procedure.name
    most_exp_name = most_exp.procedure.display_name or most_exp.procedure.name

    median, scope = _median_for(provider, cheapest.procedure)
    date_str = _fmt_date(confirmed_date)
    procs = f"{n} procedure" + ('' if n == 1 else 's')

    # ---- UNCLAIMED / PENDING ----
    if not is_verified:
        s = intro + f" Zenthir currently tracks pricing for {procs} from this practice"
        if n >= 2:
            s += (f", with prices ranging from {_money(lowest)} for {cheapest_name} "
                  f"to {_money(highest)} for {most_exp_name}.")
        else:
            s += f", priced at {_money(lowest)} for {cheapest_name}."
        if median:
            pct, direction = _pct_dir(lowest, median)
            clause = _median_clause(pct, direction, "local median", approximate=True)
            s += f" Based on available pricing data, {cheapest_name} is {clause}."
        s += " This profile has not yet been verified by the provider."
        return s

    # ---- PROVIDER ENHANCED (paid + published structured details) ----
    if is_enhanced:
        s = (intro + f" The provider has confirmed pricing for {procs} and has published "
             "additional pricing information, including what's included in select "
             "procedures, payment options, and financing details.")
        if median:
            pct, direction = _pct_dir(lowest, median)
            clause = _median_clause(pct, direction, "local market median", approximate=False)
            if direction == 'near':
                s += f" {cheapest_name} pricing is currently listed {clause}"
            else:
                s += f" {cheapest_name} pricing is currently listed at {clause}"
            s += f", with prices last verified on {date_str}." if date_str else "."
        elif date_str:
            s += f" Prices were last verified on {date_str}."
        return s

    # ---- VERIFIED (free, or paid without published details) ----
    s = intro + f" Zenthir tracks pricing for {procs} confirmed by the provider."
    median_word = f"{city} median" if (scope == 'city' and city) else "local median"
    sentence = f"{cheapest_name} is listed at {_money(lowest)}"
    if median:
        pct, direction = _pct_dir(lowest, median)
        sentence += ", " + _median_clause(pct, direction, median_word, approximate=True)
    if n >= 2:
        sentence += (f", while pricing across tracked procedures ranges from "
                     f"{_money(lowest)} to {_money(highest)}.")
    else:
        sentence += "."
    s += " " + sentence
    if date_str:
        s += f" Prices were last confirmed on {date_str}."
    return s
