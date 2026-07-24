from django.db import models


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

    def __str__(self):
        return f"Claim: {self.provider.name} by {self.contact_name}"


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
