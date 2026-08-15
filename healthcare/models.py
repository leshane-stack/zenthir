from django.db import models

from .price_basis import BASIS_CHOICES as PRICE_BASIS_CHOICES


class Vertical(models.Model):
    """Healthcare vertical — plastic surgery, dental, fertility, etc."""
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    description = models.TextField(blank=True)
    tier = models.IntegerField(default=1, help_text="Launch tier: 1=launch, 2=fast follow, 3=expansion, 4=long-term")
    sort_order = models.IntegerField(default=0)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['sort_order']


class Location(models.Model):
    """City/metro area for geographic pricing comparison."""
    city = models.CharField(max_length=200)
    state = models.CharField(max_length=2)
    state_full = models.CharField(max_length=100, blank=True)
    metro_area = models.CharField(max_length=200, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    population = models.IntegerField(null=True, blank=True)
    slug = models.SlugField(unique=True)

    def __str__(self):
        return f"{self.city}, {self.state}"

    class Meta:
        ordering = ['state', 'city']


class ProviderType(models.Model):
    """Type of provider — hospital, clinic, private practice, imaging center, etc."""
    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)

    def __str__(self):
        return self.name


class Provider(models.Model):
    """Healthcare provider — hospital, clinic, surgeon, dentist, etc."""
    name = models.CharField(max_length=500)
    slug = models.SlugField(max_length=200, unique=True)
    legal_name = models.CharField(max_length=500, blank=True)
    provider_type = models.ForeignKey(ProviderType, on_delete=models.SET_NULL, null=True, blank=True)
    verticals = models.ManyToManyField(Vertical, blank=True)
    location = models.ForeignKey(Location, on_delete=models.SET_NULL, null=True, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=20, blank=True)
    website = models.URLField(blank=True)
    
    # Verification and credentials
    npi_number = models.CharField(max_length=20, blank=True, help_text="National Provider Identifier")
    license_number = models.CharField(max_length=100, blank=True)
    license_state = models.CharField(max_length=2, blank=True)
    license_status = models.CharField(max_length=50, blank=True)
    license_verified_date = models.DateField(null=True, blank=True)
    board_certified = models.BooleanField(null=True)
    accreditation = models.CharField(max_length=200, blank=True, help_text="AAAHC, Joint Commission, etc.")
    
    # Institutional intelligence
    ownership_type = models.CharField(
        max_length=50, blank=True,
        choices=[
            ('independent', 'Independent'),
            ('hospital_system', 'Hospital System'),
            ('private_equity', 'Private Equity Owned'),
            ('physician_group', 'Physician Group'),
            ('nonprofit', 'Nonprofit'),
            ('government', 'Government'),
            ('franchise', 'Franchise'),
        ]
    )
    parent_organization = models.CharField(max_length=500, blank=True)
    pe_firm = models.CharField(max_length=300, blank=True, help_text="Private equity firm if applicable")
    
    # Quality
    cms_star_rating = models.DecimalField(max_digits=2, decimal_places=1, null=True, blank=True)
    patient_satisfaction_score = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    
    # Metadata
    employee_count = models.IntegerField(null=True, blank=True)
    year_established = models.IntegerField(null=True, blank=True)
    beds = models.IntegerField(null=True, blank=True, help_text="For hospitals")
    
    # Transparency
    transparency_compliant = models.BooleanField(null=True, help_text="CMS price transparency compliance")
    transparency_score = models.IntegerField(null=True, blank=True, help_text="0-100")
    is_individual = models.BooleanField(default=False)
    
    # Summary
    description = models.TextField(blank=True)
    summary_line = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class Procedure(models.Model):
    """Medical procedure — MRI, rhinoplasty, dental implant, etc."""
    name = models.CharField(max_length=500)
    slug = models.SlugField(unique=True)
    display_name = models.CharField(max_length=200, blank=True, default='')
    description = models.TextField(blank=True)
    verticals = models.ManyToManyField(Vertical, blank=True)
    
    # Coding
    cpt_code = models.CharField(max_length=20, blank=True, help_text="CPT code")
    hcpcs_code = models.CharField(max_length=20, blank=True)
    drg_code = models.CharField(max_length=20, blank=True)
    
    # Classification
    category = models.CharField(max_length=200, blank=True, help_text="Imaging, Surgery, Dental, etc.")
    subcategory = models.CharField(max_length=200, blank=True)
    is_elective = models.BooleanField(default=False)
    is_cash_pay_common = models.BooleanField(default=False)
    
    # Typical pricing context
    national_average_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    national_median_cost = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    national_median = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    national_p25 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    national_p75 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    national_p5 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    national_p95 = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    national_avg = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    national_avg_medicare = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    national_provider_count = models.IntegerField(null=True, blank=True)
    national_record_count = models.IntegerField(null=True, blank=True)
    by_type_json = models.TextField(null=True, blank=True)
    top_cities_json = models.TextField(null=True, blank=True)
    cost_range_low = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    cost_range_high = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # SEO
    search_volume_estimate = models.IntegerField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']


