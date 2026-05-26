from django.contrib import admin

# Register your models here.


from .models import ClaimRequest

@admin.register(ClaimRequest)
class ClaimRequestAdmin(admin.ModelAdmin):
    list_display = ['provider', 'contact_name', 'contact_email', 'phone', 'status', 'created_at']
    list_filter = ['status', 'created_at']
    readonly_fields = ['created_at']
