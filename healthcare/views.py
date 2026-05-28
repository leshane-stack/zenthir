from django.shortcuts import render, get_object_or_404
from django.db import models
from django.http import HttpResponse
from .models import (
    Provider, Procedure, PricingRecord, Vertical, Location,
    SafetyEvent, DataSource
)


def home(request):
    verticals = Vertical.objects.filter(tier__lte=2).order_by('sort_order')
    recent_providers = Provider.objects.order_by('-created_at')[:10]
    procedures = Procedure.objects.filter(is_cash_pay_common=True)[:12]
    return render(request, 'healthcare/home.html', {
        'verticals': verticals,
        'recent_providers': recent_providers,
        'procedures': procedures,
    })


def provider_detail(request, slug):
    from django.db.models import Avg
    from statistics import median as calc_median
    provider = get_object_or_404(Provider, slug=slug)
    pricing = list(provider.pricing_records.select_related('procedure').order_by('procedure__name'))
    safety_events = provider.safety_events.all()[:10]
    sources = provider.data_sources.all()
    insurance = provider.insurance_acceptance.all()

    # Calculate regional medians
    if provider.location:
        for record in pricing:
            if record.cash_price:
                regional_prices = list(
                    PricingRecord.objects.filter(
                        procedure=record.procedure,
                        provider__location=provider.location,
                        cash_price__isnull=False,
                    ).exclude(cash_price=0).values_list('cash_price', flat=True)
                )
                if len(regional_prices) >= 3:
                    med = calc_median(regional_prices)
                    if med > 0:
                        ratio = float(record.cash_price) / float(med)
                        record.vs_regional_median = round(ratio, 2)
                        pct = abs(round((ratio - 1) * 100))
                        if ratio > 1.15:
                            record.median_label = f"{pct}% above median"
                            record.median_class = "badge-amber"
                        elif ratio < 0.85:
                            record.median_label = f"{pct}% below median"
                            record.median_class = "badge-blue"
                        else:
                            record.median_label = "Near median"
                            record.median_class = "badge-blue"
                    else:
                        record.vs_regional_median = None
                        record.median_label = None
                else:
                    record.vs_regional_median = None
                    record.median_label = None
            else:
                record.vs_regional_median = None

    # Analytics summary
    prices = [float(r.cash_price) for r in pricing if r.cash_price]
    price_summary = {}
    if prices:
        price_summary = {
            'count': len(pricing),
            'lowest': min(prices),
            'highest': max(prices),
        }

    # Find nearby competitors
    from django.db.models import Count
    nearby = []
    if provider.location and provider.provider_type:
        nearby = Provider.objects.filter(
            location=provider.location,
            provider_type=provider.provider_type,
        ).exclude(id=provider.id).annotate(
            pc=Count('pricing_records')
        ).filter(pc__gt=0).order_by('-pc')[:5]

    return render(request, 'healthcare/provider_detail.html', {
        'provider': provider,
        'pricing': pricing,
        'safety_events': safety_events,
        'sources': sources,
        'insurance': insurance,
        'price_summary': price_summary,
        'nearby': nearby,
    })


def procedure_detail(request, slug):
    procedure = get_object_or_404(Procedure, slug=slug)
    pricing = procedure.pricing_records.select_related('provider', 'provider__location').order_by('cash_price')
    locations = Location.objects.filter(
        provider__pricing_records__procedure=procedure
    ).distinct().order_by('state', 'city')
    return render(request, 'healthcare/procedure_detail.html', {
        'procedure': procedure,
        'pricing': pricing,
        'locations': locations,
    })


def city_detail(request, state, city_slug):
    location = get_object_or_404(Location, slug=city_slug, state=state.upper())
    providers = Provider.objects.filter(location=location).order_by('name')
    return render(request, 'healthcare/city_detail.html', {
        'location': location,
        'providers': providers,
    })