class PricingRecord(models.Model):
    """A specific price for a specific procedure at a specific provider."""
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='pricing_records')
    procedure = models.ForeignKey(Procedure, on_delete=models.CASCADE, related_name='pricing_records')
    
    # Pricing
    cash_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    insured_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    chargemaster_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    negotiated_rate = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    insurer_name = models.CharField(max_length=200, blank=True, help_text="For negotiated rates")
    
    # Context
    price_type = models.CharField(
        max_length=30,
        choices=[
            ('cms_published', 'CMS Published'),
            ('provider_website', 'Provider Website'),
            ('crowdsourced', 'Crowdsourced'),
            ('estimated', 'Estimated'),
            ('negotiated', 'Negotiated Rate'),
        ],
        default='estimated'
    )
    
    # Data confidence
    confidence = models.CharField(
        max_length=20,
        choices=[
            ('high', 'High — CMS or verified source'),
            ('medium', 'Medium — provider website or aggregator'),
            ('low', 'Low — estimated or crowdsourced'),
        ],
        default='medium'
    )
    
    # Comparison
    percentile_rank = models.IntegerField(null=True, blank=True, help_text="Price percentile vs regional peers")
    vs_regional_median = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, 
        help_text="Multiplier vs regional median. 1.0 = average, 2.0 = 2x median")
    
    # Source
    source_url = models.URLField(blank=True)
    price_category = models.CharField(
        max_length=30,
        choices=[
            ('submitted_charge', 'Submitted Charge'),
            ('negotiated_rate', 'Negotiated Rate'),
            ('gross_charge', 'Gross Charge'),
            ('cash_price', 'Cash Price'),
            ('medicare_rate', 'Medicare Rate'),
        ],
        default='submitted_charge',
        blank=True,
        null=True,
    )
    billing_component = models.CharField(
        max_length=20,
        choices=[
            ('professional', 'Professional'),
            ('technical', 'Technical/Facility'),
            ('global', 'Global (Both)'),
        ],
        blank=True,
        null=True,
    )
    source_name = models.CharField(max_length=200, blank=True)
    # What cash_price actually represents (mapped from source_name; see
    # price_basis.py). Aggregations filter on THIS, never on source_name or the
    # meaningless price_category default. NULL until backfilled.
    price_basis = models.CharField(
        max_length=20, choices=PRICE_BASIS_CHOICES, null=True, blank=True)
    last_verified = models.DateField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.provider.name} — {self.procedure.name}: ${self.cash_price}"

    class Meta:
        ordering = ['-updated_at']


class DataSource(models.Model):
    """Tracks data sources used for a provider's information."""
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='data_sources')
    source_name = models.CharField(max_length=200)
    source_type = models.CharField(
        max_length=30,
        choices=[
            ('cms_mrf', 'CMS Machine-Readable File'),
            ('cms_quality', 'CMS Quality Data'),
            ('state_board', 'State Medical/Dental Board'),
            ('court_records', 'Court Records'),
            ('provider_website', 'Provider Website'),
            ('review_platform', 'Review Platform'),
            ('user_submitted', 'User Submitted'),
        ]
    )
    source_url = models.URLField(blank=True)
    last_checked = models.DateField()
    
    def __str__(self):
        return f"{self.provider.name} — {self.source_name}"


