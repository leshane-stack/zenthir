from django.contrib import admin
from django.utils import timezone

# Register your models here.


from .models import ClaimRequest, ConsumerLead, PriceAlertSignup, WedgeEvent
from .tiers import clear_provider_cache


@admin.register(ClaimRequest)
class ClaimRequestAdmin(admin.ModelAdmin):
    list_display = ['provider', 'contact_name', 'contact_email', 'phone',
                    'status', 'tier', 'tier_updated_at', 'created_at']
    list_filter = ['status', 'tier', 'created_at']
    readonly_fields = ['created_at', 'tier_updated_at',
                       'stripe_customer_id', 'stripe_subscription_id']
    search_fields = ['provider__name', 'contact_name', 'contact_email', 'practice_name']
    # Provider has ~2.9M rows. Rendering it as a <select> on the add/change form
    # enumerates every row and OOM-kills the worker (SIGKILL), which also starves
    # the changelist and blocks the actions below. raw_id_fields renders a plain
    # id input + lookup popup instead — no enumeration. list_select_related keeps
    # the changelist's provider column to one JOIN instead of N+1.
    raw_id_fields = ['provider']
    list_select_related = ['provider']
    actions = ['approve_claims', 'reject_claims']

    @admin.action(description="Approve — verify (free tier, activates leads)")
    def approve_claims(self, request, queryset):
        n = 0
        for claim in queryset:
            # Never downgrade a provider who has already paid.
            if claim.tier in ('paid_basic', 'paid_premium'):
                continue
            claim.status = 'verified'
            claim.tier = 'verified'
            claim.tier_updated_at = timezone.now()
            claim.save(update_fields=['status', 'tier', 'tier_updated_at'])
            clear_provider_cache(claim.provider.slug)
            n += 1
        self.message_user(request, f"Verified {n} claim(s). Consumer leads are now active for them.")

    @admin.action(description="Reject claim")
    def reject_claims(self, request, queryset):
        n = 0
        for claim in queryset:
            claim.status = 'rejected'
            claim.tier = 'pending'
            claim.tier_updated_at = timezone.now()
            claim.save(update_fields=['status', 'tier', 'tier_updated_at'])
            clear_provider_cache(claim.provider.slug)
            n += 1
        self.message_user(request, f"Rejected {n} claim(s).")


@admin.register(ConsumerLead)
class ConsumerLeadAdmin(admin.ModelAdmin):
    list_display = ['contact_name', 'contact_email', 'provider_name', 'variant_interest',
                    'source_page', 'procedure_slug', 'city_slug', 'status', 'created_at']
    list_filter = ['status', 'source_page', 'procedure_slug', 'city_slug', 'created_at']
    search_fields = ['contact_name', 'contact_email', 'provider_name']
    readonly_fields = ['created_at', 'visitor_id']
    # Same 2.9M-row Provider FK -> raw_id to avoid OOM on the change form.
    raw_id_fields = ['provider']
    date_hierarchy = 'created_at'


@admin.register(PriceAlertSignup)
class PriceAlertSignupAdmin(admin.ModelAdmin):
    list_display = ['email', 'procedure_slug', 'city_slug', 'source_page', 'created_at']
    list_filter = ['procedure_slug', 'city_slug', 'source_page', 'created_at']
    search_fields = ['email']
    readonly_fields = ['created_at', 'visitor_id']
    date_hierarchy = 'created_at'


@admin.register(WedgeEvent)
class WedgeEventAdmin(admin.ModelAdmin):
    list_display = ['event_type', 'page', 'procedure_slug', 'city_slug',
                    'provider_slug', 'visitor_id', 'created_at']
    list_filter = ['event_type', 'page', 'procedure_slug', 'city_slug', 'created_at']
    search_fields = ['provider_slug', 'visitor_id']
    readonly_fields = ['created_at']
    # Same 2.9M-row Provider FK -> raw_id to avoid OOM on the change form.
    raw_id_fields = ['provider']
    date_hierarchy = 'created_at'
