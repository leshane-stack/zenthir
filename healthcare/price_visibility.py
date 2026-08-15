"""Single source of truth for WHICH prices may be displayed.

Only PricingRecord rows whose ``source_name`` starts with an allowlisted prefix
may be rendered, schema'd, dated, or included in any median / percentile / range
/ market-position calculation. Everything else is suppressed at the data layer,
so pages degrade to their no-price variant instead of showing fabricated numbers.

Allowlist (prefix / startswith), confirmed against prod source_name families:
real CMS, real payer-MRF (BCBS/UHC), and real hospital-MRF rows only. The
fabricated families (``Market Estimate``, ``CMS Price Transparency``,
``Provider Website``, ``Aggregated Estimate``) match no prefix and are suppressed
— note two of them imitate real source names, which is why this is an allowlist.

Prefix match (not exact) so the ~8,000 ``Hospital Negotiated (<payer>)`` variants
and future import vintages need no enumeration. Any source_name that matches no
prefix is logged loudly (see ``audit_source_names``) so a future import landing
under a new name surfaces instead of being silently hidden.
"""
import logging

from django.db.models import Q

logger = logging.getLogger('healthcare.price_visibility')

ALLOWED_SOURCE_PREFIXES = (
    'BCBS Negotiated Rate',
    'UHC Negotiated Rate',
    'CMS Medicare Physician Data',
    'CMS Medicare Provider Charge Data',
    'Hospital Negotiated (',
    'Hospital Rate (cash)',
    'Hospital Max Rate',
    'Hospital Chargemaster (Gross)',
    'Hospital Min Rate',
)


def is_allowed(source_name):
    """True iff source_name starts with an allowlisted prefix."""
    if not source_name:
        return False
    return any(source_name.startswith(p) for p in ALLOWED_SOURCE_PREFIXES)


def _allow_q():
    q = Q()
    for p in ALLOWED_SOURCE_PREFIXES:
        q |= Q(source_name__startswith=p)
    return q


# Reusable Q for `.filter(ALLOWED_Q)` on any PricingRecord queryset.
ALLOWED_Q = _allow_q()


def allowed(qs):
    """Restrict a PricingRecord queryset to displayable (allowlisted) rows."""
    return qs.filter(ALLOWED_Q)


def filter_records(records):
    """Restrict an in-memory iterable of PricingRecord to allowlisted rows.

    For code paths that already hold a materialized list (e.g. provider.pricing
    after dedup) rather than a queryset.
    """
    return [r for r in records if is_allowed(getattr(r, 'source_name', None))]


def audit_source_names(log=None):
    """Log every distinct source_name that matches NO allowlist prefix, with its
    row count, so a new/unexpected import surfaces loudly instead of being
    silently suppressed. Returns the list of (source_name, count) suppressed.

    Cheap: one GROUP BY over the low-selectivity source_name column.
    """
    from django.db.models import Count
    from .models import PricingRecord
    log = log or logger
    suppressed = []
    for r in (PricingRecord.objects.values('source_name')
              .annotate(n=Count('id')).order_by('-n')):
        name = r['source_name'] or ''
        if not is_allowed(name):
            log.warning(
                'PRICE SOURCE SUPPRESSED (no allowlist prefix): source_name=%r rows=%d',
                name, r['n'])
            suppressed.append((name, r['n']))
    if not suppressed:
        log.info('audit_source_names: all source_name families are allowlisted.')
    return suppressed