class SafetyEvent(models.Model):
    """Safety events, malpractice, sanctions, disciplinary actions."""
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='safety_events')
    
    date = models.DateField()
    title = models.CharField(max_length=500)
    description = models.TextField()
    
    event_type = models.CharField(
        max_length=30,
        choices=[
            ('malpractice', 'Malpractice Action'),
            ('sanction', 'Sanction/Disciplinary'),
            ('license_action', 'License Action'),
            ('inspection_failure', 'Inspection Failure'),
            ('patient_death', 'Patient Death Report'),
            ('fda_warning', 'FDA Warning'),
            ('safety_violation', 'Safety Violation'),
            ('lawsuit', 'Lawsuit'),
        ]
    )
    severity = models.CharField(
        max_length=20,
        choices=[
            ('critical', 'Critical'),
            ('serious', 'Serious'),
            ('moderate', 'Moderate'),
            ('minor', 'Minor'),
        ]
    )
    
    source_agency = models.CharField(max_length=200, blank=True)
    source_url = models.URLField(blank=True)
    penalty_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.date} — {self.provider.name} — {self.title}"

    class Meta:
        ordering = ['-date']


class InsuranceAcceptance(models.Model):
    """Which insurance plans a provider accepts."""
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='insurance_acceptance')
    insurer_name = models.CharField(max_length=200)
    plan_name = models.CharField(max_length=200, blank=True)
    in_network = models.BooleanField(default=True)
    verified_date = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.provider.name} — {self.insurer_name}"

    class Meta:
        unique_together = ['provider', 'insurer_name', 'plan_name']


class ClaimRequest(models.Model):
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='claim_requests')
    contact_name = models.CharField(max_length=200)
    contact_email = models.EmailField()
    practice_name = models.CharField(max_length=300)
    phone = models.CharField(max_length=30)
    role = models.CharField(max_length=100)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default='pending', choices=[
        ('pending', 'Pending'),
        ('verified', 'Verified'),
        ('rejected', 'Rejected'),
    ])

    # --- Provider tier + billing (stored here, NOT on the 2.9M-row Provider) ---
    # Only claimed providers ever get a row, so this table stays small + indexed
    # on the provider FK. `tier` is the source of truth for features/leads:
    #   pending  -> claim submitted, awaiting verification
    #   verified -> approved, free; consumer lead capture is active (the hook)
    #   paid_basic / paid_premium -> paid subscription (enhanced features)
    TIER_CHOICES = [
        ('pending', 'Pending'),
        ('verified', 'Verified (free)'),
        ('paid_basic', 'Paid — Featured'),
        ('paid_premium', 'Paid — Premium'),
    ]
    tier = models.CharField(max_length=20, default='pending', choices=TIER_CHOICES)
    stripe_customer_id = models.CharField(max_length=64, blank=True, null=True)
    stripe_subscription_id = models.CharField(max_length=64, blank=True, null=True)
    tier_updated_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Claim: {self.provider.name} by {self.contact_name} ({self.tier})"


class PriceSnapshot(models.Model):
    """Historical price record — never deleted, never overwritten."""
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='price_snapshots')
    procedure = models.ForeignKey(Procedure, on_delete=models.CASCADE, related_name='price_snapshots')
    cash_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    insured_price = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    price_type = models.CharField(max_length=30, default='published')
    source_name = models.CharField(max_length=300, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recorded_at']
        indexes = [
            models.Index(fields=['provider', 'procedure', 'recorded_at']),
        ]

    def __str__(self):
        return f"{self.provider.name} - {self.procedure.name} - ${self.cash_price} ({self.recorded_at.date()})"


class ProviderSnapshot(models.Model):
    """Track provider metadata changes over time."""
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='metadata_snapshots')
    field_name = models.CharField(max_length=100)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    source = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ['-changed_at']
        indexes = [
            models.Index(fields=['provider', 'changed_at']),
            models.Index(fields=['field_name', 'changed_at']),
        ]

    def __str__(self):
        return f"{self.provider.name} - {self.field_name} changed ({self.changed_at.date()})"