def procedure_city(request, procedure_slug, state, city_slug):
    procedure = get_object_or_404(Procedure, slug=procedure_slug)
    location = get_object_or_404(Location, slug=city_slug, state=state.upper())
    pricing = PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location
    ).select_related('provider', 'provider__provider_type').order_by('cash_price')

    # Calculate savings between cheapest and most expensive
    savings = 0
    if pricing.count() >= 2:
        prices = [r.cash_price for r in pricing if r.cash_price]
        if len(prices) >= 2:
            savings = prices[-1] - prices[0]

    # Find other cities that have this procedure, sorted by most providers
    from django.db.models import Count
    other_cities = Location.objects.filter(
        provider__pricing_records__procedure=procedure
    ).exclude(id=location.id).annotate(
        proc_count=Count('provider__pricing_records', filter=models.Q(provider__pricing_records__procedure=procedure))
    ).order_by('-proc_count').distinct()[:12]

    return render(request, 'healthcare/procedure_city.html', {
        'procedure': procedure,
        'location': location,
        'pricing': pricing,
        'savings': savings,
        'other_cities': other_cities,
    })


def vertical_detail(request, slug):
    vertical = get_object_or_404(Vertical, slug=slug)
    providers = Provider.objects.filter(verticals=vertical).order_by('name')
    procedures = Procedure.objects.filter(verticals=vertical).order_by('name')
    return render(request, 'healthcare/vertical_detail.html', {
        'vertical': vertical,
        'providers': providers,
        'procedures': procedures,
    })


def search(request):
    query = request.GET.get('q', '')
    providers = Provider.objects.none()
    procedures = Procedure.objects.none()
    if query:
        providers = Provider.objects.filter(name__icontains=query)[:20]
        procedures = Procedure.objects.filter(name__icontains=query)[:20]
    return render(request, 'healthcare/search.html', {
        'query': query,
        'providers': providers,
        'procedures': procedures,
    })


