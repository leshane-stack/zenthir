import stripe
from django.conf import settings
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.utils import timezone
from healthcare.models import Procedure, PricingRecord, Provider, ClaimRequest
from healthcare.tiers import provider_tier, clear_provider_cache, plan_for_price, PAID_TIERS
from django.db.models import Avg, Count, Min, Max, Q
from statistics import median as calc_median
import json

stripe.api_key = settings.STRIPE_SECRET_KEY


def create_checkout(request):
    """Create Stripe checkout session for bill audit report"""
    procedure_slug = request.GET.get('procedure', '')
    state = request.GET.get('state', '')
    amount = request.GET.get('amount', '')

    if not procedure_slug or not amount:
        return redirect('overcharged')

    try:
        procedure = Procedure.objects.get(slug=procedure_slug)
    except Procedure.DoesNotExist:
        return redirect('overcharged')

    display_name = procedure.display_name or procedure.name

    session = stripe.checkout.Session.create(
        payment_method_types=['card'],
        line_items=[{
            'price_data': {
                'currency': 'usd',
                'product_data': {
                    'name': f'Bill Audit Report: {display_name}',
                    'description': f'Detailed pricing analysis for {display_name} in {state or "your area"}. Includes provider rankings, negotiated rates, and negotiation guidance.',
                },
                'unit_amount': 1900,  # $19.00
            },
            'quantity': 1,
        }],
        mode='payment',
        success_url=request.build_absolute_uri('/report/success/') + '?session_id={CHECKOUT_SESSION_ID}&procedure=' + procedure_slug + '&state=' + state + '&amount=' + amount,
        cancel_url=request.build_absolute_uri('/overcharged/') + '?procedure=' + procedure_slug + '&state=' + state + '&amount=' + amount,
        metadata={
            'procedure_slug': procedure_slug,
            'state': state,
            'amount': amount,
        }
    )

    return redirect(session.url)


