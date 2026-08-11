from django.shortcuts import render, get_object_or_404
from django.views.decorators.cache import cache_page
from django.db import models
from django.http import HttpResponse
from .models import (
    Provider, Procedure, PricingRecord, Vertical, Location, ProviderType,
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


@cache_page(86400)
def provider_detail(request, slug):
    from django.db.models import Avg, Count
    from statistics import median as calc_median
    from collections import defaultdict
    from django.core.cache import cache

    provider = get_object_or_404(Provider, slug=slug)

    # Filter to procedures this provider type actually performs
    # Use a hardcoded exclusion list for obvious mismatches
    from django.db.models import Count
    PROCEDURE_TYPE_EXCLUSIONS = {
        'Dietitian / Nutrition': ['coronary', 'bypass', 'cardiac', 'mri', 'ct scan', 'mammogram', 'arthroscopy', 'surgery', 'surgical'],
        'Mental Health': ['coronary', 'bypass', 'cardiac', 'mri', 'ct scan', 'mammogram', 'arthroscopy', 'surgery', 'surgical', 'colonoscopy'],
        'Chiropractor': ['coronary', 'bypass', 'cardiac', 'mammogram', 'colonoscopy', 'surgery', 'surgical'],
        'Physical Therapy': ['coronary', 'bypass', 'cardiac', 'mammogram', 'colonoscopy', 'ct scan', 'mri'],
        'Eye Care': ['coronary', 'bypass', 'cardiac', 'mammogram', 'colonoscopy', 'arthroscopy'],
        'Weight Loss Clinic': ['coronary', 'bypass', 'cardiac', 'mammogram', 'colonoscopy', 'arthroscopy', 'surgery'],
        'Allergy & Immunology': ['coronary', 'bypass', 'cardiac', 'mammogram', 'colonoscopy', 'arthroscopy', 'surgery'],
    }
    exclusion_terms = PROCEDURE_TYPE_EXCLUSIONS.get(provider.provider_type.name, []) if provider.provider_type else []

    # Deduplicated pricing: one row per procedure, filtered by exclusion terms
    all_pricing = provider.pricing_records.select_related('procedure').order_by('procedure__name', '-updated_at')[:500]
    seen_procs = set()
    pricing = []
    for r in all_pricing:
        if r.procedure_id not in seen_procs:
            seen_procs.add(r.procedure_id)
            proc_name = (r.procedure.display_name or r.procedure.name or '').lower()
            if not any(term in proc_name for term in exclusion_terms):
                pricing.append(r)
    pricing = pricing[:30]

    # Only show insured column if values actually differ from cash price
    has_different_insured = any(
        r.insured_price and r.cash_price and abs(float(r.insured_price) - float(r.cash_price)) > 1
        for r in pricing
    )

    has_medians = False
    # Only show medians for facility types where comparison is meaningful
    FACILITY_TYPES = ['Hospital', 'General Surgery', 'Imaging Center', 'Surgery Center',
                      'Community Health Center', 'Clinic', 'Urgent Care', 'Emergency Room',
                      'Ambulatory Surgical Center', 'Diagnostic Radiology']
    show_medians = provider.provider_type and provider.provider_type.name in FACILITY_TYPES
    # Regional medians from pre-computed table (fast lookup)
    if show_medians and provider.location and pricing:
        from healthcare.models import ProcedureMedian
        priced_records = [r for r in pricing if r.cash_price]
        procedure_ids = [r.procedure_id for r in priced_records]
        # Try local medians first, fall back to same-state
        medians = {
            m.procedure_id: m for m in ProcedureMedian.objects.filter(
                procedure_id__in=procedure_ids,
                location=provider.location,
                provider_type=provider.provider_type,
            )
        }

        for record in priced_records:
            m = medians.get(record.procedure_id)
            if m and m.median_price > 0:
                ratio = float(record.cash_price) / float(m.median_price)
                record.vs_regional_median = round(ratio, 2)
                pct = abs(round((ratio - 1) * 100))
                if ratio > 3.0:
                    record.median_label = "Billing may include facility fees"
                    record.median_class = "badge-muted"
                elif ratio > 1.15:
                    record.median_label = str(pct) + "% above median"
                    record.median_class = "badge-amber"
                elif ratio < 0.85:
                    record.median_label = str(pct) + "% below median"
                    record.median_class = "badge-blue"
                else:
                    record.median_label = "Near median"
                    record.median_class = "badge-blue"
            else:
                record.vs_regional_median = None
                record.median_label = None
    for record in pricing:
        if not record.cash_price:
            record.vs_regional_median = None
    has_medians = any(getattr(r, 'median_label', None) for r in pricing)

    # Price summary
    prices = [float(r.cash_price) for r in pricing if r.cash_price]
    price_summary = {}
    if len(prices) >= 2:
        price_summary = {
            'count': len(pricing),
            'lowest': min(prices),
            'highest': max(prices),
        }
    elif len(prices) == 1:
        price_summary = {
            'count': 1,
            'lowest': prices[0],
            'highest': prices[0],
        }

    # Nearby providers (deduplicated procedure count, max 5).
    # Businesses only — is_individual=False keeps out single practitioners
    # (e.g. "ANA LAMAS, M.D.") so the consumer compares comparable listings.
    nearby = []
    if provider.location and provider.provider_type:
        nearby = list(Provider.objects.filter(
            location=provider.location,
            provider_type=provider.provider_type,
            is_individual=False,
        ).exclude(id=provider.id).annotate(
            pc=Count('pricing_records__procedure_id', distinct=True)
        ).filter(pc__gt=0).order_by('-pc')[:5])

    # Market context: how many same-type providers in this city
    market_context = None
    if provider.location and provider.provider_type and prices:
        try:
            same_type_count = Provider.objects.filter(
                location=provider.location,
                provider_type=provider.provider_type,
                pricing_records__isnull=False,
            ).distinct().count()

            if same_type_count >= 3:
                provider_avg = round(sum(prices) / len(prices))
                market_context = {
                    'city': provider.location.city,
                    'state': provider.location.state,
                    'type_name': provider.provider_type.name,
                    'provider_count': same_type_count,
                    'provider_avg': provider_avg,
                }
        except Exception:
            pass

    # --- Provider tier (Listed -> Verified -> Provider Enhanced) -------------
    # Cheap indexed lookup on claim_requests by provider FK; page is cached 24h.
    # Drives the badge + which consumer affordances render. NO provider-facing
    # messaging is emitted from this view — the public page is consumer-only.
    from healthcare.tiers import provider_tier
    tier = provider_tier(provider)

    # "Last confirmed" date for verified/featured providers, from the governing
    # (non-rejected) claim.
    confirmed_date = None
    if tier in ('verified', 'paid_basic', 'paid_premium'):
        from .models import ClaimRequest
        gc = (ClaimRequest.objects.filter(provider=provider)
              .exclude(status='rejected')
              .order_by('-tier_updated_at', '-created_at').first())
        if gc:
            confirmed_date = gc.tier_updated_at

    # --- Market Position (the Zestimate-equivalent) --------------------------
    from healthcare.market import market_position
    market = market_position(provider, pricing)

    # Most recent pricing date (for "Pricing from [date]" trust signal).
    pricing_date = None
    for r in pricing:
        d = r.last_verified or (r.updated_at.date() if r.updated_at else None)
        if d and (pricing_date is None or d > pricing_date):
            pricing_date = d

    # --- Related links, contextual to provider type --------------------------
    related_links = _related_links(provider, pricing)

    # Featured-only: procedures the consumer can pick in the inquiry dropdown.
    inquiry_procedures = [
        {'slug': r.procedure.slug,
         'name': (r.procedure.display_name or r.procedure.name)}
        for r in pricing
    ] if tier in ('paid_basic', 'paid_premium') else []

    # --- Provider enrichment (structured Price Context + profile) ------------
    # Admin-managed for now. Public page shows "What's Included" per procedure
    # detail and the profile's payment/financing/equipment. The completeness
    # meter is NOT rendered here — it's provider-facing (reserved for provider
    # emails); provider_completeness() lives in completeness.py for that use.
    from healthcare.models import ProviderProcedureDetail, ProviderProfile
    from healthcare.completeness import whats_included, payment_methods
    # "Enhanced" = the provider has published at least one True structured detail.
    PPD_BOOL_FIELDS = (
        'includes_consultation', 'includes_interpretation', 'includes_facility_fee',
        'includes_anesthesia', 'includes_followup', 'financing_available',
        'self_pay_discount', 'price_guaranteed', 'good_faith_estimate_available',
    )
    included_blocks = []
    has_enhanced_details = False
    for ppd in (ProviderProcedureDetail.objects
                .filter(provider=provider).select_related('procedure')):
        if any(getattr(ppd, f) is True for f in PPD_BOOL_FIELDS):
            has_enhanced_details = True
        items = whats_included(ppd)
        if items or (ppd.provider_notes or '').strip():
            included_blocks.append({
                'procedure': (ppd.procedure.display_name or ppd.procedure.name),
                'items': items,
                'notes': (ppd.provider_notes or '').strip(),
            })
    profile = ProviderProfile.objects.filter(provider=provider).first()
    profile_payments = payment_methods(profile)
    has_profile_content = bool(profile_payments or (profile and (
        profile.financing_available or profile.equipment_notes
        or profile.languages or profile.preparation_instructions)))
    # Empty-state "Transparency Profile" prompt: only for claimed (verified/paid)
    # providers who haven't published any enrichment yet. Never for unclaimed.
    show_transparency_empty = (
        tier in ('verified', 'paid_basic', 'paid_premium')
        and not included_blocks and not has_profile_content
    )

    # --- Zenthir Summary: data-generated, factual, provenance-clean ----------
    from healthcare.summary import zenthir_summary
    try:
        zenthir_summary_text = zenthir_summary(
            provider, pricing, tier, confirmed_date, has_enhanced_details)
    except Exception:
        zenthir_summary_text = ''  # never break the page on a summary edge case

    # "About the Practice" — provider's own words, paid tier + non-empty desc only.
    about_practice = ''
    if tier in ('paid_basic', 'paid_premium'):
        about_practice = ((profile.description if profile else '') or '').strip()

    # --- Structured data (JSON-LD) -------------------------------------------
    # @type by provider category (Hospital / Dentist / default MedicalBusiness);
    # schema_offers = one Offer per priced procedure. Only emit fields with data.
    _DENTIST_SCHEMA_TYPES = {'Dentist', 'Dental Office', 'Orthodontist',
                             'Oral Surgery', 'Dental Clinic', 'Periodontics'}
    schema_type = 'MedicalBusiness'
    if provider.provider_type:
        _pt = provider.provider_type.name
        if _pt == 'Hospital':
            schema_type = 'Hospital'
        elif _pt in _DENTIST_SCHEMA_TYPES:
            schema_type = 'Dentist'
    schema_offers = [r for r in pricing if r.cash_price and float(r.cash_price) > 0]

    return render(request, 'healthcare/provider_detail.html', {
        'provider': provider,
        'pricing': pricing,
        'price_summary': price_summary,
        'nearby': nearby,
        'market_context': market_context,
        'market': market,
        'is_individual': Provider.objects.filter(address=provider.address).count() > 3 if provider.address else False,
        'has_medians': has_medians,
        'has_different_insured': has_different_insured,
        'tier': tier,
        'confirmed_date': confirmed_date,
        'pricing_date': pricing_date,
        'related_links': related_links,
        'inquiry_procedures': inquiry_procedures,
        'included_blocks': included_blocks,
        'profile': profile,
        'profile_payments': profile_payments,
        'has_profile_content': has_profile_content,
        'has_enhanced_details': has_enhanced_details,
        'show_transparency_empty': show_transparency_empty,
        'zenthir_summary_text': zenthir_summary_text,
        'about_practice': about_practice,
        'schema_type': schema_type,
        'schema_offers': schema_offers,
        'city_slug_track': provider.location.slug if provider.location else '',
        'npi_registry_url': (
            f'https://npiregistry.cms.hhs.gov/provider-view/{provider.npi_number}'
            if provider.npi_number else ''
        ),
    })


# Provider types that anchor which "Related" links make sense for consumers.
_AESTHETIC_TYPES = {'Plastic Surgery Practice', 'Med Spa', 'Dermatology',
                    'Cosmetic Surgery', 'Aesthetic Clinic'}
_DENTAL_TYPES = {'Dental Office', 'Dentist', 'Orthodontist', 'Oral Surgery',
                 'Dental Clinic', 'Periodontics'}
_FACILITY_TYPES = {'Hospital', 'Surgery Center', 'Imaging Center', 'Emergency Room',
                   'Ambulatory Surgical Center', 'Urgent Care', 'Diagnostic Radiology',
                   'General Surgery', 'Community Health Center'}


def _related_links(provider, pricing):
    """Consumer-relevant related links, contextual to the provider's type.

    Aesthetic/dental -> the provider's own cash-pay procedure pages (real
    shopping intent). Facilities -> the facility-fee / good-faith-estimate
    guides. Everyone -> their city page + the price-check calculator (carrying
    the provider slug so a returning bill maps back here).
    """
    from django.urls import reverse
    links = []
    ptype = provider.provider_type.name if provider.provider_type else ''

    if provider.location and provider.provider_type:
        links.append({
            'url': reverse('city_detail', args=[provider.location.state, provider.location.slug]),
            'label': f"{ptype} providers in {provider.location.city}, {provider.location.state}",
        })

    if ptype in _AESTHETIC_TYPES or ptype in _DENTAL_TYPES:
        seen = set()
        for r in pricing:
            if not r.procedure.is_cash_pay_common or r.procedure.slug in seen:
                continue
            seen.add(r.procedure.slug)
            links.append({
                'url': reverse('procedure_detail', args=[r.procedure.slug]),
                'label': f"{(r.procedure.display_name or r.procedure.name)}: prices & providers",
            })
            if len(seen) >= 3:
                break

    if ptype in _FACILITY_TYPES:
        links.append({'url': '/guides/facility-fees/', 'label': 'What is a facility fee?'})
        links.append({'url': '/guides/good-faith-estimate/', 'label': 'What is a Good Faith Estimate?'})

    # Price-check carries the provider slug so a returning bill maps back here.
    links.append({'url': f'/overcharged/?provider={provider.slug}',
                  'label': f'Have a bill from {provider.name}? Check your price'})
    return links


@cache_page(86400)
def procedure_detail(request, slug):
    from django.db.models import Avg, Min, Max, Count
    from statistics import median as calc_median
    procedure = get_object_or_404(Procedure, slug=slug)
    display_name = procedure.display_name or procedure.name

    # Exclude provider types that are billing artifacts
    junk_types = ['Mental Health', 'Chiropractor', 'Dietitian / Nutrition',
                  'Eye Care', 'Eye Center', 'Weight Loss Clinic', 'Dermatology',
                  'Allergy & Immunology', 'Physical Therapy', 'Dental Office',
                  'Podiatry', 'Audiology', 'Psychiatry', 'Sleep Medicine',
                  'Speech Pathology', 'Occupational Therapy', 'Plastic Surgery Practice',
                  'Clinical Laboratory', 'Fertility Clinic']

    # Use pre-computed national stats (instant lookup)
    stats = {
        'avg_price': procedure.national_avg,
        'min_price': procedure.national_p5,
        'max_price': procedure.national_p95,
        'avg_medicare': procedure.national_avg_medicare,
        'total': procedure.national_record_count,
        'provider_count': procedure.national_provider_count,
    }
    row = (
        procedure.national_median,
        procedure.national_p25,
        procedure.national_p75,
        procedure.national_p5,
        procedure.national_p95,
    )
    median = float(row[0]) if row and row[0] else 0
    p25 = float(row[1]) if row and row[1] else 0
    p75 = float(row[2]) if row and row[2] else 0
    p5 = float(row[3]) if row and row[3] else 0
    p95 = float(row[4]) if row and row[4] else 0

    # Minimum data threshold: pages with <5 providers are thin content
    has_data = stats['provider_count'] is not None and stats['provider_count'] >= 5
    has_any_data = stats['total'] is not None and stats['total'] > 0

    # Price consistency: how spread out is pricing? (p75/p25 ratio)
    consistency = None
    if has_data and p25 > 0:
        spread_ratio = round(p75 / p25, 1)
        if spread_ratio <= 2:
            consistency = {
                'ratio': spread_ratio,
                'label': 'consistent',
                'text': f'{display_name} prices are relatively consistent across providers. Most charge between ${p25:,.0f} and ${p75:,.0f}, with fewer extreme outliers than many healthcare services.',
            }
        elif spread_ratio <= 5:
            consistency = {
                'ratio': spread_ratio,
                'label': 'moderate',
                'text': f'{display_name} prices vary moderately. Most providers charge between ${p25:,.0f} and ${p75:,.0f}, but the highest prices run about {spread_ratio}x the lowest within the typical range.',
            }
        else:
            consistency = {
                'ratio': spread_ratio,
                'label': 'wide',
                'text': f'{display_name} pricing varies widely. Typical prices span roughly {spread_ratio}x from ${p25:,.0f} to ${p75:,.0f}. Comparing providers before scheduling can make a significant difference.',
            }

    # Potential savings: median minus low end of typical range
    savings = None
    if has_data and median > p25 and p25 > 0:
        savings = round(median - p25)

    # Representative providers: deduplicated, filtered out junk prices
    # Floor: prices below 1% of median are data errors
    price_floor = max(p5 * 0.5, 50) if p5 > 0 else 50
    all_records = list(PricingRecord.objects.filter(
        procedure=procedure,
        cash_price__isnull=False,
        cash_price__gte=price_floor,
        provider__is_individual=False,
    ).exclude(cash_price=0).exclude(
        provider__provider_type__name__in=junk_types
    ).select_related(
        'provider', 'provider__location', 'provider__provider_type'
    ).order_by('cash_price')[:200])

    # Deduplicate: one row per provider, skip individual practitioners
    individual_suffixes = [', M.D.', ', MD', ', D.O.', ', DO', ', PA', ', M.D., P.A.', ', APRN', ', NP', ', RN', ', DPM', ', OD', ', DDS', ', DMD', ', DC', ', LCSW', ', PHD', ', PH.D.', ', MSC', ', RD', ', LDN', ', RDN', ', CRNA', ', CNP']
    seen_providers = set()
    seen_names = set()
    pricing = []
    for record in all_records:
        name = record.provider.name or ''
        is_person = any(name.upper().endswith(s.upper()) for s in individual_suffixes) or name.isupper() and ',' in name
        name_key = name.upper().strip()
        if record.provider_id not in seen_providers and name_key not in seen_names and not is_person:
            seen_providers.add(record.provider_id)
            seen_names.add(name_key)
            # Fix ALL CAPS names
            if name.isupper():
                record.provider.name = name.title()
            if median > 0:
                diff_pct = round((float(record.cash_price) - median) / median * 100)
                record.vs_median_pct = abs(diff_pct)
                record.vs_median_dir = 'above' if diff_pct > 0 else ('below' if diff_pct < 0 else 'at')
            pricing.append(record)
        if len(pricing) >= 15:
            break

    # By facility type
    # Pre-computed facility type stats
    import json as _json
    by_type = []
    if procedure.by_type_json:
        raw = _json.loads(procedure.by_type_json)
        by_type = [{'provider__provider_type__name': t['name'], 'avg_price': t['avg_price'], 'count': t['count']} for t in raw]

    cheapest_type = by_type[0] if len(by_type) >= 2 else None

    # Generated insight paragraph (AEO block — the quotable summary)
    insight_summary = ''
    if has_data:
        insight_summary = (
            f"{display_name} prices range from ${p5:,.0f} to ${p95:,.0f} "
            f"across {stats['provider_count']:,} providers nationwide. "
            f"Most providers charge between ${p25:,.0f} and ${p75:,.0f}, with a national median of ${median:,.0f}."
        )
        if cheapest_type:
            insight_summary += (
                f" {cheapest_type['provider__provider_type__name']} providers report the lowest average prices "
                f"(${cheapest_type['avg_price']:,.0f})."
            )

    # Pre-computed top cities (spread across states)
    locations = []
    if procedure.top_cities_json:
        locations = _json.loads(procedure.top_cities_json)

    return render(request, 'healthcare/procedure_detail.html', {
        'procedure': procedure,
        'display_name': display_name,
        'pricing': pricing,
        'locations': locations,
        'stats': stats,
        'median': median,
        'p25': p25,
        'p75': p75,
        'p5': p5,
        'p95': p95,
        'by_type': by_type,
        'cheapest_type': cheapest_type,
        'consistency': consistency,
        'savings': savings,
        'insight_summary': insight_summary,
        'has_data': has_data,
        'has_any_data': has_any_data,
    })


@cache_page(86400)
def city_detail(request, state, city_slug):
    from django.db.models import Count
    location = get_object_or_404(Location, slug=city_slug, state=state.upper())

    # Optional type filter
    selected_type = request.GET.get('type', '')

    # Only business providers with pricing data
    provider_qs = Provider.objects.filter(
        location=location,
        is_individual=False,
        pricing_records__isnull=False,
    )
    if selected_type:
        provider_qs = provider_qs.filter(provider_type__name=selected_type)

    providers = provider_qs.annotate(
        proc_count=Count('pricing_records__procedure_id', distinct=True)
    ).filter(proc_count__gt=0).order_by('-proc_count')[:50]

    # Provider type summary
    type_counts = Provider.objects.filter(
        location=location,
        is_individual=False,
        pricing_records__isnull=False,
    ).values('provider_type__name').annotate(
        count=Count('id', distinct=True)
    ).filter(count__gte=1).order_by('-count')[:10]

    total_providers = Provider.objects.filter(
        location=location,
        is_individual=False,
        pricing_records__isnull=False,
    ).distinct().count()

    return render(request, 'healthcare/city_detail.html', {
        'location': location,
        'providers': providers,
        'type_counts': type_counts,
        'total_providers': total_providers,
        # Empty city pages carry no value for search; keep them out of the index.
        'noindex': total_providers == 0,
        'selected_type': selected_type,
    })


@cache_page(86400)
def procedure_city(request, procedure_slug, state, city_slug):
    from django.db.models import Count, Avg, Min, Max
    from statistics import median as calc_median

    procedure = get_object_or_404(Procedure, slug=procedure_slug)
    location = get_object_or_404(Location, slug=city_slug, state=state.upper())
    display_name = procedure.display_name or procedure.name

    # Get valid provider types for this procedure+city (3+ providers)
    valid_types = list(PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location,
        cash_price__isnull=False,
    ).exclude(cash_price=0).values(
        'provider__provider_type__name'
    ).annotate(
        count=Count('provider_id', distinct=True)
    ).filter(count__gte=3).order_by('-count').values_list(
        'provider__provider_type__name', flat=True
    ))

    # All records filtered to valid types
    base_qs = PricingRecord.objects.filter(
        procedure=procedure,
        provider__location=location,
        cash_price__isnull=False,
    ).exclude(cash_price=0)

    if valid_types:
        base_qs = base_qs.filter(provider__provider_type__name__in=valid_types)

    # Stats from filtered data
    all_prices = list(base_qs.order_by('cash_price').values_list('cash_price', flat=True))

    if all_prices:
        median = float(all_prices[len(all_prices) // 2])
        p25 = float(all_prices[len(all_prices) // 4])
        p75 = float(all_prices[3 * len(all_prices) // 4])
        price_min = float(all_prices[0])
        price_max = float(all_prices[-1])
    else:
        median = p25 = p75 = price_min = price_max = 0

    # Price floor: 50% of p25 or $50 minimum
    price_floor = max(p25 * 0.5, 50) if p25 > 0 else 50

    # Deduplicated provider list: one row per provider, cheapest record, filtered
    all_records = list(base_qs.filter(
        cash_price__gte=price_floor,
    ).select_related(
        'provider', 'provider__provider_type', 'provider__location'
    ).order_by('cash_price')[:300])

    seen = set()
    pricing = []
    for r in all_records:
        if r.provider_id not in seen:
            seen.add(r.provider_id)
            if median > 0:
                diff_pct = round((float(r.cash_price) - median) / median * 100)
                r.vs_median_pct = abs(diff_pct)
                r.vs_median_dir = 'above' if diff_pct > 0 else ('below' if diff_pct < 0 else 'at')
            pricing.append(r)
        if len(pricing) >= 25:
            break

    provider_count = len(seen) if len(pricing) < 25 else base_qs.values('provider_id').distinct().count()

    # Facility type breakdown
    by_type = list(base_qs.values(
        'provider__provider_type__name',
    ).annotate(
        avg_price=Avg('cash_price'),
        count=Count('provider_id', distinct=True),
    ).filter(count__gte=3).order_by('-count')[:5])

    # Savings: median vs p25
    savings = round(median - p25) if median > p25 > 0 else 0

    # Medicare average
    medicare_avg = base_qs.filter(
        insured_price__isnull=False,
    ).exclude(insured_price=0).aggregate(avg=Avg('insured_price'))['avg']

    # Other cities (lightweight query)
    other_cities = Location.objects.filter(
        provider__pricing_records__procedure=procedure,
        provider__pricing_records__cash_price__isnull=False,
    ).exclude(id=location.id).annotate(
        proc_count=Count('provider', distinct=True, filter=models.Q(
            provider__pricing_records__procedure=procedure,
            provider__pricing_records__cash_price__isnull=False,
        ))
    ).filter(proc_count__gte=5).order_by('-proc_count').distinct()[:12]

    # Attach median/count to other cities for display
    for city in other_cities:
        city_prices = list(PricingRecord.objects.filter(
            procedure=procedure,
            provider__location=city,
            cash_price__isnull=False,
        ).exclude(cash_price=0).order_by('cash_price').values_list('cash_price', flat=True)[:100])
        city.median_price = float(city_prices[len(city_prices) // 2]) if city_prices else 0

    return render(request, 'healthcare/procedure_city.html', {
        'procedure': procedure,
        'location': location,
        'display_name': display_name,
        'pricing': pricing,
        'provider_count': provider_count,
        'median': median,
        'p25': p25,
        'p75': p75,
        'price_min': price_min,
        'price_max': price_max,
        'savings': savings,
        'by_type': by_type,
        'medicare_avg': medicare_avg,
        'other_cities': other_cities,
        'has_data': len(pricing) > 0,
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
        "Disallow: /*/claim/",
        "Sitemap: https://zenthir.com/sitemap.xml",
    ]
    return HttpResponse("\n".join(lines), content_type="text/plain")


@cache_page(86400)
def procedures_index(request):
    selected_category = request.GET.get('category', '')
    procedures = Procedure.objects.filter(
        national_provider_count__isnull=False,
        national_provider_count__gte=50,
    ).order_by('category', 'display_name')
    categories = sorted(set(p.category for p in procedures if p.category))
    if selected_category:
        procedures = procedures.filter(category=selected_category)
    else:
        procedures = procedures.filter(national_provider_count__gte=5000)
    cash_procedures = Procedure.objects.filter(is_cash_pay_common=True).order_by('display_name')
    return render(request, 'healthcare/procedures_index.html', {
        'procedures': procedures,
        'categories': categories,
        'selected_category': selected_category,
        'cash_procedures': cash_procedures,
    })


@cache_page(86400)
def cities_index(request):
    from django.db.models import Count
    from healthcare.location_quality import exclude_malformed_locations
    valid_states = 'AL,AK,AZ,AR,CA,CO,CT,DE,FL,GA,HI,ID,IL,IN,IA,KS,KY,LA,ME,MD,MA,MI,MN,MS,MO,MT,NE,NV,NH,NJ,NM,NY,NC,ND,OH,OK,OR,PA,RI,SC,SD,TN,TX,UT,VT,VA,WA,WV,WI,WY,DC,PR'.split(',')
    selected_state = request.GET.get('state', '')
    locations = Location.objects.filter(
        state__in=valid_states,
    ).annotate(
        provider_count=Count('provider', filter=models.Q(provider__is_individual=False))
    ).filter(provider_count__gte=10).order_by('state', 'city')
    locations = exclude_malformed_locations(locations)
    if selected_state:
        locations = locations.filter(state=selected_state.upper())
    states = sorted(set(l.state for l in locations))
    locations = locations[:200]
    return render(request, 'healthcare/cities_index.html', {
        'locations': locations,
        'states': states,
        'selected_state': selected_state,
    })


def claim_profile(request, slug):
    from django.core.mail import send_mail
    from .models import ClaimRequest, WedgeEvent
    provider = get_object_or_404(Provider, slug=slug)
    success = False
    if request.method == 'POST':
        name = request.POST.get('contact_name', '')
        email = request.POST.get('contact_email', '')
        practice = request.POST.get('practice_name', '')
        phone = request.POST.get('phone', '')
        role = request.POST.get('role', '')
        notes = request.POST.get('notes', '')
        # Persist the claim (the funnel into a paid provider relationship).
        # update_or_create keyed on (provider, email) so a provider re-submitting
        # doesn't spawn duplicate pending rows. Only contact fields are updated —
        # tier/status are left untouched so a re-submit never resets an already
        # verified/paid provider back to pending.
        if email:
            try:
                ClaimRequest.objects.update_or_create(
                    provider=provider, contact_email=email[:254],
                    defaults={
                        'contact_name': name[:200],
                        'practice_name': (practice or provider.name)[:300],
                        'phone': phone[:30], 'role': role[:100],
                        'notes': notes[:2000],
                    },
                )
            except Exception:
                pass
        try:
            WedgeEvent.objects.create(
                event_type='claim_submit', page='claim', provider=provider,
                provider_slug=provider.slug,
                visitor_id=request.COOKIES.get('zwid', '')[:64],
            )
        except Exception:
            pass
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


@cache_page(3600)
def overcharged(request):
    from statistics import median as calc_median
    from django.db.models import Avg, Count
    from healthcare.models import Procedure, PricingRecord, Location
    
    valid_states = ['AL','AK','AZ','AR','CA','CO','CT','DE','DC','FL','GA','HI','ID','IL','IN','IA','KS','KY','LA','ME','MD','MA','MI','MN','MS','MO','MT','NE','NV','NH','NJ','NM','NY','NC','ND','OH','OK','OR','PA','RI','SC','SD','TN','TX','UT','VT','VA','WA','WV','WI','WY']
    states = valid_states
    provider_count = 186000  # pre-computed, avoids full table scan
    
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

            # Use standard pricing (same as procedure pages)
            # Filter out junk types and individuals
            junk_types = ['Mental Health', 'Chiropractor', 'Dietitian / Nutrition',
                          'Eye Care', 'Eye Center', 'Weight Loss Clinic', 'Dermatology',
                          'Allergy & Immunology', 'Physical Therapy', 'Dental Office',
                          'Podiatry', 'Audiology', 'Psychiatry', 'Sleep Medicine',
                          'Speech Pathology', 'Occupational Therapy', 'Plastic Surgery Practice',
                          'Clinical Laboratory', 'Fertility Clinic']
            pricing_qs = pricing_qs.exclude(
                provider__provider_type__name__in=junk_types
            ).exclude(provider__is_individual=True)
            comparison_note = 'standard'
            
            prices = list(pricing_qs.values_list('cash_price', flat=True))
            
            if len(prices) >= 3:
                prices_float = sorted([float(p) for p in prices])
                med = calc_median(prices_float)
                low = prices_float[int(len(prices_float) * 0.1)]
                high = prices_float[int(len(prices_float) * 0.9)]
                
                # Calculate percentile
                below = sum(1 for p in prices_float if p <= amount_val)
                percentile = min(int(below / len(prices_float) * 100), 98)
                
                # Determine verdict - four tiers
                if amount_val > med * 2:
                    verdict = 'overpaid'
                    headline = f'Review recommended: ${int(amount_val - med):,} above median'
                    context = f'Your charge of ${int(amount_val):,} is significantly above the median of ${int(med):,}. You paid more than {percentile}% of patients for this procedure. Consider requesting an itemized bill to verify charges.'
                elif amount_val > med * 1.15:
                    verdict = 'high'
                    headline = f'Higher than typical'
                    context = f'Your charge of ${int(amount_val):,} is above the median of ${int(med):,}. You paid more than {percentile}% of patients. It may be worth requesting an itemized bill to verify all charges.'
                elif amount_val < med * 0.75:
                    verdict = 'fair'
                    headline = f'Below typical, good price'
                    context = f'Your charge of ${int(amount_val):,} is below the median of ${int(med):,}. You paid less than {100 - percentile}% of patients for this procedure.'
                else:
                    verdict = 'near'
                    headline = f'Within typical range'
                    context = f'Your charge of ${int(amount_val):,} is close to the median of ${int(med):,}. This is within the typical range for this procedure.'
                
                unique_providers = pricing_qs.values('provider').distinct().count()
                
                # Typical range (25th-75th percentile)
                p25 = prices_float[len(prices_float) // 4]
                p75 = prices_float[3 * len(prices_float) // 4]

                # Ratio vs median
                ratio_vs_median = round(amount_val / med, 1) if med > 0 else 0
                pct_above_median = round((amount_val - med) / med * 100) if med > 0 else 0

                # Savings calculation
                savings_vs_median = round(amount_val - med) if amount_val > med else 0
                savings_vs_low = round(amount_val - p25) if amount_val > p25 else 0

                # Recommendation
                if verdict == 'overpaid':
                    recommendation = 'Request an itemized bill and compare with at least two other providers. Consider requesting a Good Faith Estimate for future procedures.'
                elif verdict == 'high':
                    recommendation = 'Request an itemized bill to verify all charges. Compare with nearby providers before your next visit.'
                elif verdict == 'fair':
                    recommendation = 'This is a competitive price. If you received a Good Faith Estimate beforehand, verify the final bill matches.'
                else:
                    recommendation = 'This is a fair market price. Keep this as a reference for future comparisons.'

                # Provider type breakdown for this procedure + state
                type_comparison = list(pricing_qs.values(
                    'provider__provider_type__name'
                ).annotate(
                    avg=Avg('cash_price'),
                    cnt=Count('provider_id', distinct=True),
                ).filter(cnt__gte=3).order_by('avg')[:5])

                # Find cost page link - use largest city in state
                cost_page = ''
                market_page = ''
                if selected_state:
                    from healthcare.models import Location
                    loc = Location.objects.filter(
                        state=selected_state,
                        provider__pricing_records__procedure=procedure,
                    ).annotate(
                        pc=Count('provider__pricing_records')
                    ).order_by('-pc').first()
                    if loc:
                        cost_page = f'/cost/{procedure.slug}/{loc.slug}/'
                        market_page = f'/market/{procedure.slug}/{loc.slug}/'

                result = {
                    'verdict': verdict,
                    'headline': headline,
                    'you_paid': f'{int(amount_val):,}',
                    'median': f'{int(med):,}',
                    'low': f'{int(low):,}',
                    'high': f'{int(high):,}',
                    'typical_low': f'{int(p25):,}',
                    'typical_high': f'{int(p75):,}',
                    'percentile': percentile,
                    'context': context,
                    'recommendation': recommendation,
                    'cost_page': cost_page,
                    'sample_size': f'{len(prices):,}',
                    'provider_count': f'{unique_providers:,}',
                    'state': selected_state,
                    'savings_vs_median': f'{savings_vs_median:,}' if savings_vs_median > 0 else '',
                    'savings_vs_low': f'{savings_vs_low:,}' if savings_vs_low > 0 else '',
                    'ratio_vs_median': ratio_vs_median,
                    'pct_above_median': pct_above_median,
                    'type_comparison': type_comparison,
                    'comparison_note': comparison_note,
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


def guide_good_faith_estimate(request):
    return render(request, 'healthcare/guide_good_faith_estimate.html')


def guide_facility_fee(request):
    return render(request, 'healthcare/guide_facility_fee.html')


def guides_index(request):
    return render(request, 'healthcare/guides_index.html')


def guide_price_variance(request):
    return render(request, 'healthcare/guide_price_variance.html')