class ProcedureMedian(models.Model):
    """Pre-computed regional median prices. Updated nightly."""
    procedure = models.ForeignKey(Procedure, on_delete=models.CASCADE, related_name='medians')
    location = models.ForeignKey(Location, on_delete=models.CASCADE, related_name='procedure_medians')
    provider_type = models.ForeignKey(ProviderType, on_delete=models.CASCADE, related_name='procedure_medians')
    median_price = models.DecimalField(max_digits=12, decimal_places=2)
    p25 = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    p75 = models.DecimalField(max_digits=12, decimal_places=2, null=True)
    provider_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['procedure', 'location', 'provider_type']
        indexes = [
            models.Index(fields=['procedure', 'location', 'provider_type']),
        ]

    def __str__(self):
        return f"{self.procedure.name} - {self.location.city} - {self.provider_type.name}: ${self.median_price}"


# ---------------------------------------------------------------------------
# Test-wedge models (Botox / Miami consumer-lead experiment)
#
# Scope: one wedge only. These capture the billable event (a consumer lead),
# the consumer email list, and lightweight funnel instrumentation. Provider
# claims reuse the existing ClaimRequest model. Kept generic (procedure_slug /
# city_slug string fields) so the wedge is measurable without hard-coding, but
# only the Botox/Miami pages populate them today.
# ---------------------------------------------------------------------------

class ConsumerLead(models.Model):
    """A shopper asking for a price / to be connected to a provider.

    This is the billable event: contact details + the specific provider they
    are interested in. This is what we sell to medspas.
    """
    procedure_slug = models.CharField(max_length=100, default='botox')
    city_slug = models.CharField(max_length=100, default='miami-fl')
    provider = models.ForeignKey(
        Provider, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='consumer_leads',
    )
    provider_name = models.CharField(max_length=500, blank=True,
        help_text="Denormalized snapshot of the provider name at lead time.")
    contact_name = models.CharField(max_length=200)
    contact_email = models.EmailField()
    contact_phone = models.CharField(max_length=40, blank=True)
    variant_interest = models.CharField(max_length=200, blank=True,
        help_text="Which Botox variant / area the shopper asked about.")
    message = models.TextField(blank=True)
    source_page = models.CharField(max_length=40, blank=True,
        help_text="hub | cheapest | provider")
    visitor_id = models.CharField(max_length=64, blank=True,
        help_text="First-party anonymous cookie id, for funnel attribution.")
    created_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, default='new', choices=[
        ('new', 'New'),
        ('contacted', 'Contacted'),
        ('sold', 'Sold to provider'),
        ('spam', 'Spam'),
    ])

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['procedure_slug', 'city_slug', 'created_at']),
            models.Index(fields=['provider', 'created_at']),
        ]

    def __str__(self):
        return f"Lead: {self.contact_name} -> {self.provider_name or 'any provider'} ({self.procedure_slug}/{self.city_slug})"


class PriceAlertSignup(models.Model):
    """Consumer email capture — 'notify me if prices drop in this market'."""
    email = models.EmailField()
    procedure_slug = models.CharField(max_length=100, default='botox')
    city_slug = models.CharField(max_length=100, default='miami-fl')
    source_page = models.CharField(max_length=40, blank=True)
    visitor_id = models.CharField(max_length=64, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        unique_together = ['email', 'procedure_slug', 'city_slug']

    def __str__(self):
        return f"Alert: {self.email} ({self.procedure_slug}/{self.city_slug})"


class WedgeEvent(models.Model):
    """Lightweight funnel instrumentation for the test wedge.

    Rows are read to compute page visits, email signups, lead clicks, and
    provider claims — and consumer-to-lead conversion by visitor_id.
    """
    EVENT_TYPES = [
        ('page_view', 'Page View'),
        ('lead_open', 'Lead Form Opened'),
        ('lead_submit', 'Lead Submitted'),
        ('email_signup', 'Email Signup'),
        ('claim_click', 'Claim Clicked'),
        ('claim_submit', 'Claim Submitted'),
        ('provider_click', 'Provider Clicked'),
        ('phone_click', 'Phone Clicked'),
        ('website_click', 'Website Clicked'),
    ]
    event_type = models.CharField(max_length=30, choices=EVENT_TYPES)
    page = models.CharField(max_length=40, blank=True, help_text="hub | cheapest | provider")
    procedure_slug = models.CharField(max_length=100, blank=True)
    city_slug = models.CharField(max_length=100, blank=True)
    provider = models.ForeignKey(
        Provider, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='wedge_events',
    )
    provider_slug = models.CharField(max_length=200, blank=True)
    visitor_id = models.CharField(max_length=64, blank=True)
    referrer = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_type', 'created_at']),
            models.Index(fields=['procedure_slug', 'city_slug', 'event_type']),
            models.Index(fields=['visitor_id', 'event_type']),
        ]

    def __str__(self):
        return f"{self.event_type} {self.page} @ {self.created_at:%Y-%m-%d %H:%M}"


