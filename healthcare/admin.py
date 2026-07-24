from django.contrib import admin

# Register your models here.


from .models import ClaimRequest, ConsumerLead, PriceAlertSignup, WedgeEvent

@admin.register(ClaimRequest)
class ClaimRequestAdmin(admin.ModelAdmin):
    list_display = ['provider', 'contact_name', 'contact_email', 'phone', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    readonly_fields = ['created_at']


@admin.register(ConsumerLead)
class ConsumerLeadAdmin(admin.ModelAdmin):
    list_display = ['contact_name', 'contact_email', 'provider_name', 'variant_interest',
                    'source_page', 'procedure_slug', 'city_slug', 'status', 'created_at']
    list_filter = ['status', 'source_page', 'procedure_slug', 'city_slug', 'created_at']
    search_fields = ['contact_name', 'contact_email', 'provider_name']
    readonly_fields = ['created_at', 'visitor_id']
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
    date_hierarchy = 'created_at'
