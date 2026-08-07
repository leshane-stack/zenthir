"""Zenthir Summary — a data-generated, factual, SPECIALTY-AWARE provider paragraph.

Template-rendered from existing DB fields only (PricingRecord / ProcedureMedian /
Procedure / ClaimRequest). Not AI-generated. Every summary answers: who are they,
what kind of provider, how much data we have, is it verified, and (optionally) one
recognizable fact.

Design rules:
- Generate by provider_type, not one generic template.
- Never name the most expensive procedure. Hospitals/surgery centers name NO
  procedures — only a rounded price range + count.
- Recognizable procedures come from a small per-specialty keyword list matched
  against the provider's actual procedure DISPLAY names (never raw .name).
- Large prices round to the nearest thousand; market comparison only for cosmetic
  specialties and only when a recognizable procedure has median data.
- Keep it short (~70 words), degrade gracefully when data is missing.
"""

# Per-specialty keywords matched (word-boundary, case-insensitive) against the
# provider's procedure display_names. Order = priority (first matches listed first).
SPECIALTY_KEYWORDS = {
    'Plastic Surgery Practice': ['Botox', 'Rhinoplasty', 'Breast Augmentation', 'Liposuction',
                                 'Facelift', 'CoolSculpting', 'Fillers', 'Blepharoplasty', 'BBL', 'Tummy Tuck'],
    'Cosmetic Surgery': ['Botox', 'Rhinoplasty', 'Breast Augmentation', 'Liposuction',
                         'Facelift', 'CoolSculpting', 'Fillers', 'Blepharoplasty', 'BBL', 'Tummy Tuck'],
    'Med Spa': ['Botox', 'Fillers', 'CoolSculpting', 'Laser', 'Microneedling', 'Chemical Peel', 'HydraFacial'],
    'Dermatology': ['Botox', 'Fillers', 'CoolSculpting', 'Laser', 'Microneedling', 'Chemical Peel', 'Mohs'],
    'Dental Office': ['Implant', 'Crown', 'Root Canal', 'Whitening', 'Veneer', 'Cleaning', 'Extraction'],
    'Dentist': ['Implant', 'Crown', 'Root Canal', 'Whitening', 'Veneer', 'Cleaning', 'Extraction'],
    'Orthodontist': ['Braces', 'Invisalign', 'Implant', 'Retainer'],
    'Fertility Clinic': ['IVF', 'Egg Freezing', 'IUI', 'Embryo Transfer', 'PGT'],
    'Eye Center': ['LASIK', 'Cataract', 'PRK'],
    'Eye Care': ['LASIK', 'Cataract', 'PRK'],
    'Imaging Center': ['MRI', 'CT', 'Ultrasound', 'X-Ray', 'PET', 'Mammogram', 'DEXA'],
    'Diagnostic Radiology': ['MRI', 'CT', 'Ultrasound', 'X-Ray', 'PET', 'Mammogram', 'DEXA'],
}

# Specialty groups -> which template to render.
_HOSPITAL_TYPES = {'Hospital', 'Surgery Center', 'General Surgery',
                   'Ambulatory Surgical Center', 'Emergency Room'}
_IMAGING_TYPES = {'Imaging Center', 'Diagnostic Radiology'}
_DENTAL_TYPES = {'Dental Office', 'Dentist', 'Orthodontist', 'Dental Clinic',
                 'Oral Surgery', 'Periodontics'}
_COSMETIC_TYPES = {'Plastic Surgery Practice', 'Cosmetic Surgery', 'Med Spa', 'Dermatology'}
_FERTILITY_TYPES = {'Fertility Clinic'}
_EYE_TYPES = {'Eye Center', 'Eye Care', 'Ophthalmology'}


def _round_price(x):
    """Round for readability: large prices to the nearest thousand ($13,031 -> $13,000)."""
    x = float(x)
    if x >= 1000:
        return int(round(x / 1000.0) * 1000)
    if x >= 100:
        return int(round(x / 100.0) * 100)
    return int(round(x / 10.0) * 10)


def _money_round(x):
    return "${:,}".format(_round_price(x))


def _article(word):
    return 'an' if word[:1].lower() in 'aeiou' else 'a'


def _median_for(provider, procedure):
    """(median_value, scope) — same-type city ProcedureMedian, else national_median."""
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
    pct = round((price - median) / median * 100)
    if abs(pct) <= 5:
        return 0, 'near'
    return abs(pct), ('below' if pct < 0 else 'above')


def _fmt_date(d):
    if not d:
        return ''
    return f"{d:%B} {d.day}, {d.year}"


def _kw_match(display_name, keyword):
    """Word-boundary, case-insensitive match of a keyword in a display name."""
    import re
    return bool(re.search(r'\b' + re.escape(keyword) + r'\b', display_name, re.IGNORECASE))


def _dname(record):
    """Text to MATCH keywords against. Prefers display_name; falls back to name
    only for detection (the summary only ever OUTPUTS the clean keyword, never
    this raw text) so specialties whose display_name is blank still resolve."""
    return (record.procedure.display_name or record.procedure.name or '')


