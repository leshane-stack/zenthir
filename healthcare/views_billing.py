import stripe
from django.conf import settings
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from healthcare.models import Procedure, PricingRecord, Provider
from django.db.models import Avg, Count, Min, Max
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
    global_qs = pricing_qs.filter(billing_component__in=['global', 'technical'])
    comparison_note = ''
    if global_qs.count() >= 10:
        pricing_qs = global_qs
        comparison_note = 'facility'
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
