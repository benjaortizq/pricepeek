from django.contrib import admin

from .models import Incident


@admin.register(Incident)
class IncidentAdmin(admin.ModelAdmin):
    list_display = ("created_at", "kind", "store_name", "product_name", "gtin")
    list_filter = ("kind", "store_name")
    search_fields = ("product_name", "gtin", "store_name")