def robots_txt(request):
    lines = [
        "User-agent: *",
        "Allow: /",
        "Sitemap: https://zenthir.com/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


def procedures_index(request):
    procedures = Procedure.objects.order_by('category', 'name')
    provider_count = Provider.objects.count()
    city_count = Location.objects.count()
    return render(request, 'healthcare/procedures_index.html', {
        'procedures': procedures,
        'provider_count': provider_count,
        'city_count': city_count,
    })


def cities_index(request):
    from django.db.models import Count
    locations = Location.objects.annotate(
        provider_count=Count('provider')
    ).filter(provider_count__gte=3).order_by('state', 'city')
    total_providers = Provider.objects.count()
    return render(request, 'healthcare/cities_index.html', {
        'locations': locations,
        'total_providers': total_providers,
    })


def claim_profile(request, slug):
    from django.core.mail import send_mail
    provider = get_object_or_404(Provider, slug=slug)
    success = False
    if request.method == 'POST':
        name = request.POST.get('contact_name', '')
        email = request.POST.get('contact_email', '')
        practice = request.POST.get('practice_name', '')
        phone = request.POST.get('phone', '')
        role = request.POST.get('role', '')
        notes = request.POST.get('notes', '')
        try:
            send_mail(
                subject=f'[Zenthir] Profile Claim: {provider.name}',
                message=f'Provider: {provider.name}\nSlug: {slug}\nURL: https://zenthir.com/provider/{slug}/\n\nContact: {name}\nEmail: {email}\nPhone: {phone}\nRole: {role}\nPractice: {practice}\n\nNotes: {notes}',
                from_email='noreply@zenthir.com',
                recipient_list=['leshane@ethicalvista.com'],
                fail_silently=True,
            )
        except Exception:
            pass
        success = True
    return render(request, 'healthcare/claim_profile.html', {
        'provider': provider,
        'success': success,
    })


def methodology(request):
    return render(request, 'healthcare/methodology.html')


def overcharged(request):
    from statistics import median as calc_median
    from healthcare.models import Procedure, PricingRecord, Location
    
    valid_states = ['AL','AK','AZ','AR','CA','CO','CT','DE','DC','FL','GA','HI','ID','IL','IN','IA','KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY']
    states = valid_states
    provider_count = Provider.objects.count()
    
    result = None
    procedure_name = ''
    procedure_slug = request.GET.get('procedure', '')
    selected_state = request.GET.get('state', '')
    amount = request.GET.get('amount', '')
    
    if procedure_slug and amount:
        try:
            procedure = Procedure.objects.get(slug=procedure_slug)
            procedure_name = procedure.name
            amount_val = float(amount)
            
            pricing_qs = PricingRecord.objects.filter(
                procedure=procedure,
                cash_price__isnull=False,
            ).exclude(cash_price=0)
            
            if selected_state:
                pricing_qs = pricing_qs.filter(provider__location__state=selected_state)
            
            prices = list(pricing_qs.values_list('cash_price', flat=True))
            
            if len(prices) >= 3:
                prices_float = sorted([float(p) for p in prices])
                med = calc_median(prices_float)
                low = prices_float[int(len(prices_float) * 0.1)]
                high = prices_float[int(len(prices_float) * 0.9)]
                
                # Calculate percentile
                below = sum(1 for p in prices_float if p <= amount_val)
                percentile = min(int(below / len(prices_float) * 100), 98)
                
                # Determine verdict
                if amount_val > med * 1.5:
                    verdict = 'overpaid'
                    headline = f'You likely overpaid by ${int(amount_val - med):,}'
                    context = f'Your charge of ${int(amount_val):,} is significantly above the median of ${int(med):,}. You paid more than {percentile}% of patients for this procedure. Consider requesting an itemized bill and comparing with nearby providers.'
                elif amount_val > med * 1.15:
                    verdict = 'high'
                    headline = f'Your price is above average'
                    context = f'Your charge of ${int(amount_val):,} is above the median of ${int(med):,}, but within a reasonable range. You paid more than {percentile}% of patients. It may be worth requesting an itemized bill to check for errors.'
                elif amount_val < med * 0.7:
                    verdict = 'fair'
                    headline = f'You got a good price'
                    context = f'Your charge of ${int(amount_val):,} is well below the median of ${int(med):,}. You paid less than {100 - percentile}% of patients for this procedure.'
                else:
                    verdict = 'near'
                    headline = f'Your price is near the median'
                    context = f'Your charge of ${int(amount_val):,} is close to the median of ${int(med):,}. This appears to be a fair market price for this procedure.'
                
                unique_providers = pricing_qs.values('provider').distinct().count()
                
                result = {
                    'verdict': verdict,
                    'headline': headline,
                    'you_paid': f'{int(amount_val):,}',
                    'median': f'{int(med):,}',
                    'low': f'{int(low):,}',
                    'high': f'{int(high):,}',
                    'percentile': percentile,
                    'context': context,
                    'sample_size': f'{len(prices):,}',
                    'provider_count': f'{unique_providers:,}',
                    'state': selected_state,
                }
            else:
                result = {
                    'verdict': 'insufficient',
                    'headline': 'Not enough data',
                    'you_paid': f'{int(amount_val):,}',
                    'median': 'N/A',
                    'low': 'N/A',
                    'high': 'N/A',
                    'percentile': 50,
                    'context': f'We only have {len(prices)} pricing records for this procedure' + (f' in {selected_state}' if selected_state else '') + '. Try removing the state filter for more data.',
                    'sample_size': str(len(prices)),
                    'provider_count': '0',
                    'state': selected_state,
                }
        except Procedure.DoesNotExist:
            pass
        except (ValueError, TypeError):
            pass
    
    return render(request, 'healthcare/overcharged.html', {
        'states': states,
        'result': result,
        'procedure_name': procedure_name,
        'procedure_slug': procedure_slug,
        'selected_state': selected_state,
        'amount': amount,
        'provider_count': f'{provider_count:,}',
    })


def procedure_api(request):
    from django.http import JsonResponse
    from django.db.models import Count
    q = request.GET.get('q', '')
    if len(q) < 2:
        return JsonResponse([], safe=False)
    
    procedures = Procedure.objects.filter(
        name__icontains=q
    ).annotate(
        record_count=Count('pricing_records')
    ).filter(
        record_count__gte=10
    ).order_by('-record_count')[:10]
    
    data = [{'name': p.name, 'slug': p.slug, 'count': p.record_count} for p in procedures]
    return JsonResponse(data, safe=False)


def guide_no_surprises(request):
    return render(request, 'healthcare/guide_no_surprises.html')
