"""Provider tier resolution + cache invalidation for the Claim -> Paid flow.

Tier state lives on ClaimRequest (never on the 2.9M-row Provider table). Only
claimed providers ever have a row, so these lookups stay small and hit the
provider FK index. `tier` is the source of truth; `status` is kept for
moderation and for backward-compat with claims approved before the tier field
existed (those may have status='verified' but tier='pending').
"""
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q

# Tiers that receive consumer leads (the free 'verified' hook + paid tiers).
LEAD_TIERS = ('verified', 'paid_basic', 'paid_premium')
# Paid tiers (enhanced features / featured styling).
PAID_TIERS = ('paid_basic', 'paid_premium')

# Highest-to-lowest precedence when a provider somehow has multiple claims.
_RANK = {'paid_premium': 4, 'paid_basic': 3, 'verified': 2, 'pending': 1}


def _claim_rank(tier, status):
    """Effective rank for one claim row, honouring legacy status='verified'."""
    if status == 'rejected':
        return 0
    r = _RANK.get(tier, 1)
    if r < 2 and status == 'verified':   # legacy row approved pre-tier-field
        return 2
    return r


def provider_tier(provider):
    """Return the effective tier string for a provider.

    One of: 'unclaimed', 'pending', 'verified', 'paid_basic', 'paid_premium'.
    Highest-ranked claim wins.
    """
    from .models import ClaimRequest
    rows = list(
        ClaimRequest.objects.filter(provider=provider).values_list('tier', 'status')
    )
    if not rows:
        return 'unclaimed'
    best_rank, best_tier = 0, 'pending'
    for tier, status in rows:
        r = _claim_rank(tier, status)
        if r > best_rank:
            best_rank, best_tier = r, (tier if _RANK.get(tier, 1) >= 2 else 'verified')
    if best_rank == 0:
        # every claim rejected -> treat as unclaimed for display purposes
        return 'unclaimed'
    if best_rank == 1:
        return 'pending'
    return best_tier


def lead_enabled(provider):
    """True if the provider has opted in to receive leads (verified or paid)."""
    if getattr(provider, 'verified', False):
        return True
    from .models import ClaimRequest
    return ClaimRequest.objects.filter(provider=provider).filter(
        Q(tier__in=LEAD_TIERS) | Q(status='verified')
    ).exists()


def lead_enabled_ids(provider_ids):
    """Bounded query -> set of provider ids that are lead-enabled."""
    if not provider_ids:
        return set()
    from .models import ClaimRequest
    return set(
        ClaimRequest.objects.filter(provider_id__in=provider_ids).filter(
            Q(tier__in=LEAD_TIERS) | Q(status='verified')
        ).values_list('provider_id', flat=True)
    )


def plan_for_price(price_id):
    """Reverse-lookup: a Stripe price id -> the plan dict that grants a tier.

    Used by the webhook as a fallback when metadata is missing.
    """
    for plan in settings.PROVIDER_PLANS.values():
        if settings.STRIPE_PRICES.get(plan['price_key']) == price_id:
            return plan
    return None


def clear_provider_cache(slug):
    """Best-effort invalidation of a provider_detail page's cache_page entry.

    LocMemCache is per-process across N gunicorn workers, so this only clears
    the current worker's copy; the rest expire on their own (24h) or on the
    next deploy restart. Never raise — cache-clearing is never worth a 500.
    """
    try:
        from django.urls import reverse
        from django.test import RequestFactory
        from django.utils.cache import get_cache_key
        request = RequestFactory().get(reverse('provider_detail', args=[slug]))
        key = get_cache_key(request)
        if key:
            cache.delete(key)
    except Exception:
        pass