def _matched_keywords(priced, keywords, limit=3):
    """Recognizable procedures present, in keyword-priority order, max `limit`."""
    names = [_dname(r) for r in priced]
    out = []
    for kw in keywords:
        if any(_kw_match(dn, kw) for dn in names):
            out.append(kw)
        if len(out) >= limit:
            break
    return out


def _verified_sentence(tier, has_enhanced_details, date_str):
    if tier in ('paid_basic', 'paid_premium') and has_enhanced_details:
        return "This provider has confirmed pricing and published additional transparency information."
    if tier in ('verified', 'paid_basic', 'paid_premium'):
        if date_str:
            return f"Pricing was last confirmed by the provider on {date_str}."
        return "Pricing has been confirmed by the provider."
    return "This profile has not yet been verified by the provider."


def _cosmetic_comparison(provider, priced, keywords):
    """Sentence comparing the cheapest RECOGNIZABLE procedure to the local median,
    or '' when none qualifies. Cosmetic specialties only (caller enforces)."""
    best = None  # (price, keyword, median)
    for r in priced:
        dn = _dname(r)
        kw = next((k for k in keywords if _kw_match(dn, k)), None)
        if not kw:
            continue
        median, _scope = _median_for(provider, r.procedure)
        if not median:
            continue
        price = float(r.cash_price)
        if best is None or price < best[0]:
            best = (price, kw, median)
    if not best:
        return ''
    price, kw, median = best
    pct, direction = _pct_dir(price, median)
    if direction == 'near':
        return f"{kw} is priced near the local median."
    return f"{kw} is approximately {pct}% {direction} the local median."


def zenthir_summary(provider, pricing, tier, confirmed_date, has_enhanced_details):
    """Specialty-aware, factual provider summary (str). Never names the most
    expensive procedure; never forces names into hospital summaries."""
    ptype = provider.provider_type.name if provider.provider_type else 'healthcare provider'
    city = provider.location.city if provider.location else ''
    state = provider.location.state if provider.location else ''
    loc = f"{city}, {state}" if city and state else (city or '')
    where = f" in {loc}" if loc else ''
    intro = f"{provider.name} is {_article(ptype)} {ptype}{where}."

    date_str = _fmt_date(confirmed_date)
    vsent = _verified_sentence(tier, has_enhanced_details, date_str)

    priced = [r for r in pricing if r.cash_price and float(r.cash_price) > 0]
    n = len(priced)
    if n == 0:
        return f"{intro} {vsent}"

    lowest = min(float(r.cash_price) for r in priced)
    highest = max(float(r.cash_price) for r in priced)
    keywords = SPECIALTY_KEYWORDS.get(ptype, [])
    recs = _matched_keywords(priced, keywords) if keywords else []

    # ---- HOSPITAL / SURGERY CENTER: never name procedures ----
    if ptype in _HOSPITAL_TYPES:
        noun = 'hospital procedures' if ptype == 'Hospital' else 'surgical procedures'
        body = (f"Zenthir tracks pricing for {n} {noun} at this facility, with prices "
                f"ranging from approximately {_money_round(lowest)} to {_money_round(highest)}.")
        return f"{intro} {body} {vsent}"

    # ---- IMAGING / DIAGNOSTIC RADIOLOGY: list modalities, no count/range ----
    if ptype in _IMAGING_TYPES:
        if recs:
            body = f"Zenthir tracks pricing for {', '.join(recs)} services at this location."
            return f"{intro} {body} {vsent}"
        # fall through to default when nothing recognizable matched

    # ---- COSMETIC (plastic / cosmetic / med spa / dermatology) ----
    if ptype in _COSMETIC_TYPES and recs:
        body = f"Zenthir tracks pricing for {n} cosmetic procedures, including {', '.join(recs)}."
        comp = _cosmetic_comparison(provider, priced, keywords)
        if comp:
            body += " " + comp
        return f"{intro} {body} {vsent}"

    # ---- DENTAL ----
    if ptype in _DENTAL_TYPES and recs:
        body = f"Zenthir tracks pricing for {n} dental procedures, including {', '.join(recs)}."
        return f"{intro} {body} {vsent}"

    # ---- FERTILITY ----
    if ptype in _FERTILITY_TYPES and recs:
        body = f"Zenthir tracks pricing for {', '.join(recs)}."
        return f"{intro} {body} {vsent}"

    # ---- EYE ----
    if ptype in _EYE_TYPES and recs:
        body = f"Zenthir tracks pricing for {', '.join(recs)} at this location."
        return f"{intro} {body} {vsent}"

    # ---- DEFAULT (anything else, or specialties with no keyword match) ----
    procs = f"{n} procedure" + ('' if n == 1 else 's')
    body = (f"Zenthir tracks pricing for {procs}, with prices ranging from approximately "
            f"{_money_round(lowest)} to {_money_round(highest)}.")
    return f"{intro} {body} {vsent}"