# ---------------------------------------------------------------------------
# Provider enrichment — structured data powering Price Context, the
# completeness meter, and (later) provider self-service. Admin-managed for now;
# NO consumer-facing write path yet. New tables, so no migration data risk.
# ---------------------------------------------------------------------------

class ProviderProcedureDetail(models.Model):
    """Structured pricing context for one provider + procedure pair.

    Booleans are null=True on purpose: NULL means "unknown / not stated" and is
    rendered as absence (not a ✗). Only True/meaningful-False surface on the
    public page.
    """
    TURNAROUND_CHOICES = [
        ('same_day', 'Same day'),
        ('24_hours', '24 hours'),
        ('48_hours', '48 hours'),
        ('3_5_days', '3–5 days'),
        ('1_week', '1 week'),
    ]
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='procedure_details')
    procedure = models.ForeignKey(Procedure, on_delete=models.CASCADE, related_name='provider_details')

    includes_consultation = models.BooleanField(null=True, blank=True)
    includes_interpretation = models.BooleanField(null=True, blank=True)
    includes_facility_fee = models.BooleanField(null=True, blank=True)
    includes_anesthesia = models.BooleanField(null=True, blank=True)
    includes_followup = models.BooleanField(null=True, blank=True)
    financing_available = models.BooleanField(null=True, blank=True)
    turnaround = models.CharField(max_length=20, choices=TURNAROUND_CHOICES, null=True, blank=True)
    self_pay_discount = models.BooleanField(null=True, blank=True)
    price_guaranteed = models.BooleanField(null=True, blank=True)
    good_faith_estimate_available = models.BooleanField(null=True, blank=True)
    provider_notes = models.TextField(blank=True, help_text='"About your pricing" — free text')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['provider', 'procedure']
        indexes = [models.Index(fields=['provider'])]

    def __str__(self):
        return f"{self.provider.name} — {self.procedure.name} (detail)"


class ProviderProfile(models.Model):
    """Provider-level enrichment (one per provider). Image fields are URLs only
    for now — no file upload."""
    provider = models.OneToOneField(Provider, on_delete=models.CASCADE, related_name='profile')

    logo = models.URLField(blank=True, help_text='URL to logo image (no upload yet)')
    cover_image = models.URLField(blank=True)
    description = models.TextField(blank=True, help_text='"About your pricing" — one paragraph')

    payment_cash = models.BooleanField(default=False)
    payment_credit = models.BooleanField(default=False)
    payment_hsa = models.BooleanField(default=False)
    payment_fsa = models.BooleanField(default=False)
    payment_carecredit = models.BooleanField(default=False)
    payment_other = models.CharField(max_length=200, blank=True)

    financing_available = models.BooleanField(default=False)
    financing_details = models.CharField(max_length=300, blank=True)

    languages = models.CharField(max_length=200, blank=True, help_text='Comma-separated')
    equipment_notes = models.CharField(max_length=300, blank=True, help_text='e.g. "3T MRI, Open MRI"')
    preparation_instructions = models.TextField(blank=True)
    hours_json = models.TextField(blank=True, help_text='JSON string for hours')

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Profile: {self.provider.name}"


