"""Provider profile completeness + display helpers for enrichment data.

`provider_completeness` powers the private completeness meter (verified/featured
providers only). `whats_included` / `payment_methods` shape the structured
enrichment for the public page.
"""

# ProviderProcedureDetail boolean fields whose True/False both carry pricing
# meaning. (field, true_text, false_text) — false_text=None means a False is
# not worth surfacing (skip it; only True shows a ✓).
_INCLUDE_FIELDS = [
    ('includes_consultation', 'Includes consultation', None),
    ('includes_interpretation', 'Includes interpretation / reading', 'Interpretation billed separately'),
    ('includes_facility_fee', 'No separate facility fee', 'Facility fee billed separately'),
    ('includes_anesthesia', 'Includes anesthesia', 'Anesthesia billed separately'),
    ('includes_followup', 'Includes follow-up visit', None),
    ('self_pay_discount', 'Self-pay discount', None),
    ('financing_available', 'Financing available', None),
    ('price_guaranteed', 'Price guaranteed', None),
    ('good_faith_estimate_available', 'Good Faith Estimate available', None),
]

_TURNAROUND_TEXT = {
    'same_day': 'Results same day',
    '24_hours': 'Results in 24 hours',
    '48_hours': 'Results in 48 hours',
    '3_5_days': 'Results in 3–5 days',
    '1_week': 'Results in 1 week',
}

# Fields that count toward "this procedure detail is meaningfully filled".
_PPD_FILLABLE = [
    'includes_consultation', 'includes_interpretation', 'includes_facility_fee',
    'includes_anesthesia', 'includes_followup', 'financing_available',
    'self_pay_discount', 'price_guaranteed', 'good_faith_estimate_available',
]


def whats_included(ppd):
    """List of {'ok': bool, 'text': str} for a ProviderProcedureDetail.

    Only surfaces True values (✓) and the few Falses that matter (✗). NULL
    (unknown) is skipped entirely.
    """
    items = []
    for field, true_text, false_text in _INCLUDE_FIELDS:
        val = getattr(ppd, field)
        if val is True:
            items.append({'ok': True, 'text': true_text})
        elif val is False and false_text:
            items.append({'ok': False, 'text': false_text})
    if ppd.turnaround and ppd.turnaround in _TURNAROUND_TEXT:
        items.append({'ok': True, 'text': _TURNAROUND_TEXT[ppd.turnaround]})
    return items


def ppd_filled_count(ppd):
    """How many structured fields are set (non-null booleans + turnaround + notes)."""
    n = sum(1 for f in _PPD_FILLABLE if getattr(ppd, f) is not None)
    if ppd.turnaround:
        n += 1
    if (ppd.provider_notes or '').strip():
        n += 1
    return n


def payment_methods(profile):
    """Human-readable list of accepted payment methods from a ProviderProfile."""
    if not profile:
        return []
    out = []
    if profile.payment_cash:
        out.append('Cash')
    if profile.payment_credit:
        out.append('Credit card')
    if profile.payment_hsa:
        out.append('HSA')
    if profile.payment_fsa:
        out.append('FSA')
    if profile.payment_carecredit:
        out.append('CareCredit')
    if (profile.payment_other or '').strip():
        out.append(profile.payment_other.strip())
    return out


def provider_completeness(provider):
    """Return {'score': 0-100, 'filled': [labels], 'missing': [labels]}.

    A fixed 11-point checklist across contact, profile enrichment, and whether
    the provider has at least one procedure detail with >= 3 fields filled.
    """
    from .models import ProviderProfile, ProviderProcedureDetail

    profile = ProviderProfile.objects.filter(provider=provider).first()

    has_pricing_detail = any(
        ppd_filled_count(ppd) >= 3
        for ppd in ProviderProcedureDetail.objects.filter(provider=provider)
    )

    checks = [
        ('Phone', bool(provider.phone)),
        ('Website', bool(provider.website)),
        ('Profile', profile is not None),
        ('Logo', bool(profile and profile.logo)),
        ('Description', bool((profile and profile.description) or provider.description)),
        ('Payment methods', bool(profile and payment_methods(profile))),
        ('Financing', bool(profile and (profile.financing_available or profile.financing_details))),
        ('Preparation', bool(profile and profile.preparation_instructions)),
        ('Equipment', bool(profile and profile.equipment_notes)),
        ('Languages', bool(profile and profile.languages)),
        ('Pricing details', has_pricing_detail),
    ]

    filled = [label for label, ok in checks if ok]
    missing = [label for label, ok in checks if not ok]
    score = round(len(filled) / len(checks) * 100)
    return {'score': score, 'filled': filled, 'missing': missing}