def report_success(request):
    """Show the detailed bill audit report after successful payment"""
    session_id = request.GET.get('session_id', '')
    procedure_slug = request.GET.get('procedure', '')
    state = request.GET.get('state', '')
    amount = request.GET.get('amount', '')

    if not session_id or not procedure_slug or not amount:
        return redirect('overcharged')

    # Verify payment (skip in debug mode)
    from django.conf import settings as django_settings
    if django_settings.DEBUG:
        pass  # Skip verification in dev
    else:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            if session.payment_status != 'paid':
                return redirect('overcharged')
        except Exception:
            return redirect('overcharged')

    # Build the detailed report
    try:
        procedure = Procedure.objects.get(slug=procedure_slug)
        amount_val = float(amount)
    except (Procedure.DoesNotExist, ValueError):
        return redirect('overcharged')

    display_name = procedure.display_name or procedure.name

    pricing_qs = PricingRecord.objects.filter(
        procedure=procedure,
        cash_price__isnull=False,
    ).exclude(cash_price=0)

    if state:
        pricing_qs = pricing_qs.filter(provider__location__state=state)

    # Filter by billing component for apples-to-apples comparison
    from healthcare.procedure_groups import get_related_procedure_ids
    
    global_qs = pricing_qs.filter(billing_component__in=['global', 'technical'])
    comparison_note = ''
    
    # Exclude gross charges, min/max rates — not what patients pay
    facility_clean = global_qs.exclude(
        source_name__icontains='Gross'
    ).exclude(
        source_name__icontains='Max Rate'
    ).exclude(
        source_name__icontains='Min Rate'
    )
    
    if facility_clean.count() >= 10:
        pricing_qs = facility_clean
        comparison_note = 'facility'
    else:
        # Try expanding to related procedures
        related_ids = get_related_procedure_ids(procedure)
        if len(related_ids) > 1:
            expanded_qs = PricingRecord.objects.filter(
                procedure_id__in=related_ids,
                cash_price__isnull=False,
                billing_component__in=['global', 'technical'],
            ).exclude(cash_price=0).exclude(
                source_name__icontains='Gross'
            ).exclude(
                source_name__icontains='Max Rate'
            ).exclude(
                source_name__icontains='Min Rate'
            )
            if state:
                expanded_qs = expanded_qs.filter(provider__location__state=state)
            if expanded_qs.count() >= 10:
                pricing_qs = expanded_qs
                comparison_note = 'facility_grouped'
            else:
                comparison_note = 'professional'
        else:
            comparison_note = 'professional'

    prices = sorted([float(p) for p in pricing_qs.values_list('cash_price', flat=True)])

    if len(prices) < 3:
        return render(request, 'healthcare/report.html', {
            'display_name': display_name,
            'no_data': True,
        })

    med = calc_median(prices)
    p5 = prices[len(prices) // 20]
    p25 = prices[len(prices) // 4]
    p75 = prices[3 * len(prices) // 4]
    p95 = prices[19 * len(prices) // 20]

    below = sum(1 for p in prices if p <= amount_val)
    percentile = min(int(below / len(prices) * 100), 99)

    # Verdict
    if amount_val > med * 2:
        verdict = 'overpaid'
        verdict_label = 'Higher than most reported charges'
    elif amount_val > med * 1.15:
        verdict = 'high'
        verdict_label = 'Above typical reported charges'
    elif amount_val < med * 0.75:
        verdict = 'fair'
        verdict_label = 'Below typical reported charges'
    else:
        verdict = 'near'
        verdict_label = 'Within typical range'

    # Top 20 lowest-priced providers - deduplicated by phone number
    all_providers = list(pricing_qs.values(
        'provider__name',
        'provider__slug',
        'provider__provider_type__name',
        'provider__address',
        'provider__phone',
    ).annotate(
        lowest=Min('cash_price'),
    ).order_by('lowest'))

    # Deduplicate by phone number
    seen_phones = set()
    lowest_providers = []
    for p in all_providers:
        phone = p.get('provider__phone', '')
        if phone and phone in seen_phones:
            continue
        if phone:
            seen_phones.add(phone)
        lowest_providers.append(p)
        if len(lowest_providers) >= 20:
            break

    # Provider type breakdown
    type_breakdown = list(pricing_qs.values(
        'provider__provider_type__name'
    ).annotate(
        avg=Avg('cash_price'),
        low=Min('cash_price'),
        high=Max('cash_price'),
        providers=Count('provider_id', distinct=True),
    ).filter(providers__gte=3).order_by('avg'))

    # Negotiation talking points
    talking_points = []
    if amount_val > med:
        diff = round(amount_val - med)
        talking_points.append(f"Your charge of ${int(amount_val):,} is ${diff:,} above the local median of ${int(med):,}.")
        talking_points.append(f"You paid more than {percentile}% of reported charges for this procedure.")
    if type_breakdown and len(type_breakdown) >= 2:
        cheapest = type_breakdown[0]
        talking_points.append(f"{cheapest['provider__provider_type__name']} providers average ${int(cheapest['avg']):,}, which may be an alternative.")
    if lowest_providers:
        cheapest_provider = lowest_providers[0]
        talking_points.append(f"The lowest reported price in your area is ${int(cheapest_provider['lowest']):,} at {cheapest_provider['provider__name']}.")
    talking_points.append("Request an itemized bill to verify each line item.")
    talking_points.append("Ask the provider if a cash-pay discount is available.")
    talking_points.append("Under federal law, you can request a Good Faith Estimate before any scheduled service.")

    context = {
        'display_name': display_name,
        'no_data': False,
        'amount': int(amount_val),
        'state': state,
        'verdict': verdict,
        'verdict_label': verdict_label,
        'median': int(med),
        'p5': int(p5),
        'p25': int(p25),
        'p75': int(p75),
        'p95': int(p95),
        'percentile': percentile,
        'sample_size': len(prices),
        'provider_count': pricing_qs.values('provider_id').distinct().count(),
        'lowest_providers': lowest_providers,
        'type_breakdown': type_breakdown,
        'talking_points': talking_points,
        'comparison_note': comparison_note,
    }

    return render(request, 'healthcare/report.html', context)


# ===========================================================================
# Provider subscription: Claim -> Verified (free) -> Paid (Featured/Premium)
# ===========================================================================

def _verified_claim(provider):
    """The claim row we bill against: a verified/paid claim for this provider."""
    return (
        ClaimRequest.objects.filter(provider=provider)
        .filter(Q(tier__in=('verified',) + PAID_TIERS) | Q(status='verified'))
        .order_by('-tier_updated_at', '-created_at')
        .first()
    )


def provider_upgrade(request, slug):
    """Start a Stripe subscription checkout for a verified provider.

    Guard: only a verified provider can upgrade (leads are already free at
    'verified' — this buys enhanced/featured treatment). Unclaimed/pending
    providers are sent to the claim flow first; already-paid providers are
    sent back to their profile.
    """
    provider = get_object_or_404(Provider, slug=slug)
    tier = provider_tier(provider)

    if tier in PAID_TIERS:
        return redirect('provider_detail', slug=slug)
    if tier != 'verified':
        # Not yet verified — claim/verify before paying.
        return redirect('claim_profile', slug=slug)

    plan_key = request.GET.get('plan', 'featured')
    plan = settings.PROVIDER_PLANS.get(plan_key)
    if not plan:
        return redirect('provider_detail', slug=slug)
    price_id = settings.STRIPE_PRICES.get(plan['price_key'])
    if not price_id:
        return redirect('provider_detail', slug=slug)

    claim = _verified_claim(provider)
    contact_email = claim.contact_email if claim else ''

    session_kwargs = dict(
        mode='subscription',
        line_items=[{'price': price_id, 'quantity': 1}],
        success_url=request.build_absolute_uri(f'/provider/{slug}/upgrade/success/')
        + '?session_id={CHECKOUT_SESSION_ID}',
        cancel_url=request.build_absolute_uri(f'/provider/{slug}/'),
        metadata={
            'provider_slug': slug,
            'claim_id': str(claim.id) if claim else '',
            'tier': plan['tier'],
            'plan': plan_key,
        },
    )
    # Reuse the existing Stripe customer if we have one, else seed by email.
    if claim and claim.stripe_customer_id:
        session_kwargs['customer'] = claim.stripe_customer_id
    elif contact_email:
        session_kwargs['customer_email'] = contact_email
    # Propagate metadata to the subscription so subscription.* events carry it.
    session_kwargs['subscription_data'] = {'metadata': session_kwargs['metadata']}

    try:
        session = stripe.checkout.Session.create(**session_kwargs)
    except Exception:
        # Misconfigured/unavailable Stripe -> don't 500 the provider.
        return redirect('provider_detail', slug=slug)

    return redirect(session.url)


def provider_upgrade_success(request, slug):
    """Thank-you page after a successful subscription checkout.

    The webhook is the source of truth for tier changes; this page just
    confirms and links back. We read the session only to show status.
    """
    provider = get_object_or_404(Provider, slug=slug)
    session_id = request.GET.get('session_id', '')
    paid = False
    if session_id and not settings.DEBUG:
        try:
            session = stripe.checkout.Session.retrieve(session_id)
            paid = session.payment_status == 'paid'
        except Exception:
            paid = False
    elif settings.DEBUG:
        paid = True
    return render(request, 'healthcare/provider_upgrade_success.html', {
        'provider': provider,
        'paid': paid,
    })


def _apply_paid_tier(claim, tier, customer_id=None, subscription_id=None):
    fields = ['tier', 'tier_updated_at']
    claim.tier = tier
    claim.tier_updated_at = timezone.now()
    if claim.status != 'verified':
        claim.status = 'verified'
        fields.append('status')
    if customer_id:
        claim.stripe_customer_id = customer_id
        fields.append('stripe_customer_id')
    if subscription_id:
        claim.stripe_subscription_id = subscription_id
        fields.append('stripe_subscription_id')
    claim.save(update_fields=fields)
    clear_provider_cache(claim.provider.slug)


@csrf_exempt
@require_POST
def stripe_webhook(request):
    """Handle provider-subscription lifecycle events from Stripe.

    checkout.session.completed  -> grant the paid tier + store customer/sub ids
    customer.subscription.deleted -> revert to the free 'verified' tier
    """
    payload = request.body
    sig_header = request.META.get('HTTP_STRIPE_SIGNATURE', '')
    secret = settings.STRIPE_WEBHOOK_SECRET
    if not secret:
        return HttpResponse(status=503)
    try:
        event = stripe.Webhook.construct_event(payload, sig_header, secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        return HttpResponse(status=400)
    except Exception:
        return HttpResponse(status=400)

    etype = event.get('type')
    obj = event.get('data', {}).get('object', {})

    if etype == 'checkout.session.completed':
        meta = obj.get('metadata') or {}
        claim_id = meta.get('claim_id')
        provider_slug = meta.get('provider_slug')
        tier = meta.get('tier') or 'paid_basic'
        customer_id = obj.get('customer')
        subscription_id = obj.get('subscription')
        claim = None
        if claim_id:
            claim = ClaimRequest.objects.filter(id=claim_id).first()
        if claim is None and provider_slug:
            claim = ClaimRequest.objects.filter(
                provider__slug=provider_slug
            ).filter(Q(tier='verified') | Q(status='verified')).order_by(
                '-tier_updated_at', '-created_at').first()
        if claim is not None and tier in PAID_TIERS:
            _apply_paid_tier(claim, tier, customer_id, subscription_id)

    elif etype == 'customer.subscription.deleted':
        subscription_id = obj.get('id')
        claim = ClaimRequest.objects.filter(
            stripe_subscription_id=subscription_id
        ).first() if subscription_id else None
        if claim is not None and claim.tier in PAID_TIERS:
            # Subscription ended -> keep them verified (leads stay free), drop
            # the paid perks. Retain customer id for a future re-subscribe.
            claim.tier = 'verified'
            claim.tier_updated_at = timezone.now()
            claim.stripe_subscription_id = None
            claim.save(update_fields=['tier', 'tier_updated_at', 'stripe_subscription_id'])
            clear_provider_cache(claim.provider.slug)

    return HttpResponse(status=200)