# ---------------------------------------------------------------------------
# Observed provider-published prices (measurement layer).
# Deliberately separate from PricingRecord: this table holds only prices that
# were actually observed on a provider's own site, with full provenance.
# Never written by the fabrication seeders; never read by live pages (yet).
# ---------------------------------------------------------------------------
class ObservedPrice(models.Model):
    """One observed, provider-published price. Append-only.

    The required fields (and the CheckConstraints below) make it structurally
    impossible to store a price without knowing where it came from, how it was
    read, and when. A changed price on a later run creates a NEW row — rows are
    never overwritten.
    """
    PRICE_BASIS = [
        ('per_unit', 'Per unit'),
        ('per_area', 'Per treatment area'),
        ('package', 'Package'),
        ('per_treatment', 'Per treatment'),
        ('other', 'Other'),
    ]
    PRICE_TYPE = [
        ('standard', 'Standard'),
        ('introductory', 'Introductory'),
        ('promotional', 'Promotional'),
        ('member', 'Member'),
        ('unknown', 'Unknown'),
    ]
    EXTRACTION_METHOD = [
        ('text', 'HTML text'),
        ('booking_widget', 'Booking widget'),
        ('pdf', 'PDF'),
        ('image_ocr', 'Image OCR'),
        ('manual', 'Manual'),
    ]

    # --- Required: no price without provenance ---
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='observed_prices')
    procedure = models.ForeignKey(Procedure, on_delete=models.CASCADE, related_name='observed_prices')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    currency = models.CharField(max_length=3, default='USD')
    price_basis = models.CharField(max_length=20, choices=PRICE_BASIS)
    price_type = models.CharField(max_length=20, choices=PRICE_TYPE)
    source_url = models.TextField()
    raw_snippet = models.TextField(help_text='Verbatim text the price was read from.')
    observed_at = models.DateTimeField(help_text='When this observation was made.')
    extraction_method = models.CharField(max_length=20, choices=EXTRACTION_METHOD)

    # --- Optional qualifiers ---
    minimum_units = models.IntegerField(null=True, blank=True)
    package_quantity = models.IntegerField(null=True, blank=True)
    package_description = models.CharField(max_length=300, null=True, blank=True)
    promotional_text = models.TextField(null=True, blank=True)
    membership_required = models.BooleanField(null=True, blank=True)
    first_visit_only = models.BooleanField(null=True, blank=True)
    effective_start = models.DateField(null=True, blank=True)
    effective_end = models.DateField(null=True, blank=True)
    confidence = models.CharField(max_length=20, null=True, blank=True,
        choices=[('high', 'High'), ('medium', 'Medium'), ('low', 'Low')])

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-observed_at']
        indexes = [models.Index(fields=['provider', 'procedure', 'observed_at'])]
        constraints = [
            # Empty strings must not satisfy the "provenance is required" rule.
            models.CheckConstraint(condition=~models.Q(source_url=''), name='obsprice_source_url_present'),
            models.CheckConstraint(condition=~models.Q(raw_snippet=''), name='obsprice_raw_snippet_present'),
            models.CheckConstraint(condition=~models.Q(price_basis=''), name='obsprice_basis_present'),
            models.CheckConstraint(condition=~models.Q(price_type=''), name='obsprice_type_present'),
            models.CheckConstraint(condition=~models.Q(currency=''), name='obsprice_currency_present'),
            models.CheckConstraint(condition=~models.Q(extraction_method=''), name='obsprice_method_present'),
        ]

    def __str__(self):
        return f"{self.provider_id}/{self.procedure_id}: {self.price} {self.currency} ({self.price_basis},{self.price_type})"


class PriceAvailability(models.Model):
    """One row per provider+procedure: the state of that provider's public
    pricing. Updated in place on re-run (this is current state, not an
    observation). `no_price_found` != `consult_only`: the latter is set ONLY
    when the provider affirmatively states price is discussed at consult; when
    uncertain, use `no_price_found`.
    """
    STATES = [
        ('text_price', 'Text price found on page'),
        ('booking_widget_price', 'Price only inside a booking widget'),
        ('image_or_pdf_price', 'Price only in an image or PDF'),
        ('consult_only', 'Provider states price is discussed at consult'),
        ('membership_gated', 'Price gated behind membership'),
        ('no_price_found', 'No price found / not fully traversed'),
        ('not_reachable', 'Site could not be reached'),
    ]
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='price_availability')
    procedure = models.ForeignKey(Procedure, on_delete=models.CASCADE, related_name='price_availability')
    state = models.CharField(max_length=30, choices=STATES)
    source_url = models.TextField(blank=True, help_text='Page that determined the state, if any.')
    pages_checked = models.IntegerField(default=0)
    detail = models.TextField(blank=True, help_text='Which pages were checked / why this state.')
    last_checked = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['provider', 'procedure'], name='priceavail_unique_provider_proc'),
        ]

    def __str__(self):
        return f"{self.provider_id}/{self.procedure_id}: {self.state}"


class PriceReviewItem(models.Model):
    """Manual-review queue. Anything ambiguous lands here WITH its snippet and
    URL. The collector never guesses, infers, or fills — it enqueues instead.
    """
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='price_review_items')
    procedure = models.ForeignKey(Procedure, on_delete=models.SET_NULL, null=True, blank=True,
                                  related_name='price_review_items')
    source_url = models.TextField()
    raw_snippet = models.TextField()
    reason = models.CharField(max_length=200)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.CheckConstraint(condition=~models.Q(source_url=''), name='reviewitem_source_url_present'),
            models.CheckConstraint(condition=~models.Q(raw_snippet=''), name='reviewitem_raw_snippet_present'),
            models.CheckConstraint(condition=~models.Q(reason=''), name='reviewitem_reason_present'),
        ]

    def __str__(self):
        return f"REVIEW {self.provider_id}: {self.reason}"


# ---------------------------------------------------------------------------
# Places business capture + site-scan provenance (measurement layer).
# Local-only ingest for the Miami med-spa coverage expansion. Never on live
# pages. Facts captured verbatim from Google Places; missing stays NULL.
# ---------------------------------------------------------------------------
class PlacesListing(models.Model):
    """One row per Provider ingested from Google Places (business, not NPI)."""
    provider = models.OneToOneField(Provider, on_delete=models.CASCADE, related_name='places_listing')
    place_id = models.CharField(max_length=200, unique=True)
    national_phone = models.CharField(max_length=40, blank=True)
    website_uri = models.TextField(blank=True)
    business_status = models.CharField(max_length=30, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    neighborhood = models.CharField(max_length=80, blank=True)
    city = models.CharField(max_length=80, blank=True)
    primary_type = models.CharField(max_length=80, blank=True)
    primary_type_display = models.CharField(max_length=120, blank=True)
    place_types = models.JSONField(default=list, blank=True)
    opening_hours = models.JSONField(null=True, blank=True)
    photo_refs = models.JSONField(default=list, blank=True)   # references only, not images
    rating = models.DecimalField(max_digits=2, decimal_places=1, null=True, blank=True)
    user_rating_count = models.IntegerField(null=True, blank=True)
    # NOTE: individual review TEXT is deliberately NOT stored. When rating/count
    # is displayed, attribution "Google / <source>" must accompany it.
    rating_attribution = models.CharField(max_length=120, default='Google', blank=True)
    discovery_query = models.CharField(max_length=200, blank=True, help_text='Sweep query that surfaced this business.')
    fetched_at = models.DateTimeField()

    def __str__(self):
        return f"PlacesListing {self.provider_id}: {self.place_id}"


class SiteScan(models.Model):
    """Per-provider capture derived from crawling the practice's own website."""
    provider = models.OneToOneField(Provider, on_delete=models.CASCADE, related_name='site_scan')
    booking_platform = models.CharField(max_length=60, blank=True)
    membership_present = models.BooleanField(null=True, blank=True)
    financing_offered = models.JSONField(default=list, blank=True)   # e.g. ["CareCredit","Cherry"]
    named_injectors = models.JSONField(default=list, blank=True)
    social_links = models.JSONField(default=dict, blank=True)
    pages_fetched = models.IntegerField(default=0)
    boulevard_business = models.CharField(max_length=120, blank=True)
    scanned_at = models.DateTimeField()
    notes = models.TextField(blank=True)

    def __str__(self):
        return f"SiteScan {self.provider_id}"


class PageSnapshot(models.Model):
    """Archived baseline of every page fetched: content hash + on-disk snapshot.
    Enables change detection and evidence for a disputed price."""
    provider = models.ForeignKey(Provider, on_delete=models.CASCADE, related_name='page_snapshots')
    url = models.TextField()
    http_status = models.IntegerField(null=True, blank=True)
    content_hash = models.CharField(max_length=64, db_index=True)   # sha256 of normalized text
    snapshot_path = models.TextField(blank=True)
    fetched_at = models.DateTimeField()

    class Meta:
        indexes = [models.Index(fields=['provider', 'content_hash'])]

    def __str__(self):
        return f"Snapshot {self.provider_id}: {self.url[:50]}"
